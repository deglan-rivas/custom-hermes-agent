# Tasks: Pendientes Lifecycle (`pendientes-lifecycle`)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~950-1150 total (PR1 ~750-900: schema.sql ~30, vida.py ~350-450, test_vida.py ~300-380, skill ~40; PR2 ~230-280: vida.py ~130-150, test_vida.py ~90-100, skill addendum ~30, cron-jobs.md note ~15) |
| 400-line budget risk | High (both PRs individually reviewed under budget; PR1 alone risks exceeding 400 without the split) |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 -> PR 2 |
| Delivery strategy | ask-on-risk (already resolved by user) |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Schema migration v2->v3 + `pendiente today` fix (G1) + `pendiente edit` (G2) + recurring reset (G4) + skill G-1/G-2 doc + prod rollout | PR 1 | schema.sql, vida.py, test_vida.py, SKILL.md — behavioral+schema core (~750-900 lines). Base: main (stacked) |
| 2 | `pendiente historial` + `pendiente stats` (G3) + skill addendum + cron-jobs.md note | PR 2 | Additive/read-only, no migration (~230-280 lines). Base: PR 1's merge point |

## Phase 0: Migration Mechanism v2 -> v3 (PR1, highest risk, sequence first)

- [x] 0.1 In `asistente_personal/bin/vida.py`, bump `TARGET_SCHEMA_VERSION = 3` and add `MIGRATIONS[3]` tuple per design.md §3: `CREATE TABLE pendientes_completado` (id, pendiente_id FK ON DELETE RESTRICT, fecha, creado_en, fuente CHECK, `UNIQUE(pendiente_id, fecha)`), 2 `CREATE INDEX` statements, backfill `INSERT ... SELECT id, date(completado_en), completado_en, fuente FROM pendientes WHERE completado_en IS NOT NULL`. Do NOT touch `MIGRATIONS[2]` or `_ensure_schema`/`_aplicar_migraciones`.
- [x] 0.2 Update `asistente_personal/data/schema.sql`: append `pendientes_completado` table (`CREATE TABLE IF NOT EXISTS`) + 2 indexes (`CREATE INDEX IF NOT EXISTS`), change final line to `INSERT OR IGNORE INTO schema_version (version) VALUES (1), (2), (3);`, update header comment to reference `pendientes-lifecycle/design.md §3`.
- [x] 0.3 Extend `cmd_health`/`health` subcommand so `tablas` includes `pendientes_completado` (design §5.8 — this is the P0.1 row-count verification tool).

### Migration Tests (`test_vida.py` — `TestMigracionV2aV3`, new class)

- [x] 0.4 RED: Write `TestMigracionV2aV3` fixture — frozen v2 DDL constant (not the live `schema.sql`), seed `pendientes` rows including closed ones with `completado_en` set.
- [x] 0.5 RED/GREEN: `test_v2_db_is_migrated_to_v3_on_open` — `MAX(version) == 3`, rows for versions 1/2/3 all present.
- [x] 0.6 RED/GREEN: `test_migration_preserves_every_row` — per-table row counts + spot-checked row identical before/after (automates P0.1's row-count criterion).
- [x] 0.7 RED/GREEN: `test_backfill_creates_one_log_row_per_closed_pendiente` — D-5: every pre-existing `completado_en IS NOT NULL` row gets exactly one log row with `fecha == date(completado_en)`; open pendientes get none.
- [x] 0.8 RED/GREEN: `test_fresh_bootstrap_and_migrated_v2_have_identical_schema` — D-0.4 guard extended to `pendientes_completado`: `PRAGMA table_info`/`index_list`/`index_info`/`foreign_key_list`, table-name set, `schema_version` contents.
- [x] 0.9 RED/GREEN: `test_migration_is_idempotent` — reopening a v3 DB twice: no duplicate `schema_version` rows, no duplicate backfill rows.
- [x] 0.10 RED/GREEN: `test_failed_migration_rolls_back_completely` — patch `MIGRATIONS[3]` last statement invalid, assert `MAX(version) == 2` and `pendientes_completado` does not exist.
- [x] 0.11 RED/GREEN: `test_health_incluye_pendientes_completado`.
- [x] 0.12 GREEN (sanctioned edit, not a regression): update the existing `test_health` to assert `schema_version == 3` instead of `2` — design §7.1 explicitly flags this as the one sanctioned edit outside the frozen test set; do not second-guess it.
- [x] 0.13 Run full existing suite + new migration tests locally — confirm zero regressions before proceeding.

**GATE — do not proceed past this point until 0.1-0.13 are green locally.**

## Phase 1: `pendiente done` rewrite (G4 — recurring reset, D-1/D-2/D-3)

- [x] 1.1 Rewrite `cmd_pendiente_done` per design §5.2: always `SELECT` the row first (`no_encontrado` if missing); on first call today, `INSERT` into `pendientes_completado (pendiente_id, fecha, creado_en, fuente)`; if `recurrencia` is non-NULL, update only `completado_en` (estado stays `'abierto'`); if NULL, update `estado='hecho'` + `completado_en` exactly as today. Payload gains `fecha`, `ya_estaba`, `hecho_a_las`, `recurrente`; no existing key removed.

### `TestPendienteRecurrente` tests (new class, PR1)

- [x] 1.2 RED/GREEN: `test_recurrente_diaria_desaparece_hoy_tras_done`.
- [x] 1.3 RED/GREEN: `test_recurrente_diaria_reaparece_manana` — seed a log row dated yesterday, assert it shows today.
- [x] 1.4 RED/GREEN: `test_recurrente_no_cambia_de_estado` — `estado` stays `'abierto'`, `completado_en` moves.
- [x] 1.5 RED/GREEN: `test_recurrente_semanal_no_aparece_fuera_de_su_dia` — D-6 regression guard.
- [x] 1.6 RED/GREEN: `test_recurrente_mensual_respeta_clamp` — `mensual:31` in a 30-day month.
- [x] 1.7 RED/GREEN: `test_done_dos_veces_mismo_dia_es_idempotente` — `ok: true`, `ya_estaba: true`, exactly one log row.
- [x] 1.8 RED/GREEN: `test_one_shot_done_sigue_marcando_hecho` — D-1: one-shot writes `estado='hecho'` AND a log row.

## Phase 2: `pendiente today` fix (G1 — sin_fecha, unbounded, sort)

- [x] 2.1 Rewrite `cmd_pendiente_today`'s inclusion rule per design §5.3, D-6: branch exclusively on `recurrencia` — recurring rows selected ONLY via `_recurrencia_vence_hoy` AND absence from today's `pendientes_completado` set (one query, no N+1); non-recurring rows keep `vence_hoy`/`vencido`/add new `fecha_objetivo IS NULL` term. Remove any `LIMIT`/cap.
- [x] 2.2 Add derived `sin_fecha` boolean per item (`fecha_objetivo IS NULL`), never persisted.
- [x] 2.3 Add `DIFICULTAD_ORDEN = {"facil": 0, "media": 1, "dificil": 2}` and change sort key to `(prioridad, dificultad, hora, id)` — `id` as final tiebreak (D-8). **Deviation**: implemented as `DIFICULTAD_ORDEN.get(dificultad, 1)`, i.e. NULL ties with `media` (rank 1) per design.md D-7 and the sdd-apply task brief's explicit hard constraint, NOT "NULL sorts last" as this line's parenthetical and spec.md §5 literally say. design.md D-7 explicitly argues against the spec's naive reading (behaviour-preservation for production data where every row has `dificultad = NULL`) and state.yaml already records this exact spec/design conflict under `resolved_design_questions.Q2` vs the stale `open_design_questions.Q2`. Flagging for sdd-verify to confirm this resolution is accepted.

### `TestPendienteToday` tests (new class, PR1)

- [x] 2.4 RED/GREEN: `test_sin_fecha_aparece_y_marca_flag`.
- [x] 2.5 RED/GREEN: `test_con_fecha_marca_sin_fecha_false`.
- [x] 2.6 RED/GREEN: `test_sin_limite` — N open pendientes (mixed dated/undated/recurring) yield N items.
- [x] 2.7 RED/GREEN: `test_orden_prioridad_luego_dificultad`.
- [x] 2.8 RED/GREEN: `test_dificultad_null_ordena_como_media` (renamed from `test_dificultad_null_ordena_ultimo` to match the D-7 resolution above) — NULL ties with `media` (rank 1) and sorts BEFORE `dificil` within the same `prioridad` tier.
- [x] 2.9 RED/GREEN: `test_orden_desempata_por_hora_luego_id`.
- [x] 2.10 RED/GREEN: `test_vencidos_siguen_apareciendo` — no regression on `--incluir-vencidos`.

## Phase 3: `pendiente edit` (G2)

- [x] 3.1 Add `pendiente_edit` argparse subparser in `build_parser`: `--id` required + `--titulo`/`--detalle`/`--fecha`/`--hora`/`--prioridad`/`--dificultad`/`--recurrencia` optional.
- [x] 3.2 Implement `cmd_pendiente_edit` per design §5.5: literal whitelist dict maps flags to columns (never from user input); require ≥1 editable flag (`codigo: "validacion"` otherwise); `no_encontrado` on missing id; reject if `estado != 'abierto'` (`codigo: "pendiente_cerrado"`, D-10); validate `prioridad`/`dificultad` against existing CHECK sets; `""` clears a field to NULL, empty `titulo` rejected (D-9); build single `UPDATE ... SET` from supplied fields; payload = full updated row + `campos_actualizados`.

### `TestPendienteEdit` tests (new class, PR1)

- [x] 3.3 RED/GREEN: one test per editable field — persists + echoed in `campos_actualizados`.
- [x] 3.4 RED/GREEN: `test_edit_no_encontrado`.
- [x] 3.5 RED/GREEN: `test_edit_sin_campos_es_validacion`.
- [x] 3.6 RED/GREEN: `test_edit_prioridad_invalida` / `test_edit_dificultad_invalida`.
- [x] 3.7 RED/GREEN: `test_edit_fecha_vacia_limpia_el_campo` (D-9).
- [x] 3.8 RED/GREEN: `test_edit_titulo_vacio_rechazado`.
- [x] 3.9 RED/GREEN: `test_edit_pendiente_cerrado_rechazado` (D-10).
- [x] 3.10 RED/GREEN: `test_edit_no_puede_tocar_estado_ni_completado_en` — assert parser has no such flags AND row's `estado`/`creado_en`/`completado_en` unchanged after a full-field edit.

## Phase 4: Frozen-test regression check (PR1, blocking)

- [x] 4.1 Run `test_pendiente_add_today_done`, `test_pendiente_done_unknown_id_fails_cleanly`, `test_pendiente_add_con_dificultad`, `test_pendiente_add_dificultad_invalida_fails_cleanly`, and `test_invalid_estado_pendiente_rejected` unmodified — confirm all 5 pass green with zero code changes to them. This is a blocking criterion for PR1, not a nice-to-have.
- [x] 4.2 Run full suite (all existing + new PR1 tests) — confirm zero regressions in `rutina`/`gasto`/`gym`/`tarjeta`/`cumple` suites.

## Phase 5: `skills/agenda-personal/SKILL.md` update (PR1, G-5 partial)

- [x] 5.1 Document `sin_fecha` field in the `pendiente today` output-reading section.
- [x] 5.2 Document `pendiente edit --id` in the "comando exacto" section: editable fields list, and the guardrail that `--id` MUST be resolved from a prior `pendiente today`/`historial` response, never guessed.
- [x] 5.3 Add a line stating a recurring pendiente marked done today reappears on its next occurrence (not permanently closed).

## Phase 6: Production Rollout (PR1, gated, sequential, manual)

- [ ] 6.1 **P0.1 (BLOCKING)**: Copy `vida.db` from labia03 (or `ops/db-snapshot.sh` output). Run migration against the COPY only. Verify: `schema_version == 3`, `pendientes_completado` exists, `PRAGMA integrity_check == ok`, row counts unchanged for `gastos`/`entrenamientos`/`tarjetas`/`contactos`/`pendientes`/`rutina_*`, and `COUNT(pendientes_completado) == COUNT(pendientes WHERE completado_en IS NOT NULL)` (D-5 backfill against real data). Do NOT touch production until this passes.
- [ ] 6.2 **P0.2 (BLOCKING)**: Verify fresh restic backup (<24h) exists immediately before production apply; degrades to an off-host local `vida.db` copy while Fase 1 F0.5 stays open.
- [ ] 6.3 Deploy: `docker compose stop hermes` -> deploy code -> `docker compose up -d hermes`. First `vida.py` invocation migrates.
- [ ] 6.4 Run `vida.py health` on labia03 — confirm `schema_version: 3`, `integrity_ok: true`, unchanged row counts.
- [ ] 6.5 Copy updated `skills/agenda-personal/SKILL.md` into `$HERMES_DATA/skills/`; confirm `ops/skills-autocommit.sh` picks it up.
- [ ] 6.6 Verify the 7am briefing the next morning: more items, new order, `sin_fecha` present, and a recurring pendiente closed the day before NOT listed (design §8 step 7 — the only place this discrepancy can be caught).
- [ ] 6.7 Live Telegram smoke test: create an undated pendiente, confirm it appears in `pendiente today` with `sin_fecha: true`.
- [ ] 6.8 Live Telegram smoke test: mark a recurring pendiente done, confirm it disappears today and reappears on its next occurrence.
- [ ] 6.9 Live Telegram smoke test: edit a pendiente's `fecha`/`prioridad` via natural language, confirm the agent resolves `--id` from a prior `today` response before calling `edit`.

---

## PR2: `pendiente historial` + `pendiente stats` (G3, additive, read-only)

## Phase 7: `pendiente historial`

- [ ] 7.1 Add `pendiente_historial` argparse subparser: `--fecha` XOR `--desde`/`--hasta` (same validation pattern as `rutina historial`).
- [ ] 7.2 Implement `cmd_pendiente_historial` per design §5.6: single source `pendientes_completado JOIN pendientes`, day-grouped like `cmd_rutina_historial`, empty days included inside an explicit range.

### `TestPendienteHistorialStats` tests (new class, PR2)

- [ ] 7.3 RED/GREEN: `test_historial_fecha_y_rango` — sugar (`hoy`/`ayer`) + empty days present.
- [ ] 7.4 RED/GREEN: `test_historial_muestra_todas_las_ocurrencias_de_un_recurrente` — the reason D-4 exists.
- [ ] 7.5 RED/GREEN: `test_historial_incluye_completados_previos_a_la_migracion` — reads backfilled rows.

## Phase 8: `pendiente stats`

- [ ] 8.1 Add `pendiente_stats` argparse subparser: `--desde`, `--hasta` required.
- [ ] 8.2 Implement `cmd_pendiente_stats` per design §5.7: `creados`/`resueltos`/`resueltos_unicos`/`abiertos`/`vencidos`, broken down by `prioridad` and `dificultad` (with explicit `sin_clasificar` bucket, never a null key), raw counts only — no percentage, no time-to-resolution field.

### `pendiente stats` tests (same `TestPendienteHistorialStats` class, PR2)

- [ ] 8.3 RED/GREEN: `test_stats_conteos_contra_calculo_manual` — seeded grid, every number asserted by hand.
- [ ] 8.4 RED/GREEN: `test_stats_resueltos_vs_resueltos_unicos`.
- [ ] 8.5 RED/GREEN: `test_stats_desglose_por_prioridad_y_dificultad` — incl. `sin_clasificar` bucket.
- [ ] 8.6 RED/GREEN: `test_stats_vencidos_excluye_recurrentes`.
- [ ] 8.7 RED/GREEN: `test_stats_sin_porcentajes` — no `pct` or time-to-resolution key anywhere in the payload (anti-scope-creep test).

## Phase 9: Wiring, docs, and PR2 regression check

- [ ] 9.1 Register `cmd_pendiente_historial`/`cmd_pendiente_stats` via `set_defaults(func=...)`; confirm `_accion()` yields `pendiente.historial`/`pendiente.stats`.
- [ ] 9.2 Run full suite (all PR1 tests + new PR2 tests) — confirm zero regressions.
- [ ] 9.3 Update `skills/agenda-personal/SKILL.md`: document `historial`/`stats` invocations + the instruction "leé los conteos tal cual, no los recalculés".
- [ ] 9.4 Check `ops/cron-jobs.md §5.1` (7am briefing) for any payload-shape assumption that needs a note given PR1's changed `pendiente today` size/order (design risk #5) — add a one-line note if the existing text doesn't already cover it; no automated test catches this, manual verification only.
- [ ] 9.5 Copy updated `skills/agenda-personal/SKILL.md` into `$HERMES_DATA/skills/` after PR2 deploy; confirm `ops/skills-autocommit.sh` picks it up.

## Rules Applied

- TDD: RED (write failing test) -> GREEN (implement) pairs used throughout Phase 0-3 and Phase 7-8 test tasks per Strict TDD Mode.
- Phase 0 is gated: no Phase 1-3 work should land ahead of Phase 0's green migration test suite.
- Phase 4 (frozen-test regression check) is blocking before Phase 5/6.
- Phase 6 is entirely production-facing and sequential; nothing in it can run in parallel with itself.
- PR2 (Phase 7-9) depends on PR1 only for `pendientes_completado`'s existence; otherwise independently reviewable.
