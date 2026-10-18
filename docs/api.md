# Referencia de la API REST

Polls expone una API REST v1 bajo el prefijo `/api/v1`. Todos los cuerpos son JSON. El servicio genera un UUID para `poll_id` y para cada `option_id`.

La especificación OpenAPI está disponible en `/openapi.json`; la interfaz interactiva de Swagger UI está en `/docs` y ReDoc en `/redoc`.

## Endpoints

| Método | Ruta | Propósito | Respuesta de éxito |
| --- | --- | --- | --- |
| `GET` | `/health` | Comprueba que la API responde. | `200` |
| `POST` | `/api/v1/polls` | Crea una encuesta. | `200`, `201` o `202` |
| `POST` | `/api/v1/polls/{poll_id}/votes` | Registra un voto. | `201` |
| `POST` | `/api/v1/polls/{poll_id}/close` | Cierra una encuesta. | `200` |
| `GET` | `/api/v1/polls/{poll_id}` | Consulta una encuesta y sus resultados. | `200` |

## Comprobar disponibilidad

`GET /health` no requiere parámetros ni cuerpo.

Respuesta `200`:

```json
{
  "status": "ok"
}
```

## Crear encuesta

`POST /api/v1/polls` recibe los datos de la encuesta. `duration_minutes` es opcional: por defecto son 5 minutos. Debe ser un entero entre 1 y 1440; Polls calcula y devuelve `closes_at` desde el instante en que recibe la solicitud. Se requieren de 2 a 10 alternativas no vacías y distintas.

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

Ejemplo de respuesta `201`:

```json
{
  "poll_id": "123e4567-e89b-12d3-a456-426614174000",
  "channel_id": "channel-123",
  "author_id": "user-456",
  "question": "¿Qué alternativa prefieres?",
  "options": [
    {
      "option_id": "123e4567-e89b-12d3-a456-426614174001",
      "position": 0,
      "text": "Alternativa A",
      "vote_count": 0
    },
    {
      "option_id": "123e4567-e89b-12d3-a456-426614174002",
      "position": 1,
      "text": "Alternativa B",
      "vote_count": 0
    }
  ],
  "status": "open",
  "duration_minutes": 5,
  "closes_at": "2026-10-18T15:05:00Z",
  "created_at": "2026-10-18T15:00:00Z",
  "closed_at": null,
  "total_votes": 0,
  "creation_error": null
}
```

## Registrar un voto

`POST /api/v1/polls/{poll_id}/votes` recibe `poll_id` como parámetro de ruta (UUID). El cuerpo identifica a quien vota y la alternativa elegida:

```json
{
  "voter_id": "user-789",
  "option_id": "123e4567-e89b-12d3-a456-426614174001"
}
```

Se permite un voto por usuario en cada encuesta. Un voto repetido o una encuesta cerrada responde `409`; una opción que no pertenece a la encuesta responde `422`.

Respuesta `201`:

```json
{
  "poll_id": "123e4567-e89b-12d3-a456-426614174000",
  "voter_id": "user-789",
  "option_id": "123e4567-e89b-12d3-a456-426614174001",
  "cast_at": "2026-10-18T15:01:00Z"
}
```

## Cerrar encuesta

`POST /api/v1/polls/{poll_id}/close` recibe `poll_id` como parámetro de ruta (UUID) y el siguiente cuerpo:

```json
{
  "author_id": "user-456"
}
```

Solo el `author_id` creador puede cerrarla (`403` para otro usuario). Repetir un cierre válido devuelve el estado final sin volver a publicar el evento.

Respuesta `200` (se muestra una encuesta sin votos):

```json
{
  "poll_id": "123e4567-e89b-12d3-a456-426614174000",
  "channel_id": "channel-123",
  "author_id": "user-456",
  "question": "¿Qué alternativa prefieres?",
  "options": [
    {
      "option_id": "123e4567-e89b-12d3-a456-426614174001",
      "position": 0,
      "text": "Alternativa A",
      "vote_count": 0
    },
    {
      "option_id": "123e4567-e89b-12d3-a456-426614174002",
      "position": 1,
      "text": "Alternativa B",
      "vote_count": 0
    }
  ],
  "status": "closed",
  "duration_minutes": 5,
  "closes_at": "2026-10-18T15:05:00Z",
  "created_at": "2026-10-18T15:00:00Z",
  "closed_at": "2026-10-18T15:02:00Z",
  "total_votes": 0,
  "creation_error": null
}
```

## Consultar encuesta y resultados

`GET /api/v1/polls/{poll_id}` recibe `poll_id` como parámetro de ruta (UUID) y no requiere cuerpo. Devuelve `poll_id`, `channel_id`, `author_id`, pregunta, estado, fechas, `total_votes` y cada opción con su identificador, texto y `vote_count`. Los conteos se muestran mientras la encuesta está abierta y cerrada; el estado también puede ser `pending_announcement` o `creation_failed`.

Respuesta `200`:

```json
{
  "poll_id": "123e4567-e89b-12d3-a456-426614174000",
  "channel_id": "channel-123",
  "author_id": "user-456",
  "question": "¿Qué alternativa prefieres?",
  "options": [
    {
      "option_id": "123e4567-e89b-12d3-a456-426614174001",
      "position": 0,
      "text": "Alternativa A",
      "vote_count": 0
    },
    {
      "option_id": "123e4567-e89b-12d3-a456-426614174002",
      "position": 1,
      "text": "Alternativa B",
      "vote_count": 0
    }
  ],
  "status": "open",
  "duration_minutes": 5,
  "closes_at": "2026-10-18T15:05:00Z",
  "created_at": "2026-10-18T15:00:00Z",
  "closed_at": null,
  "total_votes": 0,
  "creation_error": null
}
```

Errores generales: `404` para encuesta inexistente, `409` para voto duplicado, encuesta cerrada o conflicto de idempotencia, `410` si el anuncio pendiente venció, `422` para datos inválidos y `403` si alguien distinto al autor solicita el cierre.
