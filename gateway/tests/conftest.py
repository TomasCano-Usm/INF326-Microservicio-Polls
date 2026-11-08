from __future__ import annotations

import asyncio
from typing import Any, Callable

import httpx
import pytest

from gateway.app.config import Settings
from gateway.app.main import create_app
from gateway.app.upstreams import Upstreams


SERVICE_URLS = {
    "polls": "http://polls.test",
    "users": "http://users.test",
    "channels": "http://channels.test",
    "messages": "http://messages.test",
    "reactions": "http://reactions.test",
    "search": "http://search.test",
}


def execute_graphql(
    handler: Callable[[httpx.Request], httpx.Response],
    query: str,
    variables: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    async def run() -> dict[str, Any]:
        upstreams = Upstreams(
            Settings(service_urls=SERVICE_URLS, timeout_seconds=0.5),
            transport=httpx.MockTransport(record),
        )
        app = create_app(upstreams)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://gateway.test",
            ) as client:
                response = await client.post(
                    "/graphql/",
                    json={"query": query, "variables": variables or {}},
                )
                assert response.status_code == 200
                return response.json()

    result = asyncio.run(run())
    return result, requests


def json_response(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


@pytest.fixture
def service_urls() -> dict[str, str]:
    return SERVICE_URLS.copy()
