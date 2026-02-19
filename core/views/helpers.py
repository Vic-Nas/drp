"""
Shared helpers: rate limiting, plan limits, Cloudinary, key generation,
anon drop claiming.
"""

import secrets

import cloudinary.uploader
from django.core.cache import cache
from django.db import models as db_models

from core.models import Drop, Plan, UserProfile


# ── IP / rate limiting ────────────────────────────────────────────────────────

def client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')


def check_signup_rate(request):
    """Max 3 signups per IP per hour. Returns True if allowed."""
    key = f'signup_rate:{client_ip(request)}'
    count = cache.get(key, 0)
    if count >= 3:
        return False
    cache.set(key, count + 1, timeout=3600)
    return True


# ── Plan helpers ──────────────────────────────────────────────────────────────

def user_plan(user):
    if not user.is_authenticated:
        return Plan.ANON
    return getattr(getattr(user, 'profile', None), 'plan', Plan.FREE)


def max_file_bytes(user):
    return Plan.get(user_plan(user), 'max_file_mb') * 1024 * 1024


def max_text_bytes(user):
    return Plan.get(user_plan(user), 'max_text_kb') * 1024


def storage_ok(user, extra_bytes):
    if not user.is_authenticated:
        return True
    profile = getattr(user, 'profile', None)
    if not profile:
        return True
    quota = profile.storage_quota_bytes
    if quota is None:
        return True
    return (profile.storage_used_bytes + extra_bytes) <= quota


def is_paid_user(user):
    return user.is_authenticated and user_plan(user) in (Plan.STARTER, Plan.PRO)


def max_lifetime_secs(user, ns):
    """
    Max total lifetime in seconds for activity-based expiry.
    Only applies to clipboard (ns='c') anon/free drops.
    """
    if ns != Drop.NS_CLIPBOARD:
        return None
    plan = user_plan(user)
    if plan == Plan.ANON:
        return 7 * 24 * 3600
    if plan == Plan.FREE:
        return 30 * 24 * 3600
    return None


# ── Key generation ────────────────────────────────────────────────────────────

def gen_key(ns):
    key = secrets.token_urlsafe(6)
    while Drop.objects.filter(ns=ns, key=key).exists():
        key = secrets.token_urlsafe(6)
    return key


# ── Cloudinary ────────────────────────────────────────────────────────────────

def upload_to_cloudinary(file_obj, public_id):
    """Upload a file. Returns (secure_url, public_id) or raises."""
    result = cloudinary.uploader.upload(
        file_obj,
        resource_type='raw',
        public_id=public_id,
        overwrite=True,
    )
    return result['secure_url'], result['public_id']


def destroy_cloudinary(public_id):
    """Delete a file from Cloudinary. Silently ignores errors."""
    if not public_id:
        return
    try:
        cloudinary.uploader.destroy(public_id, resource_type='raw')
    except Exception:
        pass


# ── Storage accounting ────────────────────────────────────────────────────────

def add_storage(user, bytes_delta):
    if user and user.is_authenticated and bytes_delta:
        UserProfile.objects.filter(user=user).update(
            storage_used_bytes=db_models.F('storage_used_bytes') + bytes_delta
        )


def sub_storage(owner_id, bytes_amount):
    if owner_id and bytes_amount:
        UserProfile.objects.filter(user_id=owner_id).update(
            storage_used_bytes=db_models.F('storage_used_bytes') - bytes_amount
        )


# ── Anon drop claiming ────────────────────────────────────────────────────────

def claim_anon_drops(user, token):
    """
    Reassign all unclaimed anon drops with the given token to user.
    Upgrades their lifetime to free-tier limits and locks them to the account.
    Returns the number of drops claimed.
    """
    if not token:
        return 0
    drops = Drop.objects.filter(anon_token=token, owner=None)
    count = drops.count()
    if not count:
        return 0
    drops.update(
        owner=user,
        locked=True,
        locked_until=None,
        anon_token=None,
        # Extend clipboard max lifetime to free tier (files already have no secs cap)
        max_lifetime_secs=db_models.Case(
            db_models.When(ns=Drop.NS_CLIPBOARD, then=30 * 24 * 3600),
            default=None,
            output_field=db_models.IntegerField(),
        ),
    )
    return count