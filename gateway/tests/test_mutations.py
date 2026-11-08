from __future__ import annotations

import httpx

from gateway.tests.conftest import execute_graphql, json_response


def test_create_user_and_channel_payloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "users.test":
            assert request.url.path == "/api/v1/users"
            assert request.content == b'{"display_name":"Alice"}'
            return json_response({"id": "u-1", "display_name": "Alice"}, status=201)
        assert request.url.host == "channels.test"
        assert request.url.path == "/api/v1/channels"
        assert request.content == b'{"name":"general"}'
        return json_response({"id": "c-1", "name": "general"}, status=201)

    user, user_requests = execute_graphql(
        handler,
        'mutation { createUser(displayName: "Alice") { id displayName } }',
    )
    channel, channel_requests = execute_graphql(
        handler,
        'mutation { createChannel(name: "general") { id name } }',
    )

    assert user["data"]["createUser"]["displayName"] == "Alice"
    assert channel["data"]["createChannel"]["id"] == "c-1"
    assert len(user_requests) == len(channel_requests) == 1


def test_send_message_uses_author_id_and_channel_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/channels/c-1/messages"
        assert request.content == b'{"author_id":"u-1","content":"hello"}'
        return json_response(
            {
                "id": "m-1",
                "channel_id": "c-1",
                "author_id": "u-1",
                "content": "hello",
                "created_at": "2026-01-01T12:00:00Z",
            },
            status=201,
        )

    result, _ = execute_graphql(
        handler,
        'mutation { sendMessage(channelId: "c-1", authorId: "u-1", content: "hello") { id authorId content } }',
    )

    assert result["data"]["sendMessage"]["authorId"] == "u-1"


def test_reaction_mutations_include_channel_and_handle_204_delete() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.host == "reactions.test"
            assert request.url.path == "/api/v1/reactions"
            assert request.content == (
                b'{"message_id":"m-1","channel_id":"c-1","user_id":"u-1",'
                b'"reaction_type":"like"}'
            )
            return json_response(
                {
                    "id": "r-1",
                    "message_id": "m-1",
                    "user_id": "u-1",
                    "reaction_type": "like",
                    "created_at": "2026-01-01T12:00:00Z",
                },
                status=201,
            )
        assert request.method == "DELETE"
        assert request.url.path == "/api/v1/reactions/r-1"
        return httpx.Response(204)

    created, _ = execute_graphql(
        handler,
        'mutation { addReaction(messageId: "m-1", channelId: "c-1", userId: "u-1", reactionType: "like") { id reactionType } }',
    )
    deleted, _ = execute_graphql(handler, 'mutation { removeReaction(reactionId: "r-1") }')

    assert created["data"]["addReaction"] == {"id": "r-1", "reactionType": "like"}
    assert deleted["data"]["removeReaction"] is True


def test_upstream_errors_are_reported_as_graphql_extensions() -> None:
    result, _ = execute_graphql(
        lambda _request: json_response({"detail": "unavailable"}, status=503),
        '{ channel(id: "c-1") { id } }',
    )

    assert result["data"]["channel"] is None
    assert result["errors"][0]["extensions"] == {
        "code": "UPSTREAM_ERROR",
        "service": "channels",
        "status": 503,
    }
