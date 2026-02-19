"""
Tests for the drp CLI helpers (config, api, slug).

Uses LiveServerTestCase so api functions talk to a real Django instance.
All tests are self-cleaning (transaction rollback per test).
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import LiveServerTestCase, override_settings

import requests

from cli import api, config

# Use plain static storage in tests (no collectstatic needed)
_STATIC_OVERRIDE = override_settings(
    STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage'
)


# ═══════════════════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════════════════

class ConfigTests(LiveServerTestCase):
    """config.load / config.save with temp files."""

    def test_load_missing_returns_empty(self):
        """Loading a non-existent config returns {}."""
        self.assertEqual(config.load('/tmp/drp_nope_12345.json'), {})

    def test_save_and_load_roundtrip(self):
        """save → load returns the same data."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            cfg = {'host': 'https://example.com', 'email': 'a@b.com'}
            config.save(cfg, path)
            loaded = config.load(path)
            self.assertEqual(loaded, cfg)
        finally:
            os.unlink(path)

    def test_save_creates_parent_dirs(self):
        """save creates missing parent directories."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'sub', 'dir', 'config.json')
            config.save({'host': 'x'}, path)
            self.assertTrue(os.path.exists(path))
            self.assertEqual(config.load(path), {'host': 'x'})

    def test_save_overwrites(self):
        """Saving twice overwrites the first value."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            config.save({'host': 'old'}, path)
            config.save({'host': 'new'}, path)
            self.assertEqual(config.load(path)['host'], 'new')
        finally:
            os.unlink(path)


# ═══════════════════════════════════════════════════════════════════════════════
# Slug
# ═══════════════════════════════════════════════════════════════════════════════

class SlugTests(LiveServerTestCase):
    """api.slug turns filenames into url-safe keys."""

    def test_simple(self):
        self.assertEqual(api.slug('notes.txt'), 'notes')

    def test_spaces_become_dashes(self):
        self.assertEqual(api.slug('my cool file.pdf'), 'my-cool-file')

    def test_special_chars_stripped(self):
        self.assertEqual(api.slug('hello@world!.py'), 'hello-world')

    def test_long_name_truncated(self):
        name = 'a' * 100 + '.txt'
        self.assertLessEqual(len(api.slug(name)), 40)

    def test_empty_name_gets_random(self):
        """An empty stem (e.g. '.bashrc') still produces a non-empty slug."""
        result = api.slug('.bashrc')
        # .bashrc stem is '.bashrc' → 'bashrc' after stripping
        self.assertTrue(len(result) > 0)


# ═══════════════════════════════════════════════════════════════════════════════
# API – CSRF & Login
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class AuthApiTests(LiveServerTestCase):
    """CSRF, login, and session handling."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='cli@test.com', email='cli@test.com', password='pass1234'
        )
        self.session = requests.Session()

    def test_get_csrf_returns_token(self):
        token = api.get_csrf(self.live_server_url, self.session)
        self.assertTrue(len(token) > 0)

    def test_login_success(self):
        ok = api.login(self.live_server_url, self.session, 'cli@test.com', 'pass1234')
        self.assertTrue(ok)

    def test_login_wrong_password(self):
        ok = api.login(self.live_server_url, self.session, 'cli@test.com', 'wrong')
        self.assertFalse(ok)

    def test_login_nonexistent_user(self):
        ok = api.login(self.live_server_url, self.session, 'no@one.com', 'pass')
        self.assertFalse(ok)


# ═══════════════════════════════════════════════════════════════════════════════
# API – Upload, Get, Delete (anonymous)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class AnonDropApiTests(LiveServerTestCase):
    """Upload / get / delete drops as an anonymous user."""

    def setUp(self):
        self.session = requests.Session()
        self.host = self.live_server_url

    # ── Text ──────────────────────────────────────────────────────────────

    def test_upload_text(self):
        key = api.upload_text(self.host, self.session, 'hello world')
        self.assertIsNotNone(key)
        self.assertTrue(len(key) > 0)

    def test_upload_text_custom_key(self):
        key = api.upload_text(self.host, self.session, 'custom!', key='mykey')
        self.assertEqual(key, 'mykey')

    def test_get_text_drop(self):
        key = api.upload_text(self.host, self.session, 'i can be retrieved')
        kind, content = api.get_drop(self.host, self.session, key)
        self.assertEqual(kind, 'text')
        self.assertEqual(content, 'i can be retrieved')

    def test_delete_text_drop(self):
        key = api.upload_text(self.host, self.session, 'delete me')
        ok = api.delete(self.host, self.session, key)
        self.assertTrue(ok)
        # should be gone
        self.assertFalse(api.key_exists(self.host, self.session, key))

    # ── File ──────────────────────────────────────────────────────────────

    def test_upload_file(self):
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b'file content here')
            f.flush()
            path = f.name
        try:
            key = api.upload_file(self.host, self.session, path, key='filetest')
            self.assertEqual(key, 'filetest')
        finally:
            os.unlink(path)

    def test_get_file_drop(self):
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b'binary data')
            f.flush()
            path = f.name
        try:
            key = api.upload_file(self.host, self.session, path, key='getfile')
            kind, content = api.get_drop(self.host, self.session, key)
            self.assertEqual(kind, 'file')
            data, filename = content
            self.assertIn(b'binary data', data)
        finally:
            os.unlink(path)

    # ── Key checks ────────────────────────────────────────────────────────

    def test_key_exists_true(self):
        api.upload_text(self.host, self.session, 'exists', key='taken')
        self.assertTrue(api.key_exists(self.host, self.session, 'taken'))

    def test_key_exists_false(self):
        self.assertFalse(api.key_exists(self.host, self.session, 'nope-not-here'))

    # ── Not found ─────────────────────────────────────────────────────────

    def test_get_nonexistent_drop(self):
        kind, content = api.get_drop(self.host, self.session, 'no-such-key')
        self.assertIsNone(kind)
        self.assertIsNone(content)

    def test_delete_nonexistent_drop(self):
        ok = api.delete(self.host, self.session, 'no-such-key')
        self.assertFalse(ok)


# ═══════════════════════════════════════════════════════════════════════════════
# API – Authenticated drops
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class AuthDropApiTests(LiveServerTestCase):
    """Upload / get / delete drops as a logged-in user."""

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

    def test_upload_file_authed(self):
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b'auth file')
            f.flush()
            path = f.name
        try:
            key = api.upload_file(self.host, self.session, path, key='authfile')
            self.assertEqual(key, 'authfile')
        finally:
            os.unlink(path)

    def test_get_text_authed(self):
        api.upload_text(self.host, self.session, 'authed content', key='authget')
        kind, content = api.get_drop(self.host, self.session, 'authget')
        self.assertEqual(kind, 'text')
        self.assertEqual(content, 'authed content')

    def test_delete_authed(self):
        api.upload_text(self.host, self.session, 'bye', key='authdel')
        ok = api.delete(self.host, self.session, 'authdel')
        self.assertTrue(ok)
        self.assertFalse(api.key_exists(self.host, self.session, 'authdel'))

    def test_locked_drop_not_deletable_by_anon(self):
        """A locked drop can't be deleted from a fresh (anonymous) session."""
        from core.models import Drop
        api.upload_text(self.host, self.session, 'locked', key='locktest')
        Drop.objects.filter(key='locktest').update(locked=True)
        anon = requests.Session()
        ok = api.delete(self.host, anon, 'locktest')
        self.assertFalse(ok)

    def test_rename_drop(self):
        api.upload_text(self.host, self.session, 'rename me', key='oldname')
        new_key = api.rename(self.host, self.session, 'oldname', 'newname')
        self.assertEqual(new_key, 'newname')
        # old key gone, new key exists
        self.assertFalse(api.key_exists(self.host, self.session, 'oldname'))
        self.assertTrue(api.key_exists(self.host, self.session, 'newname'))

    def test_rename_to_taken_key_fails(self):
        api.upload_text(self.host, self.session, 'first', key='existing')
        api.upload_text(self.host, self.session, 'second', key='movethis')
        result = api.rename(self.host, self.session, 'movethis', 'existing')
        self.assertIsNone(result)

    def test_renew_drop(self):
        """Paid drops can be renewed."""
        from core.models import Drop, Plan
        from django.utils import timezone
        from datetime import timedelta
        self.user.profile.plan = Plan.STARTER
        self.user.profile.save()
        api.upload_text(self.host, self.session, 'renew me', key='renewtest')
        # Manually set expires_at to something in the near future
        drop = Drop.objects.get(key='renewtest')
        drop.expires_at = timezone.now() + timedelta(days=1)
        drop.save()
        expires_at, renewals = api.renew(self.host, self.session, 'renewtest')
        self.assertIsNotNone(expires_at)
        self.assertEqual(renewals, 1)

    def test_renew_anon_drop_fails(self):
        """Anon drops (no expires_at) cannot be renewed."""
        anon = requests.Session()
        api.upload_text(self.host, anon, 'no renew', key='anonrenew')
        expires_at, _ = api.renew(self.host, self.session, 'anonrenew')
        self.assertIsNone(expires_at)

    def test_list_drops(self):
        api.upload_text(self.host, self.session, 'list item 1', key='list1')
        api.upload_text(self.host, self.session, 'list item 2', key='list2')
        drops = api.list_drops(self.host, self.session)
        self.assertIsNotNone(drops)
        keys = [d['key'] for d in drops]
        self.assertIn('list1', keys)
        self.assertIn('list2', keys)

    def test_list_drops_anon_fails(self):
        """Anonymous session can't list drops (requires login)."""
        anon = requests.Session()
        drops = api.list_drops(self.host, anon)
        self.assertIsNone(drops)

    def test_list_drops_empty(self):
        drops = api.list_drops(self.host, self.session)
        self.assertIsNotNone(drops)
        self.assertEqual(len(drops), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Version
# ═══════════════════════════════════════════════════════════════════════════════

class VersionTests(LiveServerTestCase):
    """__version__ is importable and looks like semver."""

    def test_version_format(self):
        from cli import __version__
        parts = __version__.split('.')
        self.assertEqual(len(parts), 3)
        for p in parts:
            self.assertTrue(p.isdigit())
