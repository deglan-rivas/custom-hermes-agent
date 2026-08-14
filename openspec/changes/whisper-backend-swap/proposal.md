# Propuesta de cambio: Swap del backend de transcripción (`whisper-backend-swap`)

Change name: `whisper-backend-swap`
Baseline: Fase 1 (`hermes-personal-assistant`) en producción en labia03.
Fuente: `openspec/changes/whisper-backend-swap/explore.md` (verificado en vivo contra un contenedor `speaches` corriendo, 2026-08-13).

---

## 1. Intent

### Qué problema resuelve
La transcripción de notas de voz (`onerahmet/openai-whisper-asr-webservice:latest-gpu`) responde lento. Dos causas concurrentes: una imagen pesada y poco mantenida, y `MODEL_IDLE_TIMEOUT=600` que descarga `large-v3` de VRAM tras 10 minutos de inactividad — con lo cual **la mayoría de las notas de voz reales pagan una recarga en frío**, porque el uso es esporádico por definición.

### Por qué ahora
`entrada-voz` ya está viva y es la vía de entrada de menor fricción del asistente. La latencia percibida degrada justamente el caso de uso que justifica la GPU. Además el host tiene **48GB de VRAM** casi libres y un solo usuario: el idle-unload está resolviendo un problema de presión de memoria que **no existe acá**.

### Cómo se ve el éxito
1. Una nota de voz se transcribe con el mismo texto que hoy (misma precisión: `large-v3` sin cuantizar, `float16`).
2. Ninguna transcripción paga recarga en frío — el modelo queda residente.
3. El contrato JSON `ok/error` que consume `skills/entrada-voz/SKILL.md` **no cambia en absoluto**.
4. El healthcheck de compose funciona con `curl` plano, sin el workaround `python3 urllib` documentado en `TROUBLESHOOTING.md §3`.

---

## 2. Scope

### En alcance

**D-1. `docker-compose.yml`, servicio `whisper`**
| Campo | De | A |
|---|---|---|
| `image` | `onerahmet/openai-whisper-asr-webservice:latest-gpu` | `ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cuda-12.6.3` |
| `environment` | `ASR_ENGINE`/`ASR_MODEL`/`ASR_DEVICE`/`ASR_COMPUTE_TYPE`/`MODEL_IDLE_TIMEOUT` | `WHISPER__INFERENCE_DEVICE=cuda`, `WHISPER__COMPUTE_TYPE=float16`, `PRELOAD_MODELS=Systran/faster-whisper-large-v3`, `STT_MODEL_TTL` **desactivado / muy alto** |
| `healthcheck` | `python3 -c urllib ... :9000/docs` | `curl -fsS http://localhost:8000/health` (verificado en vivo: HTTP 200, `{"message":"OK"}`) |
| `volumes` | `whisper-cache:/root/.cache` | ruta de caché HF de la imagen speaches — **a confirmar contra el contenedor** (tarea de verificación, ver §5) |
| `deploy...devices` | — | sin cambios |
| `container_name: whisper` | — | sin cambios (referenciado por nombre en toda la ops) |
| `TZ: America/Lima` | — | sin cambios |

**D-2. `docker-compose.yml`, servicio `hermes`**
- `WHISPER_URL: http://whisper:9000` → `http://whisper:8000`.
- **No estaba en el explore y es la línea que realmente manda**: esta env var pisa el default del script en runtime. Sin este cambio, el swap no funciona aunque el script esté bien.

**D-3. `ops/transcribe-voice.sh`**
- Default `WHISPER_URL`: `http://whisper:9000` → `http://whisper:8000` (defensa en profundidad; el valor efectivo viene de D-2).
- Llamada: `-F "audio_file=@${AUDIO_FILE}" "${WHISPER_URL}/asr?output=json"` → `-F "file=@${AUDIO_FILE}" "${WHISPER_URL}/v1/audio/transcriptions"`, más el campo `model` si el endpoint lo exige (ver §5).
- Parseo de respuesta: **cero cambios**. El OpenAPI en vivo declara `Transcription.required: ["text"]`, con lo cual `payload.get("text")` sigue siendo correcto por contrato.
- Comentarios de cabecera (líneas 2, 8) y el mensaje de error `whisper_no_disponible` (línea 47) mencionan `/asr` — actualizar texto.

**D-4. Docs (cosmético, sin acoplamiento funcional)**
- `skills/entrada-voz/SKILL.md` (~líneas 12, 35): menciones a `whisper:9000` / `/asr`.
- `ops/SECURITY-GROUP6.md` (~líneas 54-56): ídem.
- `TROUBLESHOOTING.md §3`: **anotar** como incidente específico de la imagen `onerahmet` (ya no aplica). **No borrar** — es registro histórico.

### Fuera de alcance
- **whisper.cpp**: evaluado y descartado. Fuerza un tradeoff precisión/tooling (cuantizar, o correr f16 y perder su ventaja de velocidad) y un contrato no compatible con OpenAI — todo para resolver un problema de headroom de GPU que este host no tiene.
- **Variantes distil/cuantizadas** (`Systran/faster-distil-whisper-large-v3`): descartadas explícitamente, el usuario quiere pérdida de precisión mínima.
- **El contrato de llamada de `entrada-voz`**: el envoltorio `ok/error` queda idéntico. La skill no se toca más allá de la prosa.
- Servicios `hermes` y `restic` (más allá de la única línea `WHISPER_URL` de D-2).
- Publicar puertos: `whisper` sigue sin `ports:`, solo alcanzable por la red interna del compose.

---

## 3. Capabilities

Convención del repo: **un `spec.md` por change** (no hay `openspec/specs/`).

### New Capabilities
- Ninguna.

### Modified Capabilities
- `Voice Input (entrada-voz)` (spec Fase 1): cambia el **backend y el contrato HTTP hacia el sidecar** (endpoint, puerto, nombre del campo multipart). El contrato hacia la skill (`ok/error` + `data.texto`) y la degradación elegante ante GPU/servicio caído se mantienen sin cambios y deben re-afirmarse como requisito.

---

## 4. Approach + rationale

### 4.1 Speaches, misma familia de motor
`speaches` corre CTranslate2/faster-whisper igual que la imagen actual, así que `large-v3` + `float16` sin cuantizar es **la misma ruta de precisión de hoy**, no una aproximación. Cambia la envoltura HTTP (compatible con OpenAI, bien documentada), no el modelo ni el decodificador. Es lo que hace el swap barato de razonar y trivial de revertir.

*No se vende como "más rápido por batching"*: el explore verificó que ese beneficio aplica a lotes largos/concurrentes, no a una nota de voz corta por request. Las ganancias reales y verificadas son: imagen mantenida y más chica, healthcheck sano con `curl`, contrato estándar, y control explícito del ciclo de vida del modelo.

### 4.2 Modelo residente en vez de idle-unload (decisión del usuario)
`STT_MODEL_TTL` se desactiva (o se fija en un valor muy alto) en vez de portar `MODEL_IDLE_TIMEOUT=600` a paridad.
*Rationale*: con 48GB de VRAM, un solo usuario y sin otro consumidor de GPU en el stack, liberar VRAM entre notas de voz no compra nada y cuesta una recarga en frío en casi todas las interacciones reales. **Ésta es probablemente la mitad de la mejora de latencia percibida**, independiente del cambio de imagen. `PRELOAD_MODELS` garantiza además que el modelo esté cargado desde el arranque, no en la primera petición (`/api/ps` en vivo confirmó que sin preload no hay ningún modelo cargado).

### 4.3 El endpoint del healthcheck se verificó antes de escribirlo
`GET /health` fue probado contra el contenedor real y responde 200 con `curl` plano. Esto cierra por diseño la clase de falla documentada en `TROUBLESHOOTING.md §3` (healthcheck asumido contra una imagen sin `curl`), que además importa porque `hermes` depende de `whisper: condition: service_healthy`.

### 4.4 Volumen de caché tratado como nuevo, no migrado
El formato de caché no es reutilizable entre imágenes. Se asume descarga completa de `large-v3` en el primer arranque y se ajusta `start_period` en consecuencia, en vez de intentar reciclar `whisper-cache`.

---

## 5. Verificaciones previas (bloqueantes para `sdd-apply`)

- [ ] **V1 — Ruta de montaje de la caché.** Confirmar dentro del contenedor speaches el directorio real de caché de HuggingFace y montar `whisper-cache` ahí. Un montaje mal apuntado no rompe el servicio: lo degrada silenciosamente a re-descargar `large-v3` en cada recreación.
- [ ] **V2 — Valor de `STT_MODEL_TTL` para "nunca descargar".** Confirmar si la imagen acepta un centinela (`-1`/`0`) o si hay que usar un valor grande en segundos. Verificar el efecto con `/api/ps` tras superar el TTL viejo por defecto (300s).
- [ ] **V3 — ¿`model` es obligatorio en el multipart?** El endpoint es compatible con OpenAI, donde `model` es requerido. Confirmar con un `curl` real si `transcribe-voice.sh` debe mandar `-F "model=Systran/faster-whisper-large-v3"` o si el default del servidor alcanza. **No asumir.**
- [ ] **V4 — Transcripción end-to-end** de una nota de voz real de Telegram, comparando el texto contra el backend actual (regresión de precisión) y midiendo latencia en caliente.

---

## 6. Affected Areas

| Área | Impacto | Qué cambia |
|---|---|---|
| `asistente_personal/docker-compose.yml` | Modified | Servicio `whisper`: imagen, env, healthcheck, volumen, `start_period`. Servicio `hermes`: `WHISPER_URL` |
| `asistente_personal/ops/transcribe-voice.sh` | Modified | Puerto default, endpoint, campo multipart, prosa/mensajes de error |
| `asistente_personal/skills/entrada-voz/SKILL.md` | Modified | Solo prosa (puerto/endpoint) |
| `asistente_personal/ops/SECURITY-GROUP6.md` | Modified | Solo prosa (puerto/endpoint) |
| `asistente_personal/TROUBLESHOOTING.md` | Modified | §3 anotada como específica de `onerahmet` |
| `asistente_personal/README.md`, `ops/verify-gpu.sh`, `ops/check-stack.sh` | Sin cambios | Referencian el servicio/contenedor `whisper` por nombre, que no cambia |

---

## 7. Riesgos

| Riesgo | Prob. | Mitigación |
|---|---|---|
| Ruta del volumen de caché equivocada → re-descarga de `large-v3` en cada recreación | Media | V1 bloqueante; verificar que la caché persiste tras `docker compose down && up` |
| Primer arranque tarda más que `start_period` → healthcheck falla y `hermes` no levanta el sidecar | Media | Subir `start_period` (hoy 300s); el `depends_on` ya es `required: false`, así que el peor caso es "Fase 1 sin voz", no boot bloqueado |
| `model` requerido en el request y no enviado → todas las transcripciones fallan | Media | V3 bloqueante antes de aplicar |
| Se olvida `WHISPER_URL` en el servicio `hermes` (D-2) → el swap no aplica en runtime | Media | Explícito como deliverable propio; V4 lo detecta end-to-end |
| Regresión de precisión respecto del backend actual | Baja | Mismo motor, mismo modelo, misma `compute_type`; V4 compara textos |
| `0.9.0-rc.3` es un release candidate | Baja | Tag pinneado (no `latest`), probado en vivo; rollback de una línea |
| Modelo residente permanente ocupa VRAM sin uso | Baja | Decisión explícita del usuario: 48GB, sin otro consumidor de GPU |

---

## 8. Rollback Plan

1. El servicio conserva **el mismo `container_name`, el mismo nombre de servicio y la misma familia de respuesta JSON con `text`**. El blast radius es un puñado de líneas.
2. **Rollback**: `git revert` del commit → vuelve la imagen `onerahmet`, el bloque de env viejo, el healthcheck `python3 urllib`, `WHISPER_URL` a `:9000` y el script a `/asr` + `audio_file`. `docker compose up -d whisper hermes`.
3. **Caché**: si se creó un volumen nuevo, el `whisper-cache` viejo puede conservarse intacto durante la transición para que el rollback no vuelva a descargar el modelo.
4. **Degradación intermedia**: si `whisper` no levanta, `hermes` arranca igual (`required: false`) y `transcribe-voice.sh` devuelve `codigo: whisper_no_disponible`; la skill pide al usuario que escriba el mensaje. No hay pérdida de datos ni de mensajes en ningún escenario de falla.

---

## 9. Dependencies

- `nvidia-container-toolkit` operativo en labia03 (ya en uso por el `whisper` actual).
- Ancho de banda para la descarga inicial de `Systran/faster-whisper-large-v3` en el primer arranque.
- Ninguna dependencia de código: sin cambios en `vida.py`, en el esquema, ni en la base.

---

## 10. Success Criteria

- [ ] `docker compose up -d whisper` levanta `healthy` con el healthcheck `curl /health`.
- [ ] `/api/ps` muestra `Systran/faster-whisper-large-v3` cargado inmediatamente tras el arranque, sin ninguna petición previa.
- [ ] El modelo sigue cargado tras >10 minutos de inactividad (validación del TTL desactivado).
- [ ] Una nota de voz real de Telegram se transcribe correctamente vía `entrada-voz`, con el mismo texto que producía el backend anterior.
- [ ] `transcribe-voice.sh` sigue devolviendo exactamente un objeto JSON con la forma `ok/error`; `skills/entrada-voz/SKILL.md` no requiere cambios de comportamiento.
- [ ] Con `whisper` detenido, `transcribe-voice.sh` sale 1 con `codigo: whisper_no_disponible` (degradación elegante intacta).
- [ ] La caché del modelo persiste entre `docker compose down` / `up` (sin re-descarga).
- [ ] Latencia en caliente medida y comparada contra el baseline documentado.

---

**Next**: `sdd-spec` y `sdd-design` (pueden correr en paralelo). El punto de diseño más caro es la **matriz de configuración de speaches** (V1-V3): ruta de caché, centinela de TTL y obligatoriedad de `model`.
