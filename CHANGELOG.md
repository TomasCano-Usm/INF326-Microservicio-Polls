# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-10-16

### Added
- **Validación de referencias por id** (retro del profe): nuevos clientes HTTP en `app/clients.py` para validar `channel_id`, `author_id` (al crear encuesta) y `voter_id` (al votar) contra los servicios Users/Channels del chat base.
  - Variable `REFERENCES_ENABLED` (default `false`) para ejecutar standalone sin la base.
  - Variables `USERS_BASE_URL`, `CHANNELS_BASE_URL`, `REFERENCES_TIMEOUT_SECONDS`.
  - Errores: `422` si la referencia no existe, `503` si el servicio base no responde.
  - Tests: `test_create_poll_rejects_unknown_channel`, `test_create_poll_rejects_unknown_author`, `test_create_poll_rejects_when_channels_service_unavailable`, `test_create_poll_rejects_when_users_service_unavailable`, `test_vote_rejects_unknown_voter`, `test_vote_rejects_when_users_service_unavailable`, `test_references_disabled_skips_validation`.

- **Nuevo endpoint `GET /api/v1/polls?channel_id=`**: lista encuestas de un canal con paginación (`limit` 1–100, default 50; `offset` ≥ 0). Respuesta sin opciones (resumen liviano). Tests: `test_list_polls_by_channel`, `test_list_polls_with_limit_and_offset`, `test_list_polls_requires_channel_id`, `test_list_polls_validates_limit_bounds`.

- **Corrección contrato Messages**: el body enviado a Messages ahora usa `author_id` (no `user_id`), alineado con el chat base del curso (`{"author_id", "content"}`). Actualizado `app/messages.py`, `tests/test_messages_client.py`, fakes en `tests/test_polls_api.py`.

- **Modelos nuevos en `app/models.py`**: `PollSummary` y `PollListResponse` para el listado.

- **Import `PollSummary` en `app/service.py`** para tipado en `list_polls`.

### Changed
- `app/service.PollService` recibe `ReferenceClient` en constructor; validaciones se ejecutan solo si `enabled`.
- `app/main.create_app` añade `reference_client_factory` param.
- Bump versión a **1.2.0** en `app/version.py` y README.
- README actualizado: estado actual, contrato REST (nueva fila), validación de referencias, integración Messages (campo `author_id`), variables de entorno, ejecución con/sin Docker.

### Tests
- 31 tests pasan (16 originales + 15 nuevos).
- Cobertura: validación referencias (éxito, 422, 503, disabled), listado por canal (orden, paginación, validación params), cliente referencias HTTP/Disabled, contrato Messages con `author_id`.

### Fixed
- Nombre de parámetro en llamada interna a Messages: `author_id` en lugar de `user_id` (ya corregido en iteraciones previas de la 1.1.x pero no documentado).

---

## [1.1.0] - 2026-XX-XX

### Added
- API REST v1 completa: crear encuesta, votar, cerrar (manual/automático), consultar.
- Eventos RabbitMQ con outbox: `poll.created`, `poll.vote.cast`, `poll.closed` (envelope con `event_id` estable).
- Integración con Messages (anuncio y resultados) con reintentos, `202 pending_announcement`, `creation_failed`.
- Idempotencia en creación (`Idempotency-Key`).
- Cierre automático por vencimiento (worker periódico).
- Versionado SemVer + workflow de release (GitHub Actions).
- Tests aislados (SQLite + fakes), 16 tests.
- Docker/Compose, Alembic, OpenAPI.

---

## [1.0.0] - 2026-XX-XX

### Added
- Versión inicial del microservicio de encuestas.
- Estructura base FastAPI + SQLAlchemy + PostgreSQL + RabbitMQ.