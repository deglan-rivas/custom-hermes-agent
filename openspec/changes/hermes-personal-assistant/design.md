# Design: Asistente personal en Hermes Agent (Fase 1)

Change: `hermes-personal-assistant`
Reads: `proposal.md` (approved scope), `explore.md` (research), `PLAN.md` (baseline)
Scope: Fase 1 only. Fase 2 (puente a Claude Code), TTS y exposición pública están fuera.

> **Size note**: the sdd-design 800-word budget is intentionally exceeded. The phase brief
> explicitly requested column-level schema detail, concrete compose service definitions and
> script-level design. Detail is delivered as tables and code blocks, not prose.

---

## 1. Technical Approach

Three composed containers on `labia03`, **one writable state volume**, **zero inbound ports**,
and **two host-level watchdogs that depend on nothing inside the stack**.

The load-bearing idea is a strict split between **code** and **state**:

| Class | Lives in | Writable by agent? | Versioned by | Backed up by |
|---|---|---|---|---|
| Code (`vida.py`, `schema.sql`, compose, ops scripts, backup scripts) | project git repo, bind-mounted **read-only** into containers | No | project git (remote optional) | git |
| Agent-authored state (`skills/`, `config.yaml`, `state.db`, sessions, `vida.db`) | `~/.hermes` → `/opt/data` | Yes | local git repo scoped to `skills/` | restic |

That split is why the agent can rewrite its own skills without ever being able to rewrite the
data gate (`vida.py`) that keeps its numbers honest. It is also why "migrar en enero 2027" is
`git clone` + `restic restore` + `docker compose up`, with no third step to remember.

Everything numeric flows through `vida.py`, which returns JSON. The agent is allowed to *read*
those numbers aloud and never to compute them. Hermes' native FTS5 memory keeps soft context
(preferences, routine, tone) and is never asked to aggregate.

---

## 2. Architecture Decisions

| # | Decision | Alternatives rejected | Rationale |
|---|---|---|---|
| D1 | Official `nousresearch/hermes-agent` image, pinned by tag **and digest** | Custom `Dockerfile` running `install.sh` (PLAN.md) | Image is s6-supervised, treats `/opt/hermes` immutable and concentrates state in `/opt/data` — already the one-volume contract we need. A custom image would reimplement that worse and add rebuild maintenance. Digest pin because `latest` on a fast-moving agent runtime is an unannounced breaking change. |
| D2 | `vida.py` bind-mounted **read-only** at `/opt/data/bin/vida.py:ro`, not copied into the volume | Ship it inside the volume | If the data gate lives in writable state, `skill_manage` can edit it and the anti-hallucination guarantee evaporates. Read-only mount also keeps code out of restic and inside project git where diffs are reviewable. |
| D3 | Whisper via prebuilt `onerahmet/openai-whisper-asr-webservice:latest-gpu` (`ASR_ENGINE=faster_whisper`) | Custom Python service + Dockerfile | Same reasoning as D1: the HTTP wrapper around `faster-whisper` already exists, GPU tag included. Keeps Fase 1 at *zero* custom images. Internal network only, no published port. |
| D4 | `TZ=America/Lima` on every service | Wait for Hermes per-job timezone; hardcode UTC offsets in cron text | Hermes has **no** timezone concept (verified: zero mentions in `cron.md`/`configuration.md`, open feature requests). "7am" resolves to the container clock, which standard Linux `TZ` fully controls. One line, no feature dependency. Documented limitation: no per-job TZ. |
| D5 | Host cron + `curl` to Bot API for observability; state-file dedup with transition-only alerts | Hermes cron skill; healthcheck container; Prometheus/Grafana | A watchdog inside the stack dies with the stack, and "Hermes está muerto" is precisely the event to report. Transition-only alerting because a 15-min poller that alerts every run sends 96 messages/day and gets muted — a muted alert is no alert. |
| D6 | Separate `ops/.env.ops` (mode 600) holding **only** `TELEGRAM_TOKEN` + `TG_USER_ID` | Watchdogs read the main `.env` | Least privilege. The watchdogs never need restic credentials or the LLM key; a script that runs unattended every 15 minutes should not have them in its environment. |
| D7 | `~/.hermes/skills/` = local commit-only git repo; auto-commit by host cron every 15 min | Version all of `~/.hermes/`; rely on restic only; require a Hermes post-approval hook | `state.db` is binary and constantly written — it would bloat the repo and drown the log in noise. Restic is coarse (daily, no messages, restore = full volume mount). Git gives `git log -p` and `git revert` on the only files that need them. Cron rather than a hook because the post-approval hook mechanism is unverified; a hook is a later optimization, not the guarantee. |
| D8 | Online consistent SQLite snapshots on the host via `python3` `sqlite3.backup()` at 03:20, restic at 03:30 | Back up live `.db` files only; exclude `-wal`/`-shm`; stop the stack nightly | Copying a WAL-mode DB mid-write can capture a torn state, and excluding `-wal` makes it *unrecoverable* rather than merely stale. The stdlib backup API produces a consistent copy while writers continue — no downtime, no extra dependency, and `restore.sh` can fall back to the snapshot when `PRAGMA integrity_check` on the live file fails. |
| D9 | `${HERMES_DATA:-./state/hermes}` as the volume source | Hardcode `~/.hermes` | The restore drill on the laptop becomes `HERMES_DATA=./restore-drill/hermes docker compose up -d` with an unmodified compose file. A drill that requires editing production config is a drill that tests the wrong thing. |
| D10 | Expense `categoria` and exercise `ejercicio` as free `TEXT`, canonical vocabulary documented in `sobre-mi/SKILL.md` | Lookup tables with FK | Proposal fixes five tables; a sixth is scope creep. Free text with a documented vocabulary keeps capture friction at zero (the real failure mode is abandonment, not a typo'd category). Tradeoff accepted: `gasto report` can show near-duplicate categories; mitigated by a `--categorias` listing the skill reads before writing. |
| D11 | Progression increments as a constant map inside `vida.py` (default `2.5 kg`, compound lifts `5 kg`) | LLM-computed target; per-exercise config table | The whole point of `vida.db` is that no number is generated by a model. A deterministic Python rule is auditable and testable; a table is D10's scope creep again. |
| D12 | `crontab` (`/etc/cron.d/hermes-ops`) as the primary timer, `ops/systemd/` units as an alternative | `systemd --user` timers only | `systemd --user` needs `loginctl enable-linger` or the timers die at logout — an extra prerequisite on a machine we do not own. F0.6 already verifies `cron`. |

---

## 3. Data Flow

```
Celular ──voz/texto──► api.telegram.org ◄──long polling saliente── hermes
                                                                     │
                    ┌────────────────────────────────────────────────┤
                    │ voz: POST /asr                                 │ texto
                    ▼                                                ▼
              whisper (GPU, red interna)                    skill match (SKILL.md)
                    │ texto transcrito                              │
                    └──────────────────────────────────────────────► │
                                                                     ▼
                                                       vida.py (ro) ──► vida.db
                                                                     │  JSON
                                    respuesta al usuario ◄────────────┘
                                    (lee números, no los calcula)

cron nativo Hermes (TZ=America/Lima, tick 60s)
   └─ 07:00 briefing ─► vida.py pendiente today + gym progress + tarjeta next ─► Telegram

03:20 host cron ─► db-snapshot.sh (sqlite3.backup) ─► ~/.hermes/backup/*.snapshot
03:30 restic     ─► rclone:remoto cifrado (7d/4w/12m) ─► ./state/backup/last-success

*/15 host cron ─► check-stack.sh  ──┐
09:15 host cron ─► check-backup.sh ─┼─► notify.sh ──► curl api.telegram.org
*/15 host cron ─► skills-autocommit.sh (git commit si hay cambios)
                                    └── NO toca hermes ni docker compose para alertar
```

The alerting path crosses zero components it monitors. That is the only property that makes it
an alerting path and not a second thing to check on.

---

## 4. File Changes

All paths relative to repo root. `asistente_personal/` follows PLAN.md's naming.

| File | Action | Description |
|---|---|---|
| `asistente_personal/docker-compose.yml` | Create | 3 services (§5). No `ports:`, no custom images. |
| `asistente_personal/.env.template` | Create | `LLM_BASE_URL`, `LLM_API_KEY`, `TELEGRAM_TOKEN`, `TG_USER_ID`, `HERMES_DATA`, `RESTIC_REPOSITORY`, `RESTIC_PASSWORD`, `RCLONE_REMOTE`. Values are placeholders + comment pointing at Fase 0. |
| `asistente_personal/.gitignore` | Create | `.env`, `ops/.env.ops`, `secrets/`, `state/`, `restore-drill/`, `*.db`, `*.db-wal`, `*.db-shm`, `__pycache__/` |
| `asistente_personal/config/config.yaml.template` | Create | Hermes `config.yaml` skeleton with `${VAR}` placeholders: provider/base_url/api_key, telegram channel + allowlist, `write_approval: true`. Exact keys filled from F0.1/F0.3 output. |
| `asistente_personal/ops/render-config.sh` | Create | One-shot bootstrap: `envsubst` template → `$HERMES_DATA/config.yaml` if absent. Never overwrites (the agent owns that file after first boot). |
| `asistente_personal/data/schema.sql` | Create | 5 tables + `schema_version` (§6). Idempotent (`IF NOT EXISTS`). |
| `asistente_personal/bin/vida.py` | Create | stdlib CLI, JSON-only stdout (§7). |
| `asistente_personal/tests/test_vida.py` | Create | `unittest` over a temp DB; date math is the target (§9). |
| `asistente_personal/skills/registrar-gasto/SKILL.md` | Create | §8 |
| `asistente_personal/skills/gym-tracker/SKILL.md` | Create | §8 |
| `asistente_personal/skills/tarjetas/SKILL.md` | Create | §8 |
| `asistente_personal/skills/agenda-personal/SKILL.md` | Create | §8 |
| `asistente_personal/skills/sobre-mi/SKILL.md` | Create | §8 — seed of the living doc; copied into the volume once, then owned by the agent. |
| `asistente_personal/ops/notify.sh` | Create | Shared Telegram sender (§10). |
| `asistente_personal/ops/check-stack.sh` | Create | Watchdog A (§10). |
| `asistente_personal/ops/check-backup.sh` | Create | Watchdog B (§10). |
| `asistente_personal/ops/db-snapshot.sh` | Create | Online consistent SQLite copies (D8). |
| `asistente_personal/ops/skills-autocommit.sh` | Create | §11 |
| `asistente_personal/ops/hermes-ops.cron` | Create | `/etc/cron.d` fragment (§10). |
| `asistente_personal/ops/systemd/*.{service,timer}` | Create | Alternative to cron (D12). |
| `asistente_personal/ops/.env.ops.template` | Create | Only `TELEGRAM_TOKEN` + `TG_USER_ID` (D6). |
| `asistente_personal/backup/backup.sh` | Create | On-demand backup + retention + `restic check` (§12). |
| `asistente_personal/backup/restore.sh` | Create | Restore + integrity verification + drill instructions (§12). |
| `asistente_personal/backup/PASSPHRASE.md` | Create | **Where the passphrase lives, never the passphrase** (§12). |
| `asistente_personal/README.md` | Create | Quick path: Fase 0 checklist → bootstrap → verification. Records the pinned image digest. |
| `PLAN.md` | Modify | Strike the `Dockerfile` line; point to this design as current truth. |

**Directory layout**

```
asistente_personal/
├── docker-compose.yml
├── .env.template            .gitignore            README.md
├── config/config.yaml.template
├── data/schema.sql
├── bin/vida.py
├── tests/test_vida.py
├── skills/{registrar-gasto,gym-tracker,tarjetas,agenda-personal,sobre-mi}/SKILL.md
├── ops/{notify,check-stack,check-backup,db-snapshot,skills-autocommit,render-config}.sh
│   ├── .env.ops.template     hermes-ops.cron     systemd/
├── backup/{backup.sh,restore.sh,PASSPHRASE.md}
├── secrets/rclone.conf       (gitignored, mode 600)
└── state/                    (gitignored — runtime only)
    ├── hermes/               → /opt/data   (default HERMES_DATA)
    └── backup/last-success
```

---

## 5. Compose Service Definitions

```yaml
name: asistente-personal

x-log: &log
  driver: json-file
  options: { max-size: "10m", max-file: "3" }

networks:
  asistente: { driver: bridge }

volumes:
  whisper-cache:

services:
  hermes:
    image: nousresearch/hermes-agent:latest   # replace with @sha256:… after F0.1
    container_name: hermes
    restart: unless-stopped
    env_file: [.env]
    environment:
      TZ: America/Lima                        # D4 — sole source of "7am"
      VIDA_DB: /opt/data/data/vida.db
      WHISPER_URL: http://whisper:9000
    volumes:
      - ${HERMES_DATA:-./state/hermes}:/opt/data          # D9 — único volumen con estado
      - ./bin/vida.py:/opt/data/bin/vida.py:ro            # D2 — data gate inmutable
      - ./data/schema.sql:/opt/data/bin/schema.sql:ro
    depends_on:
      whisper: { condition: service_healthy, required: false }
    healthcheck:
      test: ["CMD-SHELL", "pgrep -f hermes >/dev/null 2>&1 || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 120s
    logging: *log
    networks: [asistente]
    # sin `ports:` — long polling saliente, admin por Tailscale SSH

  whisper:
    image: onerahmet/openai-whisper-asr-webservice:latest-gpu
    container_name: whisper
    restart: unless-stopped
    environment:
      TZ: America/Lima
      ASR_ENGINE: faster_whisper
      ASR_MODEL: large-v3
      ASR_DEVICE: cuda
      ASR_COMPUTE_TYPE: float16
      MODEL_IDLE_TIMEOUT: "600"        # libera VRAM entre notas de voz
    volumes:
      - whisper-cache:/root/.cache
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]      # única GPU passthrough del stack
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://localhost:9000/docs >/dev/null || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 300s               # descarga inicial de large-v3
    logging: *log
    networks: [asistente]
    # sin `ports:` — solo alcanzable desde la red interna del compose

  restic:
    image: mazzolino/restic:1.6
    container_name: restic
    restart: unless-stopped
    env_file: [.env]
    environment:
      TZ: America/Lima
      RUN_ON_STARTUP: "false"
      BACKUP_CRON: "0 30 3 * * *"                       # 03:30 Lima, 10 min tras db-snapshot
      RESTIC_REPOSITORY: ${RESTIC_REPOSITORY}           # rclone:${RCLONE_REMOTE}:hermes-backup
      RESTIC_PASSWORD: ${RESTIC_PASSWORD}
      RESTIC_BACKUP_SOURCES: /data
      RESTIC_BACKUP_ARGS: "--tag auto --host labia03"   # D8: NO se excluyen -wal/-shm
      RESTIC_FORGET_ARGS: "--keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune"
      POST_COMMANDS_SUCCESS: "date -Iseconds > /status/last-success"
    volumes:
      - ${HERMES_DATA:-./state/hermes}:/data:ro          # read-only: backup no muta estado
      - ./state/backup:/status                           # sentinel escribible, fuera del backup
      - ./secrets/rclone.conf:/root/.config/rclone/rclone.conf:ro
    logging: *log
    networks: [asistente]
```

Notes: `whisper` is `required: false` so an F0.2 failure degrades to "Fase 1 sin voz" instead of
blocking boot (proposal gate). The sentinel lives *outside* the backed-up volume on purpose —
it is host-observable state about the backup, not data to restore.

---

## 6. `vida.db` Schema (`data/schema.sql`)

Global: `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;`. Every table carries
`creado_en TEXT NOT NULL DEFAULT (datetime('now','localtime'))` and, where user-originated,
`fuente TEXT NOT NULL DEFAULT 'telegram' CHECK(fuente IN ('telegram','voz','cli','cron'))`.
Dates are ISO-8601 `TEXT` (`YYYY-MM-DD`) — SQLite has no date type and ISO text sorts correctly.

### `gastos`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `fecha` | TEXT | NOT NULL, DEFAULT `date('now','localtime')` | ISO date of the expense, not of capture |
| `monto` | REAL | NOT NULL, CHECK `monto > 0` | Refunds are not negative expenses; out of scope |
| `moneda` | TEXT | NOT NULL DEFAULT `'PEN'`, CHECK in (`PEN`,`USD`) | |
| `categoria` | TEXT | NOT NULL | Free text, vocabulary in `sobre-mi` (D10) |
| `descripcion` | TEXT | NULL | Raw user phrase — the audit trail for a miscategorisation |
| `metodo_pago` | TEXT | CHECK in (`efectivo`,`debito`,`credito`,`yape`,`plin`,`transferencia`) | NULL allowed |
| `tarjeta_id` | INTEGER | REFERENCES `tarjetas(id)` ON DELETE SET NULL | Only meaningful when `metodo_pago='credito'` |
| `creado_en`, `fuente` | TEXT | see global | |

Indexes: `idx_gastos_fecha(fecha)`, `idx_gastos_cat_fecha(categoria, fecha)`.

### `entrenamientos` — one row per **set**, not per session

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `fecha` | TEXT | NOT NULL DEFAULT `date('now','localtime')` | |
| `ejercicio` | TEXT | NOT NULL | Stored lowercase+trimmed by `vida.py`; `press banca` ≠ `Press Banca` would silently split progression |
| `serie` | INTEGER | NOT NULL, CHECK `serie >= 1` | Auto-assigned as `max(serie)+1` for that day+exercise if omitted |
| `peso` | REAL | NOT NULL, CHECK `peso >= 0` | kg; 0 valid for bodyweight |
| `repeticiones` | INTEGER | NOT NULL, CHECK `repeticiones >= 1` | |
| `rpe` | REAL | NULL, CHECK `rpe BETWEEN 1 AND 10` | |
| `notas` | TEXT | NULL | |
| `creado_en`, `fuente` | TEXT | see global | |

`UNIQUE(fecha, ejercicio, serie)` — a retried voice note must not double-log. Row-per-set is
what makes `gym progress` a real query instead of parsing `"3x8x60"` out of a text blob.
Index: `idx_entren_ejercicio_fecha(ejercicio, fecha DESC)`.

### `tarjetas`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `nombre` | TEXT | NOT NULL UNIQUE | e.g. `BCP Visa` |
| `banco` | TEXT | NULL | |
| `dia_corte` | INTEGER | NOT NULL, CHECK 1–31 | Day-of-month, not a date |
| `dia_pago` | INTEGER | NOT NULL, CHECK 1–31 | May land in the following month; `vida.py` resolves |
| `moneda` | TEXT | NOT NULL DEFAULT `'PEN'` | |
| `linea_credito` | REAL | NULL, CHECK `> 0` | |
| `alerta_dias_antes` | INTEGER | NOT NULL DEFAULT 3, CHECK 0–15 | Per-card, feeds the cron alert |
| `activa` | INTEGER | NOT NULL DEFAULT 1, CHECK in (0,1) | Soft delete keeps historical `gastos.tarjeta_id` valid |
| `creado_en` | TEXT | | |

Storing *days* rather than dates is deliberate: cut/payment days are the stable fact, and
generating the next real date (clamped to month length, rolling over when `dia_pago < dia_corte`)
belongs in one tested function instead of in every row.

### `contactos`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `nombre` | TEXT | NOT NULL UNIQUE | |
| `cumple_mes` | INTEGER | NOT NULL, CHECK 1–12 | |
| `cumple_dia` | INTEGER | NOT NULL, CHECK 1–31 | |
| `cumple_anio` | INTEGER | NULL, CHECK 1900–2100 | Nullable: most birthdays are known without a year; a `0000-` sentinel date breaks `date()` |
| `relacion` | TEXT | NULL | `familia`, `amigo`, `trabajo` |
| `alerta_dias_antes` | INTEGER | NOT NULL DEFAULT 7, CHECK 0–60 | |
| `notas` | TEXT | NULL | Gift ideas — soft context that still deserves a row |
| `creado_en` | TEXT | | |

Month/day split rather than a date column so Feb 29 birthdays and unknown years both survive.

### `pendientes`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `titulo` | TEXT | NOT NULL | |
| `detalle` | TEXT | NULL | |
| `fecha_objetivo` | TEXT | NULL | NULL = someday/backlog, excluded from the briefing |
| `hora` | TEXT | NULL, `HH:MM` | |
| `prioridad` | TEXT | NOT NULL DEFAULT `'media'`, CHECK in (`alta`,`media`,`baja`) | |
| `estado` | TEXT | NOT NULL DEFAULT `'abierto'`, CHECK in (`abierto`,`hecho`,`cancelado`) | |
| `recurrencia` | TEXT | NULL | `diaria` \| `semanal:lun` \| `mensual:15`. Interpreted by `vida.py`, never by the model |
| `completado_en` | TEXT | NULL | |
| `creado_en`, `fuente` | TEXT | see global | |

Index: `idx_pend_estado_fecha(estado, fecha_objetivo)`.

### `schema_version`

`version INTEGER PRIMARY KEY`, `aplicado_en TEXT NOT NULL DEFAULT (datetime('now','localtime'))`.
Fase 1 inserts `1`. Present from day one because the alternative is discovering in month four
that you cannot tell which shape a restored `vida.db` has.

---

## 7. `vida.py` CLI Design

**Constraints**: Python 3 stdlib only (`argparse`, `sqlite3`, `json`, `datetime`, `calendar`,
`os`, `sys`). No ORM, no third-party deps — the whole point is that a restore on any machine
with `python3` works with no install step.

**Invariants**

- **JSON only**, single object, always on stdout. Human text goes nowhere; the caller is an LLM.
- Success: `{"ok": true, "action": "<cmd.sub>", "data": {…}}` → exit `0`.
- Failure: `{"ok": false, "action": "…", "error": "<message>", "codigo": "<slug>"}` → exit `1`.
  Errors are JSON too: a skill that gets a stack trace on stderr will improvise a reply.
- DB path from `VIDA_DB`, default `/opt/data/data/vida.db`. Creates parent dirs; applies
  `schema.sql` when `schema_version` is missing (idempotent bootstrap, no separate migrate step).
- `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000`.
- All dates default to `localtime`, which is Lima because of D4. No UTC anywhere in this file.
- Every write is a single transaction; `gym log` of multiple sets is one atomic call.

**Subcommands**

| Command | Required flags | Optional flags | `data` payload |
|---|---|---|---|
| `gasto add` | `--monto`, `--categoria` | `--descripcion --fecha --moneda --metodo --tarjeta --fuente` | inserted row + `id` |
| `gasto report` | one of `--mes YYYY-MM` \| `--desde/--hasta` | `--categoria --limite` | `total`, `moneda`, `por_categoria[]`, `rango`, `n_gastos` |
| `gasto categorias` | — | `--desde` | distinct categories + counts (skills read this before writing — D10 mitigation) |
| `gym log` | `--ejercicio`, `--peso`, `--reps` | `--serie --rpe --fecha --notas --fuente` | inserted set(s); `--serie` auto = `max+1` |
| `gym progress` | `--ejercicio` | `--limite` (default 5 sessions) | `historial[]` (fecha, top set, volumen), `ultimo_top_set`, `sugerencia{peso,reps,razon}` |
| `gym resumen` | — | `--desde --hasta` | volume per exercise, sessions counted |
| `tarjeta add` | `--nombre`, `--dia-corte`, `--dia-pago` | `--banco --moneda --linea --alerta-dias` | inserted row |
| `tarjeta next` | — | `--dias` (default 10), `--nombre` | per card: `proximo_corte`, `proximo_pago` (real ISO dates), `dias_restantes`, `alertar` (bool), `gasto_ciclo_actual` |
| `cumple add` | `--nombre`, `--mes`, `--dia` | `--anio --relacion --alerta-dias --notas` | inserted row |
| `cumple upcoming` | — | `--dias` (default 30) | `nombre`, `fecha_este_anio`, `dias_restantes`, `edad_a_cumplir` (null if no year) |
| `pendiente add` | `--titulo` | `--fecha --hora --prioridad --detalle --recurrencia` | inserted row |
| `pendiente today` | — | `--incluir-vencidos` (default true) | open items with `fecha_objetivo <= hoy` + due recurrences, ordered by priority then hour |
| `pendiente done` | `--id` | — | updated row |
| `health` | — | — | `db_path`, `schema_version`, per-table row counts, `integrity_ok` — also consumable by ops |

**`sugerencia` rule (D11)** — deterministic, in code, documented in the payload's `razon`:

```
INCREMENTO = {"sentadilla": 5.0, "peso muerto": 5.0, "prensa": 5.0, "hip thrust": 5.0}
DEFAULT    = 2.5
if all sets of the last session for this exercise hit >= their target reps:
    sugerencia = ultimo_top_set.peso + INCREMENTO.get(ejercicio, DEFAULT)
    razon = "progresion: sesion anterior completa"
else:
    sugerencia = ultimo_top_set.peso            # repeat the weight
    razon = "repetir: sesion anterior incompleta"
if no history: sugerencia = null, razon = "sin historial"
```

`sugerencia: null` is a first-class outcome — the skill must then ask, not guess.

**Date helpers** (the only real logic, hence the only real tests): `clamp_dia(anio, mes, dia)`
(day 31 in February → last day), `proxima_fecha_de_dia(dia, desde)`, `resolver_ciclo_tarjeta`
(rolls `dia_pago` into the next month when `dia_pago < dia_corte`), `dias_hasta_cumple` (handles
year wrap: Dec 28 → Jan 3 is 6 days, not −359).

---

## 8. Skill Files (`~/.hermes/skills/`)

Each is a directory with a `SKILL.md`: YAML frontmatter (`name`, `description` carrying the
trigger phrases, since that description is what Hermes matches against) plus a body with a fixed
five-section shape. The seeds live in `asistente_personal/skills/` under project git and are
copied into the volume once at bootstrap; from then on the volume copy is the agent's, versioned
by the local git repo of §11.

**Mandatory sections in every SKILL.md**

1. **Cuándo se activa** — concrete example phrases, in Spanish, including voice-note phrasing.
2. **Comando exacto** — the literal `python3 /opt/data/bin/vida.py …` invocation. Copyable, not described.
3. **Mapeo de lenguaje natural → flags** — a table: phrase fragment → flag.
4. **Cómo responder** — read fields from the JSON `data` verbatim; confirm what was written.
5. **Nunca** — the guardrails.

The **Nunca** block is shared and non-negotiable:

> Nunca calcules totales, promedios, fechas ni pesos objetivo por tu cuenta — corré el comando y
> leé el campo. Nunca inventes un valor faltante: si falta `monto` o `ejercicio`, preguntá.
> Nunca escribas en `vida.db` por otra vía que `vida.py`. Si `ok` es `false`, decí el `error`
> textual; no reintentes en silencio ni asumas que se guardó.

**Per-skill responsibilities**

| Skill | Triggers on | Runs | Skill-specific instruction |
|---|---|---|---|
| `registrar-gasto` | "gasté/pagué/compré/me cobraron … soles/dólares en …" | `gasto add`; `gasto report` for questions; `gasto categorias` before choosing a category | Map to an existing category rather than coining a near-duplicate. Echo back `monto + categoria + fecha` so a wrong parse is caught in the same breath. If currency is unstated, assume `PEN` and say so. |
| `gym-tracker` | "hice/levanté …", "3x8 con 60", "¿cuánto me toca en …?" | one `gym log` per set; `gym progress` for "cuánto me toca" | Expand `3x8x60` into three `gym log` calls (or one multi-set call), never one row. For targets, quote `sugerencia.peso` and `razon`; when `sugerencia` is `null`, ask for a starting weight instead of inventing one. Normalise the exercise name to the vocabulary in `sobre-mi`. |
| `tarjetas` | "agregá la tarjeta …", "¿cuándo me cortan?", "¿cuánto debo?" | `tarjeta add`, `tarjeta next` | Report the resolved ISO date **and** `dias_restantes` — "el 15" is ambiguous, "el viernes 15 (en 3 días)" is not. Cut day and payment day must be captured separately; if the user gives only one, ask for the other. |
| `agenda-personal` | "recordame …", "¿qué tengo hoy?", "el cumple de … es el …", "ya lo hice" | `pendiente add/today/done`, `cumple add/upcoming` | Undated requests go in without a date rather than being dropped. Relative dates ("el martes") are resolved to ISO before the call. For "ya lo hice", resolve the `id` from `pendiente today` first — never guess an id. |
| `sobre-mi` | Any preference statement, or as context for the other four | none (it is data, not a caller) | Holds: routine and gym split, canonical expense-category vocabulary, default currency, timezone (`America/Lima`), alert lead times, tone preferences, exercise-name aliases. Also holds its own update protocol: when a stable new preference is learned, edit this file via `skill_manage`; with `write_approval: true` the edit is staged in `~/.hermes/pending/skills/` and must be approved. Volatile or one-off facts do **not** belong here — they belong in the corresponding `vida.db` table. |

That last line is the boundary that keeps this from rotting: `sobre-mi` is for what is true about
the user, `vida.db` is for what happened.

---

## 9. Testing Strategy

No test framework exists in the project (strict TDD disabled per `.atl/skill-registry.md`), so
tests are stdlib `unittest` and cheap on purpose.

| Layer | What | How |
|---|---|---|
| Unit | Date helpers: `clamp_dia` (Feb 31 → Feb 28/29), `resolver_ciclo_tarjeta` (`dia_pago < dia_corte` rollover, Dec→Jan), `dias_hasta_cumple` (year wrap), `sugerencia` (complete / incomplete / no history) | `tests/test_vida.py`, temp DB via `tempfile`, `python3 -m unittest` |
| Unit | Schema constraints actually bite: `monto <= 0` rejected, `UNIQUE(fecha,ejercicio,serie)` rejected, invalid `estado` rejected | Same file — assert `sqlite3.IntegrityError` |
| Contract | Every subcommand emits parseable JSON with `ok` on both success and failure; exit codes 0/1 | Table-driven: run each subcommand via `subprocess`, `json.loads(stdout)` |
| Integration | `docker compose config` validates; `docker compose up -d` reaches healthy; `vida.py health` from inside the container returns `integrity_ok: true`; whisper `/asr` transcribes a fixture OGG | Manual, scripted in README |
| E2E | The seven success criteria from `proposal.md` §1 — including a second Telegram user being ignored and the laptop restore drill | Manual checklist in README; the restore drill is the gate, not a nice-to-have |

---

## 10. Host-Level Observability

All three scripts run **on the host**, are `sh`-compatible, always `exit 0` (so cron stays quiet),
and source `ops/.env.ops` (mode 600, only the two Telegram vars — D6).

**`notify.sh`** — `notify.sh "<texto>"`:
`curl -fsS --max-time 15 -X POST "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage"
-d "chat_id=$TG_USER_ID" --data-urlencode "text=$1"`. No dependency on Docker, Hermes, or the
compose network. If `curl` itself fails it logs to `logger -t hermes-ops` — there is no third
channel and pretending otherwise would be theatre.

**Transition-only alerting (shared)** — each script keeps a one-word state file under
`/var/tmp/hermes-ops/<check>.state`. It notifies on `ok → bad` (the failure detail) and on
`bad → ok` (`"✅ recuperado"`), and stays silent while the state is unchanged. This is what makes
a 15-minute poller survivable.

**`check-stack.sh`** — every 15 min:

1. `cd` to the compose dir, `docker compose ps --format json`.
2. Parse with host `python3` (JSON parsing in `awk` is how you get a watchdog that lies). `jq` is
   not assumed present; `python3` is, and is already a prerequisite. If `python3` is missing the
   script alerts about *that*.
3. Expect `hermes` and `restic` to be `running`; `whisper` too unless `ops/.env.ops` sets
   `WHISPER_OPTIONAL=1` (the F0.2-degraded mode). If a `Health` field exists it must be `healthy`.
4. Any deviation, or a non-zero exit from `docker compose` itself (Docker daemon down), → alert
   naming the service and its state.

**`check-backup.sh`** — daily 09:15 (comfortably after the 03:30 window, so a failure is reported
in the morning rather than at 3am):

1. Run restic in a throwaway container reusing the compose env:
   `docker compose run --rm --entrypoint restic restic snapshots --json --latest 1`.
2. Alert if: the command exits non-zero (repo unreachable, wrong passphrase, rclone token expired
   — all real failure modes), the array is empty, or `time` of the latest snapshot is older than
   **26h** (24h schedule + 2h slack).
3. Cross-check `state/backup/last-success`: if the sentinel is fresh but no snapshot exists, the
   alert says so explicitly — that combination means the post-command ran while the backup did not.

**`ops/hermes-ops.cron`** (installed to `/etc/cron.d/hermes-ops`, `TZ` set so the times are Lima):

```cron
SHELL=/bin/sh
PATH=/usr/local/bin:/usr/bin:/bin
CRON_TZ=America/Lima
*/15 *  * * *  user  /srv/asistente_personal/ops/check-stack.sh
*/15 *  * * *  user  /srv/asistente_personal/ops/skills-autocommit.sh
20   3  * * *  user  /srv/asistente_personal/ops/db-snapshot.sh
15   9  * * *  user  /srv/asistente_personal/ops/check-backup.sh
```

`ops/systemd/` ships the same four as `.service` + `.timer` pairs (`OnCalendar`, `Persistent=true`)
for the case where F0.6 lands on systemd. Only one of the two mechanisms is installed — never both.

---

## 11. Git Versioning of `~/.hermes/skills/`

**Setup** (bootstrap, once): `git init` in `$HERMES_DATA/skills`, with `git config --local
user.name "hermes-autocommit"` and `user.email "hermes@labia03.local"` — local config so the
script never depends on a global identity that may not exist for the cron user. **No remote.**
The `.git/` sits inside the volume restic already covers, so this adds a history without adding a
backup target.

**`ops/skills-autocommit.sh`**

```sh
cd "$SKILLS_DIR" || exit 0
[ -d .git ] || exit 0                       # nunca auto-init desde cron
git add -A
git diff --cached --quiet && exit 0         # sin cambios, sin commit vacío
git commit -q -m "auto: skills snapshot $(date -Iseconds)"
```

**Triggers**: (a) host cron every 15 min — the guaranteed path; (b) optionally invoked right after
a `write_approval` approval, *if* F0 confirms a post-approval hook exists. Cron is the contract and
the hook is only latency reduction, because designing around an unverified hook is how you end up
with no history at all.

**`skills/.gitignore`** (committed):

```gitignore
*.db
*.db-wal
*.db-shm
*.sqlite
*.sqlite3
__pycache__/
*.pyc
*.log
*.tmp
.cache/
.DS_Store
```

`state.db` lives at `~/.hermes/state.db`, i.e. **outside** this repo's root — excluded by scope
(D7). The patterns above are defence in depth against a skill dropping a cache DB in its own
folder and quietly turning a text repo into a binary one.

**Recovery**: `git -C ~/.hermes/skills log -p -- sobre-mi/SKILL.md` to see what the agent changed,
`git revert <sha>` to undo it. Documented in the README next to `write_approval`, because the two
are one story: approval is the gate before, git is the net after.

---

## 12. Backup, Restore and the Passphrase

**`backup/backup.sh`** — on-demand and pre-drill (the nightly path is the `restic` service's own
cron). Loads `.env`, runs in a throwaway container against the same repo:

1. `restic backup /data --tag manual --host labia03`
2. `restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune`
3. `restic check --read-data-subset=5%` — a repo that lists snapshots is not the same as a repo
   whose data reads back.
4. On success write `state/backup/last-success`; on any failure exit non-zero **and** call
   `ops/notify.sh` (a manual backup that fails silently is worse than none).

**`backup/restore.sh --target DIR [--snapshot latest]`** — designed to be run on the laptop:

1. Refuse to start unless `RESTIC_REPOSITORY` and `RESTIC_PASSWORD` are set; the error message
   points at `backup/PASSPHRASE.md`.
2. Refuse a non-empty `--target` unless `--force` (no accidental overwrite of live state).
3. `restic restore <snapshot> --target DIR`.
4. **Verify, then report** — this is the part that makes it a drill and not a copy:
   - `python3 -c "sqlite3 … PRAGMA integrity_check"` on `data/vida.db` and `state.db`;
   - if the live file fails, swap in `backup/vida.db.snapshot` (D8) and re-check;
   - assert `skills/` exists and `git -C skills log --oneline | wc -l` is non-zero;
   - print a JSON summary: files restored, snapshot id and time, per-DB integrity, table row counts.
5. Print the next command literally:
   `HERMES_DATA=DIR docker compose up -d` — which works unmodified thanks to D9.

**`backup/PASSPHRASE.md`** — committed to the repo and containing **no secret**. It records:

| Field | Content |
|---|---|
| Where the passphrase lives | Password-manager vault + exact entry name (e.g. `Bitwarden → "restic labia03 hermes-data"`) |
| Second, offline copy | Physical location of the printed/written copy (e.g. "sobre en carpeta de documentos, casa") |
| Repository URL | `rclone:<remote>:hermes-backup` and where the `rclone.conf` token is re-obtainable |
| Recovery procedure | The four steps: get passphrase → install rclone/restic (or use the Docker image) → `restore.sh --target` → `HERMES_DATA=… docker compose up -d` |
| Verification date | Date of the last successful restore drill — updated by hand after each drill |

Three copies, two of them off `labia03`: `.env` (mode 600, on the box), password manager, printed.
The doc exists because the failure mode is not "we did not generate a passphrase", it is "the
person who needs it in January 2027 does not know where it is". F0.5 must be green before the
`restic` service is even started.

---

## 13. Migration / Rollout

No data migration — greenfield. Bootstrap order, each step gated by the previous:

1. **Fase 0 closed** (§14). `docker compose up` does not happen before F0.1, F0.3 and F0.5 are green.
2. `cp .env.template .env`, fill it, `chmod 600 .env`; same for `ops/.env.ops`.
3. `docker run --rm -it -v "$HERMES_DATA:/opt/data" nousresearch/hermes-agent setup` — the
   documented one-shot init. Then `ops/render-config.sh` fills `config.yaml` from the template
   with `write_approval: true` and the Telegram allowlist **before first gateway start**. Starting
   the bot before the allowlist is set is the one irreversible mistake here.
4. Copy the five seed skills into `$HERMES_DATA/skills/`; `git init` + first commit (§11).
5. `docker compose up -d hermes` — voice-less but functional. Verify text expense capture end to end.
6. `docker compose up -d whisper` (skip if F0.2 red → `WHISPER_OPTIONAL=1`). Verify a voice note.
7. Register the Hermes cron jobs in natural language; smoke-test with a 2-minute job before
   trusting the 07:00 briefing.
8. `docker compose up -d restic`, then `backup/backup.sh` manually, then `check-backup.sh` by hand.
9. Install the cron fragment (or systemd timers). Verify by stopping `whisper` on purpose and
   waiting for the alert — an untested alert is an assumption.
10. **Restore drill on the laptop.** Update the verification date in `PASSPHRASE.md`. Fase 1 is not
    done until this is done.

**Rollback**: `docker compose down` leaves `$HERMES_DATA` untouched; nothing installs to the host
except one cron fragment. A bad self-edited skill is `git revert`. A bad image tag is the previous
digest from the README.

---

## 14. Prerequisites (from `proposal.md` §4 — not decided here)

This design assumes Fase 0 has been closed. It is **not** re-deciding those questions.

- **F0.1** ✅ CONFIRMED — `opencode Go` (personal subscription, $10/mo, survives labia03) +
  `deepseek-v4-pro`, live `curl` against `https://opencode.ai/zen/go/v1/chat/completions` returned a
  valid OpenAI-compatible response. → `LLM_BASE_URL=https://opencode.ai/zen/go/v1`,
  `LLM_API_KEY=<opencode Go key>`, `model: deepseek-v4-pro` in `config.yaml.template`.
- **F0.2** `nvidia-container-toolkit` + Docker GPU runtime working. → red ⇒ omit `whisper`, set
  `WHISPER_OPTIONAL=1`; Fase 1 still ships (without voice). GPU is confirmed exclusive to the user
  and sudo is confirmed available — this item is now a pure configuration check, not a permissions
  unknown.
- **F0.3** ✅ CONFIRMED native — `allow_from` config key (env var `TELEGRAM_ALLOWED_USERS`),
  deny-by-default when unset. → exact key goes in `config.yaml.template` as `allow_from: [<TG_USER_ID>]`.
  No gateway-side filter code needed; drop that contingency from `sdd-tasks`. Note: historic
  GitHub issue #7651 (closed) covered a group-mention bypass, irrelevant here since this bot is
  DM-only — but verification #7 (second Telegram user is ignored) must still be tested live, not
  assumed from docs.
- **F0.4** Bot token + numeric `user_id`. → `.env` and `ops/.env.ops`.
- **F0.5** Backup destination + rclone credentials + passphrase with an out-of-band copy. →
  `secrets/rclone.conf`, `RESTIC_*`, `PASSPHRASE.md`. Still open — user action, not yet done.
- **F0.6** Docker Compose v2 usable, Tailscale SSH reachable, `cron` **or** `systemd --user`
  available. → picks §10's timer mechanism.
- **F0.6-extra (added by this design)**: host `python3` ≥ 3.8 present. `check-stack.sh`,
  `check-backup.sh` and `db-snapshot.sh` all depend on it, and it is also the fallback verifier in
  `restore.sh`. Trivial to confirm, expensive to discover later.
- **F0.7 (added by this design)**: voice interception mechanism, see §15 — still open.

Exit gate: F0.1 ✅ and F0.3 ✅ closed. **F0.5 is the only remaining hard blocker** before Fase 1
build starts. F0.2 and F0.7 red/open degrade scope (ships without voice) but do not block.

---

## 15. Open Questions

- [x] **Voice interception mechanism — RESOLVED in PR 4/6 (Groups 4-6).** Decision: implemented as
      a **skill** (`skills/entrada-voz/SKILL.md` calling `ops/transcribe-voice.sh`), not a
      gateway-level pre-message hook — Hermes' pre-message hook API remained unverified (F0.7), and
      the skill pattern was already proven by the five domain skills. Both alternatives land on the
      same `POST /asr` contract against `whisper:9000`, so nothing here changes if a native hook is
      confirmed later; see `skills/entrada-voz/SKILL.md` §0 for the full rationale.
- [ ] **`config.yaml` key names.** `config.yaml.template` uses placeholder key names for provider,
      base_url, api_key, Telegram channel and allowlist. Exact keys come from F0.1/F0.3; the
      template is a shape, not a verified schema.
- [ ] **Does Hermes read `LLM_BASE_URL`/`LLM_API_KEY` from the environment, or only from
      `config.yaml`?** The design assumes the latter and templates the file, which is safe either
      way — but if env vars are honoured, `render-config.sh` can be dropped.
- [ ] **`state.db` size growth.** Session history in SQLite grows unbounded. Not a Fase 1 problem;
      worth a `vida.py health`-style size check before it becomes a restic bandwidth problem.
- [ ] **Post-approval hook for skills auto-commit** — nice-to-have (§11); cron covers the need.

---

**Next**: `sdd-tasks` (requires `spec.md` as well).
