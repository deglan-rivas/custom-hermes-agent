## Exploration: Hermes Agent personal assistant (labia03 + Telegram) — 5 open concerns

### Current State
PLAN.md (repo root) defines a phase-1 architecture: Hermes Agent (Nous Research, MIT) in Docker on labia03, Telegram long-polling as primary channel, hybrid LLM (opencode/DeepSeek + local GPU), custom SQLite (vida.db) + vida.py CLI for structured data, custom skills under ~/.hermes/skills/, whisper STT input-only, restic backups to cloud. PREGUNTAS_BASE.md is the Q&A that produced these decisions. This exploration investigated the 5 user-flagged risks before proposal.

### Affected Areas
- PLAN.md — Dockerfile section (Fase 1, item 1) is based on an outdated/incorrect assumption (no official Docker image) — needs correction before sdd-propose.
- PLAN.md — cron proactivity section (Fase 1, item 5, "Briefing matutino ~7am") assumes timezone correctness not guaranteed by Hermes itself.
- PLAN.md — Seguridad section already lists `write_approval`; confirmed real and matches docs, no change needed.
- New: needs an observability/healthcheck component not currently in PLAN.md.
- New: needs a decision on git-versioning `~/.hermes/skills/` (or all of `.hermes/`) not currently in PLAN.md.

### Findings per concern

**1. Hermes Agent claims validation (biggest risk)**
- Official repo confirmed: `github.com/NousResearch/hermes-agent`, MIT license, active in 2026 (docs, blog posts, third-party guides all corroborate).
- Docker: **PLAN.md's claim "No existe imagen Docker oficial" is WRONG.** There IS an official prebuilt image `nousresearch/hermes-agent` on Docker Hub, Debian 13.4 based, s6-overlay supervised, treats `/opt/hermes` as immutable, all state in `/opt/data` (maps to `~/.hermes` on host). Docs: `docker run -it --rm -v ~/.hermes:/opt/data nousresearch/hermes-agent setup`. This SIMPLIFIES phase 1 — no custom Dockerfile needed, just a docker-compose service referencing the official image + volume + env vars.
- GPU: the Hermes container itself does not need GPU (calls out to LLM APIs). GPU passthrough is documented only for **sidecar** inference containers (their example uses vLLM with `devices: [capabilities: [gpu]]`). This matches PLAN.md's separate `whisper` container design — no conflict, confirmed correct pattern.
- Cron scheduler: real, built-in, gateway daemon ticks every 60s, runs due jobs in isolated agent sessions, delivers to any configured channel (Telegram confirmed), natural-language schedule definition confirmed via docs and third-party writeups (MindStudio blog: "Set Up Automated GitHub Backups with a Single Sentence"). Confirmed real, not just marketing.
- `skill_manage` + `write_approval`: **confirmed real and works as PLAN.md describes.** When `write_approval: true`, every skill_manage write (create/edit/patch/delete/write_file/remove_file) is staged under `~/.hermes/pending/skills/`, survives restarts, reviewed via approve/deny with unified diffs — same flow as dangerous-command approval. Default is `false` (agent writes freely) — PLAN.md's recommendation to flip it to `true` is correct and necessary.
- Memory: **confirmed real.** SQLite at `~/.hermes/state.db`, FTS5 full-text search over session messages (not LLM-approximated — actual DB rows), optional Honcho integration for cross-session "dialectic" user modeling (separate opt-in provider, not the default engine). PLAN.md's characterization ("good for soft context, bad for `cuánto gasté en junio`") is accurate — FTS5 does keyword search over conversation text, not structured aggregation, so the vida.db decision is correctly justified.
- **Conclusion: 4 of 5 sub-claims fully validated as real (cron, skill_manage/write_approval, memory, GPU sidecar pattern). One sub-claim (no official Docker image) is factually wrong in PLAN.md and should be corrected — use the official image, drop the custom Dockerfile.**
- Still needs live verification (not resolvable by research): whether the specific opencode/DeepSeek endpoint responds to a real `/v1/chat/completions` curl — this was already flagged as Fase 0 blocking work in PLAN.md and remains correctly scoped there.

**2. labia03 shared institutional server**
- Not resolvable by research — these are facts about a specific machine/institution only the user knows. Must be asked directly before proposal:
  - Is the 48GB GPU exclusively assigned to the user, or shared with other JNE jobs/colleagues? (Contention risk for whisper transcription latency and any local-GPU LLM fallback.)
  - Does the user have root/sudo on labia03? Required for installing `nvidia-container-toolkit` and configuring Docker's GPU runtime — without it, the whisper sidecar GPU passthrough (finding #1) is blocked entirely.
  - Any JNE IT policy on running personal/non-institutional software (Docker containers, cron jobs, background daemons) on a work server? Even though nothing is publicly exposed (long-polling only, no inbound ports), an internal audit or resource-usage policy could still flag this.
- Recommendation: add these three questions as an explicit Fase 0 gate in the proposal, before writing any Docker Compose file — a "no" on sudo access is a hard blocker for the whisper GPU container specifically (not for Hermes itself, which needs no GPU).

**3. No observability for the assistant's own health**
- No existing mechanism in PLAN.md. Recommend a minimal, single-user-sized approach (no Prometheus/Grafana):
  - A cron job (host crontab or a `healthcheck` script triggered by Hermes' own cron, defined in natural language) that runs `docker compose ps --format json` every N minutes (e.g. 15), checks all three services (`hermes`, `whisper`, `restic`) report `running`/`healthy`, and if any is down, sends a Telegram message via a direct `curl` call to the Bot API (does not depend on Hermes itself being alive, since Hermes being down is exactly the failure being detected) — this must be a standalone shell script, not a Hermes skill, precisely because Hermes' own outage is one of the failure modes to catch.
  - A second check validates the latest `restic snapshots --json` entry is younger than ~26h (accounting for the daily backup schedule) and alerts via the same standalone Telegram curl path if stale or if the restic command itself errors.
  - Both checks run from the host (not inside a container that could itself be the thing that's down) via a simple systemd timer or host crontab — deliberately outside Hermes/Docker so a Hermes or Docker Compose failure doesn't also kill the alerting path.
  - Effort: Low (2 shell scripts + 1 systemd timer or crontab entry). This is a material gap the user didn't ask about directly but IS asked about implicitly (concern #3) — already covered, just noting the concrete design.

**4. Skills auto-edited by the agent — no version control**
- Explored: making `~/.hermes/skills/` (or all of `~/.hermes/`) a local-only git repo.
- Feasibility: yes. `write_approval` staging already gives a review point before any write lands, but restic's daily/weekly snapshots are coarse (not diff-friendly, no per-commit message, restore requires full volume mount). A git repo layered *inside* the same Docker volume gives instant `git diff`/`git log`/`git revert` for skill files specifically, with near-zero overhead (skills are small text files).
- Two viable scopes:
  - **Scope A — `~/.hermes/skills/` only**: smaller repo, faster, but doesn't capture memory DB or session state changes (out of scope for git anyway — SQLite files don't diff meaningfully in git).
  - **Scope B — whole `~/.hermes/`**: captures skills + config.yaml changes together, but state.db (SQLite, binary, frequently written) would bloat the repo and produce noisy diffs; should be `.gitignore`d even in this scope.
- Recommendation: **Scope A** (`~/.hermes/skills/` as its own git repo, commit-only, no remote — or remote = a private branch/subdir of this same repo if the user wants an off-box copy). A `post-write` hook or a lightweight wrapper script invoked right after each `write_approval` approval (or a cron job every 15 min that runs `git add -A && git commit -m "auto: skill snapshot"` if there are changes) is enough. Sized for single-user: no CI, no PR review, just linear history for `git log -p` / `git revert` when a self-edited skill misbehaves.
- Docker volume fit: since `~/.hermes/skills/` already lives inside the single persistent volume (`hermes-data`), a `.git/` directory there is transparently included in the existing restic backup — no new backup target needed, this is additive, not a parallel system.
- Effort: Low.

**5. Cron timezone handling**
- Verified directly against primary docs (not just AI search summaries, which initially returned a claim of a documented `HERMES_TIMEZONE env → config.yaml timezone field → system time` fallback chain — this claim did NOT hold up under direct fetch of the source docs).
- Ground truth from `website/docs/user-guide/features/cron.md` and `website/docs/user-guide/configuration.md` (fetched directly): **zero references to timezone, TZ, or locale configuration anywhere in either doc.** Hermes has no documented timezone-aware concept at all.
- Corroborating evidence: multiple OPEN feature-request issues on the repo (e.g. "Per-job timezone for cron schedules", "Feature: Timezone Awareness in hermes setup", "Native user timezone configuration — Hermes should default to user's timezone, not UTC") — these confirm timezone awareness is explicitly NOT yet implemented, only requested.
- Practical consequence: the cron scheduler's "7am" is whatever the **container's OS-level clock** thinks 7am is — i.e., standard Linux `TZ` semantics. Since the Docker container's system time follows its `TZ` environment variable (or defaults to UTC if unset), this is fully controllable at the Compose level, no Hermes-specific config needed.
- **Recommendation**: set `TZ=America/Lima` as an environment variable on the `hermes` service in `docker-compose.yml` (or in `~/.hermes/.env` if Hermes' cron reads the process's system timezone rather than wall-clock UTC — either way, standard Linux `TZ` env var resolution applies since Hermes has no internal override). This is a one-line fix, not a Hermes feature dependency. Flag to the user: there is currently no way to run one cron job in Lima time and another in UTC in the same instance (per-job TZ is an open feature request, not shipped) — not a problem for this use case (all jobs are for the same user in the same timezone), but worth knowing if multi-timezone use is ever wanted.

### Other gaps noticed (not explicitly asked but material to phase 1)
- **PLAN.md's Dockerfile/install approach is now redundant** given the official `nousresearch/hermes-agent` image — sdd-propose should drop the custom Dockerfile task entirely and use the official image directly, reducing phase-1 scope.
- **Telegram user_id whitelist** is mentioned in PLAN.md's security section but the mechanism (Hermes-native allowlist config vs a custom gateway-side filter) was not verified — should be confirmed during Fase 0 alongside the opencode endpoint check, since an unverified assumption here is a real "anyone can DM your bot" risk.
- **Restic passphrase storage**: PLAN.md says "generar la passphrase de restic" but doesn't specify where the passphrase itself is stored/backed up — if it only lives in `.env` on labia03 and labia03 is lost before a copy is taken elsewhere, the backups become unrecoverable. Should be an explicit task: store the restic passphrase in a password manager or printed/offline copy, not solely in the volume being backed up.
- **opencode subscription lifecycle**: PLAN.md correctly notes opencode dies with labia03/January 2027, and mitigates via `LLM_BASE_URL` env var — but doesn't yet name a concrete Plan B provider/API key to pre-provision so the switch is truly a one-line `.env` edit and not a same-day scramble when the endpoint disappears.

### Recommendation
Proceed to sdd-propose with these corrections folded in:
1. Use the official `nousresearch/hermes-agent` Docker image (drop custom Dockerfile task).
2. Add three labia03 institutional questions as an explicit Fase 0 gate (GPU exclusivity, sudo/root access, JNE policy).
3. Add a minimal host-level (outside Docker) healthcheck + restic-freshness alerting pair as a phase-1 task.
4. Add `~/.hermes/skills/` as a local git repo (Scope A) with an auto-commit cron hook, as a phase-1 task.
5. Set `TZ=America/Lima` on the hermes container/compose env as a phase-1 task; document that per-job TZ override is not yet a Hermes feature.
6. Add the Telegram whitelist mechanism verification and the restic-passphrase-offsite-copy task to Fase 0/Fase 1 respectively.

### Risks
- opencode/DeepSeek endpoint compatibility remains genuinely unverified (Fase 0 blocker, unchanged from PLAN.md).
- labia03 sudo/root access is unknown and could block the whisper GPU sidecar entirely if unavailable — must be confirmed before design phase.
- GPU contention with other JNE workloads is unknown and could affect both whisper latency and any local-GPU LLM fallback path.
- Hermes' timezone behavior depends on container OS clock, not a documented Hermes feature — low risk given the one-line fix, but worth a footnote in the design so nobody assumes Hermes "understands" Peru time natively.

### Ready for Proposal
Yes — all 5 flagged concerns have concrete findings and recommendations; only the labia03 institutional facts (GPU sharing, sudo access, JNE policy) require direct user input before Fase 0/design can be finalized, and that is already surfaced as explicit questions rather than a blocker to writing the proposal itself.

---
_Migrated from Engram observation #588 (topic: `sdd/hermes-personal-assistant/explore`), created 2026-07-29 21:27:20._
