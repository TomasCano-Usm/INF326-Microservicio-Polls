# Control de calidad — guía de evaluación

Esta guía permite ejecutar y revisar la entrega después de clonar únicamente el
repositorio `INF326-Microservicio-Polls/`.

## Ruta rápida: ejecutar todo en Windows CMD

Necesitas Python 3.14 y Docker Desktop iniciado. Abre **CMD** en la raíz del
repositorio y ejecuta:

```cmd
run_qa.cmd
```

El script crea `.venv` si hace falta, comprueba que use Python 3.14, instala las
dependencias, prepara una carpeta temporal bajo `%LOCALAPPDATA%\PollsQA` y ejecuta
las pruebas de servicio, contrato e integración. Así pytest no depende de la
carpeta temporal predeterminada de Windows. Si las pruebas fallan, el script
conserva su carpeta temporal para facilitar el diagnóstico; si pasan, la elimina.
La integración construye y levanta el entorno Docker QA y lo elimina
automáticamente al terminar. No ejecutes Compose manualmente.

En la primera ejecución pueden descargarse paquetes e imágenes de Docker. El
resultado validado en Windows con Python 3.14.5 fue **35 aprobadas y 4 omitidas**;
las omitidas son pruebas opcionales que requieren PostgreSQL o RabbitMQ externos.

## Requisitos

- Python 3.14.
- Docker Desktop iniciado y el comando `docker compose` disponible para la
  integración.
- La copia QA del chat base está en `tests/fixtures/chat_base/`. Su archivo
  `README.md` documenta el repositorio de origen, la revisión incluida y la
  licencia. No se modifica el repositorio original.

La integración se ejecuta localmente. Docker puede necesitar descargar imágenes
y dependencias de Python durante la primera construcción.

## Ejecutar solo las pruebas de servicio y contrato (opcional)

Desde la raíz del repositorio, usa el bloque correspondiente a tu terminal.
En Windows, `--basetemp` es necesario en este equipo para no usar la carpeta
temporal predeterminada que está dando errores de permisos.

**Windows CMD (Símbolo del sistema):**

```cmd
py -3.14 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements-dev.txt
if not exist "%LOCALAPPDATA%\PollsQA" mkdir "%LOCALAPPDATA%\PollsQA"
python -m pytest -q --basetemp="%LOCALAPPDATA%\PollsQA\run-%RANDOM%-%RANDOM%"
```

**Linux, macOS o WSL:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Para ejecutar solo la prueba de contrato con Messages, usa el comando de tu
terminal:

**Windows CMD:**

```cmd
if not exist "%LOCALAPPDATA%\PollsQA" mkdir "%LOCALAPPDATA%\PollsQA"
python -m pytest tests/test_messages_client.py -v --basetemp="%LOCALAPPDATA%\PollsQA\messages-contract"
```

**Linux, macOS o WSL:**

```bash
python -m pytest tests/test_messages_client.py -v
```

La suite estándar no necesita Docker, PostgreSQL, RabbitMQ ni Messages. Por
configuración, pytest excluye las pruebas marcadas `integration`; cuatro pruebas
opcionales se omiten si no se configura PostgreSQL o RabbitMQ de prueba.

## Qué se probó

| Archivo | Tipo | Qué demuestra |
|---|---|---|
| `tests/test_polls_api.py` | Servicio | Endpoints de Polls con casos correctos y de error; base SQLite temporal y dobles de Messages y RabbitMQ. |
| `tests/test_messages_client.py` | Contrato | Solicitudes de anuncio y resultados de Polls compatibles con la API HTTP de Messages. |
| `tests/contracts/messages-v1.openapi.json` | Contrato | Fragmento OpenAPI de referencia para `POST /api/v1/channels/{channel_id}/messages`. |
| `tests/test_compose_integration.py` | Integración + contrato proveedor | Compara el OpenAPI de Messages real con el contrato guardado y recorre el flujo HTTP real de Polls. |

### Aislamiento y cobertura de servicio

La fixture `api` en `tests/test_polls_api.py` crea la aplicación mediante
`create_app`, inyecta una base SQLite dentro de `tmp_path` y configura
`create_schema=True`. El archivo temporal se elimina al finalizar la fixture de
pytest. El publicador RabbitMQ y el cliente Messages son dobles de prueba; estas
pruebas no utilizan la base de datos de desarrollo ni se conectan a esos
servicios.

| Endpoint | Casos incluidos |
|---|---|
| `POST /api/v1/polls` | Creación, idempotencia, cuerpo inválido y opciones inválidas. |
| `POST /api/v1/polls/{poll_id}/votes` | Voto aceptado, voto duplicado y opción inválida. |
| `POST /api/v1/polls/{poll_id}/close` | Cierre, repetición idempotente, autor no autorizado y reintentos de entrega. |
| `GET /api/v1/polls/{poll_id}` | Encuesta existente y recurso inexistente. |

También hay pruebas de salud, vencimiento de encuestas, reintentos y eventos.
Algunos casos correctos y de error se agrupan en la misma función de prueba.

### Contrato con Messages del chat base

`tests/test_messages_client.py::test_poll_announcement_and_closure_follow_messages_v1_contract`
ejecuta Polls contra `httpx.MockTransport` y comprueba sus solicitudes contra
`tests/contracts/messages-v1.openapi.json`. El contrato se obtuvo del servicio
Messages del checkout local del curso, revisión
`8930ac9255ff5a5e7574d9546404e76f1ebb62dd`, archivo
`03_Comunicación/demo/messages/app/main.py`.

Se verifica el método `POST`, la ruta, el parámetro `channel_id`, el cuerpo JSON
(`author_id` como texto y `content` de 1 a 4000 caracteres) y la respuesta `201`.
La prueba también comprueba que Polls envíe tanto el anuncio como los resultados
finales. El transporte HTTP se simula; no se consulta la base de Messages ni se
levanta el servicio para esta prueba. La integración de la sección siguiente
comprueba además que el OpenAPI del Messages real siga cumpliendo ese contrato.

## Ejecutar solo la integración local (opcional)

`compose.qa.yaml` usa el chat base vendorizado en `tests/fixtures/chat_base/` y
crea un stack aislado con Polls, PostgreSQL, RabbitMQ, Users, Channels, Messages
y una instancia MongoDB por servicio de chat. Los puertos host por defecto son
`18001` (Users), `18002` (Channels), `18003` (Messages) y `18004` (Polls). El
stack se ejecuta con un nombre de proyecto dedicado, separado del Compose de
desarrollo.

Desde la raíz del repositorio, con el entorno virtual activado, ejecuta:

**Windows CMD:**

```cmd
python -m pytest -m integration -v
```

**Linux, macOS o WSL:**

```bash
python -m pytest -m integration -v
```

La fixture de pytest construye y levanta el stack automáticamente, espera las
APIs, ejecuta las pruebas y elimina al terminar los contenedores, la red y los
volúmenes con los datos QA. Si hay un fallo, imprime los últimos logs del stack
antes de limpiarlo. Las imágenes quedan en la caché local de Docker.

La prueba de contrato compara el OpenAPI del servicio Messages real con el
fragmento guardado. La prueba de flujo crea un usuario y un canal por sus APIs,
crea una encuesta, verifica el anuncio, registra un voto, cierra la encuesta y
comprueba el mensaje de resultados. Todo se verifica por HTTP, sin consultar las
bases de datos directamente. La última ejecución de esta integración terminó con
**2 aprobadas**: una para el contrato proveedor y otra para el flujo completo.

## Pruebas opcionales

Cuatro pruebas adicionales se omiten en la suite estándar porque necesitan
servicios reales configurados por separado:

- `tests/test_postgres_concurrency.py`: establece
  `POLLS_TEST_DATABASE_URL` con una **base PostgreSQL de pruebas** donde se
  puedan crear schemas. Cada caso usa un schema aislado.
- `tests/test_rabbitmq_consumer_integration.py`: establece
  `POLLS_TEST_RABBITMQ_URL` y `POLLS_TEST_RABBITMQ_MANAGEMENT_URL` para un
  RabbitMQ de pruebas.

No son necesarias para ejecutar la integración principal de esta entrega.
