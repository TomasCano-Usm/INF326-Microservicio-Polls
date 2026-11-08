from __future__ import annotations

from typing import Any

import httpx

from gateway.app.config import Settings


class UpstreamError(Exception):
    def __init__(self, service: str, status_code: int | None = None) -> None:
        self.service = service
        self.status_code = status_code
        suffix = f" (HTTP {status_code})" if status_code is not None else " (unavailable)"
        super().__init__(f"The {service} service could not complete the request{suffix}.")


class Upstreams:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.timeout_seconds),
                transport=self._transport,
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        service: str,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str]] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        not_found_is_none: bool = False,
    ) -> Any:
        if self._client is None:
            raise RuntimeError("Upstreams must be started during application lifespan")

        url = f"{self.settings.service_urls[service].rstrip('/')}/{path.lstrip('/')}"
        try:
            response = await self._client.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise UpstreamError(service) from exc

        if response.status_code == 404 and not_found_is_none:
            return None
        if response.is_error:
            raise UpstreamError(service, response.status_code)
        if response.status_code == 204 or not response.content:
            return None

        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(service, response.status_code) from exc
