# INF326-Microservicio-Polls
Repositorio público para la implementación de un microservicio de encuestas en el contexto de la asignatura inf326, UTFSM 

> **Versión actual: `1.2.0`** · Tag de release: **`v1.2.0`** · API REST: **`/api/v1`**

La versión del servicio también aparece en la metadata OpenAPI de FastAPI (`/openapi.json` y `/docs`). Su fuente única está en `app/version.py`.

> **Credenciales de desarrollo:** las credenciales incluidas en Docker Compose son ficticias y exclusivamente para desarrollo local. No las reutilices en staging ni en despliegues reales. Los secretos reales deben suministrarse mediante variables de entorno o un gestor de secretos y nunca deben commitearse.

## Estado actual

Microservicio REST v1 con FastAPI para crear, responder, cerrar, consultar y listar encuestas. PostgreSQL conserva el estado; `channel_id`, `author_id` y `voter_id` son referencias externas validadas opcionalmente contra Users/Channels. Incluye validación de referencias por id (canal al crear, autor al crear, votante al votar) controlada por `REFERENCES_ENABLED` (deshabilitada por defecto para ejecución standalone).

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
- Health check: `GET http://localhost:8004/health`

Cuando `MESSAGES_ENABLED=false`, Polls omite y registra los anuncios/resultados, sin hacer requests HTTP; las encuestas, votos, cierres y eventos siguen funcionando. Para Messages fuera de este Compose, la URL indicada debe ser accesible desde el contenedor Polls. El puerto host de Polls se puede cambiar con `POLLS_PORT`; `POLL_CLOSE_SCAN_INTERVAL_SECONDS` configura la revisión de vencimientos y `POLL_RETRY_BASE_SECONDS` el backoff inicial de reintentos.

Para habilitar la validación de referencias contra Users/Channels (integración con el chat base):

```bash
REFERENCES_ENABLED=true USERS_BASE_URL=http://users:8000 CHANNELS_BASE_URL=http://channels:8000 docker compose up --build
```

Cuando `REFERENCES_ENABLED=false` (default), el servicio valida solo integridad interna y corre standalone.

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
export REFERENCES_ENABLED=false
alembic upgrade head
uvicorn app.main:app --reload --port 8004
```

La aplicación fuera de Compose habilita Messages por defecto para conservar el comportamiento de despliegues existentes. Si defines `MESSAGES_ENABLED=true`, también debes definir `MESSAGES_BASE_URL`; si la integración está deshabilitada, no se requiere la URL. Solo se aceptan los valores `true` y `false`.

Para validación de referencias fuera de Docker, define `REFERENCES_ENABLED=true` junto con `USERS_BASE_URL` y `CHANNELS_BASE_URL`.

En Windows, activa el entorno con `.venv\Scripts\activate` y define `DATABASE_URL`, `RABBITMQ_URL` y `MESSAGES_ENABLED` en la terminal antes de iniciar Uvicorn.

## Contrato REST v1

Todos los cuerpos son JSON. Polls genera un UUID para `poll_id` y para cada `option_id`.

| Método | Ruta | Resultado |
| --- | --- | --- |
| `POST` | `/api/v1/polls` | Crea una encuesta (`201`) o responde `202` mientras se publica el anuncio. |
| `POST` | `/api/v1/polls/{poll_id}/votes` | Registra un voto (`201`). |
| `POST` | `/api/v1/polls/{poll_id}/close` | Cierra la encuesta como su autor (`200`). |
| `GET` | `/api/v1/polls/{poll_id}` | Consulta estado y resultados (`200`). |
| `GET` | `/api/v1/polls?channel_id=` | Lista encuestas de un canal con paginación (`200`). |

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

### Listar encuestas por canal

`GET /api/v1/polls?channel_id=` devuelve un objeto con campo `polls` que contiene un array de resúmenes de encuesta (sin opciones). Parámetros de query:
- `channel_id` (obligatorio): filtra por canal.
- `limit` (opcional, default 50, máx 100): máximo de resultados.
- `offset` (opcional, default 0): paginación.

Ejemplo de respuesta:
```json
{
  "polls": [
    {
      "poll_id": "...",
      "channel_id": "channel-123",
      "author_id": "user-456",
      "question": "¿Qué alternativa prefieres?",
      "status": "open",
      "duration_minutes": 5,
      "closes_at": "2026-01-15T10:00:00Z",
      "created_at": "2026-01-15T09:55:00Z",
      "closed_at": null,
      "total_votes": 0
    }
  ]
}
```

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
  "author_id": "<author_id de la encuesta>",
  "content": "<texto construido por Polls>"
}
```

Polls no consulta Users o Channels por defecto; la validación de referencias se habilita con `REFERENCES_ENABLED=true` (ver abajo). Messages valida esas referencias y conserva los mensajes en su propio almacenamiento. Para anunciar una encuesta, `content` incluye pregunta, `poll_id`, alternativas y fecha/hora de cierre. Al cerrarla manualmente o por vencimiento, publica la pregunta, el conteo final por alternativa y el total de votos.

La creación llama a Messages antes de activar la encuesta. Un rechazo `4xx` cancela la creación y no emite `poll.created`; ante un fallo transitorio se conserva como `pending_announcement` y responde `202`. Si Messages acepta pero RabbitMQ falla, la encuesta queda activa y el outbox reintenta `poll.created` sin volver a publicar el anuncio. Al cerrar, Polls conserva el estado cerrado y el outbox de `poll.closed`; si falla el POST de resultados, se reintenta desde la tabla de entregas.

El timeout de Messages se configura con `MESSAGES_TIMEOUT_SECONDS` (5 segundos por defecto). Los rechazos HTTP `4xx` al crear se devuelven al cliente; fallos de red/`5xx` dejan el anuncio pendiente. Las notificaciones y eventos pendientes sobreviven reinicios. Messages no ofrece idempotencia en el contrato actual, por lo que un timeout ambiguo puede ocasionar un mensaje duplicado al reintentar. Cuando la integración está deshabilitada, las entregas se registran como `skipped`.

## Validación de referencias (Users/Channels)

Polls puede validar la existencia de canal, autor y votante contra los servicios del chat base antes de crear o votar. Se habilita con `REFERENCES_ENABLED=true` (requiere `USERS_BASE_URL` y `CHANNELS_BASE_URL`). Por defecto está deshabilitada (`false`) para que el servicio corra standalone.

Cuando está habilitada:
- **Crear encuesta**: valida `channel_id` y `author_id` (`GET /api/v1/channels/{id}`, `GET /api/v1/users/{id}`).
- **Votar**: valida `voter_id` (`GET /api/v1/users/{id}`).

Errores:
- Referencia no encontrada (404 del servicio base) → `422 Unprocessable Content`.
- Servicio base no disponible (timeout/red) → `503 Service Unavailable`.

Variables de entorno:
| Variable | Default | Descripción |
| --- | --- | --- |
| `REFERENCES_ENABLED` | `false` | `true`/`false` |
| `USERS_BASE_URL` | *(requerido si enabled)* | Base URL del servicio Users (ej. `http://users:8000`) |
| `CHANNELS_BASE_URL` | *(requerido si enabled)* | Base URL del servicio Channels (ej. `http://channels:8000`) |
| `REFERENCES_TIMEOUT_SECONDS` | `5` | Timeout para validaciones |

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

Publica primero el commit de la versión en `main`. Al subir el tag, el workflow `.github/workflows/release.yml` valida que coincida exactamente con `app/version.py` y crea un GitHub Release con el mismo nombre y notas autogeneradas. Usa exclusivamente el `GITHUB_TOKEN` de Actions, con permiso `contents: write`; si ya existe el release, no crea un duplicado. El contrato `/api/v1` solo cambia al iniciar una nueva versión mayor de la API.

Para publicar un tag anterior que ya existía antes del workflow, se puede ejecutar manualmente en Actions `Publish GitHub Release` indicando el tag. Por ejemplo, el release inicial de la versión actual se puede crear con:

```bash
gh workflow run release.yml --ref main -f tag=v1.1.0
```

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest
```

Las pruebas usan SQLite temporal, un publicador falso y un cliente Messages falso; no requieren PostgreSQL, RabbitMQ ni el servicio Messages. FastAPI también publica la documentación OpenAPI en `/docs` y `/redoc`.
