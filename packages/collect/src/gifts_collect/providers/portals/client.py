import json
from typing import Any, Literal, TypeAlias, Callable, Awaitable
from collections.abc import Mapping, Sequence

import aiohttp
import pydantic
import asyncio

from .types.collections import CollectionsResponse
from .consts import DEFAULT_HEADERS, BASE_URL

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


class RateLimitError(APIError):
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
    def __init__(self, *, auth_provider: AuthProvider | None = None) -> None:
        self._provider = auth_provider
        self._auth_lock = asyncio.Lock()
        self._auth = None
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    @staticmethod
    def raise_for_error(status: int, data: Any) -> None:
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

        raise error_class(status, message, payload=data)

    async def _authorize(self, *, stale: str | None = None) -> str:
        async with self._auth_lock:
            if self._auth is None or self._auth == stale:
                if self._provider is None:
                    raise AuthenticationError(401, "auth missing", payload=None)
                self._auth = await self._provider()
            return self._auth

    QueryValue: TypeAlias = str | int | float | bool | None
    async def _get(self, action: str, *, params=None) -> Any:
        if self.session is None or self.session.closed:
            raise ClientInitializeError()
        query = {k: str(v).lower() if isinstance(v, bool) else v
                 for k, v in (params or {}).items() if v is not None}
        url = f"{BASE_URL}{action.lstrip('/')}"

        token = await self._authorize() if self._provider else None
        try:
            return await self._send(url, query, token)
        except AuthenticationError:
            if token is None or self._provider is None:
                raise
            token = await self._authorize(stale=token)
            return await self._send(url, query, token)

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
                self.raise_for_error(response.status, data)
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
    ):
        return await self._get(
            "market/actions/",
            params={
                "offset": offset,
                "limit": limit,
                "action_types": ",".join(action_types) if action_types else None,
            },
        )
