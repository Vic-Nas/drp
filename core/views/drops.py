"""
Drop creation, retrieval, and download views.

File storage is now Backblaze B2.

Upload paths:
  Web browser  → POST /save/           → Django streams to B2  (server-side)
  CLI          → POST /upload/prepare/ → Django returns presigned PUT URL
               → PUT  <presigned URL>  → client uploads direct to B2
               → POST /upload/confirm/ → Django verifies + creates Drop

Download path (both web and CLI):
  GET /f/<key>/ → JSON includes a short-lived presigned GET URL
  GET /f/<key>/download/ → 302 redirect to presigned GET URL
  (Railway never proxies file bytes → no timeout risk)
"""

import secrets
from datetime import timedelta
from functools import cache

from django.conf import settings
from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect
from django.utils import timezone

from core.models import Drop, Plan, SavedDrop
from .helpers import (
    user_plan, max_file_bytes, max_text_bytes, storage_ok,
    is_paid_user, max_lifetime_secs, gen_key,
    upload_to_b2, delete_from_b2, add_storage,
)
from core.views.b2 import object_exists, object_size

ANON_COOKIE = "drp_anon"


# ── Reserved keys ─────────────────────────────────────────────────────────────

@cache
def _get_reserved_keys():
    """
    Derive reserved top-level path segments from the root URL conf.
    Deferred until first call to avoid circular import at startup.
    Cached so the resolver is only inspected once.
    """
    from django.urls import get_resolver
    resolver = get_resolver()
    reserved = set()
    for pattern in resolver.url_patterns:
        segment = str(pattern.pattern).strip("^").split("/")[0]
        if segment and not segment.startswith(("(", "?", "<")):
            reserved.add(segment)
    return reserved


# ── Home ──────────────────────────────────────────────────────────────────────

def home(request):
    claimed = request.session.pop("claimed_drops", 0)
    server_drops = []
    saved_drops = []
    if request.user.is_authenticated:
        server_drops = (
            Drop.objects
            .filter(owner=request.user)
            .order_by("-created_at")[:50]
        )
        saved_drops = (
            SavedDrop.objects
            .filter(user=request.user)
            .order_by("-saved_at")[:50]
        )
    return render(request, "home.html", {
        "server_drops": server_drops,
        "saved_drops": saved_drops,
        "claimed": claimed,
    })


# ── Check key ─────────────────────────────────────────────────────────────────

def check_key(request):
    key = request.GET.get("key", "").strip()
    ns  = request.GET.get("ns", Drop.NS_CLIPBOARD)
    if not key:
        return JsonResponse({"error": "Key required."}, status=400)
    if key in _get_reserved_keys():
        return JsonResponse({"available": False, "reserved": True, "ns": ns, "key": key})
    taken = Drop.objects.filter(ns=ns, key=key).exists()
    return JsonResponse({"available": not taken, "ns": ns, "key": key})


# ── Save drop (web flow) ──────────────────────────────────────────────────────

def save_drop(request):
    """
    Unified endpoint for web UI uploads (text + file).

    For file drops the browser POSTs multipart/form-data; Django receives the
    bytes and streams them to B2 via boto3's managed upload.  This keeps the
    web template unchanged while the CLI uses the separate prepare/confirm flow
    that never touches Railway for the actual bytes.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    f  = request.FILES.get("file")
    ns = Drop.NS_FILE if f else Drop.NS_CLIPBOARD
    key = request.POST.get("key", "").strip() or gen_key(ns)

    if key in _get_reserved_keys():
        return JsonResponse({"error": f'"{key}" is a reserved key.'}, status=400)

    existing = Drop.objects.filter(ns=ns, key=key).first()
    if existing and existing.is_expired():
        existing.hard_delete()
        existing = None

    if existing and not existing.can_edit(request.user):
        if existing.is_creation_locked():
            return JsonResponse({
                "error": (
                    "This drop was just created and is protected for 24 hours. "
                    "Wait until the window expires or pick a different key."
                )
            }, status=403)
        return JsonResponse({"error": "This drop is locked to its owner."}, status=403)

    paid = is_paid_user(request.user)

    anon_token = None
    if not request.user.is_authenticated:
        anon_token = request.COOKIES.get(ANON_COOKIE) or secrets.token_urlsafe(32)

    if f:
        response = _save_file(request, f, ns, key, existing, paid, anon_token)
    else:
        response = _save_text(request, ns, key, existing, paid, anon_token)

    if anon_token and not existing:
        response.set_cookie(
            ANON_COOKIE,
            anon_token,
            max_age=7 * 24 * 3600,
            httponly=True,
            samesite="Lax",
        )

    return response


def _expiry_and_lock(request, paid):
    """Return (expires_at, locked_until) based on user plan and POST data."""
    expires_at   = None
    locked_until = None
    expiry_days  = request.POST.get("expiry_days")

    if paid and expiry_days:
        try:
            days = min(
                int(expiry_days),
                Plan.get(user_plan(request.user), "max_expiry_days"),
            )
            expires_at = timezone.now() + timedelta(days=days)
        except (ValueError, TypeError):
            pass
    elif not request.user.is_authenticated:
        locked_until = timezone.now() + timedelta(hours=24)

    return expires_at, locked_until


def _save_file(request, f, ns, key, existing, paid, anon_token):
    if f.size > max_file_bytes(request.user):
        limit = Plan.get(user_plan(request.user), "max_file_mb")
        return JsonResponse({"error": f"File exceeds {limit} MB limit."}, status=400)

    if not storage_ok(request.user, f.size):
        return JsonResponse({"error": "Storage quota exceeded."}, status=400)

    content_type = f.content_type or "application/octet-stream"

    try:
        b2_key = upload_to_b2(f, ns, key, content_type=content_type)
    except Exception as e:
        return JsonResponse({"error": f"File upload failed: {e}"}, status=500)

    if existing:
        # Replace — update existing record; old B2 object is overwritten by key
        old_size = existing.filesize
        existing.file_public_id = b2_key
        existing.file_url       = ""   # presigned on demand; no static URL
        existing.filename       = f.name
        existing.filesize       = f.size
        existing.save(update_fields=["file_public_id", "file_url", "filename", "filesize"])
        if existing.owner_id:
            from django.db import models as db_models
            from core.models import UserProfile
            UserProfile.objects.filter(user_id=existing.owner_id).update(
                storage_used_bytes=db_models.F("storage_used_bytes") + (f.size - old_size)
            )
        drop = existing
    else:
        expires_at, locked_until = _expiry_and_lock(request, paid)
        owner = request.user if request.user.is_authenticated else None
        drop = Drop.objects.create(
            ns=ns, key=key, kind=Drop.FILE,
            file_public_id=b2_key,
            file_url="",          # presigned on demand
            filename=f.name,
            filesize=f.size,
            owner=owner,
            locked=paid,
            locked_until=locked_until,
            expires_at=expires_at,
            max_lifetime_secs=max_lifetime_secs(request.user, ns),
            anon_token=anon_token,
        )
        add_storage(request.user, f.size)

    return JsonResponse({
        "key":  drop.key,
        "ns":   drop.ns,
        "kind": drop.kind,
        "url":  f"/f/{drop.key}/",
        "new":  existing is None,
    })


def _save_text(request, ns, key, existing, paid, anon_token):
    text = request.POST.get("content", "").strip()
    if len(text.encode()) > max_text_bytes(request.user):
        limit = Plan.get(user_plan(request.user), "max_text_kb")
        return JsonResponse({"error": f"Text exceeds {limit} KB."}, status=400)

    if existing:
        existing.content = text
        existing.last_accessed_at = timezone.now()
        existing.save(update_fields=["content", "last_accessed_at"])
        drop = existing
    else:
        expires_at, locked_until = _expiry_and_lock(request, paid)
        owner = request.user if request.user.is_authenticated else None
        drop = Drop.objects.create(
            ns=ns, key=key, kind=Drop.TEXT, content=text,
            owner=owner,
            locked=paid,
            locked_until=locked_until,
            expires_at=expires_at,
            max_lifetime_secs=max_lifetime_secs(request.user, ns),
            anon_token=anon_token,
        )

    return JsonResponse({
        "key":  drop.key,
        "ns":   drop.ns,
        "kind": drop.kind,
        "url":  f"/{drop.key}/",
        "new":  existing is None,
    })


# ── CLI direct-upload endpoints ───────────────────────────────────────────────

def upload_prepare(request):
    """
    POST /upload/prepare/

    Validates auth + quota, generates a presigned B2 PUT URL.
    The CLI uses this to upload directly to B2 without routing bytes
    through Railway (avoiding the 30-second timeout).

    Request JSON:
      { "filename": "report.pdf", "size": 12345678,
        "content_type": "application/pdf", "key": "report", "ns": "f" }

    Response JSON (200):
      { "presigned_url": "https://...", "key": "report", "ns": "f",
        "expires_in": 3600 }

    Error responses: 400 (bad input), 403 (locked), 413 (too large), 507 (quota)
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    filename     = (data.get("filename") or "").strip()
    size         = int(data.get("size", 0))
    content_type = data.get("content_type") or "application/octet-stream"
    ns           = data.get("ns", Drop.NS_FILE)
    key          = (data.get("key") or "").strip() or gen_key(ns)

    if ns not in (Drop.NS_CLIPBOARD, Drop.NS_FILE):
        return JsonResponse({"error": "Invalid ns."}, status=400)

    if key in _get_reserved_keys():
        return JsonResponse({"error": f'"{key}" is a reserved key.'}, status=400)

    # Size validation
    if size > max_file_bytes(request.user):
        limit = Plan.get(user_plan(request.user), "max_file_mb")
        return JsonResponse({"error": f"File exceeds {limit} MB limit."}, status=413)

    # Quota validation (TOCTOU-safe: we re-check in confirm)
    if not storage_ok(request.user, size):
        return JsonResponse({"error": "Storage quota exceeded."}, status=507)

    # Key conflict check
    existing = Drop.objects.filter(ns=ns, key=key).first()
    if existing and existing.is_expired():
        existing.hard_delete()
        existing = None

    if existing and not existing.can_edit(request.user):
        if existing.is_creation_locked():
            return JsonResponse({
                "error": "This drop is protected for 24 hours after creation."
            }, status=403)
        return JsonResponse({"error": "This drop is locked to its owner."}, status=403)

    # Generate presigned PUT
    from core.views.b2 import presigned_put
    EXPIRES_IN = 3600  # 1 hour
    presigned_url = presigned_put(ns, key, content_type=content_type, expires_in=EXPIRES_IN)

    return JsonResponse({
        "presigned_url": presigned_url,
        "key":           key,
        "ns":            ns,
        "expires_in":    EXPIRES_IN,
    })


def upload_confirm(request):
    """
    POST /upload/confirm/

    Called by the CLI after it has PUT the file directly to B2.
    Verifies the object exists, re-validates quota, then creates the Drop record.

    Request JSON:
      { "key": "report", "ns": "f", "filename": "report.pdf",
        "content_type": "application/pdf" }

    Response JSON (200):
      { "key": "report", "ns": "f", "kind": "file", "url": "/f/report/" }
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    key      = (data.get("key") or "").strip()
    ns       = data.get("ns", Drop.NS_FILE)
    filename = (data.get("filename") or key).strip()

    if not key or ns not in (Drop.NS_CLIPBOARD, Drop.NS_FILE):
        return JsonResponse({"error": "key and valid ns required."}, status=400)

    # Verify object actually landed in B2
    if not object_exists(ns, key):
        return JsonResponse(
            {"error": "File not found in storage. Upload may have failed or expired."},
            status=404,
        )

    actual_size = object_size(ns, key)

    # Re-validate quota now that we have the actual size
    if not storage_ok(request.user, actual_size):
        # Roll back — delete the orphaned B2 object
        delete_from_b2(ns, key)
        return JsonResponse({"error": "Storage quota exceeded."}, status=507)

    paid = is_paid_user(request.user)

    # Handle replace vs create
    existing = Drop.objects.filter(ns=ns, key=key).first()
    if existing and existing.is_expired():
        existing.hard_delete()
        existing = None

    if existing:
        # Replacing an existing drop (owner already validated in prepare)
        old_size = existing.filesize
        from core.views.b2 import object_key as b2_object_key
        existing.file_public_id = b2_object_key(ns, key)
        existing.file_url       = ""
        existing.filename       = filename
        existing.filesize       = actual_size
        existing.save(update_fields=["file_public_id", "file_url", "filename", "filesize"])
        if existing.owner_id:
            from django.db import models as db_models
            from core.models import UserProfile
            UserProfile.objects.filter(user_id=existing.owner_id).update(
                storage_used_bytes=db_models.F("storage_used_bytes") + (actual_size - old_size)
            )
        drop = existing
    else:
        anon_token = None
        if not request.user.is_authenticated:
            anon_token = request.COOKIES.get(ANON_COOKIE) or secrets.token_urlsafe(32)

        # Determine expiry
        paid = is_paid_user(request.user)
        expiry_days = data.get("expiry_days")
        expires_at  = None
        locked_until = None
        if paid and expiry_days:
            try:
                days = min(int(expiry_days),
                           Plan.get(user_plan(request.user), "max_expiry_days"))
                expires_at = timezone.now() + timedelta(days=days)
            except (ValueError, TypeError):
                pass
        elif not request.user.is_authenticated:
            locked_until = timezone.now() + timedelta(hours=24)

        from core.views.b2 import object_key as b2_object_key
        owner = request.user if request.user.is_authenticated else None
        drop = Drop.objects.create(
            ns=ns, key=key, kind=Drop.FILE,
            file_public_id=b2_object_key(ns, key),
            file_url="",
            filename=filename,
            filesize=actual_size,
            owner=owner,
            locked=paid,
            locked_until=locked_until,
            expires_at=expires_at,
            max_lifetime_secs=max_lifetime_secs(request.user, ns),
            anon_token=anon_token,
        )
        add_storage(request.user, actual_size)

    return JsonResponse({
        "key":  drop.key,
        "ns":   drop.ns,
        "kind": drop.kind,
        "url":  f"/f/{drop.key}/",
        "new":  existing is None,
    })


# ── View drop ─────────────────────────────────────────────────────────────────

def _drop_response(request, drop):
    if drop.is_expired():
        drop.hard_delete()
        if "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({"error": "Drop has expired."}, status=410)
        return render(request, "expired.html", {"key": drop.key})

    drop.touch()

    if "application/json" in request.headers.get("Accept", ""):
        data = {
            "key":             drop.key,
            "ns":              drop.ns,
            "kind":            drop.kind,
            "created_at":      drop.created_at.isoformat(),
            "last_accessed_at": (drop.last_accessed_at.isoformat()
                                 if drop.last_accessed_at else None),
            "expires_at":      (drop.expires_at.isoformat()
                                if drop.expires_at else None),
        }
        if drop.kind == Drop.TEXT:
            data["content"] = drop.content
        else:
            data["filename"] = drop.filename
            data["filesize"] = drop.filesize
            # Presigned download URL — client redirects directly to B2
            data["download"] = f"/f/{drop.key}/download/"
        return JsonResponse(data)

    plan = user_plan(request.user)
    return render(request, "drop.html", {
        "drop":           drop,
        "can_edit":       drop.can_edit(request.user),
        "is_owner":       request.user.is_authenticated and drop.owner_id == request.user.pk,
        "max_expiry_days": Plan.get(plan, "max_expiry_days"),
    })


def clipboard_view(request, key):
    drop = Drop.objects.filter(ns=Drop.NS_CLIPBOARD, key=key).first()
    if not drop:
        if "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({"error": "Drop not found."}, status=404)
        raise Http404
    return _drop_response(request, drop)


def file_view(request, key):
    drop = Drop.objects.filter(ns=Drop.NS_FILE, key=key).first()
    if not drop:
        if "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({"error": "Drop not found."}, status=404)
        raise Http404
    return _drop_response(request, drop)


# ── Download ──────────────────────────────────────────────────────────────────

def download_drop(request, key):
    """
    302-redirect to a fresh presigned B2 GET URL.
    Railway never proxies bytes — no timeout risk.
    """
    drop = Drop.objects.filter(ns=Drop.NS_FILE, key=key).first()
    if not drop:
        raise Http404
    if drop.is_expired():
        drop.hard_delete()
        raise Http404
    drop.touch()
    try:
        url = drop.download_url(expires_in=3600)
    except Exception:
        raise Http404
    return redirect(url)