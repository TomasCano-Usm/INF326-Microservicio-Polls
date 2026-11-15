"""End-to-end QA flow against the isolated Docker Compose stack."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest


pytestmark = pytest.mark.integration

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path(__file__).parent / "contracts" / "messages-v1.openapi.json"
COMPOSE_COMMAND = [
    "docker",
    "compose",
    "--project-name",
    "polls-qa-integration",
    "-f",
    str(REPOSITORY_ROOT / "compose.qa.yaml"),
]
MESSAGES_CREATE_PATH = "/api/v1/channels/{channel_id}/messages"

POLLS_URL = os.getenv("POLLS_QA_BASE_URL", "http://127.0.0.1:18004").rstrip("/")
USERS_URL = os.getenv("POLLS_QA_USERS_URL", "http://127.0.0.1:18001").rstrip("/")
CHANNELS_URL = os.getenv("POLLS_QA_CHANNELS_URL", "http://127.0.0.1:18002").rstrip("/")
MESSAGES_URL = os.getenv("POLLS_QA_MESSAGES_URL", "http://127.0.0.1:18003").rstrip("/")


@pytest.fixture(scope="module", autouse=True)
def qa_compose_stack():
    """Start a dedicated local stack and always remove its containers and data."""
    try:
        version = subprocess.run(
            ["docker", "compose", "version"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        pytest.fail("Docker Desktop y el plugin `docker compose` deben estar disponibles.")
    if version.returncode != 0:
        pytest.fail(
            "Docker Compose no está disponible: "
            f"{version.stderr.strip() or version.stdout.strip()}"
        )

    try:
        subprocess.run(
            [*COMPOSE_COMMAND, "up", "--build", "--detach"],
            cwd=REPOSITORY_ROOT,
            check=True,
        )
        yield
    except BaseException:
        logs = subprocess.run(
            [*COMPOSE_COMMAND, "logs", "--no-color", "--tail=100"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if logs.stdout or logs.stderr:
            print("\n--- logs del stack QA ---", file=sys.stderr)
            print(logs.stdout, file=sys.stderr, end="")
            print(logs.stderr, file=sys.stderr, end="")
        raise
    finally:
        cleanup = subprocess.run(
            [*COMPOSE_COMMAND, "down", "--volumes", "--remove-orphans"],
            cwd=REPOSITORY_ROOT,
            check=False,
            text=True,
        )
        if cleanup.returncode != 0:
            print(
                "No se pudo limpiar automáticamente el stack polls-qa-integration; "
                "ejecuta `docker compose --project-name polls-qa-integration "
                f"-f {REPOSITORY_ROOT / 'compose.qa.yaml'} down --volumes --remove-orphans`.",
                file=sys.stderr,
            )


def wait_for_health(client: httpx.Client, base_url: str, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    last_status = "sin respuesta"
    while time.monotonic() < deadline:
        try:
            response = client.get(f"{base_url}/health")
            last_status = f"HTTP {response.status_code}"
            if response.status_code == 200:
                return
        except httpx.HTTPError as error:
            last_status = str(error)
        time.sleep(1)

    pytest.fail(f"{base_url}/health no estuvo disponible ({last_status}).")


def wait_for_message(
    client: httpx.Client,
    channel_id: str,
    expected_content: str,
    timeout: float = 30,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    url = f"{MESSAGES_URL}/api/v1/channels/{channel_id}/messages"
    while time.monotonic() < deadline:
        response = client.get(url)
        if response.status_code == 200:
            messages = response.json()
            matching = [
                message
                for message in messages
                if expected_content in message.get("content", "")
            ]
            if matching:
                return matching[-1]
        time.sleep(0.5)

    pytest.fail(f"Messages no publicó el contenido esperado: {expected_content!r}.")


def _resolve_schema(openapi: dict, schema: dict) -> dict:
    while "$ref" in schema:
        reference = schema["$ref"]
        prefix = "#/components/schemas/"
        assert reference.startswith(prefix), reference
        schema = openapi["components"]["schemas"][reference.removeprefix(prefix)]
    return schema


def _path_parameters(path_item: dict, operation: dict) -> dict[str, dict]:
    parameters = [*path_item.get("parameters", []), *operation.get("parameters", [])]
    return {(parameter["in"], parameter["name"]): parameter for parameter in parameters}


def test_live_messages_openapi_matches_chat_base_contract() -> None:
    expected = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    with httpx.Client(timeout=10) as client:
        wait_for_health(client, MESSAGES_URL)
        response = client.get(f"{MESSAGES_URL}/openapi.json")
        assert response.status_code == 200, response.text
        actual = response.json()

    route = MESSAGES_CREATE_PATH
    expected_path = expected["paths"][route]
    actual_path = actual["paths"][route]
    expected_operation = expected_path["post"]
    actual_operation = actual_path["post"]

    expected_parameters = _path_parameters(expected_path, expected_operation)
    actual_parameters = _path_parameters(actual_path, actual_operation)
    assert set(actual_parameters) == set(expected_parameters)
    channel_parameter = actual_parameters[("path", "channel_id")]
    assert channel_parameter["required"] is True
    assert channel_parameter["schema"]["type"] == "string"

    assert "201" in actual_operation["responses"]
    expected_request = expected_operation["requestBody"]
    actual_request = actual_operation["requestBody"]
    assert actual_request["required"] == expected_request["required"]
    media_type = "application/json"
    expected_schema = _resolve_schema(
        expected,
        expected_request["content"][media_type]["schema"],
    )
    actual_schema = _resolve_schema(
        actual,
        actual_request["content"][media_type]["schema"],
    )
    assert actual_schema["type"] == expected_schema["type"] == "object"
    assert set(actual_schema["required"]) == set(expected_schema["required"])
    for field in expected_schema["required"]:
        expected_field = expected_schema["properties"][field]
        actual_field = actual_schema["properties"][field]
        assert actual_field["type"] == expected_field["type"] == "string"
        for constraint in ("minLength", "maxLength"):
            if constraint in expected_field:
                assert actual_field[constraint] == expected_field[constraint]


def test_chat_users_channels_messages_and_poll_flow() -> None:
    suffix = uuid4().hex

    with httpx.Client(timeout=10) as client:
        for base_url in (POLLS_URL, USERS_URL, CHANNELS_URL, MESSAGES_URL):
            wait_for_health(client, base_url)

        user_response = client.post(
            f"{USERS_URL}/api/v1/users",
            json={"display_name": f"QA Polls {suffix}"},
        )
        assert user_response.status_code == 201, user_response.text
        author_id = user_response.json()["id"]

        channel_response = client.post(
            f"{CHANNELS_URL}/api/v1/channels",
            json={"name": f"qa-polls-{suffix}"},
        )
        assert channel_response.status_code == 201, channel_response.text
        channel_id = channel_response.json()["id"]

        question = f"Compose QA {suffix}: ¿qué alternativa prefieres?"
        poll_response = client.post(
            f"{POLLS_URL}/api/v1/polls",
            json={
                "channel_id": channel_id,
                "author_id": author_id,
                "question": question,
                "options": ["Opción A", "Opción B"],
                "duration_minutes": 60,
            },
        )
        assert poll_response.status_code == 201, poll_response.text
        poll = poll_response.json()
        assert poll["status"] == "open"

        announcement = wait_for_message(client, channel_id, poll["poll_id"])
        assert announcement["author_id"] == author_id
        assert question in announcement["content"]

        vote_response = client.post(
            f"{POLLS_URL}/api/v1/polls/{poll['poll_id']}/votes",
            json={
                "voter_id": f"qa-voter-{suffix}",
                "option_id": poll["options"][0]["option_id"],
            },
        )
        assert vote_response.status_code == 201, vote_response.text

        close_response = client.post(
            f"{POLLS_URL}/api/v1/polls/{poll['poll_id']}/close",
            json={"author_id": author_id},
        )
        assert close_response.status_code == 200, close_response.text
        assert close_response.json()["status"] == "closed"

        results_message = wait_for_message(
            client,
            channel_id,
            "Total de votos: 1",
        )
        assert question in results_message["content"]
        assert "Opción A: 1 voto(s)" in results_message["content"]
