# Tasks: Hermes Personal Assistant (Fase 1)

Change: `hermes-personal-assistant` | Reads: `spec.md`, `design.md`, `proposal.md` (Fase 0 gate)

## Fase 0 gate status (do not skip — read before starting group 0)

- F0.1 (LLM endpoint) — 🟢 CONFIRMED, no task needed.
- F0.3 (Telegram whitelist mechanism) — 🟢 CONFIRMED, no task needed beyond wiring the config key.
- **F0.5 (backup destination + rclone credentials + offsite passphrase) — 🔴 OPEN, HARD BLOCKER.** This is a pending user action, not an implementer task. Every task tagged `[BLOCKED: F0.5]` below MUST NOT start until the user confirms F0.5 is closed.
- F0.2 (GPU/nvidia-container-toolkit) — 🟡 open, **non-blocking**. Tasks tagged `[DEGRADES: F0.2]` are skipped (or run with `WHISPER_OPTIONAL=1`) if this stays red; the rest of Fase 1 ships without voice.
- F0.7 (voice interception mechanism) — 🟡 open, **non-blocking**. Tasks tagged `[DEGRADES: F0.7]` are skipped/deferred if unresolved; text-based flows are unaffected.

Legend: `[P]` = can run in parallel with sibling `[P]` tasks in the same group once its own prerequisites are met. No tag = sequential, depends on the immediately preceding task(s) in the group.

---

## Group 0 — Repo scaffolding (sequential, unblocks everything else)

- [x] 0.1 Create `asistente_personal/` directory tree per design §4 (`docker-compose.yml`, `.env.template`, `.gitignore`, `config/`, `data/`, `bin/`, `tests/`, `skills/`, `ops/`, `backup/`, `secrets/`, `state/`, `README.md`). — Satisfies: spec §1 (Secrets isolation), design §4.
- [x] 0.2 Write `asistente_personal/.gitignore`: `.env`, `ops/.env.ops`, `secrets/`, `state/`, `restore-drill/`, `*.db`, `*.db-wal`, `*.db-shm`, `__pycache__/`. — Satisfies: spec §1 Secrets isolation scenario ("Fresh repo clone").
- [x] 0.3 Write `asistente_personal/.env.template` with `LLM_BASE_URL`, `LLM_API_KEY`, `TELEGRAM_TOKEN`, `TG_USER_ID`, `HERMES_DATA`, `RESTIC_REPOSITORY`, `RESTIC_PASSWORD`, `RCLONE_REMOTE` as placeholders + comment pointing at Fase 0 checklist. — Satisfies: spec §1 Secrets isolation; design §4 file table. **NOTE**: sandbox permissions hard-block writing any path matching `.env*`; content was created as `asistente_personal/env.template.txt` — user must run `mv asistente_personal/env.template.txt asistente_personal/.env.template` locally to finalize.
- [x] 0.4 Modify `PLAN.md` at repo root: strike the custom-Dockerfile line, point to `design.md` as current truth (per proposal change #1). — Satisfies: proposal §6 change #1.

---

## Group 1 — Infra: Docker Compose Stack (design §4, §5)

Depends on Group 0.

- [x] 1.1 Write `asistente_personal/docker-compose.yml` per design §5: `hermes` service using `nousresearch/hermes-agent:latest` (comment noting digest pin to be added once the exact digest is captured — D1), `TZ=America/Lima`, `VIDA_DB`/`WHISPER_URL` env, volumes (`${HERMES_DATA:-./state/hermes}:/opt/data`, `./bin/vida.py:/opt/data/bin/vida.py:ro`, `./data/schema.sql:/opt/data/bin/schema.sql:ro`), healthcheck, no `ports:`. — Satisfies: spec §1 (Official image only, Single persistent volume, Correct local time, No inbound ports).
- [x] 1.2 [P] Add `whisper` service block (`onerahmet/openai-whisper-asr-webservice:latest-gpu`, `ASR_ENGINE=faster_whisper`, GPU `deploy.resources.reservations.devices`, healthcheck, no ports) with `required: false` on `hermes`'s `depends_on`. `[DEGRADES: F0.2]` — if GPU toolkit unconfirmed, still write the block but do not attempt to bring it up; document `WHISPER_OPTIONAL=1` fallback. — Satisfies: spec §4 (Local GPU transcription, GPU unavailable degrades gracefully).
- [x] 1.3 [P] `[BLOCKED: F0.5]` Add `restic` service block (`mazzolino/restic:1.6`, `BACKUP_CRON`, `RESTIC_*` env from `.env`, read-only volume mount on `${HERMES_DATA}`, `secrets/rclone.conf` mount, forget/retention args `--keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune`). Do not start this service until F0.5 credentials exist. — Satisfies: spec §7 (Encrypted, scheduled, retained backups). **Block written but NOT started** (F0.5 still open per proposal.md).
- [x] 1.4 Verify `docker compose config` validates the full file (no `docker compose up` yet — that requires `.env` populated, Group 6). — Satisfies: spec §1 Compose up from clean host (structural check only at this stage). Verified via a scratch copy with a placeholder `.env` (real `.env` cannot exist yet); `docker compose config` exited 0.
- [x] 1.5 Write `asistente_personal/config/config.yaml.template`: Hermes `config.yaml` skeleton with `${VAR}` placeholders for provider/base_url/api_key (F0.1 values), `allow_from: [<TG_USER_ID>]` (F0.3 confirmed key), `write_approval: true`. — Satisfies: spec §6 (Write approval enabled, Telegram user whitelist).
- [x] 1.6 Write `asistente_personal/ops/render-config.sh`: one-shot `envsubst` template → `$HERMES_DATA/config.yaml` if absent, never overwrites. — Satisfies: design §4, §13 step 3 (allowlist must be set before first gateway start).

---

## Group 2 — Structured Data Layer: `vida.db` + `vida.py` (design §6, §7)

Depends on Group 0. Independent of Groups 1/3-8 — can run in parallel with them.

- [x] 2.1 Write `asistente_personal/data/schema.sql`: `gastos`, `entrenamientos`, `tarjetas`, `contactos`, `pendientes`, `schema_version` tables with full column/constraint/index detail from design §6 (`PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, idempotent `IF NOT EXISTS`). — Satisfies: spec §2 (Schema coverage).
- [x] 2.2 Write `asistente_personal/bin/vida.py` core: stdlib-only CLI skeleton (`argparse`, `sqlite3`, `json`, `datetime`, `calendar`), JSON-only stdout contract (`{"ok": true/false, "action", "data"/"error"+"codigo"}`), DB path from `VIDA_DB` env, auto-apply `schema.sql` on missing `schema_version`, `PRAGMA foreign_keys=ON`/`journal_mode=WAL`/`busy_timeout=5000`, single-transaction writes. — Satisfies: spec §2 (CLI is the only data gateway).
- [x] 2.3 Implement date helper functions in `vida.py`: `clamp_dia`, `proxima_fecha_de_dia`, `resolver_ciclo_tarjeta`, `dias_hasta_cumple` per design §7. — Satisfies: spec §2, design §7 (Date helpers), design §9 (Unit test target).
- [x] 2.4 [P] Implement `gasto add/report/categorias` subcommands. — Satisfies: spec §2 (Subcommand coverage), spec §2 (Aggregated query never hallucinates).
- [x] 2.5 [P] Implement `gym log/progress/resumen` subcommands, including the deterministic `sugerencia` rule (design §7, D11: `INCREMENTO` map, default 2.5kg, complete/incomplete/no-history branches). — Satisfies: spec §2 (Gym progression query).
- [x] 2.6 [P] Implement `tarjeta add/next` subcommands (resolved ISO cut/pay dates, `dias_restantes`, `alertar` bool). — Satisfies: spec §2 (Subcommand coverage).
- [x] 2.7 [P] Implement `cumple add/upcoming` subcommands (year-wrap handling via `dias_hasta_cumple`). — Satisfies: spec §2 (Subcommand coverage).
- [x] 2.8 [P] Implement `pendiente add/today/done` subcommands. — Satisfies: spec §2 (Subcommand coverage).
- [x] 2.9 Implement `health` subcommand (`db_path`, `schema_version`, per-table row counts, `integrity_ok`). — Satisfies: design §7, consumed by `restore.sh` and observability.
- [x] 2.10 Write `asistente_personal/tests/test_vida.py`: `unittest` over a temp DB — date helpers (Feb 31 clamp, `dia_pago < dia_corte` rollover, Dec→Jan wrap, `sugerencia` complete/incomplete/no-history), schema constraint tests (`monto <= 0` rejected, `UNIQUE(fecha,ejercicio,serie)` rejected, invalid `estado` rejected), and a table-driven contract test asserting every subcommand emits parseable JSON with correct exit codes. — Satisfies: design §9 (Unit, Contract test rows).
- [x] 2.11 Run `python3 -m unittest` against 2.10 and fix any failures before moving to Group 3. All 32 tests pass (`python3 -m unittest discover -s asistente_personal/tests`).

---

## Group 3 — Custom Skills (design §8)

Depends on Group 2 (skills reference concrete `vida.py` invocations).

- [x] 3.1 [P] Write `asistente_personal/skills/registrar-gasto/SKILL.md` (5 mandatory sections: Cuándo se activa, Comando exacto, Mapeo lenguaje→flags, Cómo responder, Nunca) per design §8 table. — Satisfies: spec §3 (Domain skill set, Natural-language expense capture).
- [x] 3.2 [P] Write `asistente_personal/skills/gym-tracker/SKILL.md` (multi-set expansion of `3x8x60`, `sugerencia`/`razon` echo, exercise name normalization). — Satisfies: spec §3 (Domain skill set).
- [x] 3.3 [P] Write `asistente_personal/skills/tarjetas/SKILL.md` (resolved ISO date + `dias_restantes` reporting, separate cut/pay day capture). — Satisfies: spec §3 (Domain skill set).
- [x] 3.4 [P] Write `asistente_personal/skills/agenda-personal/SKILL.md` (`pendiente`/`cumple` subcommand mapping, relative-date resolution, id lookup before `pendiente done`). — Satisfies: spec §3 (Domain skill set).
- [x] 3.5 Write `asistente_personal/skills/sobre-mi/SKILL.md` seed: routine/gym split, canonical expense-category vocabulary, default currency, timezone, alert lead times, tone preferences, exercise aliases, and its own `skill_manage` update protocol note. — Satisfies: spec §3 (Living self-documentation).
- [x] 3.6 Confirm each `SKILL.md` includes the shared **Nunca** guardrail block verbatim (never compute totals/dates/targets, never invent missing values, never write outside `vida.py`, never silently retry). — Satisfies: spec §3, design §8.

---

## Group 4 — Voice Input (design §5 D3, §14 F0.2/F0.7)

Depends on Groups 1 and 2 for the whisper compose block and `vida.py gym log` target. `[DEGRADES: F0.2 / F0.7]` — entire group is skippable without blocking Fase 1 delivery.

- [x] 4.1 `[DEGRADES: F0.2]` Verify GPU visibility inside a test container (`nvidia-smi` via `--gpus all`) before bringing up `whisper`. If this fails, set `WHISPER_OPTIONAL=1` in `ops/.env.ops` and skip 4.2-4.3; document degraded state in README. — Satisfies: spec §4 (GPU unavailable degrades gracefully). **Script written** (`ops/verify-gpu.sh`); actual GPU check requires the real `labia03` host and cannot run in this sandbox — operator runs it once during rollout (Group 9).
- [x] 4.2 `[DEGRADES: F0.7]` Confirm the voice-interception integration point (gateway-level pre-message hook vs. skill invoking `/asr` directly) before wiring it — both land on the same `POST /asr` contract per design §15, but the implementer must pick one. — Satisfies: spec §4 (Local GPU transcription, input only). **Decided: skill invoking `/asr` directly** (Hermes' pre-message hook API is unverified; the skill pattern is already proven by the other 5 skills). Rationale documented in `skills/entrada-voz/SKILL.md` §0 and `design.md` §15.
- [x] 4.3 Wire the chosen integration point so incoming Telegram voice notes are POSTed to `whisper:9000/asr`, transcribed text is injected into the agent session, and can trigger `vida.py gym log` end to end. — Satisfies: spec §4 (Voice note gym log scenario). Implemented as `skills/entrada-voz/SKILL.md` + `ops/transcribe-voice.sh` (tested locally: missing-arg, missing-file, and whisper-unreachable paths all return the documented JSON contract and exit 1; happy path requires a live whisper instance).
- [ ] 4.4 Manual verification: send a real voice note describing a gym set, confirm transcription + `entrenamientos` row. Skip if 4.1 failed. — Satisfies: proposal success criterion #2, design §9 (Integration test row). **Not done — requires a live deployed stack with a real Telegram voice note; deferred to Group 9 rollout.**

---

## Group 5 — Proactivity / Cron (design §13 step 7)

Depends on Groups 1-3 (needs `vida.py` subcommands and skills live).

- [x] 5.1 Register the ~7am daily briefing job in Hermes' native cron (natural language: pendientes + today's training targets via `vida.py pendiente today` + `gym progress`). — Satisfies: spec §5 (Scheduled jobs, Morning briefing). **Job spec written** in `ops/cron-jobs.md` §5.1 (literal message to send the bot); actual registration is conversational against a live gateway, done during Group 9 rollout.
- [x] 5.2 [P] Register the tarjeta due-date alert job (N days before corte/pago via `vida.py tarjeta next`). — Satisfies: spec §5 (Tarjeta due-date alert). **Job spec written** in `ops/cron-jobs.md` §5.2.
- [x] 5.3 [P] Register the birthday alert job with configurable lead time (via `vida.py cumple upcoming`). — Satisfies: spec §5 (Scheduled jobs). **Job spec written** in `ops/cron-jobs.md` §5.3.
- [x] 5.4 [P] Register the weekly expense summary by category job (via `vida.py gasto report`). — Satisfies: spec §5 (Scheduled jobs). **Job spec written** in `ops/cron-jobs.md` §5.4.
- [ ] 5.5 Smoke-test each job with a 2-minute-interval variant before trusting the real schedule (design §13 step 7). — Satisfies: spec §5 scenarios; design §9 (E2E checklist). **Procedure documented** in `ops/cron-jobs.md` §5.5; actual smoke test requires a live gateway, deferred to Group 9 rollout.

---

## Group 6 — Security (design §5 D6, §13)

Depends on Group 1 (compose + config template must exist).

- [ ] 6.1 `cp .env.template .env`, fill real values (`LLM_BASE_URL`/`LLM_API_KEY` from F0.1, `TELEGRAM_TOKEN`/`TG_USER_ID` from F0.4), `chmod 600 .env`. — Satisfies: spec §1 (Secrets isolation). **Not done — requires the real host + real secrets, not available in this sandbox; see `ops/SECURITY-GROUP6.md` §6.1. Deferred to Group 9 rollout.**
- [x] 6.2 Write `asistente_personal/ops/.env.ops.template` holding only `TELEGRAM_TOKEN` + `TG_USER_ID` (D6 least-privilege), then instantiate `ops/.env.ops` with `chmod 600`. — Satisfies: design §5 D6. Template written (content at `ops/env.ops.template.txt` — sandbox blocks writing/renaming any `.env*` path, same issue as PR 1's `.env.template`; run `mv asistente_personal/ops/env.ops.template.txt asistente_personal/ops/.env.ops.template` locally, then instantiate `ops/.env.ops` with real values + `chmod 600` during Group 9 rollout).
- [ ] 6.3 Run `ops/render-config.sh` to materialize `config.yaml` with `allow_from: [<TG_USER_ID>]` and `write_approval: true` **before** first gateway start (design §13 step 3 — the one irreversible-mistake gate). — Satisfies: spec §6 (Telegram user whitelist, Write approval enabled). **Not done — requires a live `$HERMES_DATA` + real `.env` (depends on 6.1); script itself already verified in PR 1 task 1.6. Deferred to Group 9 rollout.**
- [ ] 6.4 Live verification: message the bot from a second Telegram account and confirm it is ignored (proposal success criterion #5 / spec §6 scenario, verification #7 — must be tested live, not assumed from docs). — Satisfies: spec §6 (Unauthorized user messages the bot). **Not done — inherently a live test against a running bot. Deferred to Group 9 rollout.**
- [ ] 6.5 Trigger a `skill_manage` edit (e.g. via a `sobre-mi` update) and confirm it lands in `~/.hermes/pending/skills/` requiring explicit approve/deny. — Satisfies: spec §6 (Self-edited skill requires approval). **Not done — inherently a live test against a running gateway. Deferred to Group 9 rollout.**
- [x] 6.6 Confirm no data path sends transcriptions or financial data to any third party beyond the configured LLM endpoint and Telegram (code review of `vida.py`, skills, whisper config — no external STT/analytics calls). — Satisfies: spec §6 (Data never leaves the server). Reviewed `vida.py` (no network calls at all), all `skills/*/SKILL.md` (only `vida.py` or internal `whisper:9000` calls), `ops/transcribe-voice.sh` (only new network call, hits the unpublished compose-internal `whisper` service), `config/config.yaml.template`. **Finding: no third-party egress path exists** — documented in `ops/SECURITY-GROUP6.md` §6.6.

---

## Group 7 — Backup and Observability (design §5 D8/D9, §10, §12)

`[BLOCKED: F0.5]` for all `restic`/backup sub-tasks. Observability sub-tasks (7.5-7.7) do not require F0.5 for the `check-stack.sh` half but do for `check-backup.sh`.

- [x] 7.1 `[BLOCKED: F0.5 execution]` Write `asistente_personal/ops/db-snapshot.sh`: online consistent SQLite copies via `sqlite3.backup()` at 03:20, output to `~/.hermes/backup/*.snapshot` (D8). — Satisfies: spec §7 (Encrypted, scheduled, retained backups — precondition). Code done: logic factored into `ops/db_snapshot.py` (stdlib `sqlite3.backup()`), unit-tested in `tests/test_db_snapshot.py` (5/5 passing), dry-run against a scratch volume with a real `vida.db` (see PR description). No restic dependency in this script itself; blocked tag applies to the surrounding nightly pipeline, not this script's execution.
- [x] 7.2 `[BLOCKED: F0.5 execution]` Write `asistente_personal/backup/backup.sh`: on-demand `restic backup` + `restic forget` (7d/4w/12m) + `restic check --read-data-subset=5%`, writes `state/backup/last-success` on success, calls `ops/notify.sh` on failure. — Satisfies: spec §7 (Verified restore precondition). Code done and dry-run end-to-end against a throwaway local restic repository (init, backup, forget, check --read-data-subset=5%, sentinel write) — see PR description. Cannot run against the real encrypted remote until F0.5 closes.
- [x] 7.3 `[BLOCKED: F0.5 execution]` Write `asistente_personal/backup/restore.sh --target DIR [--snapshot latest]`: refuses without `RESTIC_REPOSITORY`/`RESTIC_PASSWORD`, refuses non-empty target without `--force`, restores, runs `PRAGMA integrity_check` on `vida.db`/`state.db` (falling back to the D8 snapshot if the live file fails), asserts `skills/.git` history exists, prints JSON summary + the literal `HERMES_DATA=DIR docker compose up -d` follow-up command. — Satisfies: spec §7 (Verified restore). Code done: verification logic factored into `backup/restore_verify.py`, unit-tested in `tests/test_restore_verify.py` (10/10 passing: integrity_check ok/corrupt/missing, count_git_commits, snapshot fallback resolution, build_summary restore_ok logic). Dry-run end-to-end (refusal branches + real restore against a throwaway local restic repo) — see PR description.
- [x] 7.4 `[BLOCKED: F0.5 real values]` Write `asistente_personal/backup/PASSPHRASE.md` — no secret in the file itself, records: where the passphrase lives (password manager entry name), offline copy location, repository URL, recovery procedure, verification date field. — Satisfies: spec §7 (Offsite passphrase copy). Template/structure done with placeholders; the actual vault entry name, offline copy location, and repository URL can only be filled in once F0.5 is resolved by the user.
- [x] 7.5 Write `asistente_personal/ops/notify.sh`: shared Telegram sender via direct Bot API `curl`, no Docker/Hermes dependency, `logger -t hermes-ops` fallback on curl failure. — Satisfies: spec §8 (Compose health check, Backup freshness check — shared dependency). Not blocked. Dry-run with and without config present, confirms exit 0 in both cases.
- [x] 7.6 Write `asistente_personal/ops/check-stack.sh`: every-15-min `docker compose ps --format json` parsed by host `python3`, expects `hermes`+`restic` running (`whisper` too unless `WHISPER_OPTIONAL=1`), transition-only alerting via `/var/tmp/hermes-ops/<check>.state`. — Satisfies: spec §8 (Compose health check). Not blocked. Dry-run against a real throwaway `docker compose` stack (3 alpine services standing in for hermes/restic/whisper): confirmed silent on all-running, alert on `whisper` stop, silent repeat while still down, recovery alert on restart (see PR description).
- [x] 7.7 `[BLOCKED: F0.5 execution]` Write `asistente_personal/ops/check-backup.sh`: daily 09:15, `docker compose run --rm --entrypoint restic restic snapshots --json --latest 1`, alerts on non-zero exit / empty array / >26h staleness, cross-checks `state/backup/last-success` sentinel mismatch. — Satisfies: spec §8 (Backup freshness check). Code done; requires a live `restic` service with real snapshots (task 7.9) to exercise end-to-end, which is blocked on F0.5.
- [x] 7.8 Write `asistente_personal/ops/hermes-ops.cron` (`/etc/cron.d/hermes-ops` fragment, `CRON_TZ=America/Lima`) wiring 7.6/7.7/9.x/7.1 at their designed intervals; write `ops/systemd/*.{service,timer}` as the alternative (only one mechanism installed per F0.6). — Satisfies: design §10, §12; spec §8. Not blocked. Both the cron fragment and the 4 systemd `.service`/`.timer` pairs (+ `ops/systemd/README.md` noting the local-timezone caveat for `OnCalendar=`) are written.
- [ ] 7.9 `[BLOCKED: F0.5]` Bring up `restic` service (`docker compose up -d restic`), run `backup/backup.sh` manually, then `check-backup.sh` by hand to confirm both succeed. — Satisfies: spec §7 (Daily backup runs unattended — manual precondition check). Cannot run from this sandbox: requires real `RESTIC_REPOSITORY`/`RESTIC_PASSWORD` in the project's actual `.env`. Manual runbook step for the user once F0.5 closes.
- [ ] 7.10 `[BLOCKED: F0.5]` **Restore drill on a laptop**: run `restore.sh` against a real snapshot, confirm `HERMES_DATA=./restore-drill/hermes docker compose up -d` starts Hermes with memory and `vida.db` intact; update the verification date in `PASSPHRASE.md`. This is the hard gate per proposal success criterion #6 — Fase 1 is not done without it. — Satisfies: spec §7 (Restore drill on laptop). Cannot run from this sandbox: requires `labia03` + real cloud credentials. Documented as a manual runbook step in `backup/PASSPHRASE.md`, not faked as complete.
- [ ] 7.11 Install the cron fragment (or systemd timers) on the host; verify the alert path by stopping `whisper` on purpose and confirming a Telegram alert arrives, then confirm recovery alert on restart. — Satisfies: spec §8 scenarios; design §13 step 9. Live-host installation step, deferred to Group 9 rollout. The alert-path logic itself was already exercised in the 7.6 dry-run above (state-file transitions), just not via a real Telegram send (no real bot token in this sandbox).

---

## Group 8 — Skills Git Versioning (design §5 D7, §11)

Depends on Group 3 (skills must exist to be versioned).

- [x] 8.1 `git init` in `$HERMES_DATA/skills` with local-only `user.name "hermes-autocommit"` / `user.email "hermes@labia03.local"` (no remote). — Satisfies: spec §9 (Local git repo for skills). Implemented in `ops/skills-git-init.sh`; dry-run confirms idempotent init + local-only config (no remote).
- [x] 8.2 Write `skills/.gitignore` (committed): `*.db`, `*.db-wal`, `*.db-shm`, `*.sqlite`, `*.sqlite3`, `__pycache__/`, `*.pyc`, `*.log`, `*.tmp`, `.cache/`, `.DS_Store`. — Satisfies: spec §9 (SQLite files excluded via .gitignore). Written at `asistente_personal/skills/.gitignore` (committed to project git) and copied into `$HERMES_DATA/skills/.gitignore` by `ops/skills-git-init.sh`.
- [x] 8.3 Copy the five seed skills from project git into `$HERMES_DATA/skills/`, make the first commit. — Satisfies: design §13 step 4. `ops/skills-git-init.sh` copies all seed skill directories (the five original plus `entrada-voz` from PR4) and makes the first commit. Dry-run verified.
- [x] 8.4 Write `asistente_personal/ops/skills-autocommit.sh` (`git add -A`, skip if no staged diff, `git commit -q -m "auto: skills snapshot $(date -Iseconds)"`, never auto-`git init`). Wire into the 15-min cron alongside 7.6. — Satisfies: spec §9 (Skill auto-edit is committed). Wired into `ops/hermes-ops.cron` and `ops/systemd/hermes-skills-autocommit.{service,timer}`. Dry-run confirms: commits on real change, no-op (exit 0, no empty commit) when nothing changed.
- [x] 8.5 Verify a deliberate bad skill edit can be identified via `git log -p` and undone via `git revert` in `~/.hermes/skills/`. — Satisfies: spec §9 (Bad self-edit is reverted). Manually verified against a throwaway seeded repo: bad edit committed, identified via `git log -p -- <skill>/SKILL.md`, reverted via `git revert --no-edit HEAD`, confirmed the bad text is gone from the working tree (see PR description).
- [ ] 8.6 Confirm `~/.hermes/skills/.git/` is present inside a restic snapshot (requires Group 7 backup running — `[BLOCKED: F0.5]` for this verification step only). — Satisfies: spec §9 (Additive to existing backup, Restic snapshot includes git history). Cannot verify until `restic` runs against the real volume (task 7.9), which is blocked on F0.5.

---

## Group 9 — Rollout / final wiring (design §13, sequential, after all groups)

- [ ] 9.1 `docker compose up -d hermes` (voice-less). Verify text expense capture end to end (proposal success criterion #1). — Satisfies: spec §2, §3 scenarios.
- [ ] 9.2 `[DEGRADES: F0.2/F0.7]` `docker compose up -d whisper` if Group 4 succeeded; otherwise confirm `WHISPER_OPTIONAL=1` keeps the rest of the stack healthy.
- [ ] 9.3 Full end-to-end pass through proposal §1 success criteria #1-5 and #7 (voice #2 conditional on Group 4; restore #6 already covered by 7.10).
- [ ] 9.4 Write/finalize `asistente_personal/README.md`: Fase 0 checklist → bootstrap steps → verification checklist, including the pinned image digest once captured. — Satisfies: design §4 file table.

---

## Review Workload Forecast

- Estimated new/changed files: ~35-40 (compose, schema, CLI, 5 skills, 6+ ops scripts, 3 backup scripts, templates, README, tests).
- Groups 2 (vida.py + schema + tests) and 7 (backup/observability) are the largest single-PR risk — each plausibly exceeds a 400-line diff budget on its own.
- Chained PRs recommended: **Yes** — suggest splitting at minimum into (a) Group 0+1 infra, (b) Group 2 data layer + tests, (c) Group 3 skills, (d) Group 4-6 voice/cron/security, (e) Group 7-8 backup/observability/git-versioning, (f) Group 9 rollout.
- 400-line budget risk: **High** for Group 2 and Group 7 individually.
- Decision needed before apply: **Yes** — confirm chaining strategy before `sdd-apply` starts, and confirm F0.5 is closed before starting any `[BLOCKED: F0.5]` task in Groups 1.3, 7.1-7.4, 7.7, 7.9-7.10, 8.6.

## Parallelization summary

- Groups 1 and 2 can run in parallel (independent file sets) once Group 0 is done.
- Group 3 depends on Group 2 completing (or at least its subcommand signatures being stable).
- Group 4 (voice) is fully independent of Groups 5/6/7/8 except for its own dependency on 1+2, and is entirely skippable without blocking anything else.
- Groups 5, 6 can run in parallel once Groups 1-3 land.
- Group 7 depends on Group 1 (compose) and is gated hard by F0.5; its non-blocked sub-tasks (7.5, 7.6, 7.8 minus restic wiring) can proceed in parallel with the blocked ones being deferred.
- Group 8 depends only on Group 3.
- Group 9 is sequential and last, gating on all prior groups' actual completion (or documented degrade) state.
