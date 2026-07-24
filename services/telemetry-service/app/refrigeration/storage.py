from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ObjectStorageError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    etag: str | None


class ObjectStorage(Protocol):
    def put(self, *, key: str, content: bytes, media_type: str, checksum_sha256: str) -> StoredObject: ...

    def delete(self, key: str) -> None: ...

    def signed_get_url(self, key: str, *, expires_seconds: int) -> str: ...


class UnavailableObjectStorage:
    def put(self, *, key: str, content: bytes, media_type: str, checksum_sha256: str) -> StoredObject:
        raise ObjectStorageError("object storage is not configured")

    def delete(self, key: str) -> None:
        return None

    def signed_get_url(self, key: str, *, expires_seconds: int) -> str:
        raise ObjectStorageError("object storage is not configured")


class InMemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, str]] = {}

    def put(self, *, key: str, content: bytes, media_type: str, checksum_sha256: str) -> StoredObject:
        self.objects[key] = (bytes(content), media_type, checksum_sha256)
        return StoredObject(key=key, etag=f'"{checksum_sha256}"')

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def signed_get_url(self, key: str, *, expires_seconds: int) -> str:
        if key not in self.objects:
            raise ObjectStorageError(f"object {key!r} was not found")
        return f"memory://{key}?expires={expires_seconds}"


class S3ObjectStorage:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        public_endpoint_url: str | None,
        region: str,
        access_key_id: str | None,
        secret_access_key: str | None,
        force_path_style: bool,
    ) -> None:
        import boto3
        from botocore.config import Config

        self._bucket = bucket
        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if force_path_style else "auto"},
        )
        common = {
            "region_name": region,
            "aws_access_key_id": access_key_id or None,
            "aws_secret_access_key": secret_access_key or None,
            "config": config,
        }
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            **common,
        )
        self._signing_client = boto3.client(
            "s3",
            endpoint_url=public_endpoint_url or endpoint_url or None,
            **common,
        )

    def put(self, *, key: str, content: bytes, media_type: str, checksum_sha256: str) -> StoredObject:
        try:
            response = self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=media_type,
                Metadata={"sha256": checksum_sha256},
            )
        except Exception as error:
            raise ObjectStorageError("failed to upload object") from error
        return StoredObject(key=key, etag=response.get("ETag"))

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as error:
            raise ObjectStorageError("failed to delete object") from error

    def signed_get_url(self, key: str, *, expires_seconds: int) -> str:
        try:
            return str(
                self._signing_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._bucket, "Key": key},
                    ExpiresIn=expires_seconds,
                )
            )
        except Exception as error:
            raise ObjectStorageError("failed to sign object URL") from error
