"""
integration_tests/cli/test_upload_download.py

Integration tests for:
  drp up  — text string, stdin pipe, file path, https:// URL
  drp get — clipboard text, file download, --url flag, password prompt skipped

All tests drive the real `drp` binary via subprocess against the live server.
"""

import os
import re
import tempfile

import pytest

from conftest import HOST, unique_key, run_drp


# ── drp up — text ──────────────────────────────────────────────────────────────

class TestUpText:
    def test_upload_text_string_prints_url(self, cli_env, track):
        key = unique_key('uptext')
        r = run_drp('up', 'hello integration', '-k', key, env=cli_env, check=True)
        track(key)
        assert f'/{key}/' in r.stdout

    def test_upload_text_url_is_reachable(self, cli_env, track):
        import requests as req
        key = unique_key('upreach')
        run_drp('up', 'reachable', '-k', key, env=cli_env, check=True)
        track(key)
        res = req.get(f'{HOST}/{key}/', headers={'Accept': 'application/json'}, timeout=10)
        assert res.ok
        assert res.json().get('kind') == 'text'

    def test_upload_text_roundtrip_content(self, cli_env, track):
        key = unique_key('upcontent')
        content = 'roundtrip-content-xyz-12345'
        run_drp('up', content, '-k', key, env=cli_env, check=True)
        track(key)
        r = run_drp('get', key, env=cli_env, check=True)
        assert content in r.stdout

    def test_upload_with_expiry_flag(self, cli_env, track):
        key = unique_key('upexpiry')
        r = run_drp('up', 'expires', '-k', key, '-e', '1d', env=cli_env, check=True)
        track(key)
        assert r.returncode == 0

    def test_upload_burn_flag(self, cli_env, track):
        key = unique_key('upburn')
        r = run_drp('up', 'burn after reading', '-k', key, '--burn', env=cli_env, check=True)
        # Don't fetch — that would consume the drop. Just verify exit 0.
        if key not in r.stdout:
            track(key)  # might not have been created under the exact key
        assert r.returncode == 0

    def test_upload_unicode(self, cli_env, track):
        key = unique_key('upuni')
        content = 'こんにちは 🌸'
        run_drp('up', content, '-k', key, env=cli_env, check=True)
        track(key)
        r = run_drp('get', key, env=cli_env, check=True)
        assert content in r.stdout

    def test_upload_large_text(self, cli_env, track):
        key = unique_key('uplarge')
        content = 'A' * 50_000
        r = run_drp('up', content, '-k', key, env=cli_env, check=True)
        track(key)
        assert r.returncode == 0


class TestUpStdin:
    def test_stdin_pipe_uploads_content(self, cli_env, track):
        key = unique_key('stdin')
        r = run_drp('up', '-k', key, env=cli_env, input='piped content\n', check=True)
        track(key)
        assert r.returncode == 0

    def test_stdin_content_is_retrievable(self, cli_env, track):
        key = unique_key('stdinget')
        content = 'stdin-roundtrip-content'
        run_drp('up', '-k', key, env=cli_env, input=content, check=True)
        track(key)
        r = run_drp('get', key, env=cli_env, check=True)
        assert content in r.stdout

    def test_stdin_multiline(self, cli_env, track):
        key = unique_key('stdinml')
        content = 'line1\nline2\nline3'
        run_drp('up', '-k', key, env=cli_env, input=content, check=True)
        track(key)
        r = run_drp('get', key, env=cli_env, check=True)
        assert 'line1' in r.stdout
        assert 'line3' in r.stdout


class TestUpFile:
    def test_upload_file_prints_file_url(self, cli_env, track):
        key = unique_key('upfile')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(b'file upload test')
            path = f.name
        try:
            r = run_drp('up', path, '-k', key, env=cli_env, check=True)
        finally:
            os.unlink(path)
        track(key, ns='f')
        assert f'/f/{key}/' in r.stdout

    def test_upload_binary_file(self, cli_env, track):
        key = unique_key('upbin')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as f:
            f.write(bytes(range(256)) * 100)
            path = f.name
        try:
            r = run_drp('up', path, '-k', key, env=cli_env, check=True)
        finally:
            os.unlink(path)
        track(key, ns='f')
        assert r.returncode == 0

    def test_upload_file_downloadable(self, cli_env, track, tmp_path):
        key = unique_key('upfileddl')
        payload = b'download this file'
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(payload)
            path = f.name
        try:
            run_drp('up', path, '-k', key, env=cli_env, check=True)
        finally:
            os.unlink(path)
        track(key, ns='f')

        out_path = str(tmp_path / 'downloaded.txt')
        run_drp('get', '-f', key, '-o', out_path, env=cli_env, check=True)
        assert os.path.exists(out_path)
        assert open(out_path, 'rb').read() == payload


# ── drp get ────────────────────────────────────────────────────────────────────

class TestGetClipboard:
    def test_get_prints_content(self, cli_env, track):
        key = unique_key('getclip')
        run_drp('up', 'get test content', '-k', key, env=cli_env, check=True)
        track(key)
        r = run_drp('get', key, env=cli_env, check=True)
        assert 'get test content' in r.stdout

    def test_get_missing_key_exits_nonzero(self, cli_env):
        r = run_drp('get', 'drptest-no-such-key-xyz', env=cli_env)
        assert r.returncode != 0

    def test_get_url_flag_prints_url_only(self, cli_env, track):
        key = unique_key('geturlf')
        run_drp('up', 'url flag test', '-k', key, env=cli_env, check=True)
        track(key)
        r = run_drp('get', key, '--url', env=cli_env, check=True)
        assert f'{HOST}/{key}/' in r.stdout
        # Should not contain the content itself
        assert 'url flag test' not in r.stdout

    def test_get_file_url_flag(self, cli_env, track):
        key = unique_key('getfileurlf')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(b'url flag file')
            path = f.name
        try:
            run_drp('up', path, '-k', key, env=cli_env, check=True)
        finally:
            os.unlink(path)
        track(key, ns='f')
        r = run_drp('get', '-f', key, '--url', env=cli_env, check=True)
        assert f'/f/{key}/' in r.stdout


class TestGetFile:
    def test_get_file_saves_to_disk(self, cli_env, track, tmp_path):
        key = unique_key('getfile')
        payload = b'saved to disk'
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(payload)
            path = f.name
        try:
            run_drp('up', path, '-k', key, env=cli_env, check=True)
        finally:
            os.unlink(path)
        track(key, ns='f')

        out = str(tmp_path / 'out.txt')
        run_drp('get', '-f', key, '-o', out, env=cli_env, check=True)
        assert open(out, 'rb').read() == payload

    def test_get_file_wrong_namespace_hint(self, cli_env, track):
        """drp get (no -f) on a file drop gives a helpful hint and exits non-zero."""
        key = unique_key('gethint')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(b'hint test')
            path = f.name
        try:
            run_drp('up', path, '-k', key, env=cli_env, check=True)
        finally:
            os.unlink(path)
        track(key, ns='f')
        r = run_drp('get', key, env=cli_env)
        # Should mention -f flag in output
        combined = r.stdout + r.stderr
        assert '-f' in combined or 'file' in combined.lower()
