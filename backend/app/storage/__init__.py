"""``app.storage`` — bytes in and out of an object store.

The factory picks a backend from ``LE_STORAGE_BACKEND`` and is the only place that
choice is made. ``api.deps.get_storage`` and the worker bootstrap call
``get_storage()``; nothing else constructs a backend.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.storage.base import ObjectStorage, StorageStat, StoredObject
from app.storage.local import LocalObjectStorage
from app.storage.s3 import S3ObjectStorage, boto3_available

__all__ = [
    "LocalObjectStorage",
    "ObjectStorage",
    "S3ObjectStorage",
    "StorageStat",
    "StoredObject",
    "boto3_available",
    "build_storage",
    "get_storage",
]

log = get_logger(__name__)


def build_storage(settings: Settings) -> ObjectStorage:
    """Construct the configured backend.

    Raises:
        ConfigurationError: ``LE_STORAGE_BACKEND=s3`` with boto3 absent or no bucket
            set. ★ **Not a degradation** (§11.3): silently falling back to local
            storage when the operator asked for S3 would mean two API replicas each
            writing to their own container filesystem, uploads that succeed and then
            404 from the other replica, and a data-loss surface that surfaces days
            later as "some images are missing". A missing *optional* dependency
            degrades; a missing dependency that an explicit setting **requires** is a
            mistake, and refusing to boot is how it gets found in the first minute.
    """
    if settings.storage_backend == "local":
        storage: ObjectStorage = LocalObjectStorage(settings.storage_local_root)
        log.info("storage.configured", backend="local", root=str(settings.storage_local_root))
        return storage

    if settings.storage_backend == "s3":
        storage = S3ObjectStorage(settings)  # raises ConfigurationError itself
        log.info("storage.configured", backend="s3", bucket=settings.storage_s3_bucket)
        return storage

    raise ConfigurationError(
        f"LE_STORAGE_BACKEND={settings.storage_backend!r} is not a known backend. "
        f"Use 'local' or 's3'."
    )


@lru_cache(maxsize=1)
def get_storage() -> ObjectStorage:
    """The process-wide storage backend. Built once, cached.

    Cached because the S3 client holds a connection pool and rebuilding it per request
    would open a new TLS connection each time; and because ``LocalObjectStorage``
    resolves and creates its root at construction, which is not work worth repeating.
    """
    return build_storage(get_settings())
