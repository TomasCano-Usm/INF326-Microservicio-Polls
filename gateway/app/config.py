from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_SERVICE_URLS = {
    "polls": "http://localhost:8004",
    "users": "http://localhost:8001",
    "channels": "http://localhost:8002",
    "messages": "http://localhost:8003",
    "reactions": "http://localhost:8000",
    "search": "http://localhost:8000",
}


@dataclass(frozen=True)
class Settings:
    service_urls: dict[str, str]
    timeout_seconds: float
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> Settings:
        urls = {
            service: os.getenv(f"{service.upper()}_SERVICE_URL", default)
            for service, default in DEFAULT_SERVICE_URLS.items()
        }
        for service, url in urls.items():
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"{service.upper()}_SERVICE_URL must be an HTTP(S) URL")

        timeout = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "5"))
        if timeout <= 0:
            raise ValueError("UPSTREAM_TIMEOUT_SECONDS must be greater than zero")

        cors_origins = tuple(
            origin.strip()
            for origin in os.getenv("GATEWAY_CORS_ORIGINS", "").split(",")
            if origin.strip()
        )

        return cls(
            service_urls=urls,
            timeout_seconds=timeout,
            cors_origins=cors_origins,
        )
