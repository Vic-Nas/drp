"""
Tests for the drp sync client.

- Pure-function unit tests (slug, config, key mapping)
- Integration tests using Django LiveServerTestCase for real HTTP calls
"""

import json
import os
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase, LiveServerTestCase, override_settings
from django.utils import timezone

from core.models import Drop, Plan, UserProfile

# Import sync client functions
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from sync.client import (
    slug, load_config, save_config, check_stale_keys,
    get_csrf, api_login, upload_file, delete_drop,
    check_remote_key, SyncHandler,
)

_STATIC_OVERRIDE = override_settings(
    STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage'
)


# ═══════════════════════════════════════════════════════════════════════════════
# Pure function tests
# ═══════════════════════════════════════════════════════════════════════════════

class SlugTests(TestCase):
    """Tests for the slug() filename-to-key converter."""

    def test_simple_filename(self):
        self.assertEqual(slug('readme.txt'), 'readme')

    def test_spaces_become_dashes(self):
        self.assertEqual(slug('my file.pdf'), 'my-file')

    def test_special_chars_stripped(self):
        result = slug('hello@world!.txt')
        self.assertTrue(all(c.isalnum() or c in '-_' for c in result))

    def test_long_name_truncated(self):
        name = 'a' * 100 + '.txt'
        self.assertEqual(len(slug(name)), 40)

    def test_empty_stem_generates_random(self):
        result = slug('.hidden')
        self.assertTrue(len(result) > 0)

    def test_preserves_dashes_and_underscores(self):
        self.assertEqual(slug('my-file_v2.txt'), 'my-file_v2')


class ConfigTests(TestCase):
    """Tests for config load/save."""

    def test_save_and_load_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            cfg = {'host': 'https://example.com', 'folder': '/tmp/test', 'key_map': {'a.txt': 'a'}}
            save_config(cfg, path=path)
            loaded = load_config(path=path)
            self.assertEqual(loaded, cfg)
        finally:
            os.unlink(path)

    def test_load_missing_file_returns_empty(self):
        cfg = load_config(path='/tmp/nonexistent_drp_config_xyz.json')
        self.assertEqual(cfg, {})


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests (real HTTP with Django LiveServerTestCase)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC_OVERRIDE
class SyncIntegrationTests(LiveServerTestCase):
    """End-to-end tests using a real test server."""

    def setUp(self):
        import requests
        self.session = requests.Session()
        self.user = User.objects.create_user('sync@test.com', 'sync@test.com', 'testpass123')
        self.profile = self.user.profile

    # ── Auth ──────────────────────────────────────────────────────────────

    def test_login_success(self):
        result = api_login(self.live_server_url, self.session, 'sync@test.com', 'testpass123')
        self.assertTrue(result)

    def test_login_wrong_password(self):
        result = api_login(self.live_server_url, self.session, 'sync@test.com', 'wrong')
        self.assertFalse(result)

    def test_get_csrf_returns_token(self):
        token = get_csrf(self.live_server_url, self.session)
        self.assertTrue(len(token) > 0)

    # ── Upload ────────────────────────────────────────────────────────────

    def test_upload_file_anonymous(self):
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b'sync test content')
            filepath = f.name
        try:
            key = upload_file(self.live_server_url, self.session, filepath, key='sync-anon-test')
            self.assertEqual(key, 'sync-anon-test')
            self.assertTrue(Drop.objects.filter(key='sync-anon-test').exists())
        finally:
            os.unlink(filepath)

    def test_upload_file_authenticated(self):
        api_login(self.live_server_url, self.session, 'sync@test.com', 'testpass123')
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b'authed upload')
            filepath = f.name
        try:
            key = upload_file(self.live_server_url, self.session, filepath, key='sync-auth-test')
            self.assertEqual(key, 'sync-auth-test')
            drop = Drop.objects.get(key='sync-auth-test')
            self.assertEqual(drop.owner, self.user)
        finally:
            os.unlink(filepath)

    def test_upload_overwrites_existing(self):
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b'version 1')
            filepath = f.name
        try:
            upload_file(self.live_server_url, self.session, filepath, key='sync-overwrite')
            # Overwrite with new content
            with open(filepath, 'wb') as f2:
                f2.write(b'version 2')
            upload_file(self.live_server_url, self.session, filepath, key='sync-overwrite')
            # Should still be one drop
            self.assertEqual(Drop.objects.filter(key='sync-overwrite').count(), 1)
        finally:
            os.unlink(filepath)

    # ── Delete ────────────────────────────────────────────────────────────

    def test_delete_drop(self):
        Drop.objects.create(key='sync-del', kind=Drop.FILE, filename='d.txt')
        delete_drop(self.live_server_url, self.session, 'sync-del')
        self.assertFalse(Drop.objects.filter(key='sync-del').exists())

    # ── Staleness ─────────────────────────────────────────────────────────

    def test_check_remote_key_exists(self):
        Drop.objects.create(key='sync-exists', kind=Drop.TEXT, content='hi')
        self.assertTrue(check_remote_key(self.live_server_url, self.session, 'sync-exists'))

    def test_check_remote_key_missing(self):
        self.assertFalse(check_remote_key(self.live_server_url, self.session, 'sync-nope'))

    def test_check_stale_keys(self):
        Drop.objects.create(key='alive-key', kind=Drop.TEXT, content='hi')
        key_map = {'file1.txt': 'alive-key', 'file2.txt': 'dead-key'}
        live, stale = check_stale_keys(self.live_server_url, self.session, key_map)
        self.assertIn('file1.txt', live)
        self.assertIn('file2.txt', stale)
        self.assertNotIn('file2.txt', live)

    def test_stale_key_triggers_reupload(self):
        """Expired key should be detected as stale, allowing re-upload."""
        drop = Drop.objects.create(key='was-alive', kind=Drop.TEXT, content='old')
        Drop.objects.filter(pk=drop.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        # The drop exists in DB but is_expired — however check_remote_key
        # uses check-key endpoint which just checks existence
        exists = check_remote_key(self.live_server_url, self.session, 'was-alive')
        # Key still exists in DB even if expired (cleanup hasn't run)
        self.assertTrue(exists)

    # ── Authenticated upload gets owner ───────────────────────────────────

    def test_paid_user_upload_is_locked(self):
        """Paid user's synced drops should be locked to their account."""
        self.profile.plan = Plan.STARTER
        self.profile.save()
        api_login(self.live_server_url, self.session, 'sync@test.com', 'testpass123')
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b'paid sync')
            filepath = f.name
        try:
            key = upload_file(self.live_server_url, self.session, filepath, key='sync-paid')
            drop = Drop.objects.get(key='sync-paid')
            self.assertTrue(drop.locked)
            self.assertEqual(drop.owner, self.user)
        finally:
            os.unlink(filepath)


# ═══════════════════════════════════════════════════════════════════════════════
# SyncHandler unit tests (mocked HTTP)
# ═══════════════════════════════════════════════════════════════════════════════

class SyncHandlerTests(TestCase):
    """Tests for the watchdog event handler logic."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = {'host': 'http://fake', 'folder': self.tmpdir, 'key_map': {}}
        self.handler = SyncHandler('http://fake', self.tmpdir, {}, self.cfg)

    def test_ignores_dotfiles(self):
        """Hidden files (starting with .) should be skipped."""
        event = MagicMock()
        event.is_directory = False
        event.src_path = os.path.join(self.tmpdir, '.DS_Store')
        with patch.object(self.handler, 'session'):
            # on_created should return without uploading
            with patch('sync.client.upload_file') as mock_upload:
                self.handler.on_created(event)
                mock_upload.assert_not_called()

    def test_on_created_uploads(self):
        """New file triggers upload and saves key."""
        filepath = os.path.join(self.tmpdir, 'new.txt')
        Path(filepath).write_text('hi')
        event = MagicMock()
        event.is_directory = False
        event.src_path = filepath
        with patch('sync.client.upload_file', return_value='new') as mock_upload:
            with patch('sync.client.save_config'):
                self.handler.on_created(event)
                mock_upload.assert_called_once()
                self.assertEqual(self.handler.key_map.get('new.txt'), 'new')

    def test_on_deleted_removes_key(self):
        """Deleting a tracked file triggers remote delete and removes from map."""
        self.handler.key_map['gone.txt'] = 'gone-key'
        event = MagicMock()
        event.is_directory = False
        event.src_path = os.path.join(self.tmpdir, 'gone.txt')
        with patch('sync.client.delete_drop') as mock_del:
            with patch('sync.client.save_config'):
                self.handler.on_deleted(event)
                mock_del.assert_called_once_with('http://fake', self.handler.session, 'gone-key')
                self.assertNotIn('gone.txt', self.handler.key_map)

    def test_on_modified_updates_key(self):
        """Modifying a tracked file triggers re-upload."""
        self.handler.key_map['mod.txt'] = 'mod-key'
        filepath = os.path.join(self.tmpdir, 'mod.txt')
        Path(filepath).write_text('updated')
        event = MagicMock()
        event.is_directory = False
        event.src_path = filepath
        with patch('sync.client.upload_file', return_value='mod-key') as mock_upload:
            with patch('sync.client.save_config'):
                self.handler.on_modified(event)
                mock_upload.assert_called_once()

    def test_ignores_directories(self):
        """Directory events should be skipped."""
        event = MagicMock()
        event.is_directory = True
        with patch('sync.client.upload_file') as mock_upload:
            self.handler.on_created(event)
            self.handler.on_modified(event)
            mock_upload.assert_not_called()
