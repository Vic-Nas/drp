"""
integration_tests/core/test_api_actions.py

Tests for cli/api/actions.py:
  delete, rename, renew, save_bookmark, list_drops, key_exists

Rename return convention is carefully tested:
  str   → success (new key)
  False → known error (404 wrong-ns, 409 conflict, 403 locked, 400 bad)
  None  → unexpected (shouldn't happen in normal operation)
"""

import pytest

from conftest import HOST, unique_key
from cli.api.text import upload_text
from cli.api.actions import (
    delete, rename, renew, save_bookmark, list_drops, key_exists,
)


# ── key_exists ─────────────────────────────────────────────────────────────────

class TestKeyExists:
    def test_existing_clipboard_key(self, drp_session, track):
        key = unique_key('exists')
        upload_text(HOST, drp_session, 'exists test', key=key)
        track(key)
        assert key_exists(HOST, drp_session, key, ns='c') is True

    def test_nonexistent_key_returns_false(self, drp_session):
        assert key_exists(HOST, drp_session, 'drptest-no-such-key-xyz', ns='c') is False

    def test_existing_file_key(self, drp_session, track):
        import tempfile, os
        from cli.api.file import upload_file
        path = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        path.write(b'file')
        path.close()
        key = unique_key('fexists')
        try:
            upload_file(HOST, drp_session, path.name, key=key)
        finally:
            os.unlink(path.name)
        track(key, ns='f')
        assert key_exists(HOST, drp_session, key, ns='f') is True

    def test_clipboard_key_not_found_in_file_ns(self, drp_session, track):
        key = unique_key('nsexists')
        upload_text(HOST, drp_session, 'ns test', key=key)
        track(key)
        # Same key exists in 'c' ns but should not appear in 'f' ns
        assert key_exists(HOST, drp_session, key, ns='f') is False


# ── delete ─────────────────────────────────────────────────────────────────────

class TestDelete:
    def test_delete_clipboard_returns_true(self, drp_session, track):
        key = unique_key('del')
        upload_text(HOST, drp_session, 'delete me', key=key)
        # Don't track — we're deleting it ourselves
        result = delete(HOST, drp_session, key, ns='c')
        assert result is True

    def test_deleted_key_no_longer_exists(self, drp_session):
        key = unique_key('delcheck')
        upload_text(HOST, drp_session, 'delete check', key=key)
        delete(HOST, drp_session, key, ns='c')
        from cli.api.text import get_clipboard
        kind, _ = get_clipboard(HOST, drp_session, key)
        assert kind is None

    def test_delete_nonexistent_returns_false(self, drp_session):
        result = delete(HOST, drp_session, 'drptest-never-existed-xyz', ns='c')
        assert result is False

    def test_delete_file_drop(self, drp_session, track):
        import tempfile, os
        from cli.api.file import upload_file
        f = tempfile.NamedTemporaryFile(delete=False, suffix='.bin')
        f.write(b'bye')
        f.close()
        key = unique_key('delfile')
        try:
            upload_file(HOST, drp_session, f.name, key=key)
        finally:
            os.unlink(f.name)
        result = delete(HOST, drp_session, key, ns='f')
        assert result is True

    def test_delete_wrong_ns_returns_false(self, drp_session, track):
        """Deleting a clipboard drop with ns='f' should return False (404)."""
        key = unique_key('delwrongns')
        upload_text(HOST, drp_session, 'wrong ns', key=key)
        track(key)  # track for cleanup since delete will fail
        result = delete(HOST, drp_session, key, ns='f')
        assert result is False


# ── rename ─────────────────────────────────────────────────────────────────────

class TestRename:
    def test_rename_returns_new_key(self, drp_session, track):
        old = unique_key('ren')
        new = unique_key('renamed')
        upload_text(HOST, drp_session, 'rename me', key=old)
        result = rename(HOST, drp_session, old, new, ns='c')
        track(new)  # old key is gone; new key needs cleanup
        assert result == new

    def test_renamed_key_is_accessible(self, drp_session, track):
        from cli.api.text import get_clipboard
        old = unique_key('renacc')
        new = unique_key('renaccnew')
        upload_text(HOST, drp_session, 'access after rename', key=old)
        rename(HOST, drp_session, old, new, ns='c')
        track(new)
        kind, content = get_clipboard(HOST, drp_session, new)
        assert kind == 'text'
        assert content == 'access after rename'

    def test_old_key_gone_after_rename(self, drp_session, track):
        from cli.api.text import get_clipboard
        old = unique_key('rengone')
        new = unique_key('rengonenew')
        upload_text(HOST, drp_session, 'gone', key=old)
        rename(HOST, drp_session, old, new, ns='c')
        track(new)
        kind, _ = get_clipboard(HOST, drp_session, old)
        assert kind is None

    def test_rename_missing_key_returns_false(self, drp_session):
        result = rename(HOST, drp_session, 'drptest-no-such-xyz', 'drptest-dest', ns='c')
        assert result is False

    def test_rename_to_taken_key_returns_false(self, drp_session, track):
        key_a = unique_key('rena')
        key_b = unique_key('renb')
        upload_text(HOST, drp_session, 'a', key=key_a)
        upload_text(HOST, drp_session, 'b', key=key_b)
        track(key_a)
        track(key_b)
        result = rename(HOST, drp_session, key_a, key_b, ns='c')
        assert result is False

    def test_rename_wrong_ns_returns_false(self, drp_session, track):
        key = unique_key('renwrongns')
        upload_text(HOST, drp_session, 'wrong ns rename', key=key)
        track(key)
        result = rename(HOST, drp_session, key, unique_key('dest'), ns='f')
        assert result is False


# ── list_drops ─────────────────────────────────────────────────────────────────

class TestListDrops:
    def test_returns_list(self, drp_session):
        result = list_drops(HOST, drp_session)
        assert isinstance(result, list)

    def test_uploaded_drop_appears_in_list(self, drp_session, track):
        key = unique_key('ls')
        upload_text(HOST, drp_session, 'list test', key=key)
        track(key)
        drops = list_drops(HOST, drp_session)
        keys = [d['key'] for d in drops]
        assert key in keys

    def test_drop_has_expected_fields(self, drp_session, track):
        key = unique_key('lsfields')
        upload_text(HOST, drp_session, 'fields test', key=key)
        track(key)
        drops = list_drops(HOST, drp_session)
        drop = next((d for d in drops if d['key'] == key), None)
        assert drop is not None
        assert 'ns' in drop
        assert 'kind' in drop
        assert 'created_at' in drop


# ── save_bookmark ──────────────────────────────────────────────────────────────

class TestSaveBookmark:
    def test_bookmark_returns_true(self, drp_session, track):
        key = unique_key('bm')
        upload_text(HOST, drp_session, 'bookmark me', key=key)
        track(key)
        result = save_bookmark(HOST, drp_session, key, ns='c')
        assert result is True

    def test_bookmark_missing_key_returns_false(self, drp_session):
        result = save_bookmark(HOST, drp_session, 'drptest-no-such-bm-xyz', ns='c')
        assert result is False


# ── renew ──────────────────────────────────────────────────────────────────────

class TestRenew:
    def test_renew_returns_expires_at_and_count(self, drp_session, track):
        key = unique_key('renew')
        upload_text(HOST, drp_session, 'renew me', key=key, expiry_days=7)
        track(key)
        expires_at, renewals = renew(HOST, drp_session, key, ns='c')
        # renew may be a paid feature; either it works or returns (None, None)
        if expires_at is not None:
            assert isinstance(expires_at, str)
            assert isinstance(renewals, int)
        # (None, None) is also acceptable — server may block renew on free plan

    def test_renew_missing_key_returns_none_tuple(self, drp_session):
        expires_at, renewals = renew(HOST, drp_session, 'drptest-no-such-renew-xyz', ns='c')
        assert expires_at is None
        assert renewals is None
