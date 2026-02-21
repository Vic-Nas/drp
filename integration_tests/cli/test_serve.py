"""
integration_tests/cli/test_serve.py
drp serve — directory, glob, multiple files, plan interactions.
"""
import os
import re
import tempfile
from pathlib import Path
import pytest
from conftest import HOST, unique_key, run_drp
from cli.api.file import get_file


def _file(directory, name, content=b'serve test'):
    p = Path(directory) / name
    p.write_bytes(content)
    return str(p)


class TestServe:
    def test_single_file_prints_url(self, cli_envs, free_user, tmp_path):
        path = _file(tmp_path, 'single.txt')
        r = run_drp('serve', path, env=cli_envs['free'], check=True)
        assert f'{HOST}/f/' in r.stdout

    def test_single_file_downloadable(self, cli_envs, free_user, anon, tmp_path):
        payload = b'serve-and-download'
        path = _file(tmp_path, 'dl.txt', payload)
        r = run_drp('serve', path, env=cli_envs['free'], check=True)
        match = re.search(r'/f/([^/\s]+)/', r.stdout)
        assert match, f'No file URL in output:\n{r.stdout}'
        key = match.group(1)
        free_user.track(key, ns='f')
        kind, (content, _) = get_file(HOST, anon, key)
        assert kind == 'file' and content == payload

    def test_multiple_files(self, cli_envs, free_user, tmp_path):
        paths = [_file(tmp_path, f'multi{i}.txt', f'file {i}'.encode()) for i in range(3)]
        r = run_drp('serve', *paths, env=cli_envs['free'], check=True)
        for p in paths:
            assert os.path.basename(p) in r.stdout

    def test_directory(self, cli_envs, free_user, tmp_path):
        d = tmp_path / 'dist'
        d.mkdir()
        for i in range(3):
            (d / f'file{i}.txt').write_bytes(f'content {i}'.encode())
        r = run_drp('serve', str(d), env=cli_envs['free'], check=True)
        for i in range(3):
            assert f'file{i}.txt' in r.stdout

    def test_glob_pattern(self, cli_envs, free_user, tmp_path):
        for i in range(3):
            (tmp_path / f'report{i}.log').write_bytes(b'log')
        (tmp_path / 'notes.txt').write_bytes(b'not a log')
        r = run_drp('serve', str(tmp_path / '*.log'), env=cli_envs['free'], check=True)
        for i in range(3):
            assert f'report{i}.log' in r.stdout
        assert 'notes.txt' not in r.stdout

    def test_with_expires_starter(self, cli_envs, starter_user, tmp_path):
        path = _file(tmp_path, 'expiry.txt')
        r = run_drp('serve', path, '--expires', '7d', env=cli_envs['starter'], check=True)
        assert r.returncode == 0

    def test_anon_cannot_serve(self, anon_cli_env, tmp_path):
        path = _file(tmp_path, 'anon.txt')
        r = run_drp('serve', path, env=anon_cli_env)
        assert r.returncode != 0

    def test_nonexistent_path_exits_nonzero(self, cli_envs):
        r = run_drp('serve', '/tmp/drp-no-such-dir-xyz/', env=cli_envs['free'])
        assert r.returncode != 0

    def test_each_plan_can_serve(self, cli_envs, free_user, starter_user, pro_user, tmp_path):
        for name, user in (('free', free_user), ('starter', starter_user), ('pro', pro_user)):
            path = _file(tmp_path, f'{name}.txt', f'{name} content'.encode())
            r = run_drp('serve', path, env=cli_envs[name], check=True)
            match = re.search(r'/f/([^/\s]+)/', r.stdout)
            if match:
                user.track(match.group(1), ns='f')
            assert r.returncode == 0
