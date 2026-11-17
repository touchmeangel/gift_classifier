from __future__ import annotations

import asyncio
import os
import re
import signal
import struct
from contextlib import contextmanager
from typing import Awaitable, Iterator, TypeVar

from pyrogram import Client, enums
from pyrogram.errors import (
    ApiIdInvalid,
    BadRequest,
    FloodWait,
    PasswordHashInvalid,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberBanned,
    PhoneNumberFlood,
    PhoneNumberInvalid,
    PhoneNumberUnoccupied,
    RPCError,
    SessionPasswordNeeded,
    Unauthorized,
)
from pyrogram.types import SentCode, User
from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from gifts_collect import config

console = Console()

MAX_CODE_ATTEMPTS = 5
MAX_PASSWORD_ATTEMPTS = 5

_PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")

_DELIVERY = {
    "APP": "your Telegram app (check your other logged-in device)",
    "SMS": "SMS",
    "CALL": "a phone call",
    "FLASH_CALL": "a flash call",
    "MISSED_CALL": "a missed call (enter the last digits of the caller's number)",
    "EMAIL_CODE": "e-mail",
    "FRAGMENT_SMS": "Fragment (anonymous number)",
}

T = TypeVar("T")


class AuthError(Exception):
    """Login could not be completed (banned, rate-limited, offline, ...)."""


class AuthCancelled(AuthError):
    """The user pressed Ctrl+C / Ctrl+D during a prompt."""


def _ok(msg: str) -> None:
    console.print(f"[bold green]✔[/] {msg}")


def _err(msg: str) -> None:
    console.print(f"[bold red]✘[/] {msg}")


def _warn(msg: str) -> None:
    console.print(f"[bold yellow]![/] {msg}")


def _info(msg: str) -> None:
    console.print(f"[dim]•[/] {msg}")


def normalize_phone(raw: str) -> str:
    """'+1 (202) 555-0123' / '0012025550123' / '12025550123' -> '+12025550123'."""
    cleaned = re.sub(r"[\s\-().]", "", raw)
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    elif cleaned and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


def mask_phone(phone: str) -> str:
    phone = phone if phone.startswith("+") else f"+{phone}"
    if len(phone) <= 6:
        return phone
    return phone[:4] + "•" * (len(phone) - 6) + phone[-2:]


def _fmt_wait(seconds: object) -> str:
    total = 0
    if isinstance(seconds, (int, float, str)):
        try:
            total = int(seconds)
        except ValueError:
            total = 0
    if total <= 0:
        return "a while"
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    parts = [f"{hours}h" if hours else "", f"{minutes}m" if minutes else "", f"{secs}s" if secs else ""]
    return " ".join(p for p in parts if p)


@contextmanager
def _interruptible() -> Iterator[None]:
    """Let Ctrl+C interrupt a blocking prompt even under ``asyncio.run()``.

    asyncio's own SIGINT handler only *cancels* the main task, which can't take
    effect while we're sitting in ``input()`` - the first Ctrl+C would appear to
    do nothing.
    """
    try:
        previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    except ValueError:  # not the main thread
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous if previous is not None else signal.SIG_DFL)


def _ask(label: str, *, password: bool = False) -> str:
    with _interruptible():
        try:
            return Prompt.ask(label, password=password, console=console).strip()
        except (KeyboardInterrupt, EOFError):
            console.print()
            raise AuthCancelled("Login cancelled.") from None


async def _spin(message: str, awaitable: Awaitable[T]) -> T:
    with console.status(f"[cyan]{message}[/]", spinner="dots"):
        return await awaitable


def make_client(session_string: str | None = None) -> Client:
    """Build a Pyrogram client. Same fingerprint as the Portals auth provider."""
    return Client(
        "tg",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=session_string,
        in_memory=True,
        device_model=config.DEVICE_MODEL,
        app_version=config.APP_VERSION,
        system_version=config.SYSTEM_VERSION,
        client_platform=enums.ClientPlatform.WEB,
        lang_code="en",
        system_lang_code="en",
    )


def load_session() -> str | None:
    try:
        return config.SESSION_PATH.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def _save_session(session_string: str) -> None:
    config.ensure_dirs()
    tmp = config.SESSION_PATH.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(session_string)
    os.replace(tmp, config.SESSION_PATH)


def logout() -> bool:
    try:
        config.SESSION_PATH.unlink()
    except FileNotFoundError:
        _info("No saved session found.")
        return False
    _ok("Local session removed.")
    return True


def _banner() -> None:
    body = Group(
        Text("✈  Gifts Collect", style="bold cyan", justify="center"),
        Text(""),
        Text("A Telegram account is required to continue.", justify="center"),
        Text("Your session is stored locally and never leaves this machine.", style="dim", justify="center"),
    )
    console.print()
    console.print(Align.center(Panel(body, box=box.ROUNDED, border_style="cyan", padding=(1, 4))))
    console.print()


def _welcome(user: User, *, returning: bool) -> None:
    name = " ".join(p for p in (user.first_name, user.last_name) if p) or "Unknown"
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right")
    grid.add_column()
    grid.add_row("Name", f"[bold]{escape(name)}[/]" + (" ⭐" if getattr(user, "is_premium", False) else ""))
    if user.username:
        grid.add_row("Username", f"@{escape(user.username)}")
    grid.add_row("ID", str(user.id))
    if getattr(user, "phone_number", None):
        grid.add_row("Phone", mask_phone(user.phone_number))
    grid.add_row("Session", f"[dim]{escape(str(config.SESSION_PATH))}[/]")
    console.print(
        Panel(
            grid,
            title="[bold green]Welcome back[/]" if returning else "[bold green]Signed in[/]",
            box=box.ROUNDED,
            border_style="green",
            padding=(1, 3),
            expand=False,
        )
    )


def _ask_phone() -> str:
    console.rule("[bold cyan]1 · Phone number[/]", style="cyan")
    console.print("[dim]International format, e.g. +1 202 555 0123[/]")
    while True:
        phone = normalize_phone(_ask("[bold cyan]Phone[/]"))
        if _PHONE_RE.match(phone):
            return phone
        _err("That doesn't look like a valid number. Start with the country code, e.g. [bold]+12025550123[/].")


def _ask_code() -> str | None:
    while True:
        raw = _ask("[bold cyan]Login code[/] [dim](or 'r' to resend)[/]").lower()
        if raw in {"r", "resend"}:
            return None
        digits = re.sub(r"[\s\-]", "", raw)
        if digits.isdigit() and 4 <= len(digits) <= 8:
            return digits
        _err("The code consists of 5-6 digits.")


def _announce_delivery(sent: SentCode) -> None:
    kind = getattr(sent.type, "name", str(sent.type))
    via = _DELIVERY.get(kind, kind.lower().replace("_", " "))
    _ok(f"Code sent via [bold]{escape(via)}[/].")


async def _send_code(client: Client, phone: str) -> SentCode:
    try:
        sent = await _spin("Requesting login code…", client.send_code(phone))
    except PhoneNumberBanned:
        raise AuthError("This phone number is banned by Telegram.") from None
    except PhoneNumberFlood:
        raise AuthError("Too many login attempts with this number. Try again later.") from None
    except ApiIdInvalid:
        raise AuthError("Telegram rejected the API ID / hash. Check gifts_collect/config.py.") from None
    _announce_delivery(sent)
    return sent


async def _resend_code(client: Client, phone: str, sent: SentCode) -> SentCode:
    try:
        new = await _spin("Resending code…", client.resend_code(phone, sent.phone_code_hash))
    except BadRequest:  # no further delivery method available - start over
        return await _send_code(client, phone)
    _announce_delivery(new)
    return new


async def _two_factor(client: Client) -> User:
    console.print()
    console.rule("[bold cyan]3 · Two-step verification[/]", style="cyan")
    console.print("[dim]Your account is protected with a cloud password.[/]")
    try:
        hint = await client.get_password_hint()
        if hint:
            _info(f"Hint: [italic]{escape(hint)}[/]")
    except RPCError:
        pass

    attempts_left = MAX_PASSWORD_ATTEMPTS
    while attempts_left:
        password = _ask("[bold cyan]Password[/] [dim](hidden)[/]", password=True)
        if not password:
            continue
        try:
            return await _spin("Verifying…", client.check_password(password))
        except PasswordHashInvalid:
            attempts_left -= 1
            if attempts_left:
                _err(f"Incorrect password. [dim]{attempts_left} attempt(s) left.[/]")
    raise AuthError("Too many incorrect passwords.")


async def _login(client: Client) -> User:
    while True:
        phone = _ask_phone()
        try:
            sent = await _send_code(client, phone)
            break
        except PhoneNumberInvalid:
            _err("Telegram doesn't recognise that number. Double-check it and try again.")

    console.print()
    console.rule("[bold cyan]2 · Login code[/]", style="cyan")
    attempts_left = MAX_CODE_ATTEMPTS
    while attempts_left:
        code = _ask_code()
        if code is None:
            sent = await _resend_code(client, phone, sent)
            continue
        try:
            result = await _spin("Verifying…", client.sign_in(phone, sent.phone_code_hash, code))
        except SessionPasswordNeeded:
            return await _two_factor(client)  # 3 · optional 2FA
        except PhoneCodeInvalid:
            attempts_left -= 1
            if attempts_left:
                _err(f"Wrong code. [dim]{attempts_left} attempt(s) left.[/]")
        except PhoneCodeExpired:
            _warn("That code has expired - sending a new one.")
            sent = await _send_code(client, phone)
        except PhoneNumberUnoccupied:
            raise AuthError("No Telegram account exists for this number. Register in the official app first.") from None
        else:
            if isinstance(result, User):
                return result
            raise AuthError("No Telegram account exists for this number. Register in the official app first.")
    raise AuthError("Too many invalid codes. Restart the app and try again.")


async def _interactive_login() -> str:
    client = make_client()
    try:
        await _spin("Connecting to Telegram…", client.connect())
        user = await _login(client)
        session_string = await client.export_session_string()
    finally:
        if client.is_connected:
            await client.disconnect()
    _save_session(session_string)
    console.print()
    _welcome(user, returning=False)
    return session_string


async def _check_session(session_string: str) -> User | None:
    client = make_client(session_string)
    try:
        await client.connect()
        return await client.get_me()
    except (Unauthorized, ValueError, struct.error):
        return None
    finally:
        if client.is_connected:
            await client.disconnect()


async def ensure_session() -> str:
    try:
        saved = load_session()
        if saved:
            with console.status("[cyan]Checking saved session…[/]", spinner="dots"):
                user = await _check_session(saved)
            if user is not None:
                _welcome(user, returning=True)
                return saved
            _warn("Saved session is no longer valid - please sign in again.")
            try:
                config.SESSION_PATH.unlink()
            except FileNotFoundError:
                pass

        _banner()
        return await _interactive_login()

    except FloodWait as e:
        raise AuthError(f"Telegram asked us to wait {_fmt_wait(e.value)} before retrying.") from None
    except (OSError, asyncio.TimeoutError) as e:
        raise AuthError(f"Couldn't reach Telegram ({e.__class__.__name__}). Check your internet connection.") from None