"""Files in Neon Object Storage: the branch's S3-compatible buckets.

`neon deploy` writes the branch's credentials as the standard AWS variables
(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ENDPOINT_URL_S3, AWS_REGION),
and the bucket is declared in neon.ts (`assets`, private). Storage branches
with the database, so a preview branch sees the files its rows point at.

What lives here: each week's classified offers per branch, as loaded
(`archive_offers`) — neither store's source is a documented API, so the
archive is the record of what the planner was given.
"""

from __future__ import annotations

import io
import logging
import os
from datetime import date
from functools import lru_cache

from cheaprecipe.config import load_keys

log = logging.getLogger(__name__)

DEFAULT_BUCKET = "assets"


def enabled() -> bool:
    load_keys()
    return bool(os.environ.get("AWS_ENDPOINT_URL_S3") and os.environ.get("AWS_ACCESS_KEY_ID"))


def bucket() -> str:
    load_keys()
    return os.environ.get("STORAGE_BUCKET") or DEFAULT_BUCKET


@lru_cache(maxsize=1)
def client():
    import boto3
    from botocore.config import Config

    load_keys()
    return boto3.client(
        "s3",
        endpoint_url=os.environ["AWS_ENDPOINT_URL_S3"],
        region_name=os.environ.get("AWS_REGION"),
        # Neon accepts path-style addressing and SigV4 only.
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def put(key: str, body: bytes, content_type: str) -> None:
    client().put_object(Bucket=bucket(), Key=key, Body=body, ContentType=content_type)


def get(key: str) -> bytes:
    return client().get_object(Bucket=bucket(), Key=key)["Body"].read()


def url(key: str, expires_in: int = 3600) -> str:
    """A presigned GET, so a private object can be shared for a while."""
    return client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket(), "Key": key}, ExpiresIn=expires_in
    )


def list_keys(prefix: str) -> list[str]:
    response = client().list_objects_v2(Bucket=bucket(), Prefix=prefix)
    return [item["Key"] for item in response.get("Contents", [])]


def offers_key(store: str, store_id: str, week: date) -> str:
    return f"offers/{store}/{store_id}/{week.isoformat()}.csv"


def archive_offers(frame, store: str, store_id: str, week: date) -> str | None:
    """Keep the week's classified offers (a DataFrame) as CSV; the key, or
    None when storage is not configured or the upload failed — archiving
    must never stop the refresh."""
    if not enabled():
        return None
    key = offers_key(store, store_id, week)
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    try:
        put(key, buffer.getvalue().encode(), "text/csv; charset=utf-8")
    except Exception:
        log.warning("could not archive the offers to %s/%s", bucket(), key, exc_info=True)
        return None
    log.info("archived %d offers to %s/%s", len(frame), bucket(), key)
    return key
