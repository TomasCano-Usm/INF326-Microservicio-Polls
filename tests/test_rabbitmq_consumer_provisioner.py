import asyncio
import json
from urllib.parse import unquote

import httpx
import pytest

from app.rabbitmq_consumer_provisioner import (
    ConsumerSpec,
    RabbitMQConsumerProvisioner,
)


class MockManagementAPI:
    def __init__(self) -> None:
        self.exchanges: dict[str, dict[str, object]] = {}
        self.users: dict[str, dict[str, object]] = {}
        self.permissions: dict[str, dict[str, str]] = {}
        self.queues: dict[str, dict[str, object]] = {}
        self.bindings: dict[str, list[dict[str, object]]] = {}
        self.binding_posts = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        body = json.loads(request.content) if request.content else None
        parts = path.split("/")

        if request.method == "PUT" and path.endswith("/polls.events"):
            self.exchanges["polls.events"] = body
            return httpx.Response(204)

        if request.method == "PUT" and "/users/" in path:
            username = parts[-1]
            self.users[username] = body
            return httpx.Response(201)

        if request.method == "PUT" and "/permissions/" in path:
            username = parts[-1]
            self.permissions[username] = body
            return httpx.Response(200)

        if request.method == "PUT" and "/queues/" in path:
            queue_name = parts[-1]
            self.queues[queue_name] = body
            self.bindings.setdefault(queue_name, [])
            return httpx.Response(201)

        if "/bindings/" in path and request.method == "GET":
            return httpx.Response(200, json=self.bindings.get(parts[-1], []))

        if "/bindings/" in path and request.method == "POST":
            queue_name = parts[-1]
            bindings = self.bindings.setdefault(queue_name, [])
            if not any(item["routing_key"] == body["routing_key"] for item in bindings):
                self.binding_posts += 1
                bindings.append(
                    {
                        "routing_key": body["routing_key"],
                        "properties_key": f"{body['routing_key']}-properties",
                    }
                )
            return httpx.Response(201)

        if "/bindings/" in path and request.method == "DELETE":
            queue_name = parts[-2]
            properties_key = parts[-1]
            self.bindings[queue_name] = [
                item
                for item in self.bindings.get(queue_name, [])
                if item["properties_key"] != properties_key
            ]
            return httpx.Response(204)

        if request.method == "DELETE" and "/queues/" in path:
            queue_name = parts[-1]
            if queue_name not in self.queues:
                return httpx.Response(404)
            del self.queues[queue_name]
            self.bindings.pop(queue_name, None)
            return httpx.Response(204)

        if request.method == "DELETE" and "/users/" in path:
            username = parts[-1]
            if username not in self.users:
                return httpx.Response(404)
            del self.users[username]
            self.permissions.pop(username, None)
            return httpx.Response(204)

        return httpx.Response(404, json={"reason": "unexpected request"})


def test_provisioner_is_idempotent_and_consumer_is_read_only() -> None:
    management = MockManagementAPI()
    management.bindings["polls.consumer.grupo-a"] = [
        {"routing_key": "poll.vote.cast", "properties_key": "stale-binding"}
    ]
    provisioner = RabbitMQConsumerProvisioner(
        management_url="http://rabbitmq:15672",
        admin_url="amqp://polls:internal-test-value@rabbitmq:5672/",
        consumers=(
            ConsumerSpec(
                "grupo-a",
                ("poll.created", "poll.closed"),
                password="independent-test-value",
            ),
        ),
        transport=httpx.MockTransport(management),
    )

    async def run() -> None:
        await provisioner.reconcile()
        await provisioner.reconcile()

    asyncio.run(run())

    assert management.exchanges["polls.events"] == {
        "type": "topic",
        "durable": True,
        "auto_delete": False,
        "internal": False,
        "arguments": {},
    }
    assert management.users["polls-grupo-a"] == {
        "password": "independent-test-value",
        "tags": "",
    }
    assert management.permissions["polls-grupo-a"] == {
        "configure": "^$",
        "write": "^$",
        "read": r"^polls\.consumer\.grupo-a$",
    }
    assert management.queues["polls.consumer.grupo-a"] == {
        "durable": True,
        "auto_delete": False,
        "arguments": {},
    }
    assert {
        binding["routing_key"]
        for binding in management.bindings["polls.consumer.grupo-a"]
    } == {"poll.created", "poll.closed"}
    assert management.binding_posts == 2


def test_provisioner_rejects_routing_keys_outside_polls_contract() -> None:
    with pytest.raises(ValueError, match="Routing keys no permitidos"):
        RabbitMQConsumerProvisioner(
            management_url="http://rabbitmq:15672",
            admin_url="amqp://polls:internal-test-value@rabbitmq:5672/",
            consumers=(
                ConsumerSpec(
                    "grupo-a",
                    ("poll.deleted",),
                    password="independent-test-value",
                ),
            ),
        )


def test_provisioner_removes_only_requested_consumer_resources() -> None:
    management = MockManagementAPI()
    management.users["polls-grupo-a"] = {"tags": ""}
    management.permissions["polls-grupo-a"] = {"read": "queue"}
    management.queues["polls.consumer.grupo-a"] = {"durable": True}
    management.bindings["polls.consumer.grupo-a"] = []
    management.users["polls-grupo-b"] = {"tags": ""}
    management.permissions["polls-grupo-b"] = {"read": "queue"}
    management.queues["polls.consumer.grupo-b"] = {"durable": True}
    management.bindings["polls.consumer.grupo-b"] = []
    provisioner = RabbitMQConsumerProvisioner(
        management_url="http://rabbitmq:15672",
        admin_url="amqp://polls:internal-test-value@rabbitmq:5672/",
        consumers=(),
        remove_groups=("grupo-a",),
        transport=httpx.MockTransport(management),
    )

    asyncio.run(provisioner.reconcile())

    assert "polls-grupo-a" not in management.users
    assert "polls.consumer.grupo-a" not in management.queues
    assert "polls-grupo-b" in management.users
    assert "polls.consumer.grupo-b" in management.queues
