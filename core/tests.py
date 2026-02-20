"""
Tests for the B2 migration.

Each test has one clear job. No test just exercises the happy path
for its own sake — every case covers a real failure mode or invariant
that matters in production.

Run: python manage.py test core
"""

from datetime import timedelta
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory
from django.utils import timezone

from core.models import Drop, Plan, UserProfile
from core.views.b2 import object_key


# ─────────────────────────────────────────────────────────────────────────────
# b2.object_key
# ─────────────────────────────────────────────────────────────────────────────

class ObjectKeyTests(TestCase):
    """object_key() is the single source of truth for B2 paths.
    If this is wrong, files land in the wrong place and downloads break."""

    def test_file_ns(self):
        self.assertEqual(object_key("f", "report"), "drops/f/report")

    def test_clipboard_ns(self):
        self.assertEqual(object_key("c", "hello"), "drops/c/hello")

    def test_key_with_special_chars(self):
        # Keys with hyphens/underscores must survive unchanged
        self.assertEqual(object_key("f", "my-file_v2"), "drops/f/my-file_v2")


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
        # created_at is auto_now_add in DB but we set it directly here
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
        # Set last_accessed_at to 1 minute ago — inside the 5-min window
        recent = timezone.now() - timedelta(seconds=60)
        Drop.objects.filter(pk=self.drop.pk).update(last_accessed_at=recent)
        self.drop.last_accessed_at = recent

        self.drop.touch()

        # Within the debounce window, last_accessed_at must NOT be updated in the DB
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
# Drop.hard_delete() — B2 cleanup
# ─────────────────────────────────────────────────────────────────────────────

class HardDeleteTests(TestCase):
    """hard_delete() must call B2 delete for file drops and adjust storage."""

    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")

    def test_file_drop_calls_b2_delete(self):
        drop = Drop.objects.create(
            ns=Drop.NS_FILE, key="del-test", kind=Drop.FILE,
            file_public_id="drops/f/del-test",
            filename="file.pdf", filesize=1000,
            owner=self.user,
        )
        UserProfile.objects.filter(user=self.user).update(storage_used_bytes=1000)

        with patch("core.views.b2.delete_object") as mock_delete:
            drop.hard_delete()
            mock_delete.assert_called_once_with(Drop.NS_FILE, "del-test")

        # Storage must be decremented
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
        drop = Drop.objects.create(
            ns=Drop.NS_FILE, key="b2-err", kind=Drop.FILE,
            file_public_id="drops/f/b2-err",
        )
        pk = drop.pk
        with patch("core.views.b2.delete_object", side_effect=Exception("network error")):
            drop.hard_delete()  # must not raise
        self.assertFalse(Drop.objects.filter(pk=pk).exists())


# ─────────────────────────────────────────────────────────────────────────────
# storage_ok() — quota gate
# ─────────────────────────────────────────────────────────────────────────────

class StorageOkTests(TestCase):
    """storage_ok() is the quota gate used in both prepare and confirm.
    Getting this wrong either blocks legitimate uploads or allows overages."""

    from core.views.helpers import storage_ok

    def setUp(self):
        self.user = User.objects.create_user("quota-user", password="pw")
        self.profile = self.user.profile
        self.profile.plan = Plan.STARTER
        self.profile.save()

    def test_anon_always_allowed(self):
        from django.contrib.auth.models import AnonymousUser
        from core.views.helpers import storage_ok
        anon = AnonymousUser()
        self.assertTrue(storage_ok(anon, 999_999_999))

    def test_free_plan_no_quota_always_allowed(self):
        from core.views.helpers import storage_ok
        # Free plan has storage_gb=None → no cap
        self.profile.plan = Plan.FREE
        self.profile.save()
        self.assertTrue(storage_ok(self.user, 999_999_999))

    def test_starter_within_quota(self):
        from core.views.helpers import storage_ok
        self.profile.storage_used_bytes = 0
        self.profile.save()
        quota = Plan.get(Plan.STARTER, "storage_gb") * 1024 ** 3
        self.assertTrue(storage_ok(self.user, quota - 1))

    def test_starter_exceeds_quota(self):
        from core.views.helpers import storage_ok
        quota = Plan.get(Plan.STARTER, "storage_gb") * 1024 ** 3
        self.profile.storage_used_bytes = quota
        self.profile.save()
        self.assertFalse(storage_ok(self.user, 1))


# ─────────────────────────────────────────────────────────────────────────────
# upload_confirm view — TOCTOU quota re-check
# ─────────────────────────────────────────────────────────────────────────────

class UploadConfirmTests(TestCase):
    """confirm must re-check quota using the *actual* B2 object size,
    and must delete the orphaned B2 object if quota is exceeded."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user("confirm-user", password="pw")
        self.user.profile.plan = Plan.STARTER
        self.user.profile.save()

    def _post(self, data, user=None):
        import json
        from core.views.drops import upload_confirm
        req = self.factory.post(
            "/upload/confirm/",
            data=json.dumps(data),
            content_type="application/json",
        )
        req.user = user or self.user
        req.COOKIES = {}
        return upload_confirm(req)

    @patch("core.views.drops.object_exists", return_value=True)
    @patch("core.views.drops.object_size", return_value=500)
    def test_confirm_creates_drop(self, mock_size, mock_exists):
        resp = self._post({"key": "newfile", "ns": "f", "filename": "a.txt"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Drop.objects.filter(ns="f", key="newfile").exists())

    @patch("core.views.drops.object_exists", return_value=False)
    def test_confirm_404_when_object_missing(self, mock_exists):
        resp = self._post({"key": "ghost", "ns": "f", "filename": "ghost.bin"})
        self.assertEqual(resp.status_code, 404)

    @patch("core.views.drops.object_exists", return_value=True)
    @patch("core.views.drops.object_size")
    @patch("core.views.drops.delete_from_b2")
    def test_confirm_deletes_b2_on_quota_exceeded(self, mock_del, mock_size, mock_exists):
        # Fill the quota
        quota = Plan.get(Plan.STARTER, "storage_gb") * 1024 ** 3
        self.user.profile.storage_used_bytes = quota
        self.user.profile.save()
        mock_size.return_value = 1  # even 1 byte overflows

        resp = self._post({"key": "overflow", "ns": "f", "filename": "x.bin"})
        self.assertEqual(resp.status_code, 507)
        mock_del.assert_called_once_with("f", "overflow")
        self.assertFalse(Drop.objects.filter(key="overflow").exists())


# ─────────────────────────────────────────────────────────────────────────────
# download_drop view — 302 redirect, never proxies bytes
# ─────────────────────────────────────────────────────────────────────────────

class DownloadDropTests(TestCase):
    """The download endpoint must 302-redirect to a presigned URL.
    If it ever proxied the bytes through Django, Railway's 30s timeout would fire."""

    def setUp(self):
        self.factory = RequestFactory()
        self.drop = Drop.objects.create(
            ns=Drop.NS_FILE, key="dl-drop", kind=Drop.FILE,
            file_public_id="drops/f/dl-drop",
            filename="report.pdf", filesize=100,
        )

    def _get(self):
        from core.views.drops import download_drop
        req = self.factory.get("/f/dl-drop/download/")
        req.user = MagicMock(is_authenticated=False)
        return download_drop(req, key="dl-drop")

    def test_returns_302(self):
        with patch.object(Drop, "download_url", return_value="https://b2.example.com/presigned"):
            resp = self._get()
        self.assertEqual(resp.status_code, 302)

    def test_redirects_to_presigned_url(self):
        fake_url = "https://b2.example.com/presigned?sig=abc"
        with patch.object(Drop, "download_url", return_value=fake_url):
            resp = self._get()
        self.assertEqual(resp["Location"], fake_url)

    def test_404_for_missing_drop(self):
        from django.http import Http404
        from core.views.drops import download_drop
        req = self.factory.get("/f/nope/download/")
        req.user = MagicMock(is_authenticated=False)
        with self.assertRaises(Http404):
            download_drop(req, key="nope")

    def test_404_for_expired_drop(self):
        from django.http import Http404
        from core.views.drops import download_drop
        self.drop.expires_at = timezone.now() - timedelta(seconds=1)
        self.drop.save()
        req = self.factory.get(f"/f/{self.drop.key}/download/")
        req.user = MagicMock(is_authenticated=False)
        with self.assertRaises(Http404):
            download_drop(req, key=self.drop.key)


# ─────────────────────────────────────────────────────────────────────────────
# Drop.download_url()
# ─────────────────────────────────────────────────────────────────────────────

class DropDownloadUrlTests(TestCase):
    """download_url() must call presigned_get with the correct ns/key/filename."""

    def test_calls_presigned_get_correctly(self):
        drop = Drop(
            ns=Drop.NS_FILE, key="myfile", kind=Drop.FILE,
            filename="report.pdf",
        )
        with patch("core.views.b2.presigned_get", return_value="https://url") as mock:
            url = drop.download_url(expires_in=1800)
        mock.assert_called_once_with("f", "myfile", filename="report.pdf", expires_in=1800)
        self.assertEqual(url, "https://url")

    def test_raises_for_text_drop(self):
        drop = Drop(ns=Drop.NS_CLIPBOARD, key="txt", kind=Drop.TEXT)
        with self.assertRaises(ValueError):
            drop.download_url()


# ─────────────────────────────────────────────────────────────────────────────
# Plan limits
# ─────────────────────────────────────────────────────────────────────────────

class PlanLimitTests(TestCase):
    """Plan limits are production config — wrong values silently break billing."""

    def test_anon_has_no_storage_cap(self):
        self.assertIsNone(Plan.get(Plan.ANON, "storage_gb"))

    def test_free_has_no_storage_cap(self):
        self.assertIsNone(Plan.get(Plan.FREE, "storage_gb"))

    def test_starter_storage_is_5gb(self):
        self.assertEqual(Plan.get(Plan.STARTER, "storage_gb"), 5)

    def test_pro_storage_is_20gb(self):
        self.assertEqual(Plan.get(Plan.PRO, "storage_gb"), 20)

    def test_starter_max_file_mb(self):
        self.assertEqual(Plan.get(Plan.STARTER, "max_file_mb"), 1024)

    def test_pro_max_file_mb(self):
        self.assertEqual(Plan.get(Plan.PRO, "max_file_mb"), 5120)