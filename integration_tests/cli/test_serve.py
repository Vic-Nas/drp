"""
integration_tests/cli/test_serve.py

Integration tests for drp serve:
  - single file
  - multiple explicit files
  - directory (all top-level files)
  - glob pattern
  - --expires flag
  - output format (URL table)
  - partial failure (one bad file)
"""

import glob
import os
import tempfile
from pathlib import Path

import pytest

from conftest import HOST, unique_key, run_drp
from cli.api.file import get_file


def _make_file(directory, name, content=b'serve test content'):
    path = Path(directory) / name
    path.write_bytes(content)
    return str(path)


# ── drp serve ────────────────────────────────────────────────────────────────

class TestServe:
    def test_serve_single_file_exits_zero(self, cli_env, track, tmp_path):
        path = _make_file(tmp_path, 'single.txt')
        r = run_drp('serve', path, env=cli_env, check=True)
        assert r.returncode == 0

    def test_serve_single_file_prints_url(self, cli_env, track, tmp_path):
        path = _make_file(tmp_path, 'urlprint.txt')
        r = run_drp('serve', path, env=cli_env, check=True)
        assert f'{HOST}/f/' in r.stdout

    def test_serve_file_is_downloadable(self, cli_env, drp_session, track, tmp_path):
        payload = b'serve-and-download'
        path = _make_file(tmp_path, 'download.txt', content=payload)
        r = run_drp('serve', path, env=cli_env, check=True)
        # Extract the key from the printed URL: /f/<key>/
        import re
        match = re.search(r'/f/([^/]+)/', r.stdout)
        assert match, f'No file URL found in output:\n{r.stdout}'
        key = match.group(1)
        track(key, ns='f')
        kind, (content, _) = get_file(HOST, drp_session, key)
        assert kind == 'file'
        assert content == payload

    def test_serve_multiple_files(self, cli_env, track, tmp_path):
        paths = [
            _make_file(tmp_path, 'multi1.txt', b'file one'),
            _make_file(tmp_path, 'multi2.txt', b'file two'),
            _make_file(tmp_path, 'multi3.txt', b'file three'),
        ]
        r = run_drp('serve', *paths, env=cli_env, check=True)
        assert r.returncode == 0
        # All three filenames should appear in output
        for p in paths:
            assert os.path.basename(p) in r.stdout

    def test_serve_multiple_files_all_have_urls(self, cli_env, track, tmp_path):
        import re
        paths = [_make_file(tmp_path, f'murl{i}.txt') for i in range(3)]
        r = run_drp('serve', *paths, env=cli_env, check=True)
        urls = re.findall(r'/f/([^/\s]+)/', r.stdout)
        assert len(urls) == 3
        for key in urls:
            track(key, ns='f')

    def test_serve_directory(self, cli_env, track, tmp_path):
        subdir = tmp_path / 'dist'
        subdir.mkdir()
        for i in range(3):
            (subdir / f'file{i}.txt').write_bytes(f'content {i}'.encode())
        r = run_drp('serve', str(subdir), env=cli_env, check=True)
        assert r.returncode == 0
        # Should mention all 3 files
        for i in range(3):
            assert f'file{i}.txt' in r.stdout

    def test_serve_directory_not_recursive(self, cli_env, track, tmp_path):
        """Files in subdirectories should not be uploaded."""
        subdir = tmp_path / 'dist2'
        subdir.mkdir()
        (subdir / 'top.txt').write_bytes(b'top level')
        nested = subdir / 'sub'
        nested.mkdir()
        (nested / 'nested.txt').write_bytes(b'nested')

        r = run_drp('serve', str(subdir), env=cli_env, check=True)
        assert 'top.txt' in r.stdout
        assert 'nested.txt' not in r.stdout

    def test_serve_glob_pattern(self, cli_env, track, tmp_path):
        for i in range(3):
            (tmp_path / f'report{i}.log').write_bytes(f'log {i}'.encode())
        (tmp_path / 'notes.txt').write_bytes(b'not a log')

        pattern = str(tmp_path / '*.log')
        r = run_drp('serve', pattern, env=cli_env, check=True)
        assert r.returncode == 0
        for i in range(3):
            assert f'report{i}.log' in r.stdout
        assert 'notes.txt' not in r.stdout

    def test_serve_with_expires_flag(self, cli_env, track, tmp_path):
        path = _make_file(tmp_path, 'expiry.txt')
        r = run_drp('serve', path, '--expires', '7d', env=cli_env, check=True)
        assert r.returncode == 0

    def test_serve_nonexistent_path_exits_nonzero(self, cli_env):
        r = run_drp('serve', '/tmp/drp-no-such-dir-xyz/', env=cli_env)
        assert r.returncode != 0

    def test_serve_output_summary_line(self, cli_env, track, tmp_path):
        """Output should include a count summary like '3 uploaded'."""
        paths = [_make_file(tmp_path, f'sum{i}.txt') for i in range(3)]
        r = run_drp('serve', *paths, env=cli_env, check=True)
        assert 'uploaded' in r.stdout.lower()

    def test_serve_binary_file(self, cli_env, track, tmp_path):
        payload = bytes(range(256))
        path = _make_file(tmp_path, 'binary.bin', content=payload)
        r = run_drp('serve', path, env=cli_env, check=True)
        assert r.returncode == 0
