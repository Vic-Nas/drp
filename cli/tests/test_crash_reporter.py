"""
cli/tests/test_crash_reporter.py

Tests for cli/crash_reporter.py — scrubbing, traceback sanitisation,
and the three public report functions.

No network, no Django. _send() is always mocked.
"""

import sys
from unittest.mock import patch, MagicMock

import pytest

from cli.crash_reporter import (
    _scrub,
    _safe_traceback,
    report,
    report_http_error,
    report_outcome,
    _send,
)


# ── _scrub ────────────────────────────────────────────────────────────────────

class TestScrub:
    def test_scrubs_email(self):
        assert 'user@example.com' not in _scrub('error for user@example.com')
        assert '[email]' in _scrub('error for user@example.com')

    def test_scrubs_url(self):
        assert '[url]' in _scrub('fetching https://example.com/api?token=secret')

    def test_scrubs_linux_home(self):
        result = _scrub('File "/home/victorio/cli/drp.py", line 1')
        assert 'victorio' not in result
        assert '[user]' in result

    def test_scrubs_mac_home(self):
        result = _scrub('File "/Users/victorio/cli/drp.py", line 1')
        assert 'victorio' not in result

    def test_scrubs_password_in_error(self):
        assert '[redacted]' in _scrub('password=hunter2')

    def test_scrubs_token(self):
        assert '[redacted]' in _scrub('token=abc123xyz')

    def test_scrubs_api_key(self):
        assert '[redacted]' in _scrub('api_key=supersecret')

    def test_leaves_safe_text_alone(self):
        text = 'ConnectionError: timed out after 10s'
        assert _scrub(text) == text

    def test_multiple_patterns_in_one_string(self):
        text = 'user@example.com hit https://api.example.com/token=abc'
        result = _scrub(text)
        assert 'user@example.com' not in result
        assert '[email]' in result
        assert '[url]' in result


# ── _safe_traceback ───────────────────────────────────────────────────────────

class TestSafeTraceback:
    def _exc_with_tb(self, msg='test error'):
        try:
            raise RuntimeError(msg)
        except RuntimeError as e:
            return e

    def test_returns_list(self):
        exc = self._exc_with_tb()
        result = _safe_traceback(exc)
        assert isinstance(result, list)

    def test_file_lines_are_kept(self):
        exc = self._exc_with_tb()
        result = _safe_traceback(exc)
        # At least one "File" line from this test file
        assert any('File' in line for line in result)

    def test_no_home_path_in_output(self):
        exc = self._exc_with_tb()
        result = _safe_traceback(exc)
        full = ''.join(result)
        # Home paths in file lines should be scrubbed
        import os
        home = str(__import__('pathlib').Path.home())
        # We can't guarantee the test runner runs from home, but
        # we can confirm the scrub function is applied
        for line in result:
            assert 'Users/' not in line or '[user]' in line

    def test_no_variable_values_leaked(self):
        secret = 'hunter2'
        try:
            password = secret  # noqa
            raise RuntimeError('auth failed')
        except RuntimeError as e:
            result = _safe_traceback(e)
        full = ''.join(result)
        assert secret not in full

    def test_handles_exc_with_no_traceback(self):
        exc = RuntimeError('no tb')
        exc.__traceback__ = None
        result = _safe_traceback(exc)
        assert result == []


# ── report() ─────────────────────────────────────────────────────────────────

class TestReport:
    def test_sends_correct_exc_type(self):
        with patch('cli.crash_reporter._send') as mock_send:
            try:
                raise ValueError('something went wrong')
            except ValueError as e:
                report('up', e)
        payload = mock_send.call_args[0][0]
        assert payload['exc_type'] == 'ValueError'

    def test_sends_command(self):
        with patch('cli.crash_reporter._send') as mock_send:
            try:
                raise RuntimeError('oops')
            except RuntimeError as e:
                report('rm', e)
        assert mock_send.call_args[0][0]['command'] == 'rm'

    def test_sends_scrubbed_message(self):
        with patch('cli.crash_reporter._send') as mock_send:
            try:
                raise RuntimeError('failed for user@example.com')
            except RuntimeError as e:
                report('up', e)
        msg = mock_send.call_args[0][0]['exc_message']
        assert 'user@example.com' not in msg
        assert '[email]' in msg

    def test_sends_platform_info(self):
        with patch('cli.crash_reporter._send') as mock_send:
            try:
                raise RuntimeError('x')
            except RuntimeError as e:
                report('up', e)
        payload = mock_send.call_args[0][0]
        assert 'cli_version' in payload
        assert 'python_version' in payload
        assert 'platform' in payload

    def test_includes_traceback(self):
        with patch('cli.crash_reporter._send') as mock_send:
            try:
                raise RuntimeError('x')
            except RuntimeError as e:
                report('up', e)
        tb = mock_send.call_args[0][0]['traceback']
        assert isinstance(tb, list)


# ── report_http_error() ───────────────────────────────────────────────────────

class TestReportHttpError:
    def test_exc_type_is_http_status(self):
        with patch('cli.crash_reporter._send') as mock_send:
            report_http_error('rm', 403)
        assert mock_send.call_args[0][0]['exc_type'] == 'HTTP403'

    def test_exc_type_for_500(self):
        with patch('cli.crash_reporter._send') as mock_send:
            report_http_error('up', 500)
        assert mock_send.call_args[0][0]['exc_type'] == 'HTTP500'

    def test_context_included_in_message(self):
        with patch('cli.crash_reporter._send') as mock_send:
            report_http_error('rm', 404, context='delete clipboard')
        msg = mock_send.call_args[0][0]['exc_message']
        assert 'delete clipboard' in msg

    def test_context_is_scrubbed(self):
        with patch('cli.crash_reporter._send') as mock_send:
            report_http_error('up', 500, context='user@example.com upload')
        msg = mock_send.call_args[0][0]['exc_message']
        assert 'user@example.com' not in msg

    def test_traceback_is_empty(self):
        with patch('cli.crash_reporter._send') as mock_send:
            report_http_error('rm', 403)
        assert mock_send.call_args[0][0]['traceback'] == []

    def test_command_is_sent(self):
        with patch('cli.crash_reporter._send') as mock_send:
            report_http_error('mv', 409)
        assert mock_send.call_args[0][0]['command'] == 'mv'


# ── report_outcome() ──────────────────────────────────────────────────────────

class TestReportOutcome:
    def test_exc_type_is_silent_failure(self):
        with patch('cli.crash_reporter._send') as mock_send:
            report_outcome('rm', 'delete returned False')
        assert mock_send.call_args[0][0]['exc_type'] == 'SilentFailure'

    def test_description_is_sent_as_message(self):
        with patch('cli.crash_reporter._send') as mock_send:
            report_outcome('rm', 'delete returned False for clipboard drop')
        msg = mock_send.call_args[0][0]['exc_message']
        assert 'delete returned False' in msg

    def test_description_is_scrubbed(self):
        with patch('cli.crash_reporter._send') as mock_send:
            report_outcome('up', 'upload failed for /home/victorio/file.txt')
        msg = mock_send.call_args[0][0]['exc_message']
        assert 'victorio' not in msg

    def test_traceback_is_empty(self):
        with patch('cli.crash_reporter._send') as mock_send:
            report_outcome('up', 'x')
        assert mock_send.call_args[0][0]['traceback'] == []


# ── _send() ───────────────────────────────────────────────────────────────────

class TestSend:
    def test_does_nothing_when_no_host_configured(self):
        with patch('cli.config.load', return_value={}):
            with patch('requests.post') as mock_post:
                _send({'exc_type': 'Test'})
        mock_post.assert_not_called()

    def test_posts_to_correct_endpoint(self):
        with patch('cli.config.load', return_value={'host': 'https://example.com'}):
            with patch('requests.post') as mock_post:
                _send({'exc_type': 'Test'})
        url = mock_post.call_args[0][0]
        assert url == 'https://example.com/api/report-error/'

    def test_never_raises_on_network_error(self):
        with patch('cli.config.load', return_value={'host': 'https://example.com'}):
            with patch('requests.post', side_effect=Exception('network error')):
                _send({'exc_type': 'Test'})  # must not raise

    def test_never_raises_on_config_error(self):
        with patch('cli.config.load', side_effect=Exception('config broken')):
            _send({'exc_type': 'Test'})  # must not raise
