"""
Unit tests for core/views/error_reporting.py
No real GitHub token or network required — all HTTP calls are mocked.
Django is mocked out so this runs without a Django install.
"""

import sys
import types
from unittest.mock import patch, MagicMock

# ── Stub out Django before anything imports it ────────────────────────────────
# error_reporting.py uses django only for its decorators and JsonResponse.
# We replace those with no-ops so we can test the pure logic functions.

django_stub = types.ModuleType('django')
django_http_stub = types.ModuleType('django.http')
django_http_stub.JsonResponse = dict  # close enough for the functions we test
django_views_stub = types.ModuleType('django.views')
django_decorators_stub = types.ModuleType('django.views.decorators')
django_csrf_stub = types.ModuleType('django.views.decorators.csrf')
django_csrf_stub.csrf_exempt = lambda f: f
django_http_dec_stub = types.ModuleType('django.views.decorators.http')
django_http_dec_stub.require_POST = lambda f: f

sys.modules.setdefault('django', django_stub)
sys.modules.setdefault('django.http', django_http_stub)
sys.modules.setdefault('django.views', django_views_stub)
sys.modules.setdefault('django.views.decorators', django_decorators_stub)
sys.modules.setdefault('django.views.decorators.csrf', django_csrf_stub)
sys.modules.setdefault('django.views.decorators.http', django_http_dec_stub)

# Now safe to import
from core.views.error_reporting import (  # noqa: E402
    _scrub,
    _scrub_traceback,
    _issue_title,
    _issue_exists,
    _create_issue,
    _build_body,
)

import pytest  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_issue(title):
    return {'title': title, 'state': 'open'}


def _mock_gh_response(issues):
    mock = MagicMock()
    mock.ok = True
    mock.json.return_value = issues
    return mock


# ── _scrub ────────────────────────────────────────────────────────────────────

class TestScrub:
    def test_scrubs_email(self):
        assert '[email]' in _scrub('user@example.com')

    def test_scrubs_url(self):
        assert '[url]' in _scrub('https://example.com/path')

    def test_scrubs_home_path_linux(self):
        assert '[user]' in _scrub('/home/victorio/code')

    def test_scrubs_home_path_mac(self):
        assert '[user]' in _scrub('/Users/victorio/code')

    def test_scrubs_password(self):
        assert '[redacted]' in _scrub('password=secret123')

    def test_scrubs_token(self):
        assert '[redacted]' in _scrub('token=abc123')

    def test_leaves_safe_text_alone(self):
        text = 'ConnectionError in drp up'
        assert _scrub(text) == text


# ── _scrub_traceback ──────────────────────────────────────────────────────────

class TestScrubTraceback:
    def test_keeps_file_lines(self):
        lines = ['  File "cli/drp.py", line 42, in main\n']
        result = _scrub_traceback(lines)
        assert 'File' in result[0]

    def test_redacts_assignment_lines(self):
        lines = ['    password = "secret"\n']
        result = _scrub_traceback(lines)
        assert '[locals redacted]' in result[0]

    def test_redacts_during_handling(self):
        lines = ['During handling of the above exception\n']
        result = _scrub_traceback(lines)
        assert '[locals redacted]' in result[0]

    def test_scrubs_email_in_file_line(self):
        lines = ['  File "/home/user@example.com/cli.py", line 1, in main\n']
        result = _scrub_traceback(lines)
        assert 'user@example.com' not in result[0]


# ── _issue_title ──────────────────────────────────────────────────────────────

class TestIssueTitle:
    def test_format(self):
        assert _issue_title('ConnectionError', 'up') == '[auto] ConnectionError in `drp up`'


# ── _issue_exists ─────────────────────────────────────────────────────────────

class TestIssueExists:
    @patch('core.views.error_reporting.GITHUB_TOKEN', '')
    def test_returns_false_when_no_token(self):
        assert _issue_exists('ConnectionError', 'up') is False

    @patch('core.views.error_reporting.GITHUB_TOKEN', 'fake-token')
    @patch('core.views.error_reporting.http.get')
    def test_returns_true_on_exact_duplicate(self, mock_get):
        mock_get.return_value = _mock_gh_response([
            _make_issue('[auto] ConnectionError in `drp up`'),
        ])
        assert _issue_exists('ConnectionError', 'up') is True

    @patch('core.views.error_reporting.GITHUB_TOKEN', 'fake-token')
    @patch('core.views.error_reporting.http.get')
    def test_returns_false_when_no_matching_issue(self, mock_get):
        mock_get.return_value = _mock_gh_response([
            _make_issue('[auto] TimeoutError in `drp ls`'),
        ])
        assert _issue_exists('ConnectionError', 'up') is False

    @patch('core.views.error_reporting.GITHUB_TOKEN', 'fake-token')
    @patch('core.views.error_reporting.http.get')
    def test_flood_guard_triggers_at_three(self, mock_get):
        mock_get.return_value = _mock_gh_response([
            _make_issue('[auto] ConnectionError in `drp up`'),
            _make_issue('[auto] TimeoutError in `drp up`'),
            _make_issue('[auto] ValueError in `drp up`'),
        ])
        assert _issue_exists('KeyError', 'up') is True

    @patch('core.views.error_reporting.GITHUB_TOKEN', 'fake-token')
    @patch('core.views.error_reporting.http.get')
    def test_flood_guard_does_not_trigger_at_two(self, mock_get):
        mock_get.return_value = _mock_gh_response([
            _make_issue('[auto] ConnectionError in `drp up`'),
            _make_issue('[auto] TimeoutError in `drp up`'),
        ])
        assert _issue_exists('KeyError', 'up') is False

    @patch('core.views.error_reporting.GITHUB_TOKEN', 'fake-token')
    @patch('core.views.error_reporting.http.get')
    def test_flood_guard_is_per_command(self, mock_get):
        mock_get.return_value = _mock_gh_response([
            _make_issue('[auto] ConnectionError in `drp up`'),
            _make_issue('[auto] TimeoutError in `drp up`'),
            _make_issue('[auto] ValueError in `drp up`'),
        ])
        assert _issue_exists('KeyError', 'get') is False

    @patch('core.views.error_reporting.GITHUB_TOKEN', 'fake-token')
    @patch('core.views.error_reporting.http.get')
    def test_returns_false_on_network_error(self, mock_get):
        mock_get.side_effect = Exception('network error')
        assert _issue_exists('ConnectionError', 'up') is False

    @patch('core.views.error_reporting.GITHUB_TOKEN', 'fake-token')
    @patch('core.views.error_reporting.http.get')
    def test_returns_false_on_bad_response(self, mock_get):
        mock = MagicMock()
        mock.ok = False
        mock_get.return_value = mock
        assert _issue_exists('ConnectionError', 'up') is False


# ── _create_issue ─────────────────────────────────────────────────────────────

class TestCreateIssue:
    @patch('core.views.error_reporting.GITHUB_TOKEN', '')
    def test_returns_false_when_no_token(self):
        assert _create_issue('title', 'body') is False

    @patch('core.views.error_reporting.GITHUB_TOKEN', 'fake-token')
    @patch('core.views.error_reporting.http.post')
    def test_returns_true_on_201(self, mock_post):
        mock = MagicMock()
        mock.status_code = 201
        mock_post.return_value = mock
        assert _create_issue('title', 'body') is True

    @patch('core.views.error_reporting.GITHUB_TOKEN', 'fake-token')
    @patch('core.views.error_reporting.http.post')
    def test_returns_false_on_non_201(self, mock_post):
        mock = MagicMock()
        mock.status_code = 403
        mock_post.return_value = mock
        assert _create_issue('title', 'body') is False

    @patch('core.views.error_reporting.GITHUB_TOKEN', 'fake-token')
    @patch('core.views.error_reporting.http.post')
    def test_returns_false_on_network_error(self, mock_post):
        mock_post.side_effect = Exception('network error')
        assert _create_issue('title', 'body') is False


# ── _build_body ───────────────────────────────────────────────────────────────

class TestBuildBody:
    def _data(self, **kwargs):
        base = {
            'exc_type': 'ConnectionError',
            'exc_message': 'timed out',
            'traceback': ['  File "cli/drp.py", line 42, in main\n'],
            'cli_version': '0.1.12',
            'python_version': '3.12.0',
            'platform': 'Linux',
            'command': 'up',
        }
        base.update(kwargs)
        return base

    def test_contains_exc_type(self):
        assert 'ConnectionError' in _build_body(self._data())

    def test_contains_command(self):
        assert 'drp up' in _build_body(self._data())

    def test_contains_versions(self):
        body = _build_body(self._data())
        assert '0.1.12' in body
        assert '3.12.0' in body
        assert 'Linux' in body

    def test_traceback_newlines_are_intact(self):
        data = self._data(traceback=[
            '  File "cli/drp.py", line 42, in main',
            '  File "cli/api/text.py", line 10, in upload',
        ])
        body = _build_body(data)
        lines = body.split('\n')
        drp_lines = [l for l in lines if 'cli/drp.py' in l]
        api_lines = [l for l in lines if 'cli/api/text.py' in l]
        assert len(drp_lines) == 1
        assert len(api_lines) == 1

    def test_empty_traceback_shows_none(self):
        assert '(none)' in _build_body(self._data(traceback=[]))

    def test_no_user_data_in_output(self):
        data = self._data(
            exc_message='failed for user@example.com',
            traceback=['  File "/home/victorio/cli.py", line 1, in main\n'],
        )
        body = _build_body(data)
        assert 'user@example.com' not in body
        assert '/home/victorio' not in body

    def test_contains_privacy_notice(self):
        assert 'No user data included' in _build_body(self._data())