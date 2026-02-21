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

    from cli.format import dim, green, bold
    from cli.spinner import Spinner

    cfg = config.load()

    with Spinner('loading'):
        _sync_local_cache(cfg)

    local_count = len(config.load_local_drops())

    print(bold('drp status'))
    print(dim('──────────'))
    print(f'  {dim("Host:")}        {cfg.get("host", "(not set)")}')
    print(f'  {dim("Account:")}     {cfg.get("email", "anonymous")}')

    session_active = SESSION_FILE.exists()
    session_str = green('active') if session_active else dim('none')
    print(f'  {dim("Session:")}     {session_str}')

    print(f'  {dim("Local drops:")} {local_count}')
    print(f'  {dim("Config:")}      {config.CONFIG_FILE}')
    print(f'  {dim("Cache:")}       {config.DROPS_FILE}')


def _drop_status(args, key):
    """Fetch and display view stats for a specific drop."""
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    ns = 'f' if getattr(args, 'file', False) and not getattr(args, 'clip', False) else 'c'
    url = f'{host}/f/{key}/' if ns == 'f' else f'{host}/{key}/'

    from cli.spinner import Spinner
    from cli.format import dim, green, red, bold
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

    sep = dim('─' * (len(key) + len(prefix) + 3))
    print(f'  {bold("/" + prefix + key + "/")}')
    print(f'  {sep}')
    print(f'  {dim("views")}       {green(str(views)) if views else dim("0")}')
    print(f'  {dim("last seen")}   {human_time(last) if last else dim("never")}')
    print(f'  {dim("created")}     {human_time(data.get("created_at"))}')
    if data.get('expires_at'):
        print(f'  {dim("expires")}     {human_time(data.get("expires_at"))}')
    else:
        kind = data.get('kind', 'text')
        idle = dim('24h after last access' if kind == 'text' else '90d after upload')
        print(f'  {dim("expires")}     {idle}')


def _sync_local_cache(cfg) -> None:
    """
    Synchronously prune dead drops from the local cache.
    Only runs if a session exists and the user is logged in.
    Silent — never blocks or raises.
    """
    try:
        from cli.session import SESSION_FILE
        if not SESSION_FILE.exists():
            return
        email = cfg.get('email')
        host  = cfg.get('host')
        if not email or not host:
            return
        from cli.completion import _do_refresh
        _do_refresh(config, SESSION_FILE)
    except Exception:
        pass


def cmd_ping(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    from cli.format import green, red

    try:
        res = requests.get(f'{host}/', timeout=5)
        tick = green('✓')
        print(f'  {tick} {host} reachable (HTTP {res.status_code})')
    except requests.ConnectionError:
        cross = red('✗')
        print(f'  {cross} {host} unreachable — connection refused.')
        sys.exit(1)
    except requests.Timeout:
        cross = red('✗')
        print(f'  {cross} {host} unreachable — timed out.')
        sys.exit(1)
    except Exception as e:
        cross = red('✗')
        print(f'  {cross} {host} unreachable: {e}')
        sys.exit(1)