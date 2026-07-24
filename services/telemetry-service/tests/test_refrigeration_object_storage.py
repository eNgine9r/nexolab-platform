from __future__ import annotations

import hashlib
import os
from uuid import uuid4

import boto3
import pytest

from app.refrigeration.storage import S3ObjectStorage


@pytest.mark.object_storage
def test_s3_object_round_trip_and_signed_url() -> None:
    if os.environ.get("OBJECT_STORAGE_E2E") != "true":
        pytest.skip("OBJECT_STORAGE_E2E is not enabled")

    endpoint = os.environ["OBJECT_STORAGE_ENDPOINT_URL"]
    bucket = os.environ["OBJECT_STORAGE_BUCKET"]
    region = os.environ.get("OBJECT_STORAGE_REGION", "us-east-1")
    access_key = os.environ["OBJECT_STORAGE_ACCESS_KEY_ID"]
    secret_key = os.environ["OBJECT_STORAGE_SECRET_ACCESS_KEY"]
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        client.create_bucket(Bucket=bucket)

    storage = S3ObjectStorage(
        bucket=bucket,
        endpoint_url=endpoint,
        public_endpoint_url=endpoint,
        region=region,
        access_key_id=access_key,
        secret_access_key=secret_key,
        force_path_style=True,
    )
    key = f"ci/{uuid4()}.txt"
    content = b"nexolab refrigeration object storage"
    checksum = hashlib.sha256(content).hexdigest()

    stored = storage.put(
        key=key,
        content=content,
        media_type="text/plain",
        checksum_sha256=checksum,
    )
    assert stored.key == key
    assert stored.etag

    response = client.get_object(Bucket=bucket, Key=key)
    assert response["Body"].read() == content
    assert response["Metadata"]["sha256"] == checksum

    signed_url = storage.signed_get_url(key, expires_seconds=300)
    assert endpoint in signed_url
    assert "X-Amz-Signature=" in signed_url

    storage.delete(key)
    with pytest.raises(client.exceptions.NoSuchKey):
        client.get_object(Bucket=bucket, Key=key)
