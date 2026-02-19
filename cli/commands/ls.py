"""
drp ls — list drops (server for logged-in users, local cache for anon).
"""

import sys

import requests

from cli import config, api
from cli.session import auto_login, load_session
from cli.format import human_size, human_time


def cmd_ls(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    long_fmt = getattr(args, 'long', False)
    human = getattr(args, 'human', False)
    sort_key = getattr(args, 'sort', None)
    reverse = getattr(args, 'reverse', False)
    ns_filter = getattr(args, 'type', None)

    email = cfg.get('email')
    if email:
        session = requests.Session()
        authed = auto_login(cfg, host, session)

        if authed and getattr(args, 'export', False):
            _do_export(host, session)
            return

        if authed:
            drops = api.list_drops(host, session)
            if drops is not None:
                _print_drops(drops, host, long_fmt, human, sort_key, reverse, ns_filter, source='server')
                return

    # Fall back to local cache
    local = config.load_local_drops()
    if not local:
        print('  (no drops)')
        return

    # Prune stale entries
    anon_session = requests.Session()
    alive, stale = [], []
    for d in local:
        ns = d.get('ns', 'c')
        if api.key_exists(host, anon_session, d['key'], ns=ns):
            alive.append(d)
        else:
            stale.append(d)

    if stale:
        config.save_local_drops(alive)
        if long_fmt:
            for d in stale:
                print(f"  {d['key']:30s}  (gone — renamed or expired)")

    if not alive:
        print('  (no drops)')
        return

    _print_drops(alive, host, long_fmt, human, sort_key, reverse, ns_filter, source='local')


def _do_export(host, session):
    try:
        res = session.get(f'{host}/auth/account/export/', timeout=15)
        if res.ok:
            print(res.text)
            return
        print('  ✗ Export failed.')
    except Exception as e:
        print(f'  ✗ Export error: {e}')
    sys.exit(1)


def _print_drops(drops, host, long_fmt, human, sort_key, reverse, ns_filter, source):
    if ns_filter:
        drops = [d for d in drops if d.get('ns', 'c') == ns_filter]

    if not drops:
        print('  (no drops)')
        return

    # Sort
    if sort_key == 'time':
        drops = sorted(drops, key=lambda d: d.get('created_at', ''), reverse=not reverse)
    elif sort_key == 'size':
        drops = sorted(drops, key=lambda d: d.get('filesize') or 0, reverse=not reverse)
    elif sort_key == 'name':
        drops = sorted(drops, key=lambda d: d.get('key', ''), reverse=reverse)
    elif reverse:
        drops = list(reversed(drops))

    if source == 'local':
        print('  (local cache)\n')

    if long_fmt:
        print(f"  {'TYPE':<6}  {'SIZE':>7}  {'MODIFIED':<12}  {'KEY':<25}  URL")
        print(f"  {'─'*6}  {'─'*7}  {'─'*12}  {'─'*25}  {'─'*30}")
        for d in drops:
            ns = d.get('ns', 'c')
            key = d.get('key', '?')
            drop_host = d.get('host', host) or host
            url = f'{drop_host}/f/{key}/' if ns == 'f' else f'{drop_host}/{key}/'
            size = human_size(d.get('filesize')) if human else (str(d.get('filesize')) if d.get('filesize') else '-')
            modified = human_time(d.get('last_accessed_at') or d.get('created_at'))
            kind_label = 'file' if ns == 'f' else 'clip'
            name = d.get('filename', '')
            display_key = key + (f'  ({name})' if name else '')
            expiry = _expiry_str(d)
            print(f"  {kind_label:<6}  {size:>7}  {modified:<12}  {display_key:<25}  {url}")
            print(f"  {'':6}  {'':>7}  {'expires:':12}  {expiry}")
    else:
        for d in drops:
            ns = d.get('ns', 'c')
            key = d.get('key', '?')
            drop_host = d.get('host', host) or host
            url = f'{drop_host}/f/{key}/' if ns == 'f' else f'{drop_host}/{key}/'
            kind_label = 'file' if ns == 'f' else 'clip'
            name = d.get('filename', '')
            suffix = f'  {name}' if name else ''
            print(f'  {key:<30}  {kind_label:<4}{suffix}  {url}')


def _expiry_str(drop):
    expires_at = drop.get('expires_at')
    if expires_at:
        return human_time(expires_at)
    ns = drop.get('ns', 'c')
    if ns == 'c':
        last = drop.get('last_accessed_at') or drop.get('created_at')
        return f'idle+24h (last: {human_time(last)})'
    return '90d from upload'