"""
integration_tests/cli/test_manage.py
drp rm / mv / cp / renew — including cross-user ownership enforcement.
"""
import os
import tempfile
import pytest
from conftest import HOST, unique_key, run_drp
from cli.api.text import upload_text


def _up(user, label, content='content'):
    key = unique_key(label)
    upload_text(HOST, user.session, content, key=key)
    return key


class TestRm:
    def test_owner_can_delete(self, cli_envs, free_user):
        key = _up(free_user, 'rm')
        r = run_drp('rm', key, env=cli_envs['free'], check=True)
        assert r.returncode == 0

    def test_other_user_cannot_delete(self, cli_envs, free_user, starter_user):
        key = free_user.track(_up(free_user, 'rmx'))
        r = run_drp('rm', key, env=cli_envs['starter'])
        assert r.returncode != 0

    def test_anon_cannot_delete(self, anon_cli_env, free_user):
        key = free_user.track(_up(free_user, 'rmanon'))
        r = run_drp('rm', key, env=anon_cli_env)
        assert r.returncode != 0

    def test_missing_key_exits_nonzero(self, cli_envs):
        r = run_drp('rm', 'drptest-no-such-rm-xyz', env=cli_envs['free'])
        assert r.returncode != 0


class TestMv:
    def test_owner_can_rename(self, cli_envs, free_user):
        old = _up(free_user, 'mvold')
        new = free_user.track(unique_key('mvnew'))
        r = run_drp('mv', old, new, env=cli_envs['free'], check=True)
        assert new in r.stdout

    def test_other_user_cannot_rename(self, cli_envs, free_user, starter_user):
        key = free_user.track(_up(free_user, 'mvx'))
        r = run_drp('mv', key, unique_key('dest'), env=cli_envs['starter'])
        assert r.returncode != 0

    def test_rename_to_taken_key_fails(self, cli_envs, free_user):
        a = free_user.track(_up(free_user, 'mvtakena'))
        b = free_user.track(_up(free_user, 'mvtakenb'))
        r = run_drp('mv', a, b, env=cli_envs['free'])
        assert r.returncode != 0


class TestCp:
    def test_copy_clipboard(self, cli_envs, free_user):
        src = free_user.track(_up(free_user, 'cpsrc', 'copy me'))
        dst = free_user.track(unique_key('cpdst'))
        r = run_drp('cp', src, dst, env=cli_envs['free'], check=True)
        assert r.returncode == 0

    def test_copy_preserves_content(self, cli_envs, free_user):
        from cli.api.text import get_clipboard
        content = 'copy-content-marker'
        src = unique_key('cpcontsrc')
        upload_text(HOST, free_user.session, content, key=src)
        free_user.track(src)
        dst = free_user.track(unique_key('cpcontdst'))
        run_drp('cp', src, dst, env=cli_envs['free'], check=True)
        _, got = get_clipboard(HOST, free_user.session, dst)
        assert got == content

    def test_source_still_exists_after_copy(self, cli_envs, free_user):
        from cli.api.text import get_clipboard
        src = free_user.track(_up(free_user, 'cpsrcexists', 'still here'))
        dst = free_user.track(unique_key('cpdstexists'))
        run_drp('cp', src, dst, env=cli_envs['free'], check=True)
        kind, _ = get_clipboard(HOST, free_user.session, src)
        assert kind == 'text'


class TestRenew:
    def test_free_plan_renew_blocked(self, cli_envs, free_user):
        key = free_user.track(_up(free_user, 'renewfree'))
        r = run_drp('renew', key, env=cli_envs['free'])
        # Should exit non-zero or print a plan-limit message
        combined = r.stdout + r.stderr
        assert r.returncode != 0 or 'plan' in combined.lower() or 'upgrade' in combined.lower()
        assert 'Traceback' not in r.stderr

    def test_starter_renew_no_crash(self, cli_envs, starter_user):
        key = starter_user.track(_up(starter_user, 'renewstarter'))
        r = run_drp('renew', key, env=cli_envs['starter'])
        assert 'Traceback' not in r.stderr
