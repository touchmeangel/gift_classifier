from __future__ import annotations

import os
import re
import signal
import struct
from collections.abc import Awaitable, Generator
from contextlib import contextmanager
from typing import TypeVar

from pyrogram import Client, enums
from pyrogram.errors import (
    ApiIdInvalid,
    BadRequest,
    FloodWait,
    Forbidden,
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
from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt

from gifts_collect import config

console = Console()

MAX_CODE_ATTEMPTS = 5
MAX_PASSWORD_ATTEMPTS = 5

_PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")

_DELIVERY = {
    "APP": "Telegram app (check your other device)",
    "SMS": "SMS",
    "CALL": "phone call",
    "FLASH_CALL": "flash call",
    "MISSED_CALL": "missed call (enter the last digits of the caller's number)",
    "EMAIL_CODE": "e-mail",
    "FRAGMENT_SMS": "Fragment",
}

T = TypeVar("T")


class AuthError(Exception):
    """Login could not be completed (banned, rate-limited, offline, ...)."""


class AuthCancelled(AuthError):
    """The user pressed Ctrl+C / Ctrl+D during a prompt."""


def _ok(msg: str) -> None:
    console.print(msg)


def _err(msg: str) -> None:
    console.print(f"[red]{msg}[/]")


def _warn(msg: str) -> None:
    console.print(f"[yellow]{msg}[/]")


def _info(msg: str) -> None:
    console.print(f"[dim]{msg}[/]")


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
    parts = [
        f"{hours}h" if hours else "",
        f"{minutes}m" if minutes else "",
        f"{secs}s" if secs else "",
    ]
    return " ".join(p for p in parts if p)


@contextmanager
def _interruptible() -> Generator[None, None, None]:
    try:
        previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    except ValueError:  # not the main thread
        yield
        return

    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def _ask(label: str, *, password: bool = False) -> str:
    with _interruptible():
        try:
            return Prompt.ask(label, password=password, console=console).strip()
        except (KeyboardInterrupt, EOFError):
            console.print()
            raise AuthCancelled("Login cancelled.") from None


async def _spin(message: str, awaitable: Awaitable[T]) -> T:
    with console.status(f"[dim]{message}[/]", spinner="dots"):
        return await awaitable


def make_client(session_string: str | None = None) -> Client:
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
        _info("No saved session.")
        return False
    _ok("Session removed.")
    return True


def _welcome(user: User) -> None:
    name = " ".join(p for p in (user.first_name, user.last_name) if p) or "Unknown"
    handle = f" [dim]@{escape(user.username)}[/]" if user.username else ""
    console.print(f"Signed in as [bold]{escape(name)}[/]{handle}")


def _ask_phone() -> str:
    _info("Phone number in international format, e.g. +12025550123")
    while True:
        phone = normalize_phone(_ask("Phone"))
        if _PHONE_RE.match(phone):
            return phone
        _err("Invalid number. Start with the country code.")


def _ask_code() -> str | None:
    while True:
        raw = _ask("Code [dim](r to resend)[/]").lower()
        if raw in {"r", "resend"}:
            return None
        digits = re.sub(r"[\s\-]", "", raw)
        if digits.isdigit() and 4 <= len(digits) <= 8:
            return digits
        _err("Enter the digits from the code.")


def _announce_delivery(sent: SentCode) -> None:
    kind = getattr(sent.type, "name", str(sent.type))
    via = _DELIVERY.get(kind, kind.lower().replace("_", " "))
    _info(f"Code sent via {escape(via)}.")


async def _send_code(client: Client, phone: str) -> SentCode:
    try:
        sent = await _spin("Requesting code…", client.send_code(phone))
    except PhoneNumberBanned:
        raise AuthError("This phone number is banned by Telegram.") from None
    except PhoneNumberFlood:
        raise AuthError(
            "Too many login attempts with this number. Try again later."
        ) from None
    except ApiIdInvalid:
        raise AuthError(
            "Telegram rejected the API ID / hash. Check gifts_collect/config.py."
        ) from None
    _announce_delivery(sent)
    return sent


async def _resend_code(client: Client, phone: str, sent: SentCode) -> SentCode:
    try:
        new = await _spin(
            "Resending code…", client.resend_code(phone, sent.phone_code_hash)
        )
    except BadRequest:  # no further delivery method available - start over
        return await _send_code(client, phone)
    _announce_delivery(new)
    return new


async def _two_factor(client: Client) -> User:
    try:
        hint = await client.get_password_hint()
        if hint:
            _info(f"Password hint: {escape(hint)}")
    except RPCError:
        pass

    attempts_left = MAX_PASSWORD_ATTEMPTS
    while attempts_left:
        password = _ask("Password", password=True)
        if not password:
            continue
        try:
            return await _spin("Verifying…", client.check_password(password))
        except PasswordHashInvalid:
            attempts_left -= 1
            if attempts_left:
                _err(f"Incorrect password. {attempts_left} attempt(s) left.")
    raise AuthError("Too many incorrect passwords.")


async def _login(client: Client) -> User:
    while True:
        phone = _ask_phone()
        try:
            sent = await _send_code(client, phone)
            break
        except PhoneNumberInvalid:
            _err("Telegram doesn't recognise that number.")

    attempts_left = MAX_CODE_ATTEMPTS
    while attempts_left:
        code = _ask_code()
        if code is None:
            sent = await _resend_code(client, phone, sent)
            continue
        try:
            result = await _spin(
                "Verifying…", client.sign_in(phone, sent.phone_code_hash, code)
            )
        except SessionPasswordNeeded:
            return await _two_factor(client)
        except PhoneCodeInvalid:
            attempts_left -= 1
            if attempts_left:
                _err(f"Wrong code. {attempts_left} attempt(s) left.")
        except PhoneCodeExpired:
            _warn("Code expired - sending a new one.")
            sent = await _send_code(client, phone)
        except PhoneNumberUnoccupied:
            raise AuthError(
                "No Telegram account exists for this number. Register in the official app first."
            ) from None
        else:
            if isinstance(result, User):
                return result
            raise AuthError(
                "No Telegram account exists for this number. Register in the official app first."
            )
    raise AuthError("Too many invalid codes. Restart the app and try again.")


async def _interactive_login() -> str:
    client = make_client()
    try:
        await _spin("Connecting…", client.connect())
        user = await _login(client)
        session_string = await client.export_session_string()
    finally:
        if client.is_connected:
            await client.disconnect()
    _save_session(session_string)
    _welcome(user)
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


def _forbidden(e: Forbidden) -> AuthError:
    return AuthError(f"Telegram refused the request: {e}")


async def ensure_session() -> str:
    try:
        saved = load_session()
        if saved:
            with console.status("[dim]Checking saved session…[/]", spinner="dots"):
                user = await _check_session(saved)
            if user is not None:
                _welcome(user)
                return saved
            _warn("Saved session is no longer valid - sign in again.")
            try:
                config.SESSION_PATH.unlink()
            except FileNotFoundError:
                pass

        _info("Sign in to Telegram. The session is stored locally.")
        return await _interactive_login()

    except Forbidden as e:
        raise _forbidden(e) from None
    except FloodWait as e:
        raise AuthError(
            f"Telegram asked us to wait {_fmt_wait(e.value)} before retrying."
        ) from None
    except (TimeoutError, OSError) as e:
        raise AuthError(
            f"Couldn't reach Telegram ({e.__class__.__name__}). Check your internet connection."
        ) from None
