# Troubleshooting — incidentes reales encontrados en el rollout de Fase 1

Registro de los problemas encontrados al levantar `hermes-personal-assistant` en vivo en
labia03 (post-merge de los 6 PRs), su causa real y el fix. Cada uno se descubrió corriendo
el runbook (`README.md`) contra el sistema real, no en revisión de código.

---

## 1. `docker compose up -d hermes` arrancaba el REPL interactivo, no el gateway

**Síntoma:** el contenedor imprimía el chat interactivo de Hermes (`Welcome to Hermes
Agent!`), detectaba que no había TTY (`Warning: Input is not a terminal (fd=0)`) y se
cerraba solo.

**Causa:** la imagen oficial `nousresearch/hermes-agent` no tiene un `CMD` por defecto que
levante el gateway de mensajería — hay que pasarle el subcomando explícito.

**Fix:** agregar `command: gateway run` al servicio `hermes` en `docker-compose.yml`.

---

## 2. Skill `entrada-voz` no encontraba `ops/transcribe-voice.sh`

**Síntoma:** el agente reportaba *"el script de transcripción no está instalado en este
entorno"* al intentar transcribir una nota de voz, a pesar de que el archivo existía en el
repo.

**Causa:** `docker-compose.yml` solo montaba `bin/vida.py` y `data/schema.sql` dentro del
contenedor `hermes` — el directorio `ops/` (donde vive `transcribe-voice.sh` y el resto de
scripts que las skills invocan) nunca se montó.

**Fix:** agregar `./ops:/opt/data/ops:ro` a los volúmenes del servicio `hermes`.

---

## 3. Healthcheck de `whisper` en falso negativo permanente

> **Nota (change `whisper-backend-swap`):** este incidente es específico de la imagen
> `onerahmet/openai-whisper-asr-webservice:latest-gpu`, retirada por ese change en favor de
> `ghcr.io/speaches-ai/speaches`. La imagen `speaches` sí trae `curl` (verificado en vivo,
> `openspec/changes/whisper-backend-swap/tasks.md` T3) y el healthcheck volvió a `curl` plano.
> Se deja este registro intacto porque sigue siendo válido para cualquiera que haga rollback a
> la imagen `onerahmet`.

**Síntoma:** el contenedor `whisper` quedaba `unhealthy` indefinidamente aunque el servicio
funcionaba bien (`nvidia-smi` mostraba el proceso cargado y usando VRAM).

**Causa:** el healthcheck usaba `curl`, pero la imagen
`onerahmet/openai-whisper-asr-webservice:latest-gpu` no trae `curl` instalado
(`/bin/sh: 1: curl: not found` en `docker inspect --format='{{json .State.Health}}'`).

**Fix:** reemplazar el test por una llamada `python3` vía `urllib.request` (python3 sí está
presente en la imagen).

---

## 4. `config.yaml` generado por nuestro template rompía Hermes al arrancar

**Síntoma:** `hermes` crasheaba en loop con `AttributeError: 'dict' object has no attribute
'strip'` dentro de `_has_any_provider_configured()`, y el log advertía: *"This config
predates version 12 (~2 years old) and can no longer be auto-migrated"*.

**Causa:** el `config.yaml.template` + `render-config.sh` originales (PR1) generaban un
YAML plano (`provider:`, `telegram:`) sin `_config_version`, asumiendo un schema que
resultó **no coincidir** con el schema real (v33+) de la versión de Hermes instalada — el
propio `design.md §15` ya había marcado esto como riesgo abierto ("shape, not a verified
schema").

**Fix:** abandonar el enfoque de template hecho a mano. Se usa el wizard oficial
(`hermes setup` interactivo, luego `hermes setup gateway` para Telegram) como única fuente
de verdad para `config.yaml`, y `hermes config set <clave> <valor>` para ajustes puntuales
(ej. `skills.write_approval true` — la clave real no es `write_approval` a nivel raíz como
asumía el template original, sino anidada bajo `skills.`).

---

## 5. STT nativo de Hermes interceptaba las notas de voz, no nuestro sidecar GPU

**Síntoma:** una nota de voz en español se transcribía/traducía mal, en inglés, y muy
lento. Los logs de `whisper` (nuestro sidecar) no mostraban ningún request `/asr` — la
skill `entrada-voz` nunca se había ejecutado.

**Causa:** Hermes trae `faster-whisper` embebido (`stt.local`, config `model: base`,
`language: en` por defecto), corriendo **dentro del contenedor `hermes`, sin GPU** (el
passthrough solo se le dio al servicio `whisper` dedicado). Interceptaba el audio antes de
que la skill pudiera actuar.

**Fix:** `hermes config set stt.enabled false` — desactiva el STT nativo para que las notas
de voz pasen por la skill `entrada-voz` + el sidecar GPU dedicado, como estaba diseñado
(F0.7).

---

## 6. Docker crea directorios root-owned cuando el bind-mount source no existe

**Síntoma:** `Permission denied` (sin sudo) al intentar leer/escribir
`config.yaml`, `secrets/rclone.conf`, y `state/backup/last-success` desde el host.

**Causa:** cuando un `docker compose up` referencia un volumen bind-mount cuyo path fuente
todavía no existe en el host, Docker lo **crea automáticamente como directorio, propiedad
de root** — no como el archivo que el servicio esperaba, y no con el owner del usuario que
corrió el comando.

**Fix (patrón repetible):** un contenedor descartable con acceso de root al mismo path
arregla el problema sin sudo:
```sh
docker run --rm -v "$(pwd)/ruta:/target" alpine sh -c "rmdir /target/lo-que-sea 2>/dev/null; chown -R 1000:1000 /target"
```
Después de eso, el host (usuario normal) puede escribir ahí sin problema.

---

## 7. El cron del briefing de 7am nunca se registró (gap operativo, no bug)

**Síntoma:** ningún mensaje de briefing llegó desde el día del deploy.

**Causa:** solo se registró el job de **smoke test** (2 min, `ops/cron-jobs.md §5.5`) y se
borró siguiendo el propio runbook — el mensaje para registrar el job **real** (7am) nunca
se mandó al bot. `jobs.json` confirmó `"jobs": []`.

**Fix:** no es un fix de código. Registrar el job real mandándole al bot el texto de
`ops/cron-jobs.md §5.1`. Anotado acá para que no se repita al agregar futuros cron jobs
(ej. `daily-routine-tracker`'s resumen semanal) — **el smoke test no reemplaza registrar el
job real**, son dos mensajes distintos.

---

## 8. Cierre de F0.5 (backup) — notas operativas

- `mazzolino/restic:1.6` trae `rclone` embebido — no hace falta instalar `rclone` en el
  host, solo escribir `secrets/rclone.conf` con las credenciales del remoto.
- Backblaze B2 usa el backend nativo `type = b2` de rclone (más simple que el modo
  S3-compatible), con `account`/`key` = keyID/applicationKey de la Application Key
  restringida al bucket.
- El primer `restic backup` puede tirar errores `500 Internal Server Error` /
  `use of closed network connection` transitorios contra B2 — `restic`/`rclone` reintentan
  solos (`retrying after 720ms`); no es un fallo si el backup termina con `snapshot ...
  saved` y `restic check` sin errores.
- Ver incidente #6 para el error de permisos en `state/backup/last-success`.

---

## 9. Verificación de whitelist y alerta de caída — cómo probarlas sin esperar

- **Segundo usuario ignorado (criterio #5):** no se puede simular vía API — Telegram
  autentica el campo `from.id` del lado del cliente real, no algo falseable con la Bot API.
  Se confirma pidiéndole a otra persona real que le escriba al bot y buscando
  `Blocked unauthorized user <id>` en `docker logs hermes`.
- **Alerta de stack caído (criterio #7):** no hace falta esperar el tick de 15 min del
  cron — correr `ops/check-stack.sh` a mano después de `docker compose stop whisper`
  dispara la transición `ok→bad` (y luego `bad→ok` al levantarlo de nuevo) de inmediato.
