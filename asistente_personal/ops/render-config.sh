#!/bin/sh
# One-shot bootstrap: render config/config.yaml.template into $HERMES_DATA/config.yaml.
# Never overwrites an existing config.yaml -- after first boot the agent owns that file
# (design.md §4, §13 step 3: the Telegram allowlist must be set before the gateway's
# first start; this script is what makes that step repeatable and idempotent).
#
# Usage: ops/render-config.sh
# Requires: .env sourced (or the referenced vars already exported), envsubst installed.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$SCRIPT_DIR/config/config.yaml.template"
TARGET_DIR="${HERMES_DATA:-$SCRIPT_DIR/state/hermes}"
TARGET="$TARGET_DIR/config.yaml"

if [ -f "$TARGET" ]; then
  echo "render-config.sh: $TARGET already exists, not overwriting." >&2
  exit 0
fi

if [ -f "$SCRIPT_DIR/.env" ]; then
  # shellcheck disable=SC1090
  set -a; . "$SCRIPT_DIR/.env"; set +a
fi

command -v envsubst >/dev/null 2>&1 || {
  echo "render-config.sh: envsubst not found (install gettext)." >&2
  exit 1
}

mkdir -p "$TARGET_DIR"
envsubst < "$TEMPLATE" > "$TARGET"
echo "render-config.sh: wrote $TARGET"
