"""
integration_tests/core/test_api_auth.py

Tests for cli/api/auth.py: get_csrf and login.
No mocks — hits the real server.
"""

import requests
import pytest

from conftest import HOST, EMAIL, PASSWORD
from cli.api.auth import get_csrf, login


class TestGetCsrf:
    def test_returns_nonempty_string(self):
        session = requests.Session()
        token = get_csrf(HOST, session)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_idempotent_when_cookie_already_present(self):
        session = requests.Session()
        token1 = get_csrf(HOST, session)
        token2 = get_csrf(HOST, session)
        # Should return the same token without a second network call
        assert token1 == token2

    def test_sets_cookie_on_session(self):
        session = requests.Session()
        get_csrf(HOST, session)
        names = [c.name for c in session.cookies]
        assert 'csrftoken' in names


class TestLogin:
    def test_valid_credentials_returns_true(self):
        session = requests.Session()
        result = login(HOST, session, EMAIL, PASSWORD)
        assert result is True

    def test_valid_credentials_sets_session_cookie(self):
        session = requests.Session()
        login(HOST, session, EMAIL, PASSWORD)
        names = [c.name for c in session.cookies]
        assert 'sessionid' in names

    def test_wrong_password_returns_false(self):
        session = requests.Session()
        result = login(HOST, session, EMAIL, 'definitely-wrong-password-xyz')
        assert result is False

    def test_wrong_email_returns_false(self):
        session = requests.Session()
        result = login(HOST, session, 'nobody@nowhere-xyz.invalid', 'pass')
        assert result is False
