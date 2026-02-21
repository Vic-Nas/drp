"""
integration_tests/conftest.py

Reads your existing .env — no new env vars, no extra files.

  Host   → derived from DOMAIN (DEBUG=True → localhost:8000)
  Email/password → prompted once at session start (credentials live in
                   the DB, not the env, so there's nowhere else to read them)

Isolation:
  - All test keys are prefixed drptest- and deleted at session end.
  - Isolated /tmp/ config dir — ~/.config/drp/ is never touched.
  - Safe against production DB: only the test account's drops are affected.
"""

import getpass
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

import pytest
import requests

# ── Load .env ─────────────────────────────────────────────────────────────────

def _load_dotenv(path):
    p = Path(path)
    if not p.exists():
        return {}
    vals = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals

_ROOT = Path(__file__).parent.parent
_env  = _load_dotenv(_ROOT / '.env')

def _get(key, default=None):
    return _env.get(key) or os.environ.get(key) or default

# ── Host (from existing DOMAIN / DEBUG vars) ──────────────────────────────────

def _resolve_host():
    domain = _get('DOMAIN', '').rstrip('/')
    debug  = _get('DEBUG', 'False').lower() in ('1', 'true', 'yes')
    if debug or not domain:
        return 'http://localhost:8000'
    return f'https://{domain}'

HOST = _resolve_host()

# ── Credentials (prompted once — they live in the DB, not the env) ────────────

print(f'\n  drp integration tests → {HOST}')
EMAIL    = input('  Test account email: ').strip()
PASSWORD = getpass.getpass('  Test account password: ')

if not EMAIL or not PASSWORD:
    pytest.exit('Email and password are required.', returncode=2)

# ── Key helpers ───────────────────────────────────────────────────────────────

PREFIX = 'drptest-'

def unique_key(label=''):
    suffix = secrets.token_urlsafe(6)
    return f'{PREFIX}{label}-{suffix}' if label else f'{PREFIX}{suffix}'

# ── Isolated config dir ───────────────────────────────────────────────────────

@pytest.fixture(scope='session')
def config_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp('drp-integration')
    drp_dir = d / 'drp'
    drp_dir.mkdir()
    yield drp_dir
    shutil.rmtree(d, ignore_errors=True)

@pytest.fixture(scope='session')
def drp_config(config_dir):
    cfg = {'host': HOST, 'email': EMAIL, 'ansi': False}
    (config_dir / 'config.json').write_text(json.dumps(cfg))
    return cfg

# ── Authenticated requests.Session ───────────────────────────────────────────

@pytest.fixture(scope='session')
def drp_session(drp_config, config_dir):
    from cli.api.auth import login as api_login
    session = requests.Session()
    if not api_login(HOST, session, EMAIL, PASSWORD):
        pytest.exit(f'Login failed for {EMAIL} on {HOST}.', returncode=2)
    (config_dir / 'session.json').write_text(json.dumps(dict(session.cookies)))
    yield session

# ── CLI environment ───────────────────────────────────────────────────────────

@pytest.fixture(scope='session')
def cli_env(config_dir, drp_session, drp_config):
    env = os.environ.copy()
    env['XDG_CONFIG_HOME'] = str(config_dir.parent)
    env['NO_COLOR'] = '1'
    return env

def run_drp(*args, input=None, env=None, check=False):
    result = subprocess.run(
        ['drp', *args], input=input, capture_output=True, text=True, env=env,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f'drp {" ".join(args)} exited {result.returncode}\n'
            f'stdout: {result.stdout}\nstderr: {result.stderr}'
        )
    return result

# ── Key tracker & cleanup ─────────────────────────────────────────────────────

class KeyTracker:
    def __init__(self, session, host):
        self._session = session
        self._host    = host
        self._keys    = []

    def add(self, key, ns='c'):
        self._keys.append((ns, key))
        return key

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
            print(f'\n[tracker] WARNING: could not delete {len(failed)} key(s): {failed}')

@pytest.fixture(scope='session')
def tracker(drp_session):
    t = KeyTracker(drp_session, HOST)
    yield t
    t.cleanup()

@pytest.fixture
def track(tracker):
    return tracker.add

# ── Expose constants ──────────────────────────────────────────────────────────

@pytest.fixture(scope='session')
def host():
    return HOST

@pytest.fixture(scope='session')
def credentials():
    return {'email': EMAIL, 'password': PASSWORD}
