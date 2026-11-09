# Polls UI

Interfaz web del microservicio de encuestas. Está construida con React, Vite,
Chakra UI y Apollo Client, siguiendo la base de la interfaz de la Unidad 6.

## Alcance

La UI es **solo de encuestas**. No incluye pantallas para administrar usuarios,
canales ni mensajes. El gateway sigue usando esos servicios internamente cuando
corresponde, pero la interfaz solo expone operaciones de Polls:

- Listar las encuestas de un canal.
- Ver el detalle de una encuesta.
- Crear una encuesta.
- Votar.
- Cerrar una encuesta.

La interfaz pide dos identificadores de contexto:

- `channelId`: canal donde viven las encuestas.
- `userId`: usuario que crea, vota o cierra.

No son credenciales; son identificadores de dominio y se guardan en
`localStorage`.

## Modo demo local

`npm run dev` carga `.env.development`, que activa el **modo demo** con datos
locales. No se necesita gateway para recorrer la interfaz, crear encuestas,
votar y cerrar.

```bash
cd frontend
npm install
npm run dev
```

Abre `http://localhost:3000`.

En modo demo vienen prellenados un canal y un usuario de ejemplo. El botón
**Reiniciar datos** del banner superior restaura las encuestas de ejemplo.

## Usar el gateway real

Desactiva el modo demo:

```bash
VITE_DEMO_MODE=false npm run dev
```

También puedes cambiar `VITE_DEMO_MODE=true` por `false` en
`.env.development`. En este modo la UI usa `/graphql/` y Vite lo proxifica hacia
`http://localhost:5000`.

Necesitas el gateway disponible:

```bash
kubectl port-forward service/polls-gateway 5000:5000
```

Luego abre `http://localhost:3000` y pega el `channelId` y el `userId` reales.
El `channelId` debe tener anuncios de encuestas para que `polls(channelId:)`
pueda descubrirlas.

Para apuntar a otro gateway:

```bash
VITE_DEMO_MODE=false \
VITE_GATEWAY_URI=http://localhost:5000/graphql/ \
npm run dev
```

## Build de producción

```bash
npm run build
npm run preview
```

El build de producción no activa el modo demo. En producción, `nginx.conf`
sirve la SPA y proxifica `/graphql/` hacia `http://polls-gateway:5000`.

## Docker

La imagen escucha en el puerto `8080` y usa nginx sin privilegios:

```bash
docker build -t polls-ui:local ./frontend
docker run --rm -p 3000:8080 --network microsvcs polls-ui:local
```

El contenedor espera resolver el servicio `polls-gateway` dentro de la red
`microsvcs`.

## Seguridad y datos compartidos

En modo real la aplicación muestra un aviso de entorno compartido. El
formulario de encuestas agrega por defecto el prefijo `[TEST-UI]` a la pregunta.
No hay auto-seed ni creación masiva de datos.
