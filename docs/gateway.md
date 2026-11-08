# Gateway GraphQL de Polls

Este gateway es un backend independiente para la futura interfaz de Polls. La interfaz consume GraphQL; el gateway integra las APIs REST de Polls, Users, Channels, Messages, Reacciones y Búsqueda avanzada. No accede directamente a las bases de datos de esos servicios y no modifica la API REST existente de Polls.

Implementación: FastAPI + Ariadne + HTTPX asíncrono + `aiodataloader`. El gateway no implementa autenticación: los IDs de usuario son identificadores del dominio, no credenciales.

## Contratos de los servicios

Los contratos se contrastaron contra `/openapi.json` de los servicios desplegados. La integración utiliza estas rutas:

| Servicio | Rutas consumidas |
| --- | --- |
| Polls (`1.3.5`) | `GET /api/v1/polls/{poll_id}`, `POST /api/v1/polls`, `POST /api/v1/polls/{poll_id}/votes`, `POST /api/v1/polls/{poll_id}/close` |
| Users (`1.0.0`) | `GET /api/v1/users/{user_id}`, `POST /api/v1/users` |
| Channels (`1.0.0`) | `GET /api/v1/channels`, `GET /api/v1/channels/{channel_id}`, `POST /api/v1/channels` |
| Messages (`1.0.0`) | `GET /api/v1/channels/{channel_id}/messages`, `POST /api/v1/channels/{channel_id}/messages` |
| Reacciones (`1.0.2`) | `GET /api/v1/messages/{message_id}/reactions`, `POST /api/v1/reactions`, `DELETE /api/v1/reactions/{reaction_id}` |
| Búsqueda avanzada (`1.0.0`) | `GET /api/v1/search/messages` |

Detalles de compatibilidad importantes:

- Messages recibe `author_id` y `content`; el `channel_id` va en la ruta.
- El gateway siempre incluye `channel_id` al consultar y crear reacciones. Aunque el OpenAPI desplegado declara opcional el parámetro de consulta al listar, una petición sin él respondió `422 channel_id_required` con la validación externa habilitada.
- Crear una encuesta puede responder `201` o `202`. El gateway conserva el `status`, incluyendo `pending_announcement`, en ambos casos.
- No existe `GET /api/v1/polls` para listar encuestas. `polls(channelId:)` obtiene los mensajes existentes del canal, extrae UUID de líneas `Poll ID: <uuid>` y consulta cada encuesta por su endpoint oficial. Deduplica IDs y verifica que el `channel_id` devuelto coincida. No descubre encuestas pendientes, fallidas, sin anuncio o creadas con Messages deshabilitado. Depende del texto del anuncio y Messages no ofrece paginación en su contrato actual.
- Los errores en datos principales se devuelven como errores GraphQL con `extensions.code=UPSTREAM_ERROR`. Si Reacciones falla, `Message.reactions` queda `null` y los mensajes permanecen disponibles. Un usuario inexistente también produce `null` en campos nullable de usuario.
- La búsqueda conserva filtros repetidos y valida los límites desplegados (`limit` 1–25 y `offset` 0–9975) antes de llamar al servicio.

## Configuración de upstreams

Cada servicio se configura con una URL base HTTP(S):

| Variable | Valor local predeterminado | Ejemplo dentro del clúster |
| --- | --- | --- |
| `POLLS_SERVICE_URL` | `http://localhost:8004` | `http://polls.grupo-encuestas.svc.cluster.local:8004` |
| `USERS_SERVICE_URL` | `http://localhost:8001` | `http://users.servicios-base.svc.cluster.local:8000` |
| `CHANNELS_SERVICE_URL` | `http://localhost:8002` | `http://channels.servicios-base.svc.cluster.local:8000` |
| `MESSAGES_SERVICE_URL` | `http://localhost:8003` | `http://messages.servicios-base.svc.cluster.local:8000` |
| `REACTIONS_SERVICE_URL` | `http://localhost:8000` | `http://reaction-service.grupo-reacciones.svc.cluster.local:8000` |
| `SEARCH_SERVICE_URL` | `http://localhost:8000` | `http://search.grupo-busqueda-avanzada.svc.cluster.local:8000` |
| `UPSTREAM_TIMEOUT_SECONDS` | `5` | `5` |
| `GATEWAY_CORS_ORIGINS` | vacío (same-origin) | lista de orígenes separados por coma |

Los defaults locales solo son convenientes cuando esos servicios realmente escuchan en los puertos indicados; configura explícitamente las URLs de tu entorno. DNS `*.svc.cluster.local` solo es resoluble desde Pods con acceso al clúster. No se requieren credenciales Kubernetes ni acceso a bases de datos.

Si la UI se publica en un origen distinto, configura `GATEWAY_CORS_ORIGINS` con una lista explícita, por ejemplo `https://polls.example.edu`. No se habilita `*` por defecto; con UI y API bajo el mismo origen no se necesita configuración CORS.

## Desarrollo y pruebas con mocks

Requiere Python 3.12 o superior. Las pruebas usan exclusivamente `httpx.MockTransport`: no arrancan los microservicios ni realizan peticiones de red, incluso para las mutaciones.

Desde la raíz de este repositorio:

```bash
python -m venv .venv-gateway
source .venv-gateway/bin/activate
pip install -r gateway/requirements-dev.txt
python -m pytest gateway/tests -q
```

En PowerShell, activa el entorno con `.venv-gateway\Scripts\Activate.ps1`.

Para iniciar el servidor cuando tengas upstreams accesibles, define sus URLs y ejecuta:

```bash
export POLLS_SERVICE_URL=http://localhost:8004
export USERS_SERVICE_URL=http://localhost:8001
export CHANNELS_SERVICE_URL=http://localhost:8002
export MESSAGES_SERVICE_URL=http://localhost:8003
export REACTIONS_SERVICE_URL=http://localhost:8005
export SEARCH_SERVICE_URL=http://localhost:8006
uvicorn gateway.app.main:app --reload --port 5000
```

La aplicación expone `GET http://localhost:5000/health`, GraphQL en `/graphql/` y GraphiQL en el navegador. Los puertos de Reacciones y Search en el ejemplo son solo ilustrativos para evitar el conflicto entre ambos defaults: ajústalos a los puertos reales de tu entorno.

## Consultas de ejemplo

Canales y mensajes (los campos `author` y `reactions` son opcionales y sus fallos no invalidan el mensaje):

```graphql
query {
  channels { id name }
  messages(channelId: "<channel-id>") {
    id content createdAt
    author { id displayName }
    reactions {
      totalReactions
      summary { reactionType count }
    }
  }
}
```

Consultar y descubrir encuestas anunciadas en un canal:

```graphql
query {
  poll(id: "<poll-uuid>") { pollId question status totalVotes }
  polls(channelId: "<channel-id>") {
    pollId question status
    options { optionId text voteCount }
  }
}
```

Búsqueda avanzada (los filtros de lista se envían como parámetros repetidos al upstream):

```graphql
query {
  searchMessages(input: {
    content: "arquitectura"
    channelIds: ["<channel-id>"]
    has: [LINK]
    sortBy: RELEVANCE
    sortOrder: DESC
    limit: 10
    offset: 0
  }) {
    totalResults
    messages { id channelId authorId content createdAt }
  }
}
```

## Mutaciones disponibles

| Mutación | Servicio destino |
| --- | --- |
| `createUser(displayName:)` | Users |
| `createChannel(name:)` | Channels |
| `sendMessage(channelId:, authorId:, content:)` | Messages |
| `createPoll(input:, idempotencyKey:)` | Polls; reenvía `Idempotency-Key` si se entrega |
| `vote(pollId:, voterId:, optionId:)` | Polls |
| `closePoll(pollId:, authorId:)` | Polls |
| `addReaction(messageId:, channelId:, userId:, reactionType:)` | Reacciones; incluye `channel_id` |
| `removeReaction(reactionId:)` | Reacciones; acepta respuesta REST `204` |

Estas mutaciones están cubiertas solamente con upstreams simulados. No se enviaron POST ni DELETE a los servicios desplegados durante esta implementación.

## Imagen Docker

El Dockerfile independiente se construye desde la raíz del repositorio:

```bash
docker build -f Dockerfile.gateway -t polls-graphql-gateway:local .
```

El contenedor escucha en `5000`. El workflow `.github/workflows/publish-gateway-image.yml` ejecuta las pruebas del gateway en PR y, al recibir cambios relevantes en `main`, publica `ghcr.io/tomascano-usm/inf326-polls-gateway` con las etiquetas `main` y `sha-<commit>`. Este workflow solo publica la imagen; **no despliega ni modifica Polls**.

## Despliegue manual en Kubernetes

Los manifiestos independientes están en `k8s/gateway/` y usan el namespace existente `grupo-encuestas`:

- `configmap.yaml`: direcciones internas de los seis servicios, timeout y CORS vacío por defecto.
- `deployment.yaml`: Deployment `polls-gateway`, imagen `:main`, puerto `5000` y probes de salud. El ConfigMap se inyecta como variables de entorno; no se editan las URLs en Python.
- `service.yaml`: Service interno `polls-gateway:5000` de tipo `ClusterIP`.

Cuando el workflow haya terminado correctamente y la imagen esté disponible, aplica los manifiestos desde la raíz del repositorio (reemplaza la ruta por la de tu kubeconfig; no la guardes en el repo):

```powershell
kubectl --kubeconfig "RUTA_A_TU_KUBECONFIG" -n grupo-encuestas apply -f k8s/gateway/
kubectl --kubeconfig "RUTA_A_TU_KUBECONFIG" -n grupo-encuestas rollout status deployment/polls-gateway
```

Para comprobar el backend sin publicar la UI ni crear un Ingress, abre un port-forward al gateway:

```powershell
kubectl --kubeconfig "RUTA_A_TU_KUBECONFIG" -n grupo-encuestas port-forward service/polls-gateway 5000:5000
```

En otra terminal, comprueba `http://localhost:5000/health` y envía consultas GraphQL a `http://localhost:5000/graphql/`. El Service es interno; una UI usada desde el navegador necesitará más adelante un Ingress u otro acceso alcanzable desde el navegador. Si la UI usa otro origen, configura `GATEWAY_CORS_ORIGINS` en `k8s/gateway/configmap.yaml` con su origen exacto, aplica de nuevo el ConfigMap y reinicia el Deployment:

```powershell
kubectl --kubeconfig "RUTA_A_TU_KUBECONFIG" -n grupo-encuestas rollout restart deployment/polls-gateway
```

El manifiesto apunta a la etiqueta móvil `:main` y usa `imagePullPolicy: Always`. Después de publicar una nueva imagen, ejecuta `rollout restart` para que Kubernetes cree un Pod y descargue la versión actualizada. Para reproducibilidad, puedes sustituir `:main` por la etiqueta inmutable `:sha-<commit>` publicada por el workflow. Si el paquete de GHCR es privado para el clúster, configura un `imagePullSecret` por separado; no guardes credenciales en el ConfigMap ni en Git.

## Verificación pendiente al desplegar

La suite de mocks prueba el esquema GraphQL, mapeo de contratos, payloads, estados `202`, filtros, deduplicación, propagación de errores y fallos parciales. No prueba conectividad ni comportamiento real de los upstreams. Después del despliegue, valida consultas de lectura contra los servicios y realiza mutaciones solo con datos de prueba y autorización explícita. La integración debe ajustarse si los contratos desplegados cambian.
