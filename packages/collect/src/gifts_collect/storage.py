from __future__ import annotations

import gzip
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

log = logging.getLogger(__name__)

DATE_FOLDER_PREFIX = "date="

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def date_folder(date: datetime) -> str:
    return f"{DATE_FOLDER_PREFIX}{date:%Y-%m-%d}"

class RawStore:
    def __init__(self, root: Path, source: str) -> None:
        self.root = root
        self.source = source

    def write(self, endpoint: str, payload: Any, fetched_at: datetime | None = None) -> Path:
        ts = fetched_at or utc_now()
        stamp = f"{ts:%Y%m%dT%H%M%S_%f}Z"
        path = (self.root / self.source / endpoint / date_folder(ts) / f"{stamp}.json.gz")
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "schema_version": 1,
            "source": self.source,
            "endpoint": endpoint,
            "fetched_at": ts.isoformat(),
            "payload": payload,
        }
        data = gzip.compress(
            json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return path


class S3Uploader:
    def __init__(self, bucket: str, prefix: str, endpoint_url: str | None = None, access_key_id=None, secret_access_key=None, region=None) -> None:
        self.bucket = bucket
        self.prefix = prefix
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=Config(
                retries={"max_attempts": 5, "mode": "standard"},
                connect_timeout=10,
                read_timeout=60,
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def key_for(self, root: Path, path: Path) -> str:
        rel = path.relative_to(root).as_posix()
        return f"{self.prefix}/{rel}" if self.prefix else rel

    def upload(self, path: Path, key: str) -> None:
        self.client.upload_file(str(path), self.bucket, key)

    def list_keys(self, prefix: str) -> set[str]:
        keys: set[str] = set()
        pages = self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix)
        for page in pages:
            keys.update(obj["Key"] for obj in page.get("Contents", []))
        return keys

def sync_pending(root: Path, uploader: S3Uploader, days_back: int | None = 3, max_files: int = 500) -> tuple[int, int]:
    cutoff = ""
    if days_back is not None:
        cutoff = date_folder(utc_now() - timedelta(days=days_back))
    uploaded = failed = 0
    for part in sorted(root.glob(f"*/*/{DATE_FOLDER_PREFIX}*"), reverse=True):
        if part.name < cutoff:
            continue
        try:
            remote = uploader.list_keys(uploader.key_for(root, part) + "/")
        except (BotoCoreError, ClientError) as e:
            log.warning("listing failed for %s: %s", part, e)
            return uploaded, failed + 1
        for path in sorted(part.glob("*.json.gz")):
            key = uploader.key_for(root, path)
            if key in remote:
                continue
            try:
                uploader.upload(path, key)
            except (BotoCoreError, ClientError) as e:
                failed += 1
                log.warning("upload failed for %s: %s", key, e)
                if failed >= 3:
                    return uploaded, failed
                continue
            uploaded += 1
            if uploaded >= max_files:
                return uploaded, failed
    return uploaded, failed