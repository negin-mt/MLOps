from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
import pandas as pd


_CLIENT: Any | None = None


def is_s3_uri(uri: str) -> bool:
    return uri.startswith("s3://")


def parse_s3_uri(uri: str) -> tuple[str, str]:
    if not is_s3_uri(uri):
        raise ValueError(f"Unsupported URI: {uri}")
    remainder = uri[5:]
    bucket, _, key = remainder.partition("/")
    return bucket, key


def s3_client() -> Any:
    global _CLIENT
    if _CLIENT is None:
        endpoint = os.getenv("OBJECT_STORAGE_ENDPOINT", "http://minio.platform.svc.cluster.local:9000")
        secure = os.getenv("OBJECT_STORAGE_SECURE", "false").lower() == "true"
        _CLIENT = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.getenv("OBJECT_STORAGE_ACCESS_KEY", ""),
            aws_secret_access_key=os.getenv("OBJECT_STORAGE_SECRET_KEY", ""),
            region_name="us-east-1",
            use_ssl=secure,
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
    return _CLIENT


def get_bytes(uri: str) -> bytes:
    if is_s3_uri(uri):
        bucket, key = parse_s3_uri(uri)
        response = s3_client().get_object(Bucket=bucket, Key=key)
        return response["Body"].read()
    return Path(uri).read_bytes()


def put_bytes(uri: str, payload: bytes, content_type: str = "application/octet-stream") -> None:
    if is_s3_uri(uri):
        bucket, key = parse_s3_uri(uri)
        s3_client().put_object(Bucket=bucket, Key=key, Body=payload, ContentType=content_type)
        return
    Path(uri).parent.mkdir(parents=True, exist_ok=True)
    Path(uri).write_bytes(payload)


def put_json(uri: str, payload: dict[str, Any]) -> None:
    put_bytes(uri, json.dumps(payload, indent=2).encode("utf-8"), "application/json")


def read_csv(uri: str) -> pd.DataFrame:
    if is_s3_uri(uri):
        return pd.read_csv(BytesIO(get_bytes(uri)))
    return pd.read_csv(uri)


def list_objects(bucket: str, prefix: str) -> list[dict[str, Any]]:
    try:
        response = s3_client().list_objects_v2(Bucket=bucket, Prefix=prefix)
    except ClientError:
        return []
    items = [item for item in response.get("Contents", []) if not item["Key"].endswith("/")]
    return sorted(items, key=lambda entry: entry["LastModified"], reverse=True)

