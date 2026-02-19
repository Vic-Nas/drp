"""
Drop action API calls: delete, rename, renew, list, key_exists.

URL conventions:
  Clipboard:  /key/delete|rename|renew/
  File:       /f/key/delete|rename|renew/
"""

from .auth import get_csrf
from .helpers import err


def _url(host, ns, key, action):
    if ns == 'f':
        return f'{host}/f/{key}/{action}/'
    return f'{host}/{key}/{action}/'


def delete(host, session, key, ns='c'):
    """
    Delete a drop.
    Returns True on success or if already gone (idempotent).
    """
    csrf = get_csrf(host, session)
    try:
        res = session.delete(
            _url(host, ns, key, 'delete'),
            headers={'X-CSRFToken': csrf},
            timeout=10,
        )
        if res.ok:
            return True
        if res.status_code == 404:
            # Already gone — treat as success
            return True
        _handle_error(res, 'Delete failed')
    except Exception as e:
        err(f'Delete error: {e}')
    return False


def rename(host, session, key, new_key, ns='c'):
    """
    Rename a drop's key.
    Returns the new key string on success, None on failure.
    """
    csrf = get_csrf(host, session)
    try:
        res = session.post(
            _url(host, ns, key, 'rename'),
            data={'new_key': new_key, 'csrfmiddlewaretoken': csrf},
            timeout=10,
        )
        if res.ok:
            return res.json().get('key')
        _handle_error(res, 'Rename failed')
    except Exception as e:
        err(f'Rename error: {e}')
    return None


def renew(host, session, key, ns='c'):
    """
    Renew a drop's expiry.
    Returns (expires_at_str, renewal_count) on success, (None, None) on failure.
    """
    csrf = get_csrf(host, session)
    try:
        res = session.post(
            _url(host, ns, key, 'renew'),
            data={'csrfmiddlewaretoken': csrf},
            timeout=10,
        )
        if res.ok:
            data = res.json()
            return data.get('expires_at'), data.get('renewals')
        _handle_error(res, 'Renew failed')
    except Exception as e:
        err(f'Renew error: {e}')
    return None, None


def list_drops(host, session):
    """
    List the logged-in user's drops.
    Returns list of dicts on success, None if not authenticated.
    """
    try:
        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=15,
        )
        if res.ok:
            return res.json().get('drops', [])
        if res.status_code in (302, 403):
            return None  # Not logged in
        err(f'Server returned {res.status_code}.')
    except Exception as e:
        err(f'List error: {e}')
    return None


def key_exists(host, session, key, ns='c'):
    """Return True if the key exists on the server in the given namespace."""
    try:
        res = session.get(
            f'{host}/check-key/',
            params={'key': key, 'ns': ns},
            timeout=10,
        )
        if res.ok:
            return not res.json().get('available', True)
    except Exception:
        pass
    return False


def _handle_error(res, prefix):
    try:
        msg = res.json().get('error', res.text[:200])
    except Exception:
        msg = res.text[:200]
    err(f'{prefix}: {msg}')