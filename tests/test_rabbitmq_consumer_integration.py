"""Optional end-to-end ACL tests against a disposable RabbitMQ Management node."""

import asyncio
import json
import os
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import aio_pika
import httpx
import pytest
from aio_pika import DeliveryMode, Message

from app.events import RabbitMQEventPublisher
from app.rabbitmq_consumer_provisioner import ConsumerSpec, RabbitMQConsumerProvisioner


ADMIN_AMQP_URL = os.getenv("POLLS_TEST_RABBITMQ_URL")
MANAGEMENT_URL = os.getenv("POLLS_TEST_RABBITMQ_MANAGEMENT_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_AMQP_URL or not MANAGEMENT_URL,
    reason="Configura POLLS_TEST_RABBITMQ_URL y POLLS_TEST_RABBITMQ_MANAGEMENT_URL para RabbitMQ real.",
)


def consumer_url(admin_url: str, username: str, password: str) -> str:
    parsed = urlsplit(admin_url)
    if not parsed.hostname:
        raise ValueError("La URL RabbitMQ de pruebas debe incluir un host.")
    authority = f"{quote(username, safe='')}:{quote(password, safe='')}@{parsed.hostname}"
    if parsed.port is not None:
        authority += f":{parsed.port}"
    return urlunsplit(("amqp", authority, "/%2F", "", ""))


def test_external_consumer_acl_publish_denial_and_reprovisioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        assert ADMIN_AMQP_URL is not None
        assert MANAGEMENT_URL is not None
        group_a = f"it-a-{uuid4().hex[:8]}"
        group_b = f"it-b-{uuid4().hex[:8]}"
        password_a = uuid4().hex
        password_b = uuid4().hex
        consumer_a = ConsumerSpec(group_a, ("poll.created",), password_a)
        consumer_b = ConsumerSpec(group_b, ("poll.vote.cast",), password_b)
        provisioner = RabbitMQConsumerProvisioner(
            management_url=MANAGEMENT_URL,
            admin_url=ADMIN_AMQP_URL,
            consumers=(consumer_a, consumer_b),
        )
        remover = RabbitMQConsumerProvisioner(
            management_url=MANAGEMENT_URL,
            admin_url=ADMIN_AMQP_URL,
            consumers=(),
            remove_groups=(group_a, group_b),
        )
        consumer_connection = None
        publisher: RabbitMQEventPublisher | None = None

        try:
            await provisioner.reconcile()
            await provisioner.reconcile()

            consumer_connection = await aio_pika.connect(
                consumer_url(ADMIN_AMQP_URL, consumer_a.username, password_a),
                timeout=5,
            )
            consumer_channel = await consumer_connection.channel()
            queue = await consumer_channel.declare_queue(consumer_a.queue_name, passive=True)

            monkeypatch.setenv("RABBITMQ_URL", ADMIN_AMQP_URL)
            monkeypatch.setenv("RABBITMQ_EXCHANGE", "polls.events")
            publisher = RabbitMQEventPublisher()
            event_id = str(uuid4())
            await publisher.publish(
                "poll.created",
                {"poll_id": str(uuid4())},
                event_id=event_id,
            )
            message = await queue.get(timeout=5, fail=True)
            async with message.process():
                envelope = json.loads(message.body)
                assert envelope["event_id"] == event_id
                assert envelope["event_type"] == "poll.created"

            publish_channel = await consumer_connection.channel(publisher_confirms=True)
            exchange = await publish_channel.get_exchange("polls.events", ensure=False)
            with pytest.raises(Exception, match="(?i)access_refused|access refused"):
                await exchange.publish(
                    Message(body=b"consumer must not publish", delivery_mode=DeliveryMode.PERSISTENT),
                    routing_key="poll.created",
                )

            other_queue_channel = await consumer_connection.channel()
            with pytest.raises(Exception, match="(?i)access_refused|access refused"):
                await other_queue_channel.declare_queue(consumer_b.queue_name, passive=True)

            async with httpx.AsyncClient(
                base_url=MANAGEMENT_URL,
                auth=(consumer_a.username, password_a),
                timeout=5,
            ) as management_client:
                management_response = await management_client.get("/api/overview")
            assert management_response.status_code in {401, 403}

            invalid_url = consumer_url(
                ADMIN_AMQP_URL,
                consumer_a.username,
                f"invalid-{password_a}",
            )
            with pytest.raises(Exception, match="(?i)access_refused|login was refused|invalid credentials"):
                await aio_pika.connect(invalid_url, timeout=5)

            await consumer_connection.close()
            consumer_connection = None
            await publisher.close()
            publisher = None

            # Simulate lost ephemeral broker definitions: provisioning restores the
            # same password and topology from the unchanged external configuration.
            await remover.reconcile()
            await provisioner.reconcile()
            restored = await aio_pika.connect(
                consumer_url(ADMIN_AMQP_URL, consumer_a.username, password_a),
                timeout=5,
            )
            await restored.close()
        finally:
            if consumer_connection is not None:
                await consumer_connection.close()
            if publisher is not None:
                await publisher.close()

    asyncio.run(run())
