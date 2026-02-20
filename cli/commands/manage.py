"""
Drop management commands: rm, mv, renew.

Key format accepted by all commands:
  key       → clipboard (ns=c)
  -f key    → file (ns=f)
"""

import sys

import requests

from cli import config, api
from cli.session import auto_login
from cli.format import human_time
from cli.crash_reporter import report_outcome


def _parse_key(raw, is_file=False):
    """Return (ns, key). Pass is_file=True for file drops."""
    return ('f', raw) if is_file else ('c', raw)


def cmd_rm(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    auto_login(cfg, host, session)

    ns, key = _parse_key(args.key, args.file)

    if api.delete(host, session, key, ns=ns):
        prefix = 'f/' if ns == 'f' else ''
        print(f'  ✓ Deleted /{prefix}{key}/')
        config.remove_local_drop(key)
    else:
        # api.delete() already printed an error and filed a report if it got
        # an unexpected HTTP status. report_outcome() covers the case where it
        # returned False for a non-HTTP reason (e.g. network exception swallowed).
        report_outcome('rm', f'delete returned False for ns={ns} drop')
        print(f'  ✗ Could not delete /{key}/.')
        sys.exit(1)


def cmd_mv(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    auto_login(cfg, host, session)

    ns, key = _parse_key(args.key, args.file)
    new_key = api.rename(host, session, key, args.new_key, ns=ns)

    if new_key:
        prefix = 'f/' if ns == 'f' else ''
        print(f'  ✓ /{prefix}{key}/ → /{prefix}{new_key}/')
        config.rename_local_drop(key, new_key)
    else:
        report_outcome('mv', f'rename returned None for ns={ns} drop')
        print(f'  ✗ Could not rename /{key}/.')
        sys.exit(1)


def cmd_renew(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    auto_login(cfg, host, session)

    ns, key = _parse_key(args.key, args.file)
    expires_at, renewals = api.renew(host, session, key, ns=ns)

    if expires_at:
        prefix = 'f/' if ns == 'f' else ''
        print(f'  ✓ /{prefix}{key}/ renewed → expires {human_time(expires_at)} (renewal #{renewals})')
    else:
        report_outcome('renew', f'renew returned (None, None) for ns={ns} drop')
        print(f'  ✗ Could not renew /{key}/.')
        sys.exit(1)