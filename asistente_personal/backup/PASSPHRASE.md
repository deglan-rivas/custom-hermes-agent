# Restic passphrase — where it lives, never what it is

Design ref: `openspec/changes/hermes-personal-assistant/design.md` §12.
Proposal ref: `openspec/changes/hermes-personal-assistant/proposal.md` §4, F0.5.

**This file MUST NEVER contain the actual passphrase, token, or repository
credentials.** It exists so that the person who needs to restore in
January 2027 (or whenever) knows *where* to find them — the failure mode
this file defends against is not "we never generated a passphrase", it is
"the person who needs it does not know where it is".

Three copies are required, at least two of them off `labia03`:

| Field | Content |
|---|---|
| Where the passphrase lives | _(fill in during F0.5, e.g. `Bitwarden → "restic labia03 hermes-data"`)_ |
| Second, offline copy | _(fill in during F0.5, e.g. "sobre en carpeta de documentos, casa")_ |
| Repository URL | _(fill in during F0.5, e.g. `rclone:<remote>:hermes-backup`; note where the `rclone.conf` token is re-obtainable)_ |
| Recovery procedure | 1. Get the passphrase from the password manager or the offline copy. 2. Install `restic` + `rclone` (or use the `mazzolino/restic:1.6` Docker image already in `docker-compose.yml`). 3. Export `RESTIC_REPOSITORY` and `RESTIC_PASSWORD`, then run `backup/restore.sh --target DIR`. 4. Run `HERMES_DATA=DIR docker compose up -d` (the literal command `restore.sh` prints at the end). |
| Verification date | _(updated by hand after each successful restore drill — task 7.10)_ |

## Status: F0.5 is OPEN

Do not fill in the fields above, do not run `docker compose up -d restic`,
and do not populate `RESTIC_REPOSITORY`/`RESTIC_PASSWORD` in `.env` until
F0.5 (backup destination + passphrase + offsite copy) is resolved — see
`proposal.md` §4. `backup/backup.sh` and `backup/restore.sh` already refuse
to run without those two env vars set, which is the intended gate.

## Restore drill (task 7.10)

The real restore drill — running `restore.sh` on a laptop against a real
snapshot and confirming `HERMES_DATA=./restore-drill/hermes docker compose
up -d` starts Hermes with memory and `vida.db` intact — **cannot be
executed from this sandbox**. It requires:

1. `labia03` running with the `restic` service live and at least one real
   snapshot taken (task 7.9).
2. Real cloud credentials (`RESTIC_REPOSITORY`, `RESTIC_PASSWORD`,
   `secrets/rclone.conf`) available on a laptop, not just on `labia03`.
3. A laptop with `restic` (or Docker) and `python3` installed.

This is documented here as a manual runbook step for the operator, not
faked as complete. Per `proposal.md` success criterion #6, Fase 1 is not
done until this drill has actually run once and this file's "Verification
date" field has been updated by hand.
