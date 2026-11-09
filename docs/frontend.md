# Interfaz web Chat + Polls

Frontend Next.js App Router, React y TypeScript para INF326. Se mantiene en `frontend/` sin reorganizar Polls ni el Gateway.

## Arquitectura y operaciones

```text
Navegador → Next.js /api/graphql → Gateway /graphql/ → microservicios existentes
```

El navegador solo llama `POST /api/graphql` en el mismo origen. El Route Handler (`frontend/src/app/api/graphql/route.ts`) reenvía JSON al `GATEWAY_GRAPHQL_URL` de servidor, limita el cuerpo, rechaza documentos que no estén en la lista de operaciones de la interfaz, no acepta URL de destino en el cuerpo y no reenvía cookies ni headers de autenticación. Conserva `data`, `errors` y `extensions`; transforma fallos de conexión en respuestas GraphQL con HTTP `502` y timeouts en `504`.

El destino se configura en el entorno de Next.js y no usa `NEXT_PUBLIC_`. No se configura CORS en Kubernetes: la llamada navegador → Next es same-origin y la llamada Next → Gateway es server-to-server.

Las operaciones del frontend corresponden al esquema existente en `gateway/app/schema.py`:

| Funcionalidad | Operación usada |
|---|---|
| Usuarios | `channels` no aplica; `user(id:)`, `createUser(displayName:)` |
| Canales | `channels`, `channel(id:)`, `createChannel(name:)` |
| Conversación | `messages(channelId:)`, `sendMessage(channelId:, authorId:, content:)` |
| Encuestas | `polls(channelId:)`, `poll(id:)`, `createPoll(input:, idempotencyKey:)`, `vote(pollId:, voterId:, optionId:)`, `closePoll(pollId:, authorId:)` |
| Reacciones | `Message.reactions`, `addReaction(messageId:, channelId:, userId:, reactionType:)`, `removeReaction(reactionId:)` |
| Búsqueda | `searchMessages(input:)` |

`polls(channelId:)` del Gateway es la fuente de Polls para el canal. El Gateway lo implementa descubriendo los IDs en los anuncios de Messages; la interfaz no repite ese descubrimiento ni hace una consulta individual por cada Poll listado. Para relacionar un anuncio con una encuesta, una utilidad aislada extrae el ID del mensaje. Los Polls recién creados se conservan en memoria y se consultan por `poll(id:)` mientras su estado sea `pending_announcement`. El listado por canal puede omitir Polls pendientes o fallidos, sin anuncio o creados mientras Messages estaba deshabilitado.

El Gateway devuelve errores con `errors[].extensions`, que pueden contener `code`, `service` y `status`. La UI no interpreta todo `409` como el mismo caso: después de un conflicto de voto vuelve a consultar la encuesta para identificar si está cerrada o pendiente; si sigue abierta, informa que el perfil podría haber votado antes. Un `422` indica que se deben revisar los datos enviados. Tras votar, consulta nuevamente `poll(id:)` para actualizar los conteos.

La selección de usuario es un **perfil de demostración** que guarda el ID localmente. No es autenticación y el Gateway no valida identidad de persona. No existe query GraphQL para listar usuarios: se puede crear uno o consultar uno conocido mediante su ID.

## Requisitos y configuración

- Windows PowerShell con Node.js 20 o posterior, pnpm 12.9.1 y Docker Desktop para el modo Compose.
- El Service del Gateway verificado es `polls-gateway`, en el namespace `grupo-encuestas`, puerto `5000`, tipo `ClusterIP` (`k8s/gateway/service.yaml`). No hay Ingress configurado.
- El Gateway usa dentro del cluster las URLs declaradas en `k8s/gateway/configmap.yaml`. El frontend no llama a esos hosts y no necesita conocer el DNS de los microservicios.

Ejemplo de configuración local, sin credenciales:

```dotenv
GATEWAY_GRAPHQL_URL=http://localhost:5000/graphql/
```

Este valor solo está en el proceso servidor de Next.js. El proxy solo necesita HTTP(S) y envía las operaciones GraphQL definidas por la interfaz.

## Desarrollo local en Windows PowerShell

1. En una terminal, configura el path local del kubeconfig sin mostrar ni copiar su contenido y levanta el port-forward:

   ```powershell
   $env:KUBECONFIG = "<RUTA_LOCAL_AL_KUBECONFIG>"
   kubectl --kubeconfig $env:KUBECONFIG -n grupo-encuestas port-forward service/polls-gateway 5000:5000
   ```

   Mantén esta terminal abierta. `kubectl port-forward` publica el Service en la interfaz local por defecto; no crea un Ingress ni expone públicamente el Gateway.

2. Verifica el proceso del Gateway:

   ```powershell
   Invoke-WebRequest http://localhost:5000/health
   ```

   Un `200` confirma que el Gateway responde, pero no comprueba por sí solo la disponibilidad de cada upstream.

3. En otra terminal, desde la raíz del repositorio, instala y ejecuta el frontend:

   ```powershell
   Set-Location frontend
   Copy-Item .env.local.example .env.local
   pnpm install --frozen-lockfile
   pnpm run dev
   ```

   Comprueba que `frontend/.env.local` contiene `GATEWAY_GRAPHQL_URL=http://localhost:5000/graphql/`. Este archivo local no se versiona. Si prefieres no crear el archivo, define la variable antes de `pnpm run dev`:

   ```powershell
   $env:GATEWAY_GRAPHQL_URL = "http://localhost:5000/graphql/"
   pnpm run dev
   ```

4. Abre `http://localhost:3000`. El navegador envía operaciones al endpoint local `/api/graphql`; Next.js llega al port-forward usando `localhost:5000`.

No uses `npm`: el proyecto fija pnpm en `frontend/package.json` y commitea `pnpm-lock.yaml`. pnpm limita scripts de instalación y solo autoriza el script de `esbuild`, requerido por Vitest, en `frontend/pnpm-workspace.yaml`.

## Ejecución con Docker Compose

El `compose.yaml` actual conserva `migrate`, Polls, PostgreSQL y RabbitMQ, agrega el frontend y nombra la red predeterminada exactamente `microsvcs`. No agrega contenedores de Users, Channels, Messages, Reacciones, Búsqueda ni un segundo Gateway.

En PowerShell, con el port-forward anterior ejecutándose:

```powershell
$env:GATEWAY_GRAPHQL_URL = "http://host.docker.internal:5000/graphql/"
docker compose up --build frontend
```

Después abre `http://localhost:3000`. El destino es una variable de servidor del contenedor; el browser sigue llamando a `/api/graphql` en Next.

`host.docker.internal` permite al contenedor resolver el host en Docker Desktop, pero el port-forward de `kubectl` normalmente escucha en loopback. Por eso, desde el frontend contenedorizado la ruta debe verificarse en este equipo antes de la demostración. Compruébala con el túnel activo:

```powershell
docker compose run --rm frontend node -e "fetch('http://host.docker.internal:5000/health').then(r => { console.log('HTTP ' + r.status); process.exit(r.ok ? 0 : 1) }).catch(e => { console.error(e.message); process.exit(1) })"
```

En este entorno validé `host.docker.internal` desde el contenedor Compose contra un servidor HTTP temporal enlazado a `127.0.0.1` del host: respondió `200`. Eso verifica el trayecto host-loopback ↔ Docker Desktop, **no** la conexión al Gateway del cluster. Repite la prueba anterior con el port-forward activo para validar ese destino. Si falla, usa la ejecución directa de Next.js en Windows descrita arriba. No cambies el bind a `0.0.0.0` sin evaluar que eso haría accesible el puerto del host desde otras interfaces de red. La red `microsvcs` conecta contenedores Docker entre sí; no resuelve los DNS `*.svc.cluster.local` del cluster.

`docker compose up --build` inicia el frontend junto con el stack local de Polls. En ese modo, el Gateway configurado sigue siendo el del cluster si `GATEWAY_GRAPHQL_URL` apunta a `host.docker.internal`; el Polls local no es upstream de ese Gateway. Para bajar los servicios, usa `docker compose down`.

## Uso de la interfaz

1. En la primera visita, crea un usuario de demostración o consulta uno por ID conocido. No hay listado de usuarios. La interfaz conserva el perfil y canal seleccionados en almacenamiento local; eso no crea una sesión autenticada.
2. Selecciona un canal de la barra lateral o crea uno con **＋**.
3. Escribe en el compositor inferior y envía con Enter; Shift+Enter crea una línea nueva. La conversación consulta mensajes y Polls juntos y refresca aproximadamente cada 15 segundos solo si la pestaña está visible.
4. Para crear una encuesta, completa una pregunta, de 2 a 10 alternativas no vacías y una duración entre 1 y 1440 minutos. Si retorna `pending_announcement`, la tarjeta lo indica y la UI consulta el ID recién creado cada cinco segundos mientras la pestaña está activa.
5. En una encuesta abierta, selecciona una alternativa y pulsa **Votar**. Los resultados se vuelven a consultar después de la operación. En estado cerrada o pendiente no se ofrece el voto.
6. El autor indicado puede cerrar una encuesta abierta. Polls verifica el `authorId` recibido; la selección local del perfil no demuestra identidad.
7. En mensajes se muestra el resumen de Reacciones y un selector con 👍 `like`, ❤️ `heart`, 😂 `laugh`, 😢 `sad`, 😮 `surprised`, 😡 `angry`, 🔥 `fire`, 🎉 `celebrate` y 👎 `dislike`. `like`, `heart` y `sad` son ejemplos del OpenAPI 1.0.2 que compartió el equipo; los otros nombres cumplen el patrón y el largo del contrato, pero no se ha confirmado que el servicio los acepte semánticamente. Las reacciones propias se pueden quitar. Un `409` al crear se presenta como posible duplicado y refresca el mensaje, sin mostrar un éxito falso. Los tipos desconocidos del backend se muestran como texto.
8. **Buscar** permite contenido, canal, ID del autor, ID mencionado, fechas, `LINK`/`MENTION`, orden y paginación. Al elegir un resultado, la interfaz abre su canal y trata de resaltar el mensaje. La búsqueda devuelve `channelId` e ID de mensaje, pero no un endpoint de contexto temporal.

## Verificación

Desde `frontend/`:

```powershell
pnpm run lint
pnpm run typecheck
pnpm run test
pnpm run build
```

Las pruebas de frontend simulan la respuesta GraphQL del Gateway y cubren el proxy allowlisted, la propagación de `data`/`errors`/`extensions`, el timeout, fallos de conexión y extracción/mezcla local de encuestas. **No simulan ni certifican conexión real con los servicios desplegados.** Durante esta implementación no se consultó el cluster ni se usó el kubeconfig; la integración real queda pendiente de verificar con el port-forward activo y operaciones de prueba en un canal autorizado. El proxy comprueba el destino con `GET /health`; la interfaz opera por GraphQL.

La CI de frontend instala con pnpm, ejecuta lint, typecheck, tests y build. El workflow de publicación de Polls se filtra por rutas propias del servicio para que cambios solo en `frontend/` no publiquen otra imagen de Polls.

## Guion breve para el video

1. Mostrar el chat oscuro en `localhost:3000`, crear un usuario de demostración y explicar que es un ID, no login.
2. Crear o seleccionar un canal, enviar dos mensajes y mostrar autores/fechas.
3. Agregar una reacción y retirarla.
4. Buscar un mensaje por contenido o filtro de canal y abrir el canal del resultado.
5. Crear una encuesta, elegir una alternativa, votar y mostrar el conteo actualizado.
6. Cerrar la encuesta con el perfil autor y mostrar el estado/resultados finales.
7. Mostrar brevemente la tarjeta pendiente si se dispone de un caso de prueba; explicar que el listado del Gateway se descubre desde anuncios de Messages.
8. Cerrar indicando que las solicitudes del navegador llegan a Next `/api/graphql` y el Gateway permanece interno en Kubernetes.
