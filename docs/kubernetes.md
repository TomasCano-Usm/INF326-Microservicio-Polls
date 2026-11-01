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

El publicador RabbitMQ conecta de manera lazy al intentar publicar. Si el broker no está disponible, el evento permanece en `outbox_events` y se reintenta con el backoff existente. Las publicaciones usan exchange durable, mensajes persistentes y publisher confirms.

El outbox ofrece entrega *at-least-once*, no exactly-once. Una caída después de la confirmación del broker y antes de guardar `published_at` puede repetir un evento; el `event_id` estable permite deduplicación por consumidores.

RabbitMQ no utiliza PVC: la única reclamación de almacenamiento permitida se reserva para PostgreSQL. El exchange y los mensajes se declaran durables/persistentes, pero el almacenamiento efímero del broker significa que una recreación del Pod puede perder colas y mensajes ya confirmados. El outbox no vuelve a publicar eventos que ya marcó como confirmados. Por lo tanto, esta instalación académica no ofrece recuperación de eventos ante pérdida de datos de RabbitMQ; consumidores y evidencia deben considerar esa limitación.

Messages tampoco ofrece idempotencia en su contrato HTTP. Un POST aceptado remotamente cuya respuesta se pierde, o una caída del Pod antes de guardar el resultado, puede ocasionar mensajes duplicados. El token de lease de `message_deliveries` impide que un intento antiguo sobrescriba el estado de un claim posterior, pero no elimina esa ambigüedad externa.

## Persistencia y concurrencia

PostgreSQL corre como un StatefulSet de una réplica con el único PVC del namespace: `postgres-data`, `ReadWriteOnce`, `1Gi`. Se omite `storageClassName` para utilizar la clase por defecto `do-block-storage`. El Service interno `postgres` proporciona el DNS que utilizan Polls y el Job de migración.

PostgreSQL usa el UID/GID `70`, correspondiente al usuario `postgres` de `postgres:16-alpine`, y ejecuta como no-root con seccomp `RuntimeDefault`; el Pod y sus containers también mantienen `allowPrivilegeEscalation: false` y `capabilities.drop: [ALL]`. La imagen oficial deja su entrypoint como root por defecto para que pueda preparar directorios y hacer `chown` antes de bajar privilegios. En este Pod, el UID root combinado con `drop: [ALL]` deja sin `CAP_CHOWN` y `CAP_FOWNER`: el entrypoint no puede cambiar el dueño de `PGDATA` ni el modo de `/var/run/postgresql` cuando no es su dueño. `fsGroup: 70` por sí solo agrega el grupo suplementario y prepara permisos de grupo en el volumen, pero no cambia el UID del proceso.

El initContainer `prepare-pgdata` corre también como UID/GID `70`, sin capabilities añadidas, y usa el mismo PVC. Si encuentra un `PG_VERSION` válido, verifica que el directorio pertenezca al UID de `postgres` y lo deja intacto. Si no hay `PG_VERSION`, solo elimina con `rmdir` el directorio de `PGDATA` si está vacío —el placeholder vacío que pudo dejar un inicio fallido como root— y lo recrea como UID `70`; ante contenido no inicializado no vacío, falla sin borrar datos. No ejecuta `chown` ni necesita privilegios. Sus requests `25m/32Mi` y limits `50m/64Mi` son menores que los del container PostgreSQL, por lo que no aumentan los recursos efectivos del Pod.

El volumen `do-block-storage` es RWO y usa ext4 por defecto. El CSIDriver de DigitalOcean deja `fsGroupPolicy` sin especificar, cuyo valor predeterminado Kubernetes es `ReadWriteOnceWithFSType`; por tanto, kubelet aplica `fsGroup: 70` al volumen para este modo de acceso y filesystem. Esto hace escribible por el grupo `70` el directorio raíz del volumen, permitiendo al initContainer retirar únicamente el directorio vacío y crear el nuevo directorio propietario correcto. `fsGroupChangePolicy: OnRootMismatch` evita recorridos recursivos innecesarios en cada reinicio. Se conserva el claim `postgres-data`, su ruta de montaje y `PGDATA=/var/lib/postgresql/data/pgdata`; no se reemplaza ni se borra el PVC.

Los probes `startupProbe`, `livenessProbe` y `readinessProbe` siguen ejecutando `pg_isready -U polls -d polls` dentro del container PostgreSQL. El socket Unix permanece en `/var/run/postgresql`, propiedad del UID `70`, por lo que el probe conserva su comportamiento.

RabbitMQ corre como un Deployment de una réplica con `rabbitmq:4-management-alpine`. La imagen oficial crea al usuario `rabbitmq` con UID `100` y GID `101` (`adduser -u 100`, `addgroup -g 101` en su [Dockerfile Alpine](https://github.com/docker-library/rabbitmq/blob/master/Dockerfile-alpine.template)); la imagen descargada confirma esos IDs y no declara un `USER` predeterminado. Se fijan explícitamente en el `securityContext` junto con `runAsNonRoot: true`. Sin esta configuración, el proceso empieza como root y el [entrypoint oficial](https://github.com/docker-library/rabbitmq/blob/master/docker-entrypoint.sh) intenta ajustar propietarios bajo `/var/lib/rabbitmq` y cambiar a `rabbitmq` mediante `su-exec`. Esa transición llama `setgroups()` y falla con `capabilities.drop: [ALL]` (`Operation not permitted`) porque no dispone de `CAP_SETGID`. Al arrancar directamente como UID/GID `100:101`, se omite la transición root→rabbitmq y no se requieren capabilities. La imagen prepara `/var/lib/rabbitmq`, `/etc/rabbitmq` y `/var/log/rabbitmq` para que el usuario de servicio pueda inicializarlos y escribir en ellos sin PVC.

El contenedor declara `allowPrivilegeEscalation: false`, `seccompProfile.type: RuntimeDefault` y `capabilities.drop: [ALL]`, conforme a Pod Security `restricted:v1.36`; no usa privileged, hostPath ni host networking. El Service `ClusterIP` `rabbitmq` ofrece AMQP en `5672` y Management API en `15672`, ambos solo dentro del clúster; RabbitMQ no tiene PVC ni clustering.

RabbitMQ tiene `startupProbe` de hasta 180 segundos; liveness y readiness quedan habilitadas después de que `rabbitmq-diagnostics -q ping` responde. Se mantienen los recursos actuales (`100m/128Mi` requests, `250m/256Mi` limits): un smoke test local de `rabbitmq:4-management-alpine` bajo límite de `256Mi`, como UID/GID `100:101`, con todas las capabilities descartadas, arrancó correctamente en aproximadamente 47 segundos y las lecturas posteriores al inicio estuvieron entre `104.6Mi` y `108.4Mi`. Esta medida local no sustituye observar memoria y alarmas del broker en el clúster.

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

El comando del contenedor es Uvicorn y no ejecuta Alembic. Compose ejecuta un servicio one-shot `migrate`; Kubernetes usa `k8s/jobs/migration.yaml`, con `parallelism: 1` y `completions: 1`. La migración se debe completar antes de aplicar/actualizar el Deployment de Polls; no ejecutes deliberadamente el Job durante un rollout. No se agregó advisory lock porque el flujo mantiene un solo Job activo y no hay migraciones concurrentes por réplica.

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

Cálculo para los recursos configurados:

| Escenario | Requests CPU / memoria | Limits CPU / memoria |
| --- | --- | --- |
| 1 Polls + PostgreSQL + RabbitMQ | `300m` / `512Mi` | `750m` / `1024Mi` |
| 3 Polls + PostgreSQL + RabbitMQ | `500m` / `768Mi` | `1250m` / `1536Mi` |
| 3 Polls + PostgreSQL + RabbitMQ + Job | `550m` / `832Mi` | `1350m` / `1664Mi` |
| HPA scale-down/up overlap (5 Polls objects + PostgreSQL + RabbitMQ) | `700m` / `1024Mi` | `1750m` / `2048Mi` |
| HPA scale-down/up overlap plus Job | `750m` / `1088Mi` | `1850m` / `2176Mi` |

Un único Job de migración o provisioning cabe junto a las tres réplicas de Polls. Si se ejecuta un Job de cada tipo simultáneamente con tres Polls, el total sería `600m/896Mi` requests y `1450m/1792Mi` limits; aun cabe en cuota, pero se recomienda ejecutar un Job por vez. El Job activo añade un Pod: hasta seis Pods contando los tres Polls, PostgreSQL, RabbitMQ y el Job.

El Deployment usa estrategia `Recreate`: durante una actualización, Kubernetes termina las réplicas antiguas antes de crear las nuevas. Esto evita que Pods antiguos en `Terminating` se solapen con reemplazos, a cambio de una interrupción breve de la API. El Job se completa antes de iniciar el rollout.

Se eligió `Recreate` porque `maxSurge: 0` no da una cota suficiente: con tres réplicas antiguas terminando y tres nuevas activas, requests serían `800m/1152Mi` y limits `2000m/2304Mi` incluso sin Job, excediendo las cuotas de memoria. Con Job simultáneo llegarían a `850m/1216Mi` y `2100m/2432Mi`. El HPA también puede conservar Pods de un scale-down reciente en `Terminating`: un downscale de tres a uno seguido de scale-up puede mantener cinco objetos Polls temporalmente. Sin Job, ese pico queda exactamente en `1Gi` requests y `2Gi` limits de memoria; con Job excedería ambas cuotas. El pico HPA+Job serían ocho Pods en total, dentro del límite de diez, pero no cabría en las cuotas de memoria. Para nuevas migraciones, fija temporalmente `minReplicas` y `maxReplicas` del HPA al número actual de réplicas, espera a que no haya Pods `Terminating`, ejecuta y espera el Job, actualiza Polls con `Recreate` y restaura `minReplicas: 1`/`maxReplicas: 3`. No ejecutes deliberadamente migraciones durante un rollout ni durante una prueba de carga/scale.

El PVC consume exactamente `1Gi`; no se crean otros PVC. Los manifests declaran dos Deployments, un StatefulSet, un HPA, tres Services, dos ConfigMaps, dos Jobs y un PVC. Se ejecuta un Job por vez; sus Pods temporales y los escenarios HPA están contemplados en los cálculos anteriores, y todos cumplen las cuotas informadas.

El HPA usa `autoscaling/v2`, CPU promedio al `70%`, `minReplicas: 1` y `maxReplicas: 3`. Metrics Server está disponible en el clúster. Las cuotas informadas permiten estos valores; si cambian, requests/limits y máximo de réplicas están declarados en los manifests para ajustarse de forma explícita.

## CI y GHCR

- `.github/workflows/ci.yml` ejecuta pytest en pushes a `main` y pull requests.
- `.github/workflows/publish-image.yml` prueba antes de construir/publicar en pushes a `main` y en **pushes** de tags `vMAJOR.MINOR.PATCH`. Para tags valida que coincidan con `app/version.py`.
- Las imágenes de release reciben `v1.3.2`, `1.3.2` y `latest`; los pushes a `main` reciben tags `main` y `sha-<commit>`.
- Registry: `ghcr.io/tomascano-usm/inf326-microservicio-polls`.
- Publica con `GITHUB_TOKEN` y permisos `contents: read`, `packages: write`. El workflow de release SemVer existente se conserva.

El tag concreto de imagen de los manifests preparado para la próxima release es `1.3.2`; GHCR lo publicará al hacer push del tag SemVer `v1.3.2`. Hasta publicar esa release, la imagen `1.3.2` no está disponible en GHCR. Ejecutar manualmente `Publish GitHub Release` solo crea la GitHub Release y no dispara la publicación de imagen. Antes de desplegar se debe confirmar que la imagen está publicada. Para una release posterior, actualiza los manifests a su versión publicada. El paquete GHCR puede requerir hacerse público o configurar `imagePullSecret`. No hay CD, Argo CD ni GitOps.

## Procedimiento de despliegue futuro

Revisa y confirma primero el tag GHCR y que el Secret exista. No apliques todo el directorio en un único paso: las migraciones deben terminar antes de iniciar la versión nueva de Polls.

```bash
export NAMESPACE=grupo-encuestas

kubectl -n "$NAMESPACE" apply -f k8s/postgres/service.yaml
kubectl -n "$NAMESPACE" apply -f k8s/postgres/pvc.yaml
kubectl -n "$NAMESPACE" apply -f k8s/postgres/statefulset.yaml
kubectl -n "$NAMESPACE" apply -f k8s/rabbitmq/service.yaml
kubectl -n "$NAMESPACE" apply -f k8s/rabbitmq/deployment.yaml
kubectl -n "$NAMESPACE" wait --for=condition=Ready pod -l app=postgres --timeout=180s
kubectl -n "$NAMESPACE" rollout status statefulset/postgres --timeout=180s
kubectl -n "$NAMESPACE" rollout status deployment/rabbitmq --timeout=180s

# Opcional: antes de ejecutar, configura los grupos y crea el Secret externo
# polls-rabbitmq-consumer-credentials con las passwords correspondientes.
kubectl -n "$NAMESPACE" apply -f k8s/rabbitmq/consumers-configmap.yaml
kubectl -n "$NAMESPACE" apply -f k8s/jobs/rabbitmq-consumer-provisioner.yaml
kubectl -n "$NAMESPACE" wait --for=condition=complete \
  job/rabbitmq-consumer-provisioner --timeout=300s

kubectl -n "$NAMESPACE" apply -f k8s/jobs/migration.yaml
kubectl -n "$NAMESPACE" wait --for=condition=complete job/polls-migration --timeout=180s

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
