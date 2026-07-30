#!/bin/sh
# Group 7, task 7.1 `[BLOCKED: F0.5]` (design.md D8, §12): online consistent
# SQLite copies at 03:20, 10 min before the restic window at 03:30.
#
# Marked BLOCKED because the surrounding backup pipeline (restic) cannot be
# exercised end-to-end without F0.5, but this script itself has NO restic
# dependency -- it can and should run standalone once vida.db/state.db
# exist. The WAL-safe copy logic lives in ops/db_snapshot.py (stdlib
# sqlite3.backup() API) and is unit-tested in tests/test_db_snapshot.py.
#
# Usage: ops/db-snapshot.sh
# Env: HERMES_DATA (defaults to ./state/hermes, same as docker-compose.yml D9)

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HERMES_DATA_DIR="${HERMES_DATA:-$COMPOSE_DIR/state/hermes}"

command -v python3 >/dev/null 2>&1 || {
  echo "db-snapshot.sh: python3 not found" >&2
  exit 1
}

python3 "$SCRIPT_DIR/db_snapshot.py" \
  --db "$HERMES_DATA_DIR/data/vida.db" \
  --db "$HERMES_DATA_DIR/state.db" \
  --out-dir "$HERMES_DATA_DIR/backup"
