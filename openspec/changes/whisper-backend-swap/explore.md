## Exploration: whisper-backend-swap — replace slow onerahmet whisper image

### Current State
`asistente_personal/docker-compose.yml` runs `whisper` as `onerahmet/openai-whisper-asr-webservice:latest-gpu` (~10GB), `ASR_ENGINE=faster_whisper`, `ASR_MODEL=large-v3`, `ASR_DEVICE=cuda`, `ASR_COMPUTE_TYPE=float16`, `MODEL_IDLE_TIMEOUT=600`, GPU reservation via `deploy.resources.reservations.devices` (nvidia), healthcheck via `python3 urllib` against `/docs` (image has no curl — documented incident, `TROUBLESHOOTING.md` §3), volume `whisper-cache:/root/.cache`, no published ports (internal `asistente` network only). Consumer is `asistente_personal/ops/transcribe-voice.sh`: `curl -F "audio_file=@FILE" "${WHISPER_URL}/asr?output=json"`, parses top-level `"text"` field, wraps in the ok/error JSON contract consumed by `skills/entrada-voz/SKILL.md`. `WHISPER_URL` defaults to `http://whisper:9000`.

### Affected Areas
- `asistente_personal/docker-compose.yml` — `whisper` service block: image, environment, healthcheck endpoint, volume mount path.
- `asistente_personal/ops/transcribe-voice.sh` — endpoint path, multipart field name, `WHISPER_URL` default port.
- `asistente_personal/skills/entrada-voz/SKILL.md` lines 12, 35 — prose references `whisper:9000` / `/asr` (cosmetic, script owns real behavior).
- `asistente_personal/ops/SECURITY-GROUP6.md` lines 54-56 — same, cosmetic.
- `asistente_personal/TROUBLESHOOTING.md` §3 — historical record of the onerahmet curl-missing incident; keep, optionally annotate as image-specific.
- Not affected: `README.md`, `ops/verify-gpu.sh`, `ops/check-stack.sh`, `ops/env.ops.template.txt` — reference the `whisper` service/container name (unchanged) or GPU verification generically.

### Findings — verifying the two candidates

**1. speaches-ai/speaches (ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cuda-12.6.3)**
- OpenAI-compatible: `POST /v1/audio/transcriptions`, multipart field **`file`** (not `audio_file` — required script change).
- Default port **8000**, not 9000 (project formerly `faster-whisper-server`, renamed `speaches`).
- Same CTranslate2/faster-whisper engine family as current onerahmet image — `float16` + `large-v3` unquantized achievable, same precision path as today.
- Env scheme: nested double-underscore config (`WHISPER__INFERENCE_DEVICE=cuda`, `WHISPER__COMPUTE_TYPE=float16`). Model selection may be per-request (OpenAI-style `model` field) rather than a single fixed env var — **not fully confirmed**, needs a live check against `/openapi.json`.
- Idle-unload analog confirmed: **`STT_MODEL_TTL`** (seconds until model unload after last use, default 300) — direct replacement for `MODEL_IDLE_TIMEOUT`.
- **Batched-inference speed claim: partially unverified.** faster-whisper's `BatchedInferencePipeline` gives large throughput gains, but that's for many/long segments processed together. Telegram voice notes are short, single-file, single-user requests — little to batch. Cannot confirm speaches batch-decodes a single short file by default. **Don't oversell "faster via batching" to the user** — the real, verified wins are: same-precision engine, OpenAI-compatible contract, smaller image, native idle-unload.
- Healthcheck endpoint not confirmed; FastAPI/uvicorn app almost certainly exposes `/health` or `/docs`/`/openapi.json`, but must be verified live before locking the compose healthcheck (same failure class as the documented onerahmet incident).

**2. whisper.cpp (ghcr.io/ggml-org/whisper.cpp:main-cuda-<sha>)**
- HTTP server exposes `POST /inference`, multipart fields `file`, `temperature`, `response_format` — different, non-OpenAI-compatible contract, larger diff for `transcribe-voice.sh`.
- Precision: unquantized f16 GGML models exist (e.g. `ggml-large-v3.bin`) alongside quantized (q5_0/q8_0) — "always loses precision" is not strictly true, user could pick f16. But running unquantized large-v3 on whisper.cpp's CUDA path is not an established "faster than CTranslate2" configuration; CTranslate2/faster-whisper is the more mature path for batch=1 GPU decode at fp16. Quantization isn't forced, but it's the only path that plays to this image's strengths.
- Cache format incompatible with current `whisper-cache` volume either way (raw `.bin` files vs onerahmet's HF/CTranslate2 model dir) — fresh volume needed regardless of which candidate is chosen.

**Third option check:** speaches-ai/speaches is already the maintained successor to `fedirz/faster-whisper-server` — no better-maintained variant found in this family. Not widened further, out of scope.

### Recommendation
**speaches-ai/speaches confirmed as the better fit**, with one correction to the original framing: don't lean on "batched inference speed" as the mechanism — unverified whether it helps a single short voice note per request. The stronger, verified reasons:
1. Same CTranslate2/faster-whisper engine and precision path (float16, unquantized large-v3) — genuinely "little to no precision loss."
2. OpenAI-compatible REST contract, well-documented, low integration risk.
3. Native idle-unload (`STT_MODEL_TTL`) analogous to today's `MODEL_IDLE_TIMEOUT` — though worth reconsidering, not just porting 1:1 (see below).
4. Actively maintained, smaller image (~8.6GB vs ~10GB) — modest, not the primary win.

whisper.cpp not recommended as default: forces a real precision/tooling tradeoff (accept quantization, or run f16 and lose its speed edge) and needs a non-OpenAI-compatible contract with a larger blast radius on `transcribe-voice.sh` — for a GPU-headroom problem the user doesn't have (48GB, single user).

### Concrete config changes (for sdd-propose to scope)

**`docker-compose.yml`, `whisper` service:**
- `image`: `onerahmet/openai-whisper-asr-webservice:latest-gpu` → `ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cuda-12.6.3`
- `environment`: replace `ASR_ENGINE`/`ASR_MODEL`/`ASR_DEVICE`/`ASR_COMPUTE_TYPE`/`MODEL_IDLE_TIMEOUT` with `WHISPER__INFERENCE_DEVICE=cuda`, `WHISPER__COMPUTE_TYPE=float16`, `STT_MODEL_TTL=<value, revisit>`, `PRELOAD_MODELS=<exact HF model id, unconfirmed>`.
- `volumes`: `whisper-cache:/root/.cache` → likely `whisper-cache:/home/ubuntu/.cache/huggingface/hub` (path partially confirmed, verify against live container — cache format differs from onerahmet, treat as fresh volume).
- `deploy.resources.reservations.devices`: unchanged.
- `healthcheck`: needs a confirmed working endpoint on a live container, don't assume `/docs`.
- `container_name: whisper`: keep — referenced by name elsewhere, not by image.

**`ops/transcribe-voice.sh`:**
- `WHISPER_URL` default: `http://whisper:9000` → `http://whisper:8000`.
- curl call: `-F "audio_file=@${AUDIO_FILE}" "${WHISPER_URL}/asr?output=json"` → `-F "file=@${AUDIO_FILE}" "${WHISPER_URL}/v1/audio/transcriptions"`.
- Response parsing: script already only reads `payload.get("text")` — if speaches' default response includes top-level `"text"` (very likely, matches OpenAI shape), no parsing change needed. **Verify with one live curl test** before merging — the whole ok/error contract for `entrada-voz` depends on this field matching.

**Docs to update (cosmetic, no functional coupling):** `skills/entrada-voz/SKILL.md` (lines 12, 35), `ops/SECURITY-GROUP6.md` (lines 54-56) — update port/endpoint mentions. `TROUBLESHOOTING.md` §3 — optionally annotate as onerahmet-specific.

### Risks
- Model ID/preload string for speaches unconfirmed — must verify live (`/openapi.json`) before finalizing compose env.
- Cache volume not reusable as-is for either candidate — expect fresh model download on first boot (adjust `start_period`).
- Healthcheck endpoint unverified — same failure class as the documented onerahmet curl-missing incident.
- Response field-name assumption (`"text"`) for `/v1/audio/transcriptions` not live-tested.
- Batching speed benefit likely overstated for this workload (single short files, not concurrent/long batch jobs) — don't oversell to user.
- **Idle-unload value worth reconsidering, not porting 1:1.** With 48GB VRAM mostly free and single user, keeping large-v3 resident (raising/disabling `STT_MODEL_TTL`) may fix "slow to respond" more directly than the backend swap itself, since cold-reload after idle timeout could be the actual latency source today.
- Rollback: same container name, same JSON-with-`text` response shape family — single-line image/env revert if speaches underperforms or blockers surface.

### Live verification (done — container run locally, 2026-08-13)
Ran `ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cuda-12.6.3` directly (`docker run -d --rm --gpus all -p 8000:8000 ...`), confirmed via `/health`, `/openapi.json`, `/v1/models`, `/v1/registry`, `/api/ps`:
- `GET /health` → `{"message":"OK"}`, HTTP 200 — **use this as the compose healthcheck**, no curl-missing risk like onerahmet (confirmed image responds to plain `curl`, not just python3/urllib).
- `GET /docs` → HTTP 200 (FastAPI/Swagger present).
- Model registry confirms exact model id: **`Systran/faster-whisper-large-v3`** (also `Systran/faster-distil-whisper-large-v3` available as a faster/lower-fidelity alternative — not chosen, user wants minimal precision loss).
- `/v1/audio/transcriptions` response schema (from `components.schemas.Transcription` in the live OpenAPI doc): `required: ["text"]`, i.e. **`text` is guaranteed present in the response — `transcribe-voice.sh`'s existing `payload.get("text")` parsing needs zero changes**, confirming the endpoint/field-name swap is the only required script edit.
- No models loaded by default (`/api/ps` → `{"models":[]}`) — confirms `PRELOAD_MODELS=Systran/faster-whisper-large-v3` (or equivalent startup pull) is required in compose, otherwise first request pays cold-load latency.
- Container cleaned up after check (`docker stop`), no leftover state.

Both open questions resolved:
1. **Model id**: `Systran/faster-whisper-large-v3` (confirmed live) — use as `PRELOAD_MODELS` value.
2. **`STT_MODEL_TTL`**: still a user decision, not a technical unknown — proposal should present both options (parity ~600s vs. raise/disable given 48GB free VRAM) rather than silently picking one.

**Next**: sdd-propose.
