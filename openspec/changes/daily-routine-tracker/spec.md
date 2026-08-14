# Spec: Daily Routine Tracker (`daily-routine-tracker`)

Change: `daily-routine-tracker` | Type: delta spec against `openspec/changes/hermes-personal-assistant/spec.md` (Fase 1, in production). Sections below are grouped by capability per proposal §3: three **New Capabilities** and two **Modified Capabilities**. Modified sections reference the Fase 1 requirement they extend or replace; unlisted Fase 1 requirements are unaffected and remain in force unchanged.

---

## 1. New Capability: `schema-migration`

### Requirement: Versioned incremental migration replaces existence-check bootstrap
`vida.py` MUST determine the currently applied schema version by reading `MAX(version)` from `schema_version`, and MUST apply every migration block whose version is greater than the currently applied version, in ascending order, instead of skipping schema application whenever the `schema_version` table already exists.

#### Scenario: Fresh database (no `schema_version` table)
- GIVEN an empty `vida.db` with no tables
- WHEN `vida.py` opens a connection
- THEN the full bootstrap schema is applied and `schema_version` ends at the latest defined version (currently 2)

#### Scenario: Production database at v1 gains v2 migrations
- GIVEN a `vida.db` where `schema_version` contains exactly `{version: 1}` and has existing rows in `gastos`, `entrenamientos`, `tarjetas`, `contactos`, `pendientes`
- WHEN `vida.py` opens a connection
- THEN the migration block(s) for version 2 are applied and `schema_version` MAX(version) becomes 2
- AND row counts in `gastos`, `entrenamientos`, `tarjetas`, `contactos`, `pendientes` are unchanged before and after

### Requirement: Each migration block is transactional and idempotent
Each versioned migration block MUST run inside a single SQLite transaction, with the corresponding `INSERT INTO schema_version (version, ...)` as the last statement of that transaction. Re-running the migration process against a database already at or above a given version MUST NOT re-apply that version's block and MUST NOT error.

#### Scenario: Crash mid-migration leaves no partial state
- GIVEN a migration block for version N is interrupted before its transaction commits (e.g. process killed)
- WHEN `vida.py` is started again against the same database
- THEN `schema_version` MAX(version) is still N-1 (the commit never happened) and the version-N block is retried in full, not resumed partially

#### Scenario: Migration re-run against an already-migrated database is a no-op
- GIVEN `vida.db` with `schema_version` MAX(version) = 2 and the version-2 block already applied
- WHEN `vida.py` opens a connection again
- THEN no DDL statement from the version-2 block executes a second time and no error is raised

### Requirement: Bootstrap and migration produce identical schemas
Applying `schema.sql` to an empty database MUST produce a schema equivalent to applying the version-1 bootstrap followed by every subsequent migration block to a version-1 database.

#### Scenario: Fresh bootstrap matches migrated database
- GIVEN database A is created by applying `schema.sql` directly to an empty file
- AND database B starts at `schema_version = 1` (Fase 1 layout) and is migrated to `schema_version = 2`
- WHEN table/column/constraint definitions of A and B are compared
- THEN they are equivalent (same tables, same columns, same types and constraints, same `schema_version` end state)

---

## 2. New Capability: `rutina-diaria`

### Requirement: Routine data model — blocks, items, append-only completion log
`schema.sql` MUST define `rutina_bloques` (`nombre`, `hora_objetivo`, `orden`, `activo`), `rutina_items` (`bloque_id` referencing `rutina_bloques`, `nombre`, `orden`, `activo`), and `rutina_completado` as an append-only log with `UNIQUE (item_id, fecha)`, where `item_id` references `rutina_items`.

#### Scenario: Routine table creation via migration
- GIVEN a `vida.db` migrated to `schema_version = 2`
- WHEN inspecting `sqlite_master`
- THEN `rutina_bloques`, `rutina_items`, and `rutina_completado` all exist with their defined columns and constraints

### Requirement: Completion is append-only — no reset job required
Marking an item done for a given day MUST be represented as inserting a row into `rutina_completado` with today's `fecha`. The system MUST NOT implement, schedule, or require any job, cron, or code path that deletes, clears, or resets rows in `rutina_completado` or flips a "done" flag back to false at day change.

#### Scenario: Next day's checklist is clean without any reset job
- GIVEN an item was marked done yesterday (a `rutina_completado` row exists with `fecha = yesterday`)
- AND no reset job of any kind has run
- WHEN `rutina today` is invoked today
- THEN the item shows `hecho_hoy: false` today, purely because no `rutina_completado` row exists for `fecha = today`, and the yesterday row is untouched

#### Scenario: Marking the same item done twice today does not error or duplicate ambiguously
- GIVEN an item was already marked done today
- WHEN `rutina done` is invoked again for the same item and today's date
- THEN the operation is idempotent with respect to the `UNIQUE (item_id, fecha)` constraint — it does not create a duplicate log entry, and the CLI reports success without raising a constraint error to the caller

### Requirement: `vida.py rutina` subcommand group
`vida.py` MUST expose a `rutina` subcommand group (not a separate CLI/script) with: `rutina bloque add`, `rutina item add`, `rutina today`, `rutina done`, `rutina historial`, `rutina stats`. All subcommands MUST follow the existing JSON stdout contract (`{"ok": true, "action": "...", "data": {...}}` on success; `{"ok": false, "action": "...", "error": "...", "codigo": "..."}` on failure).

#### Scenario: Block and item registration
- GIVEN the user has described a routine in natural language
- WHEN the agent calls `vida.py rutina bloque add --nombre "Asearme" --hora-objetivo 07:30` followed by `vida.py rutina item add --bloque-id <id> --nombre "Ducharse"`
- THEN a `rutina_bloques` row and a `rutina_items` row referencing it exist, and both calls return `ok: true` JSON with the inserted record

#### Scenario: `rutina today` returns a single deterministic JSON combining routine and pendientes
- GIVEN active routine blocks/items exist and there are open `pendientes`
- WHEN `vida.py rutina today` runs
- THEN stdout is one JSON document containing today's routine items (each with `hecho_hoy` computed from `rutina_completado`) and open `pendientes`, filtered to `activo = 1` blocks/items

### Requirement: `rutina done` never guesses an item id
The `rutina done` subcommand MUST require an explicit, previously-resolved `item_id` (or equivalent unambiguous identifier already returned by `rutina today`). It MUST NOT accept free-text item descriptions that require the CLI or caller to infer/guess which item is meant.

#### Scenario: Marking "ya me duché" done
- GIVEN the user says "ya me duché" via Telegram
- WHEN the agent processes this request
- THEN it MUST first call `rutina today` to resolve the correct `item_id` for "Ducharse" from the returned JSON, and only then call `rutina done --item-id <resolved id>`
- AND the agent MUST NOT call `rutina done` with an id it did not read from a prior `rutina today`/`rutina historial` response

#### Scenario: Ambiguous or unresolved item is rejected, not guessed
- GIVEN `rutina today` returns no item matching the user's description unambiguously
- WHEN the agent cannot resolve a single `item_id`
- THEN the agent MUST ask the user for clarification instead of calling `rutina done` with an inferred id, and `rutina done` MUST error (`ok: false`) if invoked with a nonexistent `item_id`

### Requirement: `rutina historial` covers a single day or a range
`rutina historial` MUST accept either `--fecha <fecha o relativo>` (single day) or `--desde`/`--hasta` (range), and MUST return, for the requested period, both `rutina_completado` rows and `pendientes.completado_en` entries falling in that period.

#### Scenario: Historial for a single relative day
- GIVEN routine items and pendientes were completed yesterday
- WHEN `vida.py rutina historial --fecha ayer` runs
- THEN the JSON output lists exactly the `rutina_completado` rows and `pendientes` completions from yesterday

#### Scenario: Historial for a date range
- GIVEN completions exist across several days
- WHEN `vida.py rutina historial --desde 2026-07-01 --hasta 2026-07-07` runs
- THEN the JSON output lists exactly the completions whose date falls within `[2026-07-01, 2026-07-07]`

### Requirement: `skills/rutina-diaria/SKILL.md` — setup, daily interaction, and anti-hallucination guardrails
The system MUST include a new skill `rutina-diaria`, separate from `agenda-personal`, that: (a) translates a natural-language routine description into `rutina bloque add` / `rutina item add` calls during setup, (b) resolves "ya hice X" style messages to an `item_id` via `rutina today` before calling `rutina done`, and (c) explicitly instructs the agent to never invent completion state, never compute percentages itself, and always read them from the JSON returned by `rutina today` / `rutina stats`.

#### Scenario: Skill routes routine setup correctly
- GIVEN the user describes their morning routine in one message
- WHEN the agent applies `rutina-diaria`
- THEN it issues the corresponding `rutina bloque add` / `rutina item add` calls, not `pendiente add`

#### Scenario: Skill never estimates completion state
- GIVEN the user asks "¿ya hice todo hoy?"
- WHEN the agent applies `rutina-diaria`
- THEN it answers strictly from the `hecho_hoy` values in the JSON returned by `rutina today`, without inferring or guessing state from conversation memory

---

## 3. New Capability: `rutina-stats`

### Requirement: Completion-rate reporting is computed in SQL/Python, never by the LLM
`vida.py rutina stats --desde <fecha> --hasta <fecha>` MUST return completion rates per block and per item for the given range, computed entirely via SQL aggregation and/or deterministic Python arithmetic over `rutina_completado` and `rutina_items`/`rutina_bloques`. No percentage or count in the output MAY be produced, adjusted, or estimated by the LLM.

#### Scenario: Stats reflect real counts over a range
- GIVEN known `rutina_completado` rows over a 7-day range for a given item (e.g. done on 5 of 7 days)
- WHEN `vida.py rutina stats --desde <range start> --hasta <range end>` runs
- THEN the JSON output reports that item's completion rate as `5/7` (~71.4%), matching a manual count over the same rows

#### Scenario: Stats consumer only reads, never recomputes
- GIVEN the weekly adherence cron job or the `rutina-diaria` skill needs to report adherence
- WHEN it produces its message
- THEN it uses the percentages/counts exactly as returned by `rutina stats` JSON, performing no independent calculation

---

## 4. Modified Capability: Structured Data Layer (extends Fase 1 spec §2)

### Requirement: `pendientes` gains an optional `dificultad` column
`pendientes` MUST gain a nullable `dificultad` column with `CHECK (dificultad IS NULL OR dificultad IN ('facil','media','dificil'))`, defaulting to `NULL`. This is additive to, and does not rename or replace, the existing `prioridad` column (which continues to represent urgency).

#### Scenario: New pendiente with dificultad
- GIVEN the agent calls `vida.py pendiente add --titulo "Pagar la luz" --dificultad facil`
- WHEN the command completes
- THEN the inserted row has `dificultad = 'facil'` and stdout is valid JSON reflecting it

#### Scenario: Existing pendientes are unaffected
- GIVEN `pendientes` rows created under Fase 1 (before this migration) with no `dificultad` value
- WHEN `vida.db` is migrated to `schema_version = 2`
- THEN those rows have `dificultad = NULL`, all their other columns are unchanged, and `vida.py pendiente today` / existing Fase 1 skills continue to function exactly as before without modification

### Requirement: CLI-as-only-data-gateway extends to the `rutina` domain
The Fase 1 requirement "CLI is the only data gateway" (spec §2) extends to cover `rutina_bloques`, `rutina_items`, and `rutina_completado`: all reads and writes to these tables MUST go through `vida.py rutina *` subcommands, implemented in the same Python-stdlib, no-ORM, JSON-stdout `vida.py`, not through a separate script or database.

#### Scenario: Routine data lives in the same CLI and database as pendientes
- GIVEN `rutina today` needs to combine routine items with open `pendientes`
- WHEN it executes
- THEN both datasets are read from the same `vida.db` via the same `vida.py` process, with no second CLI, second bind mount, or second database file involved

### Requirement: Greenfield-bootstrap assumption is replaced by versioned migration
The Fase 1 assumption that schema application only ever needs to run once against an empty database (`_ensure_schema()` short-circuiting whenever `schema_version` exists) is replaced by the versioned migration mechanism defined in §1 (`schema-migration`) above. `_ensure_schema()` MUST be updated to compare `MAX(version)` against the latest defined version rather than merely checking table existence.

#### Scenario: A previously-"final" Fase 1 database still receives new schema
- GIVEN a `vida.db` bootstrapped under Fase 1's original `_ensure_schema()` (existence-check only), now at `schema_version = 1`
- WHEN the updated `vida.py` (post this change) opens a connection to it
- THEN it detects `MAX(version) = 1 < 2` and applies the pending version-2 migration block, rather than treating the presence of `schema_version` as "nothing to do"

---

## 5. Modified Capability: Proactivity / Cron (extends Fase 1 spec §5)

### Requirement: 7am briefing job is edited, not duplicated, to include routine
The existing ~7am daily briefing cron job (Fase 1 spec §5, `ops/cron-jobs.md §5.1`) MUST be edited in place to additionally include the output of `rutina today`'s routine portion, alongside the pendientes and gym content it already sends. No second, parallel 7am job MAY be created.

#### Scenario: Morning briefing includes today's routine
- GIVEN it is 07:00 Lima time and the (edited) briefing job fires
- WHEN the Telegram message is composed
- THEN it includes pending items, today's training targets, AND today's routine checklist (from `rutina today`), all in a single message from the single existing job

### Requirement: New weekly routine-adherence cron job
A new weekly cron job MUST run on Mondays, structurally parallel to the existing weekly expense summary (Fase 1 spec §5 / `ops/cron-jobs.md §5.4`), delivering a Telegram summary of the previous week's `rutina stats` output.

#### Scenario: Monday adherence summary delivered unprompted
- GIVEN it is Monday and the weekly adherence cron job fires
- WHEN the job runs
- THEN it calls `vida.py rutina stats --desde <last Monday> --hasta <last Sunday>` and sends a Telegram message using those percentages/counts as-is, without independent recalculation

---

## Out of Scope (unchanged from proposal §2 "Fuera de alcance")
Reminders/alerts near `hora_objetivo`; any UI outside Telegram conversation; editing/reordering blocks or items other than natural-language re-registration; Fase 2 (Claude Code bridge, TTS, etc.).
