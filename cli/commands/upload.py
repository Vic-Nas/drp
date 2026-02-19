"""
drp up — upload text or a file.
"""

import os
import sys

import requests

from cli import config, api
from cli.session import auto_login


def cmd_up(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    auto_login(cfg, host, session)

    target = args.target
    key = args.key

    if os.path.isfile(target):
        _upload_file(host, session, target, key, cfg)
    else:
        _upload_text(host, session, target, key, cfg)


def _upload_file(host, session, path, key, cfg):
    if not key:
        key = api.slug(os.path.basename(path))

    result_key = api.upload_file(host, session, path, key=key)
    if not result_key:
        sys.exit(1)

    url = f'{host}/f/{result_key}/'
    print(url)
    config.record_drop(result_key, 'file', ns='f',
                       filename=os.path.basename(path), host=host)


def _upload_text(host, session, text, key, cfg):
    result_key = api.upload_text(host, session, text, key=key)
    if not result_key:
        sys.exit(1)

    url = f'{host}/{result_key}/'
    print(url)
    config.record_drop(result_key, 'text', ns='c', host=host)