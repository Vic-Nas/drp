"""
integration_tests/cli/test_manage.py

Integration tests for:
  drp rm     — delete clipboard and file drops
  drp mv     — rename (all three return paths: success, known error, wrong ns)
  drp cp     — copy clipboard and file drops
  drp renew  — renew expiry (paid feature; tested for both success and graceful failure)
"""

import os
import tempfile

import pytest

from conftest import HOST, unique_key, run_drp
from cli.api.text import upload_text, get_clipboard
from cli.api.file import upload_file


def _upload_text(drp_session, label, content='test content'):
    key = unique_key(label)
    upload_text(HOST, drp_session, content, key=key)
    return key


def _upload_file(drp_session, label, payload=b'file content'):
    key = unique_key(label)
    with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
        f.write(payload)
        path = f.name
    try:
        upload_file(HOST, drp_session, path, key=key)
    finally:
        os.unlink(path)
    return key


# ── drp rm ─────────────────────────────────────────────────────────────────────

class TestRm:
    def test_rm_clipboard_exits_zero(self, cli_env, drp_session):
        key = _upload_text(drp_session, 'rm')
        r = run_drp('rm', key, env=cli_env, check=True)
        assert r.returncode == 0
        assert key in r.stdout

    def test_rm_clipboard_drop_is_gone(self, cli_env, drp_session):
        key = _upload_text(drp_session, 'rmgone')
        run_drp('rm', key, env=cli_env, check=True)
        kind, _ = get_clipboard(HOST, drp_session, key)
        assert kind is None

    def test_rm_file_drop(self, cli_env, drp_session):
        from cli.api.file import get_file
        key = _upload_file(drp_session, 'rmfile')
        r = run_drp('rm', '-f', key, env=cli_env, check=True)
        assert r.returncode == 0
        kind, _ = get_file(HOST, drp_session, key)
        assert kind is None

    def test_rm_missing_key_exits_nonzero(self, cli_env):
        r = run_drp('rm', 'drptest-no-such-rm-xyz', env=cli_env)
        assert r.returncode != 0

    def test_rm_wrong_namespace_exits_nonzero(self, cli_env, drp_session, track):
        """rm -f on a clipboard drop should fail with a helpful message."""
        key = _upload_text(drp_session, 'rmwrongns')
        track(key)
        r = run_drp('rm', '-f', key, env=cli_env)
        assert r.returncode != 0
        combined = r.stdout + r.stderr
        assert 'drp rm' in combined or 'namespace' in combined.lower() or 'not found' in combined.lower()


# ── drp mv ─────────────────────────────────────────────────────────────────────

class TestMv:
    def test_mv_clipboard_succeeds(self, cli_env, drp_session, track):
        old = _upload_text(drp_session, 'mvold')
        new = unique_key('mvnew')
        r = run_drp('mv', old, new, env=cli_env, check=True)
        track(new)
        assert r.returncode == 0
        assert new in r.stdout

    def test_mv_old_key_gone(self, cli_env, drp_session, track):
        old = _upload_text(drp_session, 'mvoldgone')
        new = unique_key('mvnewgone')
        run_drp('mv', old, new, env=cli_env, check=True)
        track(new)
        kind, _ = get_clipboard(HOST, drp_session, old)
        assert kind is None

    def test_mv_new_key_accessible(self, cli_env, drp_session, track):
        content = 'mv-content-marker'
        old = unique_key('mvacc')
        upload_text(HOST, drp_session, content, key=old)
        new = unique_key('mvaccnew')
        run_drp('mv', old, new, env=cli_env, check=True)
        track(new)
        kind, got = get_clipboard(HOST, drp_session, new)
        assert kind == 'text'
        assert got == content

    def test_mv_to_taken_key_exits_nonzero(self, cli_env, drp_session, track):
        key_a = _upload_text(drp_session, 'mvtakena')
        key_b = _upload_text(drp_session, 'mvtakenb')
        track(key_a)
        track(key_b)
        r = run_drp('mv', key_a, key_b, env=cli_env)
        assert r.returncode != 0
        combined = r.stdout + r.stderr
        assert 'taken' in combined.lower() or 'already' in combined.lower()

    def test_mv_missing_key_exits_nonzero(self, cli_env):
        r = run_drp('mv', 'drptest-no-such-mv-xyz', unique_key('mvdest'), env=cli_env)
        assert r.returncode != 0

    def test_mv_file_drop(self, cli_env, drp_session, track):
        old = _upload_file(drp_session, 'mvfileold')
        new = unique_key('mvfilenew')
        r = run_drp('mv', '-f', old, new, env=cli_env, check=True)
        track(new, ns='f')
        assert r.returncode == 0
        assert new in r.stdout

    def test_mv_wrong_ns_exits_nonzero(self, cli_env, drp_session, track):
        """mv without -f on a file drop should fail and hint at -f."""
        key = _upload_file(drp_session, 'mvwrongns')
        track(key, ns='f')
        r = run_drp('mv', key, unique_key('dest'), env=cli_env)
        assert r.returncode != 0
        combined = r.stdout + r.stderr
        assert '-f' in combined or 'file' in combined.lower() or 'not found' in combined.lower()


# ── drp cp ─────────────────────────────────────────────────────────────────────

class TestCp:
    def test_cp_clipboard_exits_zero(self, cli_env, drp_session, track):
        src = _upload_text(drp_session, 'cpsrc', 'copy source content')
        dst = unique_key('cpdst')
        r = run_drp('cp', src, dst, env=cli_env, check=True)
        track(src)
        track(dst)
        assert r.returncode == 0

    def test_cp_clipboard_content_identical(self, cli_env, drp_session, track):
        content = 'copy-content-marker-xyz'
        src = unique_key('cpcontsrc')
        upload_text(HOST, drp_session, content, key=src)
        dst = unique_key('cpcontdst')
        run_drp('cp', src, dst, env=cli_env, check=True)
        track(src)
        track(dst)
        kind, got = get_clipboard(HOST, drp_session, dst)
        assert kind == 'text'
        assert got == content

    def test_cp_source_still_exists(self, cli_env, drp_session, track):
        src = _upload_text(drp_session, 'cpsrcexists', 'still here')
        dst = unique_key('cpdstexists')
        run_drp('cp', src, dst, env=cli_env, check=True)
        track(src)
        track(dst)
        kind, _ = get_clipboard(HOST, drp_session, src)
        assert kind == 'text'

    def test_cp_to_taken_key_exits_nonzero(self, cli_env, drp_session, track):
        src = _upload_text(drp_session, 'cptakensrc')
        dst = _upload_text(drp_session, 'cptakendst')
        track(src)
        track(dst)
        r = run_drp('cp', src, dst, env=cli_env)
        assert r.returncode != 0

    def test_cp_file_drop(self, cli_env, drp_session, track):
        src = _upload_file(drp_session, 'cpfilesrc')
        dst = unique_key('cpfiledst')
        r = run_drp('cp', '-f', src, dst, env=cli_env, check=True)
        track(src, ns='f')
        track(dst, ns='f')
        assert r.returncode == 0
        assert dst in r.stdout


# ── drp renew ─────────────────────────────────────────────────────────────────

class TestRenew:
    def test_renew_exits_zero_or_reports_plan_limit(self, cli_env, drp_session, track):
        """
        renew is a paid feature. We accept either:
          - exit 0 with an expiry date printed (paid account)
          - exit non-zero with a plan-limit message (free account)
        Both are correct behaviour; the test just verifies no crash.
        """
        key = _upload_text(drp_session, 'renew')
        track(key)
        r = run_drp('renew', key, env=cli_env)
        # Should not produce an unhandled exception traceback
        assert 'Traceback' not in r.stderr
        assert 'Unexpected error' not in r.stderr

    def test_renew_missing_key_exits_nonzero(self, cli_env):
        r = run_drp('renew', 'drptest-no-such-renew-xyz', env=cli_env)
        assert r.returncode != 0
        assert 'Traceback' not in r.stderr
