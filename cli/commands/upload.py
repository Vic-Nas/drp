"""
drp up — upload text or a file.

  drp up "hello"              clipboard from string
  echo "hello" | drp up       clipboard from stdin
  drp up report.pdf           file upload
  drp up report.pdf --expires 7d
"""

import os
import sys

import requests

from cli import config, api
from cli.session import auto_login
from cli.crash_reporter import report_outcome


def _parse_expires(value: str) -> int | None:
    """
    Parse --expires value into days (int).
    Accepts: 7d, 30d, 1y, or plain integer (days).
    Returns None if unparseable.
    """
    if not value:
        return None
    value = value.strip().lower()
    try:
        if value.endswith('y'):
            return int(value[:-1]) * 365
        if value.endswith('d'):
            return int(value[:-1])
        return int(value)
    except ValueError:
        return None


def cmd_up(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    auto_login(cfg, host, session)

    # ── Resolve input ─────────────────────────────────────────────────────────
    target = getattr(args, 'target', None)
    key    = args.key

    # stdin pipe: drp up (no target) or target is '-'
    if target is None or target == '-':
        if sys.stdin.isatty():
            print('  ✗ No input. Provide text, a file path, or pipe via stdin.')
            sys.exit(1)
        target = sys.stdin.read()
    elif os.path.isfile(target):
        _upload_file(host, session, target, key, cfg, args)
        return

    _upload_text(host, session, target, key, cfg, args)


def _upload_file(host, session, path, key, cfg, args):
    if not key:
        key = api.slug(os.path.basename(path))

    expiry_days = _parse_expires(getattr(args, 'expires', None))

    result_key = api.upload_file(host, session, path, key=key, expiry_days=expiry_days)
    if not result_key:
        report_outcome('up', 'upload_file returned None (prepare/confirm flow failed)')
        sys.exit(1)

    url = f'{host}/f/{result_key}/'
    print(url)
    config.record_drop(result_key, 'file', ns='f',
                       filename=os.path.basename(path), host=host)


def _upload_text(host, session, text, key, cfg, args):
    expiry_days = _parse_expires(getattr(args, 'expires', None))

    result_key = api.upload_text(host, session, text, key=key, expiry_days=expiry_days)
    if not result_key:
        report_outcome('up', 'upload_text returned None for clipboard drop')
        sys.exit(1)

    url = f'{host}/{result_key}/'
    print(url)
    config.record_drop(result_key, 'text', ns='c', host=host)