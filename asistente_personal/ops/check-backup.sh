#!/bin/sh
# Group 7, task 7.7 `[BLOCKED: F0.5]` (design.md §10, spec §8 "Backup
# freshness check"). Daily at 09:15 Lima (comfortably after the 03:30
# restic window, so a failure is reported in the morning, not at 3am).
#
# BLOCKED on F0.5: requires a real RESTIC_REPOSITORY/RESTIC_PASSWORD and a
# live `restic` service (docker-compose.yml). The logic below is complete
# and exercised against the exit-code/staleness/sentinel-mismatch branches
# (see manual dry-run notes in the PR description); it cannot be run
# end-to-end until F0.5 closes and `docker compose up -d restic` happens
# (task 7.9).
#
# Always exits 0 so cron stays quiet -- the Telegram alert is the signal.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_DIR="/var/tmp/hermes-ops"
STATE_FILE="$STATE_DIR/check-backup.state"
SENTINEL="$COMPOSE_DIR/state/backup/last-success"
STALE_SECONDS=$((26 * 3600))

mkdir -p "$STATE_DIR" 2>/dev/null || true

if [ -f "$SCRIPT_DIR/.env.ops" ]; then
  # shellcheck disable=SC1091
  set -a; . "$SCRIPT_DIR/.env.ops"; set +a
fi

notify() {
  "$SCRIPT_DIR/notify.sh" "$1"
}

previous_state="unknown"
[ -f "$STATE_FILE" ] && previous_state="$(cat "$STATE_FILE" 2>/dev/null || echo unknown)"

cd "$COMPOSE_DIR" || exit 0

SNAPSHOTS_JSON="$(docker compose run --rm --entrypoint restic restic snapshots --json --latest 1 2>/dev/null)"
RESTIC_EXIT=$?

now_epoch="$(date +%s)"
sentinel_epoch=""
if [ -f "$SENTINEL" ]; then
  sentinel_epoch="$(date -r "$SENTINEL" +%s 2>/dev/null || echo "")"
fi

CURRENT_STATE="ok"
DETAIL=""

if [ "$RESTIC_EXIT" -ne 0 ]; then
  CURRENT_STATE="bad"
  DETAIL="restic snapshots exited $RESTIC_EXIT (repo inalcanzable, passphrase incorrecta, o token rclone vencido)"
elif [ -z "$SNAPSHOTS_JSON" ] || [ "$SNAPSHOTS_JSON" = "[]" ] || [ "$SNAPSHOTS_JSON" = "null" ]; then
  CURRENT_STATE="bad"
  DETAIL="ningun snapshot encontrado en el repositorio"
  if [ -n "$sentinel_epoch" ]; then
    age=$((now_epoch - sentinel_epoch))
    if [ "$age" -lt "$STALE_SECONDS" ]; then
      DETAIL="$DETAIL (sentinel state/backup/last-success esta fresco pero no hay snapshots -- el post-command corrio sin que el backup terminara)"
    fi
  fi
else
  snapshot_time_epoch="$(printf '%s' "$SNAPSHOTS_JSON" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    entry = data[0] if isinstance(data, list) else data
    print(entry.get("time", ""))
except Exception:
    print("")
' 2>/dev/null | xargs -I{} date -d {} +%s 2>/dev/null || echo "")"

  if [ -z "$snapshot_time_epoch" ]; then
    CURRENT_STATE="bad"
    DETAIL="no se pudo parsear el timestamp del ultimo snapshot"
  else
    age=$((now_epoch - snapshot_time_epoch))
    if [ "$age" -gt "$STALE_SECONDS" ]; then
      CURRENT_STATE="bad"
      DETAIL="ultimo snapshot tiene mas de 26h (edad: ${age}s)"
    fi
  fi
fi

echo "$CURRENT_STATE" > "$STATE_FILE"

if [ "$CURRENT_STATE" = "bad" ] && [ "$previous_state" != "bad" ]; then
  notify "check-backup.sh: backup stale/fallido -> $DETAIL"
elif [ "$CURRENT_STATE" = "ok" ] && [ "$previous_state" = "bad" ]; then
  notify "check-backup.sh: recuperado"
fi

exit 0
