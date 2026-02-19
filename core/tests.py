"""
Tests for account creation, subscriptions, and payment webhooks.

All tests use Django's TestCase (wraps each test in a transaction that rolls
back automatically), so the DB is always clean — no manual teardown needed.
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

# Use plain static storage in tests (no collectstatic needed)
_STATIC_OVERRIDE = override_settings(
    STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage'
)


# ═══════════════════════════════════════════════════════════════════════════════
# Account creation
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class AccountCreationTests(TestCase):
    """Registration, login, logout, profile auto-creation."""

    def test_register_creates_user_and_profile(self):
        resp = self.client.post('/auth/register/', {
            'email': 'new@test.com',
            'password': 'testpass123',
            'password2': 'testpass123',
        })
        self.assertEqual(resp.status_code, 302)  # redirect to home
        user = User.objects.get(email='new@test.com')
        self.assertTrue(hasattr(user, 'profile'))
        self.assertEqual(user.profile.plan, Plan.FREE)

    def test_register_logs_in_automatically(self):
        self.client.post('/auth/register/', {
            'email': 'auto@test.com',
            'password': 'testpass123',
            'password2': 'testpass123',
        })
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.wsgi_request.user.is_authenticated)

    def test_register_password_mismatch(self):
        resp = self.client.post('/auth/register/', {
            'email': 'bad@test.com',
            'password': 'testpass123',
            'password2': 'different456',
        })
        self.assertEqual(resp.status_code, 200)  # re-renders form
        self.assertContains(resp, 'Passwords do not match')
        self.assertFalse(User.objects.filter(email='bad@test.com').exists())

    def test_register_short_password(self):
        resp = self.client.post('/auth/register/', {
            'email': 'short@test.com',
            'password': '1234567',
            'password2': '1234567',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'at least 8 characters')

    def test_register_duplicate_email(self):
        User.objects.create_user('dup@test.com', 'dup@test.com', 'testpass123')
        resp = self.client.post('/auth/register/', {
            'email': 'dup@test.com',
            'password': 'testpass123',
            'password2': 'testpass123',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists')

    def test_register_email_normalized_to_lowercase(self):
        self.client.post('/auth/register/', {
            'email': 'MiXeD@Test.COM',
            'password': 'testpass123',
            'password2': 'testpass123',
        })
        self.assertTrue(User.objects.filter(email='mixed@test.com').exists())

    def test_login_success(self):
        User.objects.create_user('user@test.com', 'user@test.com', 'testpass123')
        resp = self.client.post('/auth/login/', {
            'email': 'user@test.com',
            'password': 'testpass123',
        })
        self.assertEqual(resp.status_code, 302)

    def test_login_wrong_password(self):
        User.objects.create_user('user@test.com', 'user@test.com', 'testpass123')
        resp = self.client.post('/auth/login/', {
            'email': 'user@test.com',
            'password': 'wrong',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Invalid email or password')

    def test_logout(self):
        User.objects.create_user('user@test.com', 'user@test.com', 'testpass123')
        self.client.login(username='user@test.com', password='testpass123')
        resp = self.client.get('/auth/logout/')
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get('/')
        self.assertFalse(resp.wsgi_request.user.is_authenticated)

    def test_account_page_requires_login(self):
        resp = self.client.get('/auth/account/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/auth/login/', resp.url)

    def test_account_page_shows_plan(self):
        User.objects.create_user('user@test.com', 'user@test.com', 'testpass123')
        self.client.login(username='user@test.com', password='testpass123')
        resp = self.client.get('/auth/account/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Free')

    def test_profile_auto_created_on_user_save(self):
        user = User.objects.create_user('sig@test.com', 'sig@test.com', 'testpass123')
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)

    def test_register_redirects_when_already_authenticated(self):
        User.objects.create_user('user@test.com', 'user@test.com', 'testpass123')
        self.client.login(username='user@test.com', password='testpass123')
        resp = self.client.get('/auth/register/')
        self.assertEqual(resp.status_code, 302)


# ═══════════════════════════════════════════════════════════════════════════════
# Subscription & plan management
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class SubscriptionTests(TestCase):
    """Plan limits, upgrade effects, storage quota."""

    def setUp(self):
        self.user = User.objects.create_user('sub@test.com', 'sub@test.com', 'testpass123')
        self.profile = self.user.profile

    def test_free_plan_defaults(self):
        self.assertEqual(self.profile.plan, Plan.FREE)
        self.assertFalse(self.profile.is_paid)
        self.assertIsNone(self.profile.storage_quota_bytes)

    def test_upgrade_to_starter(self):
        self.profile.plan = Plan.STARTER
        self.profile.plan_since = timezone.now()
        self.profile.save()
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_paid)
        self.assertEqual(self.profile.storage_quota_gb, 5)
        self.assertEqual(self.profile.storage_quota_bytes, 5 * 1024 ** 3)

    def test_upgrade_to_pro(self):
        self.profile.plan = Plan.PRO
        self.profile.plan_since = timezone.now()
        self.profile.save()
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_paid)
        self.assertEqual(self.profile.storage_quota_gb, 20)

    def test_downgrade_to_free(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        self.profile.plan = Plan.FREE
        self.profile.plan_since = None
        self.profile.save()
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_paid)

    def test_storage_tracking(self):
        self.profile.plan = Plan.STARTER
        self.profile.storage_used_bytes = 1024 * 1024 * 100  # 100 MB
        self.profile.save()
        self.assertEqual(self.profile.storage_available_bytes(),
                         5 * 1024 ** 3 - 1024 * 1024 * 100)

    def test_storage_available_none_for_free(self):
        self.assertIsNone(self.profile.storage_available_bytes())

    def test_plan_limits_class(self):
        self.assertEqual(Plan.get(Plan.ANON, 'max_file_mb'), 200)
        self.assertEqual(Plan.get(Plan.FREE, 'max_file_mb'), 200)
        self.assertEqual(Plan.get(Plan.STARTER, 'max_file_mb'), 1024)
        self.assertEqual(Plan.get(Plan.PRO, 'max_file_mb'), 5120)
        self.assertEqual(Plan.get(Plan.STARTER, 'max_expiry_days'), 365)
        self.assertEqual(Plan.get(Plan.PRO, 'max_expiry_days'), 365 * 3)

    def test_paid_user_creates_locked_drop(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        self.client.login(username='sub@test.com', password='testpass123')
        resp = self.client.post('/save/', {
            'content': 'paid text',
            'expiry_days': '30',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        drop = Drop.objects.get(key=data['key'])
        self.assertTrue(drop.locked)
        self.assertIsNotNone(drop.expires_at)
        self.assertEqual(drop.owner, self.user)

    def test_paid_expiry_capped_to_plan_max(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        self.client.login(username='sub@test.com', password='testpass123')
        resp = self.client.post('/save/', {
            'content': 'capped',
            'expiry_days': '9999',
        })
        data = resp.json()
        drop = Drop.objects.get(key=data['key'])
        # Should be capped to 365 days (Starter max)
        max_delta = timedelta(days=365, seconds=5)  # small tolerance
        actual_delta = drop.expires_at - drop.created_at
        self.assertLessEqual(actual_delta, max_delta)

    def test_free_user_drop_not_locked(self):
        self.client.login(username='sub@test.com', password='testpass123')
        resp = self.client.post('/save/', {'content': 'free text'})
        data = resp.json()
        drop = Drop.objects.get(key=data['key'])
        self.assertFalse(drop.locked)

    def test_anon_drop_has_locked_until(self):
        resp = self.client.post('/save/', {'content': 'anon text'})
        data = resp.json()
        drop = Drop.objects.get(key=data['key'])
        self.assertIsNotNone(drop.locked_until)
        self.assertTrue(drop.is_creation_locked())

    @patch('billing.views.PLAN_VARIANT_IDS', {Plan.STARTER: 'var_s', Plan.PRO: 'var_p'})
    @override_settings(LEMONSQUEEZY_STORE_ID='teststore')
    def test_checkout_redirect_for_starter(self):
        self.client.login(username='sub@test.com', password='testpass123')
        resp = self.client.get('/billing/checkout/starter/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('lemonsqueezy.com', resp.url)

    @patch('billing.views.PLAN_VARIANT_IDS', {Plan.STARTER: 'var_s', Plan.PRO: 'var_p'})
    @override_settings(LEMONSQUEEZY_STORE_ID='teststore')
    def test_checkout_redirect_for_pro(self):
        self.client.login(username='sub@test.com', password='testpass123')
        resp = self.client.get('/billing/checkout/pro/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('lemonsqueezy.com', resp.url)

    def test_checkout_invalid_plan_redirects(self):
        self.client.login(username='sub@test.com', password='testpass123')
        resp = self.client.get('/billing/checkout/fake/')
        self.assertEqual(resp.status_code, 302)  # redirects to account

    def test_checkout_requires_login(self):
        resp = self.client.get('/billing/checkout/starter/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/auth/login/', resp.url)

    def test_drop_renewal(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        self.client.login(username='sub@test.com', password='testpass123')
        drop = Drop.objects.create(
            key='renew-me', kind=Drop.TEXT, content='hello',
            owner=self.user, locked=True,
            expires_at=timezone.now() + timedelta(days=30),
        )
        old_expiry = drop.expires_at
        resp = self.client.post(f'/{drop.key}/renew/')
        self.assertEqual(resp.status_code, 200)
        drop.refresh_from_db()
        self.assertGreater(drop.expires_at, old_expiry)
        self.assertEqual(drop.renewal_count, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# Payment webhooks (Lemon Squeezy)
# ═══════════════════════════════════════════════════════════════════════════════

WEBHOOK_SECRET = 'test-webhook-secret-1234'


def _signed_webhook(payload, secret=WEBHOOK_SECRET):
    """Build a signed webhook request body + signature header."""
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


def _subscription_payload(user_id, variant_id, status='active',
                           customer_id='cust_123', sub_id='sub_456',
                           event='subscription_created'):
    """Build a realistic Lemon Squeezy webhook payload."""
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
    """Lemon Squeezy webhook processing — signature verification, plan changes."""

    def setUp(self):
        self.user = User.objects.create_user('wh@test.com', 'wh@test.com', 'testpass123')
        self.profile = self.user.profile

    def _post_webhook(self, payload, secret=WEBHOOK_SECRET, event=None):
        body, sig = _signed_webhook(payload, secret)
        headers = {
            'HTTP_X_SIGNATURE': sig,
            'HTTP_X_EVENT_NAME': event or payload['meta']['event_name'],
            'content_type': 'application/json',
        }
        return self.client.post('/billing/webhook/', body, **headers)

    # ── Signature verification ────────────────────────────────────────────────

    def test_invalid_signature_rejected(self):
        payload = _subscription_payload(self.user.pk, 'variant_starter')
        body, _ = _signed_webhook(payload)
        resp = self.client.post('/billing/webhook/', body,
                                HTTP_X_SIGNATURE='bad-signature',
                                HTTP_X_EVENT_NAME='subscription_created',
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_missing_signature_rejected(self):
        payload = _subscription_payload(self.user.pk, 'variant_starter')
        body = json.dumps(payload).encode()
        resp = self.client.post('/billing/webhook/', body,
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    # ── Subscription created ──────────────────────────────────────────────────

    def test_subscription_created_starter(self):
        payload = _subscription_payload(
            self.user.pk, 'variant_starter',
            event='subscription_created',
        )
        resp = self._post_webhook(payload)
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.STARTER)
        self.assertEqual(self.profile.ls_customer_id, 'cust_123')
        self.assertEqual(self.profile.ls_subscription_id, 'sub_456')
        self.assertEqual(self.profile.ls_subscription_status, 'active')
        self.assertIsNotNone(self.profile.plan_since)

    def test_subscription_created_pro(self):
        payload = _subscription_payload(
            self.user.pk, 'variant_pro',
            event='subscription_created',
        )
        resp = self._post_webhook(payload)
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.PRO)

    # ── Subscription updated ──────────────────────────────────────────────────

    def test_subscription_updated_active(self):
        payload = _subscription_payload(
            self.user.pk, 'variant_pro',
            status='active',
            event='subscription_updated',
        )
        resp = self._post_webhook(payload)
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.PRO)

    def test_subscription_updated_unpaid_downgrades(self):
        # First activate
        self.profile.plan = Plan.STARTER
        self.profile.save()
        # Then go unpaid
        payload = _subscription_payload(
            self.user.pk, 'variant_starter',
            status='unpaid',
            event='subscription_updated',
        )
        resp = self._post_webhook(payload)
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.FREE)

    # ── Subscription cancelled ────────────────────────────────────────────────

    def test_subscription_cancelled_keeps_plan(self):
        """Cancelled = still active until period end, plan stays."""
        self.profile.plan = Plan.STARTER
        self.profile.ls_customer_id = 'cust_123'
        self.profile.save()
        payload = _subscription_payload(
            self.user.pk, 'variant_starter',
            status='cancelled',
            event='subscription_cancelled',
        )
        resp = self._post_webhook(payload)
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        # Plan should remain active
        self.assertEqual(self.profile.plan, Plan.STARTER)
        self.assertEqual(self.profile.ls_subscription_status, 'cancelled')

    # ── Subscription expired ──────────────────────────────────────────────────

    def test_subscription_expired_downgrades(self):
        self.profile.plan = Plan.PRO
        self.profile.ls_customer_id = 'cust_123'
        self.profile.save()
        payload = _subscription_payload(
            self.user.pk, 'variant_pro',
            status='expired',
            event='subscription_expired',
        )
        resp = self._post_webhook(payload)
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.FREE)
        self.assertIsNone(self.profile.plan_since)
        self.assertEqual(self.profile.ls_subscription_status, 'expired')

    # ── Fallback: lookup by customer ID ───────────────────────────────────────

    def test_webhook_finds_user_by_customer_id(self):
        """When user_id is missing, should fall back to ls_customer_id."""
        self.profile.ls_customer_id = 'cust_456'
        self.profile.save()
        payload = {
            'meta': {
                'event_name': 'subscription_updated',
                'custom_data': {},  # no user_id
            },
            'data': {
                'id': 'sub_789',
                'attributes': {
                    'customer_id': 'cust_456',
                    'variant_id': 'variant_pro',
                    'status': 'active',
                },
            },
        }
        resp = self._post_webhook(payload)
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.PRO)

    def test_webhook_unknown_user_returns_200(self):
        """Unknown user — return 200 so LS doesn't endlessly retry."""
        payload = _subscription_payload(
            99999, 'variant_starter',
            event='subscription_created',
        )
        resp = self._post_webhook(payload)
        self.assertEqual(resp.status_code, 200)

    # ── Bad request handling ──────────────────────────────────────────────────

    def test_webhook_bad_json(self):
        body = b'not json'
        sig = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        resp = self.client.post('/billing/webhook/', body,
                                HTTP_X_SIGNATURE=sig,
                                HTTP_X_EVENT_NAME='subscription_created',
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_webhook_get_not_allowed(self):
        resp = self.client.get('/billing/webhook/')
        self.assertEqual(resp.status_code, 405)


# ═══════════════════════════════════════════════════════════════════════════════
# Drop lifecycle (expiry, locking, deletion)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class DropLifecycleTests(TestCase):
    """Expiry, locking, deletion, storage accounting."""

    def setUp(self):
        self.user = User.objects.create_user('drop@test.com', 'drop@test.com', 'testpass123')
        self.profile = self.user.profile

    def test_text_drop_expires_after_24h(self):
        drop = Drop.objects.create(key='old-text', kind=Drop.TEXT, content='hi')
        # Fake old creation time
        Drop.objects.filter(pk=drop.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        drop.refresh_from_db()
        self.assertTrue(drop.is_expired())

    def test_text_drop_not_expired_within_24h(self):
        drop = Drop.objects.create(key='new-text', kind=Drop.TEXT, content='hi')
        self.assertFalse(drop.is_expired())

    def test_file_drop_expires_after_90d(self):
        drop = Drop.objects.create(key='old-file', kind=Drop.FILE, filename='f.txt')
        Drop.objects.filter(pk=drop.pk).update(
            created_at=timezone.now() - timedelta(days=91)
        )
        drop.refresh_from_db()
        self.assertTrue(drop.is_expired())

    def test_paid_drop_expires_at_set_date(self):
        drop = Drop.objects.create(
            key='paid', kind=Drop.TEXT, content='paid',
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertTrue(drop.is_expired())

    def test_paid_drop_not_expired_before_date(self):
        drop = Drop.objects.create(
            key='paid-ok', kind=Drop.TEXT, content='paid',
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.assertFalse(drop.is_expired())

    def test_locked_drop_edit_by_owner_only(self):
        drop = Drop.objects.create(
            key='locked', kind=Drop.TEXT, content='mine',
            owner=self.user, locked=True,
        )
        other = User.objects.create_user('other@test.com', 'other@test.com', 'testpass123')
        self.assertTrue(drop.can_edit(self.user))
        self.assertFalse(drop.can_edit(other))

    def test_hard_delete_updates_storage(self):
        self.profile.plan = Plan.STARTER
        self.profile.storage_used_bytes = 5000
        self.profile.save()
        drop = Drop.objects.create(
            key='del', kind=Drop.FILE,
            owner=self.user, filesize=5000,
        )
        drop.hard_delete()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.storage_used_bytes, 0)

    def test_expired_drop_removed_on_view(self):
        drop = Drop.objects.create(key='exp-view', kind=Drop.TEXT, content='hi')
        Drop.objects.filter(pk=drop.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        resp = self.client.get('/exp-view/')
        self.assertEqual(resp.status_code, 200)  # renders expired.html
        self.assertFalse(Drop.objects.filter(key='exp-view').exists())

    def test_drop_renewal_extends_expiry(self):
        drop = Drop.objects.create(
            key='ren', kind=Drop.TEXT, content='hi',
            owner=self.user,
            expires_at=timezone.now() + timedelta(days=10),
        )
        drop.renew()
        drop.refresh_from_db()
        self.assertEqual(drop.renewal_count, 1)
        # New expiry should be in the future beyond the old one
        self.assertGreater(drop.expires_at, timezone.now() + timedelta(days=9))