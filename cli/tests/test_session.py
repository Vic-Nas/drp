"""
cli/tests/test_session.py

Tests for cli/session.py — cookie persistence and auto_login fast/slow paths.

No network calls. All requests.Session interactions are mocked.
"""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tmp_session_file():
    """Return a temp Path that doesn't exist yet."""
    return Path(tempfile.mktemp(suffix='.json'))


# ── load_session / save_session / clear_session ───────────────────────────────

class TestSessionPersistence:
    def setup_method(self):
        from cli import session as sess_mod
        self._orig = sess_mod.SESSION_FILE
        self._tmp = _tmp_session_file()
        sess_mod.SESSION_FILE = self._tmp

    def teardown_method(self):
        from cli import session as sess_mod
        if self._tmp.exists():
            self._tmp.unlink()
        sess_mod.SESSION_FILE = self._orig

    def test_load_session_populates_cookies(self):
        from cli.session import load_session, save_session
        session_a = MagicMock()
        session_a.cookies = {'sessionid': 'abc123'}
        save_session(session_a)

        session_b = MagicMock()
        load_session(session_b)
        session_b.cookies.update.assert_called_once_with({'sessionid': 'abc123'})

    def test_load_session_silent_when_file_missing(self):
        from cli.session import load_session
        session = MagicMock()
        load_session(session)   # must not raise
        session.cookies.update.assert_not_called()

    def test_save_creates_file(self):
        from cli.session import save_session
        session = MagicMock()
        session.cookies = {'csrftoken': 'tok'}
        save_session(session)
        assert self._tmp.exists()

    def test_clear_session_removes_file(self):
        from cli.session import save_session, clear_session
        session = MagicMock()
        session.cookies = {'sessionid': 'x'}
        save_session(session)
        assert self._tmp.exists()
        clear_session()
        assert not self._tmp.exists()

    def test_clear_session_safe_when_no_file(self):
        from cli.session import clear_session
        clear_session()  # must not raise

    def test_load_session_silent_on_corrupt_file(self):
        from cli.session import load_session
        self._tmp.write_text('not valid json{{{{')
        session = MagicMock()
        load_session(session)   # must not raise


# ── _session_is_fresh ─────────────────────────────────────────────────────────

class TestSessionIsFresh:
    def setup_method(self):
        from cli import session as sess_mod
        self._orig = sess_mod.SESSION_FILE
        self._tmp = _tmp_session_file()
        sess_mod.SESSION_FILE = self._tmp

    def teardown_method(self):
        from cli import session as sess_mod
        if self._tmp.exists():
            self._tmp.unlink()
        sess_mod.SESSION_FILE = self._orig

    def test_false_when_file_missing(self):
        from cli.session import _session_is_fresh
        assert _session_is_fresh() is False

    def test_true_when_file_is_recent(self):
        from cli.session import _session_is_fresh, SESSION_CACHE_SECS
        self._tmp.write_text('{}')
        # File was just written — should be fresh
        assert _session_is_fresh() is True

    def test_false_when_file_is_old(self):
        from cli.session import _session_is_fresh, SESSION_CACHE_SECS
        self._tmp.write_text('{}')
        # Backdate mtime beyond the cache window
        old_mtime = time.time() - SESSION_CACHE_SECS - 10
        import os
        os.utime(self._tmp, (old_mtime, old_mtime))
        assert _session_is_fresh() is False


# ── auto_login ────────────────────────────────────────────────────────────────

class TestAutoLogin:
    def setup_method(self):
        from cli import session as sess_mod
        self._orig = sess_mod.SESSION_FILE
        self._tmp = _tmp_session_file()
        sess_mod.SESSION_FILE = self._tmp

    def teardown_method(self):
        from cli import session as sess_mod
        if self._tmp.exists():
            self._tmp.unlink()
        sess_mod.SESSION_FILE = self._orig

    def _cfg(self, email='user@example.com', host='https://example.com'):
        return {'email': email, 'host': host}

    def test_returns_false_when_no_email_in_config(self):
        from cli.session import auto_login
        session = MagicMock()
        result = auto_login({}, 'https://example.com', session)
        assert result is False

    def test_fast_path_returns_true_when_session_fresh(self):
        from cli.session import auto_login, SESSION_CACHE_SECS
        # Write a fresh session file
        self._tmp.write_text('{}')
        session = MagicMock()
        with patch('cli.session._session_is_fresh', return_value=True):
            result = auto_login(self._cfg(), 'https://example.com', session)
        assert result is True
        # No network call on the fast path
        session.get.assert_not_called()

    def test_slow_path_returns_true_on_200(self):
        from cli.session import auto_login
        mock_res = MagicMock()
        mock_res.status_code = 200
        session = MagicMock()
        session.get.return_value = mock_res

        with patch('cli.session._session_is_fresh', return_value=False):
            with patch('cli.session.Spinner'):
                result = auto_login(self._cfg(), 'https://example.com', session)

        assert result is True

    def test_slow_path_prompts_on_non_200(self):
        from cli.session import auto_login
        mock_res = MagicMock()
        mock_res.status_code = 302
        session = MagicMock()
        session.get.return_value = mock_res

        with patch('cli.session._session_is_fresh', return_value=False):
            with patch('cli.session.Spinner'):
                with patch('getpass.getpass', return_value='wrongpassword'):
                    with patch('cli.api.login', return_value=False):
                        result = auto_login(self._cfg(), 'https://example.com', session)

        assert result is False

    def test_slow_path_saves_session_on_successful_relogin(self):
        from cli.session import auto_login
        mock_res = MagicMock()
        mock_res.status_code = 302
        session = MagicMock()
        session.get.return_value = mock_res

        with patch('cli.session._session_is_fresh', return_value=False):
            with patch('cli.session.Spinner'):
                with patch('getpass.getpass', return_value='correctpassword'):
                    with patch('cli.api.login', return_value=True):
                        with patch('cli.session.save_session') as mock_save:
                            result = auto_login(self._cfg(), 'https://example.com', session)

        assert result is True
        mock_save.assert_called_once()

    def test_network_error_returns_false(self):
        from cli.session import auto_login
        session = MagicMock()
        session.get.side_effect = Exception('connection refused')

        with patch('cli.session._session_is_fresh', return_value=False):
            with patch('cli.session.Spinner'):
                result = auto_login(self._cfg(), 'https://example.com', session)

        assert result is False
