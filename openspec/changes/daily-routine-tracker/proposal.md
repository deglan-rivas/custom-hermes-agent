# Propuesta de cambio: Tracker de rutina diaria (`daily-routine-tracker`)

Change name: `daily-routine-tracker`
Baseline: Fase 1 (`hermes-personal-assistant`) **ya en producción en labia03**.
Fuente: `sdd/daily-routine-tracker/explore` (Engram #609) + refinamientos acordados con el usuario post-exploración.

> ⚠️ Este cambio **no es greenfield**. `design.md §13` de Fase 1 decía "no data migration — greenfield"; eso dejó de ser cierto. Todo aquí es **aditivo y retrocompatible** contra una `vida.db` real con datos reales.

---

## 1. Intent

### Qué problema resuelve
Los `pendientes` de Fase 1 modelan bien lo **eventual** ("pagar la luz el jueves"), pero no lo **repetitivo**. La vida diaria del usuario está hecha de bloques recurrentes — *asearme* → {cortarse las uñas, ducharse, skincare}, *cocinar* → {…} — que se repiten todos los días y cuyo valor no está en recordarlos una vez, sino en **saber si hoy se cumplieron y con qué consistencia a lo largo del tiempo**.

Meter eso en `pendientes` con `recurrencia` sería forzar un modelo de to-do (una fila que se cierra) sobre un modelo de checklist (un ítem que se re-evalúa cada día). Se degradaría a filas duplicadas, estado ambiguo y cero capacidad de medir adherencia.

### Por qué ahora
Fase 1 está viva y el hábito de escribirle al bot ya existe. La rutina diaria es justamente el caso de uso de **fricción cero + proactividad** que justifica el stack: "ya me duché" desde Telegram, y a las 7am el briefing ya sabe qué falta. Además, `dificultad` en `pendientes` es un dato que el usuario quiere capturar ya, y aprovechar la misma migración evita dos toques a la base productiva.

### Cómo se ve el éxito
1. El usuario describe su rutina **una vez** en lenguaje natural y queda registrada en bloques + ítems.
2. Dice *"ya me duché"* y el ítem correcto queda marcado **hoy**, sin que el modelo adivine ningún id.
3. El briefing de las 7am (job **ya registrado**, no uno nuevo) incluye la rutina del día además de pendientes y gym.
4. Al día siguiente el checklist aparece limpio **sin ningún job de reset** — porque no hay flag que resetear.
5. Pregunta *"¿cómo vengo con mi rutina este mes?"* y recibe **porcentajes calculados en SQL**, no estimados por el LLM.
6. La migración corre contra la `vida.db` productiva **sin recrearla y sin perder una sola fila**.

---

## 2. Scope

### En alcance

**D-0. Mecanismo de migración incremental (precondición bloqueante)**
- Hoy `_ensure_schema()` (`bin/vida.py:152`) solo aplica `schema.sql` si la tabla `schema_version` **no existe**. En producción existe, con `version = 1` → cualquier `CREATE TABLE IF NOT EXISTS` nuevo en `schema.sql` **nunca se ejecutaría**.
- Se introduce migración versionada: leer `MAX(version)` de `schema_version`, aplicar en orden los bloques pendientes, insertar la nueva versión. Este cambio lleva la base a **`schema_version = 2`**.
- Es **precondición de todo lo demás**: sin esto, nada de lo siguiente aterriza en la base real.

**D-1. `pendientes`: columna `dificultad`**
- `ALTER TABLE pendientes ADD COLUMN dificultad TEXT CHECK (dificultad IS NULL OR dificultad IN ('facil','media','dificil'))`, nullable, default `NULL`.
- **No** se agrega `urgencia`: eso ya es `prioridad` (`alta`/`media`/`baja`). Se reutiliza, no se duplica ni se renombra.

**D-2. Tres tablas nuevas (patrón log append-only)**
- `rutina_bloques` — bloques de alto nivel (`nombre`, `hora_objetivo`, `orden`, `activo`).
- `rutina_items` — sub-actividades por bloque (`bloque_id`, `nombre`, `orden`, `activo`) — `activo` permite desactivar sin perder historial.
- `rutina_completado` — **log append-only**: una fila por (ítem, día) completado, `UNIQUE (item_id, fecha)`.
- Precedente: `entrenamientos` (log de series), no un flag mutable. El "reset diario" sale gratis: un día nuevo simplemente no tiene filas.

**D-3. Grupo de subcomandos `rutina` en `vida.py` (no un `daily.py`)**
| Subcomando | Qué hace |
|---|---|
| `rutina bloque add` | Alta de bloque |
| `rutina item add` | Alta de ítem dentro de un bloque |
| `rutina today` | Checklist combinado: ítems de hoy con `hecho_hoy` + pendientes abiertos, en un solo JSON determinista |
| `rutina done` | Marca un ítem como hecho hoy (insert en el log) |
| `rutina historial` | `--fecha <fecha o relativo>` **o** `--desde`/`--hasta`; devuelve `rutina_completado` + `pendientes.completado_en` de ese día/rango |
| `rutina stats` | `--desde`/`--hasta`; tasas de cumplimiento por bloque e ítem, calculadas en SQL/Python |

**D-4. Skill nueva `skills/rutina-diaria/SKILL.md`** (separada de `agenda-personal`)
- Flujo de setup: el usuario describe la rutina en lenguaje natural → la skill la traduce a llamadas `rutina bloque add` / `rutina item add`.
- Interacción diaria: *"ya me duché"* → resolver id vía `rutina today` → `rutina done`. **Nunca** adivinar un id (mismo guardrail que `pendiente done`).
- Bloque **Nunca**: nunca inventar estado de cumplimiento, nunca calcular porcentajes por su cuenta, siempre leerlos del JSON de `rutina today` / `rutina stats`.

**D-5. Extender el cron de briefing 7am existente** (`ops/cron-jobs.md §5.1`)
- El job ya registrado suma `rutina today` a `pendiente today` + `gym progress`. Se **edita** el job existente, no se crea uno paralelo.

**D-6. Cron semanal nuevo de adherencia** (lunes, gemelo de `§5.4`)
- Resumen de `rutina stats` de la semana anterior, leyendo los porcentajes tal cual vienen del JSON.

### Fuera de alcance
- **Recordatorios/alertas cerca de `hora_objetivo`** de cada ítem. Es la extensión futura obvia — `hora_objetivo` se guarda justamente para habilitarla — pero no se implementa acá.
- Cualquier UI fuera de la conversación por Telegram.
- Editar/reordenar bloques o ítems por cualquier vía que no sea re-registro en lenguaje natural (no hay `rutina bloque edit`/`move` en este alcance).
- Fase 2 completa (puente a Claude Code, TTS, etc.) — sigue fuera, igual que en Fase 1.

---

## 3. Capabilities

Convención del repo: **un `spec.md` por change** (no hay `openspec/specs/`). Estas son las secciones que `sdd-spec` debe producir dentro de `openspec/changes/daily-routine-tracker/spec.md`.

### New Capabilities
- `schema-migration`: mecanismo de migración incremental versionado sobre `vida.db` (v1 → v2).
- `rutina-diaria`: modelo de datos, subcomandos CLI y skill del tracker de rutina.
- `rutina-stats`: reporte determinista de tasas de cumplimiento por bloque/ítem en un rango.

### Modified Capabilities
- `Structured Data Layer` (spec Fase 1 §2): `pendientes` gana `dificultad`; el contrato "CLI is the only data gateway" se extiende al dominio rutina; la asunción de bootstrap idempotente greenfield queda reemplazada por migración versionada.
- `Proactivity (Cron)` (spec Fase 1 §5): el briefing 7am incorpora rutina; se suma un job semanal de adherencia.

---

## 4. Approach + rationale

### 4.1 Migración versionada, no recreate
Se compara la versión almacenada con la versión objetivo del código y se aplican bloques `-- migration: N` en orden, cada uno en una transacción, con el `INSERT INTO schema_version` como último paso del bloque. `schema.sql` sigue siendo el bootstrap de base fresca (y debe quedar equivalente al resultado de aplicar todas las migraciones, para que una base nueva y una migrada sean idénticas).
*Rationale*: la alternativa "borrá y recreá la db" destruye datos reales de producción; la alternativa "corré el ALTER a mano por SSH" convierte el esquema en algo que solo existe en la cabeza del operador y rompe el restore drill (restaurar un backup viejo dejaría una base sin migrar). La migración tiene que vivir en el mismo código que abre la conexión, correr sola, y ser idempotente — igual de "sin paso de migrate separado" que hoy, pero ahora de verdad.

### 4.2 Extender `vida.py`, no forkear a `daily.py`
*Rationale*: `design.md D2` define **una sola puerta de datos** precisamente para minimizar la superficie donde el modelo puede alucinar. Un segundo CLI duplicaría esa superficie de confianza, exigiría un segundo bind mount, un segundo contrato JSON que el modelo tiene que aprender, y una segunda `db` que rompe el single-source-of-truth (`rutina today` necesita leer `pendientes` — con dos bases, ese JOIN no existe). El patrón establecido es *un CLI, múltiples dominios*; `rutina` es un dominio más, como `gasto` o `gym`. No hay justificación técnica para forkear: es stdlib, mismas restricciones, misma base.

### 4.3 Log append-only en vez de flag mutable
*Rationale*: un `hecho INTEGER` en `rutina_items` obligaría a un job de reset a medianoche — un componente nuevo, con timezone propio, que puede fallar silenciosamente y dejar el checklist en un estado mentiroso. Con el log, "hoy" es simplemente *ausencia de fila con `fecha = hoy`*: cero código, cero cron, cero modo de fallo. Y como efecto colateral, `historial` y `stats` salen gratis del mismo dato — con el flag mutable el historial habría que inventarlo aparte.

### 4.4 `prioridad` ya es urgencia; `dificultad` es un eje nuevo
*Rationale*: renombrar `prioridad` → `urgencia` sería un breaking change contra la skill `agenda-personal` viva y contra datos existentes, a cambio de puro gusto semántico. `dificultad` (esfuerzo) sí es información que hoy no existe en ninguna columna, y es lo que permite después responder *"¿qué pendiente fácil puedo cerrar en 10 minutos?"*.

### 4.5 Skill separada, no ampliar `agenda-personal`
*Rationale*: convención de una skill por dominio ya establecida en Fase 1. Las frases gatillo no se solapan (*"anotá que tengo que…"* vs *"ya me duché"*) y el modelo mental es distinto: to-do que se cierra para siempre vs checklist que se re-evalúa cada día. Meter ambos en un archivo aumenta la chance de que el agente elija el subcomando equivocado.

### 4.6 Determinismo por contrato (D11)
Ningún porcentaje ni conteo lo produce el LLM. `rutina stats` devuelve números ya calculados y la skill/cron solo los lee — el mismo principio que hace confiables a `gasto report` y `gym progress`.

---

## 5. "Fase 0" — verificación previa

Este cambio **no tiene incógnitas de infraestructura** como sí las tenía Fase 1 (GPU, endpoint LLM, whitelist, destino de backup). Todo el stack ya está probado y corriendo. Queda **una sola precondición dura**:

- [ ] **P0.1 — Ensayo de migración contra una COPIA de la `vida.db` real de producción.**
  Copiar `vida.db` desde labia03 (o tomar el snapshot que ya produce `ops/db-snapshot.sh`), correr la migración contra esa copia y verificar: `schema_version = 2`, las tres tablas nuevas creadas, `pendientes.dificultad` presente y en `NULL` para todas las filas existentes, `PRAGMA integrity_check` OK, y **conteo de filas idéntico** en `gastos`, `entrenamientos`, `tarjetas`, `contactos`, `pendientes` antes y después.
  *Nunca* se toca la base real hasta que esto pase.
- [ ] **P0.2 — Backup restic fresco verificado** inmediatamente antes de aplicar la migración en producción (< 24h). Es la red de rollback real.

Nota operativa **fuera del alcance de este cambio**: durante pruebas se detectó que el cron de briefing 7am de Fase 1 **nunca quedó registrado** en labia03 — solo se registró un job de smoke test que después se borró siguiendo el propio runbook (`ops/cron-jobs.md §5.5`). Es un hueco operativo de Fase 1, no de código, y el usuario lo cierra registrando el job por Telegram. Se documenta acá solo porque **D-5 asume que ese job existe** para poder extenderlo.

---

## 6. Affected Areas

| Área | Impacto | Qué cambia |
|---|---|---|
| `asistente_personal/data/schema.sql` | Modified | Bloques de migración versionados; 3 tablas nuevas; `dificultad` en `pendientes`; `schema_version = 2` |
| `asistente_personal/bin/vida.py` | Modified | `_ensure_schema()` → migración incremental; grupo de subcomandos `rutina` (6 subcomandos) |
| `asistente_personal/skills/rutina-diaria/SKILL.md` | New | Skill de rutina diaria (setup + interacción + guardrails) |
| `asistente_personal/ops/cron-jobs.md` | Modified | §5.1 extendido con `rutina today`; nueva §5.6 (adherencia semanal) |
| `asistente_personal/tests/test_vida.py` | Modified | Tests de migración (v1→v2 sobre db sintética) y de `rutina *` |
| `openspec/changes/hermes-personal-assistant/design.md` | Referencia | §13 "no data migration — greenfield" queda superado; se anota, no se reescribe el change cerrado |

---

## 7. Riesgos

| Riesgo | Prob. | Mitigación |
|---|---|---|
| La migración corrompe o pierde datos de la `vida.db` productiva | Baja | P0.1 (ensayo sobre copia + conteo de filas) y P0.2 (backup fresco) son bloqueantes |
| `schema.sql` (bootstrap fresco) y el resultado de las migraciones divergen | Media | Test que compara el esquema de una db bootstrapeada contra una db v1 migrada a v2 |
| Migración parcial por crash a mitad → estado inconsistente | Baja | Cada bloque de migración en una transacción; el bump de `schema_version` es el último paso del bloque |
| Dos procesos (`cron` + Telegram) abren la db a la vez durante la migración | Baja | WAL + `busy_timeout` ya activos; aplicar la migración con el stack detenido |
| El agente inventa ids de ítems al marcar completado | Media | Guardrail explícito en la skill: siempre resolver vía `rutina today` primero |
| El usuario registra una rutina enorme y el JSON de `rutina today` se vuelve ruidoso | Baja | `activo` en bloques e ítems; `rutina today` filtra por `activo = 1` |
| Scope creep hacia recordatorios por `hora_objetivo` | Media | Explícitamente fuera de alcance; la columna se guarda pero no se usa para alertar |

---

## 8. Rollback Plan

1. **Antes de migrar**: backup restic fresco verificado + copia local de `vida.db` (P0.2).
2. **Si la migración falla en el ensayo (P0.1)**: no se toca producción. Costo cero.
3. **Si falla en producción**: detener el stack, restaurar `vida.db` desde la copia local o desde restic (`backup/restore.sh`), y desplegar la versión anterior de `vida.py` (revert del commit / branch anterior). La base vuelve a `schema_version = 1` y Fase 1 sigue operando intacta.
4. **Rollback parcial (código nuevo, datos ya migrados)**: la migración es **aditiva** — el `vida.py` de Fase 1 ignora las tablas y la columna nuevas. Es decir, revertir solo el código es seguro y no requiere tocar la base.
5. **Rollback de la skill/cron**: borrar `skills/rutina-diaria/` (o `git revert` en el repo local de skills) y re-registrar el job 7am con su texto original de `§5.1`.

---

## 9. Dependencies

- Fase 1 desplegada y funcionando en labia03 (`schema_version = 1`). ✅
- Backup restic operativo para P0.2 — depende de que **F0.5 de Fase 1 esté cerrada** (destino + passphrase offsite). Si sigue abierta, P0.2 se cubre con una copia local de `vida.db` fuera de labia03 como mínimo indispensable.
- Job de briefing 7am registrado en el bot (acción del usuario, ver §5) — bloquea solo D-5, no el resto.

---

## 10. Success Criteria

- [ ] La migración corre limpia contra una **copia** de la `vida.db` real: `schema_version = 2`, integridad OK, conteo de filas sin cambios (P0.1).
- [ ] Una `vida.db` fresca (bootstrap) y una `vida.db` v1 migrada producen **el mismo esquema**.
- [ ] `pendiente add --dificultad facil` persiste; los pendientes preexistentes quedan con `dificultad = NULL` y las skills de Fase 1 siguen funcionando sin cambios.
- [ ] El usuario describe su rutina en lenguaje natural una vez y `rutina today` devuelve los bloques e ítems correctos.
- [ ] *"ya me duché"* marca el ítem correcto para hoy, resolviendo el id vía `rutina today`, sin ids inventados.
- [ ] Al día siguiente, `rutina today` devuelve todo en `hecho_hoy: false` **sin ningún job de reset**.
- [ ] `rutina historial --fecha ayer` y `rutina historial --desde X --hasta Y` devuelven lo completado en ese día/rango (rutina + pendientes).
- [ ] `rutina stats --desde X --hasta Y` devuelve porcentajes por bloque e ítem calculados en SQL/Python; verificados contra un cálculo manual sobre datos de prueba.
- [ ] El briefing de las 7am incluye la rutina del día junto a pendientes y gym.
- [ ] El resumen semanal de adherencia llega los lunes.
- [ ] Suite de tests de `vida.py` en verde (los 47 existentes + los nuevos).

---

**Next**: `sdd-spec` y `sdd-design` (pueden correr en paralelo). El punto de diseño más caro es **D-0** (mecanismo de migración) — conviene resolverlo primero en `sdd-design`.
