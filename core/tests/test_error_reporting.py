"""
Unit tests for error reporting logic.
Imports from core/error_reporting_logic.py which has no Django dependency,
so this runs cleanly in CI without a Django install.
"""

from unittest.mock import patch, MagicMock
import pytest

from core.error_reporting_logic import (
    _scrub,
    _scrub_traceback,
    _issue_title,
    _issue_exists,
    _create_issue,
    _build_body,
    _fingerprint,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_issue(title, body=''):
    return {'title': title, 'state': 'open', 'body': body}


def _mock_gh_response(issues):
    mock = MagicMock()
    mock.ok = True
    mock.json.return_value = issues
    return mock


def _data(**kwargs):
    """Minimal valid data dict; override fields via kwargs."""
    base = {
        'exc_type':    'ConnectionError',
        'exc_message': 'timed out',
        'traceback':   [],
        'command':     'up',
        'cli_version': '0.1.12',
    }
    base.update(kwargs)
    return base


def _issue_with_fp(data, title='[auto] some issue'):
    """Return a mock GitHub issue whose body contains the fingerprint for data."""
    fp = _fingerprint(data)
    return _make_issue(title, body=f'some body\n<!-- drp-fingerprint: {fp} -->\n')


# ── _scrub ────────────────────────────────────────────────────────────────────

class TestScrub:
    def test_scrubs_email(self):
        assert '[email]' in _scrub('user@example.com')

    def test_scrubs_url(self):
        assert '[url]' in _scrub('https://example.com/path')

    def test_scrubs_home_path_linux(self):
        result = _scrub('/home/victorio/code')
        assert 'victorio' not in result
        assert '[user]' in result

    def test_scrubs_home_path_mac(self):
        result = _scrub('/Users/victorio/code')
        assert 'victorio' not in result
        assert '[user]' in result

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

    def test_passes_through_exception_message_lines(self):
        lines = ['ConnectionError: timed out\n']
        result = _scrub_traceback(lines)
        assert 'ConnectionError' in result[0]

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

    def test_output_length_matches_input_length(self):
        lines = [
            '  File "cli/drp.py", line 42, in main\n',
            '    x = secret_value\n',
            'During handling of the above exception\n',
        ]
        result = _scrub_traceback(lines)
        assert len(result) == len(lines)


# ── _issue_title ──────────────────────────────────────────────────────────────

class TestIssueTitle:
    def test_format(self):
        assert _issue_title('ConnectionError', 'up') == '[auto] ConnectionError in `drp up`'


# ── _fingerprint ──────────────────────────────────────────────────────────────

class TestFingerprint:
    def test_same_data_produces_same_fingerprint(self):
        d = _data(traceback=['  File "cli/drp.py", line 42, in main\n'])
        assert _fingerprint(d) == _fingerprint(d)

    def test_different_exc_type_produces_different_fingerprint(self):
        a = _data(exc_type='ConnectionError')
        b = _data(exc_type='ValueError')
        assert _fingerprint(a) != _fingerprint(b)

    def test_command_does_not_affect_fingerprint(self):
        # Same bug from two different commands must share a fingerprint.
        a = _data(command='up')
        b = _data(command='serve')
        assert _fingerprint(a) == _fingerprint(b)

    def test_line_number_does_not_affect_fingerprint(self):
        # Same bug after a version bump (line numbers shift) must still match.
        a = _data(traceback=['  File "cli/drp.py", line 42, in main\n'])
        b = _data(traceback=['  File "cli/drp.py", line 99, in main\n'])
        assert _fingerprint(a) == _fingerprint(b)

    def test_different_traceback_produces_different_fingerprint(self):
        a = _data(traceback=['  File "cli/drp.py", line 1, in main\n'])
        b = _data(traceback=['  File "cli/api/text.py", line 1, in upload\n'])
        assert _fingerprint(a) != _fingerprint(b)

    def test_returns_12_char_hex(self):
        fp = _fingerprint(_data())
        assert len(fp) == 12
        assert all(c in '0123456789abcdef' for c in fp)


# ── _issue_exists ─────────────────────────────────────────────────────────────

class TestIssueExists:
    @patch('core.error_reporting_logic.GITHUB_TOKEN', '')
    def test_returns_false_when_no_token(self):
        assert _issue_exists(_data()) is False

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.get')
    def test_returns_true_on_fingerprint_match(self, mock_get):
        d = _data()
        mock_get.return_value = _mock_gh_response([_issue_with_fp(d)])
        assert _issue_exists(d) is True

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.get')
    def test_returns_false_when_no_matching_fingerprint(self, mock_get):
        # Open issue has a different exc_type, so fingerprint won't match.
        existing = _data(exc_type='TimeoutError')
        incoming = _data(exc_type='ConnectionError')
        mock_get.return_value = _mock_gh_response([_issue_with_fp(existing)])
        assert _issue_exists(incoming) is False

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.get')
    def test_same_bug_different_command_is_deduplicated(self, mock_get):
        # Bug reported from `drp serve` should match an issue filed from `drp up`.
        filed_from_up   = _data(command='up')
        filed_from_serve = _data(command='serve')
        mock_get.return_value = _mock_gh_response([_issue_with_fp(filed_from_up)])
        assert _issue_exists(filed_from_serve) is True

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.get')
    def test_flood_guard_triggers_at_limit(self, mock_get):
        from core.error_reporting_logic import _FLOOD_LIMIT
        # Fill up to the limit with issues that won't fingerprint-match incoming.
        issues = [
            _issue_with_fp(_data(exc_type=f'Error{i}'))
            for i in range(_FLOOD_LIMIT)
        ]
        mock_get.return_value = _mock_gh_response(issues)
        # A brand-new error type should still be blocked by the flood guard.
        assert _issue_exists(_data(exc_type='BrandNewError')) is True

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.get')
    def test_flood_guard_does_not_trigger_below_limit(self, mock_get):
        from core.error_reporting_logic import _FLOOD_LIMIT
        issues = [
            _issue_with_fp(_data(exc_type=f'Error{i}'))
            for i in range(_FLOOD_LIMIT - 1)
        ]
        mock_get.return_value = _mock_gh_response(issues)
        assert _issue_exists(_data(exc_type='BrandNewError')) is False

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.get')
    def test_returns_false_on_network_error(self, mock_get):
        mock_get.side_effect = Exception('network error')
        assert _issue_exists(_data()) is False

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.get')
    def test_returns_false_on_bad_response(self, mock_get):
        mock = MagicMock()
        mock.ok = False
        mock_get.return_value = mock
        assert _issue_exists(_data()) is False

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.get')
    def test_issue_with_no_body_does_not_crash(self, mock_get):
        # GitHub issues can have a null body.
        mock_get.return_value = _mock_gh_response([
            {'title': '[auto] something', 'state': 'open', 'body': None},
        ])
        assert _issue_exists(_data()) is False


# ── _create_issue ─────────────────────────────────────────────────────────────

class TestCreateIssue:
    @patch('core.error_reporting_logic.GITHUB_TOKEN', '')
    def test_returns_false_when_no_token(self):
        assert _create_issue('title', 'body') is False

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.post')
    def test_returns_true_on_201(self, mock_post):
        mock = MagicMock()
        mock.status_code = 201
        mock_post.return_value = mock
        assert _create_issue('title', 'body') is True

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.post')
    def test_returns_false_on_non_201(self, mock_post):
        mock = MagicMock()
        mock.status_code = 403
        mock_post.return_value = mock
        assert _create_issue('title', 'body') is False

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.post')
    def test_returns_false_on_network_error(self, mock_post):
        mock_post.side_effect = Exception('network error')
        assert _create_issue('title', 'body') is False

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.post')
    def test_posts_correct_labels(self, mock_post):
        mock = MagicMock()
        mock.status_code = 201
        mock_post.return_value = mock
        _create_issue('title', 'body')
        _, kwargs = mock_post.call_args
        labels = kwargs['json']['labels']
        assert 'bug' in labels
        assert 'auto-reported' in labels

    @patch('core.error_reporting_logic.GITHUB_TOKEN', 'fake-token')
    @patch('core.error_reporting_logic.http.post')
    def test_posts_to_correct_repo(self, mock_post):
        mock = MagicMock()
        mock.status_code = 201
        mock_post.return_value = mock
        _create_issue('title', 'body')
        url = mock_post.call_args[0][0]
        assert 'vicnasdev/drp' in url


# ── _build_body ───────────────────────────────────────────────────────────────

class TestBuildBody:
    def _data(self, **kwargs):
        base = {
            'exc_type':       'ConnectionError',
            'exc_message':    'timed out',
            'traceback':      ['  File "cli/drp.py", line 42, in main\n'],
            'cli_version':    '0.1.12',
            'python_version': '3.12.0',
            'platform':       'Linux',
            'command':        'up',
        }
        base.update(kwargs)
        return base

    def test_returns_title_and_body_tuple(self):
        result = _build_body(self._data())
        assert isinstance(result, tuple) and len(result) == 2

    def test_title_contains_exc_type_and_command(self):
        title, _ = _build_body(self._data())
        assert 'ConnectionError' in title
        assert 'drp up' in title

    def test_contains_exc_type(self):
        _, body = _build_body(self._data())
        assert 'ConnectionError' in body

    def test_contains_command(self):
        _, body = _build_body(self._data())
        assert 'drp up' in body

    def test_contains_versions(self):
        _, body = _build_body(self._data())
        assert '0.1.12' in body
        assert '3.12.0' in body
        assert 'Linux' in body

    def test_traceback_newlines_are_intact(self):
        data = self._data(traceback=[
            '  File "cli/drp.py", line 42, in main',
            '  File "cli/api/text.py", line 10, in upload',
        ])
        _, body = _build_body(data)
        lines = body.split('\n')
        assert len([l for l in lines if 'cli/drp.py' in l]) == 1
        assert len([l for l in lines if 'cli/api/text.py' in l]) == 1

    def test_empty_traceback_shows_none(self):
        _, body = _build_body(self._data(traceback=[]))
        assert '(none)' in body

    def test_no_user_data_in_output(self):
        data = self._data(
            exc_message='failed for user@example.com',
            traceback=['  File "/home/victorio/cli.py", line 1, in main\n'],
        )
        _, body = _build_body(data)
        assert 'user@example.com' not in body
        assert '/home/victorio' not in body

    def test_contains_privacy_notice(self):
        _, body = _build_body(self._data())
        assert 'No user data included' in body

    def test_contains_fingerprint_comment(self):
        _, body = _build_body(self._data())
        assert '<!-- drp-fingerprint:' in body

    def test_fingerprint_in_body_matches_fingerprint_function(self):
        import re
        data = self._data()
        _, body = _build_body(data)
        m = re.search(r'<!-- drp-fingerprint: ([a-f0-9]{12}) -->', body)
        assert m is not None
        assert m.group(1) == _fingerprint(data)

    def test_missing_optional_fields_dont_crash(self):
        _, body = _build_body({'exc_type': 'ValueError'})
        assert 'ValueError' in body