"""
integration_tests/core/test_api_file.py

Tests for cli/api/file.py: upload_file and get_file.
Covers the full prepare → B2 PUT → confirm flow, and all get_file return paths:
  ('file', (bytes, filename)) | ('password_required', None) | (None, None)
"""

import os
import tempfile

import pytest

from conftest import HOST, unique_key
from cli.api.file import upload_file, get_file


# ── Helpers ────────────────────────────────────────────────────────────────────

def _tmp_file(content=b'integration test content', suffix='.txt'):
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(content)
    f.close()
    return f.name


# ── Upload ─────────────────────────────────────────────────────────────────────

class TestUploadFile:
    def test_basic_upload_returns_key(self, drp_session, track):
        path = _tmp_file()
        key = unique_key('file')
        try:
            result = upload_file(HOST, drp_session, path, key=key)
        finally:
            os.unlink(path)
        track(result or key, ns='f')
        assert isinstance(result, str)
        assert len(result) > 0

    def test_custom_key_honoured(self, drp_session, track):
        path = _tmp_file()
        key = unique_key('customfile')
        try:
            result = upload_file(HOST, drp_session, path, key=key)
        finally:
            os.unlink(path)
        track(result or key, ns='f')
        assert result == key

    def test_uploaded_bytes_round_trip(self, drp_session, track):
        payload = b'binary payload \x00\x01\x02\xff'
        path = _tmp_file(content=payload, suffix='.bin')
        key = unique_key('bytes')
        try:
            result = upload_file(HOST, drp_session, path, key=key)
        finally:
            os.unlink(path)
        track(result or key, ns='f')

        kind, (content, _) = get_file(HOST, drp_session, key)
        assert kind == 'file'
        assert content == payload

    def test_filename_preserved(self, drp_session, track):
        path = _tmp_file(suffix='.pdf')
        original_name = os.path.basename(path)
        key = unique_key('filename')
        try:
            result = upload_file(HOST, drp_session, path, key=key)
        finally:
            os.unlink(path)
        track(result or key, ns='f')

        _, (_, returned_name) = get_file(HOST, drp_session, key)
        assert returned_name == original_name

    def test_large_file(self, drp_session, track):
        """5 MB file — exercises chunked streaming upload."""
        payload = b'L' * (5 * 1024 * 1024)
        path = _tmp_file(content=payload, suffix='.bin')
        key = unique_key('large')
        try:
            result = upload_file(HOST, drp_session, path, key=key)
        finally:
            os.unlink(path)
        track(result or key, ns='f')
        assert result is not None

        kind, (content, _) = get_file(HOST, drp_session, key)
        assert kind == 'file'
        assert len(content) == 5 * 1024 * 1024

    def test_expiry_days_accepted(self, drp_session, track):
        path = _tmp_file()
        key = unique_key('fexpiry')
        try:
            result = upload_file(HOST, drp_session, path, key=key, expiry_days=7)
        finally:
            os.unlink(path)
        track(result or key, ns='f')
        assert result is not None

    def test_various_content_types(self, drp_session, track):
        cases = [
            (b'{"key": "value"}', '.json'),
            (b'<html></html>',    '.html'),
            (b'col1,col2\n1,2',  '.csv'),
        ]
        for payload, suffix in cases:
            path = _tmp_file(content=payload, suffix=suffix)
            key = unique_key('ctype')
            try:
                result = upload_file(HOST, drp_session, path, key=key)
            finally:
                os.unlink(path)
            track(result or key, ns='f')
            assert result is not None, f'Upload failed for {suffix}'


# ── Download ───────────────────────────────────────────────────────────────────

class TestGetFile:
    def test_returns_file_tuple(self, drp_session, track):
        payload = b'download me'
        path = _tmp_file(content=payload)
        key = unique_key('getfile')
        try:
            upload_file(HOST, drp_session, path, key=key)
        finally:
            os.unlink(path)
        track(key, ns='f')

        kind, result = get_file(HOST, drp_session, key)
        assert kind == 'file'
        content, filename = result
        assert content == payload

    def test_missing_key_returns_none_none(self, drp_session):
        kind, result = get_file(HOST, drp_session, 'drptest-no-such-file-key-xyz')
        assert kind is None
        assert result is None

    def test_clipboard_key_via_file_endpoint_returns_none(self, drp_session, track):
        """GETting a clipboard key through /f/<key>/ should return (None, None)."""
        from cli.api.text import upload_text
        key = unique_key('clipasfile')
        upload_text(HOST, drp_session, 'clipboard', key=key)
        track(key, ns='c')
        kind, result = get_file(HOST, drp_session, key)
        assert kind is None
