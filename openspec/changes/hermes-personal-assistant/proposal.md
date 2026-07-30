# Propuesta de cambio: Asistente personal en Hermes Agent (Fase 1)

Change name: `hermes-personal-assistant`
Fase cubierta por esta propuesta: **Fase 1** (Fase 2 explícitamente fuera de alcance)
Baseline: `PLAN.md` + `PREGUNTAS_BASE.md` (repo root), corregidos por `sdd/hermes-personal-assistant/explore`.

---

## 1. Intent

### Qué problema resuelve
Hoy los datos personales del usuario (gastos, progresión de gym, fechas de corte/pago de tarjetas, cumpleaños, pendientes) viven dispersos entre la memoria, notas y apps sueltas. No hay un punto único de captura ni de consulta, y sobre todo no hay proactividad: nadie avisa que mañana vence una tarjeta ni que este mes hay un cumpleaños. La captura tiene que ser de fricción casi cero (desde el celular, en lenguaje natural, incluso por voz) o no se sostiene a los tres meses.

### Por qué ahora
- `labia03` (servidor JNE) está disponible **solo hasta enero de 2027**, con GPU de 48GB exclusiva para el usuario y sudo confirmado. Es la ventana para construir sobre hardware que ya existe y no cuesta.
- El motor de razonamiento es **opencode Go** (suscripción personal, $10/mes, no atada al JNE) apuntando al modelo `deepseek-v4-pro` vía su endpoint OpenAI-compatible. Al ser personal, sobrevive a `labia03` — pero igual se mantiene `LLM_BASE_URL`/`LLM_API_KEY` como variables desde el día uno, por si el proveedor cambia de catálogo o precio.
- La exploración validó que Hermes Agent (Nous Research, MIT) trae de fábrica lo que costaría más construir: canal Telegram, cron scheduler nativo con entrega a Telegram, memoria persistente y auto-edición de skills con aprobación. 4 de 5 supuestos técnicos del plan quedaron confirmados; el quinto (imagen Docker) se corrigió **a favor** (hay imagen oficial, menos trabajo).

### Cómo se ve el éxito
La Fase 1 está lista cuando, sin abrir una terminal:
1. El usuario dice desde Telegram *"gasté 45 soles en almuerzo"* y la fila queda tipada en `vida.db` con categoría correcta.
2. Manda una **nota de voz** con un registro de gym y queda transcrita localmente (GPU) y persistida.
3. Pregunta *"¿cuánto me toca en press banca hoy?"* y recibe una respuesta calculada desde la progresión real, no inventada.
4. Recibe el **briefing de las 7am en hora de Lima** sin haberlo pedido esa mañana.
5. Un segundo usuario de Telegram le escribe al bot y es ignorado.
6. Se hace un **restore real en la laptop** desde el backup cifrado y el asistente arranca ahí con memoria y `vida.db` intactos.
7. Si el stack se cae, llega una **alerta a Telegram** por una vía que no depende del stack caído.

El criterio duro: el punto 6 no es opcional. Un backup no verificado no es un backup, y enero 2027 no es el momento de descubrirlo.

---

## 2. Scope

### En alcance (Fase 1)

**Infraestructura**
- `docker-compose.yml` con tres servicios: `hermes`, `whisper` (GPU), `restic`.
- Servicio `hermes` usando la **imagen oficial `nousresearch/hermes-agent`** (Docker Hub, Debian 13.4, s6-overlay, `/opt/hermes` inmutable, estado en `/opt/data`). Volumen: `~/.hermes` → `/opt/data`.
- **`TZ=America/Lima`** como variable de entorno del servicio `hermes`.
- `.env.template` con `LLM_BASE_URL`, `LLM_API_KEY`, `TELEGRAM_TOKEN`, `TG_USER_ID`, `RESTIC_*`.
- Un solo volumen persistente (`hermes-data`): `.hermes/` (memoria, skills, sesiones) + `data/vida.db`. Cero estado fuera de ahí.
- Cero puertos entrantes: Telegram por long-polling saliente, acceso admin por Tailscale SSH.

**Datos estructurados**
- `data/schema.sql`: tablas `gastos`, `entrenamientos`, `tarjetas`, `contactos`, `pendientes`.
- `bin/vida.py`: CLI en **stdlib de Python, sin ORM**, salida **JSON**. Subcomandos: `gasto add/report`, `gym log/progress`, `tarjeta add/next`, `cumple add/upcoming`, `pendiente add/today`.

**Skills a medida** (`~/.hermes/skills/`)
- `registrar-gasto/`, `gym-tracker/`, `tarjetas/`, `agenda-personal/`, `sobre-mi/` — cada uno un `SKILL.md` que le enseña al agente cuándo y cómo invocar `vida.py`.
- `sobre-mi/` es la "documentación base viva": el agente la edita vía `skill_manage` conforme aprende.

**Voz (solo entrada)**
- Servicio `whisper` con `faster-whisper` sobre la GPU; hook que intercepta notas de voz de Telegram, transcribe e inyecta el texto al agente. Sin salida de voz (TTS fuera de alcance).

**Proactividad** (cron nativo de Hermes, definido en lenguaje natural)
- Briefing matutino ~7am (pendientes + entrenamiento del día con pesos objetivo).
- Alerta de tarjeta N días antes de corte y de pago.
- Aviso de cumpleaños con anticipación configurable.
- Resumen semanal de gastos por categoría.

**Seguridad**
- Whitelist del `user_id` de Telegram (mecanismo exacto a verificar en Fase 0).
- `write_approval: true` desde el arranque (el default de Hermes es `false`, o sea el agente escribe libre — hay que voltearlo explícitamente).
- Secretos en `.env`, fuera de todo repo, `.gitignore` desde el primer commit.
- Transcripción de voz y datos financieros nunca salen del servidor.

**Backups y portabilidad**
- Contenedor `restic` con cron diario → repositorio cifrado en nube (Google Drive o S3 vía rclone). Retención 7 diarios / 4 semanales / 12 mensuales.
- `backup/backup.sh` + `backup/restore.sh`.
- **Restore drill real en la laptop durante la Fase 1.**
- Passphrase de restic con **copia offsite/out-of-band** (gestor de contraseñas o copia offline), no solo dentro del volumen que respalda.

**Nuevo respecto a PLAN.md — Observabilidad (a nivel host, fuera de Docker)**
- Script A: `docker compose ps --format json` cada ~15 min vía cron/systemd timer; si algún servicio no reporta `running`/`healthy`, alerta por **llamada directa a la Bot API de Telegram con `curl`**.
- Script B: valida que el último `restic snapshots --json` tenga menos de ~26h; alerta por la misma vía si está rancio o si el comando falla.
- Ambos corren **en el host, no en un contenedor**, precisamente porque la caída de Hermes/Docker es uno de los fallos a detectar. No pueden ser skills de Hermes.

**Nuevo respecto a PLAN.md — Versionado de skills**
- `~/.hermes/skills/` como **repo git local** (commit-only, sin remoto obligatorio). Auto-commit vía hook post-aprobación o cron cada ~15 min (`git add -A && git commit` si hay cambios).
- `state.db` y cualquier SQLite van al `.gitignore` (binario, ruidoso, no diffea).
- El `.git/` vive dentro del volumen ya respaldado por restic → no hay nuevo destino de backup, es aditivo.

### Fuera de alcance (Fase 2 o posterior)
- **Puente a Claude Code** (lanzar/retomar sesiones desde Telegram reusando `claude-remote/` y `claude-simple/`). Diferido explícitamente para que un stack no bloquee al otro.
- Salida de voz / TTS.
- Cualquier exposición pública de `labia03` (ni ahora ni después).
- LLM local en GPU para razonamiento general (la GPU en Fase 1 es solo para whisper/embeddings; DeepSeek remoto razona).
- Prometheus/Grafana o cualquier stack de observabilidad "de verdad" — dos scripts shell son el tamaño correcto para un usuario.
- Migración efectiva a VPS (el diseño la habilita; ejecutarla es trabajo de finales de 2026).
- Honcho / modelado cross-sesión del usuario (provider opt-in de Hermes, no el default).
- Multi-usuario, multi-timezone, CI sobre skills, revisión por PR de skills.

### Explícitamente eliminado del plan original
- **`Dockerfile` propio.** `PLAN.md` afirmaba *"No existe imagen Docker oficial"* — es **falso**. Existe `nousresearch/hermes-agent`. La tarea de escribir un Dockerfile sobre Debian que corra el `install.sh` queda **borrada**, junto con su mantenimiento. Reduce alcance de Fase 1.

---

## 3. Approach (alto nivel) + rationale

### 3.1 Imagen oficial en vez de Dockerfile propio
Se usa `nousresearch/hermes-agent` con `~/.hermes` montado en `/opt/data`.
*Rationale*: la imagen ya está supervisada por s6-overlay, trata `/opt/hermes` como inmutable y concentra todo el estado en `/opt/data` — exactamente el contrato de "un solo volumen" que necesita la portabilidad de enero 2027. Un Dockerfile propio duplicaría eso peor y añadiría una superficie de mantenimiento (reinstalar en cada rebuild, seguir cambios del `install.sh`) a cambio de nada.

### 3.2 Hermes no necesita GPU; el sidecar sí
El contenedor de Hermes no recibe passthrough de GPU. Solo `whisper` la recibe (`devices: [capabilities: [gpu]]`).
*Rationale*: confirmado en la exploración — Hermes delega la inferencia a un endpoint OpenAI-compatible, así que no toca CUDA. El passthrough documentado es para contenedores sidecar de inferencia (su ejemplo usa vLLM). El diseño de PLAN.md ya era correcto; queda confirmado, no cambiado. Beneficio lateral: si mañana la GPU desaparece, el asistente sigue funcionando y solo se pierde la voz.

### 3.3 Memoria nativa para contexto blando, `vida.db` para números
La memoria de Hermes (SQLite + FTS5 sobre mensajes de sesión) se usa para preferencias y contexto conversacional. Los datos estructurados van a `vida.db` con `vida.py` como única puerta de escritura/lectura.
*Rationale*: FTS5 hace búsqueda de keywords sobre texto de conversación, **no agregación estructurada**. *"¿Cuánto gasté en comida en junio?"* sobre FTS5 es una invitación a que el modelo alucine un número plausible. Un `SELECT SUM(...) GROUP BY categoria` no alucina. La separación no es purismo: es la diferencia entre un asistente confiable y uno que miente con seguridad sobre tu plata. Salida JSON porque es lo que el agente consume con menos ambigüedad; stdlib sin ORM porque un ORM aquí es peso muerto que además complica el restore.

### 3.4 Cron nativo de Hermes + `TZ` a nivel Linux
La proactividad se define en lenguaje natural sobre el cron integrado (daemon del gateway, tick de 60s, cada job en sesión aislada, entrega a Telegram). La hora correcta se logra con `TZ=America/Lima` en el compose.
*Rationale*: Hermes **no tiene ningún concepto de timezone** — verificado leyendo directo `cron.md` y `configuration.md` (cero menciones a TZ/timezone/locale) y corroborado por issues **abiertos** pidiendo la feature. Por lo tanto "7am" es lo que el reloj del SO del contenedor crea que es 7am, o sea semántica estándar de `TZ` en Linux, que sí controlamos. Fix de una línea, sin depender de una feature que no existe.
*Limitación a documentar*: no hay TZ por job. Todos los jobs comparten la zona del contenedor. Irrelevante hoy (un usuario, una zona); importante si algún día se quiere multi-zona.

### 3.5 Alertas fuera del sistema que vigilan
Los dos checks corren en el host (cron/systemd timer) y alertan por `curl` directo a la Bot API.
*Rationale*: un healthcheck que vive dentro del stack que monitorea no detecta la caída del stack — se cae con él. Y no puede ser un skill de Hermes por la misma razón: "Hermes está muerto" es justamente el evento a reportar. De ahí que la vía de alerta no toque Hermes ni Docker Compose en absoluto.

### 3.6 Git local para las skills que el agente se escribe solo
`~/.hermes/skills/` como repo git local, además de `write_approval: true`.
*Rationale*: son dos controles en momentos distintos. `write_approval` es el gate **antes** de que el cambio aterrice (staging en `~/.hermes/pending/skills/`, diff unificado, approve/deny, sobrevive reinicios). Git es la red **después**: `git log -p` para entender qué cambió hace tres semanas y `git revert` para deshacerlo cuando un skill auto-editado empieza a portarse raro. Restic no cubre eso — es coarse (diario/semanal), sin mensajes de commit, y restaurar implica montar el volumen completo. Solo skills (no todo `.hermes/`) porque `state.db` es binario y de escritura constante: inflaría el repo y llenaría el historial de ruido. Costo casi nulo: son archivos de texto chicos dentro de un volumen que ya se respalda.

### 3.7 Portabilidad como propiedad, no como tarea futura
`LLM_BASE_URL` + `LLM_API_KEY` como variables de entorno desde el primer commit; todo el estado en un volumen; restore probado en la laptop.
*Rationale*: la fecha de muerte de `labia03` y de la suscripción de opencode ya se conoce. Diseñar hoy para eso convierte "se cayó el proveedor" en editar una línea del `.env`, y "se perdió el servidor" en `docker compose up` + restore. Si esto se deja para después, el después es un incendio.

---

## 4. Fase 0 — Checklist de verificación bloqueante

**Nada de la Fase 1 se construye hasta cerrar esto.** No son bloqueos de política (GPU exclusiva, sudo y ausencia de restricción JNE ya están confirmados por el usuario) sino de configuración real: *tener sudo no es lo mismo que estar configurado*.

### F0.1 — Endpoint LLM 🟢 CONFIRMADO
- [x] `curl` real desde labia03 contra `https://opencode.ai/zen/go/v1/chat/completions` con `Authorization: Bearer <OPENCODE_API_KEY>` y `model: deepseek-v4-pro` → respuesta `200` con formato OpenAI-compatible válido (`choices[0].message.content`). Verificado 2026-07-29.
- [x] Es suscripción **personal** de opencode Go ($10/mes), no atada al JNE ni a `labia03` — sobrevive a enero 2027 por sí sola.
- [ ] Igual se mantiene `LLM_BASE_URL=https://opencode.ai/zen/go/v1` + `LLM_API_KEY` como env vars (no hardcodear), para que un cambio de proveedor futuro sea una línea de `.env`, no un refactor.
- *Bloqueaba*: absolutamente todo. Resuelto.

### F0.2 — GPU visible dentro de contenedores 🟡
- [ ] Confirmar que `nvidia-container-toolkit` está **instalado** (no solo instalable).
- [ ] Confirmar que el runtime de GPU de Docker está configurado.
- [ ] Prueba real: contenedor de test que corra `nvidia-smi` y vea los 48GB.
- *Bloquea*: solo el servicio `whisper` (voz). Hermes arranca sin GPU. Si esto falla, la Fase 1 puede entregarse sin voz y la voz se retoma después.

### F0.3 — Mecanismo de whitelist de Telegram 🟢 CONFIRMADO
- [x] Es **nativo**. Config: `allow_from` en `~/.hermes/config.yaml` (o env var `TELEGRAM_ALLOWED_USERS`), lista de `user_id` numéricos para DM. Equivalente para grupos: `group_allow_from` / `TELEGRAM_GROUP_ALLOWED_USERS` (no aplica, uso es solo DM).
- [x] Default es **deny-all**: sin `allow_from` configurado, el gateway no responde a nadie — seguro por omisión.
- [ ] Ojo con un error común: el `user_id` a poner es el del usuario humano, **no** el prefijo numérico del token del bot (`123456789:ABC...`).
- ⚠️ Historial: issue #7651 (cerrado por PR) describía que el allowlist no se aplicaba correctamente a menciones dentro de **grupos**. No afecta este uso (solo DM), pero refuerza que el criterio de verificación #7 ("segundo usuario le escribe → debe ser ignorado") se pruebe en real durante Fase 1, no se dé por sentado con la doc.
- *Bloqueaba*: exponer el bot. Resuelto — falta solo la prueba en vivo (verificación #7, no ítem de Fase 0).

### F0.4 — Bot de Telegram 🟢
- [ ] Crear el bot con **@BotFather**, anotar el token.
- [ ] Obtener el `user_id` propio de Telegram (numérico, no el @username).

### F0.5 — Backup: destino y passphrase 🔴
- [ ] Elegir destino (Google Drive personal o S3) y validar credenciales de rclone/restic.
- [ ] Generar la passphrase de restic.
- [ ] **Guardar la passphrase fuera de `labia03`**: gestor de contraseñas o copia impresa/offline. Si solo vive en el `.env` del volumen que respalda, perder el servidor = backups irrecuperables. Esto convierte todo el esfuerzo de backup en teatro.
- *Bloquea*: el servicio `restic` y, por tanto, el criterio de éxito #6.

### F0.6 — Sanity check del host 🟢
- [ ] `docker` y `docker compose` (v2) presentes y funcionando sin sudo, o decidir que corren con sudo.
- [ ] Tailscale activo y `labia03` alcanzable por SSH desde la laptop.
- [ ] `cron` o `systemd --user` disponible para los timers de observabilidad (F0.6 define si los scripts van por crontab o por systemd timer).
- [ ] **F0.6-extra** (del design): `python3` ≥3.8 presente en el host — lo usan `restore.sh` (verificación `PRAGMA integrity_check`) y los scripts de observabilidad.

### F0.7 — Mecanismo de intercepción de voz de Telegram 🟢 RESUELTO (PR 4/6)
- [x] Se implementó como **skill que invoca `/asr`** (`entrada-voz/SKILL.md` + `ops/transcribe-voice.sh`), no como hook de gateway — el hook pre-mensaje de Hermes no está verificado, mientras que el patrón skill-invoca-script ya está probado por las 5 skills de dominio existentes. Ambas opciones comparten el mismo contrato HTTP hacia whisper, así que esto no cierra la puerta a un hook futuro.
- [x] Degradación confirmada: sin whisper alcanzable, `transcribe-voice.sh` devuelve el contrato JSON de error documentado y exit 1 — probado localmente sin GPU real.
- *Bloqueaba*: solo la función de voz. Resuelto vía PR 4.

### Gate de salida de Fase 0
F0.1, F0.3 y F0.7 ya cerraron. **F0.5 es el único rojo que queda** para empezar Fase 1. F0.2 sigue en amarillo (requiere hardware real, `nvidia-container-toolkit` en labia03) y degrada el alcance (Fase 1 sin voz) sin bloquear.

---

## 5. Riesgos y preguntas abiertas

| Riesgo | Impacto | Estado |
|---|---|---|
| ~~El endpoint de opencode no es OpenAI-compatible~~ | Alto | ✅ Resuelto — `curl` real confirmado 2026-07-29, `deepseek-v4-pro` responde OK |
| ~~La whitelist de Telegram no es nativa~~ | Alto | ✅ Resuelto — `allow_from`/`TELEGRAM_ALLOWED_USERS` nativo, deny-by-default |
| Passphrase de restic solo en `labia03` | Crítico si se materializa — backups irrecuperables | Abierto — acción del usuario en F0.5 |
| `nvidia-container-toolkit` no configurado pese al sudo | Medio — sin voz | Abierto — verificación real en F0.2 |
| Mecanismo de intercepción de voz sin confirmar | Medio — sin voz | Abierto — F0.7, añadido por el design |
| Hermes no entiende timezones (solo reloj del SO) | Bajo | Mitigado — `TZ=America/Lima`; sin TZ por job |
| Skills auto-editados degradan el comportamiento | Medio | Mitigado por diseño — `write_approval: true` + git local con `revert` |
| Fin de vida de `labia03` (enero 2027) | Cierto, no hipotético | Mitigado por diseño — un volumen + restic + restore drill en Fase 1 |
| Alcance de Fase 1 se estira hacia Fase 2 | Medio | Mitigado — puente a Claude Code explícitamente fuera de alcance |

**Preguntas abiertas que bloquean construir (no spec/design):** solo **F0.5** (passphrase offsite, acción del usuario). F0.2 y F0.7 degradan alcance sin bloquear. F0.1 y F0.3 ya cerraron con evidencia real.

---

## 6. Cambios respecto a PLAN.md (resumen)

| # | Cambio | Origen |
|---|---|---|
| 1 | Se **elimina** el `Dockerfile` propio; se usa la imagen oficial `nousresearch/hermes-agent` | Exploración: el supuesto "no existe imagen oficial" era falso |
| 2 | Se **añade** `TZ=America/Lima` al servicio `hermes` | Exploración: Hermes no tiene concepto de timezone (issues abiertos) |
| 3 | Se **añaden** dos scripts de observabilidad a nivel host + alerta por Bot API directa | Exploración: gap material, no cubierto en PLAN.md |
| 4 | Se **añade** `~/.hermes/skills/` como repo git local (commit-only) | Exploración: restic es demasiado coarse para diff/rollback de skills |
| 5 | Se **añade** copia out-of-band de la passphrase de restic | Exploración: PLAN.md decía "generar" pero no dónde guardarla |
| 6 | Se **añade** verificación del mecanismo de whitelist de Telegram a Fase 0 | Exploración: mecanismo no verificado, riesgo de seguridad real |
| 7 | Se **añade** pre-provisionar la key del Plan B de LLM | Exploración: `LLM_BASE_URL` sin key lista no es un plan, es una intención |
| 8 | Las tres preguntas institucionales sobre `labia03` quedan **cerradas** (GPU exclusiva, sudo sí, sin restricción JNE); solo queda el sanity check de configuración | Respuestas confirmadas por el usuario |
| 9 | Todo lo demás de PLAN.md se **mantiene sin cambios** | Confirmado por exploración (cron, `skill_manage`/`write_approval`, memoria FTS5, patrón GPU sidecar) |
| 10 | F0.1 pasa a **verde**: `opencode Go` (personal, $10/mes) + `deepseek-v4-pro`, confirmado con `curl` real desde labia03 | Usuario aportó datos de la suscripción; verificado con research + prueba en vivo |
| 11 | F0.3 pasa a **verde**: whitelist nativa (`allow_from`/`TELEGRAM_ALLOWED_USERS`, deny-by-default) | Verificado en docs oficiales de Hermes + historial de issue #7651 |
| 12 | Se **añade** F0.7 (mecanismo de intercepción de voz) y F0.6-extra (`python3` en host) al gate de Fase 0 | Aportado por `sdd-design` |

---

**Next**: `sdd-tasks`.

---
_Migrado de Engram observation #589 (topic: `sdd/hermes-personal-assistant/proposal`), creado 2026-07-29 21:35:00. Actualizado 2026-07-29 con validaciones en vivo de F0.1 y F0.3._
