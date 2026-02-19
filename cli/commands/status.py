"""
drp status and drp ping commands.
"""

import sys

import requests

from cli import config
from cli.session import SESSION_FILE


def cmd_status(args):
    cfg = config.load()
    local_count = len(config.load_local_drops())
    print('drp status')
    print('──────────')
    print(f'  Host:        {cfg.get("host", "(not set)")}')
    print(f'  Account:     {cfg.get("email", "anonymous")}')
    print(f'  Session:     {"active" if SESSION_FILE.exists() else "none"}')
    print(f'  Local drops: {local_count}')
    print(f'  Config:      {config.CONFIG_FILE}')
    print(f'  Cache:       {config.DROPS_FILE}')


def cmd_ping(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)
    try:
        res = requests.get(f'{host}/', timeout=5)
        print(f'  ✓ {host} reachable (HTTP {res.status_code})')
    except requests.ConnectionError:
        print(f'  ✗ {host} unreachable — connection refused.')
        sys.exit(1)
    except requests.Timeout:
        print(f'  ✗ {host} unreachable — timed out.')
        sys.exit(1)
    except Exception as e:
        print(f'  ✗ {host} unreachable: {e}')
        sys.exit(1)