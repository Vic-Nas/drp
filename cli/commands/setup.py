"""
Setup, login, and logout commands.
"""

import getpass
import sys

import requests

from cli import config, api, DEFAULT_HOST
from cli.session import save_session, clear_session, auto_login
from cli.path_check import check_scripts_in_path


def cmd_setup(args):
    cfg = config.load()
    print('drp setup')
    print('─────────')
    default = cfg.get('host', DEFAULT_HOST)
    cfg['host'] = input(f'  Host [{default}]: ').strip() or default
    config.save(cfg)
    answer = input('  Log in now? (y/n) [y]: ').strip().lower()
    if answer != 'n':
        cmd_login(args)
    check_scripts_in_path()
    print(f'\n  ✓ Config saved to {config.CONFIG_FILE}')


def cmd_login(args):
    cfg = config.load()
    host = cfg.get('host', DEFAULT_HOST)
    email = input('  Email: ').strip()
    password = getpass.getpass('  Password: ')
    session = requests.Session()
    try:
        if api.login(host, session, email, password):
            cfg['email'] = email
            config.save(cfg)
            save_session(session)
            print(f'  ✓ Logged in as {email}')
        else:
            print('  ✗ Login failed — check your email and password.')
            sys.exit(1)
    except Exception as e:
        print(f'  ✗ Login error: {e}')
        sys.exit(1)


def cmd_logout(args):
    cfg = config.load()
    email = cfg.pop('email', None)
    config.save(cfg)
    clear_session()
    print(f'  ✓ Logged out ({email})' if email else '  (already anonymous)')