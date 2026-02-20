"""
drp save — bookmark a drop to your account.

  drp save key        bookmark a clipboard drop
  drp save f/key      bookmark a file drop

Saving grants no ownership or edit rights — the drop appears
in drp ls under [saved] and in your account dashboard.
Requires login.
"""

import sys

import requests

from cli import config, api
from cli.session import auto_login


def _parse_key(raw):
    if raw.startswith('f/'):
        return 'f', raw[2:]
    return 'c', raw


def cmd_save(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    if not cfg.get('email'):
        print('  ✗ drp save requires a logged-in account. Run: drp login')
        sys.exit(1)

    session = requests.Session()
    authed = auto_login(cfg, host, session)
    if not authed:
        print('  ✗ Not logged in. Run: drp login')
        sys.exit(1)

    ns, key = _parse_key(args.key)
    prefix = 'f/' if ns == 'f' else ''

    if api.save_bookmark(host, session, key, ns=ns):
        print(f'  ✓ Saved /{prefix}{key}/ — appears in drp ls')
    else:
        sys.exit(1)