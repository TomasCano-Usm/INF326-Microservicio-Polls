# Despliegue de Polls en Kubernetes

## Arquitectura

El namespace de la actividad es `grupo-encuestas`. Los manifests omiten `metadata.namespace`; los comandos de esta guía seleccionan el namespace explícitamente.

```text
Cliente --port-forward/ClusterIP--> Polls (1–3 Pods)
                                      |-- PostgreSQL (StatefulSet, PVC 1 GiB)
                                      |-- RabbitMQ (Deployment, efímero)
                                      `-- Messages del core (REST)
                                          http://messages.servicios-base.svc.cluster.local:8000
```

Solo se despliegan Polls, PostgreSQL y RabbitMQ. Users, Channels y Messages pertenecen al core del curso; Polls no consulta directamente Users ni Channels. Messages valida las referencias externas `author_id` y `channel_id`.

Los recursos están organizados en `k8s/polls/`, `k8s/postgres/`, `k8s/rabbitmq/` y `k8s/jobs/`. No hay Ingress, NodePort ni LoadBalancer.

## Health checks y dependencias

- `/health` se conserva para compatibilidad.
- `/health/live` solo indica que FastAPI está respondiendo; no consulta dependencias.
- `/health/ready` ejecuta `SELECT 1` en PostgreSQL. Si falla, responde `503` y Kubernetes deja de enviar tráfico al Pod.
- RabbitMQ y Messages no afectan readiness. PostgreSQL es la dependencia crítica para procesar solicitudes.

El publicador RabbitMQ conecta de manera lazy al intentar publicar. Si el broker no está disponible, el evento permanece en `outbox_events` y se reintenta con el backoff existente. Las publicaciones usan exchange durable, mensajes persistentes y publisher confirms.

El outbox ofrece entrega *at-least-once*, no exactly-once. Una caída después de la confirmación del broker y antes de guardar `published_at` puede repetir un evento; el `event_id` estable permite deduplicación por consumidores.

RabbitMQ no utiliza PVC: la única reclamación de almacenamiento permitida se reserva para PostgreSQL. El exchange y los mensajes se declaran durables/persistentes, pero el almacenamiento efímero del broker significa que una recreación del Pod puede perder colas y mensajes ya confirmados. El outbox no vuelve a publicar eventos que ya marcó como confirmados. Por lo tanto, esta instalación académica no ofrece recuperación de eventos ante pérdida de datos de RabbitMQ; consumidores y evidencia deben considerar esa limitación.

Messages tampoco ofrece idempotencia en su contrato HTTP. Un POST aceptado remotamente cuya respuesta se pierde, o una caída del Pod antes de guardar el resultado, puede ocasionar mensajes duplicados. El token de lease de `message_deliveries` impide que un intento antiguo sobrescriba el estado de un claim posterior, pero no elimina esa ambigüedad externa.

## Persistencia y concurrencia

PostgreSQL corre como un StatefulSet de una réplica con el único PVC del namespace: `postgres-data`, `ReadWriteOnce`, `1Gi`. Se omite `storageClassName` para utilizar la clase por defecto `do-block-storage`. El Service interno `postgres` proporciona el DNS que utilizan Polls y el Job de migración.

RabbitMQ corre como un Deployment de una réplica y un Service `ClusterIP` llamado `rabbitmq`; utiliza `rabbitmq:5672` dentro del namespace y no tiene PVC ni clustering.

Cada Pod de Polls conserva sus workers de cierre, outbox y entregas. La concurrencia se coordina en PostgreSQL: locks de fila para votos/cierres, constraints e idempotencia existente, claims atómicos y leases. `message_deliveries.lease_token` funciona como fencing al finalizar cada intento. No se requiere un líder único ni un servicio adicional.

## Migraciones

El comando del contenedor es Uvicorn y no ejecuta Alembic. Compose ejecuta un servicio one-shot `migrate`; Kubernetes usa `k8s/jobs/migration.yaml`, con `parallelism: 1` y `completions: 1`. La migración se debe completar antes de aplicar/actualizar el Deployment de Polls. No se agregó advisory lock porque el flujo mantiene un solo Job activo y no hay migraciones concurrentes por réplica.

Para una nueva migración:

1. Publica la imagen de la nueva release y actualiza el tag concreto en `k8s/jobs/migration.yaml` y `k8s/polls/deployment.yaml`.
2. Ejecuta `kubectl -n "$NAMESPACE" delete job polls-migration`.
3. Aplica otra vez el Job y espera su finalización.
4. Actualiza/aplica el Deployment de Polls.

El borrado del Job no borra datos de PostgreSQL ni el PVC.

## Configuración y secretos

`k8s/polls/configmap.yaml` configura Messages con:

```text
MESSAGES_ENABLED=true
MESSAGES_BASE_URL=http://messages.servicios-base.svc.cluster.local:8000
```

También configura el exchange y los intervalos de worker/reintentos. `DATABASE_URL`, `RABBITMQ_URL`, `POSTGRES_PASSWORD` y `RABBITMQ_PASSWORD` se leen del Secret externo `polls-credentials`. No hay manifest de Secret ni credenciales reales en Git. Las contraseñas generadas con hex son seguras para interpolarse en las URLs.

En el computador local, genera credenciales y crea el Secret en el namespace asignado. Este ejemplo solo se documenta; no se ejecutó:

```bash
export NAMESPACE=grupo-encuestas
export POLLS_DB_PASSWORD="$(openssl rand -hex 24)"
export POLLS_RABBIT_PASSWORD="$(openssl rand -hex 24)"

kubectl -n "$NAMESPACE" create secret generic polls-credentials \
  --from-literal=POSTGRES_PASSWORD="$POLLS_DB_PASSWORD" \
  --from-literal=RABBITMQ_PASSWORD="$POLLS_RABBIT_PASSWORD" \
  --from-literal=DATABASE_URL="postgresql+asyncpg://polls:${POLLS_DB_PASSWORD}@postgres:5432/polls" \
  --from-literal=RABBITMQ_URL="amqp://polls:${POLLS_RABBIT_PASSWORD}@rabbitmq:5672/"

unset POLLS_DB_PASSWORD POLLS_RABBIT_PASSWORD
```

Si el paquete GHCR permanece privado, el namespace necesitará un `imagePullSecret` creado según las instrucciones del curso. No se incluyen tokens ni credenciales para ello. Si se hace público el paquete, los Pods podrán descargarlo sin ese Secret.

## Recursos y cuotas

Los límites/request por Pod son:

| Componente | Requests CPU / memoria | Limits CPU / memoria |
| --- | --- | --- |
| Polls | `100m` / `128Mi` | `250m` / `256Mi` |
| PostgreSQL | `100m` / `256Mi` | `250m` / `512Mi` |
| RabbitMQ | `100m` / `128Mi` | `250m` / `256Mi` |
| Job de migración | `50m` / `64Mi` | `100m` / `128Mi` |

Cálculo para los recursos configurados:

| Escenario | Requests CPU / memoria | Limits CPU / memoria |
| --- | --- | --- |
| 1 Polls + PostgreSQL + RabbitMQ | `300m` / `512Mi` | `750m` / `1024Mi` |
| 3 Polls + PostgreSQL + RabbitMQ | `500m` / `768Mi` | `1250m` / `1536Mi` |
| 3 Polls + PostgreSQL + RabbitMQ + Job | `550m` / `832Mi` | `1350m` / `1664Mi` |

El Job cabe incluso cuando el HPA está en tres réplicas. Se ejecuta antes de actualizar el Deployment, por lo que no coincide con el Pod temporal `maxSurge: 1` del rollout. Si se solaparan además ese surge y el Job, el total máximo sería `650m`/`960Mi` en requests y `1600m`/`1920Mi` en limits, todavía dentro de la cuota. El PVC consume exactamente `1Gi`; no se crean otros PVC. Los conteos máximos son seis Pods durante el Job (siete incluyendo el surge), dos Deployments, un StatefulSet, un HPA, tres Services y un PVC; cumplen las cuotas informadas.

El HPA usa `autoscaling/v2`, CPU promedio al `70%`, `minReplicas: 1` y `maxReplicas: 3`. Metrics Server está disponible en el clúster. Las cuotas informadas permiten estos valores; si cambian, requests/limits y máximo de réplicas están declarados en los manifests para ajustarse de forma explícita.

## CI y GHCR

- `.github/workflows/ci.yml` ejecuta pytest en pushes a `main` y pull requests.
- `.github/workflows/publish-image.yml` prueba antes de construir/publicar en pushes a `main` y tags `vMAJOR.MINOR.PATCH`. Para tags valida que coincidan con `app/version.py`.
- Las imágenes de release reciben `v1.2.0`, `1.2.0` y `latest`; los pushes a `main` reciben tags `main` y `sha-<commit>`.
- Registry: `ghcr.io/tomas-cano-usm/inf326-microservicio-polls`.
- Publica con `GITHUB_TOKEN` y permisos `contents: read`, `packages: write`. El workflow de release SemVer existente se conserva.

El tag concreto de imagen de los manifests es `1.2.0`; GHCR lo publicará al crear el tag SemVer `v1.2.0`. Antes de desplegar se debe confirmar que esa imagen está publicada. Para una release posterior, actualiza ambos manifests a su versión publicada. El paquete GHCR puede requerir hacerse público o configurar `imagePullSecret`. No hay CD, Argo CD ni GitOps.

## Procedimiento de despliegue futuro

Revisa y confirma primero el tag GHCR y que el Secret exista. No apliques todo el directorio en un único paso: las migraciones deben terminar antes de iniciar la versión nueva de Polls.

```bash
export NAMESPACE=grupo-encuestas

kubectl -n "$NAMESPACE" apply -f k8s/postgres/service.yaml
kubectl -n "$NAMESPACE" apply -f k8s/postgres/pvc.yaml
kubectl -n "$NAMESPACE" apply -f k8s/postgres/statefulset.yaml
kubectl -n "$NAMESPACE" apply -f k8s/rabbitmq/service.yaml
kubectl -n "$NAMESPACE" apply -f k8s/rabbitmq/deployment.yaml
kubectl -n "$NAMESPACE" wait --for=condition=Ready pod -l app=postgres --timeout=180s
kubectl -n "$NAMESPACE" rollout status statefulset/postgres --timeout=180s
kubectl -n "$NAMESPACE" rollout status deployment/rabbitmq --timeout=180s

kubectl -n "$NAMESPACE" apply -f k8s/jobs/migration.yaml
kubectl -n "$NAMESPACE" wait --for=condition=complete job/polls-migration --timeout=180s

kubectl -n "$NAMESPACE" apply -f k8s/polls/configmap.yaml
kubectl -n "$NAMESPACE" apply -f k8s/polls/service.yaml
kubectl -n "$NAMESPACE" apply -f k8s/polls/deployment.yaml
kubectl -n "$NAMESPACE" apply -f k8s/polls/hpa.yaml
kubectl -n "$NAMESPACE" rollout status deployment/polls --timeout=180s
```

Inspección y evidencia:

```bash
kubectl -n "$NAMESPACE" get pods,deployments,statefulsets,services,hpa,pvc
kubectl -n "$NAMESPACE" get resourcequota,limitrange
kubectl -n "$NAMESPACE" top pods
kubectl -n "$NAMESPACE" get hpa -w
kubectl -n "$NAMESPACE" logs deployment/polls
kubectl -n "$NAMESPACE" describe hpa polls
kubectl -n "$NAMESPACE" port-forward service/polls 8004:8004
```

Con el port-forward activo, Swagger queda en `http://localhost:8004/docs`. Para la evidencia integrada, crea una encuesta usando IDs existentes de Users/Channels, verifica el mensaje de anuncio en el chat, emite votos, cierra la encuesta y verifica el mensaje de resultados. Para escalamiento, captura `get hpa`, `get pods` y `top pods` bajo carga y después del scale-down. Estos comandos son pasos futuros: no se ejecutaron durante la preparación.
