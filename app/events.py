import json
import os
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message


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

    async def connect(self) -> None:
        self._connection = await aio_pika.connect_robust(self.url, timeout=10)
        channel = await self._connection.channel(publisher_confirms=True)
        self._exchange = await channel.declare_exchange(
            self.exchange_name,
            type=ExchangeType.TOPIC,
            durable=True,
        )

    async def publish(
        self,
        event_type: str,
        payload: dict[str, object],
        event_id: str | None = None,
    ) -> None:
        if self._exchange is None:
            raise RuntimeError("El publicador RabbitMQ no está conectado.")

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
        await self._exchange.publish(message, routing_key=event_type)

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
