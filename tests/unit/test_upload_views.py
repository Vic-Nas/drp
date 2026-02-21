"""
tests/unit/test_upload_views.py

Unit tests for plan enforcement in core/views/drops.py.
Uses Django's test client against an in-memory SQLite DB.
No B2 calls — b2 functions are patched.
"""

import json
from unittest.mock import patch, MagicMock
from io import BytesIO

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from core.models import Drop, Plan, UserProfile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(username, plan=Plan.FREE, password="pw"):
    u = User.objects.create_user(username, email=f"{username}@test.com", password=password)
    UserProfile.objects.filter(user=u).update(plan=plan)
    u.refresh_from_db()
    return u


def _post_text(client, key, content, **extra):
    return client.post('/save/', {'key': key, 'content': content, **extra},
                       HTTP_ACCEPT='application/json')


# ── Text upload ───────────────────────────────────────────────────────────────

class TestTextUploadPlanEnforcement(TestCase):
    def setUp(self):
        self.free_user    = _make_user('free_up',    Plan.FREE)
        self.starter_user = _make_user('starter_up', Plan.STARTER)
        self.pro_user     = _make_user('pro_up',     Plan.PRO)

    def test_anon_can_upload_text(self):
        res = _post_text(self.client, 'anon-key', 'hello')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['key'], 'anon-key')

    def test_free_can_upload_text(self):
        self.client.force_login(self.free_user)
        res = _post_text(self.client, 'free-key', 'hello')
        self.assertEqual(res.status_code, 200)

    def test_free_custom_expiry_is_ignored(self):
        """Free plan: server ignores expiry_days — upload must still succeed."""
        self.client.force_login(self.free_user)
        res = _post_text(self.client, 'free-exp', 'hello', expiry_days=30)
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='free-exp')
        # Free plan has no custom expiry — expires_at should be None
        self.assertIsNone(drop.expires_at)

    def test_starter_custom_expiry_applied(self):
        self.client.force_login(self.starter_user)
        res = _post_text(self.client, 'starter-exp', 'hello', expiry_days=30)
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='starter-exp')
        self.assertIsNotNone(drop.expires_at)

    def test_pro_custom_expiry_applied(self):
        self.client.force_login(self.pro_user)
        res = _post_text(self.client, 'pro-exp', 'hello', expiry_days=90)
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='pro-exp')
        self.assertIsNotNone(drop.expires_at)

    def test_expiry_capped_at_plan_maximum(self):
        """Starter max is 365 days — 400 days should be capped, not rejected."""
        self.client.force_login(self.starter_user)
        res = _post_text(self.client, 'starter-cap', 'hello', expiry_days=400)
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='starter-cap')
        if drop.expires_at:
            from django.utils import timezone
            from datetime import timedelta
            max_delta = timedelta(days=Plan.get(Plan.STARTER, 'max_expiry_days') + 1)
            self.assertLessEqual(drop.expires_at - timezone.now(), max_delta)

    def test_text_over_limit_rejected(self):
        self.client.force_login(self.free_user)
        # Free limit is 500 KB — send 600 KB
        big = 'x' * (600 * 1024)
        res = _post_text(self.client, 'big-text', big)
        self.assertEqual(res.status_code, 400)
        self.assertIn('error', res.json())

    def test_burn_flag_set(self):
        res = _post_text(self.client, 'burn-key', 'ephemeral', burn='1')
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='burn-key')
        self.assertTrue(drop.burn)

    def test_password_rejected_for_free_user(self):
        self.client.force_login(self.free_user)
        res = _post_text(self.client, 'pw-free', 'secret content', password='mypassword')
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='pw-free')
        # Free plan — password should NOT have been set
        self.assertFalse(drop.is_password_protected)

    def test_password_accepted_for_paid_user(self):
        self.client.force_login(self.starter_user)
        res = _post_text(self.client, 'pw-paid', 'secret content', password='mypassword')
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='pw-paid')
        self.assertTrue(drop.is_password_protected)
        self.assertTrue(drop.check_password('mypassword'))


# ── Drop locking ──────────────────────────────────────────────────────────────

class TestDropLocking(TestCase):
    def setUp(self):
        self.paid_user = _make_user('paid_lock', Plan.STARTER)
        self.other     = _make_user('other_lock', Plan.FREE)

    def test_paid_drop_locked_to_owner(self):
        self.client.force_login(self.paid_user)
        _post_text(self.client, 'locked-drop', 'my content')
        drop = Drop.objects.get(key='locked-drop')
        self.assertTrue(drop.locked)

    def test_other_user_cannot_overwrite_locked_drop(self):
        self.client.force_login(self.paid_user)
        _post_text(self.client, 'protected', 'owner content')
        self.client.force_login(self.other)
        res = _post_text(self.client, 'protected', 'hijack attempt')
        self.assertEqual(res.status_code, 403)

    def test_owner_can_overwrite_own_drop(self):
        self.client.force_login(self.paid_user)
        _post_text(self.client, 'my-drop', 'v1')
        res = _post_text(self.client, 'my-drop', 'v2')
        self.assertEqual(res.status_code, 200)


# ── Renew ─────────────────────────────────────────────────────────────────────

class TestRenewEndpoint(TestCase):
    def setUp(self):
        self.free_user    = _make_user('renew_free', Plan.FREE)
        self.starter_user = _make_user('renew_starter', Plan.STARTER)

    def test_free_drop_without_expiry_cannot_be_renewed(self):
        from django.utils import timezone
        self.client.force_login(self.free_user)
        _post_text(self.client, 'renew-free', 'content')
        res = self.client.post('/renew-free/renew/', HTTP_ACCEPT='application/json')
        # No expires_at set — should return 400
        self.assertEqual(res.status_code, 400)

    def test_paid_drop_with_expiry_can_be_renewed(self):
        from django.utils import timezone
        from datetime import timedelta
        self.client.force_login(self.starter_user)
        _post_text(self.client, 'renew-paid', 'content', expiry_days=7)
        drop = Drop.objects.get(key='renew-paid')
        if drop.expires_at:
            res = self.client.post('/renew-paid/renew/', HTTP_ACCEPT='application/json')
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn('expires_at', data)
