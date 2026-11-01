"""Reconcile RabbitMQ queues and read-only accounts for external Polls consumers."""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlsplit

import httpx


logger = logging.getLogger(__name__)

EXCHANGE_NAME = "polls.events"
ALLOWED_ROUTING_KEYS = frozenset(
    {"poll.created", "poll.vote.cast", "poll.closed"}
)
GROUP_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SECRET_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ConsumerSpec:
    group: str
    routing_keys: tuple[str, ...]
    password: str = field(repr=False)

    @property
    def username(self) -> str:
        return f"polls-{self.group}"

    @property
    def queue_name(self) -> str:
        return f"polls.consumer.{self.group}"

    @property
    def queue_read_pattern(self) -> str:
        return rf"^polls\.consumer\.{self.group}$"


class RabbitMQConsumerProvisioner:
    """Provision consumers through the broker's authenticated Management API."""

    def __init__(
        self,
        management_url: str,
        admin_url: str,
        consumers: tuple[ConsumerSpec, ...],
        remove_groups: tuple[str, ...] = (),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed_management_url = urlsplit(management_url)
        if parsed_management_url.scheme not in {"http", "https"} or not parsed_management_url.netloc:
            raise ValueError("RABBITMQ_MANAGEMENT_URL debe ser una URL HTTP(S) válida.")

        parsed_admin_url = urlsplit(admin_url)
        if (
            parsed_admin_url.scheme not in {"amqp", "amqps"}
            or not parsed_admin_url.hostname
            or parsed_admin_url.username is None
            or parsed_admin_url.password is None
        ):
            raise ValueError("RABBITMQ_URL debe incluir las credenciales AMQP administrativas.")

        self.management_url = management_url.rstrip("/")
        self.admin_username = unquote(parsed_admin_url.username)
        self.admin_password = unquote(parsed_admin_url.password)
        self.consumers = consumers
        self.remove_groups = remove_groups
        self._transport = transport
        self._validate_configuration()

    @classmethod
    def from_env(cls) -> "RabbitMQConsumerProvisioner":
        config_text = os.getenv("CONSUMERS_JSON", '{"consumers": [], "remove_groups": []}')
        consumers, remove_groups = cls._parse_consumers(config_text, os.environ)
        return cls(
            management_url=os.getenv("RABBITMQ_MANAGEMENT_URL", ""),
            admin_url=os.getenv("RABBITMQ_URL", ""),
            consumers=consumers,
            remove_groups=remove_groups,
        )

    @staticmethod
    def _parse_consumers(
        config_text: str,
        environment: dict[str, str],
    ) -> tuple[tuple[ConsumerSpec, ...], tuple[str, ...]]:
        try:
            config = json.loads(config_text)
        except json.JSONDecodeError as error:
            raise ValueError("CONSUMERS_JSON debe contener JSON válido.") from error

        if not isinstance(config, dict):
            raise ValueError("CONSUMERS_JSON debe ser un objeto JSON.")
        consumer_configs = config.get("consumers", [])
        remove_groups = config.get("remove_groups", [])
        if not isinstance(consumer_configs, list) or not isinstance(remove_groups, list):
            raise ValueError("consumers y remove_groups deben ser listas.")

        consumers: list[ConsumerSpec] = []
        for item in consumer_configs:
            if not isinstance(item, dict):
                raise ValueError("Cada consumidor debe ser un objeto JSON.")
            group = item.get("group")
            routing_keys = item.get("routing_keys")
            password_key = item.get("password_key")
            if not isinstance(group, str) or not isinstance(routing_keys, list):
                raise ValueError("Cada consumidor requiere group y routing_keys.")
            if not isinstance(password_key, str) or not SECRET_KEY_PATTERN.fullmatch(password_key):
                raise ValueError("password_key debe nombrar una key válida del Secret externo.")
            password = environment.get(password_key, "")
            if not password:
                raise ValueError(f"Falta la credencial indicada por la key {password_key}.")
            if any(not isinstance(key, str) for key in routing_keys):
                raise ValueError("routing_keys solo puede contener strings.")
            consumers.append(ConsumerSpec(group, tuple(routing_keys), password))

        if any(not isinstance(group, str) for group in remove_groups):
            raise ValueError("remove_groups solo puede contener strings.")
        return tuple(consumers), tuple(remove_groups)

    def _validate_configuration(self) -> None:
        groups = [consumer.group for consumer in self.consumers]
        if len(groups) != len(set(groups)):
            raise ValueError("CONSUMERS_JSON no puede repetir grupos.")
        if len(self.remove_groups) != len(set(self.remove_groups)):
            raise ValueError("remove_groups no puede repetir grupos.")
        if set(groups) & set(self.remove_groups):
            raise ValueError("Un grupo no puede provisionarse y eliminarse en la misma ejecución.")

        for consumer in self.consumers:
            self._validate_group(consumer.group)
            if not consumer.password:
                raise ValueError(f"Falta una contraseña para el grupo {consumer.group}.")
            if not consumer.routing_keys:
                raise ValueError(f"El grupo {consumer.group} debe tener al menos un routing key.")
            if len(consumer.routing_keys) != len(set(consumer.routing_keys)):
                raise ValueError(f"El grupo {consumer.group} repite routing keys.")
            unsupported = set(consumer.routing_keys) - ALLOWED_ROUTING_KEYS
            if unsupported:
                raise ValueError(
                    f"Routing keys no permitidos para {consumer.group}: "
                    + ", ".join(sorted(unsupported))
                )

        for group in self.remove_groups:
            self._validate_group(group)

    @staticmethod
    def _validate_group(group: str) -> None:
        if not GROUP_PATTERN.fullmatch(group):
            raise ValueError("group debe usar solo minúsculas, números y guiones simples.")

    async def reconcile(self) -> None:
        auth = (self.admin_username, self.admin_password)
        async with httpx.AsyncClient(
            base_url=self.management_url,
            auth=auth,
            timeout=10,
            transport=self._transport,
        ) as client:
            await self._ensure_exchange(client)
            for group in self.remove_groups:
                await self._remove_consumer(client, group)
            for consumer in self.consumers:
                await self._ensure_consumer(client, consumer)

        logger.info(
            "RabbitMQ consumer provisioning reconciled: %d active, %d removed.",
            len(self.consumers),
            len(self.remove_groups),
        )

    async def _ensure_exchange(self, client: httpx.AsyncClient) -> None:
        await self._request(
            client,
            "PUT",
            f"/api/exchanges/{self._vhost_path()}/{quote(EXCHANGE_NAME, safe='')}",
            json={
                "type": "topic",
                "durable": True,
                "auto_delete": False,
                "internal": False,
                "arguments": {},
            },
        )

    async def _ensure_consumer(
        self,
        client: httpx.AsyncClient,
        consumer: ConsumerSpec,
    ) -> None:
        username_path = quote(consumer.username, safe="")
        queue_path = quote(consumer.queue_name, safe="")
        await self._request(
            client,
            "PUT",
            f"/api/users/{username_path}",
            json={"password": consumer.password, "tags": ""},
        )
        await self._request(
            client,
            "PUT",
            f"/api/permissions/{self._vhost_path()}/{username_path}",
            json={
                "configure": "^$",
                "write": "^$",
                "read": consumer.queue_read_pattern,
            },
        )
        await self._request(
            client,
            "PUT",
            f"/api/queues/{self._vhost_path()}/{queue_path}",
            json={"durable": True, "auto_delete": False, "arguments": {}},
        )
        await self._reconcile_bindings(client, consumer, queue_path)

    async def _reconcile_bindings(
        self,
        client: httpx.AsyncClient,
        consumer: ConsumerSpec,
        queue_path: str,
    ) -> None:
        bindings_path = (
            f"/api/bindings/{self._vhost_path()}/e/"
            f"{quote(EXCHANGE_NAME, safe='')}/q/{queue_path}"
        )
        response = await self._request(client, "GET", bindings_path)
        existing = response.json()
        if not isinstance(existing, list):
            raise RuntimeError("RabbitMQ devolvió una lista de bindings inválida.")

        desired = set(consumer.routing_keys)
        current: set[str] = set()
        for binding in existing:
            routing_key = binding.get("routing_key")
            properties_key = binding.get("properties_key")
            if not isinstance(routing_key, str) or not isinstance(properties_key, str):
                raise RuntimeError("RabbitMQ devolvió un binding sin propiedades esperadas.")
            if routing_key in desired:
                current.add(routing_key)
                continue
            await self._request(
                client,
                "DELETE",
                f"{bindings_path}/{quote(properties_key, safe='')}",
                allow_not_found=True,
            )

        for routing_key in sorted(desired - current):
            await self._request(
                client,
                "POST",
                bindings_path,
                json={"routing_key": routing_key, "arguments": {}},
            )

    async def _remove_consumer(self, client: httpx.AsyncClient, group: str) -> None:
        queue_name = f"polls.consumer.{group}"
        username = f"polls-{group}"
        await self._request(
            client,
            "DELETE",
            f"/api/queues/{self._vhost_path()}/{quote(queue_name, safe='')}?"
            "if-unused=true&if-empty=true",
            allow_not_found=True,
        )
        await self._request(
            client,
            "DELETE",
            f"/api/users/{quote(username, safe='')}",
            allow_not_found=True,
        )

    @staticmethod
    def _vhost_path() -> str:
        return quote("/", safe="")

    @staticmethod
    async def _request(
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        allow_not_found: bool = False,
    ) -> httpx.Response:
        response = await client.request(method, path, json=json)
        if allow_not_found and response.status_code == 404:
            return response
        if not response.is_success:
            raise RuntimeError(
                f"RabbitMQ Management API respondió HTTP {response.status_code} "
                f"al ejecutar {method} {path}."
            )
        return response


async def provision_from_env() -> None:
    await RabbitMQConsumerProvisioner.from_env().reconcile()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(provision_from_env())


if __name__ == "__main__":
    main()
