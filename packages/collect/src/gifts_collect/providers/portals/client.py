import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Literal, TypeAlias

import aiohttp
import pydantic

from .consts import BASE_URL, DEFAULT_HEADERS
from .types.actions import ActionsResponse
from .types.collections import CollectionsResponse

log = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(
        self,
        status: int,
        message: str,
        *,
        payload: Any = None,
    ) -> None:
        self.status = status
        self.message = message
        self.payload = payload
        super().__init__(f"{status}: {message}")


class RateLimitError(APIError):
    def __init__(
        self,
        status: int,
        message: str,
        *,
        payload: Any = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(status, message, payload=payload)
        self.retry_after = retry_after


class AuthenticationError(APIError):
    pass


class PermissionDeniedError(APIError):
    pass


class NotFoundError(APIError):
    pass


class BadRequestError(APIError):
    pass


class ValidationError(APIError):
    pass


class ServerError(APIError):
    pass


class APIConnectionError(Exception):
    pass


class ClientInitializeError(Exception):
    def __init__(self) -> None:
        super().__init__("Client must be used inside 'async with Client()'")


class ResponseParsingError(Exception):
    pass


AuthProvider = Callable[[], Awaitable[str]]


class PortalsAPI:
    def __init__(
        self,
        *,
        auth_provider: AuthProvider | None = None,
        max_retries: int | None = 8,
        retry_base: float = 5.0,
        retry_max: float = 300.0,
    ) -> None:
        self._provider = auth_provider
        self._auth_lock = asyncio.Lock()
        self._auth = None
        self.session: aiohttp.ClientSession | None = None
        self._max_retries = max_retries
        self._retry_base = retry_base
        self._retry_max = retry_max

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    @staticmethod
    def raise_for_error(
        status: int, data: Any, headers: Mapping[str, str] | None = None
    ) -> None:
        if 200 <= status < 300:
            return

        if isinstance(data, dict):
            message = (
                data.get("message")
                or data.get("detail")
                or data.get("error")
                or str(data)
            )
        else:
            message = str(data) if data is not None else "Unknown API error"

        error_mapping = {
            400: BadRequestError,
            401: AuthenticationError,
            403: PermissionDeniedError,
            404: NotFoundError,
            422: ValidationError,
            429: RateLimitError,
        }

        if status in error_mapping:
            error_class = error_mapping[status]
        elif 500 <= status < 600:
            error_class = ServerError
        else:
            error_class = APIError

        if error_class is RateLimitError:
            raise RateLimitError(
                status, message, payload=data, retry_after=_parse_retry_after(headers)
            )

        raise error_class(status, message, payload=data)

    async def _authorize(self, *, stale: str | None = None) -> str:
        async with self._auth_lock:
            if self._auth is None or self._auth == stale:
                if self._provider is None:
                    raise AuthenticationError(401, "auth missing", payload=None)
                self._auth = await self._provider()
            return self._auth

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self._retry_max)
        delay = self._retry_base * 2 ** (attempt - 1)
        return min(delay * random.uniform(0.8, 1.2), self._retry_max) # noqa: S311, safe we dont need cryptographically secure random here

    QueryValue: TypeAlias = str | int | float | bool | None

    async def _get(self, action: str, *, params=None) -> Any:
        if self.session is None or self.session.closed:
            raise ClientInitializeError()
        query = {
            k: str(v).lower() if isinstance(v, bool) else v
            for k, v in (params or {}).items()
            if v is not None
        }
        url = f"{BASE_URL}{action.lstrip('/')}"

        token = await self._authorize() if self._provider else None
        try:
            return await self._request(url, query, token)
        except AuthenticationError:
            if token is None or self._provider is None:
                raise
            token = await self._authorize(stale=token)
            return await self._request(url, query, token)

    async def _request(self, url: str, query: dict, token: str | None) -> Any:
        attempt = 0
        while True:
            try:
                return await self._send(url, query, token)
            except RateLimitError as exc:
                attempt += 1
                if self._max_retries is not None and attempt > self._max_retries:
                    raise
                delay = self._backoff(attempt, exc.retry_after)
                log.warning(
                    "rate limited on %s, retrying in %.1fs (attempt %d): %s",
                    url,
                    delay,
                    attempt,
                    exc,
                )
                await asyncio.sleep(delay)

    async def _send(self, url: str, query: dict, token: str | None) -> Any:
        if self.session is None or self.session.closed:
            raise ClientInitializeError()
        headers = dict(DEFAULT_HEADERS)
        if token:
            headers["Authorization"] = f"tma {token}"
        try:
            async with self.session.get(url, params=query, headers=headers) as response:
                text = await response.text()
                try:
                    data = json.loads(text) if text else None
                except json.JSONDecodeError:
                    data = text
                self.raise_for_error(response.status, data, headers=response.headers)
                return data
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise APIConnectionError("Failed to communicate with the API") from exc

    async def collections(
        self,
        *,
        offset: int = 0,
        limit: int = 150,
        favorites_only: bool = False,
    ):
        data = await self._get(
            "collections",
            params={
                "offset": offset,
                "limit": limit,
                "favorites_only": favorites_only,
            },
        )

        try:
            return CollectionsResponse.model_validate(data)
        except pydantic.ValidationError as exc:
            raise ResponseParsingError("Unexpected response shape") from exc

    ActionType = Literal[
        "buy", "sell", "lucky_buy", "lucky_craft", "listing", "price_update"
    ]

    async def actions(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        action_types: Sequence[ActionType] | None = None,
    ) -> ActionsResponse:
        data = await self._get(
            "market/actions/",
            params={
                "offset": offset,
                "limit": limit,
                "action_types": ",".join(action_types) if action_types else None,
            },
        )

        try:
            return ActionsResponse.model_validate(data)
        except pydantic.ValidationError as exc:
            raise ResponseParsingError("Unexpected response shape") from exc


def _parse_retry_after(headers: Mapping[str, str] | None) -> float | None:
    value = headers.get("Retry-After") if headers else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
