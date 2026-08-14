#!/bin/sh
# Transcribe a Telegram voice note via the whisper sidecar's OpenAI-compatible
# POST /v1/audio/transcriptions endpoint (speaches-ai/speaches backend).
#
# Design ref: design.md §5 D3 (compose service), §15 (voice interception decision).
# DECISION (F0.7, resolved by this PR): the integration point is a SKILL calling this
# script directly, not a gateway-level pre-message hook -- see
# skills/entrada-voz/SKILL.md for the full rationale. Both alternatives land on this
# same POST /v1/audio/transcriptions contract (design §15), so nothing here changes if
# a native hook is confirmed later.
#
# Contract: stdout is always exactly one JSON object, same shape as vida.py's contract
# so the calling skill can treat both the same way:
#   success -> {"ok": true, "action": "asr.transcribe", "data": {"texto": "..."}}       exit 0
#   failure -> {"ok": false, "action": "asr.transcribe", "error": "...", "codigo": "..."} exit 1
#
# Graceful degrade (spec §4 "GPU unavailable degrades gracefully"): if whisper is
# unreachable, times out, or errors, this exits 1 with a codigo describing why instead
# of crashing. The calling skill MUST then ask the user to type the message -- never
# silently drop it, never retry in a loop.
#
# Usage: ops/transcribe-voice.sh <path-to-downloaded-audio-file>

set -u

WHISPER_URL="${WHISPER_URL:-http://whisper:8000}"
AUDIO_FILE="${1:-}"
ACTION="asr.transcribe"
# Debe coincidir con PRELOAD_MODELS en docker-compose.yml (servicio whisper).
WHISPER_MODEL="${WHISPER_MODEL:-Systran/faster-whisper-large-v3}"

fail() {
  codigo="$1"
  error="$2"
  python3 -c '
import json, sys
print(json.dumps({"ok": False, "action": sys.argv[1], "error": sys.argv[2], "codigo": sys.argv[3]}))
' "$ACTION" "$error" "$codigo"
  exit 1
}

[ -n "$AUDIO_FILE" ] || fail "argumento_faltante" "uso: transcribe-voice.sh <path-to-audio-file>"
[ -f "$AUDIO_FILE" ] || fail "archivo_no_encontrado" "no existe: $AUDIO_FILE"
command -v curl >/dev/null 2>&1 || fail "curl_no_disponible" "curl no esta instalado"
command -v python3 >/dev/null 2>&1 || fail "python3_no_disponible" "python3 no esta instalado"

RESPUESTA="$(curl -fsS --max-time 30 \
  -F "file=@${AUDIO_FILE}" \
  -F "model=${WHISPER_MODEL}" \
  "${WHISPER_URL}/v1/audio/transcriptions" 2>/dev/null)" || {
  fail "whisper_no_disponible" "no se pudo contactar ${WHISPER_URL}/v1/audio/transcriptions (servicio caido, timeout, o F0.2/whisper aun no desplegado -- ver ops/verify-gpu.sh)"
}

printf '%s' "$RESPUESTA" | python3 -c '
import json, sys

raw = sys.stdin.read()
try:
    payload = json.loads(raw)
except json.JSONDecodeError:
    print(json.dumps({"ok": False, "action": "asr.transcribe", "error": "respuesta no-JSON de whisper", "codigo": "respuesta_invalida"}))
    sys.exit(1)

texto = (payload.get("text") or "").strip()
if not texto:
    print(json.dumps({"ok": False, "action": "asr.transcribe", "error": "transcripcion vacia", "codigo": "transcripcion_vacia"}))
    sys.exit(1)

print(json.dumps({"ok": True, "action": "asr.transcribe", "data": {"texto": texto}}))
'
