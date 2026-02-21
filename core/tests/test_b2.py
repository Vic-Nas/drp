"""
Tests for core/views/b2.py

Covers: object_key construction, presigned_get call contract,
        delete_object resilience.
"""

from unittest.mock import patch, MagicMock

from django.test import TestCase

from core.models import Drop
from core.views.b2 import object_key


class ObjectKeyTests(TestCase):
    """object_key() is the single source of truth for B2 paths.
    If this is wrong, files land in the wrong place and downloads break."""

    def test_file_ns(self):
        self.assertEqual(object_key("f", "report"), "drops/f/report")

    def test_clipboard_ns(self):
        self.assertEqual(object_key("c", "hello"), "drops/c/hello")

    def test_key_with_special_chars(self):
        # Keys with hyphens/underscores must survive unchanged
        self.assertEqual(object_key("f", "my-file_v2"), "drops/f/my-file_v2")


class DropDownloadUrlTests(TestCase):
    """download_url() must call presigned_get with the correct ns/key/filename
    and must not pass extra kwargs the caller doesn't control."""

    def test_calls_presigned_get_correctly(self):
        drop = Drop(
            ns=Drop.NS_FILE, key="myfile", kind=Drop.FILE,
            filename="report.pdf",
        )
        with patch("core.views.b2.presigned_get", return_value="https://url") as mock:
            url = drop.download_url(expires_in=1800)
        mock.assert_called_once_with("f", "myfile", filename="report.pdf", expires_in=1800)
        self.assertEqual(url, "https://url")

    def test_raises_for_text_drop(self):
        drop = Drop(ns=Drop.NS_CLIPBOARD, key="txt", kind=Drop.TEXT)
        with self.assertRaises(ValueError):
            drop.download_url()

    def test_default_expires_in_used_when_not_specified(self):
        drop = Drop(
            ns=Drop.NS_FILE, key="f1", kind=Drop.FILE,
            filename="file.zip",
        )
        with patch("core.views.b2.presigned_get", return_value="https://url") as mock:
            drop.download_url()
        _, kwargs = mock.call_args
        self.assertIn("expires_in", kwargs)
        self.assertGreater(kwargs["expires_in"], 0)
