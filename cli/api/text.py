"""
Clipboard (text) drop API calls.
"""

from .auth import get_csrf
from .helpers import err


def upload_text(host, session, text, key=None):
    """
    Upload text content.
    Returns the key string on success, None on failure.
    """
    csrf = get_csrf(host, session)
    data = {'content': text, 'csrfmiddlewaretoken': csrf}
    if key:
        data['key'] = key
    try:
        res = session.post(f'{host}/save/', data=data, timeout=30)
        if res.ok:
            return res.json().get('key')
        _handle_error(res, 'Upload failed')
    except Exception as e:
        err(f'Upload error: {e}')
    return None


def get_clipboard(host, session, key):
    """
    Fetch a clipboard drop.
    Returns (kind='text', content_str) or (None, None).
    """
    try:
        res = session.get(
            f'{host}/{key}/',
            headers={'Accept': 'application/json'},
            timeout=30,
        )
        if res.ok:
            data = res.json()
            if data.get('kind') == 'text':
                return 'text', data.get('content', '')
            # Key exists but is a file — caller should try get_file
            return None, None
        _handle_http_error(res, key)
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
        err(f'Drop /{key}/ not found.')
    elif res.status_code == 410:
        err(f'Drop /{key}/ has expired.')
    else:
        err(f'Server returned {res.status_code}.')