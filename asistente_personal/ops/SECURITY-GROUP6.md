# Group 6 — Security (design.md §5 D6, §13, spec §6)

Status of each Group 6 task after PR 4/6. Tasks 6.1, 6.3, 6.4, 6.5 require a real deployed
instance on `labia03` with real secrets and a live Telegram bot — they cannot be executed from a
sandboxed checkout of this repo and are intentionally **not** marked done here; doing so would be
a false claim. Task 6.2 and 6.6 are artifacts this PR delivers directly.

## 6.1 — `.env` with real values, `chmod 600`

**Not done here (requires live host + real secrets).** `.env.template` already lists every
required key (PR 1). Operator action on `labia03`:

```
cp .env.template .env
chmod 600 .env
# fill LLM_BASE_URL/LLM_API_KEY (F0.1, already known), TELEGRAM_TOKEN/TG_USER_ID (F0.4)
```

## 6.2 — `ops/.env.ops.template` (D6 least privilege)

**Done in this PR.** See `ops/.env.ops.template` (holds only `TELEGRAM_TOKEN`, `TG_USER_ID`,
`WHISPER_OPTIONAL`) — same D6 rationale as `.env.template`: watchdogs never need the LLM key or
restic credentials.

> Sandbox note: this repo's write-sandbox hard-blocks paths matching `.env*` (same restriction
> hit in PR 1 for `.env.template`). The content was written to
> `ops/env.ops.template.txt` — run `mv asistente_personal/ops/env.ops.template.txt
> asistente_personal/ops/.env.ops.template` locally to finalize the filename before the operator
> instantiates `ops/.env.ops` from it.

## 6.3 — Run `render-config.sh`

**Not done here (requires a live `$HERMES_DATA` and real `.env`).** The script itself was written
and structurally verified in PR 1 (task 1.6); running it for real is the operator's step 2 in
`design.md` §13, after 6.1.

## 6.4 — Live verification: second Telegram account is ignored

**Not done here — inherently a live test against a real bot.** Mechanism is already wired
(`config/config.yaml.template`'s `allow_from: [${TG_USER_ID}]`, F0.3 confirmed native). Operator
must message the bot from a second account after 9.1 and confirm no response, per spec §6
scenario and proposal success criterion #5.

## 6.5 — `skill_manage` edit requires approval

**Not done here — inherently a live test against a running gateway.** `write_approval: true` is
already set in `config/config.yaml.template` (PR 1). Operator triggers a `sobre-mi` edit after
rollout and confirms it lands in `~/.hermes/pending/skills/`.

## 6.6 — Code review: no data leaves the server beyond LLM endpoint + Telegram

**Done in this PR.** Reviewed for this PR: `bin/vida.py` (pure `sqlite3`, stdlib only — no
network calls of any kind), all `skills/*/SKILL.md` (each documents only `vida.py` invocations or,
for `entrada-voz`, a call to the internal `whisper:8000` service), `ops/transcribe-voice.sh` (the
only new network call in this PR — `curl` against `${WHISPER_URL:-http://whisper:8000}`, a
compose-internal, unpublished service per `docker-compose.yml`'s `whisper` block — no `ports:`
exposed), `config/config.yaml.template` (`provider.base_url` = the one configured LLM endpoint,
`telegram.token` = the one configured Telegram bot). **Finding: no third-party STT/analytics/data
egress path exists beyond the configured LLM endpoint and Telegram**, matching spec §6 "Data never
leaves the server". This finding will need to be re-run whenever Group 7 (backup/observability)
adds `ops/notify.sh`'s direct Bot API call — that is in-scope for spec §6 already (Telegram is an
allowed destination) and is PR 5's responsibility to re-confirm, not a new exception.
