"""
Integration tests for drp CLI (Django live server required).
All Django-dependent tests moved here from tests.py.
"""

# ...existing code for integration tests (live server, Django, etc.)...


# ═══════════════════════════════════════════════════════════════════════════════
# Auth API (live server)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC
class AuthApiTests(LiveServerTestCase):

    def setUp(self):
        self.user = User.objects.create_user('cli@test.com', 'cli@test.com', 'pass1234')
        self.session = requests.Session()

    def test_login_success(self):
        self.assertTrue(api.login(self.live_server_url, self.session, 'cli@test.com', 'pass1234'))
        self.assertIn('sessionid', self.session.cookies)

    def test_login_wrong_password_returns_false(self):
        self.assertFalse(api.login(self.live_server_url, self.session, 'cli@test.com', 'WRONG'))
        self.assertNotIn('sessionid', self.session.cookies)

    def test_login_nonexistent_user_returns_false(self):
        self.assertFalse(api.login(self.live_server_url, self.session, 'no@one.com', 'pass'))


# ═══════════════════════════════════════════════════════════════════════════════
# Clipboard API (live server)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC
class ClipboardApiTests(LiveServerTestCase):

    def setUp(self):
        self.session = requests.Session()
        self.host = self.live_server_url

    def test_upload_returns_key(self):
        key = api.upload_text(self.host, self.session, 'hello world')
        self.assertIsNotNone(key)
        self.assertGreater(len(key), 0)

    def test_upload_with_custom_key(self):
        key = api.upload_text(self.host, self.session, 'custom', key='mykey')
        self.assertEqual(key, 'mykey')

    def test_get_returns_exact_content(self):
        content = 'exact content round-trip'
        key = api.upload_text(self.host, self.session, content)
        kind, result = api.get_clipboard(self.host, self.session, key)
        self.assertEqual(kind, 'text')
        self.assertEqual(result, content)

    def test_get_nonexistent_returns_none(self):
        kind, content = api.get_clipboard(self.host, self.session, 'no-such-key-xyz')
        self.assertIsNone(kind)

    def test_delete_makes_key_unavailable(self):
        key = api.upload_text(self.host, self.session, 'bye', key='todel-c')
        self.assertTrue(api.delete(self.host, self.session, key, ns='c'))
        self.assertFalse(api.key_exists(self.host, self.session, key, ns='c'))

    def test_delete_nonexistent_is_idempotent(self):
        # Should return True (already gone), not crash
        result = api.delete(self.host, self.session, 'no-such-key', ns='c')
        self.assertTrue(result)

    def test_key_exists_after_upload(self):
        api.upload_text(self.host, self.session, 'present', key='present-key')
        self.assertTrue(api.key_exists(self.host, self.session, 'present-key', ns='c'))

    def test_overwrite_locked_anon_drop_rejected(self):
        api.upload_text(self.host, self.session, 'original', key='locked-anon')
        other = requests.Session()
        result = api.upload_text(self.host, other, 'overwrite', key='locked-anon')
        self.assertIsNone(result)

    def test_overwrite_after_lock_expires_succeeds(self):
        from core.models import Drop
        api.upload_text(self.host, self.session, 'original', key='unlocked-anon')
        Drop.objects.filter(key='unlocked-anon').update(
            locked_until=timezone.now() - timedelta(hours=1)
        )
        other = requests.Session()
        result = api.upload_text(self.host, other, 'new content', key='unlocked-anon')
        self.assertIsNotNone(result)


# ═══════════════════════════════════════════════════════════════════════════════
# File API (live server)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC
class FileApiTests(LiveServerTestCase):

    def setUp(self):
        self.session = requests.Session()
        self.host = self.live_server_url

    def _tmp(self, content=b'test file content', suffix='.txt'):
        f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        f.write(content)
        f.flush()
        f.close()
        return f.name

    def test_upload_file_returns_key(self):
        path = self._tmp()
        try:
            key = api.upload_file(self.host, self.session, path, key='uptest')
            self.assertEqual(key, 'uptest')
        finally:
            os.unlink(path)

    def test_get_file_returns_correct_bytes(self):
        content = b'exact binary content'
        path = self._tmp(content=content)
        try:
            key = api.upload_file(self.host, self.session, path, key='binfile')
            kind, result = api.get_file(self.host, self.session, key)
            self.assertEqual(kind, 'file')
            data, _ = result
            self.assertEqual(data, content)
        finally:
            os.unlink(path)

    def test_get_file_returns_original_filename(self):
        path = self._tmp(suffix='.pdf')
        basename = os.path.basename(path)
        try:
            key = api.upload_file(self.host, self.session, path, key='namedfile')
            _, (_, filename) = api.get_file(self.host, self.session, key)
            self.assertEqual(filename, basename)
        finally:
            os.unlink(path)

    def test_auto_key_derived_from_filename(self):
        path = self._tmp(suffix='.csv')
        stem = api.slug(os.path.basename(path))
        try:
            key = api.upload_file(self.host, self.session, path)
            self.assertEqual(key, stem)
        finally:
            os.unlink(path)

    def test_file_accessible_at_f_prefix_url(self):
        path = self._tmp()
        try:
            key = api.upload_file(self.host, self.session, path, key='ftest')
            resp = self.session.get(f'{self.host}/f/{key}/',
                                    headers={'Accept': 'application/json'})
            self.assertTrue(resp.ok)
            self.assertEqual(resp.json()['kind'], 'file')
        finally:
            os.unlink(path)

    def test_file_not_accessible_at_bare_key(self):
        """Files should only be at /f/key/, not /key/ (that's clipboards)."""
        path = self._tmp()
        try:
            key = api.upload_file(self.host, self.session, path, key='fonly')
            resp = self.session.get(f'{self.host}/{key}/',
                                    headers={'Accept': 'application/json'})
            # Should 404 since /key/ is clipboard namespace
            self.assertEqual(resp.status_code, 404)
        finally:
            os.unlink(path)


# ═══════════════════════════════════════════════════════════════════════════════
# Authenticated drops (live server)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC
class AuthDropApiTests(LiveServerTestCase):

    def setUp(self):
        self.user = User.objects.create_user('auth@test.com', 'auth@test.com', 'pass1234')
        self.session = requests.Session()
        self.host = self.live_server_url
        api.login(self.host, self.session, 'auth@test.com', 'pass1234')

    def test_uploaded_drop_is_owned_and_locked(self):
        from core.models import Drop
        api.upload_text(self.host, self.session, 'owned', key='ownedrop')
        drop = Drop.objects.get(key='ownedrop')
        self.assertEqual(drop.owner, self.user)
        self.assertTrue(drop.locked)

    def test_owner_can_delete_own_drop(self):
        api.upload_text(self.host, self.session, 'delete me', key='todel')
        self.assertTrue(api.delete(self.host, self.session, 'todel', ns='c'))
        self.assertFalse(api.key_exists(self.host, self.session, 'todel', ns='c'))

    def test_anon_cannot_delete_locked_drop(self):
        api.upload_text(self.host, self.session, 'protected', key='protdrop')
        anon = requests.Session()
        self.assertFalse(api.delete(self.host, anon, 'protdrop', ns='c'))
        self.assertTrue(api.key_exists(self.host, self.session, 'protdrop', ns='c'))

    def test_owner_can_rename(self):
        api.upload_text(self.host, self.session, 'hi', key='fromkey')
        new_key = api.rename(self.host, self.session, 'fromkey', 'tokey', ns='c')
        self.assertEqual(new_key, 'tokey')
        self.assertFalse(api.key_exists(self.host, self.session, 'fromkey', ns='c'))
        self.assertTrue(api.key_exists(self.host, self.session, 'tokey', ns='c'))

    def test_rename_to_taken_key_fails(self):
        api.upload_text(self.host, self.session, 'a', key='taken')
        api.upload_text(self.host, self.session, 'b', key='source')
        result = api.rename(self.host, self.session, 'source', 'taken', ns='c')
        self.assertIsNone(result)
        self.assertTrue(api.key_exists(self.host, self.session, 'source', ns='c'))

    def test_list_drops_returns_own_drops(self):
        api.upload_text(self.host, self.session, 'a', key='ls1')
        api.upload_text(self.host, self.session, 'b', key='ls2')
        drops = api.list_drops(self.host, self.session)
        keys = [d['key'] for d in drops]
        self.assertIn('ls1', keys)
        self.assertIn('ls2', keys)

    def test_list_drops_excludes_other_users(self):
        api.upload_text(self.host, self.session, 'mine', key='myls')
        other_session = requests.Session()
        User.objects.create_user('other@test.com', 'other@test.com', 'pass1234')
        api.login(self.host, other_session, 'other@test.com', 'pass1234')
        drops = api.list_drops(self.host, other_session)
        self.assertNotIn('myls', [d['key'] for d in drops])

    def test_list_drops_unauthenticated_returns_none(self):
        self.assertIsNone(api.list_drops(self.host, requests.Session()))

    def test_renew_extends_expiry(self):
        from core.models import Drop, Plan
        self.user.profile.plan = Plan.STARTER
        self.user.profile.save()
        api.upload_text(self.host, self.session, 'renew me', key='renewtest')
        old_expiry = timezone.now() + timedelta(days=30)
        Drop.objects.filter(key='renewtest').update(expires_at=old_expiry)
        expires_at, count = api.renew(self.host, self.session, 'renewtest', ns='c')
        self.assertIsNotNone(expires_at)
        self.assertEqual(count, 1)

    def test_renew_anon_drop_denied(self):
        anon = requests.Session()
        api.upload_text(self.host, anon, 'no renew', key='anonrenew')
        expires_at, _ = api.renew(self.host, anon, 'anonrenew', ns='c')
        self.assertIsNone(expires_at)


# ═══════════════════════════════════════════════════════════════════════════════
# Session persistence (live server)
# ═══════════════════════════════════════════════════════════════════════════════

@_STATIC
class SessionTests(LiveServerTestCase):

    def setUp(self):
        self.user = User.objects.create_user('sess@test.com', 'sess@test.com', 'pass1234')
        self.session = requests.Session()
        self.host = self.live_server_url
        api.login(self.host, self.session, 'sess@test.com', 'pass1234')

    def test_saved_session_authenticates_new_requests(self):
        from cli.session import save_session, load_session, SESSION_FILE
        save_session(self.session)
        self.assertTrue(SESSION_FILE.exists())
        new_session = requests.Session()
        load_session(new_session)
        res = new_session.get(
            f'{self.host}/auth/account/',
            headers={'Accept': 'application/json'},
            allow_redirects=False,
        )
        self.assertEqual(res.status_code, 200)

    def test_cleared_session_loses_auth(self):
        from cli.session import save_session, clear_session, SESSION_FILE
        save_session(self.session)
        clear_session()
        self.assertFalse(SESSION_FILE.exists())
        new_session = requests.Session()
        res = new_session.get(f'{self.host}/auth/account/', allow_redirects=False)
        self.assertIn(res.status_code, (302, 403))