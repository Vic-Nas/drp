"""
CLI tests — config, local cache, slug, and API integration.

Rules followed here:
- Config/slug/cache tests use plain TestCase (no server needed)
- API tests use LiveServerTestCase (real HTTP against a real Django instance)
- Every test asserts a specific, meaningful behavior
- No test passes vacuously
"""

import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path

import requests
from django.contrib.auth.models import User
from django.test import LiveServerTestCase, TestCase, override_settings
from django.utils import timezone

from cli import api, config

_STATIC_OVERRIDE = override_settings(
    STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage'
)


# ═══════════════════════════════════════════════════════════════════════════════
# Config  (no server needed — plain TestCase)
# ═══════════════════════════════════════════════════════════════════════════════

class ConfigTests(TestCase):

    def test_load_missing_file_returns_empty_dict(self):
        self.assertEqual(config.load('/tmp/drp_no_such_file_xyz.json'), {})

    def test_save_and_load_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            cfg = {'host': 'https://example.com', 'email': 'a@b.com'}
            config.save(cfg, path)
            self.assertEqual(config.load(path), cfg)
        finally:
            os.unlink(path)

    def test_save_creates_missing_parent_directories(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'sub', 'nested', 'config.json')
            config.save({'host': 'x'}, path)
            self.assertTrue(os.path.exists(path))

    def test_save_overwrites_existing_file(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            config.save({'host': 'old'}, path)
            config.save({'host': 'new'}, path)
            self.assertEqual(config.load(path)['host'], 'new')
        finally:
            os.unlink(path)

    def test_load_returns_all_saved_keys(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            cfg = {'host': 'h', 'email': 'e@e.com', 'extra': 'val'}
            config.save(cfg, path)
            loaded = config.load(path)
            self.assertEqual(loaded['extra'], 'val')
        finally:
            os.unlink(path)


# ═══════════════════════════════════════════════════════════════════════════════
# Local drop cache  (no server needed — plain TestCase)
# ═══════════════════════════════════════════════════════════════════════════════

class LocalDropCacheTests(TestCase):
    """
    Tests that the local JSON cache of drops is managed correctly.
    This cache is what anonymous users see in `drp ls`.
    """

    def setUp(self):
        self._orig_drops_file = config.DROPS_FILE
        config.DROPS_FILE = Path(tempfile.mktemp(suffix='.json'))

    def tearDown(self):
        if config.DROPS_FILE.exists():
            config.DROPS_FILE.unlink()
        config.DROPS_FILE = self._orig_drops_file

    def test_load_returns_empty_list_when_file_missing(self):
        self.assertEqual(config.load_local_drops(), [])

    def test_record_drop_appears_in_list(self):
        config.record_drop('k1', 'text', host='https://example.com')
        drops = config.load_local_drops()
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0]['key'], 'k1')
        self.assertEqual(drops[0]['kind'], 'text')

    def test_record_file_drop_stores_filename(self):
        config.record_drop('f1', 'file', filename='report.pdf', host='https://example.com')
        drops = config.load_local_drops()
        self.assertEqual(drops[0]['filename'], 'report.pdf')

    def test_record_same_key_twice_does_not_duplicate(self):
        config.record_drop('k', 'text', host='https://example.com')
        config.record_drop('k', 'text', host='https://example.com')
        self.assertEqual(len(config.load_local_drops()), 1)

    def test_record_multiple_different_keys(self):
        config.record_drop('a', 'text', host='https://example.com')
        config.record_drop('b', 'file', filename='x.txt', host='https://example.com')
        self.assertEqual(len(config.load_local_drops()), 2)

    def test_remove_drop_removes_only_target(self):
        config.record_drop('keep', 'text', host='https://example.com')
        config.record_drop('remove', 'text', host='https://example.com')
        config.remove_local_drop('remove')
        keys = [d['key'] for d in config.load_local_drops()]
        self.assertIn('keep', keys)
        self.assertNotIn('remove', keys)

    def test_remove_nonexistent_key_does_not_crash(self):
        config.record_drop('k', 'text', host='https://example.com')
        config.remove_local_drop('no-such-key')  # should not raise
        self.assertEqual(len(config.load_local_drops()), 1)

    def test_rename_drop_updates_key(self):
        config.record_drop('old', 'text', host='https://example.com')
        config.rename_local_drop('old', 'new')
        keys = [d['key'] for d in config.load_local_drops()]
        self.assertIn('new', keys)
        self.assertNotIn('old', keys)

    def test_rename_drop_preserves_other_fields(self):
        config.record_drop('old', 'file', filename='data.csv', host='https://example.com')
        config.rename_local_drop('old', 'new')
        drop = config.load_local_drops()[0]
        self.assertEqual(drop['filename'], 'data.csv')
        self.assertEqual(drop['kind'], 'file')

    def test_host_stored_per_drop(self):
        """Each drop must remember which host it came from for multi-host setups."""
        config.record_drop('k', 'text', host='https://myhost.com')
        drop = config.load_local_drops()[0]
        self.assertEqual(drop['host'], 'https://myhost.com')


# ═══════════════════════════════════════════════════════════════════════════════
# Slug  (pure string logic — plain TestCase)
# ═══════════════════════════════════════════════════════════════════════════════

class SlugTests(TestCase):

    def test_strips_extension(self):
        self.assertEqual(api.slug('notes.txt'), 'notes')

    def test_spaces_become_hyphens(self):
        self.assertEqual(api.slug('my cool file.pdf'), 'my-cool-file')

    def test_special_chars_removed(self):
        result = api.slug('hello@world!.py')
        self.assertNotIn('@', result)
        self.assertNotIn('!', result)

    def test_long_name_truncated_to_reasonable_length(self):
        result = api.slug('a' * 100 + '.txt')
        self.assertLessEqual(len(result), 40)
        self.assertGreater(len(result), 0)  # not empty

    def test_dotfile_produces_nonempty_slug(self):
        # .bashrc has no meaningful stem — should fall back to something
        self.assertGreater(len(api.slug('.bashrc')), 0)

    def test_unicode_filename_safe(self):
        # Should not crash and should produce a non-empty ASCII slug
        result = api.slug('résumé.pdf')
        self.assertGreater(len(result), 0)

    def test_slug_only_contains_safe_chars(self):
        result = api.slug('hello world (copy) [2].txt')
        for ch in result:
            self.assertTrue(ch.isalnum() or ch == '-',
                            f'Unsafe character in slug: {ch!r}')


# ═══════════════════════════════════════════════════════════════════════════════
# API – Auth  (needs live server)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class AuthApiTests(LiveServerTestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='cli@test.com', email='cli@test.com', password='pass1234'
        )
        self.session = requests.Session()

    def test_csrf_token_is_nonempty_string(self):
        token = api.get_csrf(self.live_server_url, self.session)
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 10)

    def test_login_success_returns_true(self):
        self.assertTrue(api.login(self.live_server_url, self.session, 'cli@test.com', 'pass1234'))

    def test_login_success_sets_sessionid_cookie(self):
        api.login(self.live_server_url, self.session, 'cli@test.com', 'pass1234')
        self.assertIn('sessionid', self.session.cookies)

    def test_login_wrong_password_returns_false(self):
        self.assertFalse(api.login(self.live_server_url, self.session, 'cli@test.com', 'WRONG'))

    def test_login_wrong_password_sets_no_sessionid(self):
        api.login(self.live_server_url, self.session, 'cli@test.com', 'WRONG')
        self.assertNotIn('sessionid', self.session.cookies)

    def test_login_nonexistent_user_returns_false(self):
        self.assertFalse(api.login(self.live_server_url, self.session, 'no@one.com', 'pass'))


# ═══════════════════════════════════════════════════════════════════════════════
# API – Anonymous text drops  (needs live server)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class AnonTextDropTests(LiveServerTestCase):

    def setUp(self):
        self.session = requests.Session()
        self.host = self.live_server_url

    def test_upload_text_returns_a_key(self):
        key = api.upload_text(self.host, self.session, 'hello world')
        self.assertIsNotNone(key)
        self.assertGreater(len(key), 0)

    def test_upload_text_with_custom_key_returns_that_key(self):
        key = api.upload_text(self.host, self.session, 'custom', key='mykey')
        self.assertEqual(key, 'mykey')

    def test_get_text_drop_returns_exact_content(self):
        content = 'exact content round-trip check'
        key = api.upload_text(self.host, self.session, content)
        kind, result = api.get_drop(self.host, self.session, key)
        self.assertEqual(kind, 'text')
        self.assertEqual(result, content)

    def test_get_nonexistent_key_returns_none_none(self):
        kind, content = api.get_drop(self.host, self.session, 'no-such-key-xyz')
        self.assertIsNone(kind)
        self.assertIsNone(content)

    def test_delete_text_drop_succeeds(self):
        key = api.upload_text(self.host, self.session, 'bye')
        self.assertTrue(api.delete(self.host, self.session, key))

    def test_deleted_drop_no_longer_exists(self):
        key = api.upload_text(self.host, self.session, 'gone')
        api.delete(self.host, self.session, key)
        self.assertFalse(api.key_exists(self.host, self.session, key))

    def test_delete_nonexistent_key_returns_false(self):
        self.assertFalse(api.delete(self.host, self.session, 'no-such-key-xyz'))

    def test_key_exists_true_after_upload(self):
        api.upload_text(self.host, self.session, 'present', key='present-key')
        self.assertTrue(api.key_exists(self.host, self.session, 'present-key'))

    def test_key_exists_false_for_missing_key(self):
        self.assertFalse(api.key_exists(self.host, self.session, 'definitely-missing'))

    def test_overwrite_locked_anon_drop_is_rejected(self):
        """Second session cannot overwrite an anon drop within 24h lock window."""
        key = api.upload_text(self.host, self.session, 'original', key='locked-anon')
        other = requests.Session()
        result = api.upload_text(self.host, other, 'overwrite', key='locked-anon')
        # Upload must either fail (None) or the content must be unchanged
        self.assertIsNone(result, 'Overwrite of locked anon drop should be rejected')

    def test_overwrite_after_lock_expires_succeeds(self):
        """After 24h, any session can claim an expired/deleted key."""
        from core.models import Drop
        api.upload_text(self.host, self.session, 'original', key='unlocked-anon')
        # Expire the lock by backdating locked_until
        Drop.objects.filter(key='unlocked-anon').update(
            locked_until=timezone.now() - timedelta(hours=1)
        )
        other = requests.Session()
        result = api.upload_text(self.host, other, 'new content', key='unlocked-anon')
        self.assertIsNotNone(result)


# ═══════════════════════════════════════════════════════════════════════════════
# API – Anonymous file drops  (needs live server)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class AnonFileDropTests(LiveServerTestCase):

    def setUp(self):
        self.session = requests.Session()
        self.host = self.live_server_url

    def _make_tmp_file(self, content=b'test file content', suffix='.txt'):
        f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        f.write(content)
        f.flush()
        f.close()
        return f.name

    def test_upload_file_returns_key(self):
        path = self._make_tmp_file()
        try:
            key = api.upload_file(self.host, self.session, path, key='uptest')
            self.assertEqual(key, 'uptest')
        finally:
            os.unlink(path)

    def test_get_file_drop_returns_correct_bytes(self):
        content = b'exact binary content check'
        path = self._make_tmp_file(content=content)
        try:
            key = api.upload_file(self.host, self.session, path, key='binfile')
            kind, result = api.get_drop(self.host, self.session, key)
            self.assertEqual(kind, 'file')
            data, _ = result
            self.assertEqual(data, content)
        finally:
            os.unlink(path)

    def test_get_file_drop_returns_original_filename(self):
        path = self._make_tmp_file(suffix='.pdf')
        basename = os.path.basename(path)
        try:
            key = api.upload_file(self.host, self.session, path, key='namedfile')
            kind, result = api.get_drop(self.host, self.session, key)
            _, filename = result
            self.assertEqual(filename, basename)
        finally:
            os.unlink(path)

    def test_auto_key_derived_from_filename_stem(self):
        """Without -k, key should come from the filename slug."""
        path = self._make_tmp_file(suffix='.csv')
        stem = api.slug(os.path.basename(path))
        try:
            key = api.upload_file(self.host, self.session, path)
            self.assertEqual(key, stem)
        finally:
            os.unlink(path)


# ═══════════════════════════════════════════════════════════════════════════════
# API – Authenticated drops  (needs live server)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class AuthDropApiTests(LiveServerTestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='auth@test.com', email='auth@test.com', password='pass1234'
        )
        self.session = requests.Session()
        self.host = self.live_server_url
        api.login(self.host, self.session, 'auth@test.com', 'pass1234')

    # ── Upload & get ──────────────────────────────────────────────────────────

    def test_upload_text_as_logged_in_user(self):
        key = api.upload_text(self.host, self.session, 'logged in text', key='authtext')
        self.assertEqual(key, 'authtext')

    def test_uploaded_drop_is_owned_by_user(self):
        from core.models import Drop
        api.upload_text(self.host, self.session, 'owned', key='ownedrop')
        drop = Drop.objects.get(key='ownedrop')
        self.assertEqual(drop.owner, self.user)

    def test_uploaded_drop_is_locked_to_owner(self):
        from core.models import Drop
        api.upload_text(self.host, self.session, 'locked', key='lockedrop')
        drop = Drop.objects.get(key='lockedrop')
        self.assertTrue(drop.locked)

    def test_get_own_drop_returns_content(self):
        api.upload_text(self.host, self.session, 'my content', key='mything')
        kind, content = api.get_drop(self.host, self.session, 'mything')
        self.assertEqual(kind, 'text')
        self.assertEqual(content, 'my content')

    # ── Delete ────────────────────────────────────────────────────────────────

    def test_owner_can_delete_own_drop(self):
        api.upload_text(self.host, self.session, 'delete me', key='todel')
        self.assertTrue(api.delete(self.host, self.session, 'todel'))
        self.assertFalse(api.key_exists(self.host, self.session, 'todel'))

    def test_anon_cannot_delete_locked_drop(self):
        api.upload_text(self.host, self.session, 'protected', key='protdrop')
        anon = requests.Session()
        self.assertFalse(api.delete(self.host, anon, 'protdrop'))
        # Drop still exists
        self.assertTrue(api.key_exists(self.host, self.session, 'protdrop'))

    def test_other_user_cannot_delete_locked_drop(self):
        api.upload_text(self.host, self.session, 'mine', key='minedrop')
        other_session = requests.Session()
        User.objects.create_user('other@test.com', 'other@test.com', 'pass1234')
        api.login(self.host, other_session, 'other@test.com', 'pass1234')
        self.assertFalse(api.delete(self.host, other_session, 'minedrop'))

    # ── Rename ────────────────────────────────────────────────────────────────

    def test_owner_can_rename_drop(self):
        api.upload_text(self.host, self.session, 'hi', key='fromkey')
        new_key = api.rename(self.host, self.session, 'fromkey', 'tokey')
        self.assertEqual(new_key, 'tokey')
        self.assertFalse(api.key_exists(self.host, self.session, 'fromkey'))
        self.assertTrue(api.key_exists(self.host, self.session, 'tokey'))

    def test_rename_to_taken_key_fails(self):
        api.upload_text(self.host, self.session, 'a', key='taken')
        api.upload_text(self.host, self.session, 'b', key='source')
        result = api.rename(self.host, self.session, 'source', 'taken')
        self.assertIsNone(result)
        # Original still exists under old key
        self.assertTrue(api.key_exists(self.host, self.session, 'source'))

    def test_anon_drop_rename_blocked_within_24h(self):
        anon = requests.Session()
        api.upload_text(self.host, anon, 'anon', key='anonrename')
        result = api.rename(self.host, anon, 'anonrename', 'anonrenamed')
        self.assertIsNone(result)
        # Must still be accessible under the original key
        self.assertTrue(api.key_exists(self.host, anon, 'anonrename'))

    def test_anon_drop_rename_allowed_after_24h(self):
        """After the 24h window, anon user can rename their own drop."""
        from core.models import Drop
        anon = requests.Session()
        api.upload_text(self.host, anon, 'anon', key='anonold')
        Drop.objects.filter(key='anonold').update(
            locked_until=timezone.now() - timedelta(hours=1)
        )
        result = api.rename(self.host, anon, 'anonold', 'anonnew')
        self.assertEqual(result, 'anonnew')

    # ── List ──────────────────────────────────────────────────────────────────

    def test_list_drops_returns_own_drops(self):
        api.upload_text(self.host, self.session, 'a', key='ls1')
        api.upload_text(self.host, self.session, 'b', key='ls2')
        drops = api.list_drops(self.host, self.session)
        keys = [d['key'] for d in drops]
        self.assertIn('ls1', keys)
        self.assertIn('ls2', keys)

    def test_list_drops_does_not_include_other_user_drops(self):
        api.upload_text(self.host, self.session, 'mine', key='myls')
        other_session = requests.Session()
        User.objects.create_user('other2@test.com', 'other2@test.com', 'pass1234')
        api.login(self.host, other_session, 'other2@test.com', 'pass1234')
        drops = api.list_drops(self.host, other_session)
        keys = [d['key'] for d in drops]
        self.assertNotIn('myls', keys)

    def test_list_drops_empty_for_new_user(self):
        drops = api.list_drops(self.host, self.session)
        self.assertEqual(drops, [])

    def test_list_drops_unauthenticated_returns_none(self):
        anon = requests.Session()
        self.assertIsNone(api.list_drops(self.host, anon))

    # ── Renew ─────────────────────────────────────────────────────────────────

    def test_renew_extends_expiry(self):
        from core.models import Drop, Plan
        self.user.profile.plan = Plan.STARTER
        self.user.profile.save()
        api.upload_text(self.host, self.session, 'renew me', key='renewtest')
        drop = Drop.objects.get(key='renewtest')
        old_expiry = timezone.now() + timedelta(days=30)
        drop.expires_at = old_expiry
        drop.save()
        expires_at, count = api.renew(self.host, self.session, 'renewtest')
        self.assertIsNotNone(expires_at)
        self.assertEqual(count, 1)
        drop.refresh_from_db()
        self.assertGreater(drop.expires_at, old_expiry)

    def test_renew_anon_drop_denied(self):
        """Anon drops cannot be renewed even by the same session."""
        anon = requests.Session()
        api.upload_text(self.host, anon, 'no renew', key='anonrenew')
        expires_at, _ = api.renew(self.host, anon, 'anonrenew')
        self.assertIsNone(expires_at)

    def test_renew_other_user_drop_denied(self):
        from core.models import Drop, Plan
        self.user.profile.plan = Plan.STARTER
        self.user.profile.save()
        api.upload_text(self.host, self.session, 'not yours', key='notren')
        Drop.objects.filter(key='notren').update(
            expires_at=timezone.now() + timedelta(days=30)
        )
        other_session = requests.Session()
        User.objects.create_user('other3@test.com', 'other3@test.com', 'pass1234')
        api.login(self.host, other_session, 'other3@test.com', 'pass1234')
        expires_at, _ = api.renew(self.host, other_session, 'notren')
        self.assertIsNone(expires_at)

    # ── Export ────────────────────────────────────────────────────────────────

    def test_export_returns_json_with_drops_key(self):
        api.upload_text(self.host, self.session, 'exported', key='exptest')
        res = self.session.get(f'{self.host}/auth/account/export/', timeout=10)
        self.assertTrue(res.ok)
        self.assertIn('drops', res.json())

    def test_export_includes_uploaded_drop(self):
        api.upload_text(self.host, self.session, 'exported', key='exptest2')
        res = self.session.get(f'{self.host}/auth/account/export/', timeout=10)
        keys = [d['key'] for d in res.json()['drops']]
        self.assertIn('exptest2', keys)

    def test_export_drop_has_required_fields(self):
        api.upload_text(self.host, self.session, 'exported', key='exptest3')
        res = self.session.get(f'{self.host}/auth/account/export/', timeout=10)
        drop = next(d for d in res.json()['drops'] if d['key'] == 'exptest3')
        for field in ('key', 'kind', 'url', 'host', 'created_at'):
            self.assertIn(field, drop, f'Missing field: {field}')

    def test_export_url_is_accessible(self):
        """The URL in the export must actually point somewhere real."""
        api.upload_text(self.host, self.session, 'exported', key='exptest4')
        res = self.session.get(f'{self.host}/auth/account/export/', timeout=10)
        drop = next(d for d in res.json()['drops'] if d['key'] == 'exptest4')
        # Replace the domain with live_server_url for test
        url = drop['url'].replace(drop['host'], self.host)
        r = self.session.get(url, timeout=10)
        self.assertEqual(r.status_code, 200)

    def test_export_requires_login(self):
        anon = requests.Session()
        res = anon.get(f'{self.host}/auth/account/export/', allow_redirects=False)
        self.assertIn(res.status_code, (302, 403))

    def test_export_does_not_include_other_users_drops(self):
        """Export must be scoped to the logged-in user only."""
        other_session = requests.Session()
        User.objects.create_user('other4@test.com', 'other4@test.com', 'pass1234')
        api.login(self.host, other_session, 'other4@test.com', 'pass1234')
        api.upload_text(self.host, other_session, 'not mine', key='notmine')
        res = self.session.get(f'{self.host}/auth/account/export/', timeout=10)
        keys = [d['key'] for d in res.json()['drops']]
        self.assertNotIn('notmine', keys)

    # ── Session persistence ───────────────────────────────────────────────────

    def test_saved_session_cookie_can_authenticate_next_request(self):
        """Core of the session persistence feature — saved cookies must work."""
        import json
        from drp import SESSION_FILE, _save_session, _load_session
        _save_session(self.session)
        self.assertTrue(SESSION_FILE.exists())
        new_session = requests.Session()
        _load_session(new_session)
        res = new_session.get(
            f'{self.host}/auth/account/',
            headers={'Accept': 'application/json'},
            allow_redirects=False,
        )
        self.assertEqual(res.status_code, 200)

    def test_cleared_session_requires_reauth(self):
        from drp import _save_session, _clear_session, SESSION_FILE
        _save_session(self.session)
        _clear_session()
        self.assertFalse(SESSION_FILE.exists())
        new_session = requests.Session()
        res = new_session.get(
            f'{self.host}/auth/account/',
            allow_redirects=False,
        )
        self.assertIn(res.status_code, (302, 403))


# ═══════════════════════════════════════════════════════════════════════════════
# Version
# ═══════════════════════════════════════════════════════════════════════════════

class VersionTests(TestCase):
    """Sanity-check that version string is well-formed — caught by CI on every publish."""

    def test_version_is_semver(self):
        from cli import __version__
        parts = __version__.split('.')
        self.assertEqual(len(parts), 3, f'Expected X.Y.Z, got {__version__!r}')
        for part in parts:
            self.assertTrue(part.isdigit(), f'Non-numeric version part: {part!r}')