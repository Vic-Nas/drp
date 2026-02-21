"""
Tests for core/models.py — Drop model behaviour.

Covers: is_expired(), touch() debounce, hard_delete() B2 cleanup + storage accounting.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Drop, Plan, UserProfile
from .helpers import make_user, make_drop, make_file_drop


# ─────────────────────────────────────────────────────────────────────────────
# Drop.is_expired()
# ─────────────────────────────────────────────────────────────────────────────

class DropExpiryTests(TestCase):
    """Expiry logic is non-trivial; wrong results silently expose or delete data."""

    def _drop(self, **kwargs):
        defaults = dict(ns=Drop.NS_CLIPBOARD, key="x", kind=Drop.TEXT)
        defaults.update(kwargs)
        return Drop(**defaults)

    def test_explicit_expires_at_in_past(self):
        d = self._drop(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(d.is_expired())

    def test_explicit_expires_at_in_future(self):
        d = self._drop(expires_at=timezone.now() + timedelta(days=1))
        self.assertFalse(d.is_expired())

    def test_max_lifetime_exceeded(self):
        d = self._drop(
            created_at=timezone.now() - timedelta(seconds=100),
            max_lifetime_secs=50,
        )
        d.created_at = timezone.now() - timedelta(seconds=100)
        self.assertTrue(d.is_expired())

    def test_clipboard_idle_anon_expires_after_24h(self):
        d = self._drop(
            owner=None,
            last_accessed_at=timezone.now() - timedelta(hours=25),
        )
        d.created_at = timezone.now() - timedelta(hours=25)
        self.assertTrue(d.is_expired())

    def test_clipboard_idle_anon_not_expired_under_24h(self):
        d = self._drop(
            owner=None,
            last_accessed_at=timezone.now() - timedelta(hours=23),
        )
        d.created_at = timezone.now() - timedelta(hours=23)
        self.assertFalse(d.is_expired())

    def test_file_drop_not_expired_under_90_days(self):
        d = self._drop(ns=Drop.NS_FILE, kind=Drop.FILE)
        d.created_at = timezone.now() - timedelta(days=89)
        self.assertFalse(d.is_expired())

    def test_file_drop_expired_after_90_days(self):
        d = self._drop(ns=Drop.NS_FILE, kind=Drop.FILE)
        d.created_at = timezone.now() - timedelta(days=91)
        self.assertTrue(d.is_expired())


# ─────────────────────────────────────────────────────────────────────────────
# Drop.touch() — debounce
# ─────────────────────────────────────────────────────────────────────────────

class DropTouchTests(TestCase):
    """touch() must skip the DB write within the debounce window.
    Without this every GET on a hot drop writes to the DB."""

    def setUp(self):
        self.user = User.objects.create_user("u", password="pw")
        self.drop = Drop.objects.create(
            ns=Drop.NS_CLIPBOARD, key="touch-test", kind=Drop.TEXT,
            owner=self.user,
        )

    def test_touch_writes_when_never_accessed(self):
        self.assertIsNone(self.drop.last_accessed_at)
        self.drop.touch()
        self.drop.refresh_from_db()
        self.assertIsNotNone(self.drop.last_accessed_at)

    def test_touch_skips_write_within_debounce(self):
        recent = timezone.now() - timedelta(seconds=60)
        Drop.objects.filter(pk=self.drop.pk).update(last_accessed_at=recent)
        self.drop.last_accessed_at = recent

        self.drop.touch()

        self.drop.refresh_from_db()
        self.assertAlmostEqual(
            self.drop.last_accessed_at.timestamp(),
            recent.timestamp(),
            delta=2,
            msg="touch() wrote to the DB within the debounce window",
        )

    def test_touch_writes_after_debounce_window(self):
        old = timezone.now() - timedelta(seconds=Drop.TOUCH_DEBOUNCE_SECS + 10)
        Drop.objects.filter(pk=self.drop.pk).update(last_accessed_at=old)
        self.drop.last_accessed_at = old

        self.drop.touch()
        self.drop.refresh_from_db()
        self.assertGreater(self.drop.last_accessed_at, old)


# ─────────────────────────────────────────────────────────────────────────────
# Drop.hard_delete() — B2 cleanup + storage accounting
# ─────────────────────────────────────────────────────────────────────────────

class HardDeleteTests(TestCase):
    """hard_delete() must call B2 delete for file drops and adjust storage."""

    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")

    def test_file_drop_calls_b2_delete(self):
        drop = make_file_drop(key="del-test", owner=self.user, filesize=1000)
        UserProfile.objects.filter(user=self.user).update(storage_used_bytes=1000)

        with patch("core.views.b2.delete_object") as mock_delete:
            drop.hard_delete()
            mock_delete.assert_called_once_with(Drop.NS_FILE, "del-test")

        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.storage_used_bytes, 0)

    def test_text_drop_does_not_call_b2(self):
        drop = Drop.objects.create(
            ns=Drop.NS_CLIPBOARD, key="text-del", kind=Drop.TEXT,
            content="hello", owner=self.user,
        )
        with patch("core.views.b2.delete_object") as mock_delete:
            drop.hard_delete()
            mock_delete.assert_not_called()

    def test_b2_error_does_not_prevent_db_deletion(self):
        """A B2 network failure must never leave an orphaned DB row."""
        drop = make_file_drop(key="b2-err")
        pk = drop.pk
        with patch("core.views.b2.delete_object", side_effect=Exception("network error")):
            drop.hard_delete()  # must not raise
        self.assertFalse(Drop.objects.filter(pk=pk).exists())

    def test_storage_decremented_on_delete(self):
        drop = make_file_drop(key="size-del", owner=self.user, filesize=2048)
        UserProfile.objects.filter(user=self.user).update(storage_used_bytes=2048)

        with patch("core.views.b2.delete_object"):
            drop.hard_delete()

        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.storage_used_bytes, 0)

    def test_storage_not_decremented_for_ownerless_drop(self):
        """Anon drops have no owner; storage accounting must not crash."""
        drop = make_file_drop(key="anon-del", owner=None, filesize=500)
        with patch("core.views.b2.delete_object"):
            drop.hard_delete()  # must not raise
        self.assertFalse(Drop.objects.filter(key="anon-del").exists())
