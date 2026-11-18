from __future__ import annotations

import os
from pathlib import Path

import dotenv

dotenv.load_dotenv()


def require_env(env: str) -> str:
    res = os.getenv(env)
    if res is None:
        raise RuntimeError(f'"{env}" is required')

    return res


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


API_ID: int = int(require_env("GIFTS_COLLECT_API_ID"))
API_HASH: str = require_env("GIFTS_COLLECT_API_HASH")

DEVICE_MODEL = "gift_collect"
APP_VERSION = "2.3 K"
SYSTEM_VERSION = "android"

DATA_DIR: Path = Path(os.getenv("GIFTS_COLLECT_DATA_DIR", "./data")).expanduser()
SESSION_DIR: Path = Path(os.getenv("GIFTS_COLLECT_SESSION_DIR", "./sessions"))

SESSION_PATH: Path = SESSION_DIR / "session.string"
RAW_DIR: Path = DATA_DIR / "raw"

def optional_env(name: str) -> str | None:
    return os.getenv(name) or None

S3_BUCKET = optional_env("GIFTS_COLLECT_S3_BUCKET")
S3_ENDPOINT_URL = optional_env("GIFTS_COLLECT_S3_ENDPOINT_URL")
S3_PREFIX = (optional_env("GIFTS_COLLECT_S3_PREFIX") or "raw").strip("/")
S3_ACCESS_KEY_ID = optional_env("GIFTS_COLLECT_S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = optional_env("GIFTS_COLLECT_S3_SECRET_ACCESS_KEY")
S3_REGION = optional_env("GIFTS_COLLECT_S3_REGION")