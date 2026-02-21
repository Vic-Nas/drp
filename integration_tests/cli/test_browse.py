"""
integration_tests/cli/test_browse.py
drp ls / status / ping / diff / edit
"""
import json
import os
import tempfile
import pytest
from conftest import HOST, unique_key, run_drp
from cli.api.text import upload_text


def _up(user, label, content='content'):
    key = unique_key(label)
    upload_text(HOST, user.session, content, key=key)
    return key


class TestPing:
    def test_ping_exits_zero(self, anon_cli_env):
        assert run_drp('ping', env=anon_cli_env).returncode == 0

    def test_ping_prints_reachable(self, anon_cli_env):
        r = run_drp('ping', env=anon_cli_env)
        assert 'reachable' in r.stdout.lower()


class TestStatus:
    def test_global_status(self, cli_envs):
        r = run_drp('status', env=cli_envs['free'], check=True)
        assert HOST in r.stdout

    def test_drop_status(self, cli_envs, free_user):
        key = free_user.track(_up(free_user, 'status'))
        r = run_drp('status', key, env=cli_envs['free'], check=True)
        assert r.returncode == 0

    def test_missing_key_exits_nonzero(self, cli_envs):
        r = run_drp('status', 'drptest-no-such-status-xyz', env=cli_envs['free'])
        assert r.returncode != 0


class TestLs:
    def test_ls_shows_own_drops(self, cli_envs, free_user):
        key = free_user.track(_up(free_user, 'ls'))
        r = run_drp('ls', env=cli_envs['free'], check=True)
        assert key in r.stdout

    def test_ls_does_not_show_other_users_drops(self, cli_envs, free_user, starter_user):
        free_key    = free_user.track(_up(free_user, 'lsown'))
        starter_key = starter_user.track(_up(starter_user, 'lsown'))
        r_free    = run_drp('ls', env=cli_envs['free'],    check=True)
        r_starter = run_drp('ls', env=cli_envs['starter'], check=True)
        assert free_key    in r_free.stdout
        assert starter_key not in r_free.stdout
        assert starter_key in r_starter.stdout
        assert free_key    not in r_starter.stdout

    def test_ls_export_valid_json(self, cli_envs, free_user):
        free_user.track(_up(free_user, 'lsexport'))
        r = run_drp('ls', '--export', env=cli_envs['free'], check=True)
        data = json.loads(r.stdout)
        assert 'drops' in data

    def test_ls_long_format(self, cli_envs):
        r = run_drp('ls', '-l', env=cli_envs['free'], check=True)
        assert r.returncode == 0

    def test_anon_ls_empty_or_blocked(self, anon_cli_env):
        r = run_drp('ls', env=anon_cli_env)
        # Either returns empty list or exits non-zero — no crash
        assert 'Traceback' not in r.stderr


class TestDiff:
    def test_identical_drops(self, cli_envs, free_user):
        content = 'same content'
        a = free_user.track(_up(free_user, 'diffa', content))
        b = free_user.track(_up(free_user, 'diffb', content))
        r = run_drp('diff', a, b, env=cli_envs['free'])
        assert r.returncode == 0
        assert 'identical' in r.stdout.lower()

    def test_different_drops_exit_one(self, cli_envs, free_user):
        a = free_user.track(_up(free_user, 'diffca', 'content A'))
        b = free_user.track(_up(free_user, 'diffcb', 'content B'))
        r = run_drp('diff', a, b, env=cli_envs['free'])
        assert r.returncode == 1

    def test_diff_across_users(self, cli_envs, free_user, starter_user):
        """diff should work even when drops belong to different users."""
        a = free_user.track(_up(free_user, 'diffxa', 'free content'))
        b = starter_user.track(_up(starter_user, 'diffxb', 'starter content'))
        r = run_drp('diff', a, b, env=cli_envs['free'])
        assert r.returncode in (0, 1)   # 0=identical, 1=different — not 2 (error)


class TestEdit:
    def test_no_change_skips_upload(self, cli_envs, free_user, tmp_path):
        key = free_user.track(_up(free_user, 'editnoop', 'unchanged'))
        editor = tmp_path / 'noop.sh'
        editor.write_text('#!/bin/sh\nexit 0\n'); editor.chmod(0o755)
        env = {**cli_envs['free'], 'EDITOR': str(editor)}
        r = run_drp('edit', key, env=env)
        assert 'no changes' in r.stdout.lower() or r.returncode == 0

    def test_change_updates_content(self, cli_envs, free_user, tmp_path):
        from cli.api.text import get_clipboard
        key = free_user.track(_up(free_user, 'editchange', 'original'))
        editor = tmp_path / 'append.sh'
        editor.write_text('#!/bin/sh\necho "appended" >> "$1"\n'); editor.chmod(0o755)
        env = {**cli_envs['free'], 'EDITOR': str(editor)}
        run_drp('edit', key, env=env, check=True)
        _, content = get_clipboard(HOST, free_user.session, key)
        assert 'appended' in content
