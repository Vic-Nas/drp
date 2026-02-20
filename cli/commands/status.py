"""
drp status and drp ping commands.

  drp status           show config, session, local drop count
  drp status <key>     show view count and last viewed for a drop
  drp ping             check server reachability
"""

import sys

import requests

from cli import config
from cli.session import SESSION_FILE


def cmd_status(args):
    key = getattr(args, 'key', None)
    if key:
        _drop_status(args, key)
        return

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


def _drop_status(args, key):
    """Fetch and display view stats for a specific drop."""
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    ns = 'f' if getattr(args, 'file', False) else 'c'
    url = f'{host}/f/{key}/' if ns == 'f' else f'{host}/{key}/'

    from cli.spinner import Spinner
    from cli.format import dim
    from cli.api.helpers import err

    session = requests.Session()
    from cli.session import auto_login
    auto_login(cfg, host, session)

    try:
        with Spinner('fetching'):
            res = session.get(url, headers={'Accept': 'application/json'}, timeout=10)
    except Exception as e:
        err(f'Could not reach server: {e}')
        sys.exit(1)

    if res.status_code == 404:
        err(f'Drop /{key}/ not found.')
        sys.exit(1)
    if res.status_code == 410:
        err(f'Drop /{key}/ has expired.')
        sys.exit(1)
    if not res.ok:
        err(f'Server returned {res.status_code}.')
        sys.exit(1)

    data = res.json()

    from cli.format import human_time

    prefix = 'f/' if ns == 'f' else ''
    views  = data.get('view_count', 0)
    last   = data.get('last_viewed_at')

    print(f'  /{prefix}{key}/')
    print(f'  {dim("─" * (len(key) + len(prefix) + 3))}')
    print(f'  views       {views}')
    print(f'  last seen   {human_time(last) if last else "never"}')
    print(f'  created     {human_time(data.get("created_at"))}')
    if data.get('expires_at'):
        print(f'  expires     {human_time(data.get("expires_at"))}')
    else:
        kind = data.get('kind', 'text')
        print(f'  expires     {"24h after last access" if kind == "text" else "90d after upload"}')


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