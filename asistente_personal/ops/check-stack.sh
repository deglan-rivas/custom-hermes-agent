#!/bin/sh
# Group 7, task 7.6 (design.md §10, spec §8 "Compose health check").
# Every 15 min (see ops/hermes-ops.cron): parse `docker compose ps` with
# host python3 (not awk/jq -- design.md §10: "JSON parsing in awk is how you
# get a watchdog that lies", jq is not assumed present, python3 already is).
#
# Expects `hermes` and `restic` running; `whisper` too unless
# ops/.env.ops sets WHISPER_OPTIONAL=1 (F0.2-degraded mode, spec §4).
#
# Transition-only alerting (shared convention, design.md §10): keeps a
# one-word state file per check under /var/tmp/hermes-ops/<check>.state and
# only notifies on ok->bad or bad->ok, so a 15-min poller stays survivable.
#
# Always exits 0 so cron stays quiet regardless of stack health -- the
# Telegram alert IS the signal, not the cron log.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_DIR="/var/tmp/hermes-ops"
STATE_FILE="$STATE_DIR/check-stack.state"

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

if ! command -v python3 >/dev/null 2>&1; then
  echo "bad" > "$STATE_FILE"
  if [ "$previous_state" != "bad" ]; then
    notify "check-stack.sh: python3 no encontrado en el host -- watchdog no puede validar el stack."
  fi
  exit 0
fi

cd "$COMPOSE_DIR" || exit 0

PS_JSON="$(docker compose ps --format json 2>/dev/null)"
DOCKER_EXIT=$?

if [ "$DOCKER_EXIT" -ne 0 ]; then
  echo "bad" > "$STATE_FILE"
  if [ "$previous_state" != "bad" ]; then
    notify "check-stack.sh: 'docker compose ps' fallo (exit $DOCKER_EXIT) -- Docker daemon caido?"
  fi
  exit 0
fi

WHISPER_OPTIONAL="${WHISPER_OPTIONAL:-0}"

REPORT="$(PS_JSON="$PS_JSON" WHISPER_OPTIONAL="$WHISPER_OPTIONAL" python3 - <<'PYEOF'
import json
import os
import sys

whisper_optional = os.environ.get("WHISPER_OPTIONAL", "0") == "1"
required = {"hermes", "restic"}
if not whisper_optional:
    required.add("whisper")

raw = os.environ.get("PS_JSON", "").strip()
services = {}
if raw:
    # `docker compose ps --format json` emits either one JSON array or one
    # JSON object per line depending on compose version -- handle both.
    try:
        parsed = json.loads(raw)
        entries = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        entries = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    for entry in entries:
        name = entry.get("Service") or entry.get("Name")
        if name:
            services[name] = entry

problems = []
for name in sorted(required):
    entry = services.get(name)
    if entry is None:
        problems.append(f"{name}: no encontrado en docker compose ps")
        continue
    state = entry.get("State", "unknown")
    health = entry.get("Health", "")
    if state != "running":
        problems.append(f"{name}: state={state}")
    elif health and health != "healthy":
        problems.append(f"{name}: health={health}")

if problems:
    print("bad")
    print("; ".join(problems))
else:
    print("ok")
PYEOF
)"

CURRENT_STATE="$(printf '%s\n' "$REPORT" | head -n1)"
DETAIL="$(printf '%s\n' "$REPORT" | tail -n +2)"

echo "$CURRENT_STATE" > "$STATE_FILE"

if [ "$CURRENT_STATE" = "bad" ] && [ "$previous_state" != "bad" ]; then
  notify "check-stack.sh: stack degradado -> $DETAIL"
elif [ "$CURRENT_STATE" = "ok" ] && [ "$previous_state" = "bad" ]; then
  notify "check-stack.sh: recuperado"
fi

exit 0
