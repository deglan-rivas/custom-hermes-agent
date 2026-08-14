# Delta for Voice Input (entrada-voz)

Change: `whisper-backend-swap` | Type: delta (modifies Section 4 "Voice Input" of `openspec/changes/hermes-personal-assistant/spec.md`).

## MODIFIED Requirements

### Requirement: Local GPU transcription, input only
The system MUST run a `whisper` sidecar service using `faster-whisper` (via the `speaches` OpenAI-compatible server) on GPU to transcribe incoming Telegram voice notes into text fed to the agent. The system MUST NOT provide voice output (TTS).
(Previously: sidecar was `onerahmet/openai-whisper-asr-webservice`, custom `/asr` endpoint; now `speaches` on the OpenAI-compatible `/v1/audio/transcriptions` contract, same engine family.)

#### Scenario: Voice note gym log
- GIVEN the user sends a voice note describing a gym set
- WHEN the `whisper` service transcribes it
- THEN the resulting text is injected into the agent session and logged via `vida.py gym log`

#### Scenario: GPU unavailable degrades gracefully
- GIVEN `nvidia-container-toolkit` is not configured on the host
- WHEN the stack is deployed
- THEN `hermes` and text-based flows MUST still function; only voice input is unavailable

## ADDED Requirements

### Requirement: Transcription request contract
`transcribe-voice.sh` MUST call `POST ${WHISPER_URL}/v1/audio/transcriptions` with the audio as multipart field `file` (not `audio_file`), against a `WHISPER_URL` whose effective value (via the `hermes` service env) resolves to `http://whisper:8000`.

#### Scenario: Successful multipart request
- GIVEN `whisper` is healthy and reachable at `http://whisper:8000`
- WHEN `transcribe-voice.sh` posts the audio file as multipart field `file` to `/v1/audio/transcriptions`
- THEN the request MUST NOT fail due to a missing/misnamed multipart field

### Requirement: Response contract stability
The JSON response from `whisper` MUST contain a top-level `"text"` field, and `transcribe-voice.sh` MUST continue parsing it via `payload.get("text")` into the existing `ok/error` envelope, unchanged from the caller's (`skills/entrada-voz/SKILL.md`) perspective.

#### Scenario: Skill contract unchanged
- GIVEN a successful transcription response containing `"text"`
- WHEN `transcribe-voice.sh` parses it
- THEN it emits the same `ok/error` JSON shape as before the backend swap
- AND `skills/entrada-voz/SKILL.md` requires no behavioral changes to consume it

### Requirement: Graceful degradation on whisper failure
`transcribe-voice.sh` MUST exit 1 with `codigo: whisper_no_disponible` (or the existing equivalent) when `whisper` is unreachable, times out, or returns an error — and MUST NOT retry indefinitely or silently drop the voice note.

#### Scenario: Whisper service down
- GIVEN `whisper` is stopped or unreachable
- WHEN a Telegram voice note triggers `transcribe-voice.sh`
- THEN the script exits 1 with `codigo: whisper_no_disponible`
- AND `skills/entrada-voz/SKILL.md` asks the user to type the message instead

### Requirement: Model residency at startup
The `whisper` container MUST load `Systran/faster-whisper-large-v3` via `PRELOAD_MODELS` at startup, without requiring any prior transcription request.

#### Scenario: Model loaded before first request
- GIVEN the `whisper` container has just finished its healthcheck startup grace period
- WHEN `GET /api/ps` is queried with zero prior transcription requests
- THEN `Systran/faster-whisper-large-v3` appears as loaded

### Requirement: No idle unload of the resident model
`STT_MODEL_TTL` MUST be configured so the model is never unloaded due to inactivity (disabled or a very high value).

#### Scenario: Model survives long idle period
- GIVEN the model has been loaded and no transcription request has occurred for over 10 minutes
- WHEN `GET /api/ps` is queried
- THEN `Systran/faster-whisper-large-v3` still appears as loaded

### Requirement: Healthcheck via plain curl
`whisper`'s compose healthcheck MUST use `curl -fsS http://localhost:8000/health` and return HTTP 200, gating `hermes`'s `depends_on: whisper condition: service_healthy` correctly.

#### Scenario: Compose healthcheck passes
- GIVEN the `whisper` container has started and the model preload has completed within `start_period`
- WHEN Docker Compose runs the healthcheck
- THEN it returns HTTP 200 via plain `curl`, no `python3 urllib` workaround needed

### Requirement: Precision parity
Transcription MUST use `Systran/faster-whisper-large-v3` unquantized with `compute_type=float16` — no distilled or quantized variant — so output text does not regress vs. the current `onerahmet` backend for the same input audio.

#### Scenario: Same audio, same model family
- GIVEN a Telegram voice note previously transcribed by the `onerahmet` backend
- WHEN the same audio is transcribed by the `speaches` backend
- THEN the resulting text MUST NOT show a precision regression attributable to model or quantization change

### Requirement: Cache persistence across recreation
The model cache volume MUST be mounted at the correct HuggingFace cache path inside the `speaches` container so `Systran/faster-whisper-large-v3` is not re-downloaded across `docker compose down && up`.

#### Scenario: Restart does not re-download
- GIVEN `whisper-cache` has already downloaded `Systran/faster-whisper-large-v3` on first boot
- WHEN `docker compose down && docker compose up -d whisper` runs
- THEN the container reaches `healthy` within the normal `start_period`, without re-downloading the model

### Requirement: Blocking verifications before apply is considered done
`sdd-apply` and `sdd-verify` MUST NOT mark this change complete until each of the following is confirmed against a live `speaches` container, per the proposal's blocking-verification list:
- **V1**: the real HuggingFace cache directory inside the `speaches` image, mounted correctly (see Cache persistence requirement above).
- **V2**: the exact `STT_MODEL_TTL` sentinel/value that prevents unload, confirmed via `/api/ps` after exceeding the old 300s default.
- **V3**: whether `model` is a required multipart field on `/v1/audio/transcriptions`; if required, `transcribe-voice.sh` MUST send `-F "model=Systran/faster-whisper-large-v3"`.
- **V4**: an end-to-end real Telegram voice note transcribed correctly, with output text compared against the previous backend.

#### Scenario: Apply blocked on unresolved verification
- GIVEN V1, V2, V3, or V4 has not been confirmed against a live container
- WHEN `sdd-verify` runs
- THEN it MUST report the change as incomplete rather than pass silently

#### Scenario: All verifications confirmed
- GIVEN V1-V4 are each confirmed with live evidence (cache path, TTL sentinel, `model` field behavior, real voice-note transcription)
- WHEN `sdd-verify` runs
- THEN it MAY report this capability's verification criteria as satisfied
