#!/usr/bin/env bash
# Keep the example entry point aligned with the Qwen3-Coder recipe.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/../../ptc_training_recipe/rl/train_megatron_qwen3_coder.sh" "$@"
