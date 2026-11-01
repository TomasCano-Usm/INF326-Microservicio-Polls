# Consumo externo de eventos RabbitMQ

## Acceso al broker

Los consumidores de otros grupos se conectan desde dentro del clúster mediante:

| Parámetro | Valor |
| --- | --- |
| Host | `rabbitmq.grupo-encuestas.svc.cluster.local` |
| Puerto | `5672` |
| Protocolo | AMQP 0-9-1 |
| Virtual host | `/` |
| Exchange | `polls.events` |
| Tipo | `topic`, durable |

El Service sigue siendo `ClusterIP`; el puerto `15672` del plugin Management también se expone solo en ese Service interno para el Job de provisioning. No hay Ingress, NodePort ni LoadBalancer. El acceso desde otro namespace depende de las reglas de red del clúster.

Polls publica estas routing keys sin cambiar sus contratos:

- `poll.created`
- `poll.vote.cast`
- `poll.closed`

El mensaje tiene el envelope existente `{event_id, event_type, occurred_at, payload}`.

## Modelo de queues y permisos

Cada integración tiene un usuario y una queue propios:

```text
usuario: polls-<grupo>
queue:   polls.consumer.<grupo>
```

La infraestructura declara una queue durable y crea los bindings seleccionados por el operador. El grupo consumidor no administra exchanges, queues ni bindings: solamente puede leer su queue. RabbitMQ recibe estos permisos por usuario y vhost:

| Permiso | Patrón para `polls-grupo-a` | Motivo |
| --- | --- | --- |
| `configure` | `^$` | No puede declarar ni eliminar recursos. |
| `write` | `^$` | No puede publicar ni modificar bindings. |
| `read` | `^polls\.consumer\.grupo-a$` | Solo puede consumir/leer su queue. |

El usuario no tiene tags administrativos, y no recibe credenciales de `polls`. No se le concede permiso sobre el exchange. Los bindings que instala el Job son los que determinan qué routing keys recibe cada grupo.

La queue ya existe antes de entregar las credenciales. El cliente debe consumirla por su nombre o hacer una declaración pasiva (`passive=True`); no debe intentar declararla activamente ni crear bindings. Por ejemplo, el cliente `aio-pika` puede usar este patrón, sustituyendo los placeholders localmente:

```python
import asyncio
import json
from urllib.parse import quote

import aio_pika


async def consume(username: str, password: str) -> None:
    user = quote(username, safe="")
    secret = quote(password, safe="")
    url = (
        f"amqp://{user}:{secret}@"
        "rabbitmq.grupo-encuestas.svc.cluster.local:5672/%2F"
    )
    connection = await aio_pika.connect_robust(url)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(
            "polls.consumer.grupo-a",
            passive=True,
        )
        async with queue.iterator() as messages:
            async for message in messages:
                async with message.process():
                    event = json.loads(message.body)
                    event_id = event["event_id"]
                    # Deduplicar event_id en la persistencia del consumidor.
                    print(event_id, event["event_type"])


asyncio.run(consume("<usuario-entregado>", "<password-entregada>"))
```

Las routing keys de una integración se configuran en `k8s/rabbitmq/consumers-configmap.yaml`. Al agregar un grupo se debe asignar un slug único, un usuario `polls-<slug>`, la queue correspondiente y una lista no vacía tomada de las tres routing keys disponibles.

## Credenciales y provisioning

No hay passwords en ConfigMaps ni manifests. Las credenciales externas se almacenan fuera de Git en el Secret:

```text
polls-rabbitmq-consumer-credentials
```

El ConfigMap contiene, por grupo, el nombre de una key (por ejemplo `POLL_CONSUMER_GRUPO_A_PASSWORD`); el Secret contiene el valor privado de esa key. Cada password es independiente. Entrega a cada grupo únicamente su username, password, vhost, queue y routing keys. No compartas `RABBITMQ_PASSWORD`, `RABBITMQ_URL` ni otras credenciales del usuario interno `polls`.

El Job `k8s/jobs/rabbitmq-consumer-provisioner.yaml` usa internamente `RABBITMQ_URL` desde `polls-credentials` para autenticarse contra `http://rabbitmq:15672/api`. No comparte ese secreto con los consumidores. El Job hace converger el estado deseado:

1. Declara o verifica el exchange durable `polls.events` tipo `topic`.
2. Crea/actualiza los usuarios `polls-<grupo>` sin tags administrativos y con los tres patrones mínimos anteriores.
3. Declara/actualiza la queue durable `polls.consumer.<grupo>`.
4. Añade bindings para las routing keys configuradas y elimina bindings obsoletos de esa queue.
5. Si se especifica `remove_groups`, elimina la queue solo si está vacía y sin consumidores, y revoca el usuario. Si no se puede borrar de forma segura, el Job falla en vez de descartar mensajes.

El Job puede ejecutarse repetidamente con la misma configuración y passwords: `PUT` actualiza usuario, permisos, exchange y queue, y los bindings se comparan antes de crear o eliminar. Para agregar una integración:

1. Añade username/slug, routing keys y `password_key` a `CONSUMERS_JSON` en el ConfigMap.
2. Crea/actualiza externamente `polls-rabbitmq-consumer-credentials` con esa key; no guardes los valores en archivos versionados.
3. Elimina el Job completado `rabbitmq-consumer-provisioner`, aplícalo de nuevo y espera su condición `complete`.
4. Entrega al grupo solo sus credenciales y datos de conexión.

Para quitar un grupo, añade su slug a `remove_groups` y vuelve a ejecutar el Job. Primero hay que parar sus consumidores y drenar su queue. El proceso elimina únicamente recursos del prefijo reservado `polls.consumer.` y usuarios `polls-<grupo>`.

RabbitMQ no tiene PVC. Al recrear el broker desaparecen usuarios, queues, bindings y mensajes encolados. Los valores de credenciales sobreviven en los Secrets externos: una vez que RabbitMQ esté Ready, vuelve a ejecutar el Job con el mismo ConfigMap y Secret, y los usuarios se reconstruirán con **las mismas passwords**. Los clientes podrán reconectarse sin recibir credenciales nuevas. El Job debe repetirse tras cada recreación del broker.

## Entrega, duplicados y reinicios

El transactional outbox conserva publicación *at-least-once*, no exactly-once. Una caída después de publisher confirm y antes de guardar `published_at` puede duplicar un evento; el `event_id` permanece estable. Los consumidores deben guardar/deduplicar esos IDs antes de confirmar el mensaje.

Aunque exchanges, queues y mensajes se declaren durable/persistent, RabbitMQ corre sin PVC por la cuota del namespace. Una recreación del broker puede perder mensajes ya confirmados; el outbox no vuelve a publicar los que Polls marcó como publicados. El provisioning recupera la topología y usuarios, no los mensajes perdidos.

El Job añade un Pod temporal con requests `50m/64Mi` y limits `100m/128Mi`, igual que el Job de migración. Ejecútalos de uno en uno. Para no exceder memoria durante una transición HPA, usa el procedimiento de congelar temporalmente el HPA descrito en [`kubernetes.md`](kubernetes.md). El límite de RabbitMQ permanece en `256Mi`; se valida con el plugin Management en ese presupuesto antes de desplegar.
