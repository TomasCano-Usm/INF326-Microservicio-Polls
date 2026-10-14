import os
from typing import Protocol
from urllib.parse import quote

import httpx


class MessagesClientError(Exception):
    """Base error for a failed request to the Messages service."""


class MessagesRejected(MessagesClientError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class MessagesUnavailable(MessagesClientError):
    pass


class ChannelMessagesClient(Protocol):
    async def connect(self) -> None: ...

    async def post_message(self, channel_id: str, user_id: str, content: str) -> None: ...

    async def close(self) -> None: ...


class HttpMessagesClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        configured_url = base_url or os.getenv("MESSAGES_BASE_URL", "")
        self.base_url = configured_url.rstrip("/")
        if not self.base_url:
            raise ValueError("La variable MESSAGES_BASE_URL es obligatoria.")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("MESSAGES_BASE_URL debe comenzar con http:// o https://.")

        self.timeout_seconds = timeout_seconds or float(os.getenv("MESSAGES_TIMEOUT_SECONDS", "5"))
        if self.timeout_seconds <= 0:
            raise ValueError("MESSAGES_TIMEOUT_SECONDS debe ser mayor que cero.")
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(timeout=self.timeout_seconds, transport=self._transport)

    async def post_message(self, channel_id: str, user_id: str, content: str) -> None:
        if self._client is None:
            raise RuntimeError("El cliente de Messages no está conectado.")

        encoded_channel_id = quote(channel_id, safe="")
        url = f"{self.base_url}/api/v1/channels/{encoded_channel_id}/messages"
        body = {"user_id": user_id, "content": content}

        try:
            response = await self._client.post(url, json=body)
        except httpx.RequestError as error:
            raise MessagesUnavailable("No fue posible conectar con Messages.") from error

        if 400 <= response.status_code < 500:
            raise MessagesRejected(response.status_code, self._response_detail(response))
        if not response.is_success:
            raise MessagesUnavailable(
                f"Messages respondió con el estado HTTP {response.status_code}."
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _response_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            body = response.text

        if isinstance(body, dict):
            detail = body.get("detail") or body.get("message")
            if detail:
                return str(detail)
        return str(body)[:500] or f"Messages respondió con el estado HTTP {response.status_code}."
