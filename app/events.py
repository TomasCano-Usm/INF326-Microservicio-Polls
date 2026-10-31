import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message


logger = logging.getLogger(__name__)


class EventPublisher(Protocol):
    async def connect(self) -> None: ...

    async def publish(
        self,
        event_type: str,
        payload: dict[str, object],
        event_id: str | None = None,
    ) -> None: ...

    async def close(self) -> None: ...


class RabbitMQEventPublisher:
    def __init__(self) -> None:
        self.url = os.getenv("RABBITMQ_URL", "amqp://polls:polls-dev-password@localhost:5672/")
        self.exchange_name = os.getenv("RABBITMQ_EXCHANGE", "polls.events")
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None
        self._connection_lock = asyncio.Lock()

    async def connect(self) -> None:
        # RabbitMQ is optional at startup: the PostgreSQL outbox retries publishing later.
        return None

    async def _ensure_exchange(self) -> aio_pika.abc.AbstractExchange:
        if (
            self._connection is not None
            and not self._connection.is_closed
            and self._exchange is not None
        ):
            return self._exchange

        async with self._connection_lock:
            if (
                self._connection is not None
                and not self._connection.is_closed
                and self._exchange is not None
            ):
                return self._exchange

            connection = await aio_pika.connect_robust(self.url, timeout=10)
            try:
                channel = await connection.channel(publisher_confirms=True)
                exchange = await channel.declare_exchange(
                    self.exchange_name,
                    type=ExchangeType.TOPIC,
                    durable=True,
                )
            except Exception:
                await connection.close()
                raise

            self._connection = connection
            self._exchange = exchange
            logger.info("Conexión a RabbitMQ establecida con exchange %s", self.exchange_name)
            return exchange

    async def publish(
        self,
        event_type: str,
        payload: dict[str, object],
        event_id: str | None = None,
    ) -> None:
        exchange = await self._ensure_exchange()

        event_id = event_id or str(uuid4())
        occurred_at = datetime.now(timezone.utc)
        envelope = {
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat(),
            "payload": payload,
        }
        message = Message(
            body=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=event_id,
            timestamp=occurred_at,
            type=event_type,
        )
        await exchange.publish(message, routing_key=event_type)

    async def close(self) -> None:
        async with self._connection_lock:
            if self._connection is not None and not self._connection.is_closed:
                await self._connection.close()
            self._connection = None
            self._exchange = None
