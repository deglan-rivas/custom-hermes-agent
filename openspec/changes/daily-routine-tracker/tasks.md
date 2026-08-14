# Tasks: Daily Routine Tracker (`daily-routine-tracker`)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~750-950 (schema.sql ~90, vida.py ~450-550, test_vida.py ~250-300, skill ~120, cron-jobs.md ~40) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 -> PR 2 |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending (ask user) |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Migration mechanism + dificultad column + rutina schema/CLI + tests | PR 1 | schema.sql, vida.py, test_vida.py — the risky, must-be-together core (~700-800 lines). Base: main (stacked) or tracker branch (feature-branch-chain) |
| 2 | Skill file + cron-jobs.md + rollout/verification | PR 2 | rutina-diaria SKILL.md, cron-jobs.md edits, P0.1/P0.2 execution, prod apply, smoke tests (~160-200 lines + manual steps). Base: PR 1's merge point |

Unit 1 alone (schema.sql + vida.py + test_vida.py) likely exceeds 400 lines on its own — if so, ask user whether to split further into 1a (migration mechanism + dificultad only) and 1b (rutina tables + subcommands + tests), sequenced strictly after 1a merges.

## Phase 0: Migration Mechanism (highest risk — sequence first, P0.1-gated)

- [x] 0.1 In `asistente_personal/bin/vida.py`, add `TARGET_SCHEMA_VERSION = 2` and `MIGRATIONS: dict[int, tuple[str, ...]]` with the version-2 block (dificultad ALTER + 3 rutina_* CREATE TABLE + 3 CREATE INDEX), per design.md §3.
- [x] 0.2 Add `_schema_version(conn)` helper: `SELECT COALESCE(MAX(version), 0) FROM schema_version`.
- [x] 0.3 Rewrite `_ensure_schema()` (replaces `bin/vida.py:152-160`): fresh DB → `executescript(schema.sql)`; existing DB → call `_aplicar_migraciones(conn)`.
- [x] 0.4 Add `_aplicar_migraciones(conn)`: per-version loop, `conn.isolation_level = None`, explicit `BEGIN IMMEDIATE` / per-statement `execute` / `INSERT INTO schema_version` last / `COMMIT`, `ROLLBACK` + re-raise on exception, restore `isolation_level` in `finally`. Raise `VidaError("migracion_faltante")` if a version has no MIGRATIONS entry.
- [x] 0.5 Update `asistente_personal/data/schema.sql`: append `dificultad` column to `pendientes` (last position, per D-1), append 3 `rutina_*` tables + 3 indexes with `IF NOT EXISTS`, change final line to `INSERT OR IGNORE INTO schema_version (version) VALUES (1), (2);`, update header comment per design.md §3 item 4.
- [x] 0.6 Extend `health` subcommand (`vida.py`) so `tablas` includes `rutina_bloques`, `rutina_items`, `rutina_completado` (needed for P0.1 row-count verification).

### Migration Tests (test_vida.py — TestMigracionV1aV2)

- [x] 0.7 RED: Write `TestMigracionV1aV2` fixture — helper that builds a v1 DB from a frozen v1 DDL constant (NOT the live `schema.sql`), seeds sample rows in every v1 table.
- [x] 0.8 RED/GREEN: `test_v1_db_is_migrated_to_v2_on_open` — `MAX(version) == 2`, rows for version 1 and 2 exist.
- [x] 0.9 RED/GREEN: `test_migration_preserves_every_row` — row counts + spot-checked row identical before/after (automates P0.1's row-count criterion).
- [x] 0.10 RED/GREEN: `test_existing_pendientes_get_null_dificultad`.
- [x] 0.11 RED/GREEN: `test_new_tables_exist_after_migration`.
- [x] 0.12 RED/GREEN: `test_fresh_bootstrap_and_migrated_v1_have_identical_schema` — compare `PRAGMA table_info`/`index_list`/`index_info`/`foreign_key_list` between fresh-bootstrap DB and v1-then-migrated DB (D-0.4 guard; do NOT compare raw `sqlite_master.sql` text).
- [x] 0.13 RED/GREEN: `test_migration_is_idempotent` — opening an already-v2 DB twice more is a no-op.
- [x] 0.14 RED/GREEN: `test_failed_migration_rolls_back_completely` — monkeypatch `MIGRATIONS[2]` with an invalid last statement, assert `MAX(version) == 1` and no `rutina_*` tables/`dificultad` column exist after the failure (validates the `BEGIN IMMEDIATE` transactional design).
- [x] 0.15 RED/GREEN: `test_missing_migration_definition_reports_json_error` — patched `TARGET_SCHEMA_VERSION = 3`, no `MIGRATIONS[3]` → `codigo == "migracion_faltante"`.
- [x] 0.16 RED/GREEN: `test_fresh_db_never_runs_migrations` — patch `MIGRATIONS = {}`, confirm bootstrap still succeeds via `schema.sql` alone.
- [x] 0.17 Run full existing suite (47 tests) + new migration tests locally — confirm zero regressions before proceeding to any other phase.

**GATE — do not proceed past this point until 0.1-0.17 are green locally.** This is the highest-risk piece; nothing below should land in the same commit sequence without this passing.

## Phase 1: `pendientes.dificultad` (CLI surface)

- [x] 1.1 In `vida.py`, add `--dificultad` optional flag to `pendiente add`, validated against `('facil','media','dificil')` before INSERT, `codigo: "validacion"` on bad value (mirrors `--prioridad`).
- [x] 1.2 Confirm `pendiente today` / `pendiente done` require no code change (SELECT * picks up the new column) — add a comment noting this is intentional/additive.
- [x] 1.3 Test: `test_pendiente_add_con_dificultad` — persists and is echoed back in JSON.
- [x] 1.4 Test: `test_pendiente_add_dificultad_invalida_fails_cleanly` — `codigo: "validacion"`.
- [x] 1.5 Test (TestSchemaConstraints): `test_dificultad_invalida_rejected` — raw `sqlite3.IntegrityError` on a bad CHECK value.

## Phase 2: `rutina` Data Model + Subcommand Group

- [ ] 2.1 Wire `rutina` subparser group in `vida.py`: `subparsers.add_parser("rutina")`, nested `add_subparsers(dest="subcomando", required=True)`, leaves named `bloque-add`, `item-add`, `today`, `done`, `historial`, `stats` (hyphenated per design.md §5, NOT a 3rd parser level).
- [ ] 2.2 Implement `cmd_rutina_bloque_add(conn, args)`: `--nombre` (normalized `strip().lower()`, UNIQUE), `--hora-objetivo`, `--orden`, `--fuente`; `codigo: "duplicado"` on UNIQUE violation.
- [ ] 2.3 Implement `cmd_rutina_item_add(conn, args)`: `--nombre` + one of `--bloque`|`--bloque-id`; resolves block by name (UNIQUE), `codigo: "no_encontrado"` listing existing block names on miss; `UNIQUE(bloque_id, nombre)` → `codigo: "duplicado"`.
- [ ] 2.4 Implement `cmd_rutina_today(conn, args)`: `--fecha` (default hoy), `--sin-pendientes`; JSON contract per design.md §5.2 — `bloques[].items[]` with `hecho_hoy`/`hecho_a_las`, `pct` null-safe, `resumen`, `pendientes` (byte-for-byte `pendiente today` payload) unless `--sin-pendientes`. Only `activo=1`, ordered `orden ASC, id ASC`.
- [ ] 2.5 Implement `cmd_rutina_done(conn, args)`: `--id` required int, `--fecha` (default hoy), `--fuente`; error table per design.md §5.5 (`no_encontrado`, `id_es_bloque`, `item_inactivo`, `fecha_futura`); `ya_estaba: true` (not error) on duplicate, exit 0.
- [ ] 2.6 Implement `cmd_rutina_historial(conn, args)`: `--fecha` XOR `--desde`/`--hasta`; returns `rutina_completado` + `pendientes.completado_en` per day in range, including empty days.
- [ ] 2.7 Implement `cmd_rutina_stats(conn, args)`: `--desde`, `--hasta`, optional `--bloque`; compute `oportunidades`/`completados`/`pct` per item (from `desde_efectivo = max(--desde, item.creado_en)`, D-7) and rollups per block/global (sum-then-divide, never average-of-percentages); `racha_actual`/`mejor_racha` streaks.
- [ ] 2.8 Implement `_parse_fecha` extension: accept `hoy`/`ayer`/`anteayer` literals in addition to ISO (D-8); `codigo: "fecha_invalida"` otherwise.
- [ ] 2.9 Register all 6 `cmd_rutina_*` functions via `set_defaults(func=...)`; confirm `_accion()` yields `rutina.bloque-add`, `rutina.item-add`, `rutina.today`, `rutina.done`, `rutina.historial`, `rutina.stats`.

### `rutina` Subcommand Tests (test_vida.py — TestRutinaSubcomandos)

- [ ] 2.10 RED/GREEN: `test_bloque_add_and_item_add` — happy path, `--bloque` name resolution.
- [ ] 2.11 RED/GREEN: `test_bloque_add_duplicate_nombre_fails_cleanly`.
- [ ] 2.12 RED/GREEN: `test_bloque_nombre_is_normalised`.
- [ ] 2.13 RED/GREEN: `test_item_add_unknown_bloque_fails_cleanly`.
- [ ] 2.14 RED/GREEN: `test_item_add_duplicate_in_same_bloque_fails_cleanly`.
- [ ] 2.15 RED/GREEN: `test_today_shape_and_ordering`.
- [ ] 2.16 RED/GREEN: `test_today_pct_is_null_when_no_items`.
- [ ] 2.17 RED/GREEN: `test_today_excludes_inactive`.
- [ ] 2.18 RED/GREEN: `test_today_includes_pendientes_and_sin_pendientes_flag`.
- [ ] 2.19 RED/GREEN: `test_done_marks_item_and_today_reflects_it`.
- [ ] 2.20 RED/GREEN: `test_done_twice_is_idempotent` — one row in `rutina_completado`, `ya_estaba: true` on 2nd call.
- [ ] 2.21 RED/GREEN: `test_done_unknown_id_fails_cleanly`.
- [ ] 2.22 RED/GREEN: `test_done_with_bloque_id_reports_id_es_bloque`.
- [ ] 2.23 RED/GREEN: `test_done_inactive_item_fails_cleanly`.
- [ ] 2.24 RED/GREEN: `test_done_future_date_fails_cleanly`.
- [ ] 2.25 RED/GREEN: `test_next_day_checklist_is_clean_without_any_reset` — the D-2 success criterion.
- [ ] 2.26 RED/GREEN: `test_historial_fecha_and_rango`.
- [ ] 2.27 RED/GREEN: `test_stats_percentages_match_a_hand_calculation` — 3 items x 10 days seeded grid, verified by hand-computed numbers.
- [ ] 2.28 RED/GREEN: `test_stats_desde_efectivo_respects_item_creation`.
- [ ] 2.29 RED/GREEN: `test_stats_streaks`.
- [ ] 2.30 RED/GREEN: `test_stats_pct_null_when_no_opportunities`.
- [ ] 2.31 RED/GREEN: `test_fecha_relativa_hoy_ayer_anteayer`.
- [ ] 2.32 Test (TestSchemaConstraints): `test_unique_item_fecha_rejected`, `test_delete_bloque_con_items_is_restricted`.
- [ ] 2.33 Test (TestSubcommandContract): `test_health_incluye_tablas_rutina`.
- [ ] 2.34 Run full suite (47 existing + ~35 new) — confirm green before Phase 3.

## Phase 3: `skills/rutina-diaria/SKILL.md`

- [ ] 3.1 Create `asistente_personal/skills/rutina-diaria/SKILL.md` with YAML frontmatter (`name`, trigger-phrase `description`) per design.md §6.
- [ ] 3.2 Write "Cuándo se activa" section: setup/daily/query trigger phrases, explicit contrast with `agenda-personal` ("recordame X" = pendiente vs "todos los días hago X" = rutina).
- [ ] 3.3 Write "Comando exacto" section: literal `python3 /opt/data/bin/vida.py rutina ...` invocations in usage order (today → done → bloque-add/item-add → historial/stats).
- [ ] 3.4 Write "Mapeo de lenguaje natural → flags" table per design.md §6.
- [ ] 3.5 Write "Cómo responder" section: read `resumen.pct`, `ya_estaba` handling, `pct: null` handling, echo-back after bloque-add/item-add.
- [ ] 3.6 Write "Nunca" section: shared Fase 1 block verbatim + two domain-specific lines (never guess `item_id`, never compute percentages/streaks locally).

## Phase 4: `ops/cron-jobs.md` Edits

- [ ] 4.1 Edit existing §5.1 (7am briefing): replace quoted message per design.md §9.1 — drop `pendiente today` call (rutina today now returns pendientes too), add rutina checklist reporting instructions, note "Extended by daily-routine-tracker D-5. Re-register with §5.5's smoke-test procedure."
- [ ] 4.2 Add new §5.6 (Monday 8:15am adherence summary) per design.md §9.2, inserted before the existing §5.5 smoke-test section.

## Phase 5: Rollout / Verification (production-gated, sequential, manual)

- [ ] 5.1 **P0.1 (BLOCKING)**: Copy `vida.db` from labia03 (or use `ops/db-snapshot.sh` output). Run migration against the COPY only. Verify: `schema_version = 2`, 3 new tables exist, `pendientes.dificultad` present and NULL on all pre-existing rows, `PRAGMA integrity_check` OK, row counts identical in `gastos`/`entrenamientos`/`tarjetas`/`contactos`/`pendientes` before/after (use extended `vida.py health`, diffed). Do NOT touch production until this passes.
- [ ] 5.2 **P0.2 (BLOCKING)**: Verify fresh restic backup (<24h) exists immediately before production apply; if Fase 1 F0.5 (offsite backup) is still open, take an off-host local `vida.db` copy as minimum fallback.
- [ ] 5.3 Deploy: `docker compose stop hermes` → deploy code → `docker compose up -d hermes`. First `vida.py` invocation triggers the migration.
- [ ] 5.4 Run `vida.py health` on labia03 — confirm `schema_version: 2`, `integrity_ok: true`, unchanged row counts.
- [ ] 5.5 Copy `skills/rutina-diaria/` into `$HERMES_DATA/skills/`; confirm `ops/skills-autocommit.sh` picks it up.
- [ ] 5.6 Re-register the 7am briefing job with §9.1's new text via Telegram (after closing the Fase 1 operational gap — job was never actually registered); smoke-test per §5.5 of cron-jobs.md.
- [ ] 5.7 Register the new §5.6 Monday adherence job via Telegram; smoke-test the same way.
- [ ] 5.8 Live Telegram smoke test: describe a routine in natural language once, confirm `rutina today` returns correct blocks/items.
- [ ] 5.9 Live Telegram smoke test: say "ya me duché", confirm the correct item is marked (resolved via `rutina today`, no invented id).
- [ ] 5.10 Live Telegram smoke test: confirm next-day checklist is clean (`hecho_hoy: false`) with zero reset job involved.
- [ ] 5.11 Live Telegram smoke test: confirm 7am briefing includes routine content alongside pendientes/gym.
- [ ] 5.12 Live Telegram smoke test: confirm Monday adherence summary arrives with correct percentages.
- [ ] 5.13 Confirm full success criteria checklist in `proposal.md §10` is satisfied.

## Rules Applied

- TDD: RED (write failing test) → GREEN (implement) pairs used throughout Phase 0 and Phase 2 test tasks per Strict TDD Mode.
- Phase 0 is gated: no Phase 1-2 work should land ahead of Phase 0's green migration test suite.
- Phase 5 is entirely production-facing and sequential; nothing in it can run in parallel with itself.
