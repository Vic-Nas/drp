"""
cli/tests/test_commands.py

Tests for pure logic extracted from command modules.
No network calls, no real filesystem side-effects beyond tempfiles.

Covers:
  - upload._parse_expires
  - upload._filename_from_response
  - serve._resolve_paths
  - manage._parse_key
  - ls._since / ls._until / ls._human
  - setup._activation_line, _profile_has_activation, _append_to_profile
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── upload._parse_expires ─────────────────────────────────────────────────────

class TestParseExpires:
    def _f(self, val):
        from cli.commands.upload import _parse_expires
        return _parse_expires(val)

    def test_none_returns_none(self):
        assert self._f(None) is None

    def test_empty_string_returns_none(self):
        assert self._f('') is None

    def test_days(self):
        assert self._f('7d') == 7

    def test_days_large(self):
        assert self._f('365d') == 365

    def test_year(self):
        assert self._f('1y') == 365

    def test_two_years(self):
        assert self._f('2y') == 730

    def test_plain_integer(self):
        assert self._f('30') == 30

    def test_invalid_returns_none(self):
        assert self._f('forever') is None

    def test_leading_whitespace_handled(self):
        assert self._f('  7d  ') == 7


# ── upload._filename_from_response ────────────────────────────────────────────

class TestFilenameFromResponse:
    def _f(self, headers, url):
        from cli.commands.upload import _filename_from_response
        r = MagicMock()
        r.headers = headers
        return _filename_from_response(r, url)

    def test_content_disposition_filename(self):
        result = self._f(
            {'Content-Disposition': 'attachment; filename="report.pdf"'},
            'https://example.com/download',
        )
        assert result == 'report.pdf'

    def test_content_disposition_single_quotes(self):
        result = self._f(
            {'Content-Disposition': "attachment; filename='data.csv'"},
            'https://example.com/download',
        )
        assert result == 'data.csv'

    def test_falls_back_to_url_basename(self):
        result = self._f(
            {},
            'https://example.com/files/report.pdf',
        )
        assert result == 'report.pdf'

    def test_url_with_trailing_slash_uses_parent(self):
        result = self._f(
            {},
            'https://example.com/files/',
        )
        # Should fall back to 'download' when basename is empty
        assert result == 'download'

    def test_no_header_no_path_returns_download(self):
        result = self._f({}, 'https://example.com/')
        assert result == 'download'


# ── serve._resolve_paths ──────────────────────────────────────────────────────

class TestResolvePaths:
    def test_single_file(self):
        from cli.commands.serve import _resolve_paths
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            result = _resolve_paths([path])
            assert path in result
        finally:
            os.unlink(path)

    def test_directory_expands_to_files(self):
        from cli.commands.serve import _resolve_paths
        with tempfile.TemporaryDirectory() as d:
            f1 = os.path.join(d, 'a.txt')
            f2 = os.path.join(d, 'b.txt')
            Path(f1).write_text('a')
            Path(f2).write_text('b')
            result = _resolve_paths([d])
        assert len(result) == 2

    def test_directory_does_not_recurse(self):
        from cli.commands.serve import _resolve_paths
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, 'sub')
            os.makedirs(sub)
            f1 = os.path.join(d, 'top.txt')
            f2 = os.path.join(sub, 'nested.txt')
            Path(f1).write_text('top')
            Path(f2).write_text('nested')
            result = _resolve_paths([d])
        # Only the top-level file, not the nested one
        basenames = [os.path.basename(p) for p in result]
        assert 'top.txt' in basenames
        assert 'nested.txt' not in basenames

    def test_no_duplicates_from_overlapping_targets(self):
        from cli.commands.serve import _resolve_paths
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            result = _resolve_paths([path, path])
            assert result.count(path) == 1
        finally:
            os.unlink(path)

    def test_glob_pattern_expands(self):
        from cli.commands.serve import _resolve_paths
        with tempfile.TemporaryDirectory() as d:
            f1 = os.path.join(d, 'log1.log')
            f2 = os.path.join(d, 'log2.log')
            f3 = os.path.join(d, 'notes.txt')
            for p in (f1, f2, f3):
                Path(p).write_text('x')
            pattern = os.path.join(d, '*.log')
            result = _resolve_paths([pattern])
        basenames = [os.path.basename(p) for p in result]
        assert 'log1.log' in basenames
        assert 'log2.log' in basenames
        assert 'notes.txt' not in basenames

    def test_nonexistent_path_returns_empty(self):
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths(['/no/such/path/xyz'])
        assert result == []


# ── manage._parse_key ─────────────────────────────────────────────────────────

class TestParseKey:
    def _f(self, raw, is_file=False):
        from cli.commands.manage import _parse_key
        return _parse_key(raw, is_file)

    def test_clipboard_by_default(self):
        ns, key = self._f('hello')
        assert ns == 'c'
        assert key == 'hello'

    def test_file_flag_sets_ns(self):
        ns, key = self._f('report', is_file=True)
        assert ns == 'f'
        assert key == 'report'


# ── ls helpers ────────────────────────────────────────────────────────────────

class TestLsHelpers:
    def test_since_seconds(self):
        from cli.commands.ls import _since
        from datetime import datetime, timezone, timedelta
        iso = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        assert _since(iso).endswith('s ago')

    def test_since_minutes(self):
        from cli.commands.ls import _since
        from datetime import datetime, timezone, timedelta
        iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        assert _since(iso).endswith('m ago')

    def test_since_hours(self):
        from cli.commands.ls import _since
        from datetime import datetime, timezone, timedelta
        iso = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        assert _since(iso).endswith('h ago')

    def test_since_days(self):
        from cli.commands.ls import _since
        from datetime import datetime, timezone, timedelta
        iso = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        assert _since(iso).endswith('d ago')

    def test_since_none_returns_dash(self):
        from cli.commands.ls import _since
        assert _since(None) == '—'

    def test_until_no_expiry(self):
        from cli.commands.ls import _until
        assert _until(None) == 'no expiry'

    def test_until_expired(self):
        from cli.commands.ls import _until
        from datetime import datetime, timezone, timedelta
        iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert _until(iso) == 'expired'

    def test_until_hours_left(self):
        from cli.commands.ls import _until
        from datetime import datetime, timezone, timedelta
        iso = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        assert _until(iso).endswith('h left')

    def test_until_days_left(self):
        from cli.commands.ls import _until
        from datetime import datetime, timezone, timedelta
        iso = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        assert _until(iso).endswith('d left')

    def test_human_bytes(self):
        from cli.commands.ls import _human
        assert _human(500) == '500B'

    def test_human_kilobytes(self):
        from cli.commands.ls import _human
        assert 'K' in _human(2048)

    def test_human_megabytes(self):
        from cli.commands.ls import _human
        assert 'M' in _human(5 * 1024 * 1024)


# ── setup helpers ─────────────────────────────────────────────────────────────

class TestSetupHelpers:
    def test_activation_line_bash(self):
        from cli.commands.setup import _activation_line
        result = _activation_line('bash')
        assert 'register-python-argcomplete' in result
        assert 'eval' in result

    def test_activation_line_zsh(self):
        from cli.commands.setup import _activation_line
        result = _activation_line('zsh')
        assert 'bashcompinit' in result

    def test_activation_line_fish(self):
        from cli.commands.setup import _activation_line
        result = _activation_line('fish')
        assert 'source' in result

    def test_activation_line_unknown_returns_none(self):
        from cli.commands.setup import _activation_line
        assert _activation_line('csh') is None

    def test_profile_has_activation_true(self):
        from cli.commands.setup import _profile_has_activation
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write('eval "$(register-python-argcomplete drp)"\n')
            path = f.name
        try:
            assert _profile_has_activation(path, 'eval "$(register-python-argcomplete drp)"')
        finally:
            os.unlink(path)

    def test_profile_has_activation_false(self):
        from cli.commands.setup import _profile_has_activation
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write('export PATH="$HOME/.local/bin:$PATH"\n')
            path = f.name
        try:
            assert not _profile_has_activation(path, 'register-python-argcomplete drp')
        finally:
            os.unlink(path)

    def test_append_to_profile_writes_line(self):
        from cli.commands.setup import _append_to_profile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            path = f.name
        try:
            ok = _append_to_profile(path, 'eval "$(register-python-argcomplete drp)"')
            assert ok is True
            content = Path(path).read_text()
            assert 'register-python-argcomplete drp' in content
        finally:
            os.unlink(path)
