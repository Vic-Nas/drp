"""
integration_tests/conftest.py

Shared fixtures for the full integration test suite.

Key design decisions:
  - .env is loaded once; missing vars raise at collection time with a clear message.
  - Each test session gets a fresh throwaway config dir so the user's real
    ~/.config/drp/ is never read or written.
  - The `drp_session` fixture gives a logged-in requests.Session pointed at the
    test host — used by core/ tests directly.
  - The `cli_env` fixture gives a dict of environment variables for subprocess
    calls that overrides XDG_CONFIG_HOME so the CLI binary also uses the
    throwaway config dir.
  - `track` is a session-scoped key registry. Tests register every key they
    create; a session-scoped finalizer deletes them all even if tests fail.
  - All keys use the prefix drptest- so they are identifiable and can be
    bulk-wiped manually if a run is aborted.
"""

import json
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import requests

# ── Load .env ─────────────────────────────────────────────────────────────────

def _load_env():
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        try:
            from dotenv import dotenv_values
            return dotenv_values(env_path)
        except ImportError:
            # Parse manually if python-dotenv not installed
            vals = {}
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    vals[k.strip()] = v.strip().strip('"').strip("'")
            return vals
    return {}

_env = _load_env()

def _require(key, default=None):
    val = _env.get(key) or os.environ.get(key) or default
    if not val:
        pytest.exit(
            f'\n\nMissing required env var: {key}\n'
            f'Set it in .env or export it before running integration tests.\n',
            returncode=2,
        )
    return val

HOST     = _require('DRP_TEST_HOST', default='https://drp.vicnas.me')
EMAIL    = _require('DRP_TEST_EMAIL')
PASSWORD = _require('DRP_TEST_PASSWORD')

# Strip trailing slash
HOST = HOST.rstrip('/')


# ── Key helpers ───────────────────────────────────────────────────────────────

PREFIX = 'drptest-'

def unique_key(label=''):
    """Generate a unique drptest- prefixed key safe to use as a drop key."""
    suffix = secrets.token_urlsafe(6)
    if label:
        return f'{PREFIX}{label}-{suffix}'
    return f'{PREFIX}{suffix}'


# ── Isolated config dir ───────────────────────────────────────────────────────

@pytest.fixture(scope='session')
def config_dir(tmp_path_factory):
    """
    A throwaway config directory for the whole test session.
    The CLI is pointed here via XDG_CONFIG_HOME so ~/.config/drp is never touched.
    """
    d = tmp_path_factory.mktemp('drp-integration')
    drp_dir = d / 'drp'
    drp_dir.mkdir()
    yield drp_dir
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope='session')
def drp_config(config_dir):
    """Write a minimal drp config.json pointing at the test host."""
    cfg = {'host': HOST, 'email': EMAIL, 'ansi': False}
    (config_dir / 'config.json').write_text(json.dumps(cfg))
    return cfg


# ── Authenticated requests.Session ────────────────────────────────────────────

@pytest.fixture(scope='session')
def drp_session(drp_config, config_dir):
    """
    A logged-in requests.Session for direct API calls (core/ tests).
    Session cookies are saved to the throwaway config dir.
    """
    from cli.api.auth import get_csrf, login as api_login

    session = requests.Session()
    ok = api_login(HOST, session, EMAIL, PASSWORD)
    if not ok:
        pytest.exit(
            f'\n\nCould not log in to {HOST} as {EMAIL}.\n'
            f'Check DRP_TEST_EMAIL / DRP_TEST_PASSWORD in .env.\n',
            returncode=2,
        )
    # Persist cookies so subsequent fixture uses are fast
    cookies_file = config_dir / 'session.json'
    cookies_file.write_text(json.dumps(dict(session.cookies)))
    yield session


# ── CLI environment ───────────────────────────────────────────────────────────

@pytest.fixture(scope='session')
def cli_env(config_dir, drp_session, drp_config):
    """
    Environment dict for subprocess CLI calls.
    Overrides XDG_CONFIG_HOME so the drp binary uses our throwaway config dir,
    not the user's ~/.config/drp/.

    Also writes the session cookies so the CLI is pre-logged-in.
    """
    # Write cookies from the API session into the CLI's expected session.json
    session_file = config_dir / 'session.json'
    # drp_session fixture already wrote them; just verify
    assert session_file.exists(), 'session.json missing — login fixture failed'

    env = os.environ.copy()
    # drp reads config from $XDG_CONFIG_HOME/drp/ (falls back to ~/.config/drp/)
    env['XDG_CONFIG_HOME'] = str(config_dir.parent)
    env['NO_COLOR'] = '1'        # deterministic output, no ANSI escape codes
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def run_drp(*args, input=None, env=None, check=False):
    """
    Run `drp <args>` as a subprocess.
    Returns CompletedProcess with .stdout, .stderr, .returncode.
    """
    cmd = ['drp', *args]
    result = subprocess.run(
        cmd,
        input=input,
        capture_output=True,
        text=True,
        env=env,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f'drp {" ".join(args)} exited {result.returncode}\n'
            f'stdout: {result.stdout}\nstderr: {result.stderr}'
        )
    return result


# ── Key tracker & cleanup ─────────────────────────────────────────────────────

class KeyTracker:
    """
    Registry of (ns, key) pairs created during a test session.
    Call tracker.add(key) or tracker.add(key, ns='f') after each creation.
    The session finalizer deletes everything registered here.
    """

    def __init__(self, session, host):
        self._session = session
        self._host = host
        self._keys = []   # list of (ns, key)

    def add(self, key, ns='c'):
        self._keys.append((ns, key))
        return key  # pass-through for convenience

    def cleanup(self):
        from cli.api.actions import delete
        failed = []
        for ns, key in self._keys:
            try:
                delete(self._host, self._session, key, ns=ns)
            except Exception:
                failed.append((ns, key))
        self._keys.clear()
        if failed:
            print(f'\n[tracker] WARNING: could not delete {len(failed)} test key(s): {failed}')


@pytest.fixture(scope='session')
def tracker(drp_session):
    t = KeyTracker(drp_session, HOST)
    yield t
    t.cleanup()


# ── Per-test key cleanup via autouse ─────────────────────────────────────────

@pytest.fixture
def track(tracker):
    """
    Per-test convenience: returns tracker.add so tests can do:
        key = track(unique_key('label'), ns='c')
    Keys added here are cleaned up at session end by the tracker finalizer.
    """
    return tracker.add


# ── Expose constants to all tests ─────────────────────────────────────────────

@pytest.fixture(scope='session')
def host():
    return HOST

@pytest.fixture(scope='session')
def credentials():
    return {'email': EMAIL, 'password': PASSWORD}
