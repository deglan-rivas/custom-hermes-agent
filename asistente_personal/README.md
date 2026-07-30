# Asistente personal (Hermes Agent + Telegram) — Fase 1

Status: scaffolding in progress (PR 1/6 — infra). See
`../openspec/changes/hermes-personal-assistant/{proposal,spec,design,tasks}.md` for the full
plan. This README will be finalized in the rollout PR (Group 9, task 9.4) once the pinned image
digest is captured and every group has landed.

## Fase 0 checklist (must be closed before `docker compose up`)

See `../openspec/changes/hermes-personal-assistant/proposal.md` §4 for full detail.

- [x] F0.1 — LLM endpoint (opencode Go + `deepseek-v4-pro`) — CONFIRMED
- [ ] F0.2 — GPU visible inside containers (`nvidia-container-toolkit`) — non-blocking, degrades to voice-less
- [x] F0.3 — Telegram whitelist mechanism (`allow_from` / `TELEGRAM_ALLOWED_USERS`) — CONFIRMED
- [ ] F0.4 — Telegram bot token + numeric `user_id`
- [ ] F0.5 — Backup destination + rclone credentials + offsite passphrase copy — **HARD BLOCKER**, open
- [ ] F0.6 — Docker Compose v2, Tailscale SSH, cron/systemd, host `python3` >= 3.8
- [ ] F0.7 — Voice interception mechanism — non-blocking, degrades to voice-less

## Bootstrap (in progress — see tasks.md Groups 0-1 for what exists so far)

1. `cp .env.template .env`, fill in real values, `chmod 600 .env`.
2. `docker compose config` to validate the compose file structurally.
3. Later PRs add: `data/schema.sql` + `bin/vida.py` (data layer), `skills/*/SKILL.md` (domain
   skills), voice wiring, cron jobs, security verification, and backup/observability scripts.

## Directory layout

```
asistente_personal/
├── docker-compose.yml       # hermes + whisper (GPU, optional) + restic (blocked on F0.5)
├── .env.template            .gitignore
├── config/config.yaml.template
├── data/                    # schema.sql lands here (Group 2)
├── bin/                     # vida.py lands here (Group 2)
├── tests/                   # test_vida.py lands here (Group 2)
├── skills/                  # SKILL.md files land here (Group 3)
├── ops/render-config.sh     # renders config.yaml.template -> $HERMES_DATA/config.yaml once
├── backup/                  # backup.sh, restore.sh, PASSPHRASE.md land here (Group 7)
├── secrets/                 # gitignored — rclone.conf goes here, never committed
└── state/                   # gitignored — runtime volume + backup sentinel
```

## Verification checklist

Filled in incrementally as each group lands (see `tasks.md`). The hard gate is the restore
drill on a laptop (Group 7, task 7.10) — Fase 1 is not done without it.
