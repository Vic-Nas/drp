"""
Unit tests for drp CLI (no Django required).
Covers: config, local cache, slug, formatting, version.
"""

import os
import tempfile
from pathlib import Path
from cli import api, config
from cli.format import human_size, human_time
import pytest

# Config tests
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

# Local drop cache tests
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
        config.record_drop('old', 'file', filename='data.csv', host='https://example.com')
        config.rename_local_drop('old', 'new')
        drop = config.load_local_drops()[0]
        assert drop['key'] == 'new'
        assert drop['filename'] == 'data.csv'

# Slug tests
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

# Format tests
class TestFormat:
    def test_human_size_bytes(self):
        assert human_size(512) == '512B'

    def test_human_size_kilobytes(self):
        result = human_size(2048)
        assert 'K' in result

    def test_human_size_megabytes(self):
        result = human_size(5 * 1024 * 1024)
        assert 'M' in result

    def test_human_size_none_returns_dash(self):
        assert human_size(0) == '-'

    def test_human_time_recent(self):
        from datetime import datetime, timezone as tz
        now = datetime.now(tz.utc).isoformat()
        result = human_time(now)
        assert result == 'just now'

    def test_human_time_invalid_returns_truncated(self):
        result = human_time('2024-01-15T10:30:00')
        assert len(result) == 10

# Version tests
class TestVersion:
    def test_version_is_semver(self):
        from cli import __version__
        parts = __version__.split('.')
        assert len(parts) == 3, f'Expected X.Y.Z, got {__version__!r}'
        for part in parts:
            assert part.isdigit(), f'Non-numeric part: {part!r}'