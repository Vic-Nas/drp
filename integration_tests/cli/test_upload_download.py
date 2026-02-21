"""
integration_tests/cli/test_upload_download.py
drp up / drp get — text, stdin, file, --url flag, cross-plan and anon access.
"""
import os
import tempfile
import pytest
from conftest import HOST, unique_key, run_drp


class TestUpText:
    def test_upload_prints_url(self, cli_envs, free_user):
        key = free_user.track(unique_key('uptext'))
        r = run_drp('up', 'hello', '-k', key, env=cli_envs['free'], check=True)
        assert f'/{key}/' in r.stdout

    def test_roundtrip(self, cli_envs, free_user):
        key = free_user.track(unique_key('uprt'))
        run_drp('up', 'roundtrip-xyz', '-k', key, env=cli_envs['free'], check=True)
        r = run_drp('get', key, env=cli_envs['free'], check=True)
        assert 'roundtrip-xyz' in r.stdout

    def test_with_expiry(self, cli_envs, starter_user):
        key = starter_user.track(unique_key('upexpiry'))
        r = run_drp('up', 'expires', '-k', key, '-e', '7d', env=cli_envs['starter'], check=True)
        assert r.returncode == 0

    def test_burn_flag(self, cli_envs, free_user):
        key = unique_key('upburn')
        r = run_drp('up', 'burn', '-k', key, '--burn', env=cli_envs['free'], check=True)
        assert r.returncode == 0

    def test_each_plan_can_upload(self, cli_envs, free_user, starter_user, pro_user):
        for name, user in (('free', free_user), ('starter', starter_user), ('pro', pro_user)):
            key = user.track(unique_key('planup'))
            r = run_drp('up', f'{name} content', '-k', key, env=cli_envs[name], check=True)
            assert r.returncode == 0


class TestUpStdin:
    def test_stdin_roundtrip(self, cli_envs, free_user):
        key = free_user.track(unique_key('stdin'))
        run_drp('up', '-k', key, env=cli_envs['free'], input='piped content', check=True)
        r = run_drp('get', key, env=cli_envs['free'], check=True)
        assert 'piped content' in r.stdout


class TestUpFile:
    def test_file_upload_prints_file_url(self, cli_envs, free_user):
        key = free_user.track(unique_key('upfile'), ns='f')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(b'file upload'); path = f.name
        try:
            r = run_drp('up', path, '-k', key, env=cli_envs['free'], check=True)
        finally:
            os.unlink(path)
        assert f'/f/{key}/' in r.stdout

    def test_file_roundtrip(self, cli_envs, free_user, tmp_path):
        key = free_user.track(unique_key('filert'), ns='f')
        payload = b'file roundtrip content'
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(payload); path = f.name
        try:
            run_drp('up', path, '-k', key, env=cli_envs['free'], check=True)
        finally:
            os.unlink(path)
        out = str(tmp_path / 'out.txt')
        run_drp('get', '-f', key, '-o', out, env=cli_envs['free'], check=True)
        assert open(out, 'rb').read() == payload


class TestGetFlags:
    def test_url_flag_prints_url_only(self, cli_envs, free_user):
        key = free_user.track(unique_key('geturlf'))
        run_drp('up', 'url flag content', '-k', key, env=cli_envs['free'], check=True)
        r = run_drp('get', key, '--url', env=cli_envs['free'], check=True)
        assert f'{HOST}/{key}/' in r.stdout
        assert 'url flag content' not in r.stdout

    def test_anon_can_get_clipboard(self, cli_envs, anon_cli_env, free_user):
        key = free_user.track(unique_key('anonget'))
        run_drp('up', 'anon readable', '-k', key, env=cli_envs['free'], check=True)
        r = run_drp('get', key, env=anon_cli_env, check=True)
        assert 'anon readable' in r.stdout

    def test_missing_key_exits_nonzero(self, anon_cli_env):
        r = run_drp('get', 'drptest-no-such-key-xyz', env=anon_cli_env)
        assert r.returncode != 0
