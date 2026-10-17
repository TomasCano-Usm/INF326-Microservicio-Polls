import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients import (
    DisabledReferenceClient,
    HttpReferenceClient,
    ReferenceNotFound,
    ReferenceServiceUnavailable,
)
from app.db import Database
from app.main import create_app
from app.messages import DisabledMessagesClient, MessagesRejected, MessagesUnavailable


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object], str | None]] = []
        self.fail_on: str | None = None

    async def connect(self) -> None:
        return None

    async def publish(
        self,
        event_type: str,
        payload: dict[str, object],
        event_id: str | None = None,
    ) -> None:
        if event_type == self.fail_on:
            raise RuntimeError("RabbitMQ no disponible")
        self.events.append((event_type, payload, event_id))

    async def close(self) -> None:
        return None


class FakeMessagesClient:
    enabled = True

    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []
        self.failure: Exception | None = None

    async def connect(self) -> None:
        return None

    async def post_message(self, channel_id: str, author_id: str, content: str) -> None:
        if self.failure is not None:
            raise self.failure
        self.requests.append(
            {"channel_id": channel_id, "author_id": author_id, "content": content}
        )

    async def close(self) -> None:
        return None


class FakeReferenceClient:
    enabled = True

    def __init__(self) -> None:
        self.valid_users: set[str] = set()
        self.valid_channels: set[str] = set()
        self.failure: Exception | None = None

    async def connect(self) -> None:
        return None

    async def validate_user(self, user_id: str) -> None:
        if self.failure is not None:
            raise self.failure
        if user_id not in self.valid_users:
            raise ReferenceNotFound("Usuario", user_id)

    async def validate_channel(self, channel_id: str) -> None:
        if self.failure is not None:
            raise self.failure
        if channel_id not in self.valid_channels:
            raise ReferenceNotFound("Canal", channel_id)

    async def close(self) -> None:
        return None


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("POLL_CLOSE_SCAN_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("POLL_RETRY_BASE_SECONDS", "0.05")
    monkeypatch.setenv("MESSAGES_ENABLED", "true")
    publisher = FakePublisher()
    messages = FakeMessagesClient()
    references = FakeReferenceClient()
    references.valid_users = {"user-author", "user-voter", "another-user"}
    references.valid_channels = {"channel-123"}
    database_path = tmp_path / "polls.sqlite"
    application = create_app(
        lambda: publisher,
        lambda: messages,
        lambda: Database(f"sqlite+aiosqlite:///{database_path}", create_schema=True),
        lambda: references,
    )
    with TestClient(application) as client:
        yield client, publisher, messages, references, database_path


def poll_request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "channel_id": "channel-123",
        "author_id": "user-author",
        "question": "¿Qué alternativa prefieres?",
        "options": ["Alternativa A", "Alternativa B"],
    }
    payload.update(overrides)
    return payload


def create_poll(client: TestClient, **headers: str) -> dict[str, object]:
    response = client.post("/api/v1/polls", json=poll_request(), headers=headers)
    assert response.status_code == 201
    return response.json()


def wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_create_persists_poll_and_emits_created_event_after_announcement(api) -> None:
    client, publisher, messages, _references, _database_path = api

    created = create_poll(client)
    response = client.get(f"/api/v1/polls/{created['poll_id']}")

    assert response.status_code == 200
    assert response.json()["status"] == "open"
    assert response.json()["duration_minutes"] == 5
    assert response.json()["total_votes"] == 0
    assert [option["vote_count"] for option in response.json()["options"]] == [0, 0]
    assert wait_for(lambda: any(event[0] == "poll.created" for event in publisher.events))
    assert len(messages.requests) == 1
    announcement = messages.requests[0]
    assert announcement["channel_id"] == "channel-123"
    assert announcement["author_id"] == "user-author"
    assert set(announcement) == {"channel_id", "author_id", "content"}
    assert created["question"] in announcement["content"]
    assert created["poll_id"] in announcement["content"]
    assert all(option["text"] in announcement["content"] for option in created["options"])
    assert "Cierre:" in announcement["content"]


def test_vote_counts_and_rejects_duplicate_voter(api) -> None:
    client, publisher, _messages, _references, _database_path = api
    poll = create_poll(client)
    option_id = poll["options"][0]["option_id"]
    body = {"voter_id": "user-voter", "option_id": option_id}

    vote = client.post(f"/api/v1/polls/{poll['poll_id']}/votes", json=body)
    duplicate = client.post(f"/api/v1/polls/{poll['poll_id']}/votes", json=body)
    result = client.get(f"/api/v1/polls/{poll['poll_id']}").json()

    assert vote.status_code == 201
    assert duplicate.status_code == 409
    assert result["total_votes"] == 1
    assert result["options"][0]["vote_count"] == 1
    assert wait_for(lambda: any(event[0] == "poll.vote.cast" for event in publisher.events))


def test_invalid_option_unknown_poll_and_option_rules(api) -> None:
    client, _publisher, _messages, _references, _database_path = api
    poll = create_poll(client)
    invalid_option = client.post(
        f"/api/v1/polls/{poll['poll_id']}/votes",
        json={"voter_id": "user-voter", "option_id": str(UUID(int=0))},
    )
    missing = client.get(f"/api/v1/polls/{UUID(int=0)}")
    duplicate_labels = client.post(
        "/api/v1/polls",
        json=poll_request(options=[" A ", "a"]),
    )
    too_many_options = client.post(
        "/api/v1/polls",
        json=poll_request(options=[f"Option {index}" for index in range(11)]),
    )
    invalid_duration = client.post("/api/v1/polls", json=poll_request(duration_minutes=1441))

    assert invalid_option.status_code == 422
    assert missing.status_code == 404
    assert duplicate_labels.status_code == 422
    assert too_many_options.status_code == 422
    assert invalid_duration.status_code == 422


def test_idempotency_key_reuses_poll_and_rejects_different_body(api) -> None:
    client, _publisher, messages, _references, _database_path = api
    headers = {"Idempotency-Key": "create-poll-123"}
    first = client.post("/api/v1/polls", json=poll_request(), headers=headers)
    replay = client.post("/api/v1/polls", json=poll_request(), headers=headers)
    changed = client.post(
        "/api/v1/polls",
        json=poll_request(question="Otra pregunta"),
        headers=headers,
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["poll_id"] == first.json()["poll_id"]
    assert changed.status_code == 409
    assert len(messages.requests) == 1


def test_only_author_can_close_and_close_is_idempotent(api) -> None:
    client, publisher, messages, _references, _database_path = api
    poll = create_poll(client)
    close_url = f"/api/v1/polls/{poll['poll_id']}/close"

    forbidden = client.post(close_url, json={"author_id": "another-user"})
    closed = client.post(close_url, json={"author_id": "user-author"})
    repeated = client.post(close_url, json={"author_id": "user-author"})
    vote = client.post(
        f"/api/v1/polls/{poll['poll_id']}/votes",
        json={"voter_id": "user-voter", "option_id": poll["options"][0]["option_id"]},
    )

    assert forbidden.status_code == 403
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert repeated.status_code == 200
    assert vote.status_code == 409
    assert wait_for(lambda: any(event[0] == "poll.closed" for event in publisher.events))
    assert len(messages.requests) == 2
    closure = messages.requests[-1]
    assert closure["channel_id"] == "channel-123"
    assert closure["author_id"] == "user-author"
    assert poll["question"] in closure["content"]
    assert "Total de votos: 0" in closure["content"]
    assert all(option["text"] in closure["content"] for option in poll["options"])


def test_deadline_closes_poll_automatically_and_publishes_results(api) -> None:
    client, publisher, messages, _references, database_path = api
    poll = create_poll(client)
    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime(
        "%Y-%m-%d %H:%M:%S.%f+00:00"
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE polls SET closes_at = ? WHERE poll_id = ?",
            (expired_at, UUID(poll["poll_id"]).hex),
        )

    assert wait_for(lambda: any(event[0] == "poll.closed" for event in publisher.events))
    result = client.get(f"/api/v1/polls/{poll['poll_id']}").json()

    assert result["status"] == "closed"
    assert len(messages.requests) == 2


def test_messages_temporary_failure_returns_202_and_retries(api) -> None:
    client, publisher, messages, _references, _database_path = api
    messages.failure = MessagesUnavailable("Messages no disponible")

    response = client.post(
        "/api/v1/polls",
        json=poll_request(),
        headers={"Idempotency-Key": "pending-announcement"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "pending_announcement"
    assert publisher.events == []
    messages.failure = None

    poll_url = f"/api/v1/polls/{response.json()['poll_id']}"
    assert wait_for(lambda: client.get(poll_url).json()["status"] == "open")
    assert wait_for(lambda: any(event[0] == "poll.created" for event in publisher.events))
    assert len(messages.requests) == 1


def test_messages_rejection_cancels_creation_without_event(api) -> None:
    client, publisher, messages, _references, _database_path = api
    messages.failure = MessagesRejected(404, "Canal no encontrado")

    response = client.post("/api/v1/polls", json=poll_request())

    assert response.status_code == 404
    assert response.json()["detail"] == "Canal no encontrado"
    assert publisher.events == []


def test_failed_created_event_retries_without_reposting_message(api) -> None:
    client, publisher, messages, _references, _database_path = api
    publisher.fail_on = "poll.created"

    created = create_poll(client)
    assert len(messages.requests) == 1
    time.sleep(0.1)
    assert not any(event[0] == "poll.created" for event in publisher.events)

    publisher.fail_on = None
    assert wait_for(lambda: any(event[0] == "poll.created" for event in publisher.events))
    assert len(messages.requests) == 1
    event_ids = [event[2] for event in publisher.events if event[0] == "poll.created"]
    assert len(event_ids) == 1 and event_ids[0]
    assert created["poll_id"] in publisher.events[0][1]["poll_id"]


def test_failed_closure_message_retries_without_duplicate_closed_event(api) -> None:
    client, publisher, messages, _references, _database_path = api
    poll = create_poll(client)
    messages.failure = MessagesUnavailable("Messages no disponible")

    response = client.post(
        f"/api/v1/polls/{poll['poll_id']}/close",
        json={"author_id": "user-author"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert wait_for(lambda: any(event[0] == "poll.closed" for event in publisher.events))
    messages.failure = None
    assert wait_for(lambda: len(messages.requests) == 2)
    assert [event[0] for event in publisher.events].count("poll.closed") == 1


def test_messages_disabled_starts_without_url_and_skips_deliveries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("MESSAGES_ENABLED", "false")
    monkeypatch.setenv("POLL_CLOSE_SCAN_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("POLL_RETRY_BASE_SECONDS", "0.05")
    monkeypatch.delenv("MESSAGES_BASE_URL", raising=False)
    publisher = FakePublisher()
    references = FakeReferenceClient()
    references.valid_users = {"user-author", "user-voter"}
    references.valid_channels = {"channel-123"}
    database_path = tmp_path / "polls-disabled.sqlite"
    application = create_app(
        lambda: publisher,
        database_factory=lambda: Database(
            f"sqlite+aiosqlite:///{database_path}", create_schema=True
        ),
        reference_client_factory=lambda: references,
    )

    with caplog.at_level(logging.INFO, logger="app.service"), TestClient(application) as client:
        assert isinstance(client.app.state.poll_service._messages_client, DisabledMessagesClient)
        poll = create_poll(client)
        closed = client.post(
            f"/api/v1/polls/{poll['poll_id']}/close",
            json={"author_id": "user-author"},
        )
        assert wait_for(lambda: any(event[0] == "poll.created" for event in publisher.events))
        assert wait_for(lambda: any(event[0] == "poll.closed" for event in publisher.events))
        with sqlite3.connect(database_path) as connection:
            deliveries = connection.execute(
                "SELECT kind, status FROM message_deliveries ORDER BY kind"
            ).fetchall()

    assert poll["status"] == "open"
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert caplog.text.count("MESSAGES_ENABLED=false") == 2
    assert deliveries == [("announcement", "skipped"), ("final_results", "skipped")]


def test_messages_enabled_requires_base_url_at_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("MESSAGES_ENABLED", "true")
    monkeypatch.delenv("MESSAGES_BASE_URL", raising=False)
    database_path = tmp_path / "polls-enabled.sqlite"
    application = create_app(
        lambda: FakePublisher(),
        database_factory=lambda: Database(
            f"sqlite+aiosqlite:///{database_path}", create_schema=True
        ),
    )

    with pytest.raises(ValueError, match="MESSAGES_BASE_URL es obligatoria"):
        with TestClient(application):
            pass


def test_messages_enabled_rejects_invalid_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MESSAGES_ENABLED", "sometimes")

    from app.messages import messages_client_from_env

    with pytest.raises(ValueError, match="MESSAGES_ENABLED debe ser true o false"):
        messages_client_from_env()


# --- New tests for reference validation ---

def test_create_poll_rejects_unknown_channel(api) -> None:
    client, _publisher, _messages, references, _database_path = api
    references.valid_channels = {"other-channel"}

    response = client.post("/api/v1/polls", json=poll_request(channel_id="unknown-channel"))

    assert response.status_code == 422
    assert "Canal unknown-channel no encontrado" in response.json()["detail"]


def test_create_poll_rejects_unknown_author(api) -> None:
    client, _publisher, _messages, references, _database_path = api
    references.valid_users = {"other-user"}

    response = client.post("/api/v1/polls", json=poll_request(author_id="unknown-author"))

    assert response.status_code == 422
    assert "Usuario unknown-author no encontrado" in response.json()["detail"]


def test_create_poll_rejects_when_channels_service_unavailable(api) -> None:
    client, _publisher, _messages, references, _database_path = api
    references.failure = ReferenceServiceUnavailable("channels")

    response = client.post("/api/v1/polls", json=poll_request())

    assert response.status_code == 503
    assert "channels" in response.json()["detail"].lower()


def test_create_poll_rejects_when_users_service_unavailable(api) -> None:
    client, _publisher, _messages, references, _database_path = api
    references.failure = ReferenceServiceUnavailable("users")

    response = client.post("/api/v1/polls", json=poll_request())

    assert response.status_code == 503
    assert "users" in response.json()["detail"].lower()


def test_vote_rejects_unknown_voter(api) -> None:
    client, _publisher, _messages, references, _database_path = api
    references.valid_users = {"user-author"}  # voter not in valid set
    poll = create_poll(client)

    response = client.post(
        f"/api/v1/polls/{poll['poll_id']}/votes",
        json={"voter_id": "unknown-voter", "option_id": poll["options"][0]["option_id"]},
    )

    assert response.status_code == 422
    assert "Usuario unknown-voter no encontrado" in response.json()["detail"]


def test_vote_rejects_when_users_service_unavailable(api) -> None:
    client, _publisher, _messages, references, _database_path = api
    # Create poll first (with working references)
    poll = create_poll(client)
    # Then make users service unavailable for the vote
    references.failure = ReferenceServiceUnavailable("users")

    response = client.post(
        f"/api/v1/polls/{poll['poll_id']}/votes",
        json={"voter_id": "user-voter", "option_id": poll["options"][0]["option_id"]},
    )

    assert response.status_code == 503
    assert "users" in response.json()["detail"].lower()


def test_references_disabled_skips_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("MESSAGES_ENABLED", "true")
    monkeypatch.setenv("REFERENCES_ENABLED", "false")
    monkeypatch.delenv("USERS_BASE_URL", raising=False)
    monkeypatch.delenv("CHANNELS_BASE_URL", raising=False)
    monkeypatch.setenv("POLL_CLOSE_SCAN_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("POLL_RETRY_BASE_SECONDS", "0.05")

    publisher = FakePublisher()
    messages = FakeMessagesClient()
    database_path = tmp_path / "polls-refs-disabled.sqlite"
    application = create_app(
        lambda: publisher,
        lambda: messages,
        lambda: Database(f"sqlite+aiosqlite:///{database_path}", create_schema=True),
        lambda: DisabledReferenceClient(),
    )

    with caplog.at_level(logging.INFO, logger="app.clients"), TestClient(application) as client:
        assert isinstance(client.app.state.poll_service._reference_client, DisabledReferenceClient)
        # Should work even though no valid users/channels configured
        poll = create_poll(client)
        vote = client.post(
            f"/api/v1/polls/{poll['poll_id']}/votes",
            json={"voter_id": "any-voter", "option_id": poll["options"][0]["option_id"]},
        )
        assert vote.status_code == 201


# --- New tests for list_polls endpoint ---

def test_list_polls_by_channel(api) -> None:
    client, _publisher, _messages, _references, _database_path = api
    # Create a few polls
    poll1 = create_poll(client)
    poll2 = create_poll(client, question="Segunda encuesta")
    poll3 = create_poll(client, question="Tercera encuesta")

    response = client.get("/api/v1/polls", params={"channel_id": "channel-123"})

    assert response.status_code == 200
    data = response.json()
    assert "polls" in data
    assert len(data["polls"]) == 3
    # Should be ordered by created_at desc (newest first)
    assert data["polls"][0]["poll_id"] == poll3["poll_id"]
    assert data["polls"][1]["poll_id"] == poll2["poll_id"]
    assert data["polls"][2]["poll_id"] == poll1["poll_id"]
    # Each poll should have summary fields (no options)
    for p in data["polls"]:
        assert "poll_id" in p
        assert "channel_id" in p
        assert "author_id" in p
        assert "question" in p
        assert "status" in p
        assert "total_votes" in p
        assert "options" not in p


def test_list_polls_with_limit_and_offset(api) -> None:
    client, _publisher, _messages, _references, _database_path = api
    # Create 5 polls
    for i in range(5):
        response = client.post("/api/v1/polls", json=poll_request(question=f"Encuesta {i}"))
        assert response.status_code == 201

    # Test limit
    response = client.get("/api/v1/polls", params={"channel_id": "channel-123", "limit": 2})
    assert response.status_code == 200
    assert len(response.json()["polls"]) == 2

    # Test offset
    response = client.get("/api/v1/polls", params={"channel_id": "channel-123", "limit": 2, "offset": 2})
    assert response.status_code == 200
    assert len(response.json()["polls"]) == 2
    # Should be the 3rd and 4th (0-indexed: 2, 3) - newest first so Encuesta 4, 3, 2, 1, 0
    assert response.json()["polls"][0]["question"] == "Encuesta 2"
    assert response.json()["polls"][1]["question"] == "Encuesta 1"


def test_list_polls_requires_channel_id(api) -> None:
    client, _publisher, _messages, _references, _database_path = api

    response = client.get("/api/v1/polls")

    assert response.status_code == 422  # missing required query param


def test_list_polls_validates_limit_bounds(api) -> None:
    client, _publisher, _messages, _references, _database_path = api

    # limit < 1
    response = client.get("/api/v1/polls", params={"channel_id": "channel-123", "limit": 0})
    assert response.status_code == 422
    assert "limit" in response.json()["detail"].lower()

    # limit > 100
    response = client.get("/api/v1/polls", params={"channel_id": "channel-123", "limit": 101})
    assert response.status_code == 422
    assert "limit" in response.json()["detail"].lower()

    # offset < 0
    response = client.get("/api/v1/polls", params={"channel_id": "channel-123", "offset": -1})
    assert response.status_code == 422
    assert "offset" in response.json()["detail"].lower()


# --- Tests for references client ---

def test_http_reference_client_validates_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.clients import reference_client_from_env

    monkeypatch.setenv("REFERENCES_ENABLED", "true")
    monkeypatch.setenv("USERS_BASE_URL", "http://users:8000")
    monkeypatch.setenv("CHANNELS_BASE_URL", "http://channels:8000")

    client = reference_client_from_env()
    assert isinstance(client, HttpReferenceClient)
    assert client.enabled is True


def test_reference_client_rejects_invalid_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.clients import reference_client_from_env

    monkeypatch.setenv("REFERENCES_ENABLED", "sometimes")

    with pytest.raises(ValueError, match="REFERENCES_ENABLED debe ser true o false"):
        reference_client_from_env()


def test_disabled_reference_client_noops() -> None:
    client = DisabledReferenceClient()
    assert client.enabled is False

    async def run():
        await client.validate_user("any")
        await client.validate_channel("any")
        await client.close()

    asyncio.run(run())


def test_http_reference_client_posts_correct_body() -> None:
    received: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append({"method": request.method, "url": str(request.url)})
        return httpx.Response(200, json={"id": "user-1"})

    async def run():
        client = HttpReferenceClient(
            users_base_url="http://users:8000",
            channels_base_url="http://channels:8000",
            transport=httpx.MockTransport(handler),
        )
        await client.connect()
        await client.validate_user("user-1")
        await client.validate_channel("channel-1")
        await client.close()

    asyncio.run(run())

    assert len(received) == 2
    assert received[0]["method"] == "GET"
    assert received[0]["url"] == "http://users:8000/api/v1/users/user-1"
    assert received[1]["method"] == "GET"
    assert received[1]["url"] == "http://channels:8000/api/v1/channels/channel-1"