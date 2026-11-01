import asyncio

import aio_pika
import pytest

from app.events import RabbitMQEventPublisher


class FakeExchange:
    def __init__(self) -> None:
        self.messages: list[tuple[object, str]] = []

    async def publish(self, message, routing_key: str, mandatory: bool) -> None:
        assert mandatory is True
        self.messages.append((message, routing_key))


class FakeChannel:
    def __init__(self, exchange: FakeExchange) -> None:
        self.exchange = exchange
        self.publisher_confirms: bool | None = None
        self.on_return_raises: bool | None = None
        self.declaration: tuple[object, object, bool] | None = None

    async def declare_exchange(self, name, type, durable: bool):
        self.declaration = (name, type, durable)
        return self.exchange


class FakeConnection:
    def __init__(self, channel: FakeChannel) -> None:
        self._channel = channel
        self.is_closed = False
        self.publisher_confirms: bool | None = None
        self.closed = False

    async def channel(self, publisher_confirms: bool, on_return_raises: bool):
        self.publisher_confirms = publisher_confirms
        self.on_return_raises = on_return_raises
        return self._channel

    async def close(self) -> None:
        self.closed = True
        self.is_closed = True


def test_rabbitmq_connection_is_lazy_and_publish_retries_after_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = FakeExchange()
    channel = FakeChannel(exchange)
    connection = FakeConnection(channel)
    attempts = 0

    async def connect_robust(_url: str, timeout: int):
        nonlocal attempts
        attempts += 1
        assert timeout == 10
        if attempts == 1:
            raise OSError("RabbitMQ no disponible")
        return connection

    monkeypatch.setattr(aio_pika, "connect_robust", connect_robust)

    async def run() -> None:
        publisher = RabbitMQEventPublisher()
        await publisher.connect()
        assert attempts == 0

        with pytest.raises(OSError, match="RabbitMQ no disponible"):
            await publisher.publish("poll.created", {"poll_id": "poll-1"}, event_id="event-1")

        await publisher.publish("poll.created", {"poll_id": "poll-1"}, event_id="event-1")
        assert attempts == 2
        assert connection.publisher_confirms is True
        assert connection.on_return_raises is True
        assert channel.declaration == ("polls.events", aio_pika.ExchangeType.TOPIC, True)
        assert len(exchange.messages) == 1

        message, routing_key = exchange.messages[0]
        assert routing_key == "poll.created"
        assert message.message_id == "event-1"
        assert message.type == "poll.created"
        assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT

        await publisher.close()
        assert connection.closed

    asyncio.run(run())
