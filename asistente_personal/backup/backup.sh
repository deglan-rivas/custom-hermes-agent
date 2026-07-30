#!/bin/sh
# Group 7, task 7.2 `[BLOCKED: F0.5]` (design.md §12, spec §7 "Verified
# restore precondition"): on-demand backup + retention + read-data
# verification, runnable independently of the nightly `restic` service cron
# (design.md §12: "the nightly path is the restic service's own cron").
#
# BLOCKED on F0.5: requires real .env RESTIC_REPOSITORY/RESTIC_PASSWORD and
# secrets/rclone.conf. The logic below is complete; it has been dry-run
# against a throwaway local restic repo (see PR description) to confirm the
# script does not error out structurally, but not against the real
# encrypted remote until F0.5 closes.
#
# Usage: backup/backup.sh
# Requires: ../.env (RESTIC_REPOSITORY, RESTIC_PASSWORD), ../secrets/rclone.conf

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SENTINEL_DIR="$COMPOSE_DIR/state/backup"
SENTINEL="$SENTINEL_DIR/last-success"

cd "$COMPOSE_DIR"

fail() {
  echo "backup.sh: $1" >&2
  # Least-privilege watchdog creds only, per D6 -- backup.sh itself may run
  # with the main .env, but notify.sh must only ever see TELEGRAM_TOKEN/TG_USER_ID.
  if [ -f "$SCRIPT_DIR/../ops/.env.ops" ]; then
    # shellcheck disable=SC1091
    set -a; . "$SCRIPT_DIR/../ops/.env.ops"; set +a
  fi
  "$SCRIPT_DIR/../ops/notify.sh" "backup.sh: FALLO -- $1" || true
  exit 1
}

[ -f "$COMPOSE_DIR/.env" ] || fail "no se encontro .env (F0.5 no configurado)"

mkdir -p "$SENTINEL_DIR"

echo "backup.sh: restic backup /data --tag manual --host labia03"
docker compose run --rm --entrypoint restic restic \
  backup /data --tag manual --host labia03 \
  || fail "restic backup fallo"

echo "backup.sh: restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune"
docker compose run --rm --entrypoint restic restic \
  forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune \
  || fail "restic forget fallo"

echo "backup.sh: restic check --read-data-subset=5%"
docker compose run --rm --entrypoint restic restic \
  check --read-data-subset=5% \
  || fail "restic check fallo -- el repositorio lista snapshots pero los datos no verifican"

date -Iseconds > "$SENTINEL"
echo "backup.sh: OK -- sentinel escrito en $SENTINEL"
