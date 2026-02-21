"""
Shared test utilities and factory helpers.
Import from here instead of duplicating setUp logic across modules.
"""

from django.contrib.auth.models import User
from django.test import RequestFactory
from django.utils import timezone

from core.models import Drop, Plan, UserProfile


def make_user(username="user", plan=Plan.FREE, storage_used=0, password="pw"):
    user = User.objects.create_user(username, password=password)
    UserProfile.objects.filter(user=user).update(
        plan=plan,
        storage_used_bytes=storage_used,
    )
    user.refresh_from_db()
    return user


def make_drop(ns=Drop.NS_CLIPBOARD, key="test", kind=Drop.TEXT, owner=None, **kwargs):
    defaults = dict(ns=ns, key=key, kind=kind, owner=owner)
    defaults.update(kwargs)
    return Drop.objects.create(**defaults)


def make_file_drop(key="file", owner=None, filesize=1000, **kwargs):
    return Drop.objects.create(
        ns=Drop.NS_FILE,
        key=key,
        kind=Drop.FILE,
        file_public_id=f"drops/f/{key}",
        filename=f"{key}.pdf",
        filesize=filesize,
        owner=owner,
        **kwargs,
    )


def json_post(view_fn, url, data, user=None, cookies=None):
    """POST JSON to a view function via RequestFactory. Returns response."""
    import json
    from unittest.mock import MagicMock
    factory = RequestFactory()
    req = factory.post(url, data=json.dumps(data), content_type="application/json")
    req.user = user or MagicMock(is_authenticated=False)
    req.COOKIES = cookies or {}
    return view_fn(req)


def anon_request(method="GET", path="/", data=None, accept_json=False):
    """Build an anonymous request."""
    from unittest.mock import MagicMock
    factory = RequestFactory()
    builder = getattr(factory, method.lower())
    req = builder(path, data=data or {})
    req.user = MagicMock(is_authenticated=False)
    req.COOKIES = {}
    if accept_json:
        req.META["HTTP_ACCEPT"] = "application/json"
    return req
