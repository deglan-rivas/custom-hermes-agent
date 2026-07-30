#!/bin/sh
# Group 4, task 4.1 (design.md §14 F0.2): verify GPU visibility inside a container
# before bringing up the `whisper` service.
#
# Run this ON THE HOST (labia03), not in CI/sandbox -- it requires the real GPU,
# nvidia-container-toolkit and Docker's nvidia runtime, none of which exist outside
# the target machine.
#
# Exit 0 + prints `nvidia-smi` output  -> GPU is visible to Docker; safe to run
#                                         `docker compose up -d whisper` (tasks 4.2-4.4).
# Exit 1                               -> GPU not visible or docker/toolkit missing;
#                                         set WHISPER_OPTIONAL=1 in ops/.env.ops and skip
#                                         tasks 4.2-4.4 (spec §4: GPU unavailable degrades
#                                         gracefully, does not block the rest of Fase 1).

set -u

if ! command -v docker >/dev/null 2>&1; then
  echo "verify-gpu.sh: docker no encontrado en PATH" >&2
  exit 1
fi

docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
