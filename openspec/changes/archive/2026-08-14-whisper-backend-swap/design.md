# Diseño técnico: `whisper-backend-swap`

Change name: `whisper-backend-swap`
Inputs: `proposal.md` (aprobado), `explore.md` (verificación en vivo 2026-08-13).
Alcance de este documento: **el CÓMO** de D-1 a D-4. No re-litiga decisiones ya cerradas (speaches-ai, `Systran/faster-whisper-large-v3` sin cuantizar, TTL desactivado, V1-V4 bloqueantes, plan de rollback).

Punto de diseño más caro, tal como lo marca la propuesta: **la matriz de configuración de speaches** (V1 ruta de caché, V2 centinela de TTL, V3 obligatoriedad de `model`). Este documento no puede resolver V1-V3 porque **la fase de diseño no tiene acceso a un contenedor vivo**. Lo que sí hace, y es su entregable principal, es:

1. Fijar el valor **best-known** de cada incógnita (con su fuente y su razonamiento), para que apply tenga un punto de partida concreto y no una casilla vacía.
2. Escribir el **procedimiento de verificación exacto** de cada una — comandos literales, salida esperada, y qué hacer si la salida no coincide — para que `sdd-apply` no tenga que reinventar el método.

> **Regla de la fase**: todo valor marcado `[V#]` en el YAML de abajo es *propuesto*, no *final*. `sdd-apply` DEBE ejecutar §6 antes de hacer commit del compose.

---

## 0. Decisiones de arquitectura de esta fase (ADR-style)

Cinco decisiones no obvias que este diseño agrega por encima de la propuesta.

### ADR-1 — `model` se manda SIEMPRE, explícito, sin condicionar a V3

**Decisión**: `transcribe-voice.sh` incluye `-F "model=Systran/faster-whisper-large-v3"` de forma incondicional.

**Rationale**: V3 pregunta "¿es obligatorio?". La respuesta correcta de diseño es **hacer que la pregunta deje de importar en runtime**. Si `model` es obligatorio, mandarlo es requisito. Si es opcional, mandarlo es inofensivo — y además *deseable*, porque el default del servidor es estado implícito que puede cambiar entre releases (el tag es un `rc`) y que no está bajo control del repo. Mandarlo explícito hace que el script sea **auto-descriptivo y determinista**: el modelo que se usa está escrito en el mismo archivo que hace la llamada, no inferido de una env var de otro servicio.

**Alternativa rechazada**: gatear el flag según lo que devuelva V3 (`if requerido then -F model`). Introduce dos rutas de código y un acoplamiento del script a un detalle interno del servidor, para ahorrar 60 bytes de request. Rechazado.

**Consecuencia**: V3 baja de "bloqueante que decide el diseño" a "verificación de confirmación". Sigue en el plan (§6.3) porque su resultado informa el mensaje de error y confirma el nombre exacto del campo, pero **ya no bloquea el diseño del script**.

**Acoplamiento nuevo introducido**: el id del modelo queda escrito en dos lugares (`PRELOAD_MODELS` en compose y el `-F model=` en el script). Se acepta conscientemente: son dos archivos del mismo repo, versionados juntos, y el desacople alternativo (pasar el id por env var desde compose) agrega una tercera variable de entorno para un valor que cambia una vez cada dos años. Ver ADR-5 para la mitigación barata.

### ADR-2 — `PRELOAD_MODELS` se escribe en forma de array JSON

**Decisión**: `PRELOAD_MODELS: '["Systran/faster-whisper-large-v3"]'`, no `PRELOAD_MODELS: Systran/faster-whisper-large-v3`.

**Rationale**: speaches configura con `pydantic-settings`. Para campos de tipo complejo (`list[str]`), pydantic-settings **parsea el valor de la env var como JSON**, no como string suelto ni como lista separada por comas. Un valor plano típicamente produce un `SettingsError` en el arranque — es decir, **el contenedor no levanta y el modo de falla es un crash-loop al boot**, no una degradación silenciosa. Es la incógnita de esta matriz con la falla más ruidosa, lo cual es bueno: se detecta en el primer `docker compose up`.

**Consecuencia para apply**: si el contenedor crashea al arranque con un error de settings, la primera hipótesis es esta línea, no la GPU ni la imagen. Verificación en §6.2.

### ADR-3 — `curl` dentro del contenedor es una suposición separada de "`/health` responde 200"

**Decisión**: tratar "el endpoint `/health` existe y devuelve 200" y "la imagen tiene `curl` instalado" como **dos hechos distintos**, y verificar el segundo antes de escribir el healthcheck.

**Rationale**: esto es exactamente la clase de falla de `TROUBLESHOOTING.md §3`. El explore verificó `/health` con `curl` **desde el host**, contra un puerto publicado (`-p 8000:8000`). Eso prueba que el endpoint responde; **no prueba que el binario `curl` exista dentro de la imagen**. El healthcheck de compose corre *dentro* del contenedor. Confundir ambas cosas es literalmente el incidente ya documentado, repetido con otra imagen.

**Consecuencia**: el healthcheck se escribe con `curl` (§1) porque es lo que pide la propuesta y lo esperable en una imagen basada en Ubuntu, pero apply DEBE correr la verificación V1b (§6.1) antes de dar por bueno el bloque, y tiene un fallback pre-escrito si `curl` no está.

### ADR-4 — El `service_healthy` de `hermes` no controla la disponibilidad de voz; solo controla el orden de arranque

**Decisión**: se mantiene `depends_on: whisper: { condition: service_healthy, required: false }` tal cual, y se sube `start_period`.

**Rationale**: `hermes` **no cachea ningún estado de disponibilidad de whisper**. No hay ni un probe al arranque ni un flag persistido: la única detección viva es el `curl` de `transcribe-voice.sh`, **por request**. Por lo tanto, aunque `hermes` arranque antes de que whisper esté listo, no puede "creer falsamente que la voz no está disponible" de forma persistente — a lo sumo una nota de voz enviada durante la ventana de descarga devuelve `whisper_no_disponible`, y la siguiente ya funciona. **El sistema se auto-cura sin reinicio.** Detalle completo en §4.

**Consecuencia**: el riesgo real del primer arranque no es "voz rota", es "arranque de hermes demorado" mientras compose espera la condición. Se mitiga con secuencia de despliegue (§4.2), no con cambios de arquitectura.

### ADR-5 — Un solo comentario ancla en el compose como fuente de verdad del id del modelo

**Decisión**: anotar en `docker-compose.yml`, junto a `PRELOAD_MODELS`, que el mismo id vive en `ops/transcribe-voice.sh`.

**Rationale**: mitigación de costo cero para el acoplamiento aceptado en ADR-1. No hay mecanismo de sincronización porque no hace falta uno: hay exactamente dos sitios, en el mismo repo, y un desalineo se manifiesta de inmediato (speaches cargaría un segundo modelo bajo demanda, o fallaría el request) — no es una falla silenciosa de larga vida.

---

## 1. `docker-compose.yml` — servicio `whisper`, config final propuesta

Reemplaza íntegro el bloque de las líneas 45-74 actuales.

```yaml
  # F0.2 non-blocking: this service is `required: false` on hermes' depends_on so an
  # unconfigured GPU degrades to "Fase 1 sin voz" instead of blocking boot.
  # If nvidia-container-toolkit is unconfirmed, do not run `docker compose up whisper`
  # yet; set WHISPER_OPTIONAL=1 in ops/.env.ops and document the degraded state in README.
  whisper:
    image: ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cuda-12.6.3
    container_name: whisper            # sin cambios: referenciado por nombre en toda la ops
    restart: unless-stopped
    environment:
      TZ: America/Lima
      WHISPER__INFERENCE_DEVICE: cuda
      WHISPER__COMPUTE_TYPE: float16   # large-v3 SIN cuantizar, misma ruta de precision que hoy
      # Array JSON obligatorio: pydantic-settings parsea list[str] como JSON (ver design ADR-2).
      # Este id tambien vive en ops/transcribe-voice.sh (-F model=...). Cambiar los dos juntos.
      PRELOAD_MODELS: '["Systran/faster-whisper-large-v3"]'
      STT_MODEL_TTL: "-1"              # [V2] -1 = nunca descargar. Reemplaza MODEL_IDLE_TIMEOUT=600.
    volumes:
      - whisper-cache:/home/ubuntu/.cache/huggingface/hub   # [V1] ruta de cache HF de la imagen
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]      # unica GPU passthrough del stack
    healthcheck:
      # [V1b] Verificado en vivo: GET /health -> 200 {"message":"OK"}.
      # A diferencia de la imagen onerahmet (TROUBLESHOOTING §3), esta imagen trae curl.
      test: ["CMD-SHELL", "curl -fsS http://localhost:8000/health >/dev/null || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 1800s              # primer arranque: descarga completa de large-v3 (~3GB) + carga en VRAM
    logging: *log
    networks: [asistente]
    # sin `ports:` - solo alcanzable desde la red interna del compose
```

### Justificación campo por campo

| Campo | Valor | Estado | Nota |
|---|---|---|---|
| `image` | `ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cuda-12.6.3` | **Confirmado** (explore, corrido en vivo) | Tag pinneado, no `latest` |
| `WHISPER__INFERENCE_DEVICE` | `cuda` | Confirmado (esquema doble guion bajo) | — |
| `WHISPER__COMPUTE_TYPE` | `float16` | Confirmado | Paridad exacta con `ASR_COMPUTE_TYPE` actual |
| `PRELOAD_MODELS` | `'["Systran/faster-whisper-large-v3"]'` | **id confirmado / formato `[V2b]`** | ADR-2. Falla ruidosa si el formato es incorrecto |
| `STT_MODEL_TTL` | `"-1"` | **`[V2]` propuesto** | Ver §2 |
| `volumes` | `whisper-cache:/home/ubuntu/.cache/huggingface/hub` | **`[V1]` propuesto** | Ver §2. Falla **silenciosa** si es incorrecto |
| `healthcheck` | `curl -fsS .../health` | endpoint confirmado / `curl` interno `[V1b]` | ADR-3 |
| `start_period` | `1800s` (de 300s) | Decisión de diseño | Ver §4.1 |
| `deploy...devices` | sin cambios | — | — |
| `container_name`, `TZ`, `restart`, `logging`, `networks`, sin `ports:` | sin cambios | — | — |

**Nota sobre el volumen `whisper-cache`**: se **reutiliza el mismo nombre de volumen** (`whisper-cache`, declarado en el top-level `volumes:`) montado en una ruta distinta. El formato de caché no es compatible entre imágenes, así que el contenido viejo queda como basura inerte dentro del volumen — no rompe nada, pero **no cumple** el punto 3 del plan de rollback de la propuesta ("conservar la caché vieja intacta para que el rollback no re-descargue"). Ver §5.2: hay que decidir entre volumen nuevo o volumen reutilizado, y este diseño recomienda **volumen nuevo**.

---

## 2. La matriz de configuración de speaches: valores best-known + qué verificar

Tres incógnitas, ordenadas por **cuán ruidoso es el modo de falla** (de más silencioso a más ruidoso). Esto importa: lo silencioso es lo que hay que verificar con más disciplina, porque no se va a notar solo.

### V1 — Ruta de caché de HuggingFace (falla **silenciosa**, la más peligrosa)

- **Valor propuesto**: `/home/ubuntu/.cache/huggingface/hub`
- **Fuente**: convención de la imagen speaches, que corre como usuario no-root `ubuntu` (`HOME=/home/ubuntu`), y el compose de referencia publicado por el proyecto monta el caché HF en esa ruta. `huggingface_hub` resuelve `HF_HOME` → `$HOME/.cache/huggingface`, y los snapshots de modelos van a su subdirectorio `hub/`.
- **Modo de falla si es incorrecto**: el servicio **funciona perfectamente**. Descarga `large-v3` a una ruta efímera del contenedor, transcribe bien, y solo se nota cuando alguien hace `docker compose down && up` meses después y el arranque tarda 15 minutos otra vez. Es la incógnita que menos avisa y por eso la de verificación más importante.
- **Alternativa de blindaje (recomendada)**: fijar `HF_HOME=/cache` explícitamente en el `environment` y montar `whisper-cache:/cache`. Esto **elimina la dependencia de la convención interna de la imagen** (usuario, `HOME`, ruta por defecto) y la reemplaza por una ruta que el repo controla. Costo: una env var más. Requiere confirmar que el proceso tiene permisos de escritura en `/cache` (el volumen se crea root-owned por defecto; si el proceso corre como `ubuntu`, puede fallar el primer write). **Decisión de diseño**: preferir la ruta convencional verificada (más simple, sin problema de permisos); usar `HF_HOME` solo si V1 revela que la ruta real es rara o cambia entre tags.

### V2 — Centinela de `STT_MODEL_TTL` (falla **semi-silenciosa**)

- **Valor propuesto**: `-1`
- **Fuente**: speaches documenta `STT_MODEL_TTL` como segundos hasta descargar el modelo tras el último uso, con **`-1` = nunca descargar** y **`0` = descargar inmediatamente tras cada request**. El campo está validado con un límite inferior `>= -1`, lo cual es coherente con `-1` como centinela y descarta que sea un valor arbitrario.
- **Por qué NO usar "un número grande" como primera opción**: `STT_MODEL_TTL: "31536000"` (un año) parece más seguro, pero es peor diseño: expresa "descargalo en un año" cuando la intención es "nunca". Si el centinela existe, usar el número mágico oculta la intención y sobrevive mal a una lectura futura. **Si V2 confirma que `-1` no está soportado**, entonces sí: fallback a `"31536000"` con un comentario explícito de que es un stand-in de "nunca".
- **Modo de falla si es incorrecto**: dos variantes. (a) El valor es rechazado por validación → crash al arranque, ruidoso, se detecta enseguida. (b) El valor es aceptado pero interpretado como "0 segundos" o similar → el modelo se descarga tras cada request y **la latencia empeora respecto de hoy**, que es exactamente el problema que este change vino a resolver. La variante (b) es la razón por la que V2 exige verificación de *comportamiento* (`/api/ps` tras 10+ min), no solo de arranque.

### V3 — ¿`model` es obligatorio en el multipart? (**neutralizada por diseño**)

- **Resuelta por ADR-1**: el script manda `model` siempre. El resultado de V3 no cambia el código.
- **Se sigue verificando** para: (a) confirmar el nombre exacto del campo (`model`, no `model_id`), (b) confirmar que el id que mandamos es aceptado tal cual, (c) documentar el comportamiento real en el spec.
- **Modo de falla si el campo estuviera mal nombrado**: HTTP 422 de FastAPI → `curl -f` falla → el script devuelve `whisper_no_disponible`. **Ruidoso y con degradación elegante ya cubierta** — el peor caso es "sin voz", nunca una transcripción incorrecta silenciosa.

### V2b — Formato de `PRELOAD_MODELS` (falla **ruidosa**, ver ADR-2)

Se lista aparte porque no estaba en las V originales de la propuesta pero es parte de la misma matriz. Crash-loop al arranque si el formato es incorrecto. Verificación en §6.2.

---

## 3. `docker-compose.yml` — servicio `hermes` (D-2)

Cambio de una línea:

```diff
     environment:
       TZ: America/Lima                        # D4 - sole source of "7am"
       VIDA_DB: /opt/data/data/vida.db
-      WHISPER_URL: http://whisper:9000
+      WHISPER_URL: http://whisper:8000
```

### Por qué esta línea es el switch real

`transcribe-voice.sh` corre **dentro del contenedor `hermes`** (montado vía `./ops:/opt/data/ops:ro`). Su default (`WHISPER_URL="${WHISPER_URL:-http://whisper:9000}"`) solo aplica si la variable **no** está en el entorno del proceso. Pero compose la inyecta siempre. Por lo tanto:

- El default del script es **código muerto en producción**. Nunca se evalúa mientras esta línea exista.
- Si se actualiza el script y no el compose, el resultado es un `connection refused` contra `whisper:9000` en **todas** las notas de voz — y el diff del script se ve perfecto, lo que hace el diagnóstico confuso.

**Decisión de diseño**: se actualizan **ambos** (compose y default del script), y se acepta la duplicación como defensa en profundidad. La razón de mantener el default en el script: permite ejecutarlo a mano fuera del contenedor durante debugging (`docker compose exec hermes /opt/data/ops/transcribe-voice.sh ...` funciona con el env inyectado; correrlo desde el host con la URL correcta requiere el default o un override explícito).

**Regla de orden para apply**: compose y script van en el **mismo commit**. Nunca separados — un estado intermedio con solo uno de los dos rompe la voz.

---

## 3.5. `ops/transcribe-voice.sh` — diff exacto (D-3)

Cuatro cambios. **Ninguno toca el parseo de la respuesta ni el contrato `ok/error`.**

### (a) Default de `WHISPER_URL` (línea 25)

```diff
-WHISPER_URL="${WHISPER_URL:-http://whisper:9000}"
+WHISPER_URL="${WHISPER_URL:-http://whisper:8000}"
```

Defensa en profundidad; el valor efectivo lo inyecta compose (§3).

### (b) Id del modelo como constante local (nueva línea, junto a `ACTION`)

```diff
 AUDIO_FILE="${1:-}"
 ACTION="asr.transcribe"
+# Debe coincidir con PRELOAD_MODELS en docker-compose.yml (servicio whisper).
+WHISPER_MODEL="${WHISPER_MODEL:-Systran/faster-whisper-large-v3}"
```

Se expone como env var con default para poder probar otro modelo sin editar el script, pero **no se configura desde compose**: el default es la fuente de verdad operativa (ADR-1/ADR-5).

### (c) La llamada curl (líneas 44-48)

```diff
-RESPUESTA="$(curl -fsS --max-time 30 \
-  -F "audio_file=@${AUDIO_FILE}" \
-  "${WHISPER_URL}/asr?output=json" 2>/dev/null)" || {
-  fail "whisper_no_disponible" "no se pudo contactar ${WHISPER_URL}/asr (servicio caido, timeout, o F0.2/whisper aun no desplegado -- ver ops/verify-gpu.sh)"
-}
+RESPUESTA="$(curl -fsS --max-time 30 \
+  -F "file=@${AUDIO_FILE}" \
+  -F "model=${WHISPER_MODEL}" \
+  "${WHISPER_URL}/v1/audio/transcriptions" 2>/dev/null)" || {
+  fail "whisper_no_disponible" "no se pudo contactar ${WHISPER_URL}/v1/audio/transcriptions (servicio caido, timeout, o F0.2/whisper aun no desplegado -- ver ops/verify-gpu.sh)"
+}
```

Tres cambios en una sola llamada: campo multipart `audio_file` → **`file`**, ruta `/asr?output=json` → **`/v1/audio/transcriptions`** (el `?output=json` desaparece: el endpoint OpenAI ya devuelve JSON por defecto, `response_format=json`), y el nuevo `-F model=` incondicional (ADR-1).

`--max-time 30` **se mantiene**. Con el modelo residente (`PRELOAD_MODELS` + `STT_MODEL_TTL=-1`) ninguna transcripción de una nota de voz corta debería acercarse a ese techo; si empieza a haber timeouts, es señal de que el TTL no está funcionando y hay que volver a §6.2b, no de que haya que subir el límite. **Tratar `--max-time 30` como un canario, no como un parámetro a tunear.**

### (d) Prosa: cabecera (líneas 2, 8)

```diff
-# Transcribe a Telegram voice note via the whisper sidecar's POST /asr endpoint.
+# Transcribe a Telegram voice note via the whisper sidecar's OpenAI-compatible
+# POST /v1/audio/transcriptions endpoint (speaches-ai/speaches backend).
```

```diff
-# skills/entrada-voz/SKILL.md for the full rationale. Both alternatives land on this
-# same POST /asr contract (design §15), so nothing here changes if a native hook is
-# confirmed later.
+# skills/entrada-voz/SKILL.md for the full rationale. Both alternatives land on this
+# same POST /v1/audio/transcriptions contract (design §15), so nothing here changes if
+# a native hook is confirmed later.
```

### Lo que explícitamente NO cambia

- El bloque `python3` de parseo (líneas 50-66): `payload.get("text")` sigue siendo correcto — el OpenAPI en vivo declara `Transcription.required: ["text"]`.
- Los `codigo` de error: `argumento_faltante`, `archivo_no_encontrado`, `curl_no_disponible`, `python3_no_disponible`, `whisper_no_disponible`, `respuesta_invalida`, `transcripcion_vacia`. **Ninguno se agrega, se quita ni se renombra** — `skills/entrada-voz/SKILL.md` los consume.
- La forma del JSON de salida, los códigos de salida (0/1), y `set -u`.

**Consecuencia**: el diff funcional real del script son **5 líneas**. Todo lo demás es prosa.

---

## 4. Secuenciación de arranque

### 4.1 Qué pasa en el primer boot, paso a paso

1. `docker compose up -d` crea `whisper`. La imagen (~8.6GB) puede necesitar pull.
2. speaches arranca, lee `PRELOAD_MODELS` y **descarga `Systran/faster-whisper-large-v3` desde HuggingFace** (varios GB) al volumen de caché. Esto ocurre **antes** de que el servidor esté listo para servir, o en paralelo según cómo el proyecto implemente el preload — en ambos casos, el modelo no está en VRAM hasta que termina.
3. El healthcheck corre cada `interval: 60s`. Durante `start_period`, **los fallos no cuentan para `retries`** y el contenedor permanece en estado `starting` (no `unhealthy`).
4. Cuando el preload termina y `/health` devuelve 200, el contenedor pasa a `healthy`.
5. `hermes`, que tiene `depends_on: whisper: {condition: service_healthy}`, arranca recién ahí.

**Por qué `start_period: 1800s` y no 300s**: los 300s actuales fueron dimensionados para la imagen `onerahmet` con una caché ya caliente. Una descarga fría de large-v3 desde HF, sujeta al ancho de banda del host (dependencia explícita en la propuesta §9), puede superar los 5 minutos con facilidad. Si `start_period` expira mientras la descarga sigue, los healthchecks empiezan a contar: 3 fallos × 60s → el contenedor se marca `unhealthy`, `restart: unless-stopped` no aplica (unhealthy no reinicia por sí solo en compose), pero compose deja de esperar la condición y arranca `hermes` con una advertencia. 1800s cubre el peor caso con margen y **no tiene costo en régimen**: en arranques posteriores, con caché caliente, el contenedor pasa a `healthy` en el primer check y `start_period` termina ahí, no consume esos 30 minutos.

### 4.2 Por qué esto NO deja a hermes "creyendo que no hay voz" (ADR-4)

La preocupación natural es: si `hermes` arranca antes de que whisper esté listo, ¿queda la voz deshabilitada hasta el próximo reinicio? **No**, por dos razones estructurales:

1. **`hermes` no tiene estado de disponibilidad de whisper.** No hay probe al arranque, no hay flag en la DB, no hay feature toggle. La única comprobación es el `curl` de `transcribe-voice.sh`, que se ejecuta **una vez por nota de voz**.
2. **La degradación es por-request y auto-curativa.** Una nota de voz durante la ventana de descarga → `curl` falla → exit 1 con `codigo: whisper_no_disponible` → la skill le pide al usuario que escriba el mensaje. La siguiente nota de voz, ya con whisper `healthy`, funciona normal. Sin reinicio, sin intervención.

Es decir: **`required: false` + `service_healthy` es una optimización de orden de arranque, no un gate de funcionalidad.** El peor caso de un primer boot lento es "las notas de voz de los primeros N minutos caen en el camino degradado", que es exactamente el comportamiento ya especificado y probado en Fase 1.

### 4.3 Interacción `PRELOAD_MODELS` × `STT_MODEL_TTL=-1`

Los dos parámetros cubren mitades complementarias del ciclo de vida del modelo, y **hacen falta los dos**:

- `PRELOAD_MODELS` resuelve el **arranque**: el modelo está en VRAM antes del primer request. Sin esto, `/api/ps` devuelve `{"models":[]}` al inicio (confirmado en vivo) y la primera nota de voz paga la carga completa.
- `STT_MODEL_TTL=-1` resuelve el **régimen**: el modelo nunca se descarga por inactividad. Sin esto, `PRELOAD_MODELS` solo mueve el problema — el modelo se carga al arranque y se descarga a los 300s del default, con lo cual la primera nota de voz real (que llega horas después) paga la recarga igual.

**Uno sin el otro no sirve.** Esta es la razón de fondo por la que V2 es bloqueante: si `-1` no funciona como se espera, `PRELOAD_MODELS` queda neutralizado y el change no entrega su beneficio principal.

**Consecuencia operativa aceptada** (decisión explícita del usuario en la propuesta): ~3-4GB de VRAM ocupados de forma permanente sobre 48GB disponibles, sin otro consumidor de GPU en el stack.

### 4.4 Recomendación de despliegue para el primer boot

Para evitar que la descarga inicial bloquee el arranque de `hermes`, apply debe desplegar en dos tiempos:

```sh
# 1. Levantar solo whisper y dejar que descargue/cargue el modelo
docker compose up -d whisper
docker compose logs -f whisper          # seguir la descarga
docker inspect --format '{{.State.Health.Status}}' whisper   # esperar a "healthy"

# 2. Recién entonces recrear hermes con el WHISPER_URL nuevo
docker compose up -d hermes
```

En arranques posteriores (caché caliente) `docker compose up -d` de una sola vez es suficiente.

---

## 5. Mecánica de rollback

### 5.1 Confirmado: revert limpio de un solo commit

El plan de la propuesta se sostiene. Los cambios funcionales viven en exactamente **dos archivos** (`docker-compose.yml`, `ops/transcribe-voice.sh`); el resto (D-4) es prosa. No hay migración de esquema, ni cambio de datos, ni artefacto generado, ni estado externo mutado. `git revert <sha>` + `docker compose up -d whisper hermes` restaura el estado anterior íntegro.

Se preserva todo lo que hace barato el revert: mismo nombre de servicio, mismo `container_name`, misma forma de respuesta JSON con `text`, mismo contrato `ok/error` hacia la skill.

**Requisito para que esto se cumpla**: los cambios de D-1, D-2 y D-3 van en **un único commit**. Si apply reparte compose y script en commits distintos, el revert deja de ser atómico y aparece la ventana de inconsistencia de §3. Los cambios de prosa (D-4) pueden ir en un commit separado sin riesgo.

### 5.2 Lo que el diseño descubre y complica el punto 3 del rollback

La propuesta dice: *"si se creó un volumen nuevo, el `whisper-cache` viejo puede conservarse intacto durante la transición para que el rollback no vuelva a descargar el modelo."* Ese beneficio **solo existe si se crea un volumen nuevo**. La config de §1 tal como está escrita **reutiliza `whisper-cache`** con otra ruta de montaje, y entonces:

- El contenido viejo (formato onerahmet, bajo `/root/.cache`) sobrevive físicamente dentro del volumen pero **no se monta** en la ruta que speaches usa. No se corrompe, pero tampoco se aprovecha.
- Un rollback vuelve a montar `whisper-cache:/root/.cache` y **sí recupera** la caché vieja intacta. El beneficio se cumple por accidente.
- Pero cada swap de ida y vuelta acumula un árbol de caché muerto dentro del mismo volumen, sin que nadie lo limpie.

**Recomendación de diseño**: declarar un volumen nuevo con nombre distinto:

```yaml
volumes:
  whisper-cache:        # legacy (imagen onerahmet) - conservar hasta validar el swap
  speaches-cache:       # nuevo backend
```

...y montar `speaches-cache:/home/ubuntu/.cache/huggingface/hub` en el servicio. Ventajas: separación limpia por backend, rollback con caché caliente garantizado, y una limpieza explícita (`docker volume rm asistente-personal_whisper-cache`) como paso final una vez que el swap se declare estable. Coste: una línea de YAML.

**`sdd-tasks` debe elegir explícitamente entre las dos opciones**; este diseño recomienda `speaches-cache`.

### 5.3 Punto de no retorno

No hay ninguno. El escenario más degradado (whisper no levanta, o levanta pero transcribe mal) termina en `codigo: whisper_no_disponible` y la skill pidiendo texto escrito. **Sin pérdida de mensajes, sin pérdida de datos, sin corrupción de estado.**

---

## 6. Plan de verificación para `sdd-apply`

Comandos literales. Se ejecutan **antes** del commit final del compose, contra un contenedor lanzado a mano — igual que hizo el explore.

### Setup común

```sh
docker run -d --rm --name speaches-probe --gpus all -p 8000:8000 \
  -e WHISPER__INFERENCE_DEVICE=cuda \
  -e WHISPER__COMPUTE_TYPE=float16 \
  -e PRELOAD_MODELS='["Systran/faster-whisper-large-v3"]' \
  -e STT_MODEL_TTL=-1 \
  ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cuda-12.6.3

docker logs -f speaches-probe          # esperar a que termine la descarga/preload
curl -fsS http://localhost:8000/health # esperado: {"message":"OK"}
```

Si este `docker run` **crashea al arranque**, el sospechoso #1 es el formato de `PRELOAD_MODELS` (ADR-2) y el #2 el valor de `STT_MODEL_TTL` (§6.2b). Los logs nombran el campo que falló.

### 6.1 V1 — Ruta real de la caché HF

```sh
# a) Donde escribio realmente los snapshots del modelo
docker exec speaches-probe sh -c 'find / -type d -name "models--Systran--faster-whisper-large-v3" 2>/dev/null'

# b) Contexto: usuario, HOME, y variables HF efectivas del proceso
docker exec speaches-probe sh -c 'id; echo "HOME=$HOME"; env | grep -i -E "^(HF_|HUGGINGFACE|XDG_CACHE)"'
```

**Esperado**: la ruta (a) termina en `.../huggingface/hub/models--Systran--faster-whisper-large-v3`. El prefijo antes de `hub/` es el valor que va en el `volumes:` del compose.
**Si no coincide** con `/home/ubuntu/.cache/huggingface/hub`: actualizar el montaje a la ruta real hallada, o aplicar el blindaje `HF_HOME` de §2/V1 (verificando permisos de escritura).

### 6.1b V1b — ¿La imagen trae `curl`? (ADR-3)

```sh
docker exec speaches-probe sh -c 'command -v curl || echo NO-CURL'
docker exec speaches-probe sh -c 'curl -fsS http://localhost:8000/health'   # el healthcheck real, desde adentro
```

**Esperado**: ruta a `curl` + `{"message":"OK"}`. Esto, y no la prueba desde el host, es lo que valida el healthcheck de §1.
**Si devuelve `NO-CURL`**, probar en orden y usar el primero que funcione:

```sh
docker exec speaches-probe sh -c 'command -v wget'
docker exec speaches-probe sh -c 'command -v python3'
```

Fallbacks pre-escritos para el bloque `healthcheck.test`:

```yaml
# fallback A - wget
test: ["CMD-SHELL", "wget -qO- http://localhost:8000/health >/dev/null || exit 1"]
# fallback B - python3 (mismo patron que TROUBLESHOOTING §3, ahora justificado y no asumido)
test: ["CMD-SHELL", "python3 -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=5).status==200 else 1)\""]
```

### 6.2 V2b — Formato de `PRELOAD_MODELS` y modelo efectivamente cargado

```sh
curl -fsS http://localhost:8000/api/ps
```

**Esperado**: `Systran/faster-whisper-large-v3` presente en `models`, **sin haber hecho ningún request de transcripción previo**. El explore confirmó que sin preload la respuesta es `{"models":[]}`, así que este check distingue inequívocamente "preload funcionó" de "preload fue ignorado".
**Si sale `{"models":[]}` pero el contenedor arrancó bien**: el array JSON fue aceptado pero el preload no se disparó → revisar logs de arranque y probar la variante de string plano antes de descartar ADR-2.

### 6.2b V2 — El TTL realmente significa "nunca descargar"

Este es el único check que **requiere esperar**. Es también el que valida la mitad del beneficio del change (§4.3).

```sh
# t=0: confirmar cargado
curl -fsS http://localhost:8000/api/ps

# Esperar >10 minutos SIN hacer ningun request (el default es 300s; 600s lo supera con margen)
sleep 660

# t=11min: debe seguir cargado
curl -fsS http://localhost:8000/api/ps
```

**Esperado**: el modelo aparece en **ambas** salidas.
**Si desapareció en la segunda**: `-1` no funciona como centinela → cambiar a `STT_MODEL_TTL: "31536000"` con comentario explícito, relanzar el probe y **repetir esta verificación completa**. No dar por bueno el valor grande sin volver a esperar los 11 minutos.

### 6.3 V3 — ¿`model` es obligatorio? (confirmación, no bloqueante — ADR-1)

Con un archivo de audio corto real a mano (`/tmp/probe.ogg`, ideal: una nota de voz de Telegram exportada):

```sh
# (a) CON model - esta es la forma que el script va a usar SIEMPRE
curl -sS -o /tmp/con-model.json -w '%{http_code}\n' \
  -F "file=@/tmp/probe.ogg" \
  -F "model=Systran/faster-whisper-large-v3" \
  http://localhost:8000/v1/audio/transcriptions
cat /tmp/con-model.json

# (b) SIN model - solo para documentar si es opcional
curl -sS -o /tmp/sin-model.json -w '%{http_code}\n' \
  -F "file=@/tmp/probe.ogg" \
  http://localhost:8000/v1/audio/transcriptions
cat /tmp/sin-model.json
```

**Esperado (a)**: HTTP 200 y un JSON con `text` en el nivel superior. **Este es el check bloqueante real** — si (a) falla, el script no funciona.
**Esperado (b)**: 200 (campo opcional) o 422 (obligatorio). **Cualquiera de los dos es aceptable** y no cambia el código; se registra el resultado en el spec/tasks como hecho documentado.
**Además**: verificar que la respuesta de (a) tenga `text` no vacío — es el campo del que depende todo el contrato `ok/error` (el OpenAPI en vivo ya lo declara `required`, esto lo confirma en la práctica).

### Teardown

```sh
docker stop speaches-probe    # --rm limpia el contenedor
```

### 6.4 Verificaciones post-despliegue (con el stack real arriba)

```sh
# Salud y modelo residente en el servicio real
docker inspect --format '{{.State.Health.Status}}' whisper
docker compose exec whisper curl -fsS http://localhost:8000/api/ps

# hermes ve el puerto correcto
docker compose exec hermes printenv WHISPER_URL      # esperado: http://whisper:8000

# Degradacion elegante intacta (criterio de exito de la propuesta)
docker compose stop whisper
docker compose exec hermes /opt/data/ops/transcribe-voice.sh /opt/data/ops/<audio-de-prueba>
#   esperado: exit 1 + {"ok": false, ..., "codigo": "whisper_no_disponible"}
docker compose start whisper

# Persistencia de cache (sin re-descarga)
docker compose down && docker compose up -d whisper
docker compose logs whisper | grep -i -E "download|fetch"   # esperado: sin descarga de large-v3
#   y el contenedor debe llegar a healthy en ~1 check, no en 15 minutos
```

---

## 7. ¿Cómo sabemos que ESTO REALMENTE FUNCIONA? — puerta de aceptación final

**V1-V3 y §6.4 son verificaciones automatizables de configuración. No son la prueba de que el sistema funciona.** Prueban que el contenedor está sano, que el modelo está residente y que el endpoint responde. Ninguna de ellas ejercita la ruta real: Telegram → gateway de `hermes` → skill `entrada-voz` → `transcribe-voice.sh` → speaches → texto → respuesta al usuario.

### La puerta de aceptación es manual y la ejecuta el usuario

**Secuencia**: `sdd-apply` → `sdd-verify` → levantar el stack → **el usuario manda una nota de voz real desde el Telegram de su teléfono**.

Nada se declara terminado antes de ese paso. Es explícitamente distinto de V1-V3 y no se puede sustituir por ellos.

**Criterios de la puerta (V4):**

1. La nota de voz **se transcribe**, y el asistente responde como corresponde al contenido — no con el fallback de "escribime el mensaje".
2. El texto transcripto es **equivalente al que producía el backend anterior** (sin regresión de precisión perceptible). Ideal: la misma frase que el usuario ya probó con el backend viejo.
3. La respuesta llega **sin la pausa larga de recarga en frío**. Este es el objetivo del change; si sigue lenta, el change no cumplió aunque toda la config esté verde.
4. **Segunda nota de voz tras >10 minutos de inactividad**: debe responder igual de rápido que la primera. Esta es la validación *end-to-end* del TTL desactivado — §6.2b lo prueba a nivel de API, este paso lo prueba a nivel de experiencia real.

**Si (1) o (2) fallan** → rollback por §5 y reabrir el diseño.
**Si (3) o (4) fallan pero (1) y (2) pasan** → el swap es funcionalmente correcto pero no entregó el beneficio; investigar `/api/ps` y logs antes de decidir revert. No es una emergencia: la voz funciona.

**Instrumentación mínima durante la prueba** (para tener datos, no impresiones):

```sh
docker compose logs -f --tail 50 whisper hermes
```

Y anotar la latencia percibida de las notas 1 y 2 para compararla contra el baseline documentado en Fase 1 (criterio de éxito final de la propuesta).

---

## 8. Resumen de decisiones para `sdd-tasks`

| # | Decisión | Estado |
|---|---|---|
| ADR-1 | `-F model=...` siempre, incondicional | Cerrada — neutraliza V3 como bloqueante de diseño |
| ADR-2 | `PRELOAD_MODELS` como array JSON | Cerrada — verificar en §6.2 |
| ADR-3 | `curl`-en-imagen es una suposición aparte del endpoint | Cerrada — verificar en §6.1b, fallbacks pre-escritos |
| ADR-4 | `service_healthy` es orden de arranque, no gate de voz | Cerrada |
| ADR-5 | Comentario ancla del id de modelo en el compose | Cerrada |
| §5.2 | **Volumen nuevo `speaches-cache` vs. reusar `whisper-cache`** | **Abierta — `sdd-tasks` debe elegir. Diseño recomienda volumen nuevo** |
| §2/V1 | Ruta de caché: convencional vs. blindaje con `HF_HOME` | Condicional — depende del resultado de §6.1 |
| §1 | `start_period: 1800s` | Cerrada |
| §3 | Compose + script en un único commit | Cerrada — requisito del rollback atómico |
| §3.5 | Diff funcional del script = 5 líneas; parseo y códigos de error intactos | Cerrada |
| §3.5c | `--max-time 30` se mantiene como canario del TTL, no se tunea | Cerrada |
| §4.4 | Despliegue en dos tiempos en el primer boot | Cerrada |
