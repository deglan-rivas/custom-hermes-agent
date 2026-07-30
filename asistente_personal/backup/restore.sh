#!/bin/sh
# Group 7, task 7.3 `[BLOCKED: F0.5]` (design.md §12, spec §7 "Verified
# restore"): restore a restic snapshot to a target directory and prove it
# is usable -- SQLite integrity (with D8 snapshot fallback), skills git
# history, and a JSON summary. Designed to run on a laptop, not labia03
# (design.md §12: "this is the part that makes it a drill and not a copy").
#
# BLOCKED on F0.5: requires a real RESTIC_REPOSITORY/RESTIC_PASSWORD and an
# existing encrypted snapshot. The restore + verification logic below is
# complete and its Python half (restore_verify.py) is unit-tested in
# tests/test_restore_verify.py; the restic-restore half was dry-run against
# a throwaway local repo with a fake snapshot to confirm the script's
# argument handling and refusal branches (see PR description), but the real
# restore drill (task 7.10) requires labia03 + real cloud credentials and
# cannot be executed from this sandbox.
#
# Usage: backup/restore.sh --target DIR [--snapshot latest] [--force]
# Requires: RESTIC_REPOSITORY and RESTIC_PASSWORD exported in the
#           environment (e.g. `set -a; . .env; set +a` first), the `restic`
#           binary on PATH, and python3.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

TARGET=""
SNAPSHOT="latest"
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --target)
      TARGET="$2"
      shift 2
      ;;
    --snapshot)
      SNAPSHOT="$2"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    *)
      echo "restore.sh: argumento desconocido: $1" >&2
      exit 1
      ;;
  esac
done

if [ -z "$TARGET" ]; then
  echo "restore.sh: falta --target DIR" >&2
  exit 1
fi

if [ -z "${RESTIC_REPOSITORY:-}" ] || [ -z "${RESTIC_PASSWORD:-}" ]; then
  echo "restore.sh: RESTIC_REPOSITORY/RESTIC_PASSWORD no configurados." >&2
  echo "restore.sh: ver backup/PASSPHRASE.md para saber donde estan." >&2
  exit 1
fi

if ! command -v restic >/dev/null 2>&1; then
  echo "restore.sh: 'restic' no encontrado en PATH." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "restore.sh: python3 no encontrado." >&2
  exit 1
fi

if [ -d "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ] && [ "$FORCE" -ne 1 ]; then
  echo "restore.sh: $TARGET no esta vacio. Usa --force para sobreescribir." >&2
  exit 1
fi

mkdir -p "$TARGET"

echo "restore.sh: restic restore $SNAPSHOT --target $TARGET"
restic restore "$SNAPSHOT" --target "$TARGET"

SNAPSHOT_JSON="$(restic snapshots --json --latest 1)"
SNAPSHOT_ID="$(printf '%s' "$SNAPSHOT_JSON" | python3 -c '
import json, sys
data = json.load(sys.stdin)
entry = data[0] if isinstance(data, list) else data
print(entry.get("short_id", entry.get("id", "unknown")))
')"
SNAPSHOT_TIME="$(printf '%s' "$SNAPSHOT_JSON" | python3 -c '
import json, sys
data = json.load(sys.stdin)
entry = data[0] if isinstance(data, list) else data
print(entry.get("time", "unknown"))
')"

echo "restore.sh: verificando integridad y git de skills..."
VERIFY_EXIT=0
python3 "$SCRIPT_DIR/restore_verify.py" \
  --target "$TARGET" \
  --db data/vida.db \
  --db state.db \
  --snapshot-dir "$TARGET/backup" \
  --snapshot-id "$SNAPSHOT_ID" \
  --snapshot-time "$SNAPSHOT_TIME" || VERIFY_EXIT=$?

echo ""
echo "restore.sh: si la verificacion fue OK, arranca Hermes con:"
echo "  HERMES_DATA=$TARGET docker compose up -d"

exit "$VERIFY_EXIT"
