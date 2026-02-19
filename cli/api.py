"""
HTTP helpers for the drp CLI.

All server communication lives here: CSRF, login, upload, download, delete,
and key-existence checks.
"""

import os
import secrets
import requests
from pathlib import Path


def get_csrf(host, session):
    """Hit the home page to pick up the csrftoken cookie."""
    session.get(f'{host}/', timeout=10)
    return session.cookies.get('csrftoken', '')


def login(host, session, email, password):
    """Authenticate with the drp server. Returns True on success."""
    csrf = get_csrf(host, session)
    res = session.post(
        f'{host}/auth/login/',
        data={'email': email, 'password': password, 'csrfmiddlewaretoken': csrf},
        timeout=10,
        allow_redirects=False,
    )
    return res.status_code in (302, 301)


def upload_text(host, session, text, key=None):
    """Upload text content. Returns the key on success, None on failure."""
    csrf = get_csrf(host, session)
    data = {'content': text, 'csrfmiddlewaretoken': csrf}
    if key:
        data['key'] = key
    try:
        res = session.post(f'{host}/save/', data=data, timeout=30)
        if res.ok:
            return res.json().get('key')
        else:
            _err(f'upload failed: {res.text[:200]}')
    except Exception as e:
        _err(f'upload error: {e}')
    return None


def upload_file(host, session, filepath, key=None):
    """Upload a file. Returns the key on success, None on failure."""
    csrf = get_csrf(host, session)
    data = {'csrfmiddlewaretoken': csrf}
    if key:
        data['key'] = key
    try:
        with open(filepath, 'rb') as f:
            res = session.post(
                f'{host}/save/',
                files={'file': (os.path.basename(filepath), f)},
                data=data,
                timeout=120,
            )
        if res.ok:
            return res.json().get('key')
        else:
            _err(f'upload failed: {res.text[:200]}')
    except Exception as e:
        _err(f'upload error: {e}')
    return None


def get_drop(host, session, key):
    """
    Fetch a drop's content via the JSON API.
    Returns (kind, content) where kind is 'text' or 'file'.
    For text drops, content is the string.
    For file drops, content is (bytes, filename).
    Returns (None, None) on failure.
    """
    try:
        res = session.get(
            f'{host}/{key}/',
            headers={'Accept': 'application/json'},
            timeout=30,
        )
        if not res.ok:
            if res.status_code == 410:
                _err('drop has expired')
            elif res.status_code == 404:
                _err('drop not found')
            else:
                _err(f'server returned {res.status_code}')
            return None, None

        data = res.json()
        if data.get('kind') == 'text':
            return 'text', data.get('content', '')

        # File drop — follow the download redirect
        dl = session.get(
            f'{host}{data["download"]}',
            timeout=120,
            allow_redirects=True,
        )
        if dl.ok:
            filename = data.get('filename', key)
            return 'file', (dl.content, filename)

        _err('failed to download file')
        return None, None
    except Exception as e:
        _err(f'get error: {e}')
        return None, None


def delete(host, session, key):
    """Delete a drop. Returns True on success."""
    csrf = get_csrf(host, session)
    try:
        res = session.delete(
            f'{host}/{key}/delete/',
            headers={'X-CSRFToken': csrf},
            timeout=10,
        )
        return res.ok
    except Exception:
        return False


def rename(host, session, key, new_key):
    """Rename a drop's key. Returns the new key on success, None on failure."""
    csrf = get_csrf(host, session)
    try:
        res = session.post(
            f'{host}/{key}/rename/',
            data={'new_key': new_key, 'csrfmiddlewaretoken': csrf},
            timeout=10,
        )
        if res.ok:
            return res.json().get('key')
        _err(res.json().get('error', 'rename failed'))
    except Exception as e:
        _err(f'rename error: {e}')
    return None


def renew(host, session, key):
    """Renew a drop's expiry. Returns (expires_at, renewals) on success."""
    csrf = get_csrf(host, session)
    try:
        res = session.post(
            f'{host}/{key}/renew/',
            data={'csrfmiddlewaretoken': csrf},
            timeout=10,
        )
        if res.ok:
            data = res.json()
            return data.get('expires_at'), data.get('renewals')
        _err(res.json().get('error', 'renew failed'))
    except Exception as e:
        _err(f'renew error: {e}')
    return None, None


def list_drops(host, session):
    """List the logged-in user's drops. Returns list of dicts or None."""
    try:
        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=15,
        )
        if res.ok:
            return res.json().get('drops', [])
        if res.status_code == 302:
            _err('not logged in')
        else:
            _err(f'server returned {res.status_code}')
    except Exception as e:
        _err(f'list error: {e}')
    return None


def key_exists(host, session, key):
    """Return True if the key exists on the server."""
    try:
        res = session.get(f'{host}/check-key/', params={'key': key}, timeout=10)
        if res.ok:
            return not res.json().get('available', True)
    except Exception:
        pass
    return False


def slug(name):
    """Turn a filename into a url-safe slug (max 40 chars)."""
    stem = Path(name).stem
    safe = ''.join(c if c.isalnum() or c in '-_' else '-' for c in stem).strip('-')
    return safe[:40] or secrets.token_urlsafe(6)


def _err(msg):
    """Print an error message."""
    import sys
    print(f'  ✗ {msg}', file=sys.stderr)
