"""
Tests for core/views/helpers.py and core/models.py Plan config.

Covers: storage_ok() quota gate, Plan limit values.
"""

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from core.models import Drop, Plan
from core.views.helpers import storage_ok
from .helpers import make_user


# ─────────────────────────────────────────────────────────────────────────────
# storage_ok() — quota gate
# ─────────────────────────────────────────────────────────────────────────────

class StorageOkTests(TestCase):
    """storage_ok() is the quota gate used in both prepare and confirm.
    Getting this wrong either blocks legitimate uploads or allows overages."""

    def setUp(self):
        self.user = make_user("quota-user", plan=Plan.STARTER)

    def test_anon_always_allowed(self):
        self.assertTrue(storage_ok(AnonymousUser(), 999_999_999))

    def test_free_plan_no_quota_always_allowed(self):
        user = make_user("free-user", plan=Plan.FREE)
        self.assertTrue(storage_ok(user, 999_999_999))

    def test_starter_within_quota(self):
        quota = Plan.get(Plan.STARTER, "storage_gb") * 1024 ** 3
        self.user.profile.storage_used_bytes = 0
        self.user.profile.save()
        self.assertTrue(storage_ok(self.user, quota - 1))

    def test_starter_exactly_at_quota_boundary(self):
        quota = Plan.get(Plan.STARTER, "storage_gb") * 1024 ** 3
        self.user.profile.storage_used_bytes = quota - 1
        self.user.profile.save()
        self.assertTrue(storage_ok(self.user, 1))

    def test_starter_exceeds_quota(self):
        quota = Plan.get(Plan.STARTER, "storage_gb") * 1024 ** 3
        self.user.profile.storage_used_bytes = quota
        self.user.profile.save()
        self.assertFalse(storage_ok(self.user, 1))

    def test_pro_within_quota(self):
        user = make_user("pro-user", plan=Plan.PRO)
        quota = Plan.get(Plan.PRO, "storage_gb") * 1024 ** 3
        self.assertTrue(storage_ok(user, quota - 1))

    def test_pro_exceeds_quota(self):
        user = make_user("pro-user2", plan=Plan.PRO)
        quota = Plan.get(Plan.PRO, "storage_gb") * 1024 ** 3
        user.profile.storage_used_bytes = quota
        user.profile.save()
        self.assertFalse(storage_ok(user, 1))


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
