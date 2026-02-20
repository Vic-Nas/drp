"""
drp diff — compare two clipboard drops.

  drp diff <key1> <key2>

Fetches both clipboard drops and prints a unified diff to stdout.
Exits 0 if identical, 1 if different, 2 on error.
File drops are not supported.
"""

import difflib
import sys

import requests

from cli import config, api
from cli.session import auto_login


def cmd_diff(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(2)

    session = requests.Session()
    auto_login(cfg, host, session)

    from cli.spinner import Spinner
    from cli.format import green, red, dim

    with Spinner('fetching'):
        kind_a, content_a = api.get_clipboard(host, session, args.key1)
        kind_b, content_b = api.get_clipboard(host, session, args.key2)

    if kind_a is None:
        print(f'  ✗ Drop /{args.key1}/ not found or is a file drop.')
        sys.exit(2)
    if kind_b is None:
        print(f'  ✗ Drop /{args.key2}/ not found or is a file drop.')
        sys.exit(2)

    lines_a = content_a.splitlines(keepends=True)
    lines_b = content_b.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        lines_a, lines_b,
        fromfile=f'/{args.key1}/',
        tofile=f'/{args.key2}/',
    ))

    if not diff:
        print(f'  {green("✓")} /{args.key1}/ and /{args.key2}/ are identical.')
        sys.exit(0)

    for line in diff:
        if line.startswith('+') and not line.startswith('+++'):
            print(green(line), end='')
        elif line.startswith('-') and not line.startswith('---'):
            print(red(line), end='')
        elif line.startswith('@@'):
            print(dim(line), end='')
        else:
            print(line, end='')

    sys.exit(1)