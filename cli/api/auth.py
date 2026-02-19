"""
Authentication helpers: CSRF token fetching and login.
"""

from .helpers import err


def get_csrf(host, session):
    """Hit the home page to pick up the csrftoken cookie."""
    # Clear any stale csrftoken first — duplicate cookies cause requests to error
    session.cookies.clear(domain=None, path='/', name='csrftoken')
    session.get(f'{host}/', timeout=10)
    return session.cookies.get('csrftoken', '')


def login(host, session, email, password):
    """
    Authenticate with the drp server.
    Returns True on success, False on bad credentials.
    Raises requests.RequestException on network errors.
    """
    csrf = get_csrf(host, session)
    res = session.post(
        f'{host}/auth/login/',
        data={'email': email, 'password': password, 'csrfmiddlewaretoken': csrf},
        timeout=10,
        allow_redirects=False,
    )
    return res.status_code in (301, 302)