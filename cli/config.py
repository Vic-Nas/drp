"""
Config management for the drp CLI.

Stores host and email in ~/.config/drp/config.json.
"""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / '.config' / 'drp'
CONFIG_FILE = CONFIG_DIR / 'config.json'


def load(path=None):
    """Load config from disk. Returns empty dict if missing."""
    p = Path(path) if path else CONFIG_FILE
    if p.exists():
        return json.loads(p.read_text())
    return {}


def save(cfg, path=None):
    """Save config to disk, creating parent dirs if needed."""
    p = Path(path) if path else CONFIG_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2) + '\n')
