#!/bin/sh
# Group 7, task 7.5 (design.md §10): shared Telegram sender for host-level
# watchdogs. No dependency on Docker, Hermes, or the compose network -- this
# is the one part of the alerting path that must survive the stack it
# monitors dying.
#
# Usage: ops/notify.sh "<message text>"
# Requires: ops/.env.ops sourced (TELEGRAM_TOKEN, TG_USER_ID) -- callers
# (check-stack.sh, check-backup.sh, skills-autocommit.sh) source it before
# calling this script.
#
# Always exits 0 so a notify failure never breaks a cron job's own exit
# status; on curl failure it falls back to `logger` (design.md §10: "there
# is no third channel and pretending otherwise would be theatre").

set -u

TEXT="${1:-}"

if [ -z "$TEXT" ]; then
  logger -t hermes-ops "notify.sh: called with no message text" 2>/dev/null || true
  exit 0
fi

if [ -z "${TELEGRAM_TOKEN:-}" ] || [ -z "${TG_USER_ID:-}" ]; then
  logger -t hermes-ops "notify.sh: TELEGRAM_TOKEN/TG_USER_ID not set, dropping: $TEXT" 2>/dev/null || true
  exit 0
fi

if ! curl -fsS --max-time 15 \
  -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
  -d "chat_id=${TG_USER_ID}" \
  --data-urlencode "text=${TEXT}" >/dev/null 2>&1; then
  logger -t hermes-ops "notify.sh: Telegram send failed: $TEXT" 2>/dev/null || true
fi

exit 0
