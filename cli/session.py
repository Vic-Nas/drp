"""
Session persistence for the drp CLI.
Saves/loads cookies so users aren't prompted for a password on every command.
"""

import getpass
import json
import sys
import time

from cli import config, api

SESSION_FILE = config.CONFIG_DIR / 'session.json'

# If the session file was written within this many seconds, trust it without
# hitting the server to validate. Avoids a full Railway round-trip on every
# command. When the session does expire, the next real API call returns 302
# which auto_login already handles by re-prompting.
SESSION_CACHE_SECS = 300  # 5 minutes


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
    # mtime is now the authoritative freshness timestamp used by auto_login


def clear_session():
    """Delete saved session."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def _session_is_fresh() -> bool:
    """
    Return True if the session file exists and was written recently enough
    that we can trust it without a server ping.
    """
    try:
        if not SESSION_FILE.exists():
            return False
        age = time.time() - SESSION_FILE.stat().st_mtime
        return age < SESSION_CACHE_SECS
    except Exception:
        return False


def auto_login(cfg, host, session, required=False):
    """
    Load saved session and verify it's still valid.

    If the session file is fresh (written within SESSION_CACHE_SECS), skip the
    validation ping entirely — the saved cookies are loaded and we return True
    immediately. This avoids a Railway round-trip on every CLI invocation.

    If the session is stale or absent, ping /auth/account/ to confirm validity.
    If that returns non-200 (expired), prompt for password once and re-save.

    Returns True if authenticated, False if anonymous.
    """
    email = cfg.get('email')
    if not email:
        return False

    load_session(session)

    # Fast path: session file is recent — trust it without a network call.
    if _session_is_fresh():
        return True

    # Slow path: validate with the server.
    try:
        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=10,
            allow_redirects=False,
        )
        if res.status_code == 200:
            # Touch the session file so the next call hits the fast path.
            SESSION_FILE.touch()
            return True
    except Exception as e:
        print(f'  ✗ Could not reach {host}: {e}')
        if required:
            sys.exit(1)
        return False

    # Session expired — prompt once.
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