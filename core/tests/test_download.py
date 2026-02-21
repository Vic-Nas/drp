"""
Tests for the download_drop view.

The download endpoint must 302-redirect to a presigned URL.
If it ever proxied bytes through Django, Railway's 30s timeout would fire.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.http import Http404
from django.test import TestCase, RequestFactory
from django.utils import timezone

from core.models import Drop
from core.views.drops import download_drop
from .helpers import make_file_drop


class DropDownloadViewTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.drop = make_file_drop(key="dl-drop")

    def _get(self, key="dl-drop", user=None):
        req = self.factory.get(f"/f/{key}/download/")
        req.user = user or MagicMock(is_authenticated=False)
        req.COOKIES = {}
        req.session = {}
        return download_drop(req, key=key)

    def test_returns_302(self):
        with patch.object(Drop, "download_url", return_value="https://b2.example.com/presigned"):
            resp = self._get()
        self.assertEqual(resp.status_code, 302)

    def test_redirects_to_presigned_url(self):
        fake_url = "https://b2.example.com/presigned?sig=abc"
        with patch.object(Drop, "download_url", return_value=fake_url):
            resp = self._get()
        self.assertEqual(resp["Location"], fake_url)

    def test_404_for_missing_drop(self):
        with self.assertRaises(Http404):
            self._get(key="nope")

    def test_404_for_expired_drop(self):
        self.drop.expires_at = timezone.now() - timedelta(seconds=1)
        self.drop.save()
        with self.assertRaises(Http404):
            self._get(key=self.drop.key)

    def test_never_proxies_content(self):
        """Response must be a redirect, not an HttpResponse with a body."""
        with patch.object(Drop, "download_url", return_value="https://b2.example.com/file"):
            resp = self._get()
        # Redirects have no meaningful content body
        self.assertIn(resp.status_code, (301, 302, 303, 307, 308))
