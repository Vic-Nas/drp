"""
drp get — fetch a clipboard drop or download a file.

  drp get <key>              print clipboard to stdout
  drp get -f <key>           download file (saves to current directory)
  drp get -f <key> -o name   download with custom filename
  drp get <key> --timing     show per-phase timing breakdown
"""

import sys

import requests

from cli import config, api
from cli.session import auto_login
from cli.timing import Timer


def cmd_get(args):
    t = Timer(enabled=getattr(args, 'timing', False))

    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    t.checkpoint('load config')

    session = requests.Session()
    t.instrument(session)   # attach response hook before any request
    auto_login(cfg, host, session)

    t.checkpoint('load session')

    if getattr(args, 'file', False):
        _get_file(args, host, session, t)
    else:
        _get_clipboard(args, host, session, t)


# ── Clipboard ─────────────────────────────────────────────────────────────────

def _get_clipboard(args, host, session, t):
    kind, content = api.get_clipboard(host, session, args.key, timer=t)

    if kind == 'text':
        t.print()
        print(content)
    elif kind is None and content is None:
        # Could be a file drop — try the file path before giving up
        url, filename = api.get_file_meta(host, session, args.key)
        if url:
            t.print()
            print(f'  ↳ This is a file drop. Use: drp get -f {args.key}')
        else:
            t.print()
            sys.exit(1)


# ── File ──────────────────────────────────────────────────────────────────────

def _get_file(args, host, session, t):
    import os

    url, filename = api.get_file_meta(host, session, args.key, timer=t)

    if not url:
        t.print()
        sys.exit(1)

    output_name = getattr(args, 'output', None) or filename or args.key

    t.checkpoint('got presigned URL')

    # Stream the download — don't time this as a single block since it
    # depends on file size. Print progress instead.
    try:
        dl = requests.get(url, stream=True, timeout=60)
        dl.raise_for_status()
    except Exception as e:
        print(f'  ✗ Download failed: {e}', file=sys.stderr)
        t.print()
        sys.exit(1)

    total = int(dl.headers.get('content-length', 0))
    received = 0

    with open(output_name, 'wb') as f:
        for chunk in dl.iter_content(chunk_size=65536):
            f.write(chunk)
            received += len(chunk)
            if total and sys.stderr.isatty():
                pct = received / total * 100
                print(f'\r  ↓ {output_name}  {pct:.0f}%', end='', file=sys.stderr)

    if total and sys.stderr.isatty():
        print(file=sys.stderr)  # newline after progress

    t.checkpoint('download')
    t.print()
    print(f'  ✓ Saved {output_name}')