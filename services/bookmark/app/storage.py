import io
import time
from datetime import timedelta
from pathlib import Path

from minio import Minio
import urllib3

from app.config import settings

http_client = urllib3.PoolManager(timeout=urllib3.Timeout(connect=2.0, read=2.0))
internal = Minio(settings.minio_endpoint, access_key=settings.minio_access_key, secret_key=settings.minio_secret_key, secure=False, http_client=http_client)
public = Minio(settings.minio_public_endpoint, access_key=settings.minio_access_key, secret_key=settings.minio_secret_key, secure=False, http_client=http_client)
ROOT = Path(settings.local_storage)
_bucket_checked_at = 0.0
_bucket_ok = False


def ensure_bucket() -> bool:
    global _bucket_checked_at, _bucket_ok
    now = time.monotonic()
    if now - _bucket_checked_at < 15:
        return _bucket_ok
    try:
        if not internal.bucket_exists(settings.minio_bucket):
            internal.make_bucket(settings.minio_bucket)
        _bucket_ok = True
    except Exception:
        _bucket_ok = False
    _bucket_checked_at = now
    return _bucket_ok


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    if ensure_bucket():
        internal.put_object(settings.minio_bucket, key, io.BytesIO(data), len(data), content_type=content_type)
        return
    path = local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def presign(key: str) -> str:
    if not key:
        return ""
    if ensure_bucket():
        return public.presigned_get_object(settings.minio_bucket, key, expires=timedelta(hours=12))
    return f"/api/bookmarks/files/{key}"


def local_path(key: str) -> Path:
    path = (ROOT / key).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError("非法文件路径")
    return path
