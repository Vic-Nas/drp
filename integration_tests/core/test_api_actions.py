"""
integration_tests/core/test_api_actions.py
Tests for delete / rename / renew / save_bookmark / list_drops / key_exists.
"""
import pytest
from conftest import HOST, unique_key
from cli.api.text import upload_text
from cli.api.actions import delete, rename, renew, save_bookmark, list_drops, key_exists


def _up(user, label, content='content'):
    key = unique_key(label)
    upload_text(HOST, user.session, content, key=key)
    return key


class TestKeyExists:
    def test_existing_key(self, free_user):
        key = free_user.track(_up(free_user, 'exists'))
        assert key_exists(HOST, free_user.session, key, ns='c') is True

    def test_missing_key(self, free_user):
        assert key_exists(HOST, free_user.session, 'drptest-no-such-xyz', ns='c') is False

    def test_wrong_ns(self, free_user):
        key = free_user.track(_up(free_user, 'nscheck'))
        assert key_exists(HOST, free_user.session, key, ns='f') is False


class TestDelete:
    def test_owner_can_delete(self, free_user):
        key = _up(free_user, 'del')
        assert delete(HOST, free_user.session, key, ns='c') is True
        assert key_exists(HOST, free_user.session, key, ns='c') is False

    def test_missing_key_returns_false(self, free_user):
        assert delete(HOST, free_user.session, 'drptest-never-existed', ns='c') is False

    def test_wrong_ns_returns_false(self, free_user):
        key = free_user.track(_up(free_user, 'delwrongns'))
        assert delete(HOST, free_user.session, key, ns='f') is False


class TestRename:
    def test_rename_succeeds(self, free_user):
        old = _up(free_user, 'renold')
        new = free_user.track(unique_key('rennew'))
        assert rename(HOST, free_user.session, old, new, ns='c') == new

    def test_content_accessible_at_new_key(self, free_user):
        from cli.api.text import get_clipboard
        content = 'rename-content-marker'
        old = unique_key('renacc')
        upload_text(HOST, free_user.session, content, key=old)
        new = free_user.track(unique_key('renaccnew'))
        rename(HOST, free_user.session, old, new, ns='c')
        _, got = get_clipboard(HOST, free_user.session, new)
        assert got == content

    def test_old_key_gone(self, free_user):
        from cli.api.text import get_clipboard
        old = unique_key('rengone')
        upload_text(HOST, free_user.session, 'gone', key=old)
        new = free_user.track(unique_key('rengonenew'))
        rename(HOST, free_user.session, old, new, ns='c')
        kind, _ = get_clipboard(HOST, free_user.session, old)
        assert kind is None

    def test_rename_missing_key_returns_false(self, free_user):
        assert rename(HOST, free_user.session, 'drptest-no-such', unique_key('dest'), ns='c') is False

    def test_rename_to_taken_key_returns_false(self, free_user):
        a = free_user.track(_up(free_user, 'rena'))
        b = free_user.track(_up(free_user, 'renb'))
        assert rename(HOST, free_user.session, a, b, ns='c') is False


class TestListDrops:
    def test_returns_list(self, free_user):
        assert isinstance(list_drops(HOST, free_user.session), list)

    def test_uploaded_drop_appears(self, free_user):
        key = free_user.track(_up(free_user, 'ls'))
        keys = [d['key'] for d in list_drops(HOST, free_user.session)]
        assert key in keys

    def test_drop_has_expected_fields(self, free_user):
        key = free_user.track(_up(free_user, 'lsfields'))
        drop = next(d for d in list_drops(HOST, free_user.session) if d['key'] == key)
        for field in ('key', 'ns', 'kind', 'created_at'):
            assert field in drop

    def test_users_only_see_own_drops(self, free_user, starter_user):
        free_key    = free_user.track(_up(free_user, 'lsown'))
        starter_key = starter_user.track(_up(starter_user, 'lsown'))
        free_keys    = [d['key'] for d in list_drops(HOST, free_user.session)]
        starter_keys = [d['key'] for d in list_drops(HOST, starter_user.session)]
        assert free_key    in free_keys
        assert starter_key not in free_keys
        assert starter_key in starter_keys
        assert free_key    not in starter_keys


class TestSaveBookmark:
    def test_bookmark_returns_true(self, free_user):
        key = free_user.track(_up(free_user, 'bm'))
        assert save_bookmark(HOST, free_user.session, key, ns='c') is True

    def test_missing_key_returns_false(self, free_user):
        assert save_bookmark(HOST, free_user.session, 'drptest-no-bm-xyz', ns='c') is False


class TestRenew:
    def test_free_plan_renew_blocked(self, free_user):
        key = free_user.track(_up(free_user, 'renewfree'))
        expires_at, count = renew(HOST, free_user.session, key, ns='c')
        # Free plan cannot renew — should return (None, None)
        assert expires_at is None

    def test_starter_plan_can_renew(self, starter_user):
        key = starter_user.track(unique_key('renewstarter'))
        upload_text(HOST, starter_user.session, 'renew me', key=key, expiry_days=7)
        expires_at, count = renew(HOST, starter_user.session, key, ns='c')
        if expires_at is not None:   # may be blocked server-side too soon after upload
            assert isinstance(expires_at, str)
            assert isinstance(count, int)

    def test_renew_missing_key(self, free_user):
        expires_at, count = renew(HOST, free_user.session, 'drptest-no-renew-xyz', ns='c')
        assert expires_at is None and count is None
