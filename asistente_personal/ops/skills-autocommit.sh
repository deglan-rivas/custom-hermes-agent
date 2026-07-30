#!/bin/sh
# Group 8, task 8.4 (design.md §11, §13 step 7): auto-commit any change to
# $HERMES_DATA/skills every ~15 min (wired into ops/hermes-ops.cron
# alongside check-stack.sh). This is the guaranteed path per design.md
# §11 -- an optional post-write_approval hook would only reduce latency,
# never replace this.
#
# Usage: ops/skills-autocommit.sh
# Env: HERMES_DATA (defaults to ./state/hermes, same as docker-compose.yml D9)

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HERMES_DATA_DIR="${HERMES_DATA:-$COMPOSE_DIR/state/hermes}"
SKILLS_DIR="$HERMES_DATA_DIR/skills"

cd "$SKILLS_DIR" || exit 0
[ -d .git ] || exit 0            # nunca auto-init desde cron (design.md §11)
git add -A
git diff --cached --quiet && exit 0   # sin cambios, sin commit vacio
git commit -q -m "auto: skills snapshot $(date -Iseconds)"
