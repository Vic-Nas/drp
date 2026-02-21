"""
tests/unit/test_plan_limits.py

Unit tests for Plan.LIMITS constants and UserProfile plan-derived properties.
No DB required for pure constant checks; Django TestCase used for profile tests.
"""

import pytest
from django.test import TestCase
from django.contrib.auth.models import User

from core.models import Plan, UserProfile


# ── Plan.LIMITS completeness ──────────────────────────────────────────────────

class TestPlanLimitsSchema(TestCase):
    """Every plan must define every field — no silent KeyError at runtime."""

    REQUIRED_FIELDS = [
        "label", "price_monthly", "max_file_mb", "max_text_kb",
        "max_expiry_days", "clipboard_idle_hours", "clipboard_max_lifetime_days",
        "storage_gb", "renewals", "password_protection",
    ]

    def _plan(self, key):
        return Plan.LIMITS[key]

    def test_anon_has_all_fields(self):
        for f in self.REQUIRED_FIELDS:
            self.assertIn(f, self._plan(Plan.ANON), msg=f"ANON missing field: {f}")

    def test_free_has_all_fields(self):
        for f in self.REQUIRED_FIELDS:
            self.assertIn(f, self._plan(Plan.FREE), msg=f"FREE missing field: {f}")

    def test_starter_has_all_fields(self):
        for f in self.REQUIRED_FIELDS:
            self.assertIn(f, self._plan(Plan.STARTER), msg=f"STARTER missing field: {f}")

    def test_pro_has_all_fields(self):
        for f in self.REQUIRED_FIELDS:
            self.assertIn(f, self._plan(Plan.PRO), msg=f"PRO missing field: {f}")


# ── File / text size limits ───────────────────────────────────────────────────

class TestPlanFileLimits(TestCase):
    def test_anon_free_same_file_limit(self):
        self.assertEqual(Plan.get(Plan.ANON, "max_file_mb"), Plan.get(Plan.FREE, "max_file_mb"))

    def test_starter_larger_than_free(self):
        self.assertGreater(Plan.get(Plan.STARTER, "max_file_mb"), Plan.get(Plan.FREE, "max_file_mb"))

    def test_pro_larger_than_starter(self):
        self.assertGreater(Plan.get(Plan.PRO, "max_file_mb"), Plan.get(Plan.STARTER, "max_file_mb"))

    def test_pro_file_limit_is_5gb(self):
        self.assertEqual(Plan.get(Plan.PRO, "max_file_mb"), 5120)

    def test_starter_file_limit_is_1gb(self):
        self.assertEqual(Plan.get(Plan.STARTER, "max_file_mb"), 1024)

    def test_free_file_limit_is_200mb(self):
        self.assertEqual(Plan.get(Plan.FREE, "max_file_mb"), 200)

    def test_pro_text_limit_is_10mb(self):
        self.assertEqual(Plan.get(Plan.PRO, "max_text_kb"), 10240)


# ── Expiry rules ──────────────────────────────────────────────────────────────

class TestPlanExpiry(TestCase):
    def test_anon_no_custom_expiry(self):
        self.assertIsNone(Plan.get(Plan.ANON, "max_expiry_days"))

    def test_free_no_custom_expiry(self):
        self.assertIsNone(Plan.get(Plan.FREE, "max_expiry_days"))

    def test_starter_can_set_custom_expiry(self):
        self.assertIsNotNone(Plan.get(Plan.STARTER, "max_expiry_days"))

    def test_starter_max_expiry_is_1_year(self):
        self.assertEqual(Plan.get(Plan.STARTER, "max_expiry_days"), 365)

    def test_pro_max_expiry_is_3_years(self):
        self.assertEqual(Plan.get(Plan.PRO, "max_expiry_days"), 365 * 3)

    def test_pro_longer_expiry_than_starter(self):
        self.assertGreater(
            Plan.get(Plan.PRO, "max_expiry_days"),
            Plan.get(Plan.STARTER, "max_expiry_days"),
        )

    def test_anon_clipboard_max_lifetime_7_days(self):
        self.assertEqual(Plan.get(Plan.ANON, "clipboard_max_lifetime_days"), 7)

    def test_free_clipboard_max_lifetime_30_days(self):
        self.assertEqual(Plan.get(Plan.FREE, "clipboard_max_lifetime_days"), 30)

    def test_paid_plans_no_clipboard_ceiling(self):
        # Paid plans use explicit expiry — no automatic ceiling
        self.assertIsNone(Plan.get(Plan.STARTER, "clipboard_max_lifetime_days"))
        self.assertIsNone(Plan.get(Plan.PRO, "clipboard_max_lifetime_days"))

    def test_free_idle_hours_48(self):
        self.assertEqual(Plan.get(Plan.FREE, "clipboard_idle_hours"), 48)

    def test_anon_idle_hours_24(self):
        self.assertEqual(Plan.get(Plan.ANON, "clipboard_idle_hours"), 24)


# ── Storage quota ─────────────────────────────────────────────────────────────

class TestPlanStorage(TestCase):
    def test_anon_no_storage(self):
        self.assertIsNone(Plan.get(Plan.ANON, "storage_gb"))

    def test_free_no_storage(self):
        self.assertIsNone(Plan.get(Plan.FREE, "storage_gb"))

    def test_starter_storage_5gb(self):
        self.assertEqual(Plan.get(Plan.STARTER, "storage_gb"), 5)

    def test_pro_storage_20gb(self):
        self.assertEqual(Plan.get(Plan.PRO, "storage_gb"), 20)


# ── Password protection flag ──────────────────────────────────────────────────

class TestPlanPasswordProtection(TestCase):
    def test_anon_no_password_protection(self):
        self.assertFalse(Plan.get(Plan.ANON, "password_protection"))

    def test_free_no_password_protection(self):
        self.assertFalse(Plan.get(Plan.FREE, "password_protection"))

    def test_starter_has_password_protection(self):
        self.assertTrue(Plan.get(Plan.STARTER, "password_protection"))

    def test_pro_has_password_protection(self):
        self.assertTrue(Plan.get(Plan.PRO, "password_protection"))


# ── UserProfile properties ────────────────────────────────────────────────────

class TestUserProfileProperties(TestCase):
    def _make_user(self, plan):
        u = User.objects.create_user(f"u_{plan}", password="pw")
        UserProfile.objects.filter(user=u).update(plan=plan)
        u.refresh_from_db()
        return u

    def test_free_is_not_paid(self):
        u = self._make_user(Plan.FREE)
        self.assertFalse(u.profile.is_paid)

    def test_starter_is_paid(self):
        u = self._make_user(Plan.STARTER)
        self.assertTrue(u.profile.is_paid)

    def test_pro_is_paid(self):
        u = self._make_user(Plan.PRO)
        self.assertTrue(u.profile.is_paid)

    def test_free_storage_quota_is_none(self):
        u = self._make_user(Plan.FREE)
        self.assertIsNone(u.profile.storage_quota_bytes)

    def test_starter_storage_quota_is_5gb(self):
        u = self._make_user(Plan.STARTER)
        expected = 5 * 1024 ** 3
        self.assertEqual(u.profile.storage_quota_bytes, expected)

    def test_pro_storage_quota_is_20gb(self):
        u = self._make_user(Plan.PRO)
        expected = 20 * 1024 ** 3
        self.assertEqual(u.profile.storage_quota_bytes, expected)

    def test_storage_available_none_when_no_quota(self):
        u = self._make_user(Plan.FREE)
        self.assertIsNone(u.profile.storage_available_bytes())

    def test_storage_available_decreases_with_usage(self):
        u = self._make_user(Plan.STARTER)
        UserProfile.objects.filter(user=u).update(storage_used_bytes=1024 ** 3)
        u.profile.refresh_from_db()
        available = u.profile.storage_available_bytes()
        self.assertEqual(available, 4 * 1024 ** 3)
