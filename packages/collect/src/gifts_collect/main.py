import argparse
import asyncio
import logging
import sys
import time

from gifts_collect.auth_ui import AuthCancelled, AuthError, ensure_session
from gifts_collect.collector import collect

log = logging.getLogger("gifts_collect")


def setup_logging() -> None:
    if sys.stderr.isatty():
        from rich.console import Console
        from rich.logging import RichHandler

        handler: logging.Handler = RichHandler(
            console=Console(stderr=True), show_path=False, rich_tracebacks=True
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
    else:
        handler = logging.StreamHandler()
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        fmt.converter = time.gmtime
        handler.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger("pyrogram").setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(prog="gifts-collect")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("login", help="interactive Telegram login (run once)")
    r = sub.add_parser("collect", help="collect, save locally, upload")
    r.add_argument("--once", action="store_true", help="one cycle then exit")
    r.add_argument("--interval", type=int, default=900, help="seconds between cycles")
    args = parser.parse_args()
    setup_logging()
    try:
        if args.action == "login":
            asyncio.run(ensure_session())
        elif args.action == "collect":
            asyncio.run(collect(once=args.once, interval=args.interval))
    except AuthCancelled:
        sys.exit(130)
    except AuthError as e:
        log.error("%s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
