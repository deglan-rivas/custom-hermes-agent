# Spec: Hermes Personal Assistant (Fase 1)

Change: `hermes-personal-assistant` | Type: new capabilities (no prior `openspec/specs/` exists — all sections below are FULL specs, not deltas).

## 1. Infra: Docker Compose Stack

### Requirement: Official Hermes image only
The system MUST run the `hermes` service from the official `nousresearch/hermes-agent` Docker Hub image. The system MUST NOT build a custom Dockerfile for Hermes.

#### Scenario: Compose up from clean host
- GIVEN a host with Docker and Docker Compose v2 installed
- WHEN `docker compose up -d` runs the `hermes` service
- THEN the container starts from `nousresearch/hermes-agent` without a local build step

### Requirement: Single persistent volume
The system MUST persist all Hermes state (memory, skills, sessions, `vida.db`) in exactly one named volume mounted at `/opt/data`, backed by `~/.hermes` on host.

#### Scenario: State survives container recreation
- GIVEN the `hermes` container is destroyed and recreated
- WHEN the same volume is reattached
- THEN memory, skills, and `vida.db` content are unchanged

### Requirement: Correct local time for cron
The `hermes` service MUST set `TZ=America/Lima` as an environment variable.

#### Scenario: Cron job fires at wall-clock 7am Lima
- GIVEN the container clock reflects `TZ=America/Lima`
- WHEN a cron job is scheduled for "7am"
- THEN it fires at 07:00 Lima time, not UTC

### Requirement: No inbound ports
The system MUST NOT expose inbound ports on `labia03`. Telegram communication MUST use outbound long-polling. Admin access MUST use Tailscale SSH.

#### Scenario: Port scan from outside Tailscale
- GIVEN an external network scan of `labia03`
- WHEN scanning for open ports related to Hermes
- THEN no inbound port is reachable

### Requirement: Secrets isolation
Secrets (`LLM_BASE_URL`, `LLM_API_KEY`, `TELEGRAM_TOKEN`, `TG_USER_ID`, `RESTIC_*`) MUST live only in `.env`, which MUST be excluded from git via `.gitignore` from the first commit.

#### Scenario: Fresh repo clone
- GIVEN a fresh clone of the project repo
- WHEN inspecting tracked files
- THEN `.env` is absent and only `.env.template` (no real values) is tracked

## 2. Structured Data Layer (`vida.db` + `vida.py`)

### Requirement: Schema coverage
`data/schema.sql` MUST define tables `gastos`, `entrenamientos`, `tarjetas`, `contactos`, `pendientes`.

#### Scenario: Fresh database init
- GIVEN an empty `vida.db`
- WHEN `schema.sql` is applied
- THEN all five tables exist with their expected columns

### Requirement: CLI is the only data gateway
`bin/vida.py` MUST be the sole read/write interface to `vida.db`, implemented in Python stdlib without an ORM, and MUST emit JSON on stdout for every subcommand.

#### Scenario: Agent logs an expense
- GIVEN the agent invokes `vida.py gasto add --monto 45 --categoria almuerzo`
- WHEN the command completes
- THEN a new row exists in `gastos` and stdout is valid JSON with the inserted record

#### Scenario: Aggregated query never hallucinates
- GIVEN multiple `gastos` rows across categories
- WHEN `vida.py gasto report --mes 2026-07` runs
- THEN the JSON output reflects `SUM(monto) GROUP BY categoria` computed by SQLite, not agent-estimated values

### Requirement: Subcommand coverage
`vida.py` MUST support: `gasto add/report`, `gym log/progress`, `tarjeta add/next`, `cumple add/upcoming`, `pendiente add/today`.

#### Scenario: Gym progression query
- GIVEN prior `entrenamientos` rows for "press banca"
- WHEN `vida.py gym progress --ejercicio "press banca"` runs
- THEN JSON output reflects the real weight/rep progression from stored rows

## 3. Custom Skills (`~/.hermes/skills/`)

### Requirement: Domain skill set
The system MUST include skills `registrar-gasto`, `gym-tracker`, `tarjetas`, `agenda-personal`, `sobre-mi`, each with a `SKILL.md` instructing the agent when/how to call `vida.py`.

#### Scenario: Natural-language expense capture
- GIVEN the user sends "gasté 45 soles en almuerzo" via Telegram
- WHEN the agent applies `registrar-gasto`
- THEN it calls the correct `vida.py gasto add` invocation with parsed amount and category

### Requirement: Living self-documentation
The `sobre-mi` skill MUST be editable by the agent via `skill_manage` as it learns new facts about the user.

#### Scenario: Agent updates user profile
- GIVEN the agent learns a new recurring preference from conversation
- WHEN it calls `skill_manage` to edit `sobre-mi/SKILL.md`
- THEN the edit is staged for approval per the write-approval requirement (Section 5)

## 4. Voice Input

### Requirement: Local GPU transcription, input only
The system MUST run a `whisper` sidecar service using `faster-whisper` on GPU to transcribe incoming Telegram voice notes into text fed to the agent. The system MUST NOT provide voice output (TTS).

#### Scenario: Voice note gym log
- GIVEN the user sends a voice note describing a gym set
- WHEN the `whisper` service transcribes it
- THEN the resulting text is injected into the agent session and logged via `vida.py gym log`

#### Scenario: GPU unavailable degrades gracefully
- GIVEN `nvidia-container-toolkit` is not configured on the host
- WHEN the stack is deployed
- THEN `hermes` and text-based flows MUST still function; only voice input is unavailable

## 5. Proactivity (Cron)

### Requirement: Scheduled jobs
The system MUST define, via Hermes' native cron in natural language: a ~7am daily briefing (pendientes + today's training targets), a tarjeta alert N days before corte/pago, a birthday alert with configurable lead time, and a weekly expense summary by category.

#### Scenario: Morning briefing delivered unprompted
- GIVEN it is 07:00 Lima time
- WHEN the daily briefing cron job fires
- THEN a Telegram message with pending items and today's training targets is delivered without user request

#### Scenario: Tarjeta due-date alert
- GIVEN a `tarjetas` row with a corte/pago date N days away
- WHEN the tarjeta cron job runs
- THEN a Telegram alert is sent before the configured threshold

## 6. Security

### Requirement: Telegram user whitelist
The system MUST restrict bot interaction to a single whitelisted `TG_USER_ID`. Messages from any other Telegram user MUST be ignored. Mechanism CONFIRMED (F0.3): Hermes' native `allow_from` config key (env var `TELEGRAM_ALLOWED_USERS`), which denies all users by default when unset — no custom gateway-side filter code is needed.

#### Scenario: Unauthorized user messages the bot
- GIVEN a Telegram user whose ID is not `TG_USER_ID`
- WHEN they send a message to the bot
- THEN the bot does not respond and does not process the message
- AND this is verified live with a second Telegram account during Fase 1 (verification #7), not assumed from documentation alone

### Requirement: Write approval enabled
The system MUST set `write_approval: true` (overriding Hermes' default `false`) so all `skill_manage` writes are staged for approval before landing.

#### Scenario: Self-edited skill requires approval
- GIVEN the agent attempts to edit a skill file
- WHEN `write_approval: true` is active
- THEN the change is staged under `~/.hermes/pending/skills/` and requires explicit approve/deny

### Requirement: Data never leaves the server
Voice transcriptions and financial data MUST NOT be transmitted to any third party beyond the configured LLM endpoint and Telegram.

#### Scenario: Whisper runs fully local
- GIVEN a voice note is received
- WHEN it is transcribed
- THEN transcription happens on the local GPU sidecar, with no external STT API call

## 7. Backup and Portability

### Requirement: Encrypted, scheduled, retained backups
The system MUST run a `restic` service with a daily cron backing up the persistent volume to an encrypted remote repository, retaining 7 daily / 4 weekly / 12 monthly snapshots.

#### Scenario: Daily backup runs unattended
- GIVEN the `restic` service is configured with valid remote credentials
- WHEN the daily cron fires
- THEN a new encrypted snapshot is created and old snapshots beyond retention are pruned

### Requirement: Verified restore
The system MUST provide `backup/backup.sh` and `backup/restore.sh`, and a real restore drill MUST be executed on a laptop during Fase 1, confirming the assistant starts with memory and `vida.db` intact.

#### Scenario: Restore drill on laptop
- GIVEN an encrypted snapshot exists in the remote repository
- WHEN `restore.sh` runs on a laptop with the correct passphrase
- THEN the restored volume launches Hermes with pre-existing memory and `vida.db` data

### Requirement: Offsite passphrase copy
The restic passphrase MUST have an out-of-band copy (password manager or offline copy) that does not reside solely inside the backed-up volume or `labia03`.

#### Scenario: Server is lost entirely
- GIVEN `labia03` becomes permanently unavailable
- WHEN the user needs to restore from backup
- THEN the passphrase is retrievable from the offsite copy, not from the lost server

## 8. Observability (Host-Level)

### Requirement: Compose health check
A host-level script (cron or systemd timer, outside any container) MUST run `docker compose ps --format json` on an interval (~15 min) and alert via a direct Telegram Bot API `curl` call if any service is not `running`/`healthy`.

#### Scenario: Hermes container crashes
- GIVEN the `hermes` container stops unexpectedly
- WHEN the next health-check interval runs
- THEN a Telegram alert is sent via direct Bot API call, independent of the Hermes/Docker stack

### Requirement: Backup freshness check
A host-level script MUST validate that the latest `restic snapshots --json` entry is less than ~26h old, alerting via the same direct Telegram path if stale or if the restic command errors.

#### Scenario: Backup silently stops running
- GIVEN no new restic snapshot has been created in over 26 hours
- WHEN the freshness check runs
- THEN a Telegram alert is sent reporting stale backups

## 9. Skills Git Versioning

### Requirement: Local git repo for skills
`~/.hermes/skills/` MUST be a local git repository (commit-only, no remote required). Any SQLite files (e.g. `state.db`) MUST be excluded via `.gitignore`.

#### Scenario: Skill auto-edit is committed
- GIVEN the agent's skill edit is approved via `write_approval`
- WHEN the post-approval hook or ~15-min cron detects a change
- THEN `git add -A && git commit` records the change with a diffable history

#### Scenario: Bad self-edit is reverted
- GIVEN a skill edit degrades agent behavior
- WHEN the user inspects `git log -p` in `~/.hermes/skills/`
- THEN they can identify the offending commit and `git revert` it

### Requirement: Additive to existing backup
The skills git repo MUST live inside the same volume already covered by restic backups, introducing no new backup destination.

#### Scenario: Restic snapshot includes git history
- GIVEN a restic snapshot is taken
- WHEN the snapshot is inspected
- THEN `~/.hermes/skills/.git/` is present within it

## Out of Scope (Fase 2+)
Claude Code bridge, TTS/voice output, public exposure of `labia03`, local GPU LLM for general reasoning, Prometheus/Grafana, VPS migration execution, Honcho cross-session modeling, multi-user/multi-timezone/CI/PR review of skills.
