"""
cli/tests/test_completion.py

Migrated from tests_completion.py — no changes to existing tests,
just moved into the package structure.
"""

import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_drops(entries):
    """entries: list of (key, ns) tuples"""
    return [
        {'key': k, 'ns': ns, 'kind': 'file' if ns == 'f' else 'text',
         'created_at': '2026-01-01T00:00:00+00:00', 'host': 'https://example.com'}
        for k, ns in entries
    ]


# ── _read_cache ───────────────────────────────────────────────────────────────

class TestReadCache:
    def _patch_drops(self, drops):
        return patch('cli.config.load_local_drops', return_value=drops)

    def test_returns_matching_clipboard_keys(self):
        from cli.completion import _read_cache
        drops = _make_drops([('hello', 'c'), ('world', 'c'), ('report', 'f')])
        with self._patch_drops(drops):
            result = _read_cache('c', '')
        assert 'hello' in result
        assert 'world' in result
        assert 'report' not in result

    def test_returns_matching_file_keys(self):
        from cli.completion import _read_cache
        drops = _make_drops([('hello', 'c'), ('report', 'f'), ('q3', 'f')])
        with self._patch_drops(drops):
            result = _read_cache('f', '')
        assert 'report' in result
        assert 'q3' in result
        assert 'hello' not in result

    def test_ns_none_returns_all(self):
        from cli.completion import _read_cache
        drops = _make_drops([('hello', 'c'), ('report', 'f')])
        with self._patch_drops(drops):
            result = _read_cache(None, '')
        assert 'hello' in result
        assert 'report' in result

    def test_prefix_filters_correctly(self):
        from cli.completion import _read_cache
        drops = _make_drops([('hello', 'c'), ('help', 'c'), ('world', 'c')])
        with self._patch_drops(drops):
            result = _read_cache('c', 'hel')
        assert 'hello' in result
        assert 'help' in result
        assert 'world' not in result

    def test_empty_cache_returns_empty_list(self):
        from cli.completion import _read_cache
        with self._patch_drops([]):
            result = _read_cache('c', '')
        assert result == []

    def test_exception_returns_empty_list(self):
        from cli.completion import _read_cache
        with patch('cli.config.load_local_drops', side_effect=Exception('boom')):
            result = _read_cache('c', '')
        assert result == []


# ── key_completer ─────────────────────────────────────────────────────────────

class TestKeyCompleter:
    def _patch_drops(self, drops):
        return patch('cli.config.load_local_drops', return_value=drops)

    def _mock_parsed_args(self, file=False):
        args = MagicMock()
        args.file = file
        return args

    def test_no_dash_f_completes_clipboard(self):
        from cli.completion import key_completer
        drops = _make_drops([('hello', 'c'), ('report', 'f')])
        with self._patch_drops(drops):
            with patch('cli.completion._trigger_background_refresh'):
                result = key_completer('', self._mock_parsed_args(file=False))
        assert 'hello' in result
        assert 'report' not in result

    def test_dash_f_completes_files(self):
        from cli.completion import key_completer
        drops = _make_drops([('hello', 'c'), ('report', 'f')])
        with self._patch_drops(drops):
            with patch('cli.completion._trigger_background_refresh'):
                result = key_completer('', self._mock_parsed_args(file=True))
        assert 'report' in result
        assert 'hello' not in result

    def test_triggers_background_refresh(self):
        from cli.completion import key_completer
        with patch('cli.config.load_local_drops', return_value=[]):
            with patch('cli.completion._trigger_background_refresh') as mock_refresh:
                key_completer('', self._mock_parsed_args())
        mock_refresh.assert_called_once()


# ── _do_refresh merge logic ───────────────────────────────────────────────────

class TestDoRefreshMerge:
    def _run_refresh(self, server_response, existing_drops):
        import cli.completion as comp

        saved_list = []

        mock_res = MagicMock()
        mock_res.ok = True
        mock_res.json.return_value = server_response

        mock_session = MagicMock()
        mock_session.get.return_value = mock_res

        mock_config = MagicMock()
        mock_config.load.return_value = {'host': 'https://example.com'}
        mock_config.load_local_drops.return_value = existing_drops
        mock_config.save_local_drops.side_effect = lambda drops: saved_list.extend(drops)

        with patch('requests.Session', return_value=mock_session):
            with patch('cli.session.load_session'):
                comp._do_refresh(mock_config, MagicMock())

        return saved_list

    def test_server_drops_added_to_cache(self):
        result = self._run_refresh(
            server_response={
                'drops': [{'key': 'q3', 'ns': 'f', 'kind': 'file',
                            'created_at': '2026-01-01T00:00:00+00:00',
                            'filename': 'q3.pdf'}],
                'saved': [],
            },
            existing_drops=[],
        )
        assert 'q3' in [d['key'] for d in result]

    def test_existing_local_drops_preserved(self):
        existing = _make_drops([('local-only', 'c')])
        result = self._run_refresh(
            server_response={'drops': [], 'saved': []},
            existing_drops=existing,
        )
        assert 'local-only' in [d['key'] for d in result]

    def test_server_entry_updates_existing(self):
        existing = _make_drops([('q3', 'f')])
        result = self._run_refresh(
            server_response={
                'drops': [{'key': 'q3', 'ns': 'f', 'kind': 'file',
                            'created_at': '2026-02-01T00:00:00+00:00',
                            'filename': 'updated.pdf'}],
                'saved': [],
            },
            existing_drops=existing,
        )
        q3_entries = [d for d in result if d['key'] == 'q3']
        assert len(q3_entries) == 1
        assert q3_entries[0].get('filename') == 'updated.pdf'

    def test_saved_drops_added_if_not_present(self):
        result = self._run_refresh(
            server_response={
                'drops': [],
                'saved': [{'key': 'shared', 'ns': 'c',
                            'saved_at': '2026-01-01T00:00:00+00:00'}],
            },
            existing_drops=[],
        )
        assert 'shared' in [d['key'] for d in result]

    def test_saved_drops_not_duplicated_if_already_owned(self):
        existing = _make_drops([('shared', 'c')])
        result = self._run_refresh(
            server_response={
                'drops': [],
                'saved': [{'key': 'shared', 'ns': 'c',
                            'saved_at': '2026-01-01T00:00:00+00:00'}],
            },
            existing_drops=existing,
        )
        assert len([d for d in result if d['key'] == 'shared']) == 1

    def test_no_crash_on_failed_request(self):
        import cli.completion as comp
        mock_config = MagicMock()
        mock_config.load.return_value = {'host': 'https://example.com'}
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception('network error')
        with patch('requests.Session', return_value=mock_session):
            with patch('cli.session.load_session'):
                comp._do_refresh(mock_config, MagicMock())  # must not raise

    def test_no_crash_on_bad_json(self):
        import cli.completion as comp
        mock_res = MagicMock()
        mock_res.ok = True
        mock_res.json.side_effect = ValueError('bad json')
        mock_session = MagicMock()
        mock_session.get.return_value = mock_res
        mock_config = MagicMock()
        mock_config.load.return_value = {'host': 'https://example.com'}
        with patch('requests.Session', return_value=mock_session):
            with patch('cli.session.load_session'):
                comp._do_refresh(mock_config, MagicMock())  # must not raise


# ── _trigger_background_refresh skips ────────────────────────────────────────

class TestTriggerSkips:
    def test_skips_when_no_session_file(self):
        from cli.completion import _trigger_background_refresh
        mock_session_file = MagicMock()
        mock_session_file.exists.return_value = False
        with patch('cli.session.SESSION_FILE', mock_session_file):
            with patch('threading.Thread') as mock_thread:
                _trigger_background_refresh()
        mock_thread.assert_not_called()

    def test_skips_when_cache_is_fresh(self):
        from cli.completion import _trigger_background_refresh, REFRESH_INTERVAL_SECS
        mock_session_file = MagicMock()
        mock_session_file.exists.return_value = True
        mock_drops_file = MagicMock()
        mock_drops_file.exists.return_value = True
        mock_drops_file.stat.return_value.st_mtime = time.time()
        with patch('cli.session.SESSION_FILE', mock_session_file):
            with patch('cli.config.DROPS_FILE', mock_drops_file):
                with patch('threading.Thread') as mock_thread:
                    _trigger_background_refresh()
        mock_thread.assert_not_called()

    def test_spawns_thread_when_cache_is_stale(self):
        from cli.completion import _trigger_background_refresh, REFRESH_INTERVAL_SECS
        mock_session_file = MagicMock()
        mock_session_file.exists.return_value = True
        mock_drops_file = MagicMock()
        mock_drops_file.exists.return_value = True
        mock_drops_file.stat.return_value.st_mtime = (
            time.time() - REFRESH_INTERVAL_SECS - 10
        )
        mock_thread_instance = MagicMock()
        with patch('cli.session.SESSION_FILE', mock_session_file):
            with patch('cli.config.DROPS_FILE', mock_drops_file):
                with patch('threading.Thread',
                           return_value=mock_thread_instance) as mock_thread:
                    _trigger_background_refresh()
        mock_thread.assert_called_once()
        mock_thread_instance.start.assert_called_once()
