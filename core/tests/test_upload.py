"""
Tests for upload_prepare and upload_confirm views (CLI upload flow).

Covers: quota re-check at confirm time (TOCTOU), B2 existence check,
        orphan cleanup on quota exceeded, drop creation.
"""

import json
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory

from core.models import Drop, Plan
from core.views.drops import upload_confirm, upload_prepare
from .helpers import make_user, make_file_drop


class UploadConfirmTests(TestCase):
    """confirm must re-check quota using the *actual* B2 object size,
    and must delete the orphaned B2 object if quota is exceeded."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = make_user("confirm-user", plan=Plan.STARTER)

    def _post(self, data, user=None):
        req = self.factory.post(
            "/upload/confirm/",
            data=json.dumps(data),
            content_type="application/json",
        )
        req.user = user or self.user
        req.COOKIES = {}
        return upload_confirm(req)

    @patch("core.views.drops.object_exists", return_value=True)
    @patch("core.views.drops.object_size", return_value=500)
    def test_confirm_creates_drop(self, mock_size, mock_exists):
        resp = self._post({"key": "newfile", "ns": "f", "filename": "a.txt"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Drop.objects.filter(ns="f", key="newfile").exists())

    @patch("core.views.drops.object_exists", return_value=True)
    @patch("core.views.drops.object_size", return_value=500)
    def test_confirm_returns_expected_fields(self, mock_size, mock_exists):
        resp = self._post({"key": "fields-test", "ns": "f", "filename": "b.txt"})
        data = json.loads(resp.content)
        self.assertIn("key", data)
        self.assertIn("url", data)
        self.assertEqual(data["key"], "fields-test")

    @patch("core.views.drops.object_exists", return_value=False)
    def test_confirm_404_when_object_missing(self, mock_exists):
        resp = self._post({"key": "ghost", "ns": "f", "filename": "ghost.bin"})
        self.assertEqual(resp.status_code, 404)

    @patch("core.views.drops.object_exists", return_value=True)
    @patch("core.views.drops.object_size")
    @patch("core.views.drops.delete_from_b2")
    def test_confirm_deletes_b2_on_quota_exceeded(self, mock_del, mock_size, mock_exists):
        quota = Plan.get(Plan.STARTER, "storage_gb") * 1024 ** 3
        self.user.profile.storage_used_bytes = quota
        self.user.profile.save()
        mock_size.return_value = 1

        resp = self._post({"key": "overflow", "ns": "f", "filename": "x.bin"})
        self.assertEqual(resp.status_code, 507)
        mock_del.assert_called_once_with("f", "overflow")
        self.assertFalse(Drop.objects.filter(key="overflow").exists())

    def test_confirm_rejects_missing_key(self):
        resp = self._post({"ns": "f", "filename": "no-key.bin"})
        self.assertEqual(resp.status_code, 400)

    def test_confirm_rejects_invalid_ns(self):
        resp = self._post({"key": "x", "ns": "bad", "filename": "x.bin"})
        self.assertEqual(resp.status_code, 400)

    def test_confirm_rejects_get_method(self):
        req = self.factory.get("/upload/confirm/")
        req.user = self.user
        req.COOKIES = {}
        resp = upload_confirm(req)
        self.assertEqual(resp.status_code, 405)

    @patch("core.views.drops.object_exists", return_value=True)
    @patch("core.views.drops.object_size", return_value=500)
    def test_confirm_updates_existing_drop(self, mock_size, mock_exists):
        make_file_drop(key="existing", owner=self.user, filesize=100)

        resp = self._post({"key": "existing", "ns": "f", "filename": "updated.txt"})
        self.assertEqual(resp.status_code, 200)

        drop = Drop.objects.get(ns="f", key="existing")
        self.assertEqual(drop.filename, "updated.txt")
        self.assertEqual(drop.filesize, 500)


class UploadPrepareTests(TestCase):
    """prepare must validate limits before issuing a presigned PUT URL."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = make_user("prep-user", plan=Plan.STARTER)

    def _post(self, data, user=None):
        req = self.factory.post(
            "/upload/prepare/",
            data=json.dumps(data),
            content_type="application/json",
        )
        req.user = user or self.user
        req.COOKIES = {}
        return upload_prepare(req)

    @patch("core.views.drops.presigned_put" if False else "core.views.b2.presigned_put",
           return_value="https://b2.example.com/presigned-put")
    def test_prepare_returns_presigned_url(self, mock_put):
        # patch at the import site used inside upload_prepare
        with patch("core.views.b2.presigned_put", return_value="https://b2.example.com/put"):
            resp = self._post({"key": "prep-file", "ns": "f",
                               "filename": "data.bin", "size": 100})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertIn("presigned_url", data)
        self.assertIn("key", data)

    def test_prepare_rejects_file_over_plan_limit(self):
        limit_bytes = Plan.get(Plan.STARTER, "max_file_mb") * 1024 * 1024
        resp = self._post({"key": "big", "ns": "f", "filename": "big.bin",
                           "size": limit_bytes + 1})
        self.assertEqual(resp.status_code, 413)

    def test_prepare_rejects_quota_exceeded(self):
        quota = Plan.get(Plan.STARTER, "storage_gb") * 1024 ** 3
        self.user.profile.storage_used_bytes = quota
        self.user.profile.save()
        resp = self._post({"key": "over", "ns": "f", "filename": "over.bin", "size": 1})
        self.assertEqual(resp.status_code, 507)

    def test_prepare_rejects_invalid_ns(self):
        resp = self._post({"key": "x", "ns": "z", "filename": "x.bin", "size": 1})
        self.assertEqual(resp.status_code, 400)
