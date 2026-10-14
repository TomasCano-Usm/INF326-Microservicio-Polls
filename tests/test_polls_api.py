import sqlite3
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.messages import MessagesRejected, MessagesUnavailable


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
    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []
        self.failure: Exception | None = None

    async def connect(self) -> None:
        return None

    async def post_message(self, channel_id: str, user_id: str, content: str) -> None:
        if self.failure is not None:
            raise self.failure
        self.requests.append(
            {"channel_id": channel_id, "user_id": user_id, "content": content}
        )

    async def close(self) -> None:
        return None


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("POLL_CLOSE_SCAN_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("POLL_RETRY_BASE_SECONDS", "0.05")
    publisher = FakePublisher()
    messages = FakeMessagesClient()
    database_path = tmp_path / "polls.sqlite"
    application = create_app(
        lambda: publisher,
        lambda: messages,
        lambda: Database(f"sqlite+aiosqlite:///{database_path}", create_schema=True),
    )
    with TestClient(application) as client:
        yield client, publisher, messages, database_path


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
    client, publisher, messages, _database_path = api

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
    assert announcement["user_id"] == "user-author"
    assert set(announcement) == {"channel_id", "user_id", "content"}
    assert created["question"] in announcement["content"]
    assert created["poll_id"] in announcement["content"]
    assert all(option["text"] in announcement["content"] for option in created["options"])
    assert "Cierre:" in announcement["content"]


def test_vote_counts_and_rejects_duplicate_voter(api) -> None:
    client, publisher, _messages, _database_path = api
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
    client, _publisher, _messages, _database_path = api
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
    client, _publisher, messages, _database_path = api
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
    client, publisher, messages, _database_path = api
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
    assert closure["user_id"] == "user-author"
    assert poll["question"] in closure["content"]
    assert "Total de votos: 0" in closure["content"]
    assert all(option["text"] in closure["content"] for option in poll["options"])


def test_deadline_closes_poll_automatically_and_publishes_results(api) -> None:
    client, publisher, messages, database_path = api
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
    client, publisher, messages, _database_path = api
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
    client, publisher, messages, _database_path = api
    messages.failure = MessagesRejected(404, "Canal no encontrado")

    response = client.post("/api/v1/polls", json=poll_request())

    assert response.status_code == 404
    assert response.json()["detail"] == "Canal no encontrado"
    assert publisher.events == []


def test_failed_created_event_retries_without_reposting_message(api) -> None:
    client, publisher, messages, _database_path = api
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
    client, publisher, messages, _database_path = api
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
