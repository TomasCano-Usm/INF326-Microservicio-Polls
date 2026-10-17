import asyncio
import json

import httpx
import pytest

from app.messages import HttpMessagesClient, MessagesRejected


def test_client_posts_only_messages_contract_fields() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["method"] = request.method
        received["url"] = str(request.url)
        received["body"] = json.loads(request.content)
        return httpx.Response(201, json={"message_id": "message-1"})

    async def run() -> None:
        client = HttpMessagesClient(
            base_url="http://messages:8003",
            transport=httpx.MockTransport(handler),
        )
        await client.connect()
        await client.post_message(
            channel_id="channel-123",
            user_id="user-456",
            content="Encuesta de prueba",
        )
        await client.close()

    asyncio.run(run())

    assert received == {
        "method": "POST",
        "url": "http://messages:8003/api/v1/channels/channel-123/messages",
        "body": {"author_id": "user-456", "content": "Encuesta de prueba"},
    }


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
