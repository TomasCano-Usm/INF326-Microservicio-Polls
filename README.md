# INF326-Microservicio-Polls
Repositorio público para la implementación de un microservicio de encuestas en el contexto de la asignatura inf326, UTFSM

> **Versión del código: `1.3.5`** · Próximo tag SemVer: **`v1.3.5`** · API REST: **`/api/v1`**

La versión del servicio también aparece en la metadata OpenAPI de FastAPI (`/openapi.json` y `/docs`). Su fuente única está en `app/version.py`.

> **Credenciales de desarrollo:** las credenciales incluidas en Docker Compose son ficticias y exclusivamente para desarrollo local. No las reutilices en staging ni en despliegues reales. Los secretos reales deben suministrarse mediante variables de entorno o un gestor de secretos y nunca deben commitearse.

## Estado actual

Microservicio REST v1 con FastAPI para crear, responder, cerrar y consultar encuestas. PostgreSQL conserva el estado; `channel_id`, `author_id` y `voter_id` son referencias externas sin llaves foráneas a Users o Channels.

## Requisitos y ejecución

Polls ocupa el puerto `8004` para convivir con Users (`8001`), Channels (`8002`) y Messages (`8003`). Compose deshabilita Messages por defecto, así que el entorno local puede levantarse directamente sin configurar su URL:

```bash
docker compose up --build
```

Para habilitar la integración cuando Messages esté disponible, define ambos valores. Si comparte la red Docker y el servicio se llama `messages`:

```bash
MESSAGES_ENABLED=true MESSAGES_BASE_URL=http://messages:8003 docker compose up --build
```

Si Messages corre en el host, usa `MESSAGES_BASE_URL=http://host.docker.internal:8003`.

- API: `http://localhost:8004`
- OpenAPI/Swagger: `http://localhost:8004/docs`
- PostgreSQL: `localhost:5432` (base/usuario `polls`, clave de desarrollo `polls-dev-password`)
- RabbitMQ Management: `http://localhost:15672` (usuario `polls`, clave `polls-dev-password`)
- Health checks: `/health`, `/health/live` y `/health/ready` en `http://localhost:8004`

Cuando `MESSAGES_ENABLED=false`, Polls omite y registra los anuncios/resultados, sin hacer requests HTTP; las encuestas, votos, cierres y eventos siguen funcionando. Para Messages fuera de este Compose, la URL indicada debe ser accesible desde el contenedor Polls. El puerto host de Polls se puede cambiar con `POLLS_PORT`; `POLL_CLOSE_SCAN_INTERVAL_SECONDS` configura la revisión de vencimientos y `POLL_RETRY_BASE_SECONDS` el backoff inicial de reintentos.

Detén los servicios con `docker compose down`.

Para ejecutar la API fuera de Docker, se requiere Python 3.12 o superior. Primero levanta PostgreSQL y RabbitMQ:

```bash
docker compose up -d postgres rabbitmq
```

Luego instala dependencias, aplica migraciones y ejecuta:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://polls:polls-dev-password@localhost:5432/polls
export RABBITMQ_URL=amqp://polls:polls-dev-password@localhost:5672/
export MESSAGES_ENABLED=false
alembic upgrade head
uvicorn app.main:app --reload --port 8004
```

La aplicación fuera de Compose habilita Messages por defecto para conservar el comportamiento de despliegues existentes. Si defines `MESSAGES_ENABLED=true`, también debes definir `MESSAGES_BASE_URL`; si la integración está deshabilitada, no se requiere la URL. Solo se aceptan los valores `true` y `false`.

En Windows, activa el entorno con `.venv\Scripts\activate` y define `DATABASE_URL`, `RABBITMQ_URL` y `MESSAGES_ENABLED` en la terminal antes de iniciar Uvicorn.

## API REST

| Método | Ruta | Propósito |
| --- | --- | --- |
| `GET` | `/health` | Comprueba disponibilidad. |
| `GET` | `/health/live` | Comprueba que el proceso responde. |
| `GET` | `/health/ready` | Comprueba conectividad con PostgreSQL. |
| `POST` | `/api/v1/polls` | Crea una encuesta. |
| `POST` | `/api/v1/polls/{poll_id}/votes` | Registra un voto. |
| `POST` | `/api/v1/polls/{poll_id}/close` | Cierra una encuesta. |
| `GET` | `/api/v1/polls/{poll_id}` | Consulta una encuesta y sus resultados. |

La referencia de parámetros, cuerpos y ejemplos está en [`docs/api.md`](docs/api.md). La documentación interactiva está disponible en `/docs` y `/redoc`.

Los diagramas de arquitectura y flujo del servicio están descritos en [`docs/diagramas.md`](docs/diagramas.md).

## Gateway GraphQL para la interfaz

El gateway backend para la futura interfaz está en [`gateway/`](gateway/) y su configuración, consultas, mutaciones, pruebas con mocks y guía de despliegue están en [`docs/gateway.md`](docs/gateway.md). Se ejecuta como componente independiente y no cambia los endpoints REST de Polls.

## Kubernetes (Unidad 05)

Los manifests, límites de recursos, migración mediante Job, integración con Messages del core y comandos futuros de despliegue están documentados en [`docs/kubernetes.md`](docs/kubernetes.md). Polls se configura con `MESSAGES_ENABLED=true` y usa `http://messages.servicios-base.svc.cluster.local:8000`; no se despliegan Users, Channels ni Messages. Kubernetes utiliza PostgreSQL persistente (un PVC de 1 GiB), RabbitMQ efímero, readiness/liveness y HPA de 1 a 3 Pods. No hay CD al clúster.

## Eventos RabbitMQ

Polls declara el exchange durable tipo `topic` **`polls.events`** y publica con confirmación del broker desde un outbox PostgreSQL:

| Routing key | Cuándo se publica | Contenido del payload |
| --- | --- | --- |
| `poll.created` | Encuesta creada | Representación inicial de la encuesta y opciones. |
| `poll.vote.cast` | Voto aceptado | `poll_id`, `channel_id`, `voter_id`, `option_id`, `cast_at`. |
| `poll.closed` | Cierre manual o por vencimiento | Encuesta con resultados finales y `reason` (`manual` o `deadline`). |

Todos usan el envelope `{ "event_id", "event_type", "occurred_at", "payload" }`. El `event_id` queda estable durante los reintentos; cada integración consume la queue durable que le provisiona la infraestructura y debe deduplicar por dicho ID.

Un worker revisa vencimientos y outbox. El intervalo se configura con `POLL_CLOSE_SCAN_INTERVAL_SECONDS`; el backoff inicial de reintentos con `POLL_RETRY_BASE_SECONDS`.

Los eventos pueden consumirse opcionalmente mediante RabbitMQ con una queue y un usuario independientes por integración. El provisioning, los permisos mínimos y el procedimiento después de reiniciar el broker están en [`docs/rabbitmq-consumers.md`](docs/rabbitmq-consumers.md).

## Integración REST con Messages

Polls consume de forma síncrona `POST {MESSAGES_BASE_URL}/api/v1/channels/{channel_id}/messages`. `channel_id` está en la URL y el body contiene exclusivamente:

```json
{
  "author_id": "<author_id de la encuesta>",
  "content": "<texto construido por Polls>"
}
```

Polls no consulta Users o Channels: Messages valida esas referencias y conserva los mensajes en su propio almacenamiento. Para anunciar una encuesta, `content` incluye pregunta, `poll_id`, alternativas y fecha/hora de cierre. Al cerrarla manualmente o por vencimiento, publica la pregunta, el conteo final por alternativa y el total de votos.

La creación llama a Messages antes de activar la encuesta. Un rechazo `4xx` cancela la creación y no emite `poll.created`; ante un fallo transitorio se conserva como `pending_announcement` y responde `202`. Si Messages acepta pero RabbitMQ falla, la encuesta queda activa y el outbox reintenta `poll.created` sin volver a publicar el anuncio. Al cerrar, Polls conserva el estado cerrado y el outbox de `poll.closed`; si falla el POST de resultados, se reintenta desde la tabla de entregas.

El timeout de Messages se configura con `MESSAGES_TIMEOUT_SECONDS` (5 segundos por defecto). Los rechazos HTTP `4xx` al crear se devuelven al cliente; fallos de red/`5xx` dejan el anuncio pendiente. Las notificaciones y eventos pendientes sobreviven reinicios. Messages no ofrece idempotencia en el contrato actual, por lo que un timeout ambiguo puede ocasionar un mensaje duplicado al reintentar. Cuando la integración está deshabilitada, las entregas se registran como `skipped`.

## Persistencia

Compose aplica migraciones mediante un servicio one-shot antes de iniciar la API. En Kubernetes se ejecutan explícitamente con `k8s/jobs/migration.yaml`; el Deployment de Polls inicia Uvicorn directamente. El esquema incluye:

- `polls`: ciclo de vida, IDs externos, duración, fechas y clave de idempotencia.
- `poll_options`: alternativas ordenadas y únicas por texto normalizado dentro de cada encuesta.
- `votes`: clave primaria `(poll_id, voter_id)` y FK compuesta que garantiza que la opción pertenezca a esa encuesta.
- `message_deliveries`: estado y reintentos de `announcement` y `final_results`.
- `outbox_events`: eventos RabbitMQ insertados en la misma transacción que el cambio de estado.

Las operaciones de voto y cierre bloquean la fila de la encuesta durante la transacción. Esto serializa el cierre con los votos concurrentes y aplica el límite temporal en la base de datos.

## Versionado y releases

Polls usa versionado semántico **`MAJOR.MINOR.PATCH`**:

- **MAJOR:** cambios incompatibles en los contratos REST o de eventos. Un cambio mayor de API usa un nuevo prefijo (por ejemplo, `/api/v2`); `/api/v1` identifica la línea mayor `1`.
- **MINOR:** funcionalidad nueva compatible. Mantiene el prefijo REST existente.
- **PATCH:** correcciones compatibles sin cambios de contrato.

Para cada release, actualiza `__version__` en `app/version.py` y la versión indicada al inicio de este README. FastAPI toma automáticamente ese valor para OpenAPI. Los tags publicados usan el prefijo `v` seguido de la versión, por ejemplo `v1.3.5`:

```bash
git tag -a v1.3.5 -m "Release v1.3.5"
git push origin v1.3.5
```

Publica primero el commit de la versión en `main`. Al hacer push del tag, el workflow `.github/workflows/release.yml` valida que coincida exactamente con `app/version.py` y crea un GitHub Release con el mismo nombre y notas autogeneradas. El workflow `.github/workflows/publish-image.yml` prueba y publica la imagen a GHCR con tags `vMAJOR.MINOR.PATCH` y `MAJOR.MINOR.PATCH`; `latest` sigue la release. Ejecutar manualmente `Publish GitHub Release` solo crea la GitHub Release y no publica la imagen. La imagen se publica mediante el push del tag. Usa `GITHUB_TOKEN` con permisos mínimos. Si ya existe el release, el workflow no crea un duplicado. El contrato `/api/v1` solo cambia al iniciar una nueva versión mayor de la API.

Para crear manualmente solo la GitHub Release de un tag existente, se puede ejecutar `Publish GitHub Release` desde Actions indicando el tag. Esto no publica la imagen en GHCR. Por ejemplo:

```bash
gh workflow run release.yml --ref main -f tag=v1.3.5
```

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest
```

Las pruebas usan SQLite temporal, un publicador falso y un cliente Messages falso; no requieren PostgreSQL, RabbitMQ ni el servicio Messages. FastAPI también publica la documentación OpenAPI en `/docs` y `/redoc`.

La suite opcional [`tests/test_postgres_concurrency.py`](tests/test_postgres_concurrency.py) usa PostgreSQL real para verificar locks de fila con votos concurrentes y la competencia entre cierre manual y automático. Sin `POLLS_TEST_DATABASE_URL`, esos tests se omiten. Levanta PostgreSQL (por ejemplo, `docker compose up -d postgres`), configura esa variable con la URL de una base de pruebas donde el usuario pueda crear schemas y ejecuta:

```bash
export POLLS_TEST_DATABASE_URL='postgresql+asyncpg://<usuario>:<clave>@localhost:5432/<base_de_pruebas>'
pytest tests/test_postgres_concurrency.py -q
```

Cada test crea y elimina su schema aislado; utiliza una base de pruebas, no una base de producción.

## Declaración de uso de inteligencia artificial

Durante el desarrollo de este proyecto se utilizaron principalmente modelos de OpenAI, específicamente GPT-6.1 Sol y GPT-6 Luna, como apoyo transversal en la implementación, resolución de problemas y elaboración de documentación.

La responsabilidad sobre el contenido entregado y las decisiones técnicas adoptadas corresponde a los autores del proyecto.
