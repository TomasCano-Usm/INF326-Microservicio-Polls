import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import Database
from app.events import EventPublisher
from app.message_content import build_poll_announcement, build_poll_results
from app.messages import ChannelMessagesClient, MessagesClientError, MessagesRejected
from app.models import (
    CloseRequest,
    OptionResult,
    PollCreateRequest,
    PollResponse,
    VoteRequest,
    VoteResponse,
)
from app.tables import MessageDelivery, OutboxEvent, Poll, PollOption, Vote


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
LEASE_SECONDS = 30
MAX_RETRY_SECONDS = 300


@dataclass(slots=True)
class CreatePollResult:
    poll: PollResponse
    status_code: int


@dataclass(slots=True)
class MessageAttempt:
    delivery_id: UUID
    poll_id: UUID
    kind: Literal["announcement", "final_results"]
    channel_id: str
    author_id: str
    content: str


class PollService:
    def __init__(
        self,
        database: Database,
        event_publisher: EventPublisher,
        messages_client: ChannelMessagesClient,
        close_scan_interval: float = 1.0,
    ) -> None:
        self._sessions = database.sessions
        self._event_publisher = event_publisher
        self._messages_client = messages_client
        self._close_scan_interval = max(0.1, close_scan_interval)
        self._retry_base_seconds = max(0.05, float(os.getenv("POLL_RETRY_BASE_SECONDS", "1")))

    async def create_poll(
        self,
        request: PollCreateRequest,
        idempotency_key: str | None = None,
    ) -> CreatePollResult:
        idempotency_key = self._validate_idempotency_key(idempotency_key)
        request_hash = self._request_hash(request)

        if idempotency_key is not None:
            existing_id = await self._find_idempotent_poll(request.author_id, idempotency_key)
            if existing_id is not None:
                return await self._return_idempotent_poll(existing_id, request_hash)

        created_at = datetime.now(timezone.utc)
        poll_id = uuid4()
        delivery_id = uuid4()
        poll = Poll(
            poll_id=poll_id,
            channel_id=request.channel_id,
            author_id=request.author_id,
            question=request.question,
            status="pending_announcement",
            duration_minutes=request.duration_minutes,
            created_at=created_at,
            closes_at=created_at + timedelta(minutes=request.duration_minutes),
            idempotency_key=idempotency_key,
            request_hash=request_hash if idempotency_key is not None else None,
            options=[
                PollOption(
                    option_id=uuid4(),
                    position=position,
                    text=text,
                    normalized_text=text.strip().casefold(),
                )
                for position, text in enumerate(request.options)
            ],
        )
        delivery = MessageDelivery(
            delivery_id=delivery_id,
            poll_id=poll_id,
            kind="announcement",
            status="pending",
            attempt_count=0,
            next_attempt_at=created_at,
            created_at=created_at,
        )

        try:
            async with self._sessions() as session, session.begin():
                session.add(poll)
                await session.flush()
                session.add(delivery)
        except IntegrityError as error:
            logger.exception("No se pudo persistir la encuesta %s", poll_id)
            if idempotency_key is not None:
                existing_id = await self._find_idempotent_poll(request.author_id, idempotency_key)
                if existing_id is not None:
                    return await self._return_idempotent_poll(existing_id, request_hash)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La encuesta entra en conflicto con un registro existente.",
            ) from error

        await self._process_message_delivery(delivery_id)
        stored_poll = await self._read_poll(poll_id)
        if stored_poll.status == "creation_failed":
            await self._raise_creation_error(poll_id)

        return CreatePollResult(
            poll=stored_poll,
            status_code=(
                status.HTTP_202_ACCEPTED
                if stored_poll.status == "pending_announcement"
                else status.HTTP_201_CREATED
            ),
        )

    async def cast_vote(self, poll_id: UUID, request: VoteRequest) -> VoteResponse:
        now = datetime.now(timezone.utc)
        closure_delivery_id: UUID | None = None
        vote_response: VoteResponse | None = None
        conflict_after_commit = False

        try:
            async with self._sessions() as session, session.begin():
                poll = await self._locked_poll(session, poll_id)
                if poll is None:
                    raise self._poll_not_found()
                if poll.status == "creation_failed":
                    raise self._creation_failed(poll)
                if poll.status == "pending_announcement":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="La encuesta aún no está disponible para votar.",
                    )

                if poll.status == "open" and poll.closes_at <= now:
                    closure_delivery_id = await self._close_poll_in_transaction(
                        session, poll, reason="deadline", closed_at=now
                    )
                    conflict_after_commit = True
                elif poll.status == "closed":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="La encuesta está cerrada.",
                    )
                else:
                    valid_option = await session.scalar(
                        select(PollOption.option_id).where(
                            PollOption.poll_id == poll_id,
                            PollOption.option_id == request.option_id,
                        )
                    )
                    if valid_option is None:
                        raise HTTPException(
                            status_code=422,
                            detail="option_id no pertenece a esta encuesta.",
                        )

                    existing_vote = await session.get(Vote, (poll_id, request.voter_id))
                    if existing_vote is not None:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="El usuario ya votó en esta encuesta.",
                        )

                    cast_at = now
                    session.add(
                        Vote(
                            poll_id=poll_id,
                            voter_id=request.voter_id,
                            option_id=request.option_id,
                            cast_at=cast_at,
                        )
                    )
                    session.add(
                        OutboxEvent(
                            event_id=uuid4(),
                            poll_id=poll_id,
                            event_type="poll.vote.cast",
                            payload={
                                "poll_id": str(poll_id),
                                "channel_id": poll.channel_id,
                                "voter_id": request.voter_id,
                                "option_id": str(request.option_id),
                                "cast_at": cast_at.isoformat(),
                            },
                            occurred_at=cast_at,
                            attempt_count=0,
                            next_attempt_at=cast_at,
                        )
                    )
                    vote_response = VoteResponse(
                        poll_id=poll_id,
                        voter_id=request.voter_id,
                        option_id=request.option_id,
                        cast_at=cast_at,
                    )
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El usuario ya votó en esta encuesta.",
            ) from error

        if closure_delivery_id is not None:
            await self._process_message_delivery(closure_delivery_id)
        if conflict_after_commit:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La encuesta está cerrada.",
            )
        assert vote_response is not None
        return vote_response

    async def close_poll(self, poll_id: UUID, request: CloseRequest) -> PollResponse:
        now = datetime.now(timezone.utc)
        delivery_id: UUID | None = None
        async with self._sessions() as session, session.begin():
            poll = await self._locked_poll(session, poll_id)
            if poll is None:
                raise self._poll_not_found()
            if poll.status == "creation_failed":
                raise self._creation_failed(poll)
            if request.author_id != poll.author_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Solo el autor puede cerrar la encuesta.",
                )
            if poll.status == "pending_announcement":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="La encuesta aún no está disponible para cerrar.",
                )

            if poll.status == "open":
                reason = "deadline" if poll.closes_at <= now else "manual"
                delivery_id = await self._close_poll_in_transaction(
                    session, poll, reason=reason, closed_at=now
                )
            else:
                delivery_id = await self._pending_closure_delivery(session, poll_id)

        if delivery_id is not None:
            await self._process_message_delivery(delivery_id)
        return await self._read_poll(poll_id)

    async def get_poll(self, poll_id: UUID) -> PollResponse:
        await self._close_due_poll(poll_id)
        await self._expire_pending_announcement(poll_id)
        return await self._read_poll(poll_id)

    async def close_expired_polls(self, batch_size: int = 100) -> None:
        await self._expire_pending_announcements(batch_size)
        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            poll_ids = list(
                await session.scalars(
                    select(Poll.poll_id)
                    .where(Poll.status == "open", Poll.closes_at <= now)
                    .order_by(Poll.closes_at)
                    .limit(batch_size)
                )
            )

        for poll_id in poll_ids:
            await self._close_due_poll(poll_id)

    async def process_pending_messages(self, batch_size: int = 50) -> None:
        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            delivery_ids = list(
                await session.scalars(
                    select(MessageDelivery.delivery_id)
                    .where(
                        or_(
                            (MessageDelivery.status == "pending")
                            & (MessageDelivery.next_attempt_at <= now),
                            (MessageDelivery.status == "processing")
                            & (MessageDelivery.lease_until <= now),
                        )
                    )
                    .order_by(MessageDelivery.next_attempt_at)
                    .limit(batch_size)
                )
            )

        for delivery_id in delivery_ids:
            await self._process_message_delivery(delivery_id)

    async def publish_pending_events(self, batch_size: int = 100) -> None:
        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            event_ids = list(
                await session.scalars(
                    select(OutboxEvent.event_id)
                    .where(
                        OutboxEvent.published_at.is_(None),
                        OutboxEvent.next_attempt_at <= now,
                        or_(OutboxEvent.lease_until.is_(None), OutboxEvent.lease_until <= now),
                    )
                    .order_by(OutboxEvent.occurred_at)
                    .limit(batch_size)
                )
            )

        for event_id in event_ids:
            await self._publish_outbox_event(event_id)

    async def run_background_worker(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.close_expired_polls()
                await self.process_pending_messages()
                await self.publish_pending_events()
            except Exception:
                logger.exception("Error en el worker de Polls")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._close_scan_interval)
            except TimeoutError:
                continue

    async def _return_idempotent_poll(self, poll_id: UUID, request_hash: str) -> CreatePollResult:
        async with self._sessions() as session:
            record = await session.get(Poll, poll_id)
            if record is None or record.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency-Key ya fue utilizado con otro contenido.",
                )
            delivery_id = await self._announcement_delivery_id(session, poll_id)

        poll = await self._read_poll(poll_id)
        if poll.status == "creation_failed":
            await self._raise_creation_error(poll_id)

        if poll.status == "pending_announcement" and delivery_id is not None:
            await self._process_message_delivery(delivery_id)
            poll = await self._read_poll(poll_id)
            if poll.status == "creation_failed":
                await self._raise_creation_error(poll_id)

        return CreatePollResult(
            poll=poll,
            status_code=(
                status.HTTP_202_ACCEPTED
                if poll.status == "pending_announcement"
                else status.HTTP_200_OK
            ),
        )

    async def _expire_pending_announcements(self, batch_size: int) -> None:
        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            poll_ids = list(
                await session.scalars(
                    select(Poll.poll_id)
                    .where(
                        Poll.status == "pending_announcement",
                        Poll.closes_at <= now,
                    )
                    .order_by(Poll.closes_at)
                    .limit(batch_size)
                )
            )
        for poll_id in poll_ids:
            await self._expire_pending_announcement(poll_id)

    async def _expire_pending_announcement(self, poll_id: UUID) -> None:
        now = datetime.now(timezone.utc)
        async with self._sessions() as session, session.begin():
            poll = await self._locked_poll(session, poll_id)
            if poll is None or poll.status != "pending_announcement" or poll.closes_at > now:
                return
            delivery = await session.scalar(
                select(MessageDelivery)
                .where(
                    MessageDelivery.poll_id == poll_id,
                    MessageDelivery.kind == "announcement",
                )
                .with_for_update()
            )
            if delivery is not None and delivery.status == "processing":
                if delivery.lease_until is not None and delivery.lease_until > now:
                    return
            poll.status = "creation_failed"
            poll.creation_error_status = status.HTTP_410_GONE
            poll.creation_error_detail = "La duración venció antes de publicar el anuncio."
            if delivery is not None and delivery.status != "sent":
                delivery.status = "failed"
                delivery.lease_until = None
                delivery.last_error = poll.creation_error_detail

    async def _find_idempotent_poll(self, author_id: str, key: str) -> UUID | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(Poll.poll_id).where(
                    Poll.author_id == author_id,
                    Poll.idempotency_key == key,
                )
            )

    async def _close_due_poll(self, poll_id: UUID) -> None:
        delivery_id: UUID | None = None
        now = datetime.now(timezone.utc)
        async with self._sessions() as session, session.begin():
            poll = await self._locked_poll(session, poll_id)
            if poll is not None and poll.status == "open" and poll.closes_at <= now:
                delivery_id = await self._close_poll_in_transaction(
                    session, poll, reason="deadline", closed_at=now
                )
        if delivery_id is not None:
            await self._process_message_delivery(delivery_id)

    async def _close_poll_in_transaction(
        self,
        session: AsyncSession,
        poll: Poll,
        reason: Literal["manual", "deadline"],
        closed_at: datetime,
    ) -> UUID:
        poll.status = "closed"
        poll.closed_at = closed_at
        response = await self._poll_response(session, poll)
        session.add(
            OutboxEvent(
                event_id=uuid4(),
                poll_id=poll.poll_id,
                event_type="poll.closed",
                payload={"poll": response.model_dump(mode="json"), "reason": reason},
                occurred_at=closed_at,
                attempt_count=0,
                next_attempt_at=closed_at,
            )
        )
        delivery_id = uuid4()
        session.add(
            MessageDelivery(
                delivery_id=delivery_id,
                poll_id=poll.poll_id,
                kind="final_results",
                status="pending",
                attempt_count=0,
                next_attempt_at=closed_at,
                created_at=closed_at,
            )
        )
        return delivery_id

    async def _process_message_delivery(self, delivery_id: UUID) -> None:
        if not self._messages_client.enabled:
            await self._skip_message_delivery(delivery_id)
            return

        attempt = await self._claim_message_delivery(delivery_id)
        if attempt is None:
            return

        try:
            await self._messages_client.post_message(
                channel_id=attempt.channel_id,
                user_id=attempt.author_id,
                content=attempt.content,
            )
        except MessagesRejected as error:
            await self._finish_message_failure(attempt, error, rejected=attempt.kind == "announcement")
        except MessagesClientError as error:
            await self._finish_message_failure(attempt, error, rejected=False)
        except Exception as error:
            logger.exception("Falló la entrega %s a Messages", delivery_id)
            await self._finish_message_failure(attempt, error, rejected=False)
        else:
            await self._finish_message_success(attempt)

    async def _skip_message_delivery(self, delivery_id: UUID) -> None:
        now = datetime.now(timezone.utc)
        async with self._sessions() as session, session.begin():
            claim = await session.execute(
                update(MessageDelivery)
                .where(
                    MessageDelivery.delivery_id == delivery_id,
                    MessageDelivery.status.in_(["pending", "processing"]),
                )
                .values(
                    status="skipped",
                    lease_until=None,
                    last_error="Omitido: integración con Messages deshabilitada.",
                )
                .returning(MessageDelivery.poll_id, MessageDelivery.kind)
            )
            claimed = claim.one_or_none()
            if claimed is None:
                return

            poll_id, kind = claimed
            poll = await self._locked_poll(session, poll_id)
            if poll is None:
                return

            logger.warning(
                "Se omitió la publicación %s a Messages para la encuesta %s: MESSAGES_ENABLED=false.",
                kind,
                poll_id,
            )
            if kind == "announcement" and poll.status == "pending_announcement":
                poll.status = "open"
                response = await self._poll_response(session, poll)
                session.add(
                    OutboxEvent(
                        event_id=uuid4(),
                        poll_id=poll.poll_id,
                        event_type="poll.created",
                        payload=response.model_dump(mode="json"),
                        occurred_at=now,
                        attempt_count=0,
                        next_attempt_at=now,
                    )
                )

    async def _claim_message_delivery(self, delivery_id: UUID) -> MessageAttempt | None:
        now = datetime.now(timezone.utc)
        async with self._sessions() as session, session.begin():
            claim = await session.execute(
                update(MessageDelivery)
                .where(
                    MessageDelivery.delivery_id == delivery_id,
                    or_(
                        and_(
                            MessageDelivery.status == "pending",
                            MessageDelivery.next_attempt_at <= now,
                        ),
                        and_(
                            MessageDelivery.status == "processing",
                            or_(
                                MessageDelivery.lease_until.is_(None),
                                MessageDelivery.lease_until <= now,
                            ),
                        ),
                    ),
                )
                .values(
                    status="processing",
                    attempt_count=MessageDelivery.attempt_count + 1,
                    lease_until=now + timedelta(seconds=LEASE_SECONDS),
                )
                .returning(MessageDelivery.delivery_id)
            )
            if claim.scalar_one_or_none() is None:
                return None
            delivery = await session.get(MessageDelivery, delivery_id, populate_existing=True)
            if delivery is None:
                return None

            poll = await self._locked_poll(session, delivery.poll_id)
            if poll is None:
                delivery.status = "failed"
                delivery.last_error = "Encuesta no encontrada."
                return None

            if delivery.kind == "announcement":
                if poll.status != "pending_announcement":
                    delivery.status = "failed"
                    delivery.last_error = "La encuesta ya no está pendiente de anuncio."
                    return None
                if poll.closes_at <= now:
                    poll.status = "creation_failed"
                    poll.creation_error_status = status.HTTP_410_GONE
                    poll.creation_error_detail = "La duración venció antes de publicar el anuncio."
                    delivery.status = "failed"
                    delivery.last_error = poll.creation_error_detail
                    return None
            elif poll.status != "closed":
                delivery.status = "failed"
                delivery.last_error = "La encuesta no está cerrada."
                return None

            response = await self._poll_response(session, poll)
            content = (
                build_poll_announcement(response)
                if delivery.kind == "announcement"
                else build_poll_results(response)
            )
            return MessageAttempt(
                delivery_id=delivery.delivery_id,
                poll_id=poll.poll_id,
                kind=delivery.kind,
                channel_id=poll.channel_id,
                author_id=poll.author_id,
                content=content,
            )

    async def _finish_message_success(self, attempt: MessageAttempt) -> None:
        now = datetime.now(timezone.utc)
        async with self._sessions() as session, session.begin():
            delivery = await session.get(MessageDelivery, attempt.delivery_id)
            poll = await self._locked_poll(session, attempt.poll_id)
            if delivery is None or poll is None or delivery.status in {"sent", "skipped"}:
                return
            delivery.status = "sent" if self._messages_client.enabled else "skipped"
            delivery.sent_at = now if self._messages_client.enabled else None
            delivery.lease_until = None
            delivery.last_error = (
                None
                if self._messages_client.enabled
                else "Omitido: integración con Messages deshabilitada."
            )

            if attempt.kind == "announcement" and poll.status == "pending_announcement":
                if poll.closes_at <= now:
                    poll.status = "creation_failed"
                    poll.creation_error_status = status.HTTP_410_GONE
                    poll.creation_error_detail = "La duración venció antes de publicar el anuncio."
                    delivery.last_error = poll.creation_error_detail
                    return
                poll.status = "open"
                response = await self._poll_response(session, poll)
                session.add(
                    OutboxEvent(
                        event_id=uuid4(),
                        poll_id=poll.poll_id,
                        event_type="poll.created",
                        payload=response.model_dump(mode="json"),
                        occurred_at=now,
                        attempt_count=0,
                        next_attempt_at=now,
                    )
                )

    async def _finish_message_failure(
        self,
        attempt: MessageAttempt,
        error: Exception,
        rejected: bool,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self._sessions() as session, session.begin():
            delivery = await session.get(MessageDelivery, attempt.delivery_id)
            poll = await self._locked_poll(session, attempt.poll_id)
            if delivery is None or delivery.status == "sent":
                return

            delivery.lease_until = None
            delivery.last_error = str(error)[:2000]
            if rejected:
                delivery.status = "failed"
                if poll is not None:
                    poll.status = "creation_failed"
                    poll.creation_error_status = getattr(error, "status_code", status.HTTP_502_BAD_GATEWAY)
                    poll.creation_error_detail = str(error)[:2000]
                return

            delivery.status = "pending"
            delivery.next_attempt_at = now + self._retry_delay(delivery.attempt_count)

    async def _publish_outbox_event(self, event_id: UUID) -> None:
        now = datetime.now(timezone.utc)
        event_type: str
        payload: dict[str, object]
        async with self._sessions() as session, session.begin():
            claim = await session.execute(
                update(OutboxEvent)
                .where(
                    OutboxEvent.event_id == event_id,
                    OutboxEvent.published_at.is_(None),
                    OutboxEvent.next_attempt_at <= now,
                    or_(OutboxEvent.lease_until.is_(None), OutboxEvent.lease_until <= now),
                )
                .values(
                    lease_until=now + timedelta(seconds=LEASE_SECONDS),
                    attempt_count=OutboxEvent.attempt_count + 1,
                )
                .returning(OutboxEvent.event_id)
            )
            if claim.scalar_one_or_none() is None:
                return
            event = await session.get(OutboxEvent, event_id, populate_existing=True)
            if event is None:
                return
            event_type = event.event_type
            payload = event.payload

        try:
            await self._event_publisher.publish(event_type, payload, event_id=str(event_id))
        except Exception as error:
            logger.exception("Falló la publicación de %s (%s)", event_type, event_id)
            async with self._sessions() as session, session.begin():
                event = await session.get(OutboxEvent, event_id)
                if event is not None and event.published_at is None:
                    event.lease_until = None
                    event.last_error = str(error)[:2000]
                    event.next_attempt_at = now + self._retry_delay(event.attempt_count)
            return

        async with self._sessions() as session, session.begin():
            event = await session.get(OutboxEvent, event_id)
            if event is not None and event.published_at is None:
                event.published_at = datetime.now(timezone.utc)
                event.lease_until = None
                event.last_error = None

    async def _read_poll(self, poll_id: UUID) -> PollResponse:
        async with self._sessions() as session:
            poll = await session.scalar(
                select(Poll)
                .options(selectinload(Poll.options))
                .where(Poll.poll_id == poll_id)
            )
            if poll is None:
                raise self._poll_not_found()
            return await self._poll_response(session, poll)

    async def _poll_response(self, session: AsyncSession, poll: Poll) -> PollResponse:
        result = await session.execute(
            select(Vote.option_id, func.count())
            .where(Vote.poll_id == poll.poll_id)
            .group_by(Vote.option_id)
        )
        counts = {option_id: count for option_id, count in result.all()}
        return PollResponse(
            poll_id=poll.poll_id,
            channel_id=poll.channel_id,
            author_id=poll.author_id,
            question=poll.question,
            options=[
                OptionResult(
                    option_id=option.option_id,
                    position=option.position,
                    text=option.text,
                    vote_count=counts.get(option.option_id, 0),
                )
                for option in poll.options
            ],
            status=poll.status,
            duration_minutes=poll.duration_minutes,
            closes_at=poll.closes_at,
            created_at=poll.created_at,
            closed_at=poll.closed_at,
            total_votes=sum(counts.values()),
            creation_error=poll.creation_error_detail,
        )

    async def _locked_poll(self, session: AsyncSession, poll_id: UUID) -> Poll | None:
        return await session.scalar(
            select(Poll)
            .options(selectinload(Poll.options))
            .where(Poll.poll_id == poll_id)
            .with_for_update()
        )

    async def _announcement_delivery_id(
        self,
        session: AsyncSession,
        poll_id: UUID,
    ) -> UUID | None:
        return await session.scalar(
            select(MessageDelivery.delivery_id).where(
                MessageDelivery.poll_id == poll_id,
                MessageDelivery.kind == "announcement",
            )
        )

    async def _pending_closure_delivery(
        self,
        session: AsyncSession,
        poll_id: UUID,
    ) -> UUID | None:
        delivery = await session.scalar(
            select(MessageDelivery).where(
                MessageDelivery.poll_id == poll_id,
                MessageDelivery.kind == "final_results",
            )
        )
        if delivery is None or delivery.status in {"sent", "failed", "skipped"}:
            return None
        return delivery.delivery_id

    async def _raise_creation_error(self, poll_id: UUID) -> None:
        async with self._sessions() as session:
            poll = await session.get(Poll, poll_id)
        if poll is None:
            raise self._poll_not_found()
        raise HTTPException(
            status_code=poll.creation_error_status or status.HTTP_502_BAD_GATEWAY,
            detail=poll.creation_error_detail or "No se pudo publicar el anuncio de la encuesta.",
        )

    @staticmethod
    def _poll_not_found() -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encuesta no encontrada.",
        )

    @staticmethod
    def _creation_failed(poll: Poll) -> HTTPException:
        return HTTPException(
            status_code=poll.creation_error_status or status.HTTP_410_GONE,
            detail=poll.creation_error_detail or "No se pudo publicar el anuncio de la encuesta.",
        )

    @staticmethod
    def _validate_idempotency_key(key: str | None) -> str | None:
        if key is None:
            return None
        key = key.strip()
        if not key or len(key) > 255:
            raise HTTPException(
                status_code=422,
                detail="Idempotency-Key debe tener entre 1 y 255 caracteres.",
            )
        return key

    @staticmethod
    def _request_hash(request: PollCreateRequest) -> str:
        canonical = json.dumps(
            request.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _retry_delay(self, attempt_count: int) -> timedelta:
        seconds = min(
            MAX_RETRY_SECONDS,
            self._retry_base_seconds * (2 ** max(0, attempt_count - 1)),
        )
        return timedelta(seconds=seconds)
