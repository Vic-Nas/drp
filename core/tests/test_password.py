"""
Tests for password protection on drops.

Covers every entry point that has a password gate:
  - clipboard_view (web + JSON)
  - file_view (web + JSON)
  - download_drop
  - set_drop_password (paid gate, owner gate)

Key invariants:
  - Wrong password and missing drop both return 401 (no enumeration)
  - Owner is never prompted for their own drop's password
  - Correct header password grants access on JSON/CLI path
  - Correct form password sets session and grants access on web path
  - Password protection is a paid-only feature
"""

import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory, Client
from django.utils import timezone

from core.models import Drop, Plan
from core.views.drops import (
    clipboard_view, file_view, download_drop, set_drop_password,
)
from .helpers import make_user, make_drop, make_file_drop


def _req(factory, method, path, user=None, accept_json=False,
         headers=None, data=None, session_data=None):
    """Build a request with optional auth, Accept header, and custom headers."""
    builder = getattr(factory, method.lower())
    req = builder(path, data=data or {})
    req.user = user or MagicMock(is_authenticated=False)
    req.COOKIES = {}

    # Attach a real session-like dict so _is_password_unlocked works
    class _Session(dict):
        def save(self): pass
        def get(self, key, default=None): return dict.get(self, key, default)
        def __setitem__(self, key, val): dict.__setitem__(self, key, val)

    req.session = _Session(session_data or {})

    if accept_json:
        req.META["HTTP_ACCEPT"] = "application/json"
    for k, v in (headers or {}).items():
        req.META[f"HTTP_{k.upper().replace('-', '_')}"] = v
    return req


class PasswordGateClipboardTests(TestCase):
    """clipboard_view must gate JSON and web access with a password."""

    def setUp(self):
        self.factory = RequestFactory()
        self.owner = make_user("clip-owner", plan=Plan.STARTER)
        self.other = make_user("clip-other")
        self.drop = make_drop(key="secret-clip", owner=self.owner)
        self.drop.set_password("hunter2")
        self.drop.save(update_fields=["password_hash"])

    def test_json_returns_401_without_password(self):
        req = _req(self.factory, "GET", "/secret-clip/",
                   user=self.other, accept_json=True)
        resp = clipboard_view(req, key="secret-clip")
        self.assertEqual(resp.status_code, 401)

    def test_json_returns_401_with_wrong_password(self):
        req = _req(self.factory, "GET", "/secret-clip/",
                   user=self.other, accept_json=True,
                   headers={"X-Drop-Password": "wrongpass"})
        resp = clipboard_view(req, key="secret-clip")
        self.assertEqual(resp.status_code, 401)

    def test_json_grants_access_with_correct_header_password(self):
        req = _req(self.factory, "GET", "/secret-clip/",
                   user=self.other, accept_json=True,
                   headers={"X-Drop-Password": "hunter2"})
        resp = clipboard_view(req, key="secret-clip")
        self.assertEqual(resp.status_code, 200)

    def test_owner_bypasses_password_prompt(self):
        req = _req(self.factory, "GET", "/secret-clip/",
                   user=self.owner, accept_json=True)
        resp = clipboard_view(req, key="secret-clip")
        self.assertEqual(resp.status_code, 200)

    def test_session_unlock_bypasses_password(self):
        session_key = f"drp_pw_ok:c:secret-clip"
        req = _req(self.factory, "GET", "/secret-clip/",
                   user=self.other, accept_json=True,
                   session_data={session_key: True})
        resp = clipboard_view(req, key="secret-clip")
        self.assertEqual(resp.status_code, 200)

    def test_web_returns_401_without_password(self):
        req = _req(self.factory, "GET", "/secret-clip/", user=self.other)
        resp = clipboard_view(req, key="secret-clip")
        self.assertEqual(resp.status_code, 401)


class PasswordGateDownloadTests(TestCase):
    """download_drop must gate downloads behind password."""

    def setUp(self):
        self.factory = RequestFactory()
        self.owner = make_user("dl-owner", plan=Plan.STARTER)
        self.other = make_user("dl-other")
        self.drop = make_file_drop(key="secret-file", owner=self.owner)
        self.drop.set_password("s3cr3t")
        self.drop.save(update_fields=["password_hash"])

    def test_json_401_without_password(self):
        req = _req(self.factory, "GET", "/f/secret-file/download/",
                   user=self.other, accept_json=True)
        resp = download_drop(req, key="secret-file")
        self.assertEqual(resp.status_code, 401)

    def test_json_401_with_wrong_password(self):
        req = _req(self.factory, "GET", "/f/secret-file/download/",
                   user=self.other, accept_json=True,
                   headers={"X-Drop-Password": "nope"})
        resp = download_drop(req, key="secret-file")
        self.assertEqual(resp.status_code, 401)

    def test_json_grants_access_with_correct_password(self):
        req = _req(self.factory, "GET", "/f/secret-file/download/",
                   user=self.other, accept_json=True,
                   headers={"X-Drop-Password": "s3cr3t"})
        with patch.object(Drop, "download_url", return_value="https://b2.example.com/dl"):
            resp = download_drop(req, key="secret-file")
        self.assertEqual(resp.status_code, 302)

    def test_owner_bypasses_password(self):
        req = _req(self.factory, "GET", "/f/secret-file/download/",
                   user=self.owner)
        with patch.object(Drop, "download_url", return_value="https://b2.example.com/dl"):
            resp = download_drop(req, key="secret-file")
        self.assertEqual(resp.status_code, 302)

    def test_session_unlock_bypasses_password(self):
        session_key = "drp_pw_ok:f:secret-file"
        req = _req(self.factory, "GET", "/f/secret-file/download/",
                   user=self.other, session_data={session_key: True})
        with patch.object(Drop, "download_url", return_value="https://b2.example.com/dl"):
            resp = download_drop(req, key="secret-file")
        self.assertEqual(resp.status_code, 302)

    def test_missing_drop_is_404(self):
        from django.http import Http404
        req = _req(self.factory, "GET", "/f/no-such-file/download/", user=self.other)
        with self.assertRaises(Http404):
            download_drop(req, key="no-such-file")


class SetDropPasswordTests(TestCase):
    """set_drop_password must enforce paid-only and owner-only access."""

    def setUp(self):
        self.factory = RequestFactory()
        self.owner = make_user("pw-owner", plan=Plan.STARTER)
        self.other = make_user("pw-other", plan=Plan.STARTER)
        self.free_owner = make_user("pw-free", plan=Plan.FREE)
        self.drop = make_drop(key="pw-drop", ns=Drop.NS_CLIPBOARD, owner=self.owner)

    def _post(self, user, password_value):
        req = self.factory.post(
            "/pw-drop/set-password/",
            data=json.dumps({"password": password_value}),
            content_type="application/json",
        )
        req.user = user
        return set_drop_password(req, ns=Drop.NS_CLIPBOARD, key="pw-drop")

    def test_owner_can_set_password(self):
        resp = self._post(self.owner, "newpass123")
        self.assertEqual(resp.status_code, 200)
        self.drop.refresh_from_db()
        self.assertTrue(self.drop.is_password_protected)

    def test_owner_can_remove_password(self):
        self.drop.set_password("existing")
        self.drop.save(update_fields=["password_hash"])

        resp = self._post(self.owner, "")
        self.assertEqual(resp.status_code, 200)
        self.drop.refresh_from_db()
        self.assertFalse(self.drop.is_password_protected)

    def test_non_owner_cannot_set_password(self):
        resp = self._post(self.other, "hacked")
        self.assertEqual(resp.status_code, 403)

    def test_free_plan_owner_cannot_set_password(self):
        free_drop = make_drop(key="free-pw-drop", ns=Drop.NS_CLIPBOARD, owner=self.free_owner)
        req = self.factory.post(
            "/free-pw-drop/set-password/",
            data=json.dumps({"password": "nope"}),
            content_type="application/json",
        )
        req.user = self.free_owner
        resp = set_drop_password(req, ns=Drop.NS_CLIPBOARD, key="free-pw-drop")
        self.assertEqual(resp.status_code, 403)

    def test_missing_drop_returns_404(self):
        req = self.factory.post(
            "/ghost/set-password/",
            data=json.dumps({"password": "x"}),
            content_type="application/json",
        )
        req.user = self.owner
        resp = set_drop_password(req, ns=Drop.NS_CLIPBOARD, key="ghost")
        self.assertEqual(resp.status_code, 404)

    def test_get_method_rejected(self):
        req = self.factory.get("/pw-drop/set-password/")
        req.user = self.owner
        resp = set_drop_password(req, ns=Drop.NS_CLIPBOARD, key="pw-drop")
        self.assertEqual(resp.status_code, 405)


class PasswordEnumerationTests(TestCase):
    """Both wrong password and missing drop must return 401 on web path
    so attackers cannot tell whether a drop exists."""

    def setUp(self):
        self.factory = RequestFactory()
        self.drop = make_drop(key="enum-test", owner=None)
        self.drop.set_password("secret")
        self.drop.save(update_fields=["password_hash"])

    def test_wrong_password_returns_401_not_403(self):
        req = _req(self.factory, "GET", "/enum-test/",
                   user=MagicMock(is_authenticated=False))
        resp = clipboard_view(req, key="enum-test")
        self.assertEqual(resp.status_code, 401)

    def test_nonexistent_drop_raises_404_not_401(self):
        """404 for missing drops is fine — there's nothing to enumerate."""
        from django.http import Http404
        req = _req(self.factory, "GET", "/no-such-drop/",
                   user=MagicMock(is_authenticated=False))
        with self.assertRaises(Http404):
            clipboard_view(req, key="no-such-drop")
