# Despliegue de Polls en Kubernetes

## Arquitectura

El namespace de la actividad es `grupo-encuestas`. Los manifests omiten `metadata.namespace`; los comandos de esta guía seleccionan el namespace explícitamente.

```text
Cliente --port-forward/ClusterIP--> Polls (1–3 Pods)
                                      |-- PostgreSQL (StatefulSet, PVC 1 GiB)
                                      |-- RabbitMQ (Deployment, Management API interno, efímero)
                                      `-- Messages del core (REST)
                                          http://messages.servicios-base.svc.cluster.local:8000
```

Solo se despliegan Polls, PostgreSQL y RabbitMQ. Users, Channels y Messages pertenecen al core del curso; Polls no consulta directamente Users ni Channels. Messages valida las referencias externas `author_id` y `channel_id`.

Los recursos están organizados en `k8s/polls/`, `k8s/postgres/`, `k8s/rabbitmq/` y `k8s/jobs/`. No hay Ingress, NodePort ni LoadBalancer.

## Health checks y dependencias

- `/health` se conserva para compatibilidad.
- `/health/live` solo indica que FastAPI está respondiendo; no consulta dependencias.
- `/health/ready` ejecuta `SELECT 1` en PostgreSQL. Si falla, responde `503` y Kubernetes deja de enviar tráfico al Pod.
- RabbitMQ y Messages no afectan readiness. PostgreSQL es la dependencia crítica para procesar solicitudes.

El lifespan de Polls sí verifica PostgreSQL antes de iniciar Uvicorn. Si PostgreSQL está caído al arrancar, el proceso termina y Kubernetes lo reinicia; por eso el despliegue espera a PostgreSQL antes de crear Polls. Si PostgreSQL cae después de arrancar, liveness sigue en `200`, readiness pasa a `503` y el contenedor no se reinicia por ese probe.

El publicador RabbitMQ conecta de manera lazy al intentar publicar. Un intento está limitado a 10 segundos; si falla, el worker libera el lease y programa el retry con backoff calculado desde el instante del fallo. El canal usa publisher confirms y `on_return_raises`: un confirm sin ninguna queue enrutada no marca el evento como publicado. El outbox conserva el evento y reintenta hasta que exista al menos una binding para su routing key.

Si `CONSUMERS_JSON` está vacío, no hay bindings de consumers y los eventos permanecen pendientes en PostgreSQL hasta provisionar una integración. Vigila el crecimiento de `outbox_events` si se mantiene esa configuración mientras se crean encuestas/votos; una vez configurados consumers, el worker entrega los eventos pendientes según su backoff (máximo 300 s).

El outbox ofrece entrega *at-least-once*, no exactly-once. Una caída después de la confirmación del broker y antes de guardar `published_at` puede repetir un evento; el `event_id` estable permite deduplicación por consumidores.

RabbitMQ no utiliza PVC: la única reclamación de almacenamiento permitida se reserva para PostgreSQL. El exchange y los mensajes se declaran durables/persistentes, pero el almacenamiento efímero del broker significa que una recreación del Pod puede perder colas y mensajes ya confirmados. El outbox no vuelve a publicar eventos que ya marcó como confirmados. Por lo tanto, esta instalación académica no ofrece recuperación de eventos ante pérdida de datos de RabbitMQ; consumidores y evidencia deben considerar esa limitación.

Messages tampoco ofrece idempotencia en su contrato HTTP. Un POST aceptado remotamente cuya respuesta se pierde, o una caída del Pod antes de guardar el resultado, puede ocasionar mensajes duplicados. El token de lease de `message_deliveries` impide que un intento antiguo sobrescriba el estado de un claim posterior, pero no elimina esa ambigüedad externa.

## Persistencia y concurrencia

PostgreSQL corre como un StatefulSet de una réplica con el único PVC del namespace: `postgres-data`, `ReadWriteOnce`, `1Gi`. Se omite `storageClassName` para utilizar la clase por defecto `do-block-storage`. El Service interno `postgres` proporciona el DNS que utilizan Polls y el Job de migración.

PostgreSQL usa el UID/GID `70`, correspondiente al usuario `postgres` de `postgres:16-alpine`, y ejecuta como no-root con seccomp `RuntimeDefault`; el Pod y sus containers también mantienen `allowPrivilegeEscalation: false` y `capabilities.drop: [ALL]`. La imagen oficial deja su entrypoint como root por defecto para que pueda preparar directorios y hacer `chown` antes de bajar privilegios. En este Pod, el UID root combinado con `drop: [ALL]` deja sin `CAP_CHOWN` y `CAP_FOWNER`: el entrypoint no puede cambiar el dueño de `PGDATA` ni el modo de `/var/run/postgresql` cuando no es su dueño. `fsGroup: 70` por sí solo agrega el grupo suplementario y prepara permisos de grupo en el volumen, pero no cambia el UID del proceso.

El initContainer `prepare-pgdata` corre también como UID/GID `70`, sin capabilities añadidas, y usa el mismo PVC. Si encuentra un `PG_VERSION` válido, verifica que el directorio pertenezca al UID de `postgres` y lo deja intacto. Si no hay `PG_VERSION`, solo elimina con `rmdir` el directorio de `PGDATA` si está vacío —el placeholder vacío que pudo dejar un inicio fallido como root— y lo recrea como UID `70`; ante contenido no inicializado no vacío, falla sin borrar datos. No ejecuta `chown` ni necesita privilegios. Sus requests `25m/32Mi` y limits `50m/64Mi` son menores que los del container PostgreSQL, por lo que no aumentan los recursos efectivos del Pod.

El volumen `do-block-storage` es RWO y usa ext4 por defecto. El CSIDriver de DigitalOcean deja `fsGroupPolicy` sin especificar, cuyo valor predeterminado Kubernetes es `ReadWriteOnceWithFSType`; por tanto, kubelet aplica `fsGroup: 70` al volumen para este modo de acceso y filesystem. Esto hace escribible por el grupo `70` el directorio raíz del volumen, permitiendo al initContainer retirar únicamente el directorio vacío y crear el nuevo directorio propietario correcto. `fsGroupChangePolicy: OnRootMismatch` evita recorridos recursivos innecesarios en cada reinicio. Se conserva el claim `postgres-data`, su ruta de montaje y `PGDATA=/var/lib/postgresql/data/pgdata`; no se reemplaza ni se borra el PVC.

Los probes `startupProbe`, `livenessProbe` y `readinessProbe` siguen ejecutando `pg_isready -U polls -d polls` dentro del container PostgreSQL. El socket Unix permanece en `/var/run/postgresql`, propiedad del UID `70`, por lo que el probe conserva su comportamiento.

RabbitMQ corre como un Deployment de una réplica con `rabbitmq:4-management-alpine` y estrategia `Recreate`. Durante la actualización se detiene el broker anterior antes de crear el nuevo: habrá una interrupción breve y no habrá dos brokers independientes detrás del Service. No representa HA; Polls conserva/reintenta eventos sin publicar. La recreación pierde estado efímero y requiere ejecutar de nuevo el provisioner después de que RabbitMQ esté listo.

La imagen oficial crea al usuario `rabbitmq` con UID `100` y GID `101` (`adduser -u 100`, `addgroup -g 101` en su [Dockerfile Alpine](https://github.com/docker-library/rabbitmq/blob/master/Dockerfile-alpine.template)); la imagen descargada confirma esos IDs y no declara un `USER` predeterminado. Se fijan explícitamente en el `securityContext` junto con `runAsNonRoot: true`. Sin esta configuración, el proceso empieza como root y el [entrypoint oficial](https://github.com/docker-library/rabbitmq/blob/master/docker-entrypoint.sh) intenta ajustar propietarios bajo `/var/lib/rabbitmq` y cambiar a `rabbitmq` mediante `su-exec`. Esa transición llama `setgroups()` y falla con `capabilities.drop: [ALL]` (`Operation not permitted`) porque no dispone de `CAP_SETGID`. Al arrancar directamente como UID/GID `100:101`, se omite la transición root→rabbitmq y no se requieren capabilities. La imagen prepara `/var/lib/rabbitmq`, `/etc/rabbitmq` y `/var/log/rabbitmq` para que el usuario de servicio pueda inicializarlos y escribir en ellos sin PVC.

El contenedor declara `allowPrivilegeEscalation: false`, `seccompProfile.type: RuntimeDefault` y `capabilities.drop: [ALL]`, conforme a Pod Security `restricted:v1.36`; no usa privileged, hostPath ni host networking. El Service `ClusterIP` `rabbitmq` ofrece AMQP en `5672` y Management API en `15672`, ambos solo dentro del clúster; RabbitMQ no tiene PVC ni clustering.

Las probes no ejecutan periódicamente una CLI Erlang:

- `startupProbe`: TCP en AMQP `5672`, cada 5 s, timeout 1 s y hasta 180 s de startup (`failureThreshold: 36`). Un test local con la imagen de auditoría tardó unos 52 s en completar el arranque.
- `readinessProbe`: abre TCP a `5672` y `15672` con Bash `/dev/tcp`, cada 5 s, timeout 1 s y dos fallos para retirar el Pod. Esto comprueba los dos listeners usados por Polls y el provisioner.
- `livenessProbe`: TCP en AMQP `5672`, cada 10 s, timeout 1 s y seis fallos consecutivos (aprox. 60 s) antes de reiniciar. La ventana evita reiniciar por una sola demora breve.

En pruebas locales, detener la aplicación RabbitMQ con `rabbitmqctl stop_app` dejaba `rabbitmq-diagnostics -q ping` en éxito, pero cerraba los puertos AMQP/Management: readiness y liveness TCP fallaron como se esperaba. Al desactivar solo Management, readiness falló y liveness AMQP permaneció sana. El coste observado para los comandos de probe, incluyendo overhead de `docker exec`, fue de 92–205 ms.

El ConfigMap `rabbitmq-config` fija `vm_memory_high_watermark.absolute = 160MiB`. Sin configuración, `rabbitmq:4-management-alpine` (RabbitMQ 4.4.0 en esta prueba) eligió el 60% de la RAM del host: `9396MiB`, aunque el límite del contenedor era `256MiB`. RabbitMQ recomienda un watermark absoluto en contenedores porque la detección de cgroups no siempre es correcta. La alarma activa flow control; **no es un límite de RSS ni impide que el proceso consuma más memoria**.

Mediciones bajo `256Mi`, CPU `250m`, UID/GID `100:101`, `drop: ALL`, `no-new-privileges` y seccomp RuntimeDefault local del runtime:

| Carga/medida | RabbitMQ `mem_used` / watermark | Memoria cgroup observada | Alarma/OOM |
| --- | ---: | ---: | --- |
| Recién listo | `126.4 MB` / `160Mi` (baseline aprox. `120.5Mi`) | `103–106Mi` | Sin alarma |
| 10 000 mensajes persistentes de 4 KiB | `140.2 MB` (aprox. `133.7Mi`) | `117.8Mi` | Sin alarma |
| Backlog sintético de más de 100 000 mensajes no persistentes de 4 KiB | Llegó a `162.7 MB`; el broker bloqueó el publisher por memoria y este agotó su timeout de prueba | Pico muestreado `147.2Mi` durante publicación | Flow control observado; sin OOM |
| Tras purgar un backlog grande | Spike transitorio de `mem_used=217.1 MB` y alarma activa | `memory.current=171.4 MB` de `268.4 MB`; `docker stats` llegó a `210.1Mi` | Alarma se despejó; sin OOM |

El watermark `160Mi` deja unos `39.5Mi` sobre el baseline interno medido, y `96Mi` aritméticos entre el umbral y el límite cgroup. Durante el spike la métrica interna sobrepasó el watermark, lo que confirma que no es una barrera de memoria. El test mostró que se activa flow control antes del OOM local y que los publishers pueden quedar bloqueados; por eso el timeout del outbox libera el lease y reintenta. El límite Kubernetes permanece en `256Mi`; se debe observar el uso real del clúster bajo carga.

## Consumidores externos RabbitMQ

El provisioning de consumidores usa el Management API interno de RabbitMQ. El puerto `15672` es un endpoint administrativo autenticado para el Job; no se entrega a los grupos consumidores. El Job accede con el `RABBITMQ_URL` del Secret interno `polls-credentials`. Nunca compartas esa credencial.

`k8s/rabbitmq/consumers-configmap.yaml` es la fuente declarativa no sensible. Su key `CONSUMERS_JSON` acepta esta forma:

```json
{
  "consumers": [
    {
      "group": "grupo-a",
      "routing_keys": ["poll.created", "poll.vote.cast"],
      "password_key": "POLL_CONSUMER_GRUPO_A_PASSWORD"
    }
  ],
  "remove_groups": []
}
```

El Job deriva username `polls-grupo-a` y queue `polls.consumer.grupo-a`; solo se aceptan routing keys del contrato Polls. El password procede de la key nombrada en `password_key` del Secret externo:

```text
Secret: polls-rabbitmq-consumer-credentials
Key:    POLL_CONSUMER_GRUPO_A_PASSWORD
```

Los valores reales se generan y almacenan manualmente fuera de Git. El Secret se proyecta solo al Job de provisioning; al grupo se entrega por un canal seguro únicamente su username/password, queue, vhost `/`, host y port. Cada grupo tiene una contraseña independiente.

El Job `k8s/jobs/rabbitmq-consumer-provisioner.yaml` asegura el exchange durable tipo topic `polls.events`, crea/actualiza usuario sin tags administrativos, queue durable y bindings, y reconcilia bindings obsoletos. Es idempotente; se puede volver a ejecutar para aplicar cambios. Los permisos RabbitMQ del consumidor son:

| Permiso | Patrón | Efecto |
| --- | --- | --- |
| `configure` | `^$` | No puede declarar/eliminar recursos. |
| `write` | `^$` | No puede publicar ni modificar bindings. |
| `read` | `^polls\\.consumer\\.grupo-a$` | Solo puede consumir su queue. |

La infraestructura crea los bindings autorizados. El consumidor no tiene permiso sobre el exchange ni puede elegir routing keys, crear queues, alterar bindings o administrar RabbitMQ. Su cliente AMQP debe consumir la queue asignada o declararla en modo pasivo.

Para agregar una integración, agrega su grupo/routing keys/`password_key` al ConfigMap y crea la key correspondiente en el Secret externo. Luego aplica el ConfigMap, elimina un Job de provisioning anterior si ya está `Complete`, aplica de nuevo el Job y espera `condition=complete`. Para revocar una integración, agrega el slug a `remove_groups` y vuelve a ejecutar el Job; se elimina solo si la queue está vacía y sin consumidores.

RabbitMQ es efímero: al recrearse el Pod se pierden usuarios externos, queues, bindings y mensajes encolados. Después de esperar RabbitMQ Ready, vuelve a ejecutar el mismo Job con el ConfigMap y Secret conservados. Así se recrean las cuentas con las mismas passwords y los grupos se reconectan sin rotarlas. Los mensajes ya encolados pueden perderse; el outbox no republica los eventos que ya confirmó.

Desde un namespace con conectividad al Service, los datos de conexión AMQP son:

```text
host: rabbitmq.grupo-encuestas.svc.cluster.local
port: 5672
exchange: polls.events (topic)
queue: polls.consumer.<grupo>
```

Los eventos usan `{event_id, event_type, occurred_at, payload}` y se entregan *at-least-once*, no exactly-once. Los consumidores deben deduplicar `event_id`. El acceso solo funciona desde donde el Service del clúster sea alcanzable y las políticas de red lo permitan. No almacenes credenciales en repositorios.

Cada Pod de Polls conserva sus workers de cierre, outbox y entregas. La concurrencia se coordina en PostgreSQL: locks de fila para votos/cierres, constraints e idempotencia existente, claims atómicos y leases. `message_deliveries.lease_token` y `outbox_events.lease_token` cercan las finalizaciones de claims vencidos. No se requiere un líder único ni un servicio adicional.

## Migraciones

El comando del contenedor es Uvicorn y no ejecuta Alembic. Compose ejecuta un servicio one-shot `migrate`; Kubernetes usa `k8s/jobs/migration.yaml`, con `parallelism: 1`, `completions: 1`, `backoffLimit: 3` y `activeDeadlineSeconds: 300`. La migración se debe completar antes de aplicar/actualizar el Deployment de Polls; no ejecutes deliberadamente el Job durante un rollout. No se agregó advisory lock porque el flujo mantiene un solo Job activo y no hay migraciones concurrentes por réplica.

Para una nueva migración:

1. Publica la imagen de la nueva release y actualiza el tag concreto en `k8s/jobs/migration.yaml` y `k8s/polls/deployment.yaml`.
2. Si Polls ya está instalado, fija temporalmente el HPA al número actual de réplicas y espera a que no haya Pods `Terminating`:

   ```bash
   POLLS_REPLICAS="$(kubectl -n "$NAMESPACE" get deployment polls -o jsonpath='{.spec.replicas}')"
   kubectl -n "$NAMESPACE" patch hpa polls --type merge \
     -p "{\"spec\":{\"minReplicas\":${POLLS_REPLICAS},\"maxReplicas\":${POLLS_REPLICAS}}}"
   kubectl -n "$NAMESPACE" get pods -l app=polls
   ```

3. Ejecuta `kubectl -n "$NAMESPACE" delete job polls-migration`.
4. Aplica otra vez el Job y espera su finalización.
5. Actualiza/aplica el Deployment de Polls; `Recreate` reemplaza las réplicas sin solapar versiones.
6. Restaura el rango del HPA a `minReplicas: 1`, `maxReplicas: 3`:

   ```bash
   kubectl -n "$NAMESPACE" patch hpa polls --type merge \
     -p '{"spec":{"minReplicas":1,"maxReplicas":3}}'
   ```

El borrado del Job no borra datos de PostgreSQL ni el PVC.

## Configuración y secretos

`k8s/polls/configmap.yaml` configura Messages con:

```text
MESSAGES_ENABLED=true
MESSAGES_BASE_URL=http://messages.servicios-base.svc.cluster.local:8000
```

También configura el exchange y los intervalos de worker/reintentos. `DATABASE_URL`, `RABBITMQ_URL`, `POSTGRES_PASSWORD` y `RABBITMQ_PASSWORD` se leen del Secret externo `polls-credentials`. No hay manifest de Secret ni credenciales reales en Git. Las contraseñas generadas con hex son seguras para interpolarse en las URLs.

En el computador local, genera credenciales y crea el Secret en el namespace asignado. Este ejemplo solo se documenta; no se ejecutó:

```bash
export NAMESPACE=grupo-encuestas
export POLLS_DB_PASSWORD="$(openssl rand -hex 24)"
export POLLS_RABBIT_PASSWORD="$(openssl rand -hex 24)"

kubectl -n "$NAMESPACE" create secret generic polls-credentials \
  --from-literal=POSTGRES_PASSWORD="$POLLS_DB_PASSWORD" \
  --from-literal=RABBITMQ_PASSWORD="$POLLS_RABBIT_PASSWORD" \
  --from-literal=DATABASE_URL="postgresql+asyncpg://polls:${POLLS_DB_PASSWORD}@postgres:5432/polls" \
  --from-literal=RABBITMQ_URL="amqp://polls:${POLLS_RABBIT_PASSWORD}@rabbitmq:5672/"

unset POLLS_DB_PASSWORD POLLS_RABBIT_PASSWORD
```

Si el paquete GHCR permanece privado, el namespace necesitará un `imagePullSecret` creado según las instrucciones del curso. No se incluyen tokens ni credenciales para ello. Si se hace público el paquete, los Pods podrán descargarlo sin ese Secret.

## Recursos y cuotas

Los límites/request por Pod son:

| Componente | Requests CPU / memoria | Limits CPU / memoria |
| --- | --- | --- |
| Polls | `100m` / `128Mi` | `250m` / `256Mi` |
| PostgreSQL | `100m` / `256Mi` | `250m` / `512Mi` |
| RabbitMQ | `100m` / `128Mi` | `250m` / `256Mi` |
| Un Job (migración o provisioning) | `50m` / `64Mi` | `100m` / `128Mi` |

Cálculo desde los recursos actuales de los manifests. PostgreSQL cuenta con la request/limit del container regular: su initContainer (`25m/32Mi`, `50m/64Mi`) es menor y no se suma al máximo efectivo del Pod.

| Escenario | Pods | Requests CPU | Requests memoria | Limits CPU | Limits memoria | Contra quota |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Polls=1 + PostgreSQL + RabbitMQ | 3 | `300m` | `512Mi` | `750m` | `1024Mi` | Cabe |
| Polls=3 + PostgreSQL + RabbitMQ | 5 | `500m` | `768Mi` | `1250m` | `1536Mi` | Cabe |
| Polls=3 + un Job | 6 | `550m` | `832Mi` | `1350m` | `1664Mi` | Cabe |
| Polls=3 + ambos Jobs | 7 | `600m` | `896Mi` | `1450m` | `1792Mi` | Cabe |
| 5 Polls transitorios + PostgreSQL + RabbitMQ | 7 | `700m` | `1024Mi` | `1750m` | `2048Mi` | Exactamente al límite de memoria |
| 5 Polls transitorios + PostgreSQL + RabbitMQ + un Job | 8 | `750m` | `1088Mi` | `1850m` | `2176Mi` | Rechazable: excede requests/limits de memoria |
| Peor caso: 5 Polls transitorios + PostgreSQL + RabbitMQ + ambos Jobs | 9 | `800m` | `1152Mi` | `1950m` | `2304Mi` | Rechazable: excede requests/limits de memoria |

Las quotas son `10 Pods`, requests `1 CPU/1Gi` y limits `2 CPU/2Gi`; todos los containers cumplen además el máximo individual del LimitRange (`1 CPU/1Gi`). El caso máximo normal con Polls=3 y ambos Jobs cabe. El peor escenario plausible durante scale-down/up con Pods aún `Terminating` y los dos Jobs excede la quota de memoria, aunque no la cantidad de Pods. Ejecuta un Job por vez; antes de Jobs o rollouts, estabiliza/congela el HPA, espera que los Pods `Terminating` desaparezcan y evita solapar tareas con el scale-up/down.

Polls usa `Recreate`: durante un cambio de imagen, Kubernetes termina las réplicas antiguas antes de crear las nuevas, a cambio de una interrupción breve de la API. RabbitMQ también usa `Recreate`: hay una interrupción AMQP/Management mientras se reemplaza su única réplica; así se evita servir tráfico desde dos brokers sin estado compartido. El outbox reintenta publicaciones y el provisioner debe recrear topología/usuarios después de cada reemplazo. El Job de migración se completa antes de iniciar el rollout de Polls.

`Recreate` de Polls evita solapar revisiones distintas, pero el HPA aún puede mantener Pods de un scale-down en `Terminating` mientras crea réplicas nuevas. El caso de cinco objetos Polls deja exactamente `1Gi` requests y `2Gi` limits de memoria antes de añadir cualquier Job. Para una operación segura, fija temporalmente `minReplicas` y `maxReplicas` del HPA al número de réplicas deseado, espera a que no haya Pods `Terminating`, ejecuta un solo Job, espera a que su Pod termine y luego restaura `minReplicas: 1`/`maxReplicas: 3`. No ejecutes deliberadamente Jobs durante un rollout ni durante una prueba de carga/scale.

El PVC consume exactamente `1Gi`; no se crean otros PVC. Los manifests declaran dos Deployments, un StatefulSet, un HPA, tres Services, tres ConfigMaps, dos Jobs y un PVC. Los casos que exceden quota en la tabla son posibles durante churn del HPA si coinciden Jobs; evita esa superposición siguiendo el procedimiento anterior.

El HPA usa `autoscaling/v2`, CPU promedio al `70%`, `minReplicas: 1` y `maxReplicas: 3`. Metrics Server está disponible en el clúster. Las cuotas informadas permiten estos valores; si cambian, requests/limits y máximo de réplicas están declarados en los manifests para ajustarse de forma explícita.

## CI y GHCR

- `.github/workflows/ci.yml` ejecuta pytest en pushes a `main` y pull requests.
- `.github/workflows/publish-image.yml` prueba antes de construir/publicar en pushes a `main` y en **pushes** de tags `vMAJOR.MINOR.PATCH`. Para tags valida que coincidan con `app/version.py`.
- Las imágenes de release reciben `v1.3.5`, `1.3.5` y `latest`; los pushes a `main` reciben tags `main` y `sha-<commit>`.
- Registry: `ghcr.io/tomascano-usm/inf326-microservicio-polls`.
- Publica con `GITHUB_TOKEN` y permisos `contents: read`, `packages: write`. El workflow de release SemVer existente se conserva.

El tag concreto de imagen de los manifests preparado para la próxima release es `1.3.5`; GHCR lo publicará al hacer push del tag SemVer `v1.3.5`. Hasta publicar esa release, la imagen `1.3.5` no está disponible en GHCR. Ejecutar manualmente `Publish GitHub Release` solo crea la GitHub Release y no dispara la publicación de imagen. Antes de desplegar se debe confirmar que la imagen está publicada. Para una release posterior, actualiza los manifests a su versión publicada. El paquete GHCR puede requerir hacerse público o configurar `imagePullSecret`. No hay CD, Argo CD ni GitOps.

## Procedimiento de despliegue futuro

Revisa y confirma primero el tag GHCR y que el Secret exista. No apliques todo el directorio en un único paso: las migraciones deben terminar antes de iniciar la versión nueva de Polls.

```bash
export NAMESPACE=grupo-encuestas

kubectl -n "$NAMESPACE" apply -f k8s/postgres/service.yaml
kubectl -n "$NAMESPACE" apply -f k8s/postgres/pvc.yaml
kubectl -n "$NAMESPACE" apply -f k8s/postgres/statefulset.yaml
kubectl -n "$NAMESPACE" apply -f k8s/rabbitmq/service.yaml
kubectl -n "$NAMESPACE" apply -f k8s/rabbitmq/configmap.yaml
kubectl -n "$NAMESPACE" apply -f k8s/rabbitmq/deployment.yaml
kubectl -n "$NAMESPACE" wait --for=condition=Ready pod -l app=postgres --timeout=180s
kubectl -n "$NAMESPACE" rollout status statefulset/postgres --timeout=180s
kubectl -n "$NAMESPACE" rollout status deployment/rabbitmq --timeout=180s

kubectl -n "$NAMESPACE" apply -f k8s/jobs/migration.yaml
kubectl -n "$NAMESPACE" wait --for=condition=complete job/polls-migration --timeout=360s

# Opcional: antes de ejecutar, configura los grupos y crea el Secret externo
# polls-rabbitmq-consumer-credentials con las passwords correspondientes.
kubectl -n "$NAMESPACE" apply -f k8s/rabbitmq/consumers-configmap.yaml
kubectl -n "$NAMESPACE" apply -f k8s/jobs/rabbitmq-consumer-provisioner.yaml
kubectl -n "$NAMESPACE" wait --for=condition=complete \
  job/rabbitmq-consumer-provisioner --timeout=300s

kubectl -n "$NAMESPACE" apply -f k8s/polls/configmap.yaml
kubectl -n "$NAMESPACE" apply -f k8s/polls/service.yaml
kubectl -n "$NAMESPACE" apply -f k8s/polls/deployment.yaml
kubectl -n "$NAMESPACE" apply -f k8s/polls/hpa.yaml
kubectl -n "$NAMESPACE" rollout status deployment/polls --timeout=180s
```

Inspección y evidencia:

```bash
kubectl -n "$NAMESPACE" get pods,deployments,statefulsets,services,hpa,pvc
kubectl -n "$NAMESPACE" get resourcequota,limitrange
kubectl -n "$NAMESPACE" top pods
kubectl -n "$NAMESPACE" get hpa -w
kubectl -n "$NAMESPACE" logs deployment/polls
kubectl -n "$NAMESPACE" describe hpa polls
kubectl -n "$NAMESPACE" port-forward service/polls 8004:8004
```

Con el port-forward activo, Swagger queda en `http://localhost:8004/docs`. Para la evidencia integrada, crea una encuesta usando IDs existentes de Users/Channels, verifica el mensaje de anuncio en el chat, emite votos, cierra la encuesta y verifica el mensaje de resultados. Para escalamiento, captura `get hpa`, `get pods` y `top pods` bajo carga y después del scale-down. Estos comandos son pasos futuros: no se ejecutaron durante la preparación.
