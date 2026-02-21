"""
integration_tests/core/test_api_file.py
Tests for upload_file / get_file across all plan tiers.
"""
import os
import tempfile
import pytest
from conftest import HOST, unique_key
from cli.api.file import upload_file, get_file


def _tmp(content=b'integration test', suffix='.txt'):
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(content); f.close()
    return f.name


class TestUploadFile:
    def test_basic_upload(self, free_user):
        path = _tmp()
        key = unique_key('file')
        try:
            result = upload_file(HOST, free_user.session, path, key=key)
        finally:
            os.unlink(path)
        free_user.track(result or key, ns='f')
        assert result == key

    def test_roundtrip_bytes(self, free_user):
        payload = b'binary \x00\x01\x02\xff'
        path = _tmp(content=payload, suffix='.bin')
        key = unique_key('bytes')
        try:
            upload_file(HOST, free_user.session, path, key=key)
        finally:
            os.unlink(path)
        free_user.track(key, ns='f')
        kind, (content, _) = get_file(HOST, free_user.session, key)
        assert kind == 'file' and content == payload

    def test_filename_preserved(self, free_user):
        path = _tmp(suffix='.pdf')
        key = unique_key('fname')
        try:
            upload_file(HOST, free_user.session, path, key=key)
        finally:
            os.unlink(path)
        free_user.track(key, ns='f')
        _, (_, name) = get_file(HOST, free_user.session, key)
        assert name == os.path.basename(path)

    def test_anon_can_download_file(self, free_user, anon):
        payload = b'public file'
        path = _tmp(content=payload)
        key = unique_key('anonfile')
        try:
            upload_file(HOST, free_user.session, path, key=key)
        finally:
            os.unlink(path)
        free_user.track(key, ns='f')
        kind, (content, _) = get_file(HOST, anon, key)
        assert kind == 'file' and content == payload

    def test_missing_key_returns_none(self, anon):
        kind, result = get_file(HOST, anon, 'drptest-no-such-file-xyz')
        assert kind is None and result is None

    def test_each_plan_can_upload(self, free_user, starter_user, pro_user):
        for user in (free_user, starter_user, pro_user):
            path = _tmp(content=f'{user.plan} file'.encode())
            key = unique_key('planfile')
            try:
                result = upload_file(HOST, user.session, path, key=key)
            finally:
                os.unlink(path)
            user.track(result or key, ns='f')
            assert result is not None
