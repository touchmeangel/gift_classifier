from collections.abc import Mapping, Sequence
from typing import Any, TypeAlias
import asyncio
import aiohttp
import json

BASE_URL = "https://portal-market.com/api/"

class APIError(Exception):
    """Base exception for API response errors."""

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
    """Connection, DNS, timeout, or other transport-level failure."""

class ClientInitializeError(Exception):
    def __init__(self) -> None:
        super().__init__("Client must be used inside 'async with Client()'")

QueryValue: TypeAlias = str | int | float | bool | None

class Client:    
    def __init__(self,
        *,
        authorization: str | None = None,
        cf_clearance: str | None = None
    ) -> None:
        self.session = aiohttp.ClientSession(base_url=BASE_URL)
        self.headers = {
            "Accept": "application/json, text/plain, */*",
        }

        if authorization:
            self.headers["Authorization"] = authorization

        self.cookies = {}
        if cf_clearance:
            self.cookies["cf_clearance"] = cf_clearance

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
        
        try:
            async with self.session.get(action, params=query, headers=self.headers) as response:
                raw = await response.text()

                try:
                    data = json.loads(raw) if raw else None
                except json.JSONDecodeError:
                    data = raw

                self.raise_for_error(response.status, data)
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise APIConnectionError(
                "Failed to communicate with the API"
            ) from exc
        
    async def __aenter__(self):
        self.session = await self.session.__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
        
    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
            
    async def collections(self, offset: int = 0, limit: int = 150, favorites_only: bool = False):
        return await self._get("/collections", params={ "offset": offset, "limit":limit, "favorites_only":favorites_only })