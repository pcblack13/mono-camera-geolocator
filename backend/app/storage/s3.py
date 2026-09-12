"""``S3ObjectStorage`` — boto3 / MinIO, opt-in (CONTRACT.md §2.4, §9.5).

★ **boto3 is bound at call time, never at module scope** (§11.3). boto3 is an
*optional* dependency (§9.14), and ``app.storage.__init__`` imports this module in
order to offer the backend at all — so a module-scope ``import boto3`` would make the
whole storage package unimportable on the default, local-backend deployment where
boto3 is deliberately absent. That is precisely the failure §11.3 was written about.

The absence of boto3 is nonetheless **not a degradation** when it is actually needed:
§11.3's table says *"boto3 — only reachable with ``LE_STORAGE_BACKEND=s3``; that is a
configuration error, not a degradation → ``ConfigurationError`` at boot."* An
operator who asked for S3 must not silently get a local directory.
"""

from __future__ import annotations

import hashlib
from contextlib import AbstractContextManager, contextmanager
from importlib.util import find_spec
from typing import Any, BinaryIO, ClassVar, Iterable, Iterator, Mapping

from app.core.config import Settings
from app.core.exceptions import ArtifactReadFailed, ArtifactWriteFailed, ConfigurationError
from app.core.logging import get_logger
from app.storage.base import CHUNK_SIZE, ObjectStorage, StorageStat, StoredObject
from app.storage.keys import validate_key

__all__ = ["S3ObjectStorage", "boto3_available"]

log = get_logger(__name__)


def boto3_available() -> bool:
    """Whether boto3 can be imported, without importing it.

    ``find_spec``, not a try/except import: importing boto3 costs a few hundred
    milliseconds and builds a session registry, and this is called from
    ``/capabilities`` and from the storage factory on a deployment that has already
    decided not to use S3.
    """
    return find_spec("boto3") is not None


class S3ObjectStorage(ObjectStorage):
    """Object storage on S3 or any S3-compatible endpoint (MinIO, R2, Ceph)."""

    backend: ClassVar[str] = "s3"

    def __init__(self, settings: Settings) -> None:
        """
        Raises:
            ConfigurationError: boto3 absent, or no bucket configured. Both at
                construction, i.e. at boot, not at the first upload — an S3
                deployment that starts and then 500s on every write has converted a
                startup check into a customer-facing incident.
        """
        if not boto3_available():
            raise ConfigurationError(
                "LE_STORAGE_BACKEND=s3 requires boto3, which is not installed. "
                "Install it with `pip install landexplorer-backend[s3]`, or set "
                "LE_STORAGE_BACKEND=local."
            )
        if not settings.storage_s3_bucket:
            raise ConfigurationError(
                "LE_STORAGE_BACKEND=s3 requires LE_STORAGE_S3_BUCKET, which is empty."
            )

        self._bucket = settings.storage_s3_bucket
        self._settings = settings
        self._client: Any | None = None
        self._signed_url_ttl = settings.storage_signed_url_ttl_seconds

    def _get_client(self) -> Any:
        """Build the boto3 client on first use, then cache it.

        ★ The import lives here — the call-time binding rule (§11.3). ``__init__``
        proves boto3 is *importable*; this is the first place it is imported.
        """
        if self._client is None:
            import boto3  # noqa: PLC0415 — §11.3 call-time binding, deliberate.
            from botocore.config import Config

            s = self._settings
            self._client = boto3.client(
                "s3",
                region_name=s.storage_s3_region,
                endpoint_url=s.storage_s3_endpoint_url or None,
                aws_access_key_id=s.storage_s3_access_key_id.get_secret_value() or None,
                aws_secret_access_key=s.storage_s3_secret_access_key.get_secret_value() or None,
                config=Config(
                    # Retries are boto3's job and it does them better than we would.
                    # `standard` adds jittered backoff over the legacy mode.
                    retries={"max_attempts": 3, "mode": "standard"},
                    signature_version="s3v4",
                ),
            )
            log.info(
                "storage.s3_client_created",
                bucket=self._bucket,
                endpoint=s.storage_s3_endpoint_url or "aws",
            )
        return self._client

    def put(
        self,
        key: str,
        data: bytes | BinaryIO | Iterable[bytes],
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        validate_key(key)
        client = self._get_client()

        # Buffer to a spooled temp file rather than uploading the stream directly.
        #
        # Two reasons, both non-negotiable: (1) StoredObject.checksum_sha256 is not
        # optional and we must hash the exact bytes stored; (2) boto3's upload_fileobj
        # needs a seekable object to retry a failed part, and a non-seekable stream
        # turns a transient 500 from S3 into a permanently failed upload.
        # SpooledTemporaryFile keeps small objects (thumbnails, exports) entirely in
        # memory and only spills a real original to disk.
        import tempfile

        hasher = hashlib.sha256()
        total = 0
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as buffer:
            for chunk in _iter_chunks(data):
                hasher.update(chunk)
                total += len(chunk)
                buffer.write(chunk)
            buffer.seek(0)

            extra: dict[str, Any] = {}
            if content_type:
                extra["ContentType"] = content_type
            if metadata:
                extra["Metadata"] = dict(metadata)

            try:
                client.upload_fileobj(buffer, self._bucket, key, ExtraArgs=extra or None)
            except Exception as exc:  # noqa: BLE001 — botocore's tree is broad and unstable.
                raise ArtifactWriteFailed(f"Could not write {key!r} to S3.") from exc

        return StoredObject(
            key=key,
            size_bytes=total,
            checksum_sha256=hasher.hexdigest(),
            content_type=content_type,
        )

    def get(self, key: str) -> bytes:
        validate_key(key)
        try:
            response = self._get_client().get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()  # type: ignore[no-any-return]
        except Exception as exc:  # noqa: BLE001
            raise ArtifactReadFailed(f"Could not read {key!r} from S3.") from exc

    @contextmanager
    def _open(self, key: str) -> Iterator[BinaryIO]:
        validate_key(key)
        try:
            response = self._get_client().get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise ArtifactReadFailed(f"Could not open {key!r} from S3.") from exc
        body = response["Body"]
        try:
            yield body
        finally:
            body.close()

    def open(self, key: str) -> AbstractContextManager[BinaryIO]:
        return self._open(key)

    def delete(self, key: str) -> bool:
        validate_key(key)
        existed = self.exists(key)
        try:
            self._get_client().delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise ArtifactWriteFailed(f"Could not delete {key!r} from S3.") from exc
        return existed

    def exists(self, key: str) -> bool:
        return self.stat(key) is not None

    def stat(self, key: str) -> StorageStat | None:
        try:
            validate_key(key)
        except ValueError:
            return None
        try:
            head = self._get_client().head_object(Bucket=self._bucket, Key=key)
        except Exception:  # noqa: BLE001 — a 404 here is an answer, not an error.
            return None
        return StorageStat(
            key=key,
            size_bytes=int(head.get("ContentLength", 0)),
            modified_at=head.get("LastModified"),
            content_type=head.get("ContentType"),
            etag=(head.get("ETag") or "").strip('"') or None,
        )

    def url_for(
        self,
        key: str,
        *,
        expires_in: int | None = None,
        download_name: str | None = None,
    ) -> str | None:
        """A presigned GET URL, so large originals never transit the API process."""
        validate_key(key)
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        if download_name:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
        try:
            return self._get_client().generate_presigned_url(  # type: ignore[no-any-return]
                "get_object",
                Params=params,
                ExpiresIn=expires_in or self._signed_url_ttl,
            )
        except Exception as exc:  # noqa: BLE001
            # Degrade to None rather than raise: None means "no direct URL", and the
            # caller's fallback is to stream the bytes through the API — slower, but
            # the surveyor gets their file.
            log.warning("storage.presign_failed", key=key, error=str(exc))
            return None

    def free_bytes(self) -> int | None:
        """None: an object store's capacity is not a question this process can answer."""
        return None

    def list_prefix(self, prefix: str) -> Iterator[str]:
        paginator = self._get_client().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                yield item["Key"]


def _iter_chunks(data: bytes | BinaryIO | Iterable[bytes]) -> Iterator[bytes]:
    if isinstance(data, bytes):
        yield data
        return
    read = getattr(data, "read", None)
    if callable(read):
        while chunk := read(CHUNK_SIZE):
            yield chunk
        return
    for chunk in data:  # type: ignore[union-attr]
        yield chunk
