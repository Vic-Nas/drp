"""
integration_tests/core/test_api_auth.py
Tests for cli/api/auth.py: get_csrf and login.
"""
import requests
import pytest
from conftest import HOST
from cli.api.auth import get_csrf, login


class TestGetCsrf:
    def test_returns_nonempty_string(self):
        s = requests.Session()
        assert len(get_csrf(HOST, s)) > 0

    def test_sets_csrftoken_cookie(self):
        s = requests.Session()
        get_csrf(HOST, s)
        assert 'csrftoken' in [c.name for c in s.cookies]

    def test_idempotent(self):
        s = requests.Session()
        assert get_csrf(HOST, s) == get_csrf(HOST, s)


class TestLogin:
    def test_valid_credentials(self, free_user):
        s = requests.Session()
        assert login(HOST, s, free_user.email, free_user.password) is True

    def test_sets_sessionid_cookie(self, free_user):
        s = requests.Session()
        login(HOST, s, free_user.email, free_user.password)
        assert 'sessionid' in [c.name for c in s.cookies]

    def test_wrong_password_returns_false(self, free_user):
        s = requests.Session()
        assert login(HOST, s, free_user.email, 'wrong-password-xyz') is False

    def test_unknown_email_returns_false(self):
        s = requests.Session()
        assert login(HOST, s, 'nobody@nowhere-xyz.invalid', 'pass') is False
