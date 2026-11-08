from __future__ import annotations

import httpx

from gateway.tests.conftest import execute_graphql, json_response


POLL_ID = "11111111-1111-4111-8111-111111111111"
OTHER_POLL_ID = "22222222-2222-4222-8222-222222222222"


def test_poll_discovery_deduplicates_and_checks_channel() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "messages.test":
            return json_response(
                [
                    {"content": f"📊 Nueva encuesta\nPoll ID: {POLL_ID}"},
                    {"content": f"Poll ID: {POLL_ID}"},
                    {"content": f"Poll ID: {OTHER_POLL_ID}"},
                    {"content": "message without a poll"},
                ]
            )
        assert request.url.host == "polls.test"
        if request.url.path.endswith(POLL_ID):
            return json_response(
                {
                    "poll_id": POLL_ID,
                    "channel_id": "channel-1",
                    "author_id": "user-1",
                    "question": "Lunch?",
                    "options": [],
                    "status": "open",
                    "duration_minutes": 5,
                    "closes_at": "2026-01-01T12:00:00Z",
                    "created_at": "2026-01-01T11:55:00Z",
                    "closed_at": None,
                    "total_votes": 0,
                }
            )
        return json_response(
            {
                "poll_id": OTHER_POLL_ID,
                "channel_id": "a-different-channel",
                "author_id": "user-1",
                "question": "Not in this channel",
                "options": [],
                "status": "open",
                "duration_minutes": 5,
                "closes_at": "2026-01-01T12:00:00Z",
                "created_at": "2026-01-01T11:55:00Z",
                "closed_at": None,
                "total_votes": 0,
            }
        )

    result, requests = execute_graphql(
        handler,
        '{ polls(channelId: "channel-1") { pollId channelId question status } }',
    )

    assert result == {
        "data": {
            "polls": [
                {
                    "pollId": POLL_ID,
                    "channelId": "channel-1",
                    "question": "Lunch?",
                    "status": "open",
                }
            ]
        }
    }
    assert sum(request.url.host == "polls.test" for request in requests) == 2


def test_create_poll_forwards_idempotency_and_accepts_pending_202() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.host == "polls.test"
        assert request.url.path == "/api/v1/polls"
        assert request.headers["Idempotency-Key"] == "request-123"
        assert request.read()
        assert request.content == (
            b'{"channel_id":"c-1","author_id":"u-1","question":"Lunch?",'
            b'"options":["Pizza","Sushi"],"duration_minutes":10}'
        )
        return json_response(
            {
                "poll_id": POLL_ID,
                "channel_id": "c-1",
                "author_id": "u-1",
                "question": "Lunch?",
                "options": [],
                "status": "pending_announcement",
                "duration_minutes": 10,
                "closes_at": "2026-01-01T12:00:00Z",
                "created_at": "2026-01-01T11:50:00Z",
                "closed_at": None,
                "total_votes": 0,
            },
            status=202,
        )

    result, _ = execute_graphql(
        handler,
        """
        mutation Create($input: CreatePollInput!, $key: String) {
          createPoll(input: $input, idempotencyKey: $key) { pollId status }
        }
        """,
        {
            "input": {
                "channelId": "c-1",
                "authorId": "u-1",
                "question": "Lunch?",
                "options": ["Pizza", "Sushi"],
                "durationMinutes": 10,
            },
            "key": "request-123",
        },
    )

    assert "errors" not in result
    assert result["data"]["createPoll"] == {
        "pollId": POLL_ID,
        "status": "pending_announcement",
    }


def test_vote_maps_graphql_names_to_polls_rest_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == f"/api/v1/polls/{POLL_ID}/votes"
        assert request.content == b'{"voter_id":"user-7","option_id":"option-8"}'
        return json_response(
            {
                "poll_id": POLL_ID,
                "voter_id": "user-7",
                "option_id": "option-8",
                "cast_at": "2026-01-01T12:00:00Z",
            },
            status=201,
        )

    result, _ = execute_graphql(
        handler,
        f'mutation {{ vote(pollId: "{POLL_ID}", voterId: "user-7", optionId: "option-8") {{ pollId voterId optionId }} }}',
    )

    assert result["data"]["vote"]["voterId"] == "user-7"


def test_close_poll_uses_author_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == f"/api/v1/polls/{POLL_ID}/close"
        assert request.content == b'{"author_id":"user-1"}'
        return json_response(
            {
                "poll_id": POLL_ID,
                "channel_id": "c-1",
                "author_id": "user-1",
                "question": "Lunch?",
                "options": [],
                "status": "closed",
                "duration_minutes": 5,
                "closes_at": "2026-01-01T12:00:00Z",
                "created_at": "2026-01-01T11:55:00Z",
                "closed_at": "2026-01-01T12:00:00Z",
                "total_votes": 0,
            }
        )

    result, _ = execute_graphql(
        handler,
        f'mutation {{ closePoll(pollId: "{POLL_ID}", authorId: "user-1") {{ status }} }}',
    )

    assert result["data"]["closePoll"]["status"] == "closed"
