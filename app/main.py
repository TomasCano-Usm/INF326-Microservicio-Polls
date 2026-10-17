import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from uuid import UUID

from fastapi import FastAPI, Header, Request, status
from fastapi.responses import JSONResponse

from app.clients import ReferenceClient, reference_client_from_env
from app.db import Database
from app.events import EventPublisher, RabbitMQEventPublisher
from app.messages import ChannelMessagesClient, messages_client_from_env
from app.models import CloseRequest, PollCreateRequest, PollListResponse, PollResponse, PollSummary, VoteRequest, VoteResponse
from app.service import CreatePollResult, PollService
from app.version import __version__


PublisherFactory = Callable[[], EventPublisher]
MessagesClientFactory = Callable[[], ChannelMessagesClient]
DatabaseFactory = Callable[[], Database]
ReferenceClientFactory = Callable[[], ReferenceClient]


def create_app(
    publisher_factory: PublisherFactory = RabbitMQEventPublisher,
    messages_client_factory: MessagesClientFactory = messages_client_from_env,
    database_factory: DatabaseFactory = Database,
    reference_client_factory: ReferenceClientFactory = reference_client_from_env,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        messages_client = messages_client_factory()
        database = database_factory()
        publisher = publisher_factory()
        reference_client = reference_client_factory()
        try:
            await database.connect()
            await publisher.connect()
            await messages_client.connect()
            await reference_client.connect()
        except Exception:
            with suppress(Exception):
                await messages_client.close()
            with suppress(Exception):
                await publisher.close()
            with suppress(Exception):
                await database.close()
            with suppress(Exception):
                await reference_client.close()
            raise

        close_scan_interval = float(os.getenv("POLL_CLOSE_SCAN_INTERVAL_SECONDS", "1"))
        service = PollService(
            database,
            publisher,
            messages_client,
            reference_client,
            close_scan_interval=close_scan_interval,
        )
        application.state.database = database
        application.state.poll_service = service
        stop_worker = asyncio.Event()
        worker = asyncio.create_task(service.run_background_worker(stop_worker))
        try:
            yield
        finally:
            stop_worker.set()
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            try:
                await messages_client.close()
            finally:
                try:
                    await publisher.close()
                finally:
                    try:
                        await reference_client.close()
                    finally:
                        await database.close()

    application = FastAPI(
        title="Microservicio de encuestas",
        description="API REST v1 para crear, responder y consultar encuestas.",
        version=__version__,
        lifespan=lifespan,
    )

    @application.get("/health", tags=["Salud"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @application.post(
        "/api/v1/polls",
        response_model=PollResponse,
        responses={
            status.HTTP_200_OK: {"model": PollResponse},
            status.HTTP_202_ACCEPTED: {"model": PollResponse},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["Encuestas"],
    )
    async def create_poll(
        payload: PollCreateRequest,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        result: CreatePollResult = await get_service(request).create_poll(payload, idempotency_key)
        return JSONResponse(
            status_code=result.status_code,
            content=result.poll.model_dump(mode="json"),
        )

    @application.post(
        "/api/v1/polls/{poll_id}/votes",
        response_model=VoteResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["Votos"],
    )
    async def cast_vote(poll_id: UUID, payload: VoteRequest, request: Request) -> VoteResponse:
        return await get_service(request).cast_vote(poll_id, payload)

    @application.post(
        "/api/v1/polls/{poll_id}/close",
        response_model=PollResponse,
        tags=["Encuestas"],
    )
    async def close_poll(poll_id: UUID, payload: CloseRequest, request: Request) -> PollResponse:
        return await get_service(request).close_poll(poll_id, payload)

    @application.get(
        "/api/v1/polls/{poll_id}",
        response_model=PollResponse,
        tags=["Encuestas"],
    )
    async def get_poll(poll_id: UUID, request: Request) -> PollResponse:
        return await get_service(request).get_poll(poll_id)

    @application.get(
        "/api/v1/polls",
        response_model=PollListResponse,
        tags=["Encuestas"],
    )
    async def list_polls(
        request: Request,
        channel_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> PollListResponse:
        polls = await get_service(request).list_polls(channel_id, limit, offset)
        return PollListResponse(polls=polls)

    return application


def get_service(request: Request) -> PollService:
    return request.app.state.poll_service


app = create_app()
