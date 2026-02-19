"""
File drop API calls.
"""

import os

import requests as _requests

from .auth import get_csrf
from .helpers import err


def upload_file(host, session, filepath, key=None):
    """
    Upload a file.
    Returns the key string on success, None on failure.
    """
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
        _handle_error(res, 'Upload failed')
    except Exception as e:
        err(f'Upload error: {e}')
    return None


def get_file(host, session, key):
    """
    Fetch a file drop.
    Returns ('file', (bytes, filename)) or (None, None).
    """
    try:
        res = session.get(
            f'{host}/f/{key}/',
            headers={'Accept': 'application/json'},
            timeout=30,
        )
        if not res.ok:
            _handle_http_error(res, key)
            return None, None

        data = res.json()
        if data.get('kind') != 'file':
            err(f'/f/{key}/ is not a file drop.')
            return None, None

        download_url = f'{host}{data["download"]}'
        dl = session.get(download_url, timeout=120, allow_redirects=True)
        if not dl.ok:
            # CDN redirect may not work with authenticated session — try bare
            dl = _requests.get(download_url, timeout=120, allow_redirects=True)

        if dl.ok:
            return 'file', (dl.content, data.get('filename', key))

        err(f'File download failed (HTTP {dl.status_code}).')
    except Exception as e:
        err(f'Get error: {e}')
    return None, None


def _handle_error(res, prefix):
    try:
        msg = res.json().get('error', res.text[:200])
    except Exception:
        msg = res.text[:200]
    err(f'{prefix}: {msg}')


def _handle_http_error(res, key):
    if res.status_code == 404:
        err(f'File /f/{key}/ not found.')
    elif res.status_code == 410:
        err(f'File /f/{key}/ has expired.')
    else:
        err(f'Server returned {res.status_code}.')