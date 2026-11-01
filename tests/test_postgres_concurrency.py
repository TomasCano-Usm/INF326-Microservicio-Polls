"""Optional row-lock integration tests against a dedicated PostgreSQL database.

Set POLLS_TEST_DATABASE_URL to enable them. Each test uses and drops an isolated schema.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import Base
from app.models import CloseRequest, VoteRequest
from app.service import PollService
from app.tables import MessageDelivery, OutboxEvent, Poll, PollOption, Vote


POSTGRES_TEST_URL = os.getenv("POLLS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="Configura POLLS_TEST_DATABASE_URL con una base PostgreSQL de pruebas.",
)


class FakePublisher:
    async def connect(self) -> None:
        return None

    async def publish(self, *_args, **_kwargs) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeMessagesClient:
    enabled = True

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str]] = []

    async def connect(self) -> None:
        return None

    async def post_message(self, channel_id: str, author_id: str, content: str) -> None:
        self.requests.append((channel_id, author_id, content))

    async def close(self) -> None:
        return None


@asynccontextmanager
async def isolated_postgres_service():
    assert POSTGRES_TEST_URL is not None
    schema = f"polls_test_{uuid4().hex}"
    admin_engine = create_async_engine(POSTGRES_TEST_URL, poolclass=NullPool)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_async_engine(
        POSTGRES_TEST_URL,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        database = SimpleNamespace(
            sessions=async_sessionmaker(engine, expire_on_commit=False)
        )
        yield database
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()


async def add_open_poll(database, closes_at: datetime) -> tuple[Poll, UUID]:
    now = datetime.now(timezone.utc)
    poll_id = uuid4()
    option_id = uuid4()
    poll = Poll(
        poll_id=poll_id,
        channel_id="channel-integration",
        author_id="user-author",
        question="¿Qué alternativa prefieres?",
        status="open",
        duration_minutes=5,
        created_at=now - timedelta(minutes=5),
        closes_at=closes_at,
        options=[
            PollOption(
                option_id=option_id,
                position=0,
                text="Alternativa A",
                normalized_text="alternativa a",
            ),
            PollOption(
                option_id=uuid4(),
                position=1,
                text="Alternativa B",
                normalized_text="alternativa b",
            ),
        ],
    )
    async with database.sessions() as session, session.begin():
        session.add(poll)
    return poll, option_id


def test_postgres_row_lock_serializes_concurrent_duplicate_votes() -> None:
    async def run() -> None:
        async with isolated_postgres_service() as database:
            poll, option_id = await add_open_poll(
                database, datetime.now(timezone.utc) + timedelta(minutes=5)
            )
            service = PollService(database, FakePublisher(), FakeMessagesClient())
            request = VoteRequest(voter_id="same-voter", option_id=option_id)
            results = await asyncio.wait_for(
                asyncio.gather(
                    service.cast_vote(poll.poll_id, request),
                    service.cast_vote(poll.poll_id, request),
                    return_exceptions=True,
                ),
                timeout=10,
            )

            assert sum(not isinstance(result, BaseException) for result in results) == 1
            errors = [result for result in results if isinstance(result, BaseException)]
            assert len(errors) == 1
            assert isinstance(errors[0], HTTPException)
            assert errors[0].status_code == 409

            async with database.sessions() as session:
                vote_count = await session.scalar(
                    select(func.count()).select_from(Vote).where(Vote.poll_id == poll.poll_id)
                )
                event_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(
                        OutboxEvent.poll_id == poll.poll_id,
                        OutboxEvent.event_type == "poll.vote.cast",
                    )
                )
            assert vote_count == 1
            assert event_count == 1

    asyncio.run(run())


def test_postgres_manual_and_automatic_closure_create_one_delivery() -> None:
    async def run() -> None:
        async with isolated_postgres_service() as database:
            poll, _option_id = await add_open_poll(
                database, datetime.now(timezone.utc) - timedelta(seconds=1)
            )
            messages = FakeMessagesClient()
            service = PollService(database, FakePublisher(), messages)
            results = await asyncio.wait_for(
                asyncio.gather(
                    service.close_poll(poll.poll_id, CloseRequest(author_id="user-author")),
                    service._close_due_poll(poll.poll_id),
                    return_exceptions=True,
                ),
                timeout=10,
            )

            assert not [result for result in results if isinstance(result, BaseException)]
            async with database.sessions() as session:
                closed_events = await session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(
                        OutboxEvent.poll_id == poll.poll_id,
                        OutboxEvent.event_type == "poll.closed",
                    )
                )
                closure_deliveries = await session.scalar(
                    select(func.count())
                    .select_from(MessageDelivery)
                    .where(
                        MessageDelivery.poll_id == poll.poll_id,
                        MessageDelivery.kind == "final_results",
                    )
                )
                stored_poll = await session.get(Poll, poll.poll_id)

            assert stored_poll is not None and stored_poll.status == "closed"
            assert closed_events == 1
            assert closure_deliveries == 1
            assert len(messages.requests) == 1

    asyncio.run(run())
