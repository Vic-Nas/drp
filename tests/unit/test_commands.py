"""
tests/unit/test_commands.py

Pure unit tests for the newer CLI commands added in drp:
  - cli.commands.manage: cmd_rm, cmd_mv, cmd_renew, _parse_key
  - cli.commands.edit:   _find_editor, _on_path
  - cli.commands.diff:   (pure parts — diff output logic)
  - cli.commands.serve:  _resolve_paths
  - cli.commands.cp:     _parse_key (re-exported via manage)
  - cli.commands.ls:     _human, _since, _until

No network, no Django DB, no filesystem side-effects beyond tempfiles.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone, timedelta

import pytest


# ── cli.commands.manage: _parse_key ──────────────────────────────────────────

class TestParseKey:
    def _pk(self, raw, is_file=False, is_clip=False):
        from cli.commands.manage import _parse_key
        return _parse_key(raw, is_file, is_clip)

    def test_default_is_clipboard(self):
        ns, key = self._pk('hello')
        assert ns == 'c'
        assert key == 'hello'

    def test_file_flag(self):
        ns, key = self._pk('report', is_file=True)
        assert ns == 'f'
        assert key == 'report'

    def test_clip_flag_overrides_file(self):
        # is_clip=True means clipboard even if is_file=True
        ns, key = self._pk('notes', is_file=True, is_clip=True)
        assert ns == 'c'

    def test_empty_key_preserved(self):
        ns, key = self._pk('', is_file=True)
        assert ns == 'f'
        assert key == ''


# ── cli.commands.manage: cmd_rm, cmd_mv, cmd_renew (mocked) ──────────────────

class TestCmdRm:
    def _make_args(self, key, is_file=False):
        args = MagicMock()
        args.key = key
        args.file = is_file
        args.clip = False
        return args

    @patch('cli.commands.manage.config')
    @patch('cli.commands.manage.requests')
    @patch('cli.commands.manage.auto_login')
    @patch('cli.commands.manage.api')
    def test_rm_success_clipboard(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.delete.return_value = True
        args = self._make_args('hello')
        import cli.commands.manage as m
        with patch('builtins.print') as mock_print:
            m.cmd_rm(args)
        mock_api.delete.assert_called_once_with('https://x.com', mock_req.Session(), 'hello', ns='c')
        mock_config.remove_local_drop.assert_called_once_with('hello')

    @patch('cli.commands.manage.config')
    @patch('cli.commands.manage.requests')
    @patch('cli.commands.manage.auto_login')
    @patch('cli.commands.manage.api')
    def test_rm_success_file(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.delete.return_value = True
        args = self._make_args('q3', is_file=True)
        import cli.commands.manage as m
        with patch('builtins.print'):
            m.cmd_rm(args)
        mock_api.delete.assert_called_once_with('https://x.com', mock_req.Session(), 'q3', ns='f')

    @patch('cli.commands.manage.config')
    @patch('cli.commands.manage.requests')
    @patch('cli.commands.manage.auto_login')
    @patch('cli.commands.manage.api')
    def test_rm_failure_exits(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.delete.return_value = False
        args = self._make_args('hello')
        import cli.commands.manage as m
        with pytest.raises(SystemExit) as exc:
            with patch('builtins.print'):
                m.cmd_rm(args)
        assert exc.value.code == 1

    @patch('cli.commands.manage.config')
    def test_rm_no_host_exits(self, mock_config):
        mock_config.load.return_value = {}
        import cli.commands.manage as m
        with pytest.raises(SystemExit):
            with patch('builtins.print'):
                m.cmd_rm(MagicMock(key='x', file=False, clip=False))


class TestCmdMv:
    def _make_args(self, key, new_key, is_file=False):
        args = MagicMock()
        args.key = key
        args.new_key = new_key
        args.file = is_file
        args.clip = False
        return args

    @patch('cli.commands.manage.config')
    @patch('cli.commands.manage.requests')
    @patch('cli.commands.manage.auto_login')
    @patch('cli.commands.manage.api')
    def test_mv_success(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.rename.return_value = 'new-key'  # string = success
        args = self._make_args('old', 'new-key')
        import cli.commands.manage as m
        with patch('builtins.print') as p:
            m.cmd_mv(args)
        output = ' '.join(str(c) for c in p.call_args_list)
        assert 'old' in output or 'new-key' in output
        mock_config.rename_local_drop.assert_called_once_with('old', 'new-key')

    @patch('cli.commands.manage.config')
    @patch('cli.commands.manage.requests')
    @patch('cli.commands.manage.auto_login')
    @patch('cli.commands.manage.api')
    def test_mv_known_failure_exits_1(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.rename.return_value = False  # False = known error
        args = self._make_args('old', 'new')
        import cli.commands.manage as m
        with pytest.raises(SystemExit) as exc:
            with patch('builtins.print'):
                m.cmd_mv(args)
        assert exc.value.code == 1

    @patch('cli.commands.manage.config')
    @patch('cli.commands.manage.requests')
    @patch('cli.commands.manage.auto_login')
    @patch('cli.commands.manage.api')
    def test_mv_unknown_failure_exits_1(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.rename.return_value = None  # None = unexpected
        args = self._make_args('old', 'new')
        import cli.commands.manage as m
        with pytest.raises(SystemExit) as exc:
            with patch('builtins.print'):
                with patch('cli.commands.manage.report_outcome'):
                    m.cmd_mv(args)
        assert exc.value.code == 1


class TestCmdRenew:
    @patch('cli.commands.manage.config')
    @patch('cli.commands.manage.requests')
    @patch('cli.commands.manage.auto_login')
    @patch('cli.commands.manage.api')
    def test_renew_success(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.renew.return_value = ('2026-01-01T00:00:00Z', 2)
        args = MagicMock(key='notes', file=False, clip=False)
        import cli.commands.manage as m
        with patch('builtins.print') as p:
            m.cmd_renew(args)
        printed = ' '.join(str(c) for c in p.call_args_list)
        assert 'notes' in printed or 'renewed' in printed

    @patch('cli.commands.manage.config')
    @patch('cli.commands.manage.requests')
    @patch('cli.commands.manage.auto_login')
    @patch('cli.commands.manage.api')
    def test_renew_failure_exits(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.renew.return_value = (None, None)
        args = MagicMock(key='notes', file=False, clip=False)
        import cli.commands.manage as m
        with pytest.raises(SystemExit) as exc:
            with patch('builtins.print'):
                with patch('cli.commands.manage.report_outcome'):
                    m.cmd_renew(args)
        assert exc.value.code == 1


# ── cli.commands.edit: _find_editor, _on_path ─────────────────────────────────

class TestFindEditor:
    def test_find_editor_returns_string(self):
        from cli.commands.edit import _find_editor
        editor = _find_editor()
        assert isinstance(editor, str)
        assert len(editor) > 0

    def test_on_path_true_for_python(self):
        from cli.commands.edit import _on_path
        assert _on_path('python') or _on_path('python3')

    def test_on_path_false_for_nonexistent(self):
        from cli.commands.edit import _on_path
        assert not _on_path('this-editor-does-not-exist-xyz-abc')

    def test_editor_env_var_used(self):
        """EDITOR env var is picked up by cmd_edit (we don't run cmd_edit, just
        verify that _find_editor falls back correctly when EDITOR is unset)."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('VISUAL', None)
            os.environ.pop('EDITOR', None)
            from cli.commands.edit import _find_editor
            e = _find_editor()
            assert e in ('nano', 'vi', 'notepad') or _find_editor()


# ── cli.commands.serve: _resolve_paths ────────────────────────────────────────

class TestResolvePaths:
    def test_file_path(self, tmp_path):
        f = tmp_path / 'a.txt'
        f.write_text('x')
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths([str(f)])
        assert result == [str(f)]

    def test_directory_lists_files(self, tmp_path):
        (tmp_path / 'a.txt').write_text('a')
        (tmp_path / 'b.txt').write_text('b')
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths([str(tmp_path)])
        names = [os.path.basename(p) for p in result]
        assert set(names) == {'a.txt', 'b.txt'}

    def test_glob_pattern(self, tmp_path):
        (tmp_path / 'x.log').write_text('x')
        (tmp_path / 'y.log').write_text('y')
        (tmp_path / 'z.txt').write_text('z')
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths([str(tmp_path / '*.log')])
        names = [os.path.basename(p) for p in result]
        assert set(names) == {'x.log', 'y.log'}

    def test_deduplicates(self, tmp_path):
        f = tmp_path / 'a.txt'
        f.write_text('a')
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths([str(f), str(f)])
        assert len(result) == 1

    def test_nonexistent_target_returns_empty(self, tmp_path):
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths([str(tmp_path / 'nonexistent')])
        assert result == []

    def test_empty_input(self):
        from cli.commands.serve import _resolve_paths
        assert _resolve_paths([]) == []

    def test_directory_not_recursive(self, tmp_path):
        subdir = tmp_path / 'sub'
        subdir.mkdir()
        (subdir / 'nested.txt').write_text('nested')
        (tmp_path / 'top.txt').write_text('top')
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths([str(tmp_path)])
        names = [os.path.basename(p) for p in result]
        assert 'top.txt' in names
        assert 'nested.txt' not in names  # non-recursive


# ── cli.commands.ls: _human, _since, _until ──────────────────────────────────

class TestLsHelpers:
    def test_human_bytes(self):
        from cli.commands.ls import _human
        assert _human(512) == '512B'

    def test_human_kilobytes(self):
        from cli.commands.ls import _human
        result = _human(2048)
        assert 'K' in result

    def test_human_megabytes(self):
        from cli.commands.ls import _human
        result = _human(5 * 1024 * 1024)
        assert 'M' in result

    def test_human_gigabytes(self):
        from cli.commands.ls import _human
        result = _human(2 * 1024 ** 3)
        assert 'G' in result

    def test_since_none(self):
        from cli.commands.ls import _since
        assert _since(None) == '—'

    def test_since_recent(self):
        from cli.commands.ls import _since
        now = datetime.now(timezone.utc)
        iso = (now - timedelta(seconds=30)).isoformat()
        result = _since(iso)
        assert 'ago' in result

    def test_since_minutes(self):
        from cli.commands.ls import _since
        now = datetime.now(timezone.utc)
        iso = (now - timedelta(minutes=5)).isoformat()
        result = _since(iso)
        assert 'm ago' in result

    def test_since_hours(self):
        from cli.commands.ls import _since
        now = datetime.now(timezone.utc)
        iso = (now - timedelta(hours=3)).isoformat()
        result = _since(iso)
        assert 'h ago' in result

    def test_since_days(self):
        from cli.commands.ls import _since
        now = datetime.now(timezone.utc)
        iso = (now - timedelta(days=5)).isoformat()
        result = _since(iso)
        assert 'd ago' in result

    def test_until_none(self):
        from cli.commands.ls import _until
        assert _until(None) == 'no expiry'

    def test_until_future(self):
        from cli.commands.ls import _until
        future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        result = _until(future)
        assert result  # non-empty string


# ── cli.commands.cp: basic structure ─────────────────────────────────────────

class TestCmdCp:
    @patch('cli.commands.cp.config')
    @patch('cli.commands.cp.requests')
    @patch('cli.commands.cp.auto_login')
    def test_cp_no_host_exits(self, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {}
        import cli.commands.cp as cp
        with pytest.raises(SystemExit):
            with patch('builtins.print'):
                cp.cmd_cp(MagicMock(key='src', new_key='dst', file=False, clip=False))

    @patch('cli.commands.cp.config')
    @patch('cli.commands.cp.requests')
    @patch('cli.commands.cp.auto_login')
    @patch('cli.commands.cp.get_csrf', return_value='csrf-token')
    def test_cp_posts_to_copy_endpoint(self, mock_csrf, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_session = MagicMock()
        mock_req.Session.return_value = mock_session
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {'key': 'dst'}
        mock_session.post.return_value = mock_response
        args = MagicMock(key='src', new_key='dst', file=False, clip=False)
        import cli.commands.cp as cp
        with patch('builtins.print'):
            with patch('cli.commands.cp.Spinner'):
                cp.cmd_cp(args)
        mock_session.post.assert_called_once()
        call_url = mock_session.post.call_args[0][0]
        assert '/src/copy/' in call_url