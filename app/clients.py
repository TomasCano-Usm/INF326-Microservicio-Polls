"""Clientes HTTP para servicios del chat base (Users, Channels)."""
import logging
import os
from typing import Protocol
from urllib.parse import quote

import httpx


logger = logging.getLogger(__name__)


class ReferenceClientError(Exception):
    """Error base para fallos al validar referencias."""


class ReferenceNotFound(ReferenceClientError):
    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(f"{resource} {resource_id} no encontrado")
        self.resource = resource
        self.resource_id = resource_id


class ReferenceServiceUnavailable(ReferenceClientError):
    def __init__(self, service: str) -> None:
        super().__init__(f"Servicio {service} no disponible")
        self.service = service


class ReferenceClient(Protocol):
    enabled: bool

    async def connect(self) -> None: ...

    async def validate_user(self, user_id: str) -> None: ...

    async def validate_channel(self, channel_id: str) -> None: ...

    async def close(self) -> None: ...


class HttpReferenceClient:
    enabled = True

    def __init__(
        self,
        users_base_url: str | None = None,
        channels_base_url: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.users_base_url = (users_base_url or os.getenv("USERS_BASE_URL", "")).rstrip("/")
        self.channels_base_url = (channels_base_url or os.getenv("CHANNELS_BASE_URL", "")).rstrip("/")
        if not self.users_base_url:
            raise ValueError("USERS_BASE_URL es obligatoria cuando REFERENCES_ENABLED=true")
        if not self.channels_base_url:
            raise ValueError("CHANNELS_BASE_URL es obligatoria cuando REFERENCES_ENABLED=true")
        if not self.users_base_url.startswith(("http://", "https://")):
            raise ValueError("USERS_BASE_URL debe comenzar con http:// o https://")
        if not self.channels_base_url.startswith(("http://", "https://")):
            raise ValueError("CHANNELS_BASE_URL debe comenzar con http:// o https://")

        self.timeout_seconds = timeout_seconds or float(os.getenv("REFERENCES_TIMEOUT_SECONDS", "5"))
        if self.timeout_seconds <= 0:
            raise ValueError("REFERENCES_TIMEOUT_SECONDS debe ser mayor que cero")

        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(timeout=self.timeout_seconds, transport=self._transport)

    async def validate_user(self, user_id: str) -> None:
        if self._client is None:
            raise RuntimeError("El cliente de referencias no está conectado")
        encoded_id = quote(user_id, safe="")
        url = f"{self.users_base_url}/api/v1/users/{encoded_id}"
        try:
            response = await self._client.get(url)
        except httpx.RequestError as error:
            raise ReferenceServiceUnavailable("users") from error
        if response.status_code == 404:
            raise ReferenceNotFound("Usuario", user_id)
        if 400 <= response.status_code < 500:
            raise ReferenceNotFound("Usuario", user_id)
        if not response.is_success:
            raise ReferenceServiceUnavailable("users")

    async def validate_channel(self, channel_id: str) -> None:
        if self._client is None:
            raise RuntimeError("El cliente de referencias no está conectado")
        encoded_id = quote(channel_id, safe="")
        url = f"{self.channels_base_url}/api/v1/channels/{encoded_id}"
        try:
            response = await self._client.get(url)
        except httpx.RequestError as error:
            raise ReferenceServiceUnavailable("channels") from error
        if response.status_code == 404:
            raise ReferenceNotFound("Canal", channel_id)
        if 400 <= response.status_code < 500:
            raise ReferenceNotFound("Canal", channel_id)
        if not response.is_success:
            raise ReferenceServiceUnavailable("channels")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class DisabledReferenceClient:
    enabled = False

    async def connect(self) -> None:
        return None

    async def validate_user(self, user_id: str) -> None:
        logger.info("Validación de usuario omitida (REFERENCES_ENABLED=false): %s", user_id)
        return None

    async def validate_channel(self, channel_id: str) -> None:
        logger.info("Validación de canal omitida (REFERENCES_ENABLED=false): %s", channel_id)
        return None

    async def close(self) -> None:
        return None


def reference_client_from_env() -> ReferenceClient:
    configured_value = os.getenv("REFERENCES_ENABLED", "false").strip().lower()
    if configured_value == "false":
        return DisabledReferenceClient()
    if configured_value == "true":
        return HttpReferenceClient()
    raise ValueError("REFERENCES_ENABLED debe ser true o false")