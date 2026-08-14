# Asistente personal (Hermes Agent + Telegram) — Fase 1

Status: **code-complete across PR 1-6**. This README is the operator bring-up runbook — it is the
literal sequence a human follows on `labia03` to go from a checkout of this repo to a live,
verified assistant. See `../openspec/changes/hermes-personal-assistant/{proposal,spec,design,tasks}.md`
for the full plan, rationale, and per-task implementation notes.

**Nothing in this document has been executed.** Every script referenced here was written and
unit-/dry-run-tested inside the sandbox that built PRs 1-5 (real GPU, real Telegram bot, real
cloud backup credentials, and `labia03` itself were never available there). Running this runbook
for real, on `labia03`, is the one remaining step before Fase 1 is actually live — that is the
explicit purpose of this PR.

---

## 0. Before you start: close F0.5 (the one remaining hard blocker)

Every other Fase 0 item is closed or explicitly non-blocking:

| Item | Status |
|---|---|
| F0.1 — LLM endpoint (opencode Go + `gpt-5.6-luna`, see TROUBLESHOOTING.md §10) | 🟢 CONFIRMED |
| F0.2 — GPU visible inside containers (`nvidia-container-toolkit`) | 🟡 open, **non-blocking** — degrades to voice-less |
| F0.3 — Telegram whitelist mechanism (`allow_from` / `TELEGRAM_ALLOWED_USERS`) | 🟢 CONFIRMED |
| F0.4 — Telegram bot token + numeric `user_id` | 🟡 open, quick (BotFather) |
| **F0.5 — Backup destination + rclone credentials + offsite passphrase copy** | 🔴 **OPEN — HARD BLOCKER** |
| F0.6 — Docker Compose v2, Tailscale SSH, cron/systemd, host `python3` ≥ 3.8 | 🟡 open, sanity check only |
| F0.7 — Voice interception mechanism | 🟢 RESOLVED (PR 4) — skill-based, see `skills/entrada-voz/SKILL.md` §0 |

Full detail: `../openspec/changes/hermes-personal-assistant/proposal.md` §4.

**F0.5 must close before step 8 below (bringing up `restic`), and the restore drill (step 10) is
the hard success gate — Fase 1 is not done without it.** Nothing else in this runbook is blocked
by F0.5; you can do steps 1-7 (and the voice-less half of 9) with F0.5 still red.

To close F0.5:

1. Choose a backup destination (Google Drive personal or S3) and obtain rclone credentials for it.
2. Generate the `restic` repository passphrase.
3. Store the passphrase **outside `labia03`**: a password manager entry, plus a second offline
   copy (printed or written down, physically off the server). Fill in `backup/PASSPHRASE.md`'s
   table with where each copy lives — never the secret itself.
4. Write `secrets/rclone.conf` on `labia03` (`chmod 600`), and set `RESTIC_REPOSITORY` /
   `RESTIC_PASSWORD` in `.env` in step 2 below.

---

## 1. Host sanity checks (F0.6 / F0.6-extra)

Run on `labia03` before anything else:

```sh
docker compose version         # Docker Compose v2 present
docker ps                      # works without sudo, or decide it runs with sudo
python3 --version              # >= 3.8 (used by db-snapshot.sh, check-*.sh, restore.sh)
crontab -l                     # cron available (or confirm systemd --user + loginctl enable-linger)
```

Confirm Tailscale SSH reaches `labia03` from your laptop — this is your admin path since the
compose file publishes **zero inbound ports** by design.

If GPU/voice is in scope, also run (Group 4, task 4.1):

```sh
asistente_personal/ops/verify-gpu.sh
```

Exit 0 with visible `nvidia-smi` output → GPU is usable, proceed with `whisper` later. Exit
non-zero → set `WHISPER_OPTIONAL=1` in `ops/.env.ops` (step 3) and skip every `whisper` step below;
Fase 1 still ships, without voice (spec §4 — GPU unavailable degrades gracefully).

---

## 2. Render real secrets from templates

```sh
cd asistente_personal
cp .env.template .env
chmod 600 .env
# fill in: LLM_BASE_URL, LLM_API_KEY (F0.1, already known: opencode Go + gpt-5.6-luna),
#          the default model itself lives in config.yaml (model.default), not .env,
#          see TROUBLESHOOTING.md §10 if it needs changing again,
#          TELEGRAM_TOKEN, TG_USER_ID (F0.4),
#          RESTIC_REPOSITORY, RESTIC_PASSWORD, RCLONE_REMOTE (F0.5 — leave blank/unused if
#          F0.5 is still open; do NOT bring up `restic` until they're real)

cp ops/.env.ops.template ops/.env.ops   # if the template still has the .txt suffix from the
                                        # sandbox workaround, `mv` it first: see ops/SECURITY-GROUP6.md §6.2
chmod 600 ops/.env.ops
# fill in: TELEGRAM_TOKEN, TG_USER_ID (same values, least-privilege copy — D6)
# set WHISPER_OPTIONAL=1 here if step 1's verify-gpu.sh failed
```

`docker compose config` should validate cleanly against the real `.env` at this point (already
verified structurally in PR 1 against a placeholder `.env`).

---

## 3. Bootstrap order — the one irreversible step

**Do this before the first `docker compose up -d hermes`.** Starting the gateway before the
Telegram allowlist and `write_approval: true` are in place is the one mistake in this whole
runbook that cannot be undone after the fact — a message that lands before the allowlist exists is
a message the bot already acted on.

```sh
# 3a. One-shot official image init (per nousresearch/hermes-agent docs)
docker run --rm -it -v "${HERMES_DATA:-./state/hermes}:/opt/data" nousresearch/hermes-agent setup

# 3b. Render config.yaml from the template — sets allow_from: [<TG_USER_ID>] and
#     write_approval: true BEFORE the gateway ever starts (design.md §13 step 3)
ops/render-config.sh

# 3c. Confirm the rendered file actually has both, before proceeding:
grep -E 'allow_from|write_approval' "${HERMES_DATA:-./state/hermes}/config.yaml"
```

Do not proceed to step 4 until 3c's output shows your real `TG_USER_ID` in `allow_from` and
`write_approval: true`. `render-config.sh` never overwrites an existing `config.yaml` — if it
already exists from a previous partial attempt, verify it by hand instead of re-running.

---

## 4. Seed the skills git repo

```sh
ops/skills-git-init.sh
```

Copies the seed `SKILL.md` files into `$HERMES_DATA/skills/`, `git init`s a local-only,
commit-only repo there (`hermes-autocommit` / `hermes@labia03.local`, no remote — design §11), and
makes the first commit.

---

## 5. Bring up the stack (voice-less first)

```sh
docker compose up -d hermes
```

Verify text expense capture end to end from Telegram — *"gasté 45 soles en almuerzo"* — and
confirm the row lands in `vida.db` with the correct category (proposal success criterion #1,
verification checklist item 1 below).

If step 1's GPU check passed and `WHISPER_OPTIONAL` is unset:

```sh
docker compose up -d whisper
```

Send a voice note describing a gym set and confirm it transcribes and lands in `entrenamientos`
(task 4.4, success criterion #2). If GPU/whisper was skipped, confirm the rest of the stack stays
healthy with `WHISPER_OPTIONAL=1` — this is the documented degraded mode, not a failure.

---

## 6. Register cron jobs (proactivity)

Hermes' cron is registered **conversationally** — see `ops/cron-jobs.md` for the exact
Spanish messages to send the bot for: the ~7am morning briefing, the tarjeta due-date alert, the
birthday alert, and the weekly expense summary. Follow `ops/cron-jobs.md` §5.5's smoke-test
procedure (a 2-minute-interval throwaway variant, confirm 2-3 firings, then delete it and register
the real schedule) **before** trusting any job at its real interval — start with the 07:00
briefing since it is the one job with an explicit spec scenario.

---

## 7. Security live verification (Group 6 — cannot be done from a checkout)

- Message the bot from a **second** Telegram account and confirm it is ignored (`allow_from`
  already wired in step 3; proposal success criterion #5, spec §6, verification #7 below).
- Trigger a `sobre-mi` self-edit (any stable new preference) and confirm it lands in
  `~/.hermes/pending/skills/` requiring explicit approve/deny (`write_approval: true`, set in
  step 3).

Details and rationale: `ops/SECURITY-GROUP6.md`.

---

## 8. Bring up backups (gated on F0.5)

**Do not run this section until F0.5 (step 0) is closed.**

```sh
docker compose up -d restic
backup/backup.sh                 # on-demand: backup + retention + restic check --read-data-subset=5%
ops/check-backup.sh              # by hand once, confirm it reports the fresh snapshot correctly
```

Install the timer mechanism (only one — D12):

```sh
# cron:
sudo cp ops/hermes-ops.cron /etc/cron.d/hermes-ops
# or systemd (pick one, not both):
sudo cp ops/systemd/*.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-check-stack.timer hermes-check-backup.timer \
  hermes-db-snapshot.timer hermes-skills-autocommit.timer
```

Verify the alert path once, deliberately: stop `whisper` (`docker compose stop whisper`), wait for
the next `check-stack.sh` tick, confirm a Telegram alert arrives; restart it and confirm the
recovery alert (`"✅ recuperado"`). This is task 7.11 and success criterion #7 — an alert path is
not trusted until it has actually fired once.

---

## 9. Restore drill on a laptop — the hard gate

**Fase 1 is not done without this step (proposal success criterion #6).**

On a laptop (not `labia03`), with `restic`/Docker and `python3` installed, and
`RESTIC_REPOSITORY`/`RESTIC_PASSWORD`/`secrets/rclone.conf` available (from `backup/PASSPHRASE.md`
step 0):

```sh
backup/restore.sh --target ./restore-drill/hermes
```

Confirm the printed JSON summary shows integrity checks passing (`vida.db`/`state.db`, falling
back to the `db-snapshot.sh` snapshot if needed) and the skills git history present, then run the
literal command it prints:

```sh
HERMES_DATA=./restore-drill/hermes docker compose up -d
```

Confirm the assistant comes up on the laptop with memory and `vida.db` intact. Update the
**Verification date** field in `backup/PASSPHRASE.md` by hand — that field, not a script output, is
the record that this drill actually happened.

---

## 10. Final verification checklist (proposal.md §1, "Cómo se ve el éxito")

Walk through all seven, literally, without opening a terminal for any of them except where noted:

1. **Text expense capture** — say *"gasté 45 soles en almuerzo"* from Telegram; confirm a
   correctly-categorized row lands in `vida.db` (done in step 5).
2. **Voice gym log** — send a voice note describing a gym set; confirm local (GPU) transcription
   and a persisted `entrenamientos` row (step 5, conditional on F0.2/F0.7 not degrading — skip if
   `WHISPER_OPTIONAL=1`).
3. **Real progression query** — ask *"¿cuánto me toca en press banca hoy?"* and confirm the answer
   quotes `vida.py gym progress`'s `sugerencia`/`razon` verbatim, not an invented number.
4. **Unprompted 7am briefing** — confirm the registered job (step 6) fires on its own the next
   morning, Lima time, without being asked that day.
5. **Second Telegram user is ignored** — message the bot from an unauthorized account; confirm no
   response (step 7).
6. **Real restore drill** — the laptop restore in step 9, with the verification date recorded.
7. **Independent stack-down alert** — the alert-path test in step 8 (stop `whisper`, confirm the
   Telegram alert arrives via a path that does not depend on the stack it monitors, then confirm
   the recovery alert on restart).

Fase 1 is complete only when all seven are checked against a live `labia03`, not against this
document.

---

## Directory layout

```
asistente_personal/
├── docker-compose.yml       # hermes + whisper (GPU, optional) + restic
├── .env.template            .gitignore
├── config/config.yaml.template
├── data/schema.sql          bin/vida.py         tests/test_vida.py
├── skills/{registrar-gasto,gym-tracker,tarjetas,agenda-personal,sobre-mi,entrada-voz}/SKILL.md
├── ops/render-config.sh     ops/verify-gpu.sh   ops/transcribe-voice.sh
├── ops/{notify,check-stack,check-backup,db-snapshot,skills-git-init,skills-autocommit}.sh
├── ops/db_snapshot.py       ops/cron-jobs.md    ops/SECURITY-GROUP6.md
├── ops/hermes-ops.cron      ops/systemd/        ops/.env.ops.template
├── backup/{backup.sh,restore.sh,restore_verify.py,PASSPHRASE.md}
├── secrets/                 # gitignored — rclone.conf goes here, never committed
└── state/                   # gitignored — runtime volume + backup sentinel
```

## Rollback

`docker compose down` leaves `$HERMES_DATA` untouched — nothing installs to the host except the
one cron fragment (or systemd timer set) from step 8. A bad self-edited skill is `git revert` in
`$HERMES_DATA/skills` (step 4, design §11). A bad image tag is the previous digest — pin one here
once captured from `labia03`:

```
Pinned image digest: <not yet captured — capture during first real `docker compose up -d hermes`
on labia03 via `docker inspect --format '{{.RepoDigests}}' hermes` and record it here, then move
docker-compose.yml's `hermes.image` from `nousresearch/hermes-agent:latest` to the pinned digest>
```

## Reference: what's implemented per PR

| PR | Groups | What it added |
|---|---|---|
| 1 | 0-1 | Repo scaffolding, docker-compose.yml, config template, render-config.sh |
| 2 | 2 | `vida.db` schema, `vida.py` CLI, unit tests |
| 3 | 3 | The five domain skills (`registrar-gasto`, `gym-tracker`, `tarjetas`, `agenda-personal`, `sobre-mi`) |
| 4 | 4-6 | Voice input (`entrada-voz` skill + `transcribe-voice.sh`), cron job specs, security hardening |
| 5 | 7-8 | Backup/restore scripts, host watchdogs, skills git-versioning |
| 6 | 9 | This runbook — bring-up sequence, bootstrap ordering, final verification checklist |

Every PR's code is written and tested to the extent the sandbox that built it allowed (unit tests,
dry runs against throwaway local resources). **Live execution on `labia03` — everything in
sections 0-10 above — is the operator's job, not something any of these six PRs could do on their
own.**
