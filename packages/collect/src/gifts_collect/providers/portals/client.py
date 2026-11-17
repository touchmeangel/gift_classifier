import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypeAlias

import aiohttp
import pydantic

from .types.collections import CollectionsResponse

BASE_URL = "https://portal-market.com/api/"

USER_AGENT = "Mozilla/5.0 (Linux; Android 10; SM-G980F Build/QP1A.190711.020; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/80.0.3987.149 Mobile Safari/537.36"


DEFAULT_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/jxl,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "User-Agent": USER_AGENT,
}


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


class Client:
    def __init__(self, *, cf_clearance: str | None = None) -> None:
        self.cf_clearance = cf_clearance
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

    def cookies(self) -> dict:
        cookies = {}

        if self.cf_clearance is not None:
            cookies["cf_clearance"] = self.cf_clearance

        return cookies

    QueryValue: TypeAlias = str | int | float | bool | None

    async def _get(
        self,
        action: str,
        *,
        params: Mapping[str, QueryValue] | None = None,
    ) -> Any:
        if self.session is None or self.session.closed:
            raise ClientInitializeError()

        query = {
            key: str(value).lower() if isinstance(value, bool) else value
            for key, value in (params or {}).items()
            if value is not None
        }

        url = f"{BASE_URL}{action.lstrip('/')}"

        try:
            async with self.session.get(
                url,
                params=query,
                headers=DEFAULT_HEADERS,
                cookies=self.cookies(),
            ) as response:
                raw = await response.text()

                try:
                    data = json.loads(raw) if raw else None
                except json.JSONDecodeError:
                    data = raw

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
