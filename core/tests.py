"""
Tests for account creation, drop lifecycle, subscriptions, and payment webhooks.

Rules followed here:
- Every test has a clear purpose stated in its name and/or docstring
- No test passes vacuously (vacuous = would pass even if the feature is broken)
- Side effects (DB mutations) are intentional and explicitly verified
- Webhook tests verify DB state, not just HTTP status code
"""

import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from core.models import Drop, Plan, UserProfile

_STATIC_OVERRIDE = override_settings(
    STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage'
)


# ═══════════════════════════════════════════════════════════════════════════════
# Account creation & auth
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class AccountCreationTests(TestCase):

    def test_register_creates_user(self):
        self.client.post('/auth/register/', {
            'email': 'new@test.com', 'password': 'testpass123', 'password2': 'testpass123',
        })
        self.assertTrue(User.objects.filter(email='new@test.com').exists())

    def test_register_creates_profile_on_free_plan(self):
        self.client.post('/auth/register/', {
            'email': 'new@test.com', 'password': 'testpass123', 'password2': 'testpass123',
        })
        user = User.objects.get(email='new@test.com')
        self.assertEqual(user.profile.plan, Plan.FREE)

    def test_register_logs_in_automatically(self):
        self.client.post('/auth/register/', {
            'email': 'auto@test.com', 'password': 'testpass123', 'password2': 'testpass123',
        })
        resp = self.client.get('/')
        self.assertTrue(resp.wsgi_request.user.is_authenticated)

    def test_register_redirects_on_success(self):
        resp = self.client.post('/auth/register/', {
            'email': 'redir@test.com', 'password': 'testpass123', 'password2': 'testpass123',
        })
        self.assertEqual(resp.status_code, 302)

    def test_register_password_mismatch_rejected(self):
        resp = self.client.post('/auth/register/', {
            'email': 'bad@test.com', 'password': 'testpass123', 'password2': 'different456',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email='bad@test.com').exists())

    def test_register_short_password_rejected(self):
        resp = self.client.post('/auth/register/', {
            'email': 'short@test.com', 'password': '1234567', 'password2': '1234567',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email='short@test.com').exists())

    def test_register_duplicate_email_rejected(self):
        User.objects.create_user('dup@test.com', 'dup@test.com', 'testpass123')
        resp = self.client.post('/auth/register/', {
            'email': 'dup@test.com', 'password': 'testpass123', 'password2': 'testpass123',
        })
        self.assertEqual(resp.status_code, 200)
        # Only one user with that email
        self.assertEqual(User.objects.filter(email='dup@test.com').count(), 1)

    def test_register_normalizes_email_to_lowercase(self):
        self.client.post('/auth/register/', {
            'email': 'MiXeD@Test.COM', 'password': 'testpass123', 'password2': 'testpass123',
        })
        self.assertTrue(User.objects.filter(email='mixed@test.com').exists())
        self.assertFalse(User.objects.filter(email='MiXeD@Test.COM').exists())

    def test_login_valid_credentials_redirects(self):
        User.objects.create_user('user@test.com', 'user@test.com', 'testpass123')
        resp = self.client.post('/auth/login/', {'email': 'user@test.com', 'password': 'testpass123'})
        self.assertEqual(resp.status_code, 302)

    def test_login_wrong_password_stays_on_form(self):
        User.objects.create_user('user@test.com', 'user@test.com', 'testpass123')
        resp = self.client.post('/auth/login/', {'email': 'user@test.com', 'password': 'wrong'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.wsgi_request.user.is_authenticated)

    def test_logout_clears_session(self):
        User.objects.create_user('user@test.com', 'user@test.com', 'testpass123')
        self.client.login(username='user@test.com', password='testpass123')
        self.client.get('/auth/logout/')
        resp = self.client.get('/')
        self.assertFalse(resp.wsgi_request.user.is_authenticated)

    def test_account_page_redirects_when_not_logged_in(self):
        resp = self.client.get('/auth/account/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/auth/login/', resp.url)

    def test_account_page_accessible_when_logged_in(self):
        User.objects.create_user('user@test.com', 'user@test.com', 'testpass123')
        self.client.login(username='user@test.com', password='testpass123')
        resp = self.client.get('/auth/account/')
        self.assertEqual(resp.status_code, 200)

    def test_profile_created_automatically_via_signal(self):
        user = User.objects.create_user('sig@test.com', 'sig@test.com', 'testpass123')
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)

    def test_register_redirects_when_already_logged_in(self):
        User.objects.create_user('user@test.com', 'user@test.com', 'testpass123')
        self.client.login(username='user@test.com', password='testpass123')
        resp = self.client.get('/auth/register/')
        self.assertEqual(resp.status_code, 302)


# ═══════════════════════════════════════════════════════════════════════════════
# Plan limits & entitlements
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class PlanEntitlementTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('plan@test.com', 'plan@test.com', 'testpass123')
        self.profile = self.user.profile

    def test_free_plan_is_not_paid(self):
        self.assertEqual(self.profile.plan, Plan.FREE)
        self.assertFalse(self.profile.is_paid)

    def test_free_plan_has_no_storage_quota(self):
        self.assertIsNone(self.profile.storage_quota_bytes)

    def test_starter_plan_is_paid(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        self.assertTrue(self.profile.is_paid)

    def test_starter_plan_storage_quota_is_5gb(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        self.assertEqual(self.profile.storage_quota_bytes, 5 * 1024 ** 3)

    def test_pro_plan_storage_quota_is_20gb(self):
        self.profile.plan = Plan.PRO
        self.profile.save()
        self.assertEqual(self.profile.storage_quota_bytes, 20 * 1024 ** 3)

    def test_storage_available_decreases_with_usage(self):
        self.profile.plan = Plan.STARTER
        self.profile.storage_used_bytes = 100 * 1024 ** 2  # 100 MB
        self.profile.save()
        expected = 5 * 1024 ** 3 - 100 * 1024 ** 2
        self.assertEqual(self.profile.storage_available_bytes(), expected)

    def test_storage_available_is_none_for_free_plan(self):
        self.assertIsNone(self.profile.storage_available_bytes())

    def test_plan_limits_anon_max_file(self):
        self.assertEqual(Plan.get(Plan.ANON, 'max_file_mb'), 200)

    def test_plan_limits_starter_max_file(self):
        self.assertEqual(Plan.get(Plan.STARTER, 'max_file_mb'), 1024)

    def test_plan_limits_pro_max_file(self):
        self.assertEqual(Plan.get(Plan.PRO, 'max_file_mb'), 5120)

    def test_plan_limits_starter_max_expiry(self):
        self.assertEqual(Plan.get(Plan.STARTER, 'max_expiry_days'), 365)

    def test_plan_limits_pro_max_expiry(self):
        self.assertEqual(Plan.get(Plan.PRO, 'max_expiry_days'), 365 * 3)

    def test_paid_drop_is_owner_locked(self):
        """Paid user upload must produce a drop with locked=True, owner set."""
        self.profile.plan = Plan.STARTER
        self.profile.save()
        self.client.login(username='plan@test.com', password='testpass123')
        resp = self.client.post('/save/', {'content': 'paid text', 'expiry_days': '30'})
        data = resp.json()
        drop = Drop.objects.get(key=data['key'])
        self.assertTrue(drop.locked)
        self.assertEqual(drop.owner, self.user)

    def test_paid_expiry_is_capped_at_plan_max(self):
        """Requesting 9999 days must be capped to the plan's max_expiry_days."""
        self.profile.plan = Plan.STARTER
        self.profile.save()
        self.client.login(username='plan@test.com', password='testpass123')
        resp = self.client.post('/save/', {'content': 'capped', 'expiry_days': '9999'})
        data = resp.json()
        drop = Drop.objects.get(key=data['key'])
        max_days = Plan.get(Plan.STARTER, 'max_expiry_days')
        delta = drop.expires_at - drop.created_at
        self.assertLessEqual(delta.days, max_days,
                             f'Expiry not capped: {delta.days} > {max_days}')

    def test_free_user_drop_has_no_expires_at(self):
        """Free user drops use time-based expiry, not an explicit expires_at date."""
        self.client.login(username='plan@test.com', password='testpass123')
        resp = self.client.post('/save/', {'content': 'free text'})
        data = resp.json()
        drop = Drop.objects.get(key=data['key'])
        self.assertIsNone(drop.expires_at)

    def test_anon_drop_has_24h_creation_lock(self):
        resp = self.client.post('/save/', {'content': 'anon'})
        data = resp.json()
        drop = Drop.objects.get(key=data['key'])
        self.assertIsNotNone(drop.locked_until)
        self.assertTrue(drop.is_creation_locked())

    def test_drop_renewal_extends_expiry_by_plan_period(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        self.client.login(username='plan@test.com', password='testpass123')
        original_expiry = timezone.now() + timedelta(days=10)
        drop = Drop.objects.create(
            key='renew-me', kind=Drop.TEXT, content='hi',
            owner=self.user, locked=True, expires_at=original_expiry,
        )
        resp = self.client.post(f'/{drop.key}/renew/')
        self.assertEqual(resp.status_code, 200)
        drop.refresh_from_db()
        self.assertEqual(drop.renewal_count, 1)
        self.assertGreater(drop.expires_at, original_expiry,
                           'Renewal must move expiry further into the future')

    def test_free_plan_drop_cannot_be_renewed(self):
        """Free plan drops don't have explicit expiry — renew should be rejected."""
        self.client.login(username='plan@test.com', password='testpass123')
        drop = Drop.objects.create(
            key='norenewal', kind=Drop.TEXT, content='hi',
            owner=self.user,
        )
        resp = self.client.post(f'/{drop.key}/renew/')
        self.assertNotEqual(resp.status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════════
# Drop lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class DropLifecycleTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('drop@test.com', 'drop@test.com', 'testpass123')
        self.profile = self.user.profile

    def test_anon_text_drop_expired_after_24h(self):
        drop = Drop.objects.create(key='old-txt', kind=Drop.TEXT, content='x')
        Drop.objects.filter(pk=drop.pk).update(created_at=timezone.now() - timedelta(hours=25))
        drop.refresh_from_db()
        self.assertTrue(drop.is_expired())

    def test_anon_text_drop_not_expired_at_23h(self):
        drop = Drop.objects.create(key='new-txt', kind=Drop.TEXT, content='x')
        Drop.objects.filter(pk=drop.pk).update(created_at=timezone.now() - timedelta(hours=23))
        drop.refresh_from_db()
        self.assertFalse(drop.is_expired())

    def test_anon_file_drop_expired_after_90d(self):
        drop = Drop.objects.create(key='old-file', kind=Drop.FILE, filename='f.txt')
        Drop.objects.filter(pk=drop.pk).update(created_at=timezone.now() - timedelta(days=91))
        drop.refresh_from_db()
        self.assertTrue(drop.is_expired())

    def test_anon_file_drop_not_expired_at_89d(self):
        drop = Drop.objects.create(key='new-file', kind=Drop.FILE, filename='f.txt')
        Drop.objects.filter(pk=drop.pk).update(created_at=timezone.now() - timedelta(days=89))
        drop.refresh_from_db()
        self.assertFalse(drop.is_expired())

    def test_paid_drop_expired_when_expires_at_is_past(self):
        drop = Drop.objects.create(
            key='paid-exp', kind=Drop.TEXT, content='x',
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertTrue(drop.is_expired())

    def test_paid_drop_not_expired_when_expires_at_is_future(self):
        drop = Drop.objects.create(
            key='paid-ok', kind=Drop.TEXT, content='x',
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.assertFalse(drop.is_expired())

    def test_owner_can_edit_locked_drop(self):
        drop = Drop.objects.create(
            key='owned', kind=Drop.TEXT, content='mine',
            owner=self.user, locked=True,
        )
        self.assertTrue(drop.can_edit(self.user))

    def test_other_user_cannot_edit_locked_drop(self):
        drop = Drop.objects.create(
            key='owned2', kind=Drop.TEXT, content='mine',
            owner=self.user, locked=True,
        )
        other = User.objects.create_user('other@test.com', 'other@test.com', 'testpass123')
        self.assertFalse(drop.can_edit(other))

    def test_anon_drop_cannot_edit_during_24h_lock(self):
        drop = Drop.objects.create(
            key='anonlocked', kind=Drop.TEXT, content='x',
            locked_until=timezone.now() + timedelta(hours=23),
        )
        self.assertFalse(drop.can_edit(None))

    def test_anon_drop_can_edit_after_24h_lock(self):
        drop = Drop.objects.create(
            key='anonunlocked', kind=Drop.TEXT, content='x',
            locked_until=timezone.now() - timedelta(hours=1),
        )
        self.assertTrue(drop.can_edit(None))

    def test_hard_delete_reduces_owner_storage(self):
        self.profile.plan = Plan.STARTER
        self.profile.storage_used_bytes = 5000
        self.profile.save()
        drop = Drop.objects.create(
            key='del-store', kind=Drop.FILE,
            owner=self.user, filesize=5000,
        )
        drop.hard_delete()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.storage_used_bytes, 0)

    def test_hard_delete_removes_drop_from_db(self):
        drop = Drop.objects.create(key='gone', kind=Drop.TEXT, content='x')
        drop.hard_delete()
        self.assertFalse(Drop.objects.filter(key='gone').exists())

    def test_expired_drop_deleted_when_viewed(self):
        """Viewing an expired drop must clean it up and not serve stale content."""
        drop = Drop.objects.create(key='exp-view', kind=Drop.TEXT, content='old')
        Drop.objects.filter(pk=drop.pk).update(created_at=timezone.now() - timedelta(hours=25))
        self.client.get('/exp-view/')
        self.assertFalse(Drop.objects.filter(key='exp-view').exists())


# ═══════════════════════════════════════════════════════════════════════════════
# Cleanup management command
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class CleanupCommandTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('clean@test.com', 'clean@test.com', 'testpass123')
        self.profile = self.user.profile
        from django.core.management import call_command as _cc
        self._call = lambda: _cc('cleanup')

    def test_fresh_anon_text_drop_survives(self):
        Drop.objects.create(key='fresh-txt', kind=Drop.TEXT, content='hi')
        self._call()
        self.assertTrue(Drop.objects.filter(key='fresh-txt').exists())

    def test_old_anon_text_drop_deleted(self):
        d = Drop.objects.create(key='old-txt', kind=Drop.TEXT, content='hi')
        Drop.objects.filter(pk=d.pk).update(created_at=timezone.now() - timedelta(hours=25))
        self._call()
        self.assertFalse(Drop.objects.filter(key='old-txt').exists())

    def test_fresh_anon_file_drop_survives(self):
        Drop.objects.create(key='fresh-file', kind=Drop.FILE, filename='f.txt')
        self._call()
        self.assertTrue(Drop.objects.filter(key='fresh-file').exists())

    def test_old_anon_file_drop_deleted(self):
        d = Drop.objects.create(key='old-file', kind=Drop.FILE, filename='f.txt')
        Drop.objects.filter(pk=d.pk).update(created_at=timezone.now() - timedelta(days=91))
        self._call()
        self.assertFalse(Drop.objects.filter(key='old-file').exists())

    def test_paid_drop_before_expiry_survives(self):
        Drop.objects.create(
            key='paid-safe', kind=Drop.TEXT, content='x',
            owner=self.user, locked=True,
            expires_at=timezone.now() + timedelta(days=180),
        )
        self._call()
        self.assertTrue(Drop.objects.filter(key='paid-safe').exists())

    def test_paid_drop_after_expiry_deleted(self):
        Drop.objects.create(
            key='paid-exp', kind=Drop.TEXT, content='x',
            owner=self.user, locked=True,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self._call()
        self.assertFalse(Drop.objects.filter(key='paid-exp').exists())

    def test_cleanup_mixed_batch_only_removes_expired(self):
        # Survivors
        Drop.objects.create(key='s-txt', kind=Drop.TEXT, content='ok')
        Drop.objects.create(key='s-file', kind=Drop.FILE, filename='a.txt')
        Drop.objects.create(
            key='s-paid', kind=Drop.TEXT, content='x',
            owner=self.user, expires_at=timezone.now() + timedelta(days=365),
        )
        # Deaths
        d_txt = Drop.objects.create(key='d-txt', kind=Drop.TEXT, content='x')
        Drop.objects.filter(pk=d_txt.pk).update(created_at=timezone.now() - timedelta(hours=25))
        d_file = Drop.objects.create(key='d-file', kind=Drop.FILE, filename='d.txt')
        Drop.objects.filter(pk=d_file.pk).update(created_at=timezone.now() - timedelta(days=91))
        Drop.objects.create(
            key='d-paid', kind=Drop.TEXT, content='x',
            owner=self.user, expires_at=timezone.now() - timedelta(seconds=1),
        )
        self._call()
        for key in ('s-txt', 's-file', 's-paid'):
            self.assertTrue(Drop.objects.filter(key=key).exists(), f'{key} should survive')
        for key in ('d-txt', 'd-file', 'd-paid'):
            self.assertFalse(Drop.objects.filter(key=key).exists(), f'{key} should be deleted')

    def test_cleanup_reduces_owner_storage_for_deleted_file_drop(self):
        self.profile.plan = Plan.STARTER
        self.profile.storage_used_bytes = 8192
        self.profile.save()
        Drop.objects.create(
            key='store-exp', kind=Drop.FILE, filename='s.txt',
            owner=self.user, filesize=8192,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self._call()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.storage_used_bytes, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Payment webhooks
# ═══════════════════════════════════════════════════════════════════════════════

WEBHOOK_SECRET = 'test-webhook-secret-1234'


def _make_webhook(payload, secret=WEBHOOK_SECRET):
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


def _subscription_payload(user_id, variant_id, status='active',
                           customer_id='cust_123', sub_id='sub_456',
                           event='subscription_created'):
    return {
        'meta': {
            'event_name': event,
            'custom_data': {'user_id': str(user_id)},
        },
        'data': {
            'id': sub_id,
            'attributes': {
                'customer_id': customer_id,
                'variant_id': variant_id,
                'status': status,
            },
        },
    }


@override_settings(LEMONSQUEEZY_SIGNING_SECRET=WEBHOOK_SECRET)
@patch('billing.views.VARIANT_PLAN_MAP', {'variant_starter': Plan.STARTER, 'variant_pro': Plan.PRO})
class WebhookTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('wh@test.com', 'wh@test.com', 'testpass123')
        self.profile = self.user.profile

    def _post(self, payload, secret=WEBHOOK_SECRET):
        body, sig = _make_webhook(payload, secret)
        return self.client.post(
            '/billing/webhook/', body,
            HTTP_X_SIGNATURE=sig,
            content_type='application/json',
        )

    # ── Signature verification ────────────────────────────────────────────────

    def test_bad_signature_returns_400(self):
        payload = _subscription_payload(self.user.pk, 'variant_starter')
        body, _ = _make_webhook(payload)
        resp = self.client.post('/billing/webhook/', body,
                                HTTP_X_SIGNATURE='bad',
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_bad_signature_does_not_change_plan(self):
        payload = _subscription_payload(self.user.pk, 'variant_pro')
        body, _ = _make_webhook(payload)
        self.client.post('/billing/webhook/', body,
                         HTTP_X_SIGNATURE='bad',
                         content_type='application/json')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.FREE)  # unchanged

    def test_missing_signature_returns_400(self):
        payload = _subscription_payload(self.user.pk, 'variant_starter')
        body = json.dumps(payload).encode()
        resp = self.client.post('/billing/webhook/', body, content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_get_method_not_allowed(self):
        resp = self.client.get('/billing/webhook/')
        self.assertEqual(resp.status_code, 405)

    def test_bad_json_returns_400(self):
        body = b'not json'
        sig = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        resp = self.client.post('/billing/webhook/', body,
                                HTTP_X_SIGNATURE=sig,
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    # ── subscription_created ──────────────────────────────────────────────────

    def test_subscription_created_upgrades_to_starter(self):
        payload = _subscription_payload(self.user.pk, 'variant_starter')
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.STARTER)

    def test_subscription_created_stores_customer_and_subscription_ids(self):
        payload = _subscription_payload(
            self.user.pk, 'variant_starter',
            customer_id='cust_abc', sub_id='sub_xyz',
        )
        self._post(payload)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.ls_customer_id, 'cust_abc')
        self.assertEqual(self.profile.ls_subscription_id, 'sub_xyz')

    def test_subscription_created_sets_plan_since(self):
        payload = _subscription_payload(self.user.pk, 'variant_starter')
        self._post(payload)
        self.profile.refresh_from_db()
        self.assertIsNotNone(self.profile.plan_since)

    def test_subscription_created_pro(self):
        payload = _subscription_payload(self.user.pk, 'variant_pro')
        self._post(payload)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.PRO)

    # ── subscription_updated ──────────────────────────────────────────────────

    def test_subscription_updated_active_keeps_plan(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        payload = _subscription_payload(
            self.user.pk, 'variant_starter',
            status='active', event='subscription_updated',
        )
        self._post(payload)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.STARTER)

    def test_subscription_updated_unpaid_downgrades_to_free(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        payload = _subscription_payload(
            self.user.pk, 'variant_starter',
            status='unpaid', event='subscription_updated',
        )
        self._post(payload)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.FREE)

    def test_subscription_updated_stores_status(self):
        payload = _subscription_payload(
            self.user.pk, 'variant_starter',
            status='active', event='subscription_updated',
        )
        self._post(payload)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.ls_subscription_status, 'active')

    # ── subscription_cancelled ────────────────────────────────────────────────

    def test_subscription_cancelled_records_cancelled_status(self):
        """Cancelled = still active until period end. Status stored, plan TBD by policy."""
        self.profile.plan = Plan.STARTER
        self.profile.ls_customer_id = 'cust_123'
        self.profile.save()
        payload = _subscription_payload(
            self.user.pk, 'variant_starter',
            status='cancelled', event='subscription_cancelled',
        )
        self._post(payload)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.ls_subscription_status, 'cancelled')

    # ── subscription_expired ──────────────────────────────────────────────────

    def test_subscription_expired_downgrades_to_free(self):
        self.profile.plan = Plan.PRO
        self.profile.ls_customer_id = 'cust_123'
        self.profile.save()
        payload = _subscription_payload(
            self.user.pk, 'variant_pro',
            status='expired', event='subscription_expired',
        )
        self._post(payload)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.FREE)

    def test_subscription_expired_clears_plan_since(self):
        self.profile.plan = Plan.PRO
        self.profile.plan_since = timezone.now() - timedelta(days=365)
        self.profile.save()
        payload = _subscription_payload(
            self.user.pk, 'variant_pro',
            status='expired', event='subscription_expired',
        )
        self._post(payload)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.plan_since)

    def test_subscription_expired_stores_expired_status(self):
        self.profile.plan = Plan.PRO
        self.profile.save()
        payload = _subscription_payload(
            self.user.pk, 'variant_pro',
            status='expired', event='subscription_expired',
        )
        self._post(payload)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.ls_subscription_status, 'expired')

    # ── Fallback: find user by customer_id ────────────────────────────────────

    def test_webhook_finds_user_by_customer_id_when_user_id_missing(self):
        self.profile.ls_customer_id = 'cust_fallback'
        self.profile.save()
        payload = {
            'meta': {'event_name': 'subscription_updated', 'custom_data': {}},
            'data': {
                'id': 'sub_789',
                'attributes': {
                    'customer_id': 'cust_fallback',
                    'variant_id': 'variant_pro',
                    'status': 'active',
                },
            },
        }
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.PRO)

    def test_webhook_unknown_user_returns_200_without_side_effects(self):
        """LS must get 200 so it doesn't retry forever. No profile must be mutated."""
        before_count = UserProfile.objects.count()
        payload = _subscription_payload(99999, 'variant_starter')
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(UserProfile.objects.count(), before_count)

    # ── Checkout redirect ─────────────────────────────────────────────────────

    @patch('billing.views.PLAN_VARIANT_IDS', {Plan.STARTER: 'var_s', Plan.PRO: 'var_p'})
    @override_settings(LEMONSQUEEZY_STORE_ID='teststore')
    def test_checkout_starter_redirects_to_lemonsqueezy(self):
        self.client.login(username='wh@test.com', password='testpass123')
        resp = self.client.get('/billing/checkout/starter/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('lemonsqueezy.com', resp.url)

    @patch('billing.views.PLAN_VARIANT_IDS', {Plan.STARTER: 'var_s', Plan.PRO: 'var_p'})
    @override_settings(LEMONSQUEEZY_STORE_ID='teststore')
    def test_checkout_pro_redirects_to_lemonsqueezy(self):
        self.client.login(username='wh@test.com', password='testpass123')
        resp = self.client.get('/billing/checkout/pro/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('lemonsqueezy.com', resp.url)

    def test_checkout_requires_login(self):
        resp = self.client.get('/billing/checkout/starter/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/auth/login/', resp.url)

    def test_checkout_invalid_plan_redirects(self):
        self.client.login(username='wh@test.com', password='testpass123')
        resp = self.client.get('/billing/checkout/nonexistent/')
        self.assertEqual(resp.status_code, 302)