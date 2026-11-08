from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from ariadne.asgi import GraphQL
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from gateway.app.schema import _context_value, schema
from gateway.app.upstreams import Upstreams


def create_app(upstreams: Upstreams | None = None) -> FastAPI:
    clients = upstreams or Upstreams()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await clients.start()
        try:
            yield
        finally:
            await clients.close()

    app = FastAPI(title="Polls GraphQL Gateway", version="1.0.0", lifespan=lifespan)
    if clients.settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(clients.settings.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Idempotency-Key"],
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": "1.0.0"}

    app.mount(
        "/graphql",
        GraphQL(
            schema,
            context_value=lambda request, data: _context_value(clients, request, data),
            debug=False,
        ),
    )
    return app


app = create_app()
