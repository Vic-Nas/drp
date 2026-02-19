"""
drp load — import a JSON export, bookmarking all drops server-side.

  drp load backup.json

Reads a drp export file and sends it to the server, which creates
SavedDrop entries for the current user. No content is transferred —
just the keys. The importer gets no ownership or edit permissions.
Requires login.
"""

import json
import sys

import requests

from cli import config
from cli.session import auto_login


def cmd_load(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    if not cfg.get('email'):
        print('  ✗ drp load requires a logged-in account. Run: drp login')
        sys.exit(1)

    try:
        with open(args.file) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f'  ✗ File not found: {args.file}')
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f'  ✗ Invalid JSON: {e}')
        sys.exit(1)

    session = requests.Session()
    authed = auto_login(cfg, host, session)
    if not authed:
        print('  ✗ Not logged in. Run: drp login')
        sys.exit(1)

    try:
        res = session.post(
            f'{host}/auth/account/import/',
            json=data,
            headers={'Content-Type': 'application/json'},
            timeout=15,
        )
    except Exception as e:
        print(f'  ✗ Request failed: {e}')
        sys.exit(1)

    if not res.ok:
        try:
            msg = res.json().get('error', res.text[:200])
        except Exception:
            msg = res.text[:200]
        print(f'  ✗ Import failed: {msg}')
        sys.exit(1)

    result = res.json()
    imported = result.get('imported', 0)
    skipped = result.get('skipped', 0)

    print(f'  ✓ Imported {imported} drop(s) as saved.' + (f' {skipped} already saved or skipped.' if skipped else ''))