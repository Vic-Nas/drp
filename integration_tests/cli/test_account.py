"""
integration_tests/cli/test_account.py

Integration tests for:
  drp save   — bookmark a drop (clipboard and file)
  drp load   — import a JSON export as saved drops
  drp login  — login flow via subprocess (non-interactive via env override)
  drp logout — clears session
"""

import json
import os
import tempfile

import pytest

from conftest import HOST, EMAIL, PASSWORD, unique_key, run_drp
from cli.api.text import upload_text


def _upload(drp_session, label, content='content'):
    key = unique_key(label)
    upload_text(HOST, drp_session, content, key=key)
    return key


# ── drp save ──────────────────────────────────────────────────────────────────

class TestSave:
    def test_save_clipboard_exits_zero(self, cli_env, drp_session, track):
        key = _upload(drp_session, 'saveclip')
        track(key)
        r = run_drp('save', key, env=cli_env, check=True)
        assert r.returncode == 0

    def test_save_clipboard_appears_in_ls(self, cli_env, drp_session, track):
        key = _upload(drp_session, 'savels')
        track(key)
        run_drp('save', key, env=cli_env, check=True)
        r = run_drp('ls', '-t', 's', env=cli_env, check=True)
        assert key in r.stdout

    def test_save_file_drop(self, cli_env, drp_session, track):
        from cli.api.file import upload_file
        key = unique_key('savefile')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(b'save file test')
            path = f.name
        try:
            upload_file(HOST, drp_session, path, key=key)
        finally:
            os.unlink(path)
        track(key, ns='f')
        r = run_drp('save', '-f', key, env=cli_env, check=True)
        assert r.returncode == 0

    def test_save_missing_key_exits_nonzero(self, cli_env):
        r = run_drp('save', 'drptest-no-such-save-xyz', env=cli_env)
        assert r.returncode != 0

    def test_save_prints_confirmation(self, cli_env, drp_session, track):
        key = _upload(drp_session, 'saveconfirm')
        track(key)
        r = run_drp('save', key, env=cli_env, check=True)
        assert '✓' in r.stdout or 'saved' in r.stdout.lower()


# ── drp load ──────────────────────────────────────────────────────────────────

class TestLoad:
    def _make_export(self, drp_session, track, n=2):
        """Create n clipboard drops, export them as JSON."""
        keys = []
        for i in range(n):
            key = _upload(drp_session, f'loadkey{i}')
            track(key)
            keys.append(key)
        # Build the export JSON manually (same format as drp ls --export)
        drops = [{'key': k, 'ns': 'c', 'kind': 'text', 'created_at': '2026-01-01T00:00:00+00:00'}
                 for k in keys]
        return {'drops': drops, 'saved': []}

    def test_load_valid_export_exits_zero(self, cli_env, drp_session, track, tmp_path):
        export = self._make_export(drp_session, track)
        export_file = tmp_path / 'export.json'
        export_file.write_text(json.dumps(export))
        r = run_drp('load', str(export_file), env=cli_env, check=True)
        assert r.returncode == 0

    def test_load_reports_import_count(self, cli_env, drp_session, track, tmp_path):
        export = self._make_export(drp_session, track, n=2)
        export_file = tmp_path / 'export2.json'
        export_file.write_text(json.dumps(export))
        r = run_drp('load', str(export_file), env=cli_env, check=True)
        # Should mention how many were imported
        assert any(c.isdigit() for c in r.stdout)

    def test_load_from_ls_export(self, cli_env, drp_session, track, tmp_path):
        """Round-trip: ls --export then load."""
        key = _upload(drp_session, 'loadrtkey')
        track(key)
        # Export
        r = run_drp('ls', '--export', env=cli_env, check=True)
        export_file = tmp_path / 'roundtrip.json'
        export_file.write_text(r.stdout)
        # Load (may say "already saved" for existing drops — that's fine)
        r2 = run_drp('load', str(export_file), env=cli_env)
        assert r2.returncode == 0

    def test_load_missing_file_exits_nonzero(self, cli_env):
        r = run_drp('load', '/tmp/drp-no-such-export-xyz.json', env=cli_env)
        assert r.returncode != 0

    def test_load_invalid_json_exits_nonzero(self, cli_env, tmp_path):
        bad = tmp_path / 'bad.json'
        bad.write_text('this is not json {{{{')
        r = run_drp('load', str(bad), env=cli_env)
        assert r.returncode != 0


# ── drp login / logout ────────────────────────────────────────────────────────

class TestLoginLogout:
    def test_logout_exits_zero(self, cli_env):
        r = run_drp('logout', env=cli_env, check=True)
        assert r.returncode == 0

    def test_logout_prints_confirmation(self, cli_env):
        r = run_drp('logout', env=cli_env)
        combined = r.stdout + r.stderr
        # Either "Logged out" or "(already anonymous)"
        assert 'logged out' in combined.lower() or 'anonymous' in combined.lower()

    def test_login_with_correct_credentials(self, cli_env, config_dir):
        """
        drp login is interactive (prompts for email + password).
        We simulate it by writing credentials to stdin.
        """
        # First log out to clear state
        run_drp('logout', env=cli_env)
        # Feed email\npassword\n to stdin
        r = run_drp('login', env=cli_env, input=f'{EMAIL}\n{PASSWORD}\n')
        assert r.returncode == 0
        combined = r.stdout + r.stderr
        assert 'logged in' in combined.lower() or EMAIL in combined

    def test_login_wrong_password_exits_nonzero(self, cli_env):
        run_drp('logout', env=cli_env)
        r = run_drp('login', env=cli_env, input=f'{EMAIL}\nwrong-password-xyz\n')
        assert r.returncode != 0

    def test_login_restores_session_for_ls(self, cli_env):
        """After login, ls should work (requires authenticated session)."""
        run_drp('logout', env=cli_env)
        run_drp('login', env=cli_env, input=f'{EMAIL}\n{PASSWORD}\n', check=True)
        r = run_drp('ls', env=cli_env, check=True)
        assert r.returncode == 0
