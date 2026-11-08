from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

from aiodataloader import DataLoader
from ariadne import EnumType, MutationType, ObjectType, QueryType, ScalarType, gql, make_executable_schema
from graphql import GraphQLError
from graphql.language import StringValueNode

from gateway.app.upstreams import UpstreamError, Upstreams

logger = logging.getLogger(__name__)

POLL_ID_PATTERN = re.compile(
    r"(?im)^\s*Poll ID:\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s*$"
)

TYPE_DEFS = gql(
    """
    scalar DateTime

    enum SearchHas { LINK MENTION }
    enum SearchSortBy { TIMESTAMP RELEVANCE }
    enum SearchSortOrder { ASC DESC }

    type GatewayHealth {
      status: String!
      version: String!
    }

    type User {
      id: ID!
      displayName: String!
    }

    type Channel {
      id: ID!
      name: String!
    }

    type Message {
      id: ID!
      channelId: ID!
      authorId: ID!
      content: String!
      createdAt: DateTime!
      author: User
      reactions: MessageReactions
    }

    type MessageReactions {
      messageId: ID!
      totalReactions: Int!
      summary: [ReactionSummary!]!
      reactions: [Reaction!]!
    }

    type ReactionSummary {
      reactionType: String!
      count: Int!
    }

    type Reaction {
      id: ID!
      messageId: ID!
      userId: ID!
      reactionType: String!
      createdAt: DateTime
    }

    type PollOption {
      optionId: ID!
      position: Int!
      text: String!
      voteCount: Int!
    }

    type Poll {
      pollId: ID!
      channelId: ID!
      authorId: ID!
      question: String!
      options: [PollOption!]!
      status: String!
      durationMinutes: Int!
      closesAt: DateTime!
      createdAt: DateTime!
      closedAt: DateTime
      totalVotes: Int!
      creationError: String
    }

    type Vote {
      pollId: ID!
      voterId: ID!
      optionId: ID!
      castAt: DateTime!
    }

    type SearchMessage {
      id: ID!
      channelId: ID!
      authorId: ID!
      content: String!
      createdAt: DateTime!
      editedAt: DateTime
      has: [String!]!
      mentions: [ID!]!
      links: [String!]!
      highlights: [String!]!
    }

    type SearchMessagesResult {
      totalResults: Int!
      messages: [SearchMessage!]!
    }

    input SearchMessagesInput {
      content: String
      authorIds: [ID!]
      channelIds: [ID!]
      mentions: [ID!]
      has: [SearchHas!]
      minDate: DateTime
      maxDate: DateTime
      sortBy: SearchSortBy = TIMESTAMP
      sortOrder: SearchSortOrder = DESC
      limit: Int = 25
      offset: Int = 0
    }

    input CreatePollInput {
      channelId: ID!
      authorId: ID!
      question: String!
      options: [String!]!
      durationMinutes: Int = 5
    }

    type Query {
      health: GatewayHealth!
      channels: [Channel!]!
      channel(id: ID!): Channel
      user(id: ID!): User
      messages(channelId: ID!): [Message!]!
      poll(id: ID!): Poll
      polls(channelId: ID!): [Poll!]!
      searchMessages(input: SearchMessagesInput!): SearchMessagesResult!
    }

    type Mutation {
      createUser(displayName: String!): User!
      createChannel(name: String!): Channel!
      sendMessage(channelId: ID!, authorId: ID!, content: String!): Message!
      createPoll(input: CreatePollInput!, idempotencyKey: String): Poll!
      vote(pollId: ID!, voterId: ID!, optionId: ID!): Vote!
      closePoll(pollId: ID!, authorId: ID!): Poll!
      addReaction(messageId: ID!, channelId: ID!, userId: ID!, reactionType: String!): Reaction!
      removeReaction(reactionId: ID!): Boolean!
    }
    """
)


def camelize(value: Any) -> Any:
    if isinstance(value, list):
        return [camelize(item) for item in value]
    if isinstance(value, dict):
        return {
            re.sub(r"_([a-z])", lambda match: match.group(1).upper(), key): camelize(item)
            for key, item in value.items()
        }
    return value


def snake_case(value: dict[str, Any]) -> dict[str, Any]:
    return {
        re.sub(r"[A-Z]", lambda match: f"_{match.group(0).lower()}", key): item
        for key, item in value.items()
    }


def encoded(value: str) -> str:
    return quote(str(value), safe="")


def isoformat(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("DateTime values must be ISO 8601 strings")
    if parsed.tzinfo is None:
        raise ValueError("DateTime values must include a timezone")
    return parsed


datetime_scalar = ScalarType("DateTime")


@datetime_scalar.serializer
def _serialize_datetime(value: Any) -> str:
    return isoformat(parse_datetime(value))


@datetime_scalar.value_parser
def _parse_datetime(value: Any) -> datetime:
    return parse_datetime(value)


@datetime_scalar.literal_parser
def _parse_datetime_literal(node: Any, _variables: Any = None) -> datetime:
    if not isinstance(node, StringValueNode):
        raise ValueError("DateTime literals must be strings")
    return parse_datetime(node.value)


class UserLoader(DataLoader):
    def __init__(self, upstreams: Upstreams) -> None:
        super().__init__()
        self.upstreams = upstreams

    async def batch_load_fn(self, user_ids: list[str]) -> list[Any]:
        return await asyncio.gather(
            *(
                self.upstreams.request(
                    "users",
                    "GET",
                    f"/api/v1/users/{encoded(user_id)}",
                    not_found_is_none=True,
                )
                for user_id in user_ids
            )
        )


def _context_value(upstreams: Upstreams, _request: Any, _data: Any) -> dict[str, Any]:
    return {
        "upstreams": upstreams,
        "users": UserLoader(upstreams),
        "message_tasks": {},
    }


def _upstreams(info: Any) -> Upstreams:
    return info.context["upstreams"]


def _graphql_upstream_error(error: UpstreamError) -> GraphQLError:
    return GraphQLError(
        str(error),
        extensions={
            "code": "UPSTREAM_ERROR",
            "service": error.service,
            "status": error.status_code,
        },
    )


async def _request(
    info: Any,
    service: str,
    method: str,
    path: str,
    **kwargs: Any,
) -> Any:
    try:
        response = await _upstreams(info).request(service, method, path, **kwargs)
    except UpstreamError as error:
        raise _graphql_upstream_error(error) from error
    return camelize(response)


async def _messages_for_channel(info: Any, channel_id: str) -> list[dict[str, Any]]:
    cache: dict[str, asyncio.Task[Any]] = info.context["message_tasks"]
    if channel_id not in cache:
        cache[channel_id] = asyncio.create_task(
            _request(
                info,
                "messages",
                "GET",
                f"/api/v1/channels/{encoded(channel_id)}/messages",
            )
        )
    result = await cache[channel_id]
    if not isinstance(result, list):
        raise GraphQLError("Messages returned an invalid response.")
    return result


query = QueryType()
mutation = MutationType()
message = ObjectType("Message")


@query.field("health")
def resolve_health(*_: Any) -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@query.field("channels")
async def resolve_channels(_root: Any, info: Any) -> Any:
    result = await _request(info, "channels", "GET", "/api/v1/channels")
    if not isinstance(result, list):
        raise GraphQLError("Channels returned an invalid response.")
    return result


@query.field("channel")
async def resolve_channel(_root: Any, info: Any, id: str) -> Any:
    return await _request(
        info,
        "channels",
        "GET",
        f"/api/v1/channels/{encoded(id)}",
        not_found_is_none=True,
    )


@query.field("user")
async def resolve_user(_root: Any, info: Any, id: str) -> Any:
    try:
        return camelize(
            await info.context["users"].load(id)
        )
    except UpstreamError as error:
        logger.warning("User lookup failed: %s", error)
        return None


@query.field("messages")
async def resolve_messages(_root: Any, info: Any, channelId: str) -> Any:
    return camelize(await _messages_for_channel(info, channelId))


@query.field("poll")
async def resolve_poll(_root: Any, info: Any, id: str) -> Any:
    return await _request(
        info,
        "polls",
        "GET",
        f"/api/v1/polls/{encoded(id)}",
        not_found_is_none=True,
    )


@query.field("polls")
async def resolve_polls(_root: Any, info: Any, channelId: str) -> list[dict[str, Any]]:
    messages = await _messages_for_channel(info, channelId)
    poll_ids = list(
        dict.fromkeys(
            poll_id
            for item in messages
            for poll_id in POLL_ID_PATTERN.findall(str(item.get("content", "")))
        )
    )
    semaphore = asyncio.Semaphore(10)

    async def fetch_poll(poll_id: str) -> Any:
        async with semaphore:
            return await _request(
                info,
                "polls",
                "GET",
                f"/api/v1/polls/{encoded(poll_id)}",
                not_found_is_none=True,
            )

    results = await asyncio.gather(*(fetch_poll(poll_id) for poll_id in poll_ids))
    return [
        result
        for result in results
        if result is not None and str(result.get("channelId")) == str(channelId)
    ]


@query.field("searchMessages")
async def resolve_search_messages(_root: Any, info: Any, input: dict[str, Any]) -> Any:
    limit = input.get("limit", 25)
    offset = input.get("offset", 0)
    if not 1 <= limit <= 25:
        raise GraphQLError("limit must be between 1 and 25.", extensions={"code": "BAD_USER_INPUT"})
    if not 0 <= offset <= 9975:
        raise GraphQLError("offset must be between 0 and 9975.", extensions={"code": "BAD_USER_INPUT"})

    params: list[tuple[str, str]] = [("limit", str(limit)), ("offset", str(offset))]
    if input.get("content") is not None:
        params.append(("content", input["content"]))
    for field, query_parameter in (
        ("authorIds", "author_id"),
        ("channelIds", "channel_id"),
        ("mentions", "mentions"),
    ):
        params.extend((query_parameter, str(value)) for value in input.get(field) or [])
    params.extend(("has", str(value)) for value in input.get("has") or [])
    for field in ("minDate", "maxDate"):
        if input.get(field) is not None:
            params.append((snake_case({field: input[field]}).popitem()[0], isoformat(input[field])))
    params.append(("sort_by", str(input.get("sortBy", "timestamp")).lower()))
    params.append(("sort_order", str(input.get("sortOrder", "desc")).lower()))
    result = await _request(info, "search", "GET", "/api/v1/search/messages", params=params)
    if not isinstance(result, dict) or not isinstance(result.get("messages"), list):
        raise GraphQLError("Search returned an invalid response.")
    return result


@mutation.field("createUser")
async def resolve_create_user(_root: Any, info: Any, displayName: str) -> Any:
    return await _request(
        info,
        "users",
        "POST",
        "/api/v1/users",
        json={"display_name": displayName},
    )


@mutation.field("createChannel")
async def resolve_create_channel(_root: Any, info: Any, name: str) -> Any:
    return await _request(
        info,
        "channels",
        "POST",
        "/api/v1/channels",
        json={"name": name},
    )


@mutation.field("sendMessage")
async def resolve_send_message(
    _root: Any,
    info: Any,
    channelId: str,
    authorId: str,
    content: str,
) -> Any:
    return await _request(
        info,
        "messages",
        "POST",
        f"/api/v1/channels/{encoded(channelId)}/messages",
        json={"author_id": authorId, "content": content},
    )


@mutation.field("createPoll")
async def resolve_create_poll(
    _root: Any,
    info: Any,
    input: dict[str, Any],
    idempotencyKey: str | None = None,
) -> Any:
    headers = {"Idempotency-Key": idempotencyKey} if idempotencyKey else None
    return await _request(
        info,
        "polls",
        "POST",
        "/api/v1/polls",
        json=snake_case(input),
        headers=headers,
    )


@mutation.field("vote")
async def resolve_vote(
    _root: Any,
    info: Any,
    pollId: str,
    voterId: str,
    optionId: str,
) -> Any:
    return await _request(
        info,
        "polls",
        "POST",
        f"/api/v1/polls/{encoded(pollId)}/votes",
        json={"voter_id": voterId, "option_id": optionId},
    )


@mutation.field("closePoll")
async def resolve_close_poll(_root: Any, info: Any, pollId: str, authorId: str) -> Any:
    return await _request(
        info,
        "polls",
        "POST",
        f"/api/v1/polls/{encoded(pollId)}/close",
        json={"author_id": authorId},
    )


@mutation.field("addReaction")
async def resolve_add_reaction(
    _root: Any,
    info: Any,
    messageId: str,
    channelId: str,
    userId: str,
    reactionType: str,
) -> Any:
    return await _request(
        info,
        "reactions",
        "POST",
        "/api/v1/reactions",
        json={
            "message_id": messageId,
            "channel_id": channelId,
            "user_id": userId,
            "reaction_type": reactionType,
        },
    )


@mutation.field("removeReaction")
async def resolve_remove_reaction(_root: Any, info: Any, reactionId: str) -> bool:
    await _request(
        info,
        "reactions",
        "DELETE",
        f"/api/v1/reactions/{encoded(reactionId)}",
    )
    return True


@message.field("author")
async def resolve_message_author(root: dict[str, Any], info: Any) -> Any:
    try:
        return camelize(await info.context["users"].load(str(root["authorId"])))
    except UpstreamError as error:
        logger.warning("Message author lookup failed: %s", error)
        return None


@message.field("reactions")
async def resolve_message_reactions(root: dict[str, Any], info: Any) -> Any:
    try:
        return await _request(
            info,
            "reactions",
            "GET",
            f"/api/v1/messages/{encoded(root['id'])}/reactions",
            params=[("channel_id", str(root["channelId"]))],
        )
    except (UpstreamError, GraphQLError) as error:
        logger.warning("Reaction lookup failed for message %s: %s", root.get("id"), error)
        return None


schema = make_executable_schema(
    TYPE_DEFS,
    query,
    mutation,
    message,
    datetime_scalar,
    EnumType("SearchHas", {"LINK": "link", "MENTION": "mention"}),
    EnumType("SearchSortBy", {"TIMESTAMP": "timestamp", "RELEVANCE": "relevance"}),
    EnumType("SearchSortOrder", {"ASC": "asc", "DESC": "desc"}),
)
