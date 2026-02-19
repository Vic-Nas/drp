"""
Tests for the drp CLI helpers (config, api, slug).

Uses LiveServerTestCase so api functions talk to a real Django instance.
All tests are self-cleaning (transaction rollback per test).
"""

import json
import os
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import LiveServerTestCase, override_settings

import requests

from cli import api, config

_STATIC_OVERRIDE = override_settings(
    STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage'
)


# ═══════════════════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════════════════

class ConfigTests(LiveServerTestCase):

    def test_load_missing_returns_empty(self):
        self.assertEqual(config.load('/tmp/drp_nope_12345.json'), {})

    def test_save_and_load_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            cfg = {'host': 'https://example.com', 'email': 'a@b.com'}
            config.save(cfg, path)
            self.assertEqual(config.load(path), cfg)
        finally:
            os.unlink(path)

    def test_save_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'sub', 'dir', 'config.json')
            config.save({'host': 'x'}, path)
            self.assertTrue(os.path.exists(path))
            self.assertEqual(config.load(path), {'host': 'x'})

    def test_save_overwrites(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            config.save({'host': 'old'}, path)
            config.save({'host': 'new'}, path)
            self.assertEqual(config.load(path)['host'], 'new')
        finally:
            os.unlink(path)


# ═══════════════════════════════════════════════════════════════════════════════
# Local drop cache
# ═══════════════════════════════════════════════════════════════════════════════

class LocalDropCacheTests(LiveServerTestCase):

    def setUp(self):
        # Use a temp file to avoid touching real cache
        self._orig = config.DROPS_FILE
        config.DROPS_FILE = Path(tempfile.mktemp(suffix='.json'))

    def tearDown(self):
        if config.DROPS_FILE.exists():
            config.DROPS_FILE.unlink()
        config.DROPS_FILE = self._orig

    def test_record_and_load(self):
        config.record_drop('mykey', 'text', host='https://example.com')
        drops = config.load_local_drops()
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0]['key'], 'mykey')
        self.assertEqual(drops[0]['kind'], 'text')

    def test_record_file_with_filename(self):
        config.record_drop('filekey', 'file', filename='notes.txt', host='https://example.com')
        drops = config.load_local_drops()
        self.assertEqual(drops[0]['filename'], 'notes.txt')

    def test_record_deduplicates(self):
        config.record_drop('k', 'text', host='https://example.com')
        config.record_drop('k', 'text', host='https://example.com')
        self.assertEqual(len(config.load_local_drops()), 1)

    def test_remove_drop(self):
        config.record_drop('k1', 'text', host='https://example.com')
        config.record_drop('k2', 'text', host='https://example.com')
        config.remove_local_drop('k1')
        keys = [d['key'] for d in config.load_local_drops()]
        self.assertNotIn('k1', keys)
        self.assertIn('k2', keys)

    def test_rename_drop(self):
        config.record_drop('old', 'text', host='https://example.com')
        config.rename_local_drop('old', 'new')
        keys = [d['key'] for d in config.load_local_drops()]
        self.assertIn('new', keys)
        self.assertNotIn('old', keys)

    def test_load_empty_when_missing(self):
        self.assertEqual(config.load_local_drops(), [])


# ═══════════════════════════════════════════════════════════════════════════════
# Slug
# ═══════════════════════════════════════════════════════════════════════════════

class SlugTests(LiveServerTestCase):

    def test_simple(self):
        self.assertEqual(api.slug('notes.txt'), 'notes')

    def test_spaces_become_dashes(self):
        self.assertEqual(api.slug('my cool file.pdf'), 'my-cool-file')

    def test_special_chars_stripped(self):
        self.assertEqual(api.slug('hello@world!.py'), 'hello-world')

    def test_long_name_truncated(self):
        self.assertLessEqual(len(api.slug('a' * 100 + '.txt')), 40)

    def test_empty_stem_gets_fallback(self):
        self.assertTrue(len(api.slug('.bashrc')) > 0)


# ═══════════════════════════════════════════════════════════════════════════════
# API – CSRF & Login
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class AuthApiTests(LiveServerTestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='cli@test.com', email='cli@test.com', password='pass1234'
        )
        self.session = requests.Session()

    def test_get_csrf_returns_token(self):
        token = api.get_csrf(self.live_server_url, self.session)
        self.assertTrue(len(token) > 0)

    def test_login_success(self):
        self.assertTrue(api.login(self.live_server_url, self.session, 'cli@test.com', 'pass1234'))

    def test_login_wrong_password(self):
        self.assertFalse(api.login(self.live_server_url, self.session, 'cli@test.com', 'wrong'))

    def test_login_nonexistent_user(self):
        self.assertFalse(api.login(self.live_server_url, self.session, 'no@one.com', 'pass'))

    def test_login_sets_session_cookie(self):
        api.login(self.live_server_url, self.session, 'cli@test.com', 'pass1234')
        self.assertIn('sessionid', self.session.cookies)


# ═══════════════════════════════════════════════════════════════════════════════
# API – Text drops (anonymous)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class AnonTextDropTests(LiveServerTestCase):

    def setUp(self):
        self.session = requests.Session()
        self.host = self.live_server_url

    def test_upload_text(self):
        key = api.upload_text(self.host, self.session, 'hello world')
        self.assertIsNotNone(key)

    def test_upload_text_custom_key(self):
        key = api.upload_text(self.host, self.session, 'custom!', key='mykey')
        self.assertEqual(key, 'mykey')

    def test_get_text_drop(self):
        key = api.upload_text(self.host, self.session, 'retrievable content')
        kind, content = api.get_drop(self.host, self.session, key)
        self.assertEqual(kind, 'text')
        self.assertEqual(content, 'retrievable content')

    def test_delete_text_drop(self):
        key = api.upload_text(self.host, self.session, 'delete me')
        self.assertTrue(api.delete(self.host, self.session, key))
        self.assertFalse(api.key_exists(self.host, self.session, key))

    def test_get_nonexistent_drop(self):
        kind, content = api.get_drop(self.host, self.session, 'no-such-key-xyz')
        self.assertIsNone(kind)
        self.assertIsNone(content)

    def test_delete_nonexistent_drop(self):
        self.assertFalse(api.delete(self.host, self.session, 'no-such-key-xyz'))

    def test_key_exists_true(self):
        api.upload_text(self.host, self.session, 'exists', key='taken-key')
        self.assertTrue(api.key_exists(self.host, self.session, 'taken-key'))

    def test_key_exists_false(self):
        self.assertFalse(api.key_exists(self.host, self.session, 'definitely-not-here'))

    def test_upload_duplicate_key_within_24h_blocked(self):
        """Anon drop is locked for 24h — overwrite should be rejected."""
        api.upload_text(self.host, self.session, 'original', key='locked-key')
        other = requests.Session()
        result = api.upload_text(self.host, other, 'overwrite attempt', key='locked-key')
        # Should fail (403) — key is locked
        kind, content = api.get_drop(self.host, self.session, 'locked-key')
        self.assertEqual(content, 'original')


# ═══════════════════════════════════════════════════════════════════════════════
# API – File drops (anonymous)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class AnonFileDropTests(LiveServerTestCase):

    def setUp(self):
        self.session = requests.Session()
        self.host = self.live_server_url

    def _tmp_file(self, content=b'test content', suffix='.txt'):
        f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        f.write(content)
        f.flush()
        f.close()
        return f.name

    def test_upload_file(self):
        path = self._tmp_file()
        try:
            key = api.upload_file(self.host, self.session, path, key='filetest')
            self.assertEqual(key, 'filetest')
        finally:
            os.unlink(path)

    def test_get_file_drop(self):
        path = self._tmp_file(b'binary data here')
        try:
            key = api.upload_file(self.host, self.session, path, key='getfile')
            kind, content = api.get_drop(self.host, self.session, key)
            self.assertEqual(kind, 'file')
            data, filename = content
            self.assertIn(b'binary data here', data)
        finally:
            os.unlink(path)

    def test_uploaded_file_key_matches_slug(self):
        path = self._tmp_file(suffix='.pdf')
        try:
            # No explicit key — should use slug of filename
            key = api.upload_file(self.host, self.session, path)
            self.assertIsNotNone(key)
        finally:
            os.unlink(path)


# ═══════════════════════════════════════════════════════════════════════════════
# API – Authenticated drops
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

    def test_upload_text_authed(self):
        key = api.upload_text(self.host, self.session, 'logged in text', key='authtext')
        self.assertEqual(key, 'authtext')

    def test_get_text_authed(self):
        api.upload_text(self.host, self.session, 'authed content', key='authget')
        kind, content = api.get_drop(self.host, self.session, 'authget')
        self.assertEqual(kind, 'text')
        self.assertEqual(content, 'authed content')

    def test_delete_authed(self):
        api.upload_text(self.host, self.session, 'bye', key='authdel')
        self.assertTrue(api.delete(self.host, self.session, 'authdel'))
        self.assertFalse(api.key_exists(self.host, self.session, 'authdel'))

    def test_locked_drop_not_deletable_by_anon(self):
        from core.models import Drop
        api.upload_text(self.host, self.session, 'locked', key='locktest')
        Drop.objects.filter(key='locktest').update(locked=True)
        anon = requests.Session()
        self.assertFalse(api.delete(self.host, anon, 'locktest'))

    def test_rename_drop(self):
        api.upload_text(self.host, self.session, 'rename me', key='oldname')
        new_key = api.rename(self.host, self.session, 'oldname', 'newname')
        self.assertEqual(new_key, 'newname')
        self.assertFalse(api.key_exists(self.host, self.session, 'oldname'))
        self.assertTrue(api.key_exists(self.host, self.session, 'newname'))

    def test_rename_to_taken_key_fails(self):
        api.upload_text(self.host, self.session, 'first', key='existing')
        api.upload_text(self.host, self.session, 'second', key='movethis')
        result = api.rename(self.host, self.session, 'movethis', 'existing')
        self.assertIsNone(result)

    def test_rename_blocked_within_24h_for_anon(self):
        """Anon drops cannot be renamed within 24h creation window."""
        anon = requests.Session()
        api.upload_text(self.host, anon, 'anon drop', key='anonmv')
        result = api.rename(self.host, anon, 'anonmv', 'anonmv-new')
        self.assertIsNone(result)

    def test_list_drops(self):
        api.upload_text(self.host, self.session, 'item 1', key='list1')
        api.upload_text(self.host, self.session, 'item 2', key='list2')
        drops = api.list_drops(self.host, self.session)
        self.assertIsNotNone(drops)
        keys = [d['key'] for d in drops]
        self.assertIn('list1', keys)
        self.assertIn('list2', keys)

    def test_list_drops_anon_fails(self):
        anon = requests.Session()
        self.assertIsNone(api.list_drops(self.host, anon))

    def test_list_drops_empty(self):
        drops = api.list_drops(self.host, self.session)
        self.assertIsNotNone(drops)
        self.assertEqual(len(drops), 0)

    def test_renew_drop(self):
        from core.models import Drop, Plan
        from django.utils import timezone
        from datetime import timedelta
        self.user.profile.plan = Plan.STARTER
        self.user.profile.save()
        api.upload_text(self.host, self.session, 'renew me', key='renewtest')
        drop = Drop.objects.get(key='renewtest')
        drop.expires_at = timezone.now() + timedelta(days=1)
        drop.save()
        expires_at, renewals = api.renew(self.host, self.session, 'renewtest')
        self.assertIsNotNone(expires_at)
        self.assertEqual(renewals, 1)

    def test_renew_anon_drop_fails(self):
        anon = requests.Session()
        api.upload_text(self.host, anon, 'no renew', key='anonrenew')
        expires_at, _ = api.renew(self.host, self.session, 'anonrenew')
        self.assertIsNone(expires_at)

    def test_export_drops(self):
        """Export endpoint returns JSON with correct structure."""
        api.upload_text(self.host, self.session, 'export me', key='exporttest')
        res = self.session.get(
            f'{self.host}/auth/account/export/',
            headers={'Accept': 'application/json'},
            timeout=10,
        )
        self.assertTrue(res.ok)
        data = res.json()
        self.assertIn('drops', data)
        keys = [d['key'] for d in data['drops']]
        self.assertIn('exporttest', keys)
        # Each drop should have required fields
        drop = next(d for d in data['drops'] if d['key'] == 'exporttest')
        self.assertIn('kind', drop)
        self.assertIn('url', drop)
        self.assertIn('host', drop)

    def test_export_requires_login(self):
        """Export endpoint rejects anonymous requests."""
        anon = requests.Session()
        res = anon.get(f'{self.host}/auth/account/export/', allow_redirects=False)
        self.assertIn(res.status_code, (302, 403))


# ═══════════════════════════════════════════════════════════════════════════════
# Version
# ═══════════════════════════════════════════════════════════════════════════════

class VersionTests(LiveServerTestCase):

    def test_version_format(self):
        from cli import __version__
        parts = __version__.split('.')
        self.assertEqual(len(parts), 3)
        for p in parts:
            self.assertTrue(p.isdigit())