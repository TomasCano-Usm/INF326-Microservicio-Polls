# INF326-Microservicio-Polls
Repositorio público para la implementación de un microservicio de encuestas en el contexto de la asignatura inf326, UTFSM 

> **Versión actual: `1.0.0`** · Tag de release: **`v1.0.0`** · API REST: **`/api/v1`**

La versión del servicio también aparece en la metadata OpenAPI de FastAPI (`/openapi.json` y `/docs`). Su fuente única está en `app/version.py`.

## Estado actual

Microservicio REST v1 con FastAPI para crear, responder, cerrar y consultar encuestas. PostgreSQL conserva el estado; `channel_id`, `author_id` y `voter_id` son referencias externas sin llaves foráneas a Users o Channels.

## Requisitos y ejecución

Polls ocupa el puerto `8004` para convivir con Users (`8001`), Channels (`8002`) y Messages (`8003`). Define primero `MESSAGES_BASE_URL` y luego levanta la API, PostgreSQL y RabbitMQ:

```bash
# Si Messages comparte la red Docker y el servicio se llama "messages":
export MESSAGES_BASE_URL=http://messages:8003
# Para Messages ejecutándose en el host, usar en su lugar:
# export MESSAGES_BASE_URL=http://host.docker.internal:8003
docker compose up --build
```

- API: `http://localhost:8004`
- OpenAPI/Swagger: `http://localhost:8004/docs`
- PostgreSQL: `localhost:5432` (base/usuario `polls`, clave de desarrollo `polls-dev-password`)
- RabbitMQ Management: `http://localhost:15672` (usuario `polls`, clave `polls-dev-password`)
- Health check: `GET http://localhost:8004/health`

Si Messages corre en el host mientras Polls está en Docker, configura `MESSAGES_BASE_URL=http://host.docker.internal:8003`. Si usa otro nombre o dirección de red, define la URL base correspondiente; el servicio Messages no forma parte de este Compose y debe ser accesible desde el contenedor Polls. El puerto host de Polls se puede cambiar con `POLLS_PORT`; `POLL_CLOSE_SCAN_INTERVAL_SECONDS` configura la revisión de vencimientos y `POLL_RETRY_BASE_SECONDS` el backoff inicial de reintentos.

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
export MESSAGES_BASE_URL=http://localhost:8003
alembic upgrade head
uvicorn app.main:app --reload --port 8004
```

En Windows, activa el entorno con `.venv\Scripts\activate` y define `DATABASE_URL`, `RABBITMQ_URL` y `MESSAGES_BASE_URL` en la terminal antes de iniciar Uvicorn.

## Contrato REST v1

Todos los cuerpos son JSON. Polls genera un UUID para `poll_id` y para cada `option_id`.

| Método | Ruta | Resultado |
| --- | --- | --- |
| `POST` | `/api/v1/polls` | Crea una encuesta (`201`) o responde `202` mientras se publica el anuncio. |
| `POST` | `/api/v1/polls/{poll_id}/votes` | Registra un voto (`201`). |
| `POST` | `/api/v1/polls/{poll_id}/close` | Cierra la encuesta como su autor (`200`). |
| `GET` | `/api/v1/polls/{poll_id}` | Consulta estado y resultados (`200`). |

### Crear encuesta

`duration_minutes` es opcional: por defecto son 5 minutos. Debe ser un entero entre 1 y 1440; Polls calcula y devuelve `closes_at` desde el instante en que recibe la solicitud. Se requieren de 2 a 10 alternativas no vacías y distintas.

```json
{
  "channel_id": "channel-123",
  "author_id": "user-456",
  "question": "¿Qué alternativa prefieres?",
  "options": ["Alternativa A", "Alternativa B"],
  "duration_minutes": 5
}
```

También puedes enviar el header opcional `Idempotency-Key`. Si se repite con el mismo body y autor, Polls devuelve la misma encuesta sin repetir el anuncio (`200` si ya está activa, `202` si sigue pendiente); si se reutiliza con otro body responde `409`.

La respuesta incluye `poll_id`, `closes_at` y las opciones con sus `option_id`, posición y conteo inicial. Si Messages está temporalmente indisponible, Polls devuelve `202` con estado `pending_announcement`; el anuncio se reintenta y la encuesta se activa al publicarse. Durante ese estado aún no se puede votar. Si el anuncio no llega a publicarse antes del deadline, el estado pasa a `creation_failed`.

### Registrar un voto

```json
{
  "voter_id": "user-789",
  "option_id": "<option_id-devuelto-al-crear>"
}
```

Se permite un voto por usuario en cada encuesta. Un voto repetido o una encuesta cerrada responde `409`; una opción que no pertenece a la encuesta responde `422`.

### Cerrar encuesta

```json
{
  "author_id": "user-456"
}
```

Solo el `author_id` creador puede cerrarla (`403` para otro usuario). Repetir un cierre válido devuelve el estado final sin volver a publicar el evento.

### Consultar encuesta y resultados

`GET /api/v1/polls/{poll_id}` no requiere body. Devuelve `poll_id`, `channel_id`, `author_id`, pregunta, estado, fechas, `total_votes` y cada opción con su identificador, texto y `vote_count`. Los conteos se muestran mientras la encuesta está abierta y cerrada; el estado también puede ser `pending_announcement` o `creation_failed`.

Errores generales: `404` para encuesta inexistente, `409` para voto duplicado, encuesta cerrada o conflicto de idempotencia, `410` si el anuncio pendiente venció, `422` para datos inválidos y `403` si alguien distinto al autor solicita el cierre.

## Eventos RabbitMQ

Polls declara el exchange durable tipo `topic` **`polls.events`** y publica con confirmación del broker desde un outbox PostgreSQL:

| Routing key | Cuándo se publica | Contenido del payload |
| --- | --- | --- |
| `poll.created` | Encuesta creada | Representación inicial de la encuesta y opciones. |
| `poll.vote.cast` | Voto aceptado | `poll_id`, `channel_id`, `voter_id`, `option_id`, `cast_at`. |
| `poll.closed` | Cierre manual o por vencimiento | Encuesta con resultados finales y `reason` (`manual` o `deadline`). |

Todos usan el envelope `{ "event_id", "event_type", "occurred_at", "payload" }`. El `event_id` queda estable durante los reintentos; los consumidores deben enlazar sus colas durables al exchange y deduplicar por dicho ID.

Un worker revisa vencimientos y outbox. El intervalo se configura con `POLL_CLOSE_SCAN_INTERVAL_SECONDS`; el backoff inicial de reintentos con `POLL_RETRY_BASE_SECONDS`.

## Integración REST con Messages

Polls consume de forma síncrona `POST {MESSAGES_BASE_URL}/api/v1/channels/{channel_id}/messages`. `channel_id` está en la URL y el body contiene exclusivamente:

```json
{
  "user_id": "<author_id de la encuesta>",
  "content": "<texto construido por Polls>"
}
```

Polls no consulta Users o Channels: Messages valida esas referencias y conserva los mensajes en su propio almacenamiento. Para anunciar una encuesta, `content` incluye pregunta, `poll_id`, alternativas y fecha/hora de cierre. Al cerrarla manualmente o por vencimiento, publica la pregunta, el conteo final por alternativa y el total de votos.

La creación llama a Messages antes de activar la encuesta. Un rechazo `4xx` cancela la creación y no emite `poll.created`; ante un fallo transitorio se conserva como `pending_announcement` y responde `202`. Si Messages acepta pero RabbitMQ falla, la encuesta queda activa y el outbox reintenta `poll.created` sin volver a publicar el anuncio. Al cerrar, Polls conserva el estado cerrado y el outbox de `poll.closed`; si falla el POST de resultados, se reintenta desde la tabla de entregas.

El timeout de Messages se configura con `MESSAGES_TIMEOUT_SECONDS` (5 segundos por defecto). Los rechazos HTTP `4xx` al crear se devuelven al cliente; fallos de red/`5xx` dejan el anuncio pendiente. Las notificaciones y eventos pendientes sobreviven reinicios. Messages no ofrece idempotencia en el contrato actual, por lo que un timeout ambiguo puede ocasionar un mensaje duplicado al reintentar.

## Persistencia

Alembic aplica las migraciones al iniciar el contenedor. El esquema incluye:

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

Para cada release, actualiza `__version__` en `app/version.py` y la versión actual indicada al inicio de este README. FastAPI toma automáticamente ese valor para OpenAPI. Los tags publicados usan el prefijo `v` seguido de la versión, por ejemplo `v1.1.0`:

```bash
git tag -a v1.1.0 -m "Release v1.1.0"
git push origin v1.1.0
```

Publica también el commit que contiene esa versión en `main`. GitHub mostrará el tag como release seleccionable; `/api/v1` solo cambia al iniciar una nueva versión mayor de la API.

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest
```

Las pruebas usan SQLite temporal, un publicador falso y un cliente Messages falso; no requieren PostgreSQL, RabbitMQ ni el servicio Messages. FastAPI también publica la documentación OpenAPI en `/docs` y `/redoc`.
