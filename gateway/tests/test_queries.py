from __future__ import annotations

from datetime import datetime, timezone

import httpx

from gateway.tests.conftest import execute_graphql, json_response


def test_channels_are_fetched_from_channels_service() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "channels.test"
        assert request.url.path == "/api/v1/channels"
        return json_response([{"id": "c-1", "name": "general"}])

    result, requests = execute_graphql(handler, "{ channels { id name } }")

    assert result == {"data": {"channels": [{"id": "c-1", "name": "general"}]}}
    assert len(requests) == 1


def test_messages_use_user_loader_and_reactions_failure_is_partial() -> None:
    timestamp = "2026-01-01T12:00:00Z"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "messages.test":
            return json_response(
                [
                    {
                        "id": "m-1",
                        "channel_id": "c-1",
                        "author_id": "User-A",
                        "content": "hello",
                        "created_at": timestamp,
                    },
                    {
                        "id": "m-2",
                        "channel_id": "c-1",
                        "author_id": "User-A",
                        "content": "again",
                        "created_at": timestamp,
                    },
                ]
            )
        if request.url.host == "users.test":
            return json_response({"id": "User-A", "display_name": "Alice"})
        if request.url.host == "reactions.test":
            assert request.url.params["channel_id"] == "c-1"
            return json_response({"error": "temporarily unavailable"}, status=503)
        raise AssertionError(f"Unexpected mocked upstream: {request.url}")

    result, requests = execute_graphql(
        handler,
        """
        query {
          messages(channelId: "c-1") {
            id author { id displayName }
            reactions { totalReactions }
          }
        }
        """,
    )

    assert "errors" not in result
    assert [item["author"]["displayName"] for item in result["data"]["messages"]] == [
        "Alice",
        "Alice",
    ]
    assert [item["reactions"] for item in result["data"]["messages"]] == [None, None]
    assert sum(request.url.host == "users.test" for request in requests) == 1
    assert sum(request.url.host == "reactions.test" for request in requests) == 2


def test_not_found_user_is_nullable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/users/missing"
        return httpx.Response(404, json={"detail": "not found"})

    result, _ = execute_graphql(handler, '{ user(id: "missing") { id displayName } }')

    assert result == {"data": {"user": None}}


def test_gateway_health_does_not_require_upstreams() -> None:
    result, requests = execute_graphql(
        lambda request: (_ for _ in ()).throw(AssertionError(request.url)),
        "{ health { status version } }",
    )

    assert result["data"]["health"] == {"status": "ok", "version": "1.0.0"}
    assert requests == []


def test_search_preserves_case_repeated_filters_and_datetime() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "search.test"
        assert request.url.path == "/api/v1/search/messages"
        assert request.url.params.get_list("author_id") == ["User-A", "User-B"]
        assert request.url.params.get_list("channel_id") == ["Channel-X"]
        assert request.url.params.get_list("has") == ["link"]
        assert request.url.params["min_date"] == "2026-01-01T12:30:00Z"
        assert request.url.params["sort_by"] == "relevance"
        return json_response(
            {
                "total_results": 1,
                "messages": [
                    {
                        "id": "m-1",
                        "channel_id": "Channel-X",
                        "author_id": "User-A",
                        "content": "hello",
                        "created_at": "2026-01-02T12:30:00Z",
                        "has": [],
                        "mentions": [],
                        "links": [],
                        "highlights": [],
                    }
                ],
            }
        )

    result, _ = execute_graphql(
        handler,
        """
        query Search($input: SearchMessagesInput!) {
          searchMessages(input: $input) {
            totalResults
            messages { id channelId authorId content createdAt }
          }
        }
        """,
        {
            "input": {
                "authorIds": ["User-A", "User-B"],
                "channelIds": ["Channel-X"],
                "has": ["LINK"],
                "minDate": datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc).isoformat(),
                "sortBy": "RELEVANCE",
            }
        },
    )

    assert "errors" not in result
    assert result["data"]["searchMessages"]["totalResults"] == 1


def test_search_rejects_out_of_range_pagination_without_http_call() -> None:
    result, requests = execute_graphql(
        lambda request: (_ for _ in ()).throw(AssertionError(request.url)),
        "{ searchMessages(input: { content: \"hello\", limit: 26 }) { totalResults } }",
    )

    assert result["errors"][0]["extensions"]["code"] == "BAD_USER_INPUT"
    assert requests == []
