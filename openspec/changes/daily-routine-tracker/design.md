# Design: Tracker de rutina diaria (`daily-routine-tracker`)

Change: `daily-routine-tracker`
Reads: `proposal.md` (approved scope), `openspec/changes/hermes-personal-assistant/design.md` (Fase 1 baseline)
Baseline: Fase 1 **live on labia03**, `schema_version = 1`, real data in `vida.db`.

> **Size note**: the sdd-design 800-word budget is intentionally exceeded, same as Fase 1's design.
> The phase brief explicitly asked for the migration mechanism at code level, column-level schema,
> per-subcommand JSON contracts and a test plan. Detail is delivered as tables and code blocks.

> ⚠️ This change is **not greenfield**. Fase 1 `design.md §13` said "no data migration — greenfield";
> that statement is superseded here, not rewritten in the closed change.

---

## 1. Technical Approach

One load-bearing idea: **the schema is now a sequence, not a snapshot.**

Until today `vida.db` had exactly one possible shape, and `_ensure_schema()` only had to answer
"does it exist?". From this change on, a `vida.db` can be at v1 (production, right now), at v2
(after this lands), or freshly created — and all three have to converge on the same shape without
the operator running anything by hand. That is decision **D-0**, and every other decision here is
downstream of it.

Everything else follows established Fase 1 contracts unchanged:

| Contract (Fase 1) | Status in this change |
|---|---|
| `vida.py` is the **only** data gateway (D2) | Preserved — `rutina` is a new domain inside the same CLI, not a second CLI |
| stdlib only, no ORM, no third-party deps (§7) | Preserved — the migration runner is `sqlite3` + a Python list |
| JSON-only stdout envelope | Preserved — same `{"ok", "action", "data"}` / `{"ok", "action", "error", "codigo"}` |
| No number is produced by the model (D11) | Preserved — `rutina stats` returns computed percentages; the skill reads them |
| `vida.py` bind-mounted read-only (D2) | Preserved — **and it is why migrations live inside `vida.py`** (see D-0.1) |
| Soft delete (`activa`) instead of `DELETE` (`tarjetas`) | Extended — `activo` on `rutina_bloques` and `rutina_items` |

Nothing in this change touches `docker-compose.yml`. The two files already mounted into the
container (`bin/vida.py`, `data/schema.sql`) are exactly the two files the migration mechanism
needs. That constraint is what picks the mechanism below.

---

## 2. Architecture Decisions

| # | Decision | Alternatives rejected | Rationale |
|---|---|---|---|
| **D-0.1** | Migrations live as a **Python data structure inside `vida.py`**: `MIGRATIONS: dict[int, tuple[str, ...]]`, one entry per version, each a **tuple of individual SQL statements** | (a) numbered `.sql` files under `data/migrations/`; (b) `-- migration: N` delimited blocks parsed out of `schema.sql` | (a) is the textbook answer and would be right in a normal deploy — but it needs a **new bind mount** (`./data/migrations:/opt/data/bin/migrations:ro`), and `docker-compose.yml` is not in the proposal's Affected Areas. Worse, it decouples the migration from the code that assumes it: a `vida.py` that queries `rutina_items` could ship without its migration file and fail at runtime. Embedding makes deploy atomic — the file that runs the migration **is** the file that carries it, and D2's read-only mount already guarantees the agent cannot edit it. (b) means writing a SQL block-splitter that has to survive strings, triggers and comments; a naive `split(";")` is a latent corruption bug in the one code path that must never be clever. Storing statements as a **tuple** sidesteps splitting entirely. |
| **D-0.2** | Version read as `SELECT COALESCE(MAX(version), 0) FROM schema_version`; target is the module constant `TARGET_SCHEMA_VERSION = 2` | A single-row `current_version` table; a `PRAGMA user_version` | `schema_version` already exists **in production** as a one-row-per-version log with `aplicado_en` (Fase 1 §6). Reshaping it into a single-row table would itself require a migration — bootstrapped by the mechanism we are introducing. Chicken-and-egg for zero gain. `PRAGMA user_version` is an integer with no audit trail, and it would silently disagree with the table already there. Keeping the log means `SELECT * FROM schema_version` answers "when did this box get migrated?", which is exactly the question during an incident. |
| **D-0.3** | Each migration runs inside an **explicit `BEGIN IMMEDIATE` … `COMMIT`**, with `conn.isolation_level = None` for the duration, and the `INSERT INTO schema_version` as the **last statement inside the same transaction** | Rely on the `with conn:` context manager used everywhere else in `vida.py`; use `executescript()` | This is the one place where `vida.py`'s existing idiom is **wrong**. Python's `sqlite3` in legacy autocommit mode (`isolation_level=""`, the default, still the default on 3.11 and earlier — and `vida.py` targets "any machine with `python3`") only opens an implicit transaction before `INSERT`/`UPDATE`/`DELETE`/`REPLACE`. **DDL is not wrapped.** A `CREATE TABLE` would commit itself and a later failure would leave half a migration applied with `schema_version` untouched — precisely the failure mode `proposal.md §7` asks us to prevent. `executescript()` is worse: it issues an implicit `COMMIT` before running. Explicit `BEGIN IMMEDIATE` also takes the write lock up front, which is what makes the "cron + Telegram open the DB at the same time" race benign (D-0.5). |
| **D-0.4** | `schema.sql` stays the **fresh-database bootstrap** and is the full v2 shape, ending with `INSERT OR IGNORE INTO schema_version (version) VALUES (1), (2);` | Delete `schema.sql` and bootstrap a fresh DB by replaying migrations 1..N against an empty file | Replaying migrations would make fresh-vs-migrated equivalence a *tautology* instead of a *test* — technically the stronger design, and it is rejected only because `proposal.md §4.1` fixes `schema.sql` as the bootstrap (approved scope) and because a single readable `schema.sql` is the artifact an operator opens at 3am. The divergence risk this creates is real and is paid for with a **mandatory equivalence test** (§7.1), which is a blocking success criterion, not a nice-to-have. Inserting **both** version rows (not just `2`) keeps `schema_version` contents identical between the two paths too. |
| **D-0.5** | `version > TARGET` → do nothing, proceed normally (no error) | Refuse to run ("database is newer than this code") | `proposal.md §8.4` explicitly says reverting *only the code* must be safe. That is true **because migrations are additive by convention** — a v1 `vida.py` never selects the new columns or tables. Hard-failing on a newer DB would turn a safe rollback into an outage. The convention is the guarantee, so it is written down here: **a migration in this project may only ADD tables, columns and indexes.** A destructive migration would break rollback and needs its own design. |
| **D-1** | `pendientes.dificultad` is declared **last** in `schema.sql` (after `fuente`), not next to `prioridad` | Declare it in the semantically pretty position | `ALTER TABLE … ADD COLUMN` always appends. If `schema.sql` put it in the middle, a fresh DB and a migrated DB would differ in column order (`cid` in `PRAGMA table_info`) — a difference the equivalence test would either flag (blocking a correct change) or be weakened to ignore (blinding the test). Aesthetics lose; the test keeps its teeth. |
| **D-2** | Three tables, `rutina_completado` as an **append-only log** with `UNIQUE(item_id, fecha)` | `rutina_items.hecho INTEGER` + a midnight reset job | Already argued in `proposal.md §4.3`. Restated here for its schema consequence: "not done today" is *absence of a row*, so there is no state to reset, no timezone-sensitive cron, and no way for the checklist to lie. `historial` and `stats` are then queries over data that already exists rather than a second feature. |
| **D-3** | FKs use `ON DELETE RESTRICT`, deactivation is `activo = 0` | `ON DELETE CASCADE` | Cascading from `rutina_bloques` would let a single mistaken delete erase months of `rutina_completado`. There is no delete subcommand in scope; `activo` is the sanctioned path, mirroring `tarjetas.activa` (Fase 1 §6, "soft delete keeps historical rows valid"). `RESTRICT` makes the destructive path fail loudly rather than succeed quietly. |
| **D-4** | `rutina done` accepts **`--id` only** — never a name, never a fuzzy match | `rutina done --nombre "ducharme"` | This is the anti-hallucination guardrail expressed as a *missing feature*. If the CLI could resolve names, the model would pass whatever it heard and the CLI would guess. Forcing `--id` makes `rutina today` a mandatory prior call, exactly like `pendiente done` (Fase 1 §8, `agenda-personal`). The safety property lives in the CLI's surface, not in the skill's prose — prose can be paraphrased away by the model, an argparse signature cannot. |
| **D-5** | `rutina done` on an already-completed (item, date) returns **`ok: true` with `ya_estaba: true`**, not an error | `codigo: "duplicado"`, mirroring `gym log` | The two cases are genuinely different. A duplicated `gym log` means data loss risk (a real second set silently discarded), so it must shout. A duplicated `rutina done` means the user said "ya me duché" twice — the requested state ("done today") already holds. Erroring there produces a bot that argues with the user about a checkbox. `UNIQUE(item_id, fecha)` still guarantees one row; the command is idempotent on top of it. |
| **D-6** | `rutina today` returns rutina **and** open `pendientes` in one JSON | Two separate calls composed by the model/cron | `proposal.md §4.2`'s single-database argument, made concrete: one call means one atomic view of "today", no interleaving, and the 7am cron job's prompt gets shorter (fewer commands = fewer chances for the model to skip one). `--sin-pendientes` exists for callers that only want the checklist. |
| **D-7** | `rutina stats` counts **`oportunidades` from the item's creation date**, not from `--desde` | Every active item is scored over the whole range | An item registered on the 20th would otherwise show ~35% for the month and the user would read a real number as a failure. Scoring from `max(--desde, date(creado_en))` is the only definition that is both deterministic and honest. It is exposed per item as `desde_efectivo` so the number is auditable, not magic. |
| **D-8** | `--fecha` accepts ISO **or** the literals `hoy` / `ayer` / `anteayer`, resolved **in `vida.py`** | Require the model to resolve relative dates to ISO | Fase 1 already makes the model resolve "el próximo martes" → ISO, and that stays. But `ayer` is the single most common phrasing in this domain ("me olvidé de marcar lo de ayer") and it is a one-line deterministic resolution. Anything more ambiguous than these three literals stays the model's job, because a date parser that guesses is a date parser that is wrong on the day it matters. |

---

## 3. `_ensure_schema()` — the migration mechanism (D-0)

Replaces `bin/vida.py:152-160` in full. Everything else in `get_connection()` is unchanged.

```python
TARGET_SCHEMA_VERSION = 2

# Migrations are ADDITIVE ONLY (D-0.5): add tables/columns/indexes, never drop or
# rewrite. That convention is what makes "revert the code, keep the data" safe.
# Each version maps to a tuple of INDIVIDUAL statements — no ";" splitting, ever.
MIGRATIONS: dict[int, tuple[str, ...]] = {
    2: (
        "ALTER TABLE pendientes ADD COLUMN dificultad TEXT "
        "CHECK (dificultad IS NULL OR dificultad IN ('facil', 'media', 'dificil'))",

        """CREATE TABLE rutina_bloques (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre         TEXT    NOT NULL UNIQUE,
            hora_objetivo  TEXT,
            orden          INTEGER NOT NULL DEFAULT 0,
            activo         INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
            creado_en      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            fuente         TEXT    NOT NULL DEFAULT 'telegram'
                                   CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron'))
        )""",

        """CREATE TABLE rutina_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            bloque_id  INTEGER NOT NULL REFERENCES rutina_bloques(id) ON DELETE RESTRICT,
            nombre     TEXT    NOT NULL,
            orden      INTEGER NOT NULL DEFAULT 0,
            activo     INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
            creado_en  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            fuente     TEXT    NOT NULL DEFAULT 'telegram'
                               CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron')),
            UNIQUE (bloque_id, nombre)
        )""",

        """CREATE TABLE rutina_completado (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id    INTEGER NOT NULL REFERENCES rutina_items(id) ON DELETE RESTRICT,
            fecha      TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
            creado_en  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            fuente     TEXT    NOT NULL DEFAULT 'telegram'
                               CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron')),
            UNIQUE (item_id, fecha)
        )""",

        "CREATE INDEX idx_rutina_items_bloque ON rutina_items(bloque_id, orden)",
        "CREATE INDEX idx_rutina_compl_fecha ON rutina_completado(fecha)",
        "CREATE INDEX idx_rutina_compl_item_fecha ON rutina_completado(item_id, fecha)",
    ),
}


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version").fetchone()
    return int(row["v"])


def _ensure_schema(conn: sqlite3.Connection) -> None:
    existe = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if existe is None:
        # Fresh database: schema.sql IS the v2 shape and inserts versions 1 and 2 (D-0.4).
        with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
            conn.executescript(fh.read())
        conn.commit()
        return
    _aplicar_migraciones(conn)


def _aplicar_migraciones(conn: sqlite3.Connection) -> None:
    actual = _schema_version(conn)
    if actual >= TARGET_SCHEMA_VERSION:
        return  # up to date, or newer DB + older code — safe because migrations are additive

    previo = conn.isolation_level
    conn.isolation_level = None  # manual control: sqlite3 does NOT wrap DDL (D-0.3)
    try:
        for version in range(actual + 1, TARGET_SCHEMA_VERSION + 1):
            sentencias = MIGRATIONS.get(version)
            if sentencias is None:
                raise VidaError(
                    f"falta la definicion de la migracion {version}", "migracion_faltante"
                )
            conn.execute("BEGIN IMMEDIATE")
            try:
                for sentencia in sentencias:
                    conn.execute(sentencia)
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    finally:
        conn.isolation_level = previo
```

**Atomicity properties, stated so they can be tested (§7.1):**

- The `INSERT INTO schema_version` is the **last statement inside** the transaction. A crash at any
  earlier point rolls back *both* the DDL and the version bump. There is no window where the version
  says 2 and the tables are missing, nor the reverse.
- Migrations run **one transaction per version**, not one for the whole range. A future v1→v3 jump
  that fails at v3 leaves a clean, consistent v2 — and the next run resumes from v2.
- `BEGIN IMMEDIATE` takes the write lock before the first `CREATE TABLE`. A second process (cron
  firing while the user texts the bot) blocks for `busy_timeout = 5000` ms; when it proceeds,
  `actual >= TARGET` is already true and it does nothing. `proposal.md §7`'s "apply with the stack
  stopped" stays the recommended procedure, but correctness does not depend on it.
- `PRAGMA foreign_keys = ON` is set in `get_connection()` **before** any transaction opens — the
  pragma is a silent no-op inside a transaction, which is exactly the kind of thing that turns
  "FKs are enforced" into a comfortable lie.
- The `VidaError` raised on a missing definition surfaces through `main()`'s existing handler as
  `{"ok": false, ..., "codigo": "migracion_faltante"}` — a broken deploy reports itself as JSON on
  the very next command instead of crashing with a traceback the skill would try to narrate.

**`schema.sql` changes** (the other half of D-0.4):

1. `pendientes` gains `dificultad` as the **last** column, with the CHECK text identical to the one
   in migration 2 (D-1).
2. The three `rutina_*` tables and their three indexes are appended, written with
   `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` to match the file's existing style
   (the migration path uses the plain form — inside a versioned migration, `IF NOT EXISTS` would
   mask a real inconsistency instead of failing).
3. Final line becomes `INSERT OR IGNORE INTO schema_version (version) VALUES (1), (2);`.
4. The header comment stops saying "applied idempotently on first run" and states the new contract:
   *this file is the bootstrap for a fresh DB and must stay equivalent to v1 + all migrations;
   the equivalence test in `tests/test_vida.py` enforces it.*

---

## 4. Data Model (v2 additions)

Global conventions inherited from Fase 1 §6: ISO-8601 `TEXT` dates, `creado_en TEXT NOT NULL
DEFAULT (datetime('now','localtime'))`, `fuente` with the four-value CHECK on user-originated rows.

### `pendientes` (modified)

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `dificultad` | TEXT | NULL, CHECK `dificultad IS NULL OR dificultad IN ('facil','media','dificil')` | Effort axis. **Distinct from `prioridad`**, which already carries urgency (`proposal.md §4.4`). Existing rows stay `NULL`; declared last (D-1). |

### `rutina_bloques`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `nombre` | TEXT | NOT NULL **UNIQUE** | Normalised by `vida.py` to `strip().lower()`, same treatment as `entrenamientos.ejercicio` — "Asearme" and "asearme" must not become two blocks. UNIQUE is what lets `rutina item add --bloque <nombre>` resolve without ambiguity. |
| `hora_objetivo` | TEXT | NULL, `HH:MM` | Stored, **not used for alerting** in this change (explicitly out of scope). Feeds ordering and display only. |
| `orden` | INTEGER | NOT NULL DEFAULT 0 | Display order; ties broken by `id` so output is always deterministic. |
| `activo` | INTEGER | NOT NULL DEFAULT 1, CHECK in (0,1) | Soft delete (D-3). `rutina today` filters `activo = 1`. |
| `creado_en`, `fuente` | TEXT | see global | |

### `rutina_items`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | The **only** identifier `rutina done` accepts (D-4). |
| `bloque_id` | INTEGER | NOT NULL, REFERENCES `rutina_bloques(id)` ON DELETE RESTRICT | |
| `nombre` | TEXT | NOT NULL | Normalised `strip().lower()`. |
| `orden` | INTEGER | NOT NULL DEFAULT 0 | |
| `activo` | INTEGER | NOT NULL DEFAULT 1, CHECK in (0,1) | Deactivating keeps every historical `rutina_completado` row valid. |
| `creado_en`, `fuente` | TEXT | see global | `creado_en` is load-bearing: it defines `desde_efectivo` in `stats` (D-7). |
| — | — | **`UNIQUE (bloque_id, nombre)`** | Re-registering the same routine is idempotent instead of duplicating the checklist. |

> **Naming note**: the phase brief mentioned `UNIQUE(bloque_id, titulo)`. `proposal.md §D-2` (approved
> scope) specifies `nombre`, and `nombre` is what the sibling table uses. Resolved in favour of
> `nombre` for consistency; `titulo` remains `pendientes`-only vocabulary.

### `rutina_completado` — append-only log

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `item_id` | INTEGER | NOT NULL, REFERENCES `rutina_items(id)` ON DELETE RESTRICT | |
| `fecha` | TEXT | NOT NULL DEFAULT `date('now','localtime')` | The day being credited — not the day it was typed. `--fecha ayer` writes yesterday. |
| `creado_en` | TEXT | NOT NULL DEFAULT `datetime('now','localtime')` | Wall-clock instant of marking; surfaced as `hecho_a_las`. No separate `completado_en`: in an append-only log the row's creation *is* the completion. |
| `fuente` | TEXT | see global | |
| — | — | **`UNIQUE (item_id, fecha)`** | One completion per item per day. Backs D-5's idempotency. |

Indexes: `idx_rutina_items_bloque(bloque_id, orden)`, `idx_rutina_compl_fecha(fecha)` (drives
`today` and `historial`), `idx_rutina_compl_item_fecha(item_id, fecha)` (drives `stats` and streaks).

---

## 5. `vida.py` — the `rutina` subcommand group

Wired exactly like `pendiente`/`gasto`/`gym`: a `subparsers.add_parser("rutina")` with its own
`add_subparsers(dest="subcomando", required=True)`, one `cmd_rutina_*(conn, args) -> dict` per leaf,
attached via `set_defaults(func=…)`. `_accion()` yields `rutina.today`, `rutina.done`, etc. — nesting
depth stays 2, so `bloque add` and `item add` become the parser names **`bloque-add`** and
**`item-add`** rather than a third level. Rationale: a third `add_subparsers` level would need
`_accion()` rewritten and would break the `"<cmd>.<sub>"` action string every existing test and skill
already relies on. The user-facing phrasing in `proposal.md §D-3` is preserved verbatim in the skill
docs; only the CLI token is hyphenated.

### 5.1 Signatures

| Command | Required | Optional | `data` payload |
|---|---|---|---|
| `rutina bloque-add` | `--nombre` | `--hora-objetivo --orden --fuente` | inserted `rutina_bloques` row |
| `rutina item-add` | `--nombre` + exactly one of `--bloque` \| `--bloque-id` | `--orden --fuente` | inserted `rutina_items` row + `bloque` (name) |
| `rutina today` | — | `--fecha` (default `hoy`), `--sin-pendientes` | §5.2 |
| `rutina done` | `--id` | `--fecha` (default `hoy`), `--fuente` | `{item_id, item, bloque, fecha, ya_estaba, hecho_a_las}` |
| `rutina historial` | one of `--fecha` \| `--desde`+`--hasta` | — | §5.4 |
| `rutina stats` | `--desde`, `--hasta` | `--bloque` | §5.3 |

`--fecha` on `today`/`done`/`historial` accepts ISO or `hoy`/`ayer`/`anteayer` (D-8); anything else
returns `codigo: "fecha_invalida"`, reusing the existing `_parse_fecha` message shape.

### 5.2 `rutina today` — JSON contract

```json
{
  "ok": true,
  "action": "rutina.today",
  "data": {
    "fecha": "2026-08-02",
    "bloques": [
      {
        "bloque_id": 1,
        "nombre": "asearme",
        "hora_objetivo": "07:00",
        "orden": 1,
        "total_items": 3,
        "hechos": 1,
        "pct": 33.3,
        "items": [
          {"item_id": 3, "nombre": "ducharme",  "orden": 1, "hecho_hoy": true,
           "hecho_a_las": "2026-08-02 07:12:40"},
          {"item_id": 4, "nombre": "skincare",  "orden": 2, "hecho_hoy": false,
           "hecho_a_las": null},
          {"item_id": 5, "nombre": "cortarme las unas", "orden": 3, "hecho_hoy": false,
           "hecho_a_las": null}
        ]
      },
      {
        "bloque_id": 2, "nombre": "cocinar", "hora_objetivo": null, "orden": 2,
        "total_items": 2, "hechos": 2, "pct": 100.0,
        "items": [
          {"item_id": 6, "nombre": "almuerzo", "orden": 1, "hecho_hoy": true,
           "hecho_a_las": "2026-08-02 12:40:11"},
          {"item_id": 7, "nombre": "lavar los platos", "orden": 2, "hecho_hoy": true,
           "hecho_a_las": "2026-08-02 13:05:02"}
        ]
      }
    ],
    "resumen": {"total_items": 5, "hechos": 3, "pct": 60.0},
    "pendientes": [
      {"id": 12, "titulo": "llamar al banco", "fecha_objetivo": "2026-08-02",
       "hora": "15:00", "prioridad": "alta", "dificultad": "facil", "estado": "abierto",
       "detalle": null, "recurrencia": null, "completado_en": null,
       "creado_en": "2026-08-01 20:11:03", "fuente": "telegram"}
    ]
  }
}
```

Rules:

- Only `activo = 1` blocks and items. Ordering: `orden ASC, id ASC` at both levels — deterministic
  even when the user never sets `orden`.
- `pct` is `round(hechos / total_items * 100, 1)`; **`pct` is `null` when `total_items == 0`**. The
  skill must never divide, so the CLI must never emit a number it had to invent. A block with zero
  active items still appears (with `items: []`) so "I registered it and it vanished" is impossible.
- `pendientes` is byte-for-byte the payload of `pendiente today` (same rows, same order, now
  including `dificultad`). Omitted entirely when `--sin-pendientes` is passed.
- `hecho_a_las` is `rutina_completado.creado_en` verbatim, `null` when not done.

### 5.3 `rutina stats` — JSON contract

```json
{
  "ok": true,
  "action": "rutina.stats",
  "data": {
    "rango": {"desde": "2026-07-01", "hasta": "2026-07-31", "dias": 31},
    "global": {"oportunidades": 145, "completados": 101, "pct": 69.7},
    "por_bloque": [
      {
        "bloque_id": 1, "nombre": "asearme",
        "oportunidades": 93, "completados": 80, "pct": 86.0,
        "items": [
          {"item_id": 3, "nombre": "ducharme", "desde_efectivo": "2026-07-01",
           "oportunidades": 31, "completados": 29, "pct": 93.5,
           "racha_actual": 5, "mejor_racha": 12},
          {"item_id": 4, "nombre": "skincare", "desde_efectivo": "2026-07-01",
           "oportunidades": 31, "completados": 24, "pct": 77.4,
           "racha_actual": 0, "mejor_racha": 9},
          {"item_id": 5, "nombre": "cortarme las unas", "desde_efectivo": "2026-07-01",
           "oportunidades": 31, "completados": 27, "pct": 87.1,
           "racha_actual": 3, "mejor_racha": 7}
        ]
      },
      {
        "bloque_id": 2, "nombre": "cocinar",
        "oportunidades": 52, "completados": 21, "pct": 40.4,
        "items": [
          {"item_id": 6, "nombre": "almuerzo", "desde_efectivo": "2026-07-01",
           "oportunidades": 31, "completados": 18, "pct": 58.1,
           "racha_actual": 2, "mejor_racha": 6},
          {"item_id": 7, "nombre": "lavar los platos", "desde_efectivo": "2026-07-11",
           "oportunidades": 21, "completados": 3, "pct": 14.3,
           "racha_actual": 0, "mejor_racha": 2}
        ]
      }
    ]
  }
}
```

Definitions, all computed in SQL/Python and none by the model (D11):

| Field | Definition |
|---|---|
| `desde_efectivo` | `max(--desde, date(rutina_items.creado_en))` — D-7. Visible so the number is auditable. |
| `oportunidades` (item) | Inclusive day count from `desde_efectivo` to `--hasta`. `0` if the item was created after `--hasta`. |
| `completados` (item) | `COUNT(*)` of `rutina_completado` rows for that item with `fecha BETWEEN desde_efectivo AND hasta`. Rows outside the item's effective window cannot exist, but the filter is written anyway — a `--fecha ayer` typo must not inflate a percentage. |
| `pct` | `round(completados / oportunidades * 100, 1)`; `null` when `oportunidades == 0`. Same no-invented-numbers rule as §5.2. |
| block / global rollups | Sums of the item-level counters, then one division. Never an average of percentages — averaging percentages over unequal windows is how a report starts lying. |
| `racha_actual` | Consecutive days ending at `--hasta` (or at `hoy` if `--hasta >= hoy`) with a completion row. `0` if `--hasta` itself has none. |
| `mejor_racha` | Longest consecutive run inside `[desde_efectivo, --hasta]`. |

Only `activo = 1` items are scored; `--bloque <nombre>` narrows to one block.

### 5.4 `rutina historial` — JSON contract

```json
{
  "ok": true,
  "action": "rutina.historial",
  "data": {
    "rango": {"desde": "2026-08-01", "hasta": "2026-08-01", "dias": 1},
    "dias": [
      {
        "fecha": "2026-08-01",
        "rutina": [
          {"item_id": 3, "item": "ducharme", "bloque_id": 1, "bloque": "asearme",
           "hecho_a_las": "2026-08-01 07:05:19"}
        ],
        "pendientes": [
          {"id": 9, "titulo": "pagar la luz", "prioridad": "alta", "dificultad": null,
           "completado_en": "2026-08-01 18:22:00"}
        ]
      }
    ]
  }
}
```

`--fecha X` is sugar for `--desde X --hasta X`. Days with no activity still appear with empty
arrays inside an explicit `--desde/--hasta` range — a gap the user can see beats a gap they have to
infer. Completed `pendientes` are matched on `date(completado_en)`. Inactive items **are** included
here: history is history.

### 5.5 `rutina done` — id-resolution safety contract (D-4)

| Situation | Result |
|---|---|
| `--id` omitted or non-integer | argparse rejects: exit **2**, message on **stderr**, no JSON. Pre-existing hole in the Fase 1 envelope (`pendiente done` behaves the same). Documented, not fixed here — see §10. |
| `--id` matches no row in `rutina_items` | `{"ok": false, "action": "rutina.done", "error": "no existe item de rutina con id 42", "codigo": "no_encontrado"}`, exit 1 |
| `--id` matches a **`rutina_bloques`** row instead of an item | `{"ok": false, …, "error": "el id 2 es un bloque, no un item; usa los item_id de 'rutina today'", "codigo": "id_es_bloque"}`, exit 1. The two id spaces overlap numerically, so this is the mistake the model will actually make — naming it beats a generic "not found". |
| item exists but `activo = 0` | `{"ok": false, …, "codigo": "item_inactivo"}`, exit 1. Never silently reactivate. |
| `--fecha` in the future | `{"ok": false, …, "codigo": "fecha_futura"}`, exit 1. You cannot pre-complete tomorrow. |
| already completed for that date | `{"ok": true, …, "data": {…, "ya_estaba": true}}`, exit 0 (D-5) |
| happy path | `{"ok": true, …, "data": {"item_id": 3, "item": "ducharme", "bloque": "asearme", "fecha": "2026-08-02", "ya_estaba": false, "hecho_a_las": "2026-08-02 07:12:40"}}`, exit 0 |

There is deliberately **no name-based lookup**. The skill's only route to an `item_id` is
`rutina today`.

`rutina item-add --bloque <nombre>` resolves a *block* by name — safe because `nombre` is UNIQUE, it
is a setup-time operation, and an unknown name returns `codigo: "no_encontrado"` listing the existing
block names in `error` so the model can correct itself in one turn instead of inventing a block.

### 5.6 Collateral changes to existing commands

| Command | Change |
|---|---|
| `pendiente add` | New optional `--dificultad`, validated against `('facil','media','dificil')` before the INSERT (same pattern as `--prioridad`), `codigo: "validacion"` on a bad value. |
| `pendiente today` / `pendiente done` | No code change — `SELECT *` picks up `dificultad` for free. Contract is **additive**: a new key appears, none disappear. |
| `health` | `tablas` gains `rutina_bloques`, `rutina_items`, `rutina_completado`. This is what makes P0.1's "identical row counts before and after" a single command instead of a manual `sqlite3` session. |

---

## 6. `skills/rutina-diaria/SKILL.md`

Same five-section shape as every Fase 1 skill, same YAML frontmatter (`name`, `description` carrying
the trigger phrases, since Hermes matches on the description), same non-negotiable **Nunca** block
verbatim plus two domain-specific lines.

| Section | Content |
|---|---|
| frontmatter `description` | "Registra y hace seguimiento de la rutina diaria del usuario (bloques e ítems recurrentes), marca lo hecho hoy y reporta adherencia. Se activa con frases como 'ya me duché', '¿qué me falta hoy?', 'mi rutina de la mañana es…', '¿cómo vengo con mi rutina?'." |
| **1. Cuándo se activa** | Setup: "mi rutina de la mañana es ducharme, skincare y cortarme las uñas". Daily: "ya me duché", "listo el skincare", "ya hice todo lo de asearme". Query: "¿qué me falta hoy?", "¿cómo vengo con mi rutina este mes?", "¿qué hice ayer?". Includes voice-note phrasings. Explicitly contrasted with `agenda-personal`: **"recordame X"** is a pendiente, **"todos los días hago X"** is a rutina. |
| **2. Comando exacto** | Literal, copyable invocations of the six commands, `python3 /opt/data/bin/vida.py rutina …`, in the order they are actually used: `today` first (because it is a prerequisite for `done`), then `done`, then `bloque-add`/`item-add`, then `historial`/`stats`. |
| **3. Mapeo de lenguaje natural → flags** | Table: block description → one `bloque-add` + N `item-add` calls (one call per item, mirroring `gym-tracker`'s "expand 3x8 into three calls"); "a las 7" → `--hora-objetivo`; item order in the sentence → `--orden` 1..N; "ya me duché" → `rutina today` then `rutina done --id <id resuelto>`; "ayer" → `--fecha ayer`; "este mes" → `stats --desde <1º ISO> --hasta <hoy ISO>`; voice note → `--fuente voz`. |
| **4. Cómo responder** | After `today`: read `resumen.pct` and list only items with `hecho_hoy: false` when the user asks what is missing. After `done`: confirm `item` + `bloque`; if `ya_estaba` is `true`, say it was already marked today instead of pretending to have written it. After `stats`: quote `pct` per block/item **exactly as it comes**; when `pct` is `null`, say there is not enough history rather than reporting 0%. After `bloque-add`/`item-add`: echo the block and the item list so a misheard item is caught in the same breath. |
| **5. Nunca** | The shared Fase 1 block verbatim, plus: *"Nunca adivines un `item_id`: siempre corré `rutina today` primero y usá el `item_id` que devuelve. Si hay dos ítems parecidos, preguntá cuál."* and *"Nunca calcules porcentajes de cumplimiento ni rachas por tu cuenta — vienen calculados en `rutina stats`."* |

Bootstrap: the seed lives in `asistente_personal/skills/rutina-diaria/SKILL.md` under project git and
is copied once into `$HERMES_DATA/skills/`, where `ops/skills-autocommit.sh` picks it up — no new
mechanism (Fase 1 §11).

---

## 7. Testing Strategy

stdlib `unittest` in `asistente_personal/tests/test_vida.py`, matching the existing four-class
layout. Two new classes plus additions to the existing ones.

### 7.1 `TestMigracionV1aV2` — the class that justifies this whole design

Fixture: a helper that builds a **v1 database from the frozen v1 DDL** (the Fase 1 `schema.sql`
text embedded as a test constant — reading the live `schema.sql` would make the test tautological,
since that file now *is* v2), seeds a few rows in every v1 table, then opens it with
`vida.get_connection()` and asserts what happened.

| Test | Assertion |
|---|---|
| `test_v1_db_is_migrated_to_v2_on_open` | `MAX(version) == 2`; `schema_version` has rows `1` **and** `2` |
| `test_migration_preserves_every_row` | Row counts per table identical before/after, and a spot-checked row is byte-identical — the P0.1 criterion, automated |
| `test_existing_pendientes_get_null_dificultad` | Every pre-existing `pendientes` row has `dificultad IS NULL` |
| `test_new_tables_exist_after_migration` | The three `rutina_*` tables and three indexes are present in `sqlite_master` |
| **`test_fresh_bootstrap_and_migrated_v1_have_identical_schema`** | **The D-0.4 guard.** Build DB A fresh (`schema.sql`) and DB B as v1-then-migrated. For every table name in the union: compare normalised `PRAGMA table_info` (name, type, notnull, dflt_value, pk — **including `cid` order**, which is why D-1 exists), `PRAGMA index_list` + `PRAGMA index_info`, and `PRAGMA foreign_key_list`. Compare the sorted set of table names. Compare `SELECT version FROM schema_version ORDER BY version`. **Raw `sqlite_master.sql` text is deliberately NOT compared**: `ALTER TABLE ADD COLUMN` rewrites the stored CREATE text by appending, so the two paths produce semantically identical but textually different DDL. Comparing text would either fail on a correct change or have to be loosened until it proves nothing. |
| `test_migration_is_idempotent` | Opening an already-v2 DB twice more changes nothing: no duplicate `schema_version` rows, no error, schema unchanged |
| **`test_failed_migration_rolls_back_completely`** | Monkeypatch `vida.MIGRATIONS[2]` to a copy whose **last** DDL statement is invalid SQL. Open a v1 DB, assert it raises, then assert on a fresh connection: `MAX(version) == 1`, **none** of the `rutina_*` tables exist, and `pendientes` has **no** `dificultad` column. This is the test that would have caught the `isolation_level` trap in D-0.3 — without the explicit `BEGIN`, the earlier `CREATE TABLE`s survive and this test fails. |
| `test_missing_migration_definition_reports_json_error` | With `TARGET_SCHEMA_VERSION` patched to 3 and no `MIGRATIONS[3]`, the CLI exits 1 with `codigo == "migracion_faltante"` — a broken deploy is legible, not a traceback |
| `test_fresh_db_never_runs_migrations` | A brand-new DB reaches v2 via `schema.sql` only; assert `MIGRATIONS` was not consulted (patch it to `{}` and confirm bootstrap still succeeds) |

### 7.2 `TestRutinaSubcomandos` — subprocess/contract tests

Extends the existing `TestSubcommandContract` pattern (temp DB via `VIDA_DB`, `_run()`,
`_assert_json_ok()`).

| Test | Covers |
|---|---|
| `test_bloque_add_and_item_add` | Happy path; `item-add --bloque <nombre>` resolves; response echoes the block |
| `test_bloque_add_duplicate_nombre_fails_cleanly` | `codigo: "duplicado"`, exit 1 |
| `test_bloque_nombre_is_normalised` | `"Asearme "` and `"asearme"` collide |
| `test_item_add_unknown_bloque_fails_cleanly` | `codigo: "no_encontrado"`, `error` lists existing blocks |
| `test_item_add_duplicate_in_same_bloque_fails_cleanly` | `UNIQUE(bloque_id, nombre)` surfaces as `duplicado` |
| `test_today_shape_and_ordering` | Blocks/items ordered by `orden, id`; `hecho_hoy` all `false` on a fresh day; `resumen.pct` correct |
| `test_today_pct_is_null_when_no_items` | The no-invented-numbers rule |
| `test_today_excludes_inactive` | `activo = 0` block and item are absent |
| `test_today_includes_pendientes_and_sin_pendientes_flag` | D-6 both ways |
| `test_done_marks_item_and_today_reflects_it` | End-to-end: `done` → `today` shows `hecho_hoy: true` + `hecho_a_las` |
| **`test_done_twice_is_idempotent`** | Second call → `ok: true`, `ya_estaba: true`, and exactly **one** row in `rutina_completado` |
| `test_done_unknown_id_fails_cleanly` | `codigo: "no_encontrado"` |
| `test_done_with_bloque_id_reports_id_es_bloque` | D-4's real-world mistake |
| `test_done_inactive_item_fails_cleanly` | `codigo: "item_inactivo"` |
| `test_done_future_date_fails_cleanly` | `codigo: "fecha_futura"` |
| **`test_next_day_checklist_is_clean_without_any_reset`** | Mark today, then query `--fecha <tomorrow-as-today via seeded rows>`: everything `hecho_hoy: false`, zero rows deleted. The success criterion for D-2, tested rather than assumed |
| `test_historial_fecha_and_rango` | `--fecha ayer` sugar; range includes empty days; completed `pendientes` matched by `date(completado_en)` |
| `test_stats_percentages_match_a_hand_calculation` | Seed a known grid (e.g. 3 items × 10 days, 17 completions), assert every `pct`, `oportunidades`, `completados` against numbers computed by hand in the test — `proposal.md §10`'s "verified against a manual calculation" |
| `test_stats_desde_efectivo_respects_item_creation` | D-7: an item created mid-range is not penalised |
| `test_stats_streaks` | `racha_actual` breaks on a gap at `--hasta`; `mejor_racha` finds the longest interior run |
| `test_stats_pct_null_when_no_opportunities` | Item created after `--hasta` |
| `test_fecha_relativa_hoy_ayer_anteayer` | D-8, plus `codigo: "fecha_invalida"` on anything else |

### 7.3 Additions to existing classes

| Class | Added test |
|---|---|
| `TestSchemaConstraints` | `test_dificultad_invalida_rejected` (`sqlite3.IntegrityError`); `test_unique_item_fecha_rejected` on `rutina_completado`; `test_delete_bloque_con_items_is_restricted` (FK `RESTRICT` bites, with `foreign_keys = ON` verified) |
| `TestSubcommandContract` | `test_pendiente_add_con_dificultad` (persists, echoed back); `test_pendiente_add_dificultad_invalida_fails_cleanly` (`codigo: "validacion"`); `test_health_incluye_tablas_rutina` (P0.1's row-count tool) |

Green bar target: the **47 existing tests plus roughly 35 new ones**, all `python3 -m unittest`, no
new dependency, no fixture file on disk beyond `tempfile`.

### 7.4 Manual gate (not automatable here)

P0.1 against a real production copy (§8) and the live end-to-end checks: "ya me duché" from
Telegram marking the right item, the 7am briefing including the routine, the Monday adherence
message arriving. Test suites cannot prove a cron job was registered.

---

## 8. Prerequisites (from `proposal.md §5` — not decided here)

Assumed closed before apply. This design does **not** re-decide them.

- **P0.1** — Migration rehearsal against a **copy** of the real `vida.db` (or the
  `ops/db-snapshot.sh` output): after running, `schema_version = 2`, the three tables exist,
  `pendientes.dificultad` is present and `NULL` everywhere, `PRAGMA integrity_check` is `ok`, and
  row counts for `gastos`/`entrenamientos`/`tarjetas`/`contactos`/`pendientes` are unchanged.
  With §5.6's `health` extension this is `vida.py health` before and after, diffed. **Production is
  not touched until this passes.**
- **P0.2** — Fresh verified restic backup (< 24 h) immediately before applying in production;
  degrades to an off-host local copy of `vida.db` while Fase 1's F0.5 stays open.
- **Fase 1 operational gap** — the 7am briefing job was never actually registered on labia03. D-5
  *edits* that job; the user re-registers it via Telegram. This blocks only D-5's rollout, not the
  code.

---

## 9. Cron changes (`ops/cron-jobs.md`)

`cron-jobs.md` is a runbook of literal Spanish messages a human sends the bot — nothing executes it.
Two edits.

### 9.1 §5.1 — replace the quoted message (D-5, edit, do not add a parallel job)

> Todos los días a las 7:00 am (hora de Lima) corré `python3 /opt/data/bin/vida.py rutina today` y
> `python3 /opt/data/bin/vida.py gym progress --ejercicio <el ejercicio de mi rutina de hoy según
> sobre-mi>`, y mandame un resumen breve por Telegram con tres partes: (1) mi rutina de hoy — por
> cada bloque de `data.bloques`, el `nombre` del bloque y los ítems que todavía tienen
> `hecho_hoy: false`, más el `resumen.pct` tal cual viene en el JSON; (2) mis pendientes de hoy con
> su prioridad, leídos de `data.pendientes` del mismo comando; (3) mi objetivo de entrenamiento del
> día si tengo rutina asignada hoy. Nunca inventes ítems, pendientes ni pesos que no vengan del JSON;
> nunca calcules vos el porcentaje — leé `resumen.pct`. Si `data.pendientes` viene vacío decime "sin
> pendientes hoy"; si `data.bloques` viene vacío decime "no tenés rutina registrada".

Note under the quote: the job now runs **two** commands instead of three — `rutina today` already
returns the pendientes, so `pendiente today` is dropped from this job (D-6). The prose after the
quote keeps citing spec §5 "Morning briefing delivered unprompted" and gains: *"Extended by
`daily-routine-tracker` D-5. Re-register with §5.5's smoke-test procedure before trusting it."*

### 9.2 New §5.6 — weekly adherence (D-6), inserted before §5.5's smoke-test section

> ## 5.6 — Weekly routine adherence summary
>
> > Todos los lunes a las 8:15 am corré
> > `python3 /opt/data/bin/vida.py rutina stats --desde <lunes de la semana pasada> --hasta <domingo
> > de la semana pasada>` y mandame por Telegram: el `global.pct` de la semana, y por cada entrada de
> > `por_bloque` el `nombre` del bloque con su `pct`. Destacá los ítems con el `pct` más bajo para
> > que sepa dónde estoy fallando. Leé todos los porcentajes tal cual vienen del JSON — no los
> > recalculés ni los redondees distinto. Si algún `pct` es `null`, decí que no hay suficiente
> > historial para ese ítem en vez de reportar 0%.
>
> Satisfies `daily-routine-tracker` D-6. Scheduled at 08:15 rather than 08:00 so it does not collide
> with §5.4's weekly expense summary — two Telegram messages arriving in the same minute read as one
> wall of text and get skimmed.

---

## 10. Rollout order and rollback

1. Code lands (`vida.py`, `schema.sql`, tests, skill seed, `cron-jobs.md`). Suite green locally —
   §7.1 in particular. Production is untouched: nothing runs until a container restarts.
2. **P0.2**: fresh verified backup.
3. **P0.1**: rehearse on a copy of the production `vida.db`. Compare `health` output before/after.
4. `docker compose stop hermes` (per `proposal.md §7` — belt and braces on top of `BEGIN IMMEDIATE`),
   deploy, `docker compose up -d hermes`. The first `vida.py` invocation migrates.
5. `vida.py health` → `schema_version: 2`, `integrity_ok: true`, row counts unchanged.
6. Copy `skills/rutina-diaria/` into `$HERMES_DATA/skills/`; `skills-autocommit.sh` commits it.
7. Re-register the 7am job with §9.1's text (after the Fase 1 gap is closed), smoke-test per §5.5.
8. Register §5.6's Monday job, smoke-test the same way.

**Rollback**: revert the code — the data stays, because migrations are additive and a v1 `vida.py`
never looks at the new tables (D-0.5). Only a genuine corruption needs `backup/restore.sh`, which
returns the DB to `schema_version = 1`. Skill and cron rollback is deleting the skill directory and
restoring §5.1's original wording.

---

## 11. Open questions / accepted debt

- [ ] **argparse errors bypass the JSON envelope.** A missing or malformed `--id` exits **2** with
      plain text on stderr, for `rutina done` exactly as for `pendiente done` today. The skill's
      **Nunca** block tells the model to report `error` from JSON — and there is no JSON. Pre-existing
      Fase 1 debt, deliberately not fixed here (it would change the contract of every subcommand and
      belongs in its own change). Recorded so it is a known hole, not a surprise.
- [ ] **No `rutina bloque edit` / `move` / `item deactivate`.** Out of scope per the proposal;
      `activo` can currently only be flipped with direct SQL, which contradicts "the CLI is the only
      data gateway". The first time the user wants to retire an item, this becomes the next change —
      `rutina item deactivate --id` is the obvious minimal addition.
- [ ] **`hora_objetivo` is stored and never used.** Deliberate (reminders are out of scope). Worth
      re-reading before it accumulates a second unused column.
- [ ] **Streaks (`racha_actual` / `mejor_racha`) are the only computed field not strictly required by
      the proposal.** Kept because §5.6's weekly message is the motivational surface and a streak is
      the cheapest honest signal there. If `sdd-tasks` needs to cut scope, this is the first thing to
      drop — the JSON keys simply disappear, nothing else depends on them.

---

**Next**: `sdd-tasks` (requires `spec.md` as well).
