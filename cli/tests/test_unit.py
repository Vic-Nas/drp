"""
cli/tests/test_unit.py

Unit tests: config, local drop cache, slug, formatting, version.
Migrated from tests_unit.py with gaps filled.

No network, no Django.
"""

import os
import tempfile
from datetime import datetime, timezone as tz, timedelta
from pathlib import Path

import pytest

from cli import api, config
from cli.format import human_size, human_time


# ── Config ────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_load_missing_file_returns_empty_dict(self):
        assert config.load('/tmp/drp_no_such_file_xyz.json') == {}

    def test_save_and_load_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            cfg = {'host': 'https://example.com', 'email': 'a@b.com'}
            config.save(cfg, path)
            assert config.load(path) == cfg
        finally:
            os.unlink(path)

    def test_save_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'sub', 'nested', 'config.json')
            config.save({'host': 'x'}, path)
            assert os.path.exists(path)

    def test_save_overwrites_existing(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            config.save({'host': 'old'}, path)
            config.save({'host': 'new'}, path)
            assert config.load(path)['host'] == 'new'
        finally:
            os.unlink(path)

    def test_load_returns_all_keys(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            cfg = {'host': 'https://example.com', 'email': 'x@y.com', 'ansi': True}
            config.save(cfg, path)
            loaded = config.load(path)
            assert loaded['ansi'] is True
            assert loaded['email'] == 'x@y.com'
        finally:
            os.unlink(path)


# ── Local drop cache ──────────────────────────────────────────────────────────

class TestLocalDropCache:
    def setup_method(self):
        self._orig = config.DROPS_FILE
        config.DROPS_FILE = Path(tempfile.mktemp(suffix='.json'))

    def teardown_method(self):
        if config.DROPS_FILE.exists():
            config.DROPS_FILE.unlink()
        config.DROPS_FILE = self._orig

    def test_load_returns_empty_list_when_missing(self):
        assert config.load_local_drops() == []

    def test_record_drop_appears_in_list(self):
        config.record_drop('k1', 'text', host='https://example.com')
        drops = config.load_local_drops()
        assert len(drops) == 1
        assert drops[0]['key'] == 'k1'

    def test_record_same_key_twice_no_duplicate(self):
        config.record_drop('k', 'text', host='https://example.com')
        config.record_drop('k', 'text', host='https://example.com')
        assert len(config.load_local_drops()) == 1

    def test_record_file_drop_stores_ns(self):
        config.record_drop('report', 'file', ns='f', host='https://example.com')
        drop = config.load_local_drops()[0]
        assert drop['ns'] == 'f'
        assert drop['kind'] == 'file'

    def test_record_with_filename(self):
        config.record_drop('q3', 'file', ns='f', filename='q3.pdf',
                            host='https://example.com')
        drop = config.load_local_drops()[0]
        assert drop['filename'] == 'q3.pdf'

    def test_remove_only_removes_target(self):
        config.record_drop('keep', 'text', host='https://example.com')
        config.record_drop('remove', 'text', host='https://example.com')
        config.remove_local_drop('remove')
        keys = [d['key'] for d in config.load_local_drops()]
        assert 'keep' in keys
        assert 'remove' not in keys

    def test_remove_nonexistent_key_is_safe(self):
        config.record_drop('k', 'text', host='https://example.com')
        config.remove_local_drop('no-such-key')
        assert len(config.load_local_drops()) == 1

    def test_rename_updates_key_preserves_other_fields(self):
        config.record_drop('old', 'file', filename='data.csv',
                            host='https://example.com')
        config.rename_local_drop('old', 'new')
        drop = config.load_local_drops()[0]
        assert drop['key'] == 'new'
        assert drop['filename'] == 'data.csv'

    def test_rename_nonexistent_key_is_safe(self):
        config.record_drop('k', 'text', host='https://example.com')
        config.rename_local_drop('no-such-key', 'whatever')
        assert config.load_local_drops()[0]['key'] == 'k'

    def test_most_recent_drop_is_first(self):
        config.record_drop('first', 'text', host='https://example.com')
        config.record_drop('second', 'text', host='https://example.com')
        drops = config.load_local_drops()
        assert drops[0]['key'] == 'second'


# ── Slug ──────────────────────────────────────────────────────────────────────

class TestSlug:
    def test_strips_extension(self):
        assert api.slug('notes.txt') == 'notes'

    def test_spaces_become_hyphens(self):
        assert api.slug('my cool file.pdf') == 'my-cool-file'

    def test_truncated_to_40_chars(self):
        result = api.slug('a' * 100 + '.txt')
        assert len(result) <= 40
        assert len(result) > 0

    def test_only_safe_chars(self):
        result = api.slug('hello world (copy) [2].txt')
        for ch in result:
            assert ch.isalnum() or ch == '-', f'Unsafe char in slug: {ch!r}'

    def test_dotfile_produces_nonempty_slug(self):
        assert len(api.slug('.bashrc')) > 0

    def test_unicode_filename_safe(self):
        result = api.slug('résumé.pdf')
        assert len(result) > 0

    def test_no_leading_or_trailing_hyphens(self):
        result = api.slug('  spaced.txt  ')
        assert not result.startswith('-')
        assert not result.endswith('-')

    def test_no_consecutive_hyphens(self):
        result = api.slug('hello   world.txt')
        assert '--' not in result


# ── Format: human_size ────────────────────────────────────────────────────────

class TestHumanSize:
    def test_bytes(self):
        assert human_size(512) == '512B'

    def test_kilobytes(self):
        assert 'K' in human_size(2048)

    def test_megabytes(self):
        assert 'M' in human_size(5 * 1024 * 1024)

    def test_gigabytes(self):
        assert 'G' in human_size(2 * 1024 ** 3)

    def test_zero_returns_dash(self):
        assert human_size(0) == '-'

    def test_one_byte(self):
        assert human_size(1) == '1B'


# ── Format: human_time ────────────────────────────────────────────────────────

class TestHumanTime:
    def _iso(self, **delta):
        return (datetime.now(tz.utc) - timedelta(**delta)).isoformat()

    def test_just_now(self):
        assert human_time(self._iso(seconds=5)) == 'just now'

    def test_minutes_ago(self):
        result = human_time(self._iso(minutes=30))
        assert result.endswith('m ago')

    def test_hours_ago(self):
        result = human_time(self._iso(hours=3))
        assert result.endswith('h ago')

    def test_days_ago(self):
        result = human_time(self._iso(days=3))
        assert result.endswith('d ago')

    def test_old_date_returns_date_string(self):
        result = human_time(self._iso(days=30))
        # Should be YYYY-MM-DD format
        assert len(result) == 10
        assert result[4] == '-'

    def test_none_returns_dash(self):
        assert human_time(None) == '-'

    def test_empty_string_returns_dash(self):
        assert human_time('') == '-'

    def test_invalid_returns_truncated(self):
        result = human_time('2024-01-15T10:30:00')
        assert len(result) == 10


# ── Version ───────────────────────────────────────────────────────────────────

class TestVersion:
    def test_version_is_semver(self):
        from cli import __version__
        parts = __version__.split('.')
        assert len(parts) == 3, f'Expected X.Y.Z, got {__version__!r}'
        for part in parts:
            assert part.isdigit(), f'Non-numeric part: {part!r}'
