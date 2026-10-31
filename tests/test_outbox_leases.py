import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.db import Database
from app.service import PollService
from app.tables import OutboxEvent, Poll


class DeferredPublisher:
    def __init__(self, first_outcome: str) -> None:
        self.first_outcome = first_outcome
        self.started = [asyncio.Event(), asyncio.Event()]
        self.release = [asyncio.Event(), asyncio.Event()]
        self.calls = 0

    async def connect(self) -> None:
        return None

    async def publish(
        self,
        _event_type: str,
        _payload: dict[str, object],
        event_id: str | None = None,
    ) -> None:
        self.calls += 1
        call = self.calls - 1
        self.started[call].set()
        await self.release[call].wait()
        if call == 0 and self.first_outcome == "failure":
            raise RuntimeError("resultado tardío del primer claim")

    async def close(self) -> None:
        return None


class DisabledMessages:
    enabled = False


def run_late_outbox_attempt(first_outcome: str, tmp_path) -> None:
    async def run() -> None:
        database_path = tmp_path / f"outbox-{first_outcome}.sqlite"
        database = Database(f"sqlite+aiosqlite:///{database_path}", create_schema=True)
        await database.connect()
        publisher = DeferredPublisher(first_outcome)
        service = PollService(database, publisher, DisabledMessages())
        now = datetime.now(timezone.utc)
        poll_id = uuid4()
        event_id = uuid4()

        async with database.sessions() as session, session.begin():
            session.add(
                Poll(
                    poll_id=poll_id,
                    channel_id="channel-123",
                    author_id="user-author",
                    question="Pregunta de prueba",
                    status="open",
                    duration_minutes=5,
                    created_at=now,
                    closes_at=now + timedelta(minutes=5),
                )
            )
            session.add(
                OutboxEvent(
                    event_id=event_id,
                    poll_id=poll_id,
                    event_type="poll.created",
                    payload={"poll_id": str(poll_id)},
                    occurred_at=now,
                    attempt_count=0,
                    next_attempt_at=now,
                )
            )

        first_worker = asyncio.create_task(service._publish_outbox_event(event_id))
        second_worker: asyncio.Task[None] | None = None
        try:
            await asyncio.wait_for(publisher.started[0].wait(), timeout=2)
            async with database.sessions() as session, session.begin():
                event = await session.get(OutboxEvent, event_id)
                assert event is not None
                first_token = event.lease_token
                assert first_token is not None
                event.lease_until = now - timedelta(seconds=1)

            second_worker = asyncio.create_task(service._publish_outbox_event(event_id))
            await asyncio.wait_for(publisher.started[1].wait(), timeout=2)

            async with database.sessions() as session:
                event = await session.get(OutboxEvent, event_id)
                assert event is not None
                second_token = event.lease_token
                second_lease_until = event.lease_until
                second_attempt_count = event.attempt_count
                assert second_token is not None
                assert second_token != first_token

            publisher.release[0].set()
            await asyncio.wait_for(first_worker, timeout=2)

            async with database.sessions() as session:
                event = await session.get(OutboxEvent, event_id)
                assert event is not None
                assert event.published_at is None
                assert event.lease_token == second_token
                assert event.lease_until == second_lease_until
                assert event.attempt_count == second_attempt_count
                assert event.last_error is None

            publisher.release[1].set()
            await asyncio.wait_for(second_worker, timeout=2)

            async with database.sessions() as session:
                event = await session.get(OutboxEvent, event_id)
                assert event is not None
                assert event.published_at is not None
                assert event.lease_until is None
                assert event.lease_token is None
            assert publisher.calls == 2
        finally:
            publisher.release[0].set()
            publisher.release[1].set()
            tasks = [task for task in (first_worker, second_worker) if task is not None]
            for task in tasks:
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await database.close()

    asyncio.run(run())


def test_late_outbox_failure_cannot_clear_newer_lease(tmp_path) -> None:
    run_late_outbox_attempt("failure", tmp_path)


def test_late_outbox_success_cannot_clear_newer_lease(tmp_path) -> None:
    run_late_outbox_attempt("success", tmp_path)
