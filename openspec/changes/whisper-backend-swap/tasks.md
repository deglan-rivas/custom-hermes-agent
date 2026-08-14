# Tasks: `whisper-backend-swap`

Inputs: `proposal.md`, `spec.md`, `design.md` (all approved — do not re-litigate).
Execution order below is sequential unless marked `[parallel-ok]`. Each task references the spec requirement it satisfies and the exact design.md section its commands/values come from.

**Decision locked here (design §5.2 open item, resolved):** use a **new named volume `speaches-cache`**, not a reused `whisper-cache` path. Rationale: the old `whisper-cache` volume stays untouched (legacy `onerahmet` cache format under `/root/.cache`), which is what makes the rollback plan's "keep old cache warm" guarantee actually true instead of accidental. Cost is one extra line in the top-level `volumes:` block. This mirrors design.md §5.2's own recommendation.

---

## Phase 0 — Live verification against a throwaway probe container

None of these touch `docker-compose.yml` or the real stack. All commands are copied verbatim from design.md §6; do not improvise variants.

- [x] **T1. Launch the probe container** (design §6, "Setup común")
  Satisfies: spec "Blocking verifications before apply is considered done" (V1-V3 gate).
  ```sh
  docker run -d --rm --name speaches-probe --gpus all -p 8000:8000 \
    -e WHISPER__INFERENCE_DEVICE=cuda \
    -e WHISPER__COMPUTE_TYPE=float16 \
    -e PRELOAD_MODELS='["Systran/faster-whisper-large-v3"]' \
    -e STT_MODEL_TTL=-1 \
    ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cuda-12.6.3

  docker logs -f speaches-probe          # wait for download/preload to finish
  curl -fsS http://localhost:8000/health # expected: {"message":"OK"}
  ```
  If the container crashes on boot: suspect #1 is `PRELOAD_MODELS` JSON-array format (ADR-2), suspect #2 is `STT_MODEL_TTL` value. Read the crash log before touching anything else.

- [x] **T2. V1 — confirm the real HuggingFace cache path** (design §6.1) — CONFIRMED: `/home/ubuntu/.cache/huggingface/hub`, exactly matches design's best-known value. No deviation.
  Satisfies: spec "Cache persistence across recreation".
  ```sh
  docker exec speaches-probe sh -c 'find / -type d -name "models--Systran--faster-whisper-large-v3" 2>/dev/null'
  docker exec speaches-probe sh -c 'id; echo "HOME=$HOME"; env | grep -i -E "^(HF_|HUGGINGFACE|XDG_CACHE)"'
  ```
  Expected: path ends in `.../huggingface/hub/models--Systran--faster-whisper-large-v3`. The prefix before `hub/` is the mount target for `speaches-cache` in T5.
  If it does NOT match `/home/ubuntu/.cache/huggingface/hub`: use the real path found here instead of the design's best-known value, and record the deviation in the commit message / apply-progress notes.

- [x] **T3. V1b — confirm `curl` exists inside the image** (design §6.1b, ADR-3) — CONFIRMED: `/usr/bin/curl` present, `curl -fsS http://localhost:8000/health` returns `{"message":"OK"}` from inside the container. No fallback needed.
  Satisfies: spec "Healthcheck via plain curl".
  ```sh
  docker exec speaches-probe sh -c 'command -v curl || echo NO-CURL'
  docker exec speaches-probe sh -c 'curl -fsS http://localhost:8000/health'
  ```
  If `NO-CURL`: run the fallback probes below, in order, and use the first one that works. Do NOT assume `curl` — this is literally the class of bug documented in `TROUBLESHOOTING.md §3`.
  ```sh
  docker exec speaches-probe sh -c 'command -v wget'
  docker exec speaches-probe sh -c 'command -v python3'
  ```
  Pre-written fallback healthcheck blocks (use only if `curl` is confirmed absent):
  ```yaml
  # fallback A - wget
  test: ["CMD-SHELL", "wget -qO- http://localhost:8000/health >/dev/null || exit 1"]
  # fallback B - python3
  test: ["CMD-SHELL", "python3 -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=5).status==200 else 1)\""]
  ```

- [x] **T4. V2b — confirm `PRELOAD_MODELS` actually loaded the model** (design §6.2, ADR-2) — PARTIAL / DEVIATION FOUND: JSON-array format was accepted (no crash, `preload_models=['Systran/faster-whisper-large-v3']` in config log), and the model **was downloaded** to the cache path on startup ("Successfully downloaded model" in logs). However `/api/ps` returned `{"models":[]}` with zero prior transcription requests — `PRELOAD_MODELS` in this speaches version (0.9.0-rc.3) only pre-downloads to disk cache, it does **not** load the model into VRAM at startup. The model only loads into VRAM (and then appears in `/api/ps`) on the **first real transcription request**. Confirmed identically against both the probe container and the real deployed stack. This is a genuine deviation from the design/spec assumption of "model residency at startup with zero prior requests" — see apply-progress notes and risks.
  Satisfies: spec "Model residency at startup".
  ```sh
  curl -fsS http://localhost:8000/api/ps
  ```
  Expected: `Systran/faster-whisper-large-v3` present in `models`, with zero prior transcription requests.
  If `{"models":[]}` but the container booted fine: the JSON array was accepted but preload did not fire — check boot logs before trying a plain-string variant.

- [x] **T5. V2 — confirm `STT_MODEL_TTL=-1` means "never unload"** (design §6.2b) — the only check that requires waiting — CONFIRMED: after loading the model via one transcription request, `/api/ps` showed the model loaded at t=0 (23:53:19) and still loaded at t=11min (00:04:26) after a full `sleep 660` idle period with zero requests. `-1` sentinel works as designed. No fallback needed.
  Satisfies: spec "No idle unload of the resident model".
  ```sh
  # t=0: confirm loaded
  curl -fsS http://localhost:8000/api/ps

  # wait >10 minutes with zero requests (old default was 300s; 660s clears it with margin)
  sleep 660

  # t=11min: must still be loaded
  curl -fsS http://localhost:8000/api/ps
  ```
  Expected: model present in both outputs.
  If it disappeared in the second call: `-1` is not a valid sentinel — switch to `STT_MODEL_TTL: "31536000"` with an explicit "stand-in for never" comment in the compose file, relaunch the probe (repeat T1), and **repeat this entire 11-minute check** before proceeding. Do not accept the large-value fallback without re-verifying it lives up to the same guarantee.

- [x] **T6. V3 — confirm the `model` multipart field behavior** (design §6.3, ADR-1 — confirmation only, not a blocker) — CONFIRMED: (a) WITH `model` → HTTP 200, non-empty `text` field (synthetic sine-tone audio, no TTS available in sandbox — server hallucinated `"Thank you."`, mechanically confirms the field/parsing contract). (b) WITHOUT `model` → HTTP 422, `{"detail":[{"type":"missing","loc":["body","model"],"msg":"Field required"...}]}`. **`model` is a required field on this endpoint** — validates ADR-1's decision to always send it unconditionally.
  Satisfies: spec "Transcription request contract" (documents field name/behavior).
  Requires a short real audio file at hand (e.g. `/tmp/probe.ogg`, ideally exported from a Telegram voice note).
  ```sh
  # (a) WITH model — this is the form the script will always use
  curl -sS -o /tmp/con-model.json -w '%{http_code}\n' \
    -F "file=@/tmp/probe.ogg" \
    -F "model=Systran/faster-whisper-large-v3" \
    http://localhost:8000/v1/audio/transcriptions
  cat /tmp/con-model.json

  # (b) WITHOUT model — documentation only
  curl -sS -o /tmp/sin-model.json -w '%{http_code}\n' \
    -F "file=@/tmp/probe.ogg" \
    http://localhost:8000/v1/audio/transcriptions
  cat /tmp/sin-model.json
  ```
  Expected (a): HTTP 200, non-empty `text` field — this is the real blocking check (if it fails, the script cannot work regardless of ADR-1). Expected (b): 200 or 422, either acceptable, record which one for the spec/tasks trail.

- [x] **T7. Teardown the probe** [parallel-ok with nothing — do last in Phase 0] — done, `docker stop speaches-probe` (auto-removed via `--rm`).
  ```sh
  docker stop speaches-probe    # --rm cleans up the container
  ```

---

## Phase 1 — `docker-compose.yml` edits

Sequential; both edits below MUST land in the **same commit** as Phase 2 (design §3, §5.1 — atomic rollback requirement). Apply the T2/T3/T5 findings from Phase 0 before writing the final block (i.e. do not paste the design.md block blindly if verification revealed a different cache path, healthcheck fallback, or TTL value).

- [x] **T8. Add `speaches-cache` to the top-level `volumes:` block**, keep `whisper-cache` untouched (legacy, kept warm for rollback per design §5.2).
  ```yaml
  volumes:
    whisper-cache:        # legacy (onerahmet image) - keep until swap is validated stable
    speaches-cache:       # new backend
  ```

- [x] **T9. Replace the `whisper` service block** (design.md §1) with the config below, substituting any Phase 0 deviations (cache path from T2, healthcheck test from T3, `STT_MODEL_TTL` value from T5): — applied verbatim, no deviations needed (T2/T3/T5 all matched design's best-known values).
  ```yaml
    whisper:
      image: ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cuda-12.6.3
      container_name: whisper
      restart: unless-stopped
      environment:
        TZ: America/Lima
        WHISPER__INFERENCE_DEVICE: cuda
        WHISPER__COMPUTE_TYPE: float16
        # JSON array required: pydantic-settings parses list[str] as JSON (design ADR-2).
        # This id also lives in ops/transcribe-voice.sh (-F model=...). Change both together.
        PRELOAD_MODELS: '["Systran/faster-whisper-large-v3"]'
        STT_MODEL_TTL: "-1"              # -1 = never unload. Replaces MODEL_IDLE_TIMEOUT=600.
      volumes:
        - speaches-cache:/home/ubuntu/.cache/huggingface/hub   # confirm path against T2
      deploy:
        resources:
          reservations:
            devices:
              - driver: nvidia
                count: 1
                capabilities: [gpu]
      healthcheck:
        test: ["CMD-SHELL", "curl -fsS http://localhost:8000/health >/dev/null || exit 1"]
        interval: 60s
        timeout: 10s
        retries: 3
        start_period: 1800s              # first boot: full large-v3 download (~3GB) + VRAM load
      logging: *log
      networks: [asistente]
      # no `ports:` - internal compose network only
  ```
  Satisfies: spec "Model residency at startup", "No idle unload of the resident model", "Healthcheck via plain curl", "Precision parity", "Cache persistence across recreation".

- [x] **T10. Update the `hermes` service `WHISPER_URL` env var** (design §3 — "the real switch")
  ```diff
       environment:
         TZ: America/Lima
         VIDA_DB: /opt/data/data/vida.db
  -      WHISPER_URL: http://whisper:9000
  +      WHISPER_URL: http://whisper:8000
  ```
  Satisfies: spec "Transcription request contract" (effective `WHISPER_URL` resolution).
  Note (do not skip): this line overrides the script's own default at runtime — T10 and T9 must ship together with Phase 2, never split across commits (design §3, §5.1).

---

## Phase 2 — `ops/transcribe-voice.sh` edits

Sequential, same commit as Phase 1. Diff is exactly 5 functional lines (design §3.5) — do not touch the response-parsing block or the error `codigo` list.

- [x] **T11. Update the `WHISPER_URL` default** (design §3.5a)
  ```diff
  -WHISPER_URL="${WHISPER_URL:-http://whisper:9000}"
  +WHISPER_URL="${WHISPER_URL:-http://whisper:8000}"
  ```

- [x] **T12. Add the `WHISPER_MODEL` constant** near `ACTION` (design §3.5b, ADR-5)
  ```diff
   AUDIO_FILE="${1:-}"
   ACTION="asr.transcribe"
  +# Must match PRELOAD_MODELS in docker-compose.yml (whisper service).
  +WHISPER_MODEL="${WHISPER_MODEL:-Systran/faster-whisper-large-v3}"
  ```

- [x] **T13. Update the curl call** (design §3.5c, ADR-1 — `model` sent unconditionally)
  ```diff
  -RESPUESTA="$(curl -fsS --max-time 30 \
  -  -F "audio_file=@${AUDIO_FILE}" \
  -  "${WHISPER_URL}/asr?output=json" 2>/dev/null)" || {
  -  fail "whisper_no_disponible" "no se pudo contactar ${WHISPER_URL}/asr (servicio caido, timeout, o F0.2/whisper aun no desplegado -- ver ops/verify-gpu.sh)"
  -}
  +RESPUESTA="$(curl -fsS --max-time 30 \
  +  -F "file=@${AUDIO_FILE}" \
  +  -F "model=${WHISPER_MODEL}" \
  +  "${WHISPER_URL}/v1/audio/transcriptions" 2>/dev/null)" || {
  +  fail "whisper_no_disponible" "no se pudo contactar ${WHISPER_URL}/v1/audio/transcriptions (servicio caido, timeout, o F0.2/whisper aun no desplegado -- ver ops/verify-gpu.sh)"
  +}
  ```
  Keep `--max-time 30` unchanged (design treats it as a TTL canary, not a tunable — do not raise it even if T5 revealed the TTL is flaky; that's a signal to re-check T5, not to loosen the timeout).

- [x] **T14. Update header comments** (design §3.5d, lines 2 and 8)
  ```diff
  -# Transcribe a Telegram voice note via the whisper sidecar's POST /asr endpoint.
  +# Transcribe a Telegram voice note via the whisper sidecar's OpenAI-compatible
  +# POST /v1/audio/transcriptions endpoint (speaches-ai/speaches backend).
  ```
  ```diff
  -# skills/entrada-voz/SKILL.md for the full rationale. Both alternatives land on this
  -# same POST /asr contract (design §15), so nothing here changes if a native hook is
  -# confirmed later.
  +# skills/entrada-voz/SKILL.md for the full rationale. Both alternatives land on this
  +# same POST /v1/audio/transcriptions contract (design §15), so nothing here changes if
  +# a native hook is confirmed later.
  ```
  Satisfies (T11-T14): spec "Transcription request contract", "Response contract stability" (verify unchanged by inspection — no edit needed), "Graceful degradation on whisper failure" (verify unchanged by inspection).

- [x] **T15. Confirm by inspection — do NOT edit — that the response-parsing block and error `codigo` list are untouched**: `payload.get("text")`, and `argumento_faltante` / `archivo_no_encontrado` / `curl_no_disponible` / `python3_no_disponible` / `whisper_no_disponible` / `respuesta_invalida` / `transcripcion_vacia`. — confirmed unchanged by inspection.

---

## Phase 3 — Docs (cosmetic, single task) `[parallel-ok with nothing else — do after Phase 1/2, can be its own commit per design §5.1]`

- [x] **T16. Update prose references to the old port/endpoint** in:
  - `skills/entrada-voz/SKILL.md` (~lines 12, 35): `whisper:9000` / `/asr` → `whisper:8000` / `/v1/audio/transcriptions`.
  - `ops/SECURITY-GROUP6.md` (~lines 54-56): same substitution.
  - `TROUBLESHOOTING.md §3`: **annotate** (do not delete) as specific to the retired `onerahmet` image — it's a historical record, still valid for anyone who reverts.
  Satisfies: spec "Response contract stability" / "Healthcheck via plain curl" (docs consistency, no behavioral requirement).

---

## Phase 4 — Bring up the real stack (last automatable task)

- [x] **T17. Two-stage deploy** (design §4.4, ADR-4 — first boot only; later boots can use one-shot `docker compose up -d`) — `docker compose up -d whisper` reached healthy in ~5 min (first-boot download to the new `speaches-cache` volume), then `docker compose up -d hermes` came up healthy immediately after.
  ```sh
  # 1. Bring up whisper alone, let it download/load the model
  docker compose up -d whisper
  docker compose logs -f whisper
  docker inspect --format '{{.State.Health.Status}}' whisper   # wait for "healthy"

  # 2. Only then recreate hermes with the new WHISPER_URL
  docker compose up -d hermes
  ```
- [x] **T18. Post-deploy verification against the real stack** (design §6.4) — all sub-checks confirmed:
  - `whisper` and `hermes` both `healthy`.
  - `hermes` sees `WHISPER_URL=http://whisper:8000` (correct).
  - Graceful degradation: with `whisper` stopped, `transcribe-voice.sh` exited 1 with `{"ok": false, ..., "codigo": "whisper_no_disponible"}` exactly as designed.
  - Success path: with `whisper` running and the model warm, `transcribe-voice.sh` returned `{"ok": true, "action": "asr.transcribe", "data": {"texto": "..."}}`, exit 0.
  - Cache persistence: `docker compose down whisper && up -d whisper` reached `healthy` in ~10s (2 poll iterations), logs showed `Fetching 6 files: 100%` in under 1 second with **no HuggingFace network download** — cache hit confirmed, no re-download.
  - **IMPORTANT FINDING** (also logged under T4): the first transcription request after any fresh `whisper` container start took long enough to blow past `transcribe-voice.sh`'s `--max-time 30` (client-side timeout at 30s, `curl: (28) Operation timed out`), because the model was not yet in VRAM despite `PRELOAD_MODELS` and despite the container already being `healthy`. The *second* request (model now warm) succeeded normally. This means: **every real container recreation (deploy, restart, host reboot) will make the first voice note after it fail with the graceful `whisper_no_disponible` message**, not silently, but it does mean "zero cold-load penalty" from the proposal's success criteria is not fully achieved — the cold load moved from "per 10-minute idle window" (old backend) to "per container lifecycle" (new backend), which is still a large improvement but not literally zero. See apply-progress and risks for the full write-up.
  ```sh
  docker inspect --format '{{.State.Health.Status}}' whisper
  docker compose exec whisper curl -fsS http://localhost:8000/api/ps
  docker compose exec hermes printenv WHISPER_URL      # expected: http://whisper:8000

  # Graceful degradation still intact
  docker compose stop whisper
  docker compose exec hermes /opt/data/ops/transcribe-voice.sh /opt/data/ops/<test-audio>
  #   expected: exit 1 + {"ok": false, ..., "codigo": "whisper_no_disponible"}
  docker compose start whisper

  # Cache persists across recreation
  docker compose down && docker compose up -d whisper
  docker compose logs whisper | grep -i -E "download|fetch"   # expected: no large-v3 download
  #   and the container should reach healthy on ~1 check, not in 15 minutes
  ```
  Satisfies: spec "Graceful degradation on whisper failure", "Cache persistence across recreation".

---

## Phase 5 — USER ACTION (manual, not sdd-apply's job)

- [ ] **T19. [USER ACTION — requires a real Telegram client, sdd-apply CANNOT perform this]** — STATUS: NOT DONE, blocked on user. The stack is deployed and healthy (T17/T18 done); everything up to this point that is automatable has been verified live. This is the only remaining task and it requires a human sending a real Telegram voice note from their phone. Final acceptance gate (design §7, spec "Blocking verifications before apply is considered done" V4).
  1. Send a real Telegram voice note. Confirm: it transcribes, the assistant responds to the content (not the "type your message" fallback), and the text matches what the old backend would have produced, with no long cold-load pause.
  2. Wait **more than 10 minutes** idle, then send a **second** voice note. Confirm it responds just as fast as the first — this is the only proof that the disabled TTL (`STT_MODEL_TTL=-1`) actually holds up end-to-end, not just at the API level (T5 only proved it at the API level).
  If (1) fails on transcription or accuracy → roll back per design §5 and reopen the design. If only latency (3) or the idle-survival (4) criteria fail but transcription itself works → investigate `/api/ps` and logs before deciding on a revert; voice is still functionally up, this is not an emergency.
  Instrumentation while testing: `docker compose logs -f --tail 50 whisper hermes`.

---

## Review Workload Forecast

- **Files touched**: 2 code files (`docker-compose.yml`, `ops/transcribe-voice.sh`) + 3 doc files (`skills/entrada-voz/SKILL.md`, `ops/SECURITY-GROUP6.md`, `TROUBLESHOOTING.md`).
- **Estimated changed lines**: `docker-compose.yml` ~35 lines (full `whisper` service block replacement + 1-line `hermes` env change + 1-line volume declaration); `transcribe-voice.sh` ~12 lines (5 functional lines per design §3.5, plus comment lines); docs ~10-15 lines combined (prose only). **Total estimate: ~60-65 changed lines.**
- **Chained PRs recommended**: No.
- **400-line budget risk**: Low. Even generously padded, this stays well under half the 400-line budget in a single PR.
- **Decision needed before apply**: No — `delivery_strategy: ask-on-risk` does not need to trigger; this can proceed as a single PR/commit per design §5.1's atomic-rollback requirement (compose + script together; docs may be a separate small commit within the same PR).

---

## Ordering summary for `sdd-apply`

1. Phase 0 (T1-T7) — probe verification, no repo changes.
2. Phase 1 + Phase 2 (T8-T15) — same commit, compose + script together (rollback atomicity).
3. Phase 3 (T16) — docs, can be a separate commit in the same PR.
4. Phase 4 (T17-T18) — bring up real stack, verify.
5. Phase 5 (T19) — hand control back to the user. `sdd-apply` and `sdd-verify` must not mark this change fully complete until the user confirms T19.
