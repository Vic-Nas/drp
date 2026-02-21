"""
integration_tests/cli/test_browse.py

Integration tests for:
  drp ls     — list drops (default, long, filter by type, sort, export)
  drp status — per-drop stats and global status
  drp ping   — reachability check
  drp diff   — unified diff of two clipboard drops
  drp edit   — fetch + edit + re-upload (mocked editor)
"""

import json
import os
import tempfile

import pytest

from conftest import HOST, unique_key, run_drp
from cli.api.text import upload_text


def _upload(drp_session, label, content='content'):
    key = unique_key(label)
    upload_text(HOST, drp_session, content, key=key)
    return key


# ── drp ping ───────────────────────────────────────────────────────────────────

class TestPing:
    def test_ping_exits_zero(self, cli_env):
        r = run_drp('ping', env=cli_env, check=True)
        assert r.returncode == 0

    def test_ping_prints_reachable(self, cli_env):
        r = run_drp('ping', env=cli_env, check=True)
        assert 'reachable' in r.stdout.lower()


# ── drp status ────────────────────────────────────────────────────────────────

class TestStatus:
    def test_global_status_exits_zero(self, cli_env):
        r = run_drp('status', env=cli_env, check=True)
        assert r.returncode == 0

    def test_global_status_shows_host(self, cli_env):
        r = run_drp('status', env=cli_env, check=True)
        assert HOST in r.stdout

    def test_drop_status_exits_zero(self, cli_env, drp_session, track):
        key = _upload(drp_session, 'statuskey')
        track(key)
        r = run_drp('status', key, env=cli_env, check=True)
        assert r.returncode == 0

    def test_drop_status_shows_views(self, cli_env, drp_session, track):
        key = _upload(drp_session, 'statusviews')
        track(key)
        r = run_drp('status', key, env=cli_env, check=True)
        assert 'views' in r.stdout.lower() or '0' in r.stdout

    def test_drop_status_missing_key_exits_nonzero(self, cli_env):
        r = run_drp('status', 'drptest-no-such-status-xyz', env=cli_env)
        assert r.returncode != 0

    def test_file_drop_status(self, cli_env, drp_session, track):
        from cli.api.file import upload_file
        key = unique_key('statusfile')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(b'status file test')
            path = f.name
        try:
            upload_file(HOST, drp_session, path, key=key)
        finally:
            os.unlink(path)
        track(key, ns='f')
        r = run_drp('status', '-f', key, env=cli_env, check=True)
        assert r.returncode == 0


# ── drp ls ────────────────────────────────────────────────────────────────────

class TestLs:
    def test_ls_exits_zero(self, cli_env):
        r = run_drp('ls', env=cli_env, check=True)
        assert r.returncode == 0

    def test_ls_shows_uploaded_key(self, cli_env, drp_session, track):
        key = _upload(drp_session, 'lskey')
        track(key)
        r = run_drp('ls', env=cli_env, check=True)
        assert key in r.stdout

    def test_ls_long_format(self, cli_env, drp_session, track):
        key = _upload(drp_session, 'lslong')
        track(key)
        r = run_drp('ls', '-l', env=cli_env, check=True)
        assert r.returncode == 0
        # Long format shows time-based info
        assert 'ago' in r.stdout or 'text' in r.stdout

    def test_ls_filter_clipboard(self, cli_env, drp_session, track):
        key = _upload(drp_session, 'lstypefilter')
        track(key)
        r = run_drp('ls', '-t', 'c', env=cli_env, check=True)
        assert key in r.stdout

    def test_ls_filter_file_excludes_clipboard(self, cli_env, drp_session, track):
        key = _upload(drp_session, 'lstypefile')
        track(key)
        r = run_drp('ls', '-t', 'f', env=cli_env, check=True)
        # Clipboard key should not appear in file listing
        assert key not in r.stdout

    def test_ls_export_is_valid_json(self, cli_env, drp_session, track):
        key = _upload(drp_session, 'lsexport')
        track(key)
        r = run_drp('ls', '--export', env=cli_env, check=True)
        data = json.loads(r.stdout)
        assert 'drops' in data
        assert 'saved' in data

    def test_ls_export_contains_uploaded_key(self, cli_env, drp_session, track):
        key = _upload(drp_session, 'lsexportkey')
        track(key)
        r = run_drp('ls', '--export', env=cli_env, check=True)
        data = json.loads(r.stdout)
        keys = [d['key'] for d in data['drops']]
        assert key in keys

    def test_ls_sort_by_name(self, cli_env):
        r = run_drp('ls', '--sort', 'name', env=cli_env, check=True)
        assert r.returncode == 0

    def test_ls_sort_by_time(self, cli_env):
        r = run_drp('ls', '--sort', 'time', env=cli_env, check=True)
        assert r.returncode == 0

    def test_ls_reverse_flag(self, cli_env):
        r = run_drp('ls', '-r', env=cli_env, check=True)
        assert r.returncode == 0


# ── drp diff ──────────────────────────────────────────────────────────────────

class TestDiff:
    def test_diff_identical_drops_exits_zero(self, cli_env, drp_session, track):
        content = 'same content for diff'
        key_a = unique_key('diffa')
        key_b = unique_key('diffb')
        upload_text(HOST, drp_session, content, key=key_a)
        upload_text(HOST, drp_session, content, key=key_b)
        track(key_a)
        track(key_b)
        r = run_drp('diff', key_a, key_b, env=cli_env)
        assert r.returncode == 0
        assert 'identical' in r.stdout.lower()

    def test_diff_different_drops_exits_one(self, cli_env, drp_session, track):
        key_a = unique_key('diffca')
        key_b = unique_key('diffcb')
        upload_text(HOST, drp_session, 'content A\nline2', key=key_a)
        upload_text(HOST, drp_session, 'content B\nline2', key=key_b)
        track(key_a)
        track(key_b)
        r = run_drp('diff', key_a, key_b, env=cli_env)
        assert r.returncode == 1  # diff convention: exit 1 when different

    def test_diff_output_contains_unified_diff_markers(self, cli_env, drp_session, track):
        key_a = unique_key('diffma')
        key_b = unique_key('diffmb')
        upload_text(HOST, drp_session, 'original line', key=key_a)
        upload_text(HOST, drp_session, 'changed line', key=key_b)
        track(key_a)
        track(key_b)
        r = run_drp('diff', key_a, key_b, env=cli_env)
        # Unified diff has --- and +++ headers
        assert '---' in r.stdout or '+' in r.stdout

    def test_diff_missing_key_exits_two(self, cli_env, drp_session, track):
        key = _upload(drp_session, 'diffmissing')
        track(key)
        r = run_drp('diff', key, 'drptest-no-such-diff-xyz', env=cli_env)
        assert r.returncode == 2


# ── drp edit ──────────────────────────────────────────────────────────────────

class TestEdit:
    def test_edit_no_change_prints_no_changes(self, cli_env, drp_session, track, tmp_path):
        """If the editor makes no change, drp edit should say '(no changes)'."""
        key = _upload(drp_session, 'editnochange', 'edit content unchanged')
        track(key)

        # Editor that immediately exits without modifying the file
        editor_script = tmp_path / 'noop_editor.sh'
        editor_script.write_text('#!/bin/sh\nexit 0\n')
        editor_script.chmod(0o755)

        env = cli_env.copy()
        env['EDITOR'] = str(editor_script)
        r = run_drp('edit', key, env=env)
        assert 'no changes' in r.stdout.lower() or r.returncode == 0

    def test_edit_with_change_updates_content(self, cli_env, drp_session, track, tmp_path):
        """Editor that appends a line; drp edit should re-upload."""
        key = _upload(drp_session, 'editchange', 'original content')
        track(key)

        editor_script = tmp_path / 'append_editor.sh'
        editor_script.write_text('#!/bin/sh\necho "appended line" >> "$1"\n')
        editor_script.chmod(0o755)

        env = cli_env.copy()
        env['EDITOR'] = str(editor_script)
        r = run_drp('edit', key, env=env)
        assert r.returncode == 0

        from cli.api.text import get_clipboard
        _, content = get_clipboard(HOST, drp_session, key)
        assert 'appended line' in content

    def test_edit_missing_key_exits_nonzero(self, cli_env, tmp_path):
        editor_script = tmp_path / 'noop.sh'
        editor_script.write_text('#!/bin/sh\nexit 0\n')
        editor_script.chmod(0o755)
        env = cli_env.copy()
        env['EDITOR'] = str(editor_script)
        r = run_drp('edit', 'drptest-no-such-edit-xyz', env=env)
        assert r.returncode != 0
