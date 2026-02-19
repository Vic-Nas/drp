"""
Server-side tests: account auth, drop lifecycle, plan entitlements, cleanup, webhooks.
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

_STATIC = override_settings(
    STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage'
)


# ═══════════════════════════════════════════════════════════════════════════════
# Auth
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC
class AuthTests(TestCase):

    def test_register_creates_user_on_free_plan(self):
        self.client.post('/auth/register/', {
            'email': 'new@test.com', 'password': 'testpass123', 'password2': 'testpass123',
        })
        user = User.objects.get(email='new@test.com')
        self.assertEqual(user.profile.plan, Plan.FREE)

    def test_register_logs_in_and_redirects(self):
        resp = self.client.post('/auth/register/', {
            'email': 'redir@test.com', 'password': 'testpass123', 'password2': 'testpass123',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.wsgi_request.user.is_authenticated)

    def test_register_rejects_password_mismatch(self):
        resp = self.client.post('/auth/register/', {
            'email': 'bad@test.com', 'password': 'testpass123', 'password2': 'different456',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email='bad@test.com').exists())

    def test_register_rejects_short_password(self):
        resp = self.client.post('/auth/register/', {
            'email': 'short@test.com', 'password': '1234567', 'password2': '1234567',
        })
        self.assertFalse(User.objects.filter(email='short@test.com').exists())

    def test_register_rejects_duplicate_email(self):
        User.objects.create_user('dup@test.com', 'dup@test.com', 'testpass123')
        self.client.post('/auth/register/', {
            'email': 'dup@test.com', 'password': 'testpass123', 'password2': 'testpass123',
        })
        self.assertEqual(User.objects.filter(email='dup@test.com').count(), 1)

    def test_register_normalizes_email_to_lowercase(self):
        self.client.post('/auth/register/', {
            'email': 'MiXeD@Test.COM', 'password': 'testpass123', 'password2': 'testpass123',
        })
        self.assertTrue(User.objects.filter(email='mixed@test.com').exists())

    def test_login_valid_credentials_redirects(self):
        User.objects.create_user('u@test.com', 'u@test.com', 'testpass123')
        resp = self.client.post('/auth/login/', {'email': 'u@test.com', 'password': 'testpass123'})
        self.assertEqual(resp.status_code, 302)

    def test_login_wrong_password_stays_on_form(self):
        User.objects.create_user('u@test.com', 'u@test.com', 'testpass123')
        resp = self.client.post('/auth/login/', {'email': 'u@test.com', 'password': 'wrong'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.wsgi_request.user.is_authenticated)

    def test_account_redirects_when_not_logged_in(self):
        resp = self.client.get('/auth/account/')
        self.assertRedirects(resp, '/auth/login/?next=/auth/account/', fetch_redirect_response=False)

    def test_profile_created_automatically_via_signal(self):
        user = User.objects.create_user('sig@test.com', 'sig@test.com', 'testpass123')
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)


# ═══════════════════════════════════════════════════════════════════════════════
# Plan entitlements
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC
class PlanEntitlementTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('plan@test.com', 'plan@test.com', 'testpass123')
        self.profile = self.user.profile
        self.client.login(username='plan@test.com', password='testpass123')

    def test_starter_storage_quota_is_5gb(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        self.assertEqual(self.profile.storage_quota_bytes, 5 * 1024 ** 3)

    def test_pro_storage_quota_is_20gb(self):
        self.profile.plan = Plan.PRO
        self.profile.save()
        self.assertEqual(self.profile.storage_quota_bytes, 20 * 1024 ** 3)

    def test_free_plan_has_no_storage_quota(self):
        self.assertIsNone(self.profile.storage_quota_bytes)

    def test_paid_drop_is_locked_to_owner(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        resp = self.client.post('/save/', {'content': 'paid text', 'expiry_days': '30'})
        drop = Drop.objects.get(key=resp.json()['key'])
        self.assertTrue(drop.locked)
        self.assertEqual(drop.owner, self.user)

    def test_expiry_capped_at_plan_max(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        resp = self.client.post('/save/', {'content': 'capped', 'expiry_days': '9999'})
        drop = Drop.objects.get(key=resp.json()['key'])
        delta = drop.expires_at - drop.created_at
        self.assertLessEqual(delta.days, Plan.get(Plan.STARTER, 'max_expiry_days'))

    def test_free_user_drop_has_no_expires_at(self):
        resp = self.client.post('/save/', {'content': 'free text'})
        drop = Drop.objects.get(key=resp.json()['key'])
        self.assertIsNone(drop.expires_at)

    def test_anon_drop_has_24h_creation_lock(self):
        self.client.logout()
        resp = self.client.post('/save/', {'content': 'anon'})
        drop = Drop.objects.get(key=resp.json()['key'])
        self.assertTrue(drop.is_creation_locked())

    def test_renewal_extends_expiry(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        original = timezone.now() + timedelta(days=10)
        drop = Drop.objects.create(
            key='renew-me', kind=Drop.TEXT, content='hi',
            owner=self.user, locked=True, expires_at=original,
        )
        resp = self.client.post(f'/{drop.key}/renew/')
        self.assertEqual(resp.status_code, 200)
        drop.refresh_from_db()
        self.assertGreater(drop.expires_at, original)

    def test_free_plan_drop_cannot_be_renewed(self):
        drop = Drop.objects.create(
            key='norenewal', kind=Drop.TEXT, content='hi', owner=self.user,
        )
        resp = self.client.post(f'/{drop.key}/renew/')
        self.assertNotEqual(resp.status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════════
# Drop lifecycle & URLs
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC
class DropLifecycleTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('drop@test.com', 'drop@test.com', 'testpass123')

    def test_clipboard_accessible_at_slash_key(self):
        Drop.objects.create(ns='c', key='hello', kind=Drop.TEXT, content='hi')
        resp = self.client.get('/hello/')
        self.assertEqual(resp.status_code, 200)

    def test_file_accessible_at_f_slash_key(self):
        Drop.objects.create(ns='f', key='report', kind=Drop.FILE, filename='r.pdf',
                            file_url='https://example.com/r.pdf')
        resp = self.client.get('/f/report/')
        self.assertEqual(resp.status_code, 200)

    def test_clipboard_not_accessible_at_f_prefix(self):
        Drop.objects.create(ns='c', key='clip', kind=Drop.TEXT, content='hi')
        resp = self.client.get('/f/clip/')
        self.assertEqual(resp.status_code, 404)

    def test_expired_clipboard_returns_410_on_json_request(self):
        drop = Drop.objects.create(ns='c', key='exp', kind=Drop.TEXT, content='x')
        Drop.objects.filter(pk=drop.pk).update(created_at=timezone.now() - timedelta(hours=25))
        resp = self.client.get('/exp/', HTTP_ACCEPT='application/json')
        self.assertEqual(resp.status_code, 410)

    def test_expired_drop_is_deleted_on_view(self):
        drop = Drop.objects.create(ns='c', key='gone', kind=Drop.TEXT, content='x')
        Drop.objects.filter(pk=drop.pk).update(created_at=timezone.now() - timedelta(hours=25))
        self.client.get('/gone/')
        self.assertFalse(Drop.objects.filter(key='gone').exists())

    def test_anon_cannot_delete_locked_drop(self):
        drop = Drop.objects.create(
            ns='c', key='locked', kind=Drop.TEXT, content='x',
            owner=self.user, locked=True,
        )
        resp = self.client.delete(
            f'/{drop.key}/delete/',
            HTTP_X_CSRFTOKEN=self.client.cookies.get('csrftoken', ''),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Drop.objects.filter(key='locked').exists())

    def test_owner_can_delete_own_drop(self):
        self.client.login(username='drop@test.com', password='testpass123')
        drop = Drop.objects.create(
            ns='c', key='mine', kind=Drop.TEXT, content='x',
            owner=self.user, locked=True,
        )
        resp = self.client.delete(
            f'/{drop.key}/delete/',
            HTTP_X_CSRFTOKEN='test',
            content_type='application/json',
        )
        # Re-login to get CSRF properly
        self.client.force_login(self.user)
        self.client.get('/')  # get csrf
        resp = self.client.delete(f'/{drop.key}/delete/')
        self.assertFalse(Drop.objects.filter(key='mine').exists())

    def test_rename_to_taken_key_returns_409(self):
        self.client.force_login(self.user)
        Drop.objects.create(ns='c', key='taken', kind=Drop.TEXT, content='a',
                            owner=self.user, locked=True)
        Drop.objects.create(ns='c', key='source', kind=Drop.TEXT, content='b',
                            owner=self.user, locked=True)
        resp = self.client.post('/source/rename/', {'new_key': 'taken'})
        self.assertEqual(resp.status_code, 409)

    def test_anon_drop_locked_24h_then_renameable(self):
        resp = self.client.post('/save/', {'content': 'anon', 'key': 'anonkey'})
        # Within lock window — rename blocked
        resp2 = self.client.post('/anonkey/rename/', {'new_key': 'newkey'})
        self.assertEqual(resp2.status_code, 403)
        # Expire the lock
        Drop.objects.filter(key='anonkey').update(
            locked_until=timezone.now() - timedelta(hours=1)
        )
        resp3 = self.client.post('/anonkey/rename/', {'new_key': 'newkey'})
        self.assertEqual(resp3.status_code, 200)

    def test_hard_delete_removes_drop_and_reduces_storage(self):
        self.user.profile.plan = Plan.STARTER
        self.user.profile.storage_used_bytes = 5000
        self.user.profile.save()
        drop = Drop.objects.create(
            ns='f', key='storedrop', kind=Drop.FILE,
            owner=self.user, filesize=5000,
        )
        drop.hard_delete()
        self.assertFalse(Drop.objects.filter(key='storedrop').exists())
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.storage_used_bytes, 0)

    def test_is_expired_clipboard_after_24h(self):
        drop = Drop.objects.create(ns='c', key='old', kind=Drop.TEXT, content='x')
        Drop.objects.filter(pk=drop.pk).update(created_at=timezone.now() - timedelta(hours=25))
        drop.refresh_from_db()
        self.assertTrue(drop.is_expired())

    def test_is_not_expired_clipboard_at_23h(self):
        drop = Drop.objects.create(ns='c', key='new', kind=Drop.TEXT, content='x')
        Drop.objects.filter(pk=drop.pk).update(created_at=timezone.now() - timedelta(hours=23))
        drop.refresh_from_db()
        self.assertFalse(drop.is_expired())

    def test_is_expired_file_after_90d(self):
        drop = Drop.objects.create(ns='f', key='oldfile', kind=Drop.FILE, filename='f.txt')
        Drop.objects.filter(pk=drop.pk).update(created_at=timezone.now() - timedelta(days=91))
        drop.refresh_from_db()
        self.assertTrue(drop.is_expired())

    def test_paid_drop_not_expired_before_expires_at(self):
        drop = Drop.objects.create(
            ns='c', key='paid', kind=Drop.TEXT, content='x',
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.assertFalse(drop.is_expired())

    def test_can_edit_locked_by_owner_only(self):
        drop = Drop.objects.create(
            ns='c', key='owned', kind=Drop.TEXT, content='x',
            owner=self.user, locked=True,
        )
        other = User.objects.create_user('other@test.com', 'other@test.com', 'pass1234')
        self.assertTrue(drop.can_edit(self.user))
        self.assertFalse(drop.can_edit(other))

    def test_check_key_available(self):
        resp = self.client.get('/check-key/?key=brandnew&ns=c')
        self.assertTrue(resp.json()['available'])

    def test_check_key_taken(self):
        Drop.objects.create(ns='c', key='existing', kind=Drop.TEXT, content='x')
        resp = self.client.get('/check-key/?key=existing&ns=c')
        self.assertFalse(resp.json()['available'])


# ═══════════════════════════════════════════════════════════════════════════════
# Cleanup command
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC
class CleanupCommandTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('clean@test.com', 'clean@test.com', 'testpass123')
        from django.core.management import call_command
        self._cleanup = lambda: call_command('cleanup')

    def test_fresh_drops_survive(self):
        Drop.objects.create(ns='c', key='fresh-txt', kind=Drop.TEXT, content='hi')
        Drop.objects.create(ns='f', key='fresh-file', kind=Drop.FILE, filename='f.txt')
        self._cleanup()
        self.assertTrue(Drop.objects.filter(key='fresh-txt').exists())
        self.assertTrue(Drop.objects.filter(key='fresh-file').exists())

    def test_expired_drops_deleted(self):
        d_txt = Drop.objects.create(ns='c', key='old-txt', kind=Drop.TEXT, content='x')
        Drop.objects.filter(pk=d_txt.pk).update(created_at=timezone.now() - timedelta(hours=25))
        d_file = Drop.objects.create(ns='f', key='old-file', kind=Drop.FILE, filename='f.txt')
        Drop.objects.filter(pk=d_file.pk).update(created_at=timezone.now() - timedelta(days=91))
        self._cleanup()
        self.assertFalse(Drop.objects.filter(key='old-txt').exists())
        self.assertFalse(Drop.objects.filter(key='old-file').exists())

    def test_paid_drop_before_expiry_survives(self):
        Drop.objects.create(
            ns='c', key='paid-safe', kind=Drop.TEXT, content='x',
            owner=self.user, expires_at=timezone.now() + timedelta(days=180),
        )
        self._cleanup()
        self.assertTrue(Drop.objects.filter(key='paid-safe').exists())

    def test_paid_drop_after_expiry_deleted(self):
        Drop.objects.create(
            ns='c', key='paid-exp', kind=Drop.TEXT, content='x',
            owner=self.user, expires_at=timezone.now() - timedelta(seconds=1),
        )
        self._cleanup()
        self.assertFalse(Drop.objects.filter(key='paid-exp').exists())

    def test_cleanup_reduces_owner_storage_for_expired_file(self):
        self.user.profile.plan = Plan.STARTER
        self.user.profile.storage_used_bytes = 8192
        self.user.profile.save()
        Drop.objects.create(
            ns='f', key='store-exp', kind=Drop.FILE, filename='s.txt',
            owner=self.user, filesize=8192,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self._cleanup()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.storage_used_bytes, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Export
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC
class ExportTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('exp@test.com', 'exp@test.com', 'testpass123')
        self.client.force_login(self.user)

    def test_export_requires_login(self):
        self.client.logout()
        resp = self.client.get('/auth/account/export/', follow=False)
        self.assertIn(resp.status_code, (302, 403))

    def test_export_contains_own_drops_only(self):
        Drop.objects.create(ns='c', key='mine', kind=Drop.TEXT, content='x', owner=self.user)
        other = User.objects.create_user('o@test.com', 'o@test.com', 'pass1234')
        Drop.objects.create(ns='c', key='theirs', kind=Drop.TEXT, content='y', owner=other)
        resp = self.client.get('/auth/account/export/')
        keys = [d['key'] for d in resp.json()['drops']]
        self.assertIn('mine', keys)
        self.assertNotIn('theirs', keys)

    def test_export_drop_has_required_fields(self):
        Drop.objects.create(ns='c', key='exptest', kind=Drop.TEXT, content='x', owner=self.user)
        resp = self.client.get('/auth/account/export/')
        drop = next(d for d in resp.json()['drops'] if d['key'] == 'exptest')
        for field in ('key', 'kind', 'url', 'host', 'created_at'):
            self.assertIn(field, drop)


# ═══════════════════════════════════════════════════════════════════════════════
# Payment webhooks
# ═══════════════════════════════════════════════════════════════════════════════

WEBHOOK_SECRET = 'test-webhook-secret-1234'


def _make_webhook(payload, secret=WEBHOOK_SECRET):
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


def _sub_payload(user_id, variant_id, status='active',
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

    def test_bad_signature_returns_400_and_does_not_change_plan(self):
        payload = _sub_payload(self.user.pk, 'variant_pro')
        body, _ = _make_webhook(payload)
        self.client.post('/billing/webhook/', body, HTTP_X_SIGNATURE='bad',
                         content_type='application/json')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.FREE)

    def test_subscription_created_upgrades_plan_and_stores_ids(self):
        payload = _sub_payload(self.user.pk, 'variant_starter',
                               customer_id='cust_abc', sub_id='sub_xyz')
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.STARTER)
        self.assertEqual(self.profile.ls_customer_id, 'cust_abc')
        self.assertEqual(self.profile.ls_subscription_id, 'sub_xyz')

    def test_subscription_updated_unpaid_downgrades_to_free(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        resp = self._post(_sub_payload(self.user.pk, 'variant_starter',
                                       status='unpaid', event='subscription_updated'))
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.FREE)

    def test_subscription_expired_downgrades_and_clears_plan_since(self):
        self.profile.plan = Plan.PRO
        self.profile.plan_since = timezone.now() - timedelta(days=365)
        self.profile.save()
        self._post(_sub_payload(self.user.pk, 'variant_pro',
                                status='expired', event='subscription_expired'))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.FREE)
        self.assertIsNone(self.profile.plan_since)

    def test_subscription_cancelled_records_status_without_downgrade(self):
        self.profile.plan = Plan.STARTER
        self.profile.save()
        self._post(_sub_payload(self.user.pk, 'variant_starter',
                                status='cancelled', event='subscription_cancelled'))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.ls_subscription_status, 'cancelled')
        self.assertEqual(self.profile.plan, Plan.STARTER)  # still active until period end

    def test_webhook_finds_user_by_customer_id_fallback(self):
        self.profile.ls_customer_id = 'cust_fallback'
        self.profile.save()
        payload = {
            'meta': {'event_name': 'subscription_updated', 'custom_data': {}},
            'data': {
                'id': 'sub_789',
                'attributes': {'customer_id': 'cust_fallback',
                               'variant_id': 'variant_pro', 'status': 'active'},
            },
        }
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, Plan.PRO)

    def test_webhook_unknown_user_returns_200_without_side_effects(self):
        before = UserProfile.objects.count()
        resp = self._post(_sub_payload(99999, 'variant_starter'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(UserProfile.objects.count(), before)

    @patch('billing.views.PLAN_VARIANT_IDS', {Plan.STARTER: 'var_s', Plan.PRO: 'var_p'})
    @override_settings(LEMONSQUEEZY_STORE_ID='teststore')
    def test_checkout_redirects_to_lemonsqueezy(self):
        self.client.login(username='wh@test.com', password='testpass123')
        resp = self.client.get('/billing/checkout/starter/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('lemonsqueezy.com', resp.url)

    def test_checkout_requires_login(self):
        resp = self.client.get('/billing/checkout/starter/')
        self.assertRedirects(resp, '/auth/login/?next=/billing/checkout/starter/',
                             fetch_redirect_response=False)