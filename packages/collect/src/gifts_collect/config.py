from __future__ import annotations

import os
import dotenv
from pathlib import Path

dotenv.load_dotenv()

def require_env(env: str) -> str:
    res = os.getenv(env)
    if res is None:
        raise RuntimeError(f"\"{env}\" is required")
    
    return res

def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

API_ID: int = int(require_env("GIFTS_COLLECT_API_ID"))
API_HASH: str = require_env("GIFTS_COLLECT_API_HASH")

DEVICE_MODEL = "gift_collect"
APP_VERSION = "2.3 K"
SYSTEM_VERSION = "android"

DATA_DIR: Path = Path(
    os.getenv("GIFTS_COLLECT_DATA_DIR", "./data")
).expanduser()
SESSION_DIR: Path = Path(
    os.getenv("GIFTS_COLLECT_SESSION_DIR", "./sessions")
)

SESSION_PATH: Path = SESSION_DIR / "session.string"

