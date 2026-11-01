from pathlib import Path

import yaml

from app.version import __version__


K8S_ROOT = Path(__file__).resolve().parents[1] / "k8s"
POD_WORKLOADS = {"Deployment", "StatefulSet", "Job"}
EXPECTED_EXTERNAL_SECRETS = {
    "polls-credentials": {
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "RABBITMQ_PASSWORD",
        "RABBITMQ_URL",
    },
    "polls-rabbitmq-consumer-credentials": set(),
}


def load_manifests() -> list[dict]:
    manifests = []
    for path in sorted(K8S_ROOT.rglob("*.yaml")):
        manifests.extend(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    return [manifest for manifest in manifests if manifest]


def test_every_pod_template_meets_restricted_security_contract() -> None:
    workloads = [item for item in load_manifests() if item.get("kind") in POD_WORKLOADS]
    assert {item["metadata"]["name"] for item in workloads} == {
        "polls",
        "rabbitmq",
        "postgres",
        "polls-migration",
        "rabbitmq-consumer-provisioner",
    }

    for workload in workloads:
        pod = workload["spec"]["template"]["spec"]
        pod_security = pod.get("securityContext", {})
        assert pod.get("hostNetwork") is not True, workload["metadata"]["name"]
        assert pod.get("hostPID") is not True, workload["metadata"]["name"]
        assert pod.get("hostIPC") is not True, workload["metadata"]["name"]
        assert not any("hostPath" in volume for volume in pod.get("volumes", []))

        for container in [*pod.get("initContainers", []), *pod["containers"]]:
            security = {**pod_security, **container.get("securityContext", {})}
            label = f"{workload['metadata']['name']}/{container['name']}"
            assert security.get("runAsNonRoot") is True, label
            assert security.get("runAsUser", 1) > 0, label
            assert security.get("allowPrivilegeEscalation") is False, label
            assert security.get("seccompProfile", {}).get("type") in {
                "RuntimeDefault",
                "Localhost",
            }, label
            capabilities = security.get("capabilities", {})
            assert "ALL" in capabilities.get("drop", []), label
            assert set(capabilities.get("add", [])) <= {"NET_BIND_SERVICE"}, label
            assert security.get("privileged") is not True, label
            assert security.get("procMount", "Default") == "Default", label


def test_services_select_workloads_and_target_declared_ports() -> None:
    manifests = load_manifests()
    workloads = [item for item in manifests if item.get("kind") in POD_WORKLOADS]
    services = [item for item in manifests if item.get("kind") == "Service"]
    assert {item["metadata"]["name"] for item in services} == {
        "polls",
        "postgres",
        "rabbitmq",
    }

    for service in services:
        selector = service["spec"]["selector"]
        matching = [
            item
            for item in workloads
            if all(
                item["spec"]["template"]["metadata"]["labels"].get(key) == value
                for key, value in selector.items()
            )
        ]
        assert len(matching) == 1, service["metadata"]["name"]
        pod = matching[0]["spec"]["template"]["spec"]
        container_ports = [
            port
            for container in pod["containers"]
            for port in container.get("ports", [])
        ]
        for service_port in service["spec"]["ports"]:
            target = service_port.get("targetPort", service_port["port"])
            assert any(
                port.get("name") == target or port.get("containerPort") == target
                for port in container_ports
            ), f"{service['metadata']['name']} targetPort={target}"

    postgres = next(item for item in workloads if item["kind"] == "StatefulSet")
    assert postgres["spec"]["serviceName"] == "postgres"
    assert postgres["spec"]["template"]["spec"]["volumes"][-1][
        "persistentVolumeClaim"
    ]["claimName"] == "postgres-data"


def test_configmap_secret_and_application_image_references_are_coherent() -> None:
    manifests = load_manifests()
    configmaps = {
        item["metadata"]["name"]: item
        for item in manifests
        if item.get("kind") == "ConfigMap"
    }
    assert {"polls-config", "rabbitmq-consumers", "rabbitmq-config"} <= set(configmaps)
    versioned_images = []
    referenced_secrets: dict[str, set[str]] = {}

    for workload in (item for item in manifests if item.get("kind") in POD_WORKLOADS):
        pod = workload["spec"]["template"]["spec"]
        for container in [*pod.get("initContainers", []), *pod["containers"]]:
            image = container.get("image", "")
            assert not image.endswith(":latest"), workload["metadata"]["name"]
            if image.startswith("ghcr.io/tomascano-usm/inf326-microservicio-polls:"):
                versioned_images.append(image.rsplit(":", 1)[1])
                assert container.get("imagePullPolicy") == "IfNotPresent"
            for env in container.get("env", []):
                secret_ref = env.get("valueFrom", {}).get("secretKeyRef")
                if secret_ref:
                    referenced_secrets.setdefault(secret_ref["name"], set()).add(
                        secret_ref["key"]
                    )
            for env_from in container.get("envFrom", []):
                config_ref = env_from.get("configMapRef")
                if config_ref:
                    assert config_ref["name"] in configmaps
                secret_ref = env_from.get("secretRef")
                if secret_ref:
                    referenced_secrets.setdefault(secret_ref["name"], set())

        for volume in pod.get("volumes", []):
            config_ref = volume.get("configMap")
            if config_ref:
                assert config_ref["name"] in configmaps

    assert versioned_images == [__version__] * 3
    for name, keys in referenced_secrets.items():
        assert name in EXPECTED_EXTERNAL_SECRETS
        assert keys <= EXPECTED_EXTERNAL_SECRETS[name]
    assert referenced_secrets["polls-credentials"] == {
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "RABBITMQ_PASSWORD",
        "RABBITMQ_URL",
    }


def test_hpa_targets_only_polls_with_requested_cpu_and_versioned_app_images() -> None:
    manifests = load_manifests()
    hpa = next(item for item in manifests if item.get("kind") == "HorizontalPodAutoscaler")
    assert hpa["spec"]["scaleTargetRef"] == {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "name": "polls",
    }
    assert hpa["spec"]["minReplicas"] == 1
    assert hpa["spec"]["maxReplicas"] == 3
    assert hpa["spec"]["metrics"][0]["resource"]["target"]["averageUtilization"] == 70

    polls = next(
        item
        for item in manifests
        if item.get("kind") == "Deployment" and item["metadata"]["name"] == "polls"
    )
    assert polls["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"][
        "cpu"
    ] == "100m"


def test_rabbitmq_probe_rollout_and_memory_configuration_contract() -> None:
    manifests = load_manifests()
    rabbit = next(
        item
        for item in manifests
        if item.get("kind") == "Deployment" and item["metadata"]["name"] == "rabbitmq"
    )
    pod = rabbit["spec"]["template"]["spec"]
    container = pod["containers"][0]
    security = container["securityContext"]

    assert rabbit["spec"]["replicas"] == 1
    assert rabbit["spec"]["strategy"]["type"] == "Recreate"
    assert security["runAsNonRoot"] is True
    assert security["runAsUser"] == 100
    assert security["runAsGroup"] == 101
    assert security["allowPrivilegeEscalation"] is False
    assert security["seccompProfile"]["type"] == "RuntimeDefault"
    assert security["capabilities"]["drop"] == ["ALL"]
    assert not security["capabilities"].get("add")
    assert container["startupProbe"]["tcpSocket"]["port"] == "amqp"
    assert container["startupProbe"]["failureThreshold"] * container["startupProbe"][
        "periodSeconds"
    ] == 180
    assert container["readinessProbe"]["exec"]["command"] == [
        "bash",
        "-ec",
        "</dev/tcp/127.0.0.1/5672 && </dev/tcp/127.0.0.1/15672",
    ]
    assert container["livenessProbe"]["tcpSocket"]["port"] == "amqp"
    assert (
        container["livenessProbe"]["failureThreshold"]
        * container["livenessProbe"]["periodSeconds"]
        == 60
    )
    assert container["resources"]["limits"]["memory"] == "256Mi"
    assert container["volumeMounts"][0]["subPath"] == "rabbitmq.conf"

    rabbit_config = next(
        item
        for item in manifests
        if item.get("kind") == "ConfigMap" and item["metadata"]["name"] == "rabbitmq-config"
    )
    assert rabbit_config["data"]["rabbitmq.conf"].strip() == (
        "vm_memory_high_watermark.absolute = 160MiB"
    )

    migration = next(
        item
        for item in manifests
        if item.get("kind") == "Job" and item["metadata"]["name"] == "polls-migration"
    )
    assert migration["spec"]["activeDeadlineSeconds"] == 300
    assert migration["spec"]["backoffLimit"] == 3
    migration_pod = migration["spec"]["template"]["spec"]
    migration_container = migration_pod["containers"][0]
    assert migration_container["command"] == ["alembic", "upgrade", "head"]
    assert {env["name"] for env in migration_container["env"]} == {"DATABASE_URL"}
    assert not migration_pod.get("initContainers")


def test_compose_rabbitmq_healthcheck_uses_lightweight_listeners() -> None:
    compose = yaml.safe_load((K8S_ROOT.parent / "compose.yaml").read_text(encoding="utf-8"))
    healthcheck = compose["services"]["rabbitmq"]["healthcheck"]
    command = " ".join(healthcheck["test"])
    assert "rabbitmq-diagnostics" not in command
    assert "5672" in command and "15672" in command
    assert healthcheck["timeout"] == "2s"
