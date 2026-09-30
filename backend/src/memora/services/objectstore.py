"""Where uploaded bytes actually live.

Two backends behind one interface. Local disk is the default and needs nothing; S3 is what
makes this survive more than one machine — a pod that writes to its own filesystem serves a
file the next pod cannot find, and the bug looks like "images sometimes 404".

`storage_path` on the row keeps its meaning either way: a filesystem path for local, or an
`s3://bucket/key` URI. Old rows are filesystem paths and keep working, so switching the
backend does not orphan what was already uploaded.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from memora.config import get_settings
from memora.core import pools
from memora.core.logging import get_logger

log = get_logger("memora.objectstore")
S3_PREFIX = "s3://"


def s3_enabled() -> bool:
    s = get_settings()
    return bool(getattr(s, "s3_endpoint", "") and getattr(s, "s3_bucket", ""))


def _client() -> Any:
    import boto3
    from botocore.config import Config
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key or None,
        aws_secret_access_key=s.s3_secret_key or None,
        region_name=s.s3_region or "us-east-1",
        # SeaweedFS, MinIO and friends serve one host with the bucket in the path.
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3, "mode": "standard"}),
    )


def _put_sync(key: str, data: bytes, mime: str) -> None:
    s = get_settings()
    c = _client()
    with contextlib.suppress(Exception):        # idempotent: fine if it already exists
        c.create_bucket(Bucket=s.s3_bucket)
    c.put_object(Bucket=s.s3_bucket, Key=key, Body=data, ContentType=mime)


def _get_sync(key: str) -> bytes:
    s = get_settings()
    return _client().get_object(Bucket=s.s3_bucket, Key=key)["Body"].read()


def _delete_sync(key: str) -> None:
    s = get_settings()
    with contextlib.suppress(Exception):
        _client().delete_object(Bucket=s.s3_bucket, Key=key)


async def put(key: str, data: bytes, mime: str, *, local_path: Path | None = None) -> str:
    """Store bytes and return what belongs in `storage_path`."""
    if s3_enabled():
        await pools.to_thread("misc", _put_sync, key, data, mime)
        return f"{S3_PREFIX}{get_settings().s3_bucket}/{key}"
    path = local_path or (get_settings().upload_root / key)
    await pools.to_thread("misc", _write_local, path, data)
    return str(path)


def _write_local(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


async def get(storage_path: str) -> bytes:
    if storage_path.startswith(S3_PREFIX):
        _, key = _split(storage_path)
        return await pools.to_thread("misc", _get_sync, key)
    return await pools.to_thread("misc", Path(storage_path).read_bytes)


async def delete(storage_path: str) -> None:
    if storage_path.startswith(S3_PREFIX):
        _, key = _split(storage_path)
        await pools.to_thread("misc", _delete_sync, key)
        return
    with contextlib.suppress(FileNotFoundError, OSError):
        await pools.to_thread("misc", Path(storage_path).unlink)


def _delete_prefix_sync(prefix: str) -> int:
    s = get_settings()
    c = _client()
    n = 0
    token = None
    while True:
        kw: dict[str, Any] = {"Bucket": s.s3_bucket, "Prefix": prefix, "MaxKeys": 1000}
        if token:
            kw["ContinuationToken"] = token
        page = c.list_objects_v2(**kw)
        keys = [{"Key": o["Key"]} for o in page.get("Contents") or []]
        if keys:
            c.delete_objects(Bucket=s.s3_bucket, Delete={"Objects": keys, "Quiet": True})
            n += len(keys)
        if not page.get("IsTruncated"):
            return n
        token = page.get("NextContinuationToken")


async def delete_prefix(prefix: str) -> int:
    """한 사람의 것 전부(``<user_id>/``). 계정을 지울 때 — 디스크만 지우고 S3 에 남겨 두면
    지운 계정의 사진과 문서가 버킷에 영영 남는다."""
    if not prefix or not prefix.endswith("/") or len(prefix) < 10:
        raise ValueError("refusing to delete a short or open prefix")
    if not s3_enabled():
        return 0
    return await pools.to_thread("misc", _delete_prefix_sync, prefix)


def _split(uri: str) -> tuple[str, str]:
    rest = uri[len(S3_PREFIX):]
    bucket, _, key = rest.partition("/")
    return bucket, key


async def health() -> dict[str, Any]:
    """What the admin console shows: which backend is live, and whether it answers."""
    if not s3_enabled():
        root = get_settings().upload_root
        return {"backend": "local", "ok": root.exists(), "detail": str(root)}
    s = get_settings()
    try:
        await pools.to_thread("misc", lambda: _client().head_bucket(Bucket=s.s3_bucket))
        return {"backend": "s3", "ok": True, "detail": f"{s.s3_endpoint}/{s.s3_bucket}"}
    except Exception as e:  # noqa: BLE001
        return {"backend": "s3", "ok": False, "detail": f"{type(e).__name__}: {str(e)[:160]}"}


def _usage_sync() -> dict[str, Any]:
    """Walk the bucket once and total it.

    Paginated and capped: a listing is the only way S3 will answer "how much is in here",
    and an unbounded walk of a large bucket is a diagnostics page becoming an outage.
    """
    s = get_settings()
    c = _client()
    objects = 0
    size = 0
    token: str | None = None
    pages = 0
    while pages < _USAGE_MAX_PAGES:
        kw: dict[str, Any] = {"Bucket": s.s3_bucket, "MaxKeys": 1000}
        if token:
            kw["ContinuationToken"] = token
        r = c.list_objects_v2(**kw)
        for obj in r.get("Contents") or []:
            objects += 1
            size += int(obj.get("Size") or 0)
        pages += 1
        token = r.get("NextContinuationToken")
        if not r.get("IsTruncated") or not token:
            return {"objects": objects, "bytes": size, "complete": True}
    return {"objects": objects, "bytes": size, "complete": False}


#: 10,000 objects is plenty to characterise this install's storage; past that the number is
#: reported as a floor rather than spending the page's budget counting.
_USAGE_MAX_PAGES = 10


async def usage() -> dict[str, Any]:
    return await pools.to_thread("misc", _usage_sync)
