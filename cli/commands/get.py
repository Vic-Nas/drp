"""
drp get — retrieve a clipboard or file drop.

  drp get key          clipboard → stdout, file → saved to disk
  drp get f/key        explicitly fetch a file drop
  drp get key -o out   save with custom filename
"""

import sys

import requests

from cli import config, api
from cli.session import load_session
from cli.format import human_size


def cmd_get(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    load_session(session)  # silent — never prompts for password

    raw_key = args.key
    force_file = raw_key.startswith('f/')
    key = raw_key[2:] if force_file else raw_key

    if force_file:
        _get_file(host, session, key, args)
        return

    # Try clipboard first, fall back to file
    kind, content = api.get_clipboard(host, session, key)
    if kind == 'text':
        print(content)
        return

    # Not a clipboard — try file namespace
    kind, content = api.get_file(host, session, key)
    if kind == 'file':
        _save_file(content, key, args)
        return

    print(f'  ✗ No drop found for key "{key}".')
    sys.exit(1)


def _get_file(host, session, key, args):
    kind, content = api.get_file(host, session, key)
    if kind != 'file':
        sys.exit(1)
    _save_file(content, key, args)


def _save_file(content, key, args):
    data, filename = content
    out = args.output or filename
    with open(out, 'wb') as f:
        f.write(data)
    print(f'  ✓ Saved {out} ({human_size(len(data))})')