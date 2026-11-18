from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import UTC, datetime, timedelta

from pyrogram.errors import FloodWait

from gifts_collect import config
from gifts_collect.auth_ui import require_session
from gifts_collect.providers.portals.client import PortalsAPI
from gifts_collect.providers.portals.telegram_auth import telegram_provider
from gifts_collect.storage import RawStore, S3Uploader, sync_pending

log = logging.getLogger(__name__)
SOURCE = "portals"
MAX_CONSECUTIVE_FAILURES = 5

OVERLAP = timedelta(minutes=1)

async def collect_actions(
    client: PortalsAPI,
    store: RawStore,
    last_seen: datetime,
    page_size: int = 20,
    max_pages: int = 50,
) -> tuple[datetime, int]:
    newest, reached = last_seen, False
    amount_collected = 0

    for page in range(max_pages):
        offset = page * page_size
        resp = await client.actions(action_types=["buy", "sell"], limit=page_size, offset=offset)

        if not resp.actions:
            reached = True
            break

        store.write("actions", resp.model_dump(mode="json"))
        amount_collected += len(resp.actions)

        times = [a.created_at for a in resp.actions]
        newest = max(times) if newest is None else max(newest, *times)

        if min(times) <= last_seen - OVERLAP:
            reached = True
            break

    if not reached:
        log.warning("page cap hit before reaching last seen action: possible gap")

    return newest, amount_collected


async def collect_once(
    client: PortalsAPI, store: RawStore, last_seen: datetime | None
) -> datetime:
    collections = await client.collections()
    store.write("collections", collections.model_dump(mode="json"))
    if last_seen is None:
        last_seen = datetime.now(UTC)
        log.info(
            "saved %d collections, listening for actions",
            len(collections.collections),
        )
    else:
        last_seen, amount_actions = await collect_actions(client, store, last_seen)
        log.info(
            "saved %d collections, %d actions",
            len(collections.collections),
            amount_actions,
        )
    return last_seen


async def collect(*, once: bool, interval: int) -> int:
    session_string = await require_session()
    config.ensure_dirs()
    store = RawStore(config.RAW_DIR, SOURCE)
    uploader = (
        S3Uploader(
            config.S3_BUCKET,
            config.S3_PREFIX,
            config.S3_ENDPOINT_URL,
            config.S3_ACCESS_KEY_ID,
            config.S3_SECRET_ACCESS_KEY,
            config.S3_REGION,
        )
        if config.S3_BUCKET
        else None
    )
    if uploader is None:
        log.warning("GIFTS_COLLECT_S3_BUCKET not set: saving locally only")

    failures = 0
    async with PortalsAPI(
        auth_provider=telegram_provider(
            config.API_ID,
            config.API_HASH,
            session_string,
            device_model=config.DEVICE_MODEL,
            app_version=config.APP_VERSION,
            system_version=config.SYSTEM_VERSION,
        )
    ) as client:
        last_seen = None
        while True:
            started = time.monotonic()
            try:
                last_seen = await collect_once(client, store, last_seen)
                failures = 0
            except FloodWait as e:
                wait = 0
                if isinstance(e.value, (int, float, str)):
                    try:
                        wait = int(e.value) + 1
                    except ValueError:
                        wait = 0
                log.warning("flood wait: sleeping %ss", wait)
                await asyncio.sleep(wait)
                continue
            except Exception:
                failures += 1
                log.exception(
                    "collection failed (%d/%d)", failures, MAX_CONSECUTIVE_FAILURES
                )
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    return 1

            if uploader is not None:
                up, bad = await asyncio.to_thread(
                    sync_pending, config.RAW_DIR, uploader
                )
                if up or bad:
                    log.info("uploaded %d files, %d failed", up, bad)

            if once:
                return 1 if failures else 0
            jitter = random.uniform(0, 5)  # noqa: S311, safe we dont need cryptographically secure random here
            await asyncio.sleep(
                max(0.0, interval - (time.monotonic() - started)) + jitter
            )
