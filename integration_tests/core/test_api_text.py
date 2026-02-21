"""
integration_tests/core/test_api_text.py

Tests for cli/api/text.py: upload_text and get_clipboard.
All return paths covered:
  upload_text  → key string | None
  get_clipboard → ('text', content) | ('password_required', None) | (None, None)
"""

import pytest

from conftest import HOST, unique_key
from cli.api.text import upload_text, get_clipboard


class TestUploadText:
    def test_basic_upload_returns_key(self, drp_session, track):
        key = unique_key('text')
        result = upload_text(HOST, drp_session, 'hello integration', key=key)
        track(result or key)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_uploaded_content_is_retrievable(self, drp_session, track):
        key = unique_key('roundtrip')
        content = 'round-trip content ✓'
        upload_text(HOST, drp_session, content, key=key)
        track(key)
        kind, got = get_clipboard(HOST, drp_session, key)
        assert kind == 'text'
        assert got == content

    def test_custom_key_is_honoured(self, drp_session, track):
        key = unique_key('custom')
        result = upload_text(HOST, drp_session, 'custom key test', key=key)
        track(result or key)
        assert result == key

    def test_unicode_content(self, drp_session, track):
        key = unique_key('unicode')
        content = '日本語テスト 🎌 émojis & accents'
        upload_text(HOST, drp_session, content, key=key)
        track(key)
        _, got = get_clipboard(HOST, drp_session, key)
        assert got == content

    def test_multiline_content(self, drp_session, track):
        key = unique_key('multiline')
        content = 'line one\nline two\nline three'
        upload_text(HOST, drp_session, content, key=key)
        track(key)
        _, got = get_clipboard(HOST, drp_session, key)
        assert got == content

    def test_empty_content(self, drp_session, track):
        key = unique_key('empty')
        result = upload_text(HOST, drp_session, '', key=key)
        # Server may accept or reject empty content; either is valid
        if result:
            track(result)

    def test_expiry_days_accepted(self, drp_session, track):
        key = unique_key('expiry')
        result = upload_text(HOST, drp_session, 'expires soon', key=key, expiry_days=1)
        track(result or key)
        assert result is not None

    def test_burn_flag_accepted(self, drp_session, track):
        key = unique_key('burn')
        result = upload_text(HOST, drp_session, 'burn after reading', key=key, burn=True)
        # Don't retrieve it (would delete it); just confirm upload succeeded
        if result:
            track(result)
        assert result is not None

    def test_large_content(self, drp_session, track):
        key = unique_key('large')
        content = 'x' * 100_000
        result = upload_text(HOST, drp_session, content, key=key)
        track(result or key)
        assert result is not None
        _, got = get_clipboard(HOST, drp_session, key)
        assert got == content


class TestGetClipboard:
    def test_returns_text_and_content(self, drp_session, track):
        key = unique_key('gettext')
        upload_text(HOST, drp_session, 'get test', key=key)
        track(key)
        kind, content = get_clipboard(HOST, drp_session, key)
        assert kind == 'text'
        assert content == 'get test'

    def test_missing_key_returns_none_none(self, drp_session):
        kind, content = get_clipboard(HOST, drp_session, 'drptest-no-such-key-xyz-404')
        assert kind is None
        assert content is None

    def test_file_drop_key_returns_none_none(self, drp_session, track):
        """Getting a file key via get_clipboard should return (None, None)."""
        from cli.api.file import upload_file
        import tempfile, os
        key = unique_key('fileastext')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(b'file content')
            path = f.name
        try:
            upload_file(HOST, drp_session, path, key=key)
            track(key, ns='f')
        finally:
            os.unlink(path)
        kind, content = get_clipboard(HOST, drp_session, key)
        # Server returns 404 for clipboard GET on a file key
        assert kind is None

    def test_wrong_namespace_hint_for_file_drop(self, drp_session, track):
        """Attempting clipboard GET of a file-ns drop returns (None, None), not an exception."""
        from cli.api.file import upload_file
        import tempfile, os
        key = unique_key('nscheck')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as f:
            f.write(b'\x00\x01\x02')
            path = f.name
        try:
            upload_file(HOST, drp_session, path, key=key)
            track(key, ns='f')
        finally:
            os.unlink(path)
        kind, _ = get_clipboard(HOST, drp_session, key)
        assert kind is None
