"""
integration_tests/core/test_api_text.py
Tests for upload_text / get_clipboard across all plan tiers.
"""
import pytest
from conftest import HOST, unique_key
from cli.api.text import upload_text, get_clipboard


class TestUploadText:
    def test_basic_upload(self, free_user):
        key = free_user.track(unique_key('text'))
        result = upload_text(HOST, free_user.session, 'hello', key=key)
        assert result == key

    def test_roundtrip(self, free_user):
        key = free_user.track(unique_key('rt'))
        upload_text(HOST, free_user.session, 'round-trip ✓', key=key)
        kind, got = get_clipboard(HOST, free_user.session, key)
        assert kind == 'text' and got == 'round-trip ✓'

    def test_unicode(self, free_user):
        key = free_user.track(unique_key('uni'))
        content = '日本語 🎌 émojis'
        upload_text(HOST, free_user.session, content, key=key)
        _, got = get_clipboard(HOST, free_user.session, key)
        assert got == content

    def test_multiline(self, free_user):
        key = free_user.track(unique_key('ml'))
        content = 'line1\nline2\nline3'
        upload_text(HOST, free_user.session, content, key=key)
        _, got = get_clipboard(HOST, free_user.session, key)
        assert got == content

    def test_large(self, free_user):
        key = free_user.track(unique_key('large'))
        content = 'x' * 100_000
        upload_text(HOST, free_user.session, content, key=key)
        _, got = get_clipboard(HOST, free_user.session, key)
        assert got == content

    def test_missing_key_returns_none(self, anon):
        kind, content = get_clipboard(HOST, anon, 'drptest-no-such-key-xyz')
        assert kind is None and content is None

    def test_anon_can_read_clipboard(self, free_user, anon):
        key = free_user.track(unique_key('anonread'))
        upload_text(HOST, free_user.session, 'public content', key=key)
        kind, got = get_clipboard(HOST, anon, key)
        assert kind == 'text' and got == 'public content'

    def test_each_plan_can_upload(self, free_user, starter_user, pro_user):
        for user in (free_user, starter_user, pro_user):
            key = user.track(unique_key('planup'))
            result = upload_text(HOST, user.session, f'upload by {user.plan}', key=key)
            assert result == key
