#!/usr/bin/env sh
set -eu

exec vllm serve Qwen/Qwen2.5-14B-Instruct \
  --revision cf98f3b3bbb457ad9e2bb7baf9a0125b6b88caa8 \
  --dtype bfloat16 \
  --host "${HOST:-127.0.0.1}" \
  --port "${PORT:-8000}" \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 4
