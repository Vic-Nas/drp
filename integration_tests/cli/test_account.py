"""
integration_tests/cli/test_account.py
drp save / drp load — bookmark and import, across plan tiers.
(login/logout tested minimally — users are pre-created by fixtures.)
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


class TestSave:
    def test_owner_can_save(self, cli_envs, free_user):
        key = free_user.track(_up(free_user, 'save'))
        r = run_drp('save', key, env=cli_envs['free'], check=True)
        assert r.returncode == 0

    def test_saved_drop_appears_in_ls(self, cli_envs, free_user):
        key = free_user.track(_up(free_user, 'savels'))
        run_drp('save', key, env=cli_envs['free'], check=True)
        r = run_drp('ls', '-t', 's', env=cli_envs['free'], check=True)
        assert key in r.stdout

    def test_saved_drop_not_visible_to_other_user(self, cli_envs, free_user, starter_user):
        key = free_user.track(_up(free_user, 'saveprivate'))
        run_drp('save', key, env=cli_envs['free'], check=True)
        r = run_drp('ls', '-t', 's', env=cli_envs['starter'], check=True)
        assert key not in r.stdout

    def test_anon_cannot_save(self, anon_cli_env, free_user):
        key = free_user.track(_up(free_user, 'saveanon'))
        r = run_drp('save', key, env=anon_cli_env)
        assert r.returncode != 0

    def test_each_plan_can_save(self, cli_envs, free_user, starter_user, pro_user):
        for name, user in (('free', free_user), ('starter', starter_user), ('pro', pro_user)):
            key = user.track(_up(user, 'saveplan'))
            r = run_drp('save', key, env=cli_envs[name], check=True)
            assert r.returncode == 0


class TestLoad:
    def _export(self, user, n=2):
        keys = [user.track(_up(user, f'loadkey{i}')) for i in range(n)]
        drops = [{'key': k, 'ns': 'c', 'kind': 'text',
                  'created_at': '2026-01-01T00:00:00+00:00'} for k in keys]
        return {'drops': drops, 'saved': []}

    def test_load_valid_export(self, cli_envs, free_user, tmp_path):
        export = self._export(free_user)
        f = tmp_path / 'export.json'
        f.write_text(json.dumps(export))
        r = run_drp('load', str(f), env=cli_envs['free'], check=True)
        assert r.returncode == 0

    def test_load_roundtrip_from_ls_export(self, cli_envs, free_user, tmp_path):
        free_user.track(_up(free_user, 'loadrt'))
        r = run_drp('ls', '--export', env=cli_envs['free'], check=True)
        f = tmp_path / 'rt.json'
        f.write_text(r.stdout)
        r2 = run_drp('load', str(f), env=cli_envs['free'])
        assert r2.returncode == 0

    def test_load_missing_file_exits_nonzero(self, cli_envs):
        r = run_drp('load', '/tmp/drp-no-such-export-xyz.json', env=cli_envs['free'])
        assert r.returncode != 0

    def test_load_invalid_json_exits_nonzero(self, cli_envs, tmp_path):
        bad = tmp_path / 'bad.json'
        bad.write_text('not json {{{{')
        r = run_drp('load', str(bad), env=cli_envs['free'])
        assert r.returncode != 0
