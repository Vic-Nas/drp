"""
Backblaze B2 storage helpers (S3-compatible via boto3).
"""

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

_client = None
_bucket = None


def _b2():
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
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        _bucket = settings.B2_BUCKET_NAME
    return _client, _bucket


def object_key(ns: str, drop_key: str) -> str:
    return f"drops/{ns}/{drop_key}"


def presigned_put(ns: str, drop_key: str, content_type: str = "application/octet-stream",
                  size: int = 0, expires_in: int = 3600) -> str:
    """
    Generate a presigned PUT URL for direct upload to B2.

    Pass `size` so boto3 includes ContentLength in the signed params —
    B2 requires Content-Length on PUT and will reject the request if the
    header isn't covered by the signature.
    """
    client, bucket = _b2()
    params = {
        "Bucket": bucket,
        "Key": object_key(ns, drop_key),
        "ContentType": content_type,
    }
    if size:
        params["ContentLength"] = size

    url = client.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )
    return url


def presigned_get(ns: str, drop_key: str, filename: str = "",
                  expires_in: int = 3600) -> str:
    client, bucket = _b2()
    params = {
        "Bucket": bucket,
        "Key": object_key(ns, drop_key),
    }
    if filename:
        safe_name = filename.replace('"', "")
        params["ResponseContentDisposition"] = f'attachment; filename="{safe_name}"'

    url = client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expires_in,
    )
    return url


def upload_fileobj(file_obj, ns: str, drop_key: str,
                   content_type: str = "application/octet-stream") -> str:
    from boto3.s3.transfer import TransferConfig

    client, bucket = _b2()
    key = object_key(ns, drop_key)

    config = TransferConfig(
        multipart_threshold=100 * 1024 * 1024,
        multipart_chunksize=50 * 1024 * 1024,
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


def object_exists(ns: str, drop_key: str) -> bool:
    client, bucket = _b2()
    try:
        client.head_object(Bucket=bucket, Key=object_key(ns, drop_key))
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def object_size(ns: str, drop_key: str) -> int:
    client, bucket = _b2()
    try:
        resp = client.head_object(Bucket=bucket, Key=object_key(ns, drop_key))
        return resp.get("ContentLength", 0)
    except ClientError:
        return 0


def delete_object(ns: str, drop_key: str) -> bool:
    import logging
    logger = logging.getLogger(__name__)

    client, bucket = _b2()
    try:
        client.delete_object(Bucket=bucket, Key=object_key(ns, drop_key))
        return True
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchKey"):
            return True
        logger.error("B2 delete failed for %s/%s: %s", ns, drop_key, e)
        return False
    except Exception as e:
        logger.error("B2 delete error for %s/%s: %s", ns, drop_key, e)
        return False