"""
Session persistence for the drp CLI.
Saves/loads cookies so users aren't prompted for a password on every command.
"""

import getpass
import json
import sys

from cli import config, api

SESSION_FILE = config.CONFIG_DIR / 'session.json'


def load_session(session):
    """Load saved cookies into session. Silent — never prompts."""
    if SESSION_FILE.exists():
        try:
            session.cookies.update(json.loads(SESSION_FILE.read_text()))
        except Exception:
            pass


def save_session(session):
    """Persist session cookies to disk."""
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(dict(session.cookies)) + '\n')


def clear_session():
    """Delete saved session."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def auto_login(cfg, host, session, required=False):
    """
    Load saved session and verify it's still valid.
    If expired, prompt for password once and re-save.
    Returns True if authenticated, False if anonymous.
    """
    email = cfg.get('email')
    if not email:
        return False

    load_session(session)

    try:
        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=10,
            allow_redirects=False,
        )
        if res.status_code == 200:
            return True
    except Exception as e:
        print(f'  ✗ Could not reach {host}: {e}')
        if required:
            sys.exit(1)
        return False

    # Session expired — prompt once
    try:
        password = getpass.getpass(f'  Session expired. Password for {email}: ')
    except (KeyboardInterrupt, EOFError):
        print()
        if required:
            sys.exit(1)
        return False

    try:
        if api.login(host, session, email, password):
            save_session(session)
            return True
    except Exception as e:
        print(f'  ✗ Login error: {e}')

    print('  ✗ Login failed. Continuing as anonymous.')
    if required:
        sys.exit(1)
    return False