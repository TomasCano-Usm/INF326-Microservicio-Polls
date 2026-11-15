import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.messages import HttpMessagesClient, MessagesRejected


MESSAGES_CONTRACT_PATH = (
    Path(__file__).parent / "contracts" / "messages-v1.openapi.json"
)


def _path_template_pattern(path_template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^{}]+\})", path_template)
    pattern = "".join(
        "[^/]+" if part.startswith("{") and part.endswith("}") else re.escape(part)
        for part in parts
    )
    return re.compile(f"^{pattern}$")


def _resolve_schema(contract: dict, schema: dict) -> dict:
    reference = schema["$ref"]
    prefix = "#/components/schemas/"
    assert reference.startswith(prefix)
    return contract["components"]["schemas"][reference.removeprefix(prefix)]


def _assert_matches_messages_contract(request: httpx.Request, contract: dict) -> dict:
    paths = contract["paths"]
    matching_paths = [
        path
        for path in paths
        if _path_template_pattern(path).fullmatch(request.url.path)
    ]
    assert len(matching_paths) == 1
    path_template = matching_paths[0]
    operation = paths[path_template][request.method.lower()]
    path_parameters = {
        parameter["name"]: parameter
        for parameter in operation.get("parameters", [])
        if parameter["in"] == "path"
    }
    template_parameters = set(re.findall(r"\{([^{}]+)\}", path_template))
    assert template_parameters == set(path_parameters)
    assert all(parameter["required"] for parameter in path_parameters.values())

    assert request.headers["content-type"].startswith("application/json")
    body = json.loads(request.content)
    request_spec = operation["requestBody"]["content"]["application/json"]["schema"]
    body_schema = _resolve_schema(contract, request_spec)
    properties = body_schema["properties"]
    assert set(body_schema["required"]).issubset(body)
    if body_schema.get("additionalProperties") is False:
        assert set(body).issubset(properties)

    for name, value in body.items():
        property_schema = properties.get(name)
        if property_schema is None:
            assert body_schema.get("additionalProperties", True) is not False
            continue
        if property_schema["type"] == "string":
            assert isinstance(value, str)
            assert len(value) >= property_schema.get("minLength", 0)
            assert len(value) <= property_schema.get("maxLength", float("inf"))

    assert "201" in operation["responses"]
    return body


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
    contract = json.loads(MESSAGES_CONTRACT_PATH.read_text(encoding="utf-8"))
    requests: list[dict[str, str]] = []

    def messages_stub(request: httpx.Request) -> httpx.Response:
        body = _assert_matches_messages_contract(request, contract)
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
