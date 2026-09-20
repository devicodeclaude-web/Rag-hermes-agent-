#!/usr/bin/env sh
set -eu

MODEL_PATH=${MODEL_PATH:?Set MODEL_PATH to the downloaded GGUF file}
EXPECTED_SHA256=e47ad95dad6ff848b431053b375adb5d39321290ea2c638682577dafca87c008
ACTUAL_SHA256=$(sha256sum "$MODEL_PATH" | cut -d' ' -f1)
[ "$ACTUAL_SHA256" = "$EXPECTED_SHA256" ] || {
  printf 'GGUF checksum mismatch: %s\n' "$ACTUAL_SHA256" >&2
  exit 1
}

exec llama-server \
  --model "$MODEL_PATH" \
  --host "${HOST:-127.0.0.1}" \
  --port "${PORT:-8080}" \
  --ctx-size 8192 \
  --n-gpu-layers 99 \
  --parallel 1
