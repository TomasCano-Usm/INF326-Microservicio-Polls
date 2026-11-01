import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.messages import HttpMessagesClient, MessagesRejected


def test_client_posts_only_messages_contract_fields() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["method"] = request.method
        received["url"] = str(request.url)
        body = json.loads(request.content)
        assert set(body) == {"author_id", "content"}
        received["body"] = body
        return httpx.Response(201, json={"message_id": "message-1"})

    async def run() -> None:
        client = HttpMessagesClient(
            base_url="http://messages:8003",
            transport=httpx.MockTransport(handler),
        )
        await client.connect()
        await client.post_message(
            channel_id="channel-123",
            author_id="user-456",
            content="Encuesta de prueba",
        )
        await client.close()

    asyncio.run(run())

    assert received == {
        "method": "POST",
        "url": "http://messages:8003/api/v1/channels/channel-123/messages",
        "body": {"author_id": "user-456", "content": "Encuesta de prueba"},
    }


def test_poll_announcement_and_closure_follow_messages_v1_contract(tmp_path) -> None:
    requests: list[dict[str, str]] = []

    def messages_stub(request: httpx.Request) -> httpx.Response:
        if request.method != "POST" or request.url.path != (
            "/api/v1/channels/channel-123/messages"
        ):
            return httpx.Response(404, json={"detail": "Route not found"})

        body = json.loads(request.content)
        if set(body) != {"author_id", "content"}:
            return httpx.Response(
                422,
                json={
                    "detail": [
                        {
                            "loc": ["body", "author_id"],
                            "msg": "Field required",
                        }
                    ]
                },
            )
        if not isinstance(body["author_id"], str) or not isinstance(body["content"], str):
            return httpx.Response(422, json={"detail": "Invalid MessageCreate"})

        requests.append(body)
        return httpx.Response(201, json={"message_id": f"message-{len(requests)}"})

    class StubPublisher:
        async def connect(self) -> None:
            return None

        async def publish(self, *_args, **_kwargs) -> None:
            return None

        async def close(self) -> None:
            return None

    messages_client = HttpMessagesClient(
        base_url="http://messages:8003",
        transport=httpx.MockTransport(messages_stub),
    )
    database_path = tmp_path / "messages-contract.sqlite"
    application = create_app(
        lambda: StubPublisher(),
        lambda: messages_client,
        lambda: Database(f"sqlite+aiosqlite:///{database_path}", create_schema=True),
    )

    with TestClient(application) as client:
        created = client.post(
            "/api/v1/polls",
            json={
                "channel_id": "channel-123",
                "author_id": "author-789",
                "question": "¿Qué alternativa prefieres?",
                "options": ["Alternativa A", "Alternativa B"],
            },
        )
        assert created.status_code == 201

        closed = client.post(
            f"/api/v1/polls/{created.json()['poll_id']}/close",
            json={"author_id": "author-789"},
        )
        assert closed.status_code == 200

    assert len(requests) == 2
    assert all(set(message) == {"author_id", "content"} for message in requests)
    assert all(message["author_id"] == "author-789" for message in requests)
    assert "Nueva encuesta:" in requests[0]["content"]
    assert "Encuesta finalizada:" in requests[1]["content"]


def test_client_preserves_messages_reference_validation_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Canal no encontrado"})

    async def run() -> None:
        client = HttpMessagesClient(
            base_url="http://messages:8003",
            transport=httpx.MockTransport(handler),
        )
        await client.connect()
        try:
            with pytest.raises(MessagesRejected) as error:
                await client.post_message("channel-unknown", "user-456", "Texto")
            assert error.value.status_code == 404
            assert error.value.detail == "Canal no encontrado"
        finally:
            await client.close()

    asyncio.run(run())
