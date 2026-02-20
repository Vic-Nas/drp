"""
Backblaze B2 storage helpers (S3-compatible via boto3).

All Cloudinary references are gone. This module owns every B2 operation:
  - presigned PUT  (direct upload from client)
  - presigned GET  (direct download to client)
  - object delete
  - multipart-aware upload from a file-like object (server-side, for web flow)

Environment variables required:
  B2_KEY_ID         Application key ID
  B2_APP_KEY        Application key secret
  B2_BUCKET_NAME    e.g. drp-files
  B2_ENDPOINT_URL   e.g. https://s3.us-east-005.backblazeb2.com

The endpoint URL encodes the region — no separate region variable needed.
"""

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# ── Client singleton ──────────────────────────────────────────────────────────

_client = None
_bucket = None


def _b2():
    """Return a cached boto3 S3 client pointed at B2."""
    global _client, _bucket
    if _client is None:
        from django.conf import settings
        _client = boto3.client(
            "s3",
            endpoint_url=settings.B2_ENDPOINT_URL,
            aws_access_key_id=settings.B2_KEY_ID,
            aws_secret_access_key=settings.B2_APP_KEY,
            config=Config(
                signature_version="s3v4",
                # Retry up to 3 times on transient errors
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        _bucket = settings.B2_BUCKET_NAME
    return _client, _bucket


# ── Object key convention ─────────────────────────────────────────────────────

def object_key(ns: str, drop_key: str) -> str:
    """
    Map a drop (ns, key) to a B2 object key.
      ns='f', key='report' → 'drops/f/report'
    Centralised so every call is consistent.
    """
    return f"drops/{ns}/{drop_key}"


# ── Presigned URLs ────────────────────────────────────────────────────────────

def presigned_put(ns: str, drop_key: str, content_type: str = "application/octet-stream",
                  expires_in: int = 3600) -> str:
    """
    Generate a presigned PUT URL the client can use to upload directly to B2.
    The URL expires in `expires_in` seconds (default 1 hour).
    Returns the URL string.
    """
    client, bucket = _b2()
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": bucket,
            "Key": object_key(ns, drop_key),
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )
    return url


def presigned_get(ns: str, drop_key: str, filename: str = "",
                  expires_in: int = 3600) -> str:
    """
    Generate a presigned GET URL for a download.
    Sets Content-Disposition so browsers suggest the original filename.
    Returns the URL string.
    """
    client, bucket = _b2()
    params = {
        "Bucket": bucket,
        "Key": object_key(ns, drop_key),
    }
    if filename:
        # RFC 5987 encoding handled by the browser; ASCII fallback is fine here
        safe_name = filename.replace('"', "")
        params["ResponseContentDisposition"] = f'attachment; filename="{safe_name}"'

    url = client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expires_in,
    )
    return url


# ── Server-side upload (web flow) ─────────────────────────────────────────────

def upload_fileobj(file_obj, ns: str, drop_key: str,
                   content_type: str = "application/octet-stream") -> str:
    """
    Upload a file-like object to B2 from the Django process.
    Uses boto3's managed transfer (multipart above threshold, single PUT below).
    Returns the object key on success, raises on failure.

    This is used by the web /save/ endpoint where the browser POSTs to Django
    and Django streams to B2.  For the CLI direct-upload flow, the client uses
    presigned_put() instead and Django never sees the bytes.
    """
    from boto3.s3.transfer import TransferConfig

    client, bucket = _b2()
    key = object_key(ns, drop_key)

    config = TransferConfig(
        multipart_threshold=100 * 1024 * 1024,   # 100 MB
        multipart_chunksize=50 * 1024 * 1024,    # 50 MB chunks
        max_concurrency=4,
        use_threads=True,
    )

    client.upload_fileobj(
        file_obj,
        bucket,
        key,
        ExtraArgs={"ContentType": content_type},
        Config=config,
    )
    return key


# ── Object existence check ────────────────────────────────────────────────────

def object_exists(ns: str, drop_key: str) -> bool:
    """
    Return True if the object exists in B2.
    Used by /upload/confirm/ to verify the client actually uploaded.
    """
    client, bucket = _b2()
    try:
        client.head_object(Bucket=bucket, Key=object_key(ns, drop_key))
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def object_size(ns: str, drop_key: str) -> int:
    """
    Return the size in bytes of an object in B2.
    Returns 0 if the object doesn't exist.
    """
    client, bucket = _b2()
    try:
        resp = client.head_object(Bucket=bucket, Key=object_key(ns, drop_key))
        return resp.get("ContentLength", 0)
    except ClientError:
        return 0


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_object(ns: str, drop_key: str) -> bool:
    """
    Delete an object from B2. Returns True on success or if already gone.
    Never raises — deletion failures are logged but don't crash the caller.
    """
    import logging
    logger = logging.getLogger(__name__)

    client, bucket = _b2()
    try:
        client.delete_object(Bucket=bucket, Key=object_key(ns, drop_key))
        return True
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchKey"):
            return True  # already gone, that's fine
        logger.error("B2 delete failed for %s/%s: %s", ns, drop_key, e)
        return False
    except Exception as e:
        logger.error("B2 delete error for %s/%s: %s", ns, drop_key, e)
        return False