"""
cli/tests/conftest.py

Shared pytest fixtures for the CLI test suite.
"""

import tempfile
from pathlib import Path
import pytest

from cli import config


@pytest.fixture(autouse=False)
def isolated_drops_file(tmp_path):
    """
    Redirect DROPS_FILE to a temp location for the duration of a test.
    Use when a test calls config.record_drop / remove / rename / load.
    """
    orig = config.DROPS_FILE
    config.DROPS_FILE = tmp_path / 'drops.json'
    yield config.DROPS_FILE
    config.DROPS_FILE = orig


@pytest.fixture(autouse=False)
def isolated_config_file(tmp_path):
    """
    Redirect CONFIG_FILE to a temp location.
    Use when a test calls config.save / config.load without a path arg.
    """
    orig = config.CONFIG_FILE
    config.CONFIG_FILE = tmp_path / 'config.json'
    yield config.CONFIG_FILE
    config.CONFIG_FILE = orig
