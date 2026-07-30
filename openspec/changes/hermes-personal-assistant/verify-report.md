# Verification Report: hermes-personal-assistant

**Branch verified**: `hermes-personal-assistant/pr-6-rollout` (cumulative state of all 6 stacked PRs)
**Mode**: openspec (file-based artifacts; primary report written to `verify-report.md`)
**Verdict**: **PASS WITH WARNINGS**

---

## 1. Completeness (tasks.md vs actual code)

Cross-checked every `[x]` task in `tasks.md` against real files on disk, not the checkbox text alone.

| Group | Claimed | Verified |
|---|---|---|
| 0 — Scaffolding | done | Confirmed: full directory tree, `.gitignore`, `.env.template` (empty placeholders), `PLAN.md` note. |
| 1 — Infra/compose | done | `docker-compose.yml` matches design §5 almost verbatim (service names, volumes, healthchecks, no `ports:`). `docker compose config` **validates cleanly (exit 0)** against a scratch copy + dummy `.env` — re-verified independently, not just trusted from PR1's claim. |
| 2 — Data layer | done, "32/32 then 47/47" | Re-ran `python3 -m unittest discover -s asistente_personal/tests` myself: **47/47 passing**, 0 failures, 0.7s. Matches PR5's claimed count exactly. |
| 3 — Skills | done | All 5 domain `SKILL.md` files read in full; every `vida.py` invocation shown (flags, dest names like `--dia-corte`→`dia_corte`) matches the actual `argparse` wiring in `bin/vida.py` line-for-line. No drift found. |
| 4 — Voice | 4.1-4.3 done, 4.4 deferred | Code (`entrada-voz/SKILL.md`, `transcribe-voice.sh`, `verify-gpu.sh`) present and internally consistent (JSON contract shared with `vida.py`'s `{ok,action,data/error,codigo}` shape). 4.4 correctly left unchecked — it requires a live voice note against real GPU/whisper, honestly deferred to rollout, not silently marked done. |
| 5 — Cron | 5.1-5.4 done, 5.5 deferred | `ops/cron-jobs.md` exists with the literal natural-language messages. 5.5 (smoke test) correctly unchecked — needs a live gateway. |
| 6 — Security | 6.2, 6.6 done; 6.1/6.3/6.4/6.5 deferred | `ops/env.ops.template.txt` (sandbox-blocked rename, documented identically in PR1's `.env.template` precedent) present with only `TELEGRAM_TOKEN`/`TG_USER_ID`/`WHISPER_OPTIONAL` — least-privilege, matches D6. 6.1/6.3/6.4/6.5 correctly unchecked (real secrets/live bot required). |
| 7 — Backup/Observability | 7.1-7.8 done; 7.9-7.11 blocked on F0.5 | All scripts present, shellcheck-clean (only info-level SC1091 on intentional `. "$file"` sourcing). `db_snapshot.py`/`restore_verify.py` unit tests pass (part of the 47). 7.9-7.11 correctly unchecked with F0.5 cited as the reason, not silently skipped. |
| 8 — Skills git versioning | 8.1-8.5 done, 8.6 blocked | `ops/skills-git-init.sh` + `skills-autocommit.sh` present, idempotent-by-design (`[ -d .git ] || exit 0`, never auto-inits from cron per D7). 8.6 correctly unchecked (needs a real restic snapshot). |
| 9 — Rollout | 9.4 done, 9.1-9.3 deferred | `README.md` (304 lines) is a full, accurate operator runbook matching design §13's bootstrap order, including the "allowlist + write_approval before first boot" irreversibility warning. 9.1-9.3 correctly unchecked. |

**No task found marked `[x]` that isn't actually backed by code.** The pattern of "code done, live execution deferred to Group 9 rollout / requires labia03" is applied consistently and honestly across all 6 PRs — this matches the explicit instruction that this is expected, not a gap.

---

## 2. Test suite — actually re-executed

```
python3 -m unittest discover -s asistente_personal/tests
Ran 47 tests in 0.725s
OK
```

Re-run independently (not trusted from state.yaml's claim). Matches PR5's reported 47/47 exactly (32 from `test_vida.py` + 5 from `test_db_snapshot.py` + 10 from `test_restore_verify.py`).

---

## 3. `docker compose config` validation

`docker-compose.yml` requires `env_file: [.env]` on two services, so `--env-file` alone is insufficient — a scratch copy of the whole `asistente_personal/` tree was made in `/tmp`, seeded with a copy of the tracked `.env.template` (renamed to `.env`, all placeholder/empty values), and validated there (not in the real repo, so the real `.gitignore`d `.env` was never created in-tree). Result:

```
docker compose -f docker-compose.yml config
EXIT: 0
```

Full rendered config confirms: 3 services (`hermes`, `whisper`, `restic`), correct volume mounts, `TZ=America/Lima` on all three, no `ports:` anywhere, healthchecks present, `whisper`'s GPU `deploy.resources.reservations.devices` block intact.

---

## 4. Cross-PR consistency (spot-checked, not assumed)

- **PR3 skills vs PR2's `vida.py` CLI contract**: verified directly — every flag in `registrar-gasto`, `gym-tracker`, `tarjetas`, `agenda-personal`'s `SKILL.md` (`--monto`, `--categoria`, `--dia-corte`/`--dia-pago` with `dest=dia_corte/dia_pago`, `--ejercicio`, `--peso`, `--reps`, `--serie`, `--rpe`, `--alerta-dias`) matches `build_parser()` in `bin/vida.py` exactly, including `dest=` renames for hyphenated flags. No drift.
- **PR5 backup/ops scripts vs PR1/PR4 env vars**: `check-stack.sh`/`check-backup.sh`/`notify.sh` all source `ops/.env.ops` and read `TELEGRAM_TOKEN`, `TG_USER_ID`, `WHISPER_OPTIONAL` — exactly the three vars defined in PR4's `ops/env.ops.template.txt`. `db-snapshot.sh` reads `HERMES_DATA/data/vida.db` and `HERMES_DATA/state.db`, consistent with compose's `${HERMES_DATA:-./state/hermes}:/opt/data` mount (D9) and `VIDA_DB=/opt/data/data/vida.db`.
- **PR4 entrada-voz skill vs PR1 whisper service**: `ops/transcribe-voice.sh` posts to `${WHISPER_URL:-http://whisper:9000}/asr`, matching the compose service name `whisper` and the `WHISPER_URL: http://whisper:9000` env var set on the `hermes` service.
- **Schema (PR2) vs design.md §6**: table-by-table comparison of `data/schema.sql` against the design's column tables — exact match on columns, constraints (`CHECK`, `UNIQUE(fecha,ejercicio,serie)`), and indexes.

No inconsistencies found between PRs' assumptions about each other's contracts.

---

## 5. Secret hygiene

Grepped tracked files (current tree) and full git log (`git log --all -p -- asistente_personal`) for API-key-shaped strings, Telegram bot token patterns (`\d{6,}:[A-Za-z0-9_-]{20,}`), AWS keys, PEM private key headers, and generic long-secret assignment patterns. **Zero matches, in the working tree and in history.**

- `.env.template`: all secret fields (`LLM_API_KEY`, `TELEGRAM_TOKEN`, `TG_USER_ID`, `RESTIC_REPOSITORY`, `RESTIC_PASSWORD`, `RCLONE_REMOTE`) are empty placeholders.
- `ops/env.ops.template.txt`: same — empty `TELEGRAM_TOKEN`/`TG_USER_ID`.
- `backup/PASSPHRASE.md`: explicitly documents it must never contain the actual passphrase — confirmed it doesn't; all fields are `_(fill in during F0.5...)_` placeholders.
- `.gitignore` correctly excludes `.env`, `ops/.env.ops`, `secrets/`, `state/`, `restore-drill/`, `*.db*`, `__pycache__/`. Verified working tree is clean (`git status --short` empty) and no `__pycache__` directories are tracked despite existing on disk.

---

## 6. Deferred/blocked tasks — honestly documented

Confirmed F0.5-blocked and labia03-only tasks are consistently left as `[ ]` in `tasks.md` (never falsely checked), each annotated with the specific blocking reason (F0.5 open, requires real GPU, requires live Telegram bot, requires labia03 host). `state.yaml`'s `apply_progress` block explicitly states `apply: code_complete_pending_execution` and spells out that Fase 1 is not live yet. `README.md` opens with "**Nothing in this document has been executed.**" This is the correct, non-misleading way to represent a sandboxed SDD implementation phase — no CRITICAL finding here.

---

## Issues

### CRITICAL
None found.

### WARNING
1. **D1 deviation (digest pin) — expected but worth flagging for the archive record.** `design.md` D1 calls for pinning the Hermes image "by tag **and digest**"; `docker-compose.yml` currently uses `nousresearch/hermes-agent:latest` with a comment noting the digest will be added once captured live. This is unavoidable without a live pull (no digest exists yet) and is honestly flagged in the compose file and README's Rollback section — but it means the "Official Hermes image only" / reproducibility guarantee is not yet fully closed until an operator captures and pins the digest during the first real `docker compose up -d hermes` on `labia03`. Track this as an open rollout action, not a code defect.
2. **`calcular_sugerencia`'s "complete session" rule is a documented interpretation, not a literal implementation of design §7.** Design's `sugerencia` rule says "if all sets of the last session hit >= their target reps," but no target-reps column exists in the schema. PR2 substituted "no set's reps fall below the first set's (serie 1) rep count" and documented this explicitly in the docstring and in `state.yaml`'s `pr_2_known_deviation`. This is a reasonable, tested (4 dedicated unit tests) interpretation, but it is a design deviation that should be explicitly re-confirmed against real user expectations during Fase 1 use, since "session complete" now means something narrower than what design.md's prose literally describes.
3. **`ops/.env.ops.template` does not exist under that exact filename** — it exists as `ops/env.ops.template.txt` due to a sandbox permission guard blocking any `.env*`-glob write, exactly mirroring PR1's `.env.template` workaround. `README.md` §2 documents the required `mv`/rename step explicitly, so this will not silently break the operator — but it's a second occurrence of the same environmental limitation and should be resolved (e.g. by renaming during PR review/merge, not left to the live operator) if a lower-friction path exists before archive.

### SUGGESTION
1. Consider adding a `.dockerignore`/pre-commit hook (or a CI check) that fails the build if any `*.env*`-shaped file other than the two committed templates (`*.template`) appears in the tree — this would catch a future accidental real `.env` commit automatically rather than relying solely on `.gitignore` discipline.
2. `backup/restore.sh` and `check-backup.sh` both duplicate small inline Python snippets for parsing `restic snapshots --json` output (extracting `time`/`short_id`). Given `ops/db_snapshot.py` and `backup/restore_verify.py` already exist as testable Python modules, factoring these tiny parsers into a shared, unit-tested helper (as was already done for the WAL-snapshot and restore-verification logic) would close the last untested surface in the backup/observability path before the live restore drill.
3. `README.md`'s final verification checklist (§10) is excellent operator-facing documentation — consider mirroring its 7-point structure directly into `tasks.md` Group 9 as explicit checkbox items (currently 9.3 bundles all 7 into prose) so `sdd-archive` can point at exact per-criterion completion state rather than a single task.

---

## Final Verdict: **PASS WITH WARNINGS**

Code matches spec.md and design.md requirements to the extent testable without labia03/real secrets/a live bot. Test suite re-executed and passes (47/47). `docker compose config` re-validated independently (exit 0). No secrets found in tracked files or full git history. Cross-PR contracts (vida.py CLI ↔ skills, env vars ↔ ops scripts, schema ↔ design) verified consistent. All F0.5/labia03-only deferrals are honestly represented as incomplete, not silently marked done. The 3 WARNINGs above are rollout/documentation-quality items, not implementation defects, and do not block proceeding to `sdd-archive` — but the digest-pin and `.env.ops.template` filename items should be captured as explicit open follow-ups in the archive record so they aren't lost once this change closes.
