#!/usr/bin/env bash
# Run on every node with the same NNODES, NGPUS_PER_NODE, and MASTER_ADDR.
# NODE_RANK must be unique; rank 0 runs the training driver.
set -euo pipefail
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <train_script.sh> [args...]" >&2
    exit 1
fi
export NNODES=${NNODES:-1}
export NODE_RANK=${NODE_RANK:-0}
export NGPUS_PER_NODE=${NGPUS_PER_NODE:-8}
export MASTER_ADDR=${MASTER_ADDR:-127.0.0.1}
export MASTER_PORT=${MASTER_PORT:-6379}
export RAY_TIMEOUT=${RAY_TIMEOUT:-1000}
export VLLM_USE_FLASHINFER_MOE_FP16=${VLLM_USE_FLASHINFER_MOE_FP16:-0}
export HYDRA_FULL_ERROR=1

export RAY_ADDRESS="${MASTER_ADDR}:${MASTER_PORT}"
if [[ "$NODE_RANK" -ne 0 ]]; then
    deadline=$((SECONDS + RAY_TIMEOUT))
    until timeout 5 ray status --address="$RAY_ADDRESS" >/dev/null 2>&1; do
        if (( SECONDS >= deadline )); then
            echo "Timed out waiting for Ray head at $RAY_ADDRESS" >&2
            exit 1
        fi
        sleep 2
    done
    exec ray start --address="$RAY_ADDRESS" --num-gpus="$NGPUS_PER_NODE" \
        --disable-usage-stats --block
fi
ray start --head --port="$MASTER_PORT" --num-gpus="$NGPUS_PER_NODE" --disable-usage-stats
python3 - <<'PY'
import os
import time
import ray

ray.init(address=os.environ["RAY_ADDRESS"])
expected = int(os.environ["NNODES"])
deadline = time.monotonic() + int(os.environ["RAY_TIMEOUT"])
while sum(node["Alive"] for node in ray.nodes()) < expected:
    if time.monotonic() >= deadline:
        raise TimeoutError(f"Expected {expected} Ray nodes before starting training")
    time.sleep(2)
ray.shutdown()
PY
exec bash "$@"
