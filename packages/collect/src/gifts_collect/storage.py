from __future__ import annotations

import gzip
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

log = logging.getLogger(__name__)

DATE_FOLDER_PREFIX = "date="

def date_folder(date: datetime) -> str:
    return f"{DATE_FOLDER_PREFIX}{date:%Y-%m-%d}"


class RawStore:
    def __init__(self, root: Path, source: str) -> None:
        self.root = root
        self.source = source

    def write(
        self, endpoint: str, payload: Any, fetched_at: datetime | None = None
    ) -> Path:
        ts = fetched_at or datetime.now(UTC)
        stamp = f"{ts:%Y%m%dT%H%M%S_%f}Z"
        path = self.root / self.source / endpoint / date_folder(ts) / f"{stamp}.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "schema_version": 1,
            "source": self.source,
            "endpoint": endpoint,
            "fetched_at": ts.isoformat(),
            "payload": payload,
        }
        data = gzip.compress(
            json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return path


class S3Uploader:
    def __init__(
        self,
        bucket: str,
        prefix: str,
        endpoint_url: str | None = None,
        access_key_id=None,
        secret_access_key=None,
        region=None,
    ) -> None:

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


def sync_pending(root: Path, uploader: S3Uploader, max_files: int = 500) -> tuple[int, int]:
    uploaded = failed = 0
    for path in sorted(root.rglob("*.json.gz")):
        key = uploader.key_for(root, path)
        try:
            uploader.upload(path, key)
        except (BotoCoreError, ClientError) as e:
            failed += 1
            log.warning("upload failed for %s: %s", key, e)
            if failed >= 3:
                break
            continue
        path.unlink()
        uploaded += 1
        if uploaded >= max_files:
            break
    return uploaded, failed