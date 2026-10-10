#!/bin/bash
# Megatron SFT for Qwen3-8B (dense)
# Usage: bash ptc_training_recipe/sft/sft_qwen3_8b.sh [--model_path ...] [--data_path ...] [--output_dir ...]
#
# Prepare the official model first:
#   python ptc_training_recipe/prepare_qwen3.py --model /path/to/Qwen3-8B

set -euo pipefail

# ==============================================================================
# Parse command line arguments
# ==============================================================================
data_paths=()
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --model_path) model_path="$2"; shift 2 ;;
        --data_path) data_paths+=("$2"); shift 2 ;;
        --output_dir) output_dir="$2"; shift 2 ;;
        --) shift; break ;;
        *) break ;;
    esac
done

# ==============================================================================
# Configuration
# ==============================================================================
CUDA_DEVICES=${CUDA_DEVICES:-0,1,2,3,4,5,6,7}
model_path=${model_path:?Pass --model_path /path/to/model}
if [ ${#data_paths[@]} -eq 0 ]; then
    echo "ERROR: pass at least one --data_path /path/to/data.jsonl" >&2
    exit 1
fi
output_dir=${output_dir:?Pass --output_dir /path/to/checkpoint}

# NCCL settings
export NCCL_NVLS_ENABLE=${NCCL_NVLS_ENABLE:-0}

echo "=== Megatron SFT Training (Qwen3-8B Dense) ==="
echo "Model:   $model_path"
echo "Dataset: ${data_paths[@]}"
echo "Output:  $output_dir"
echo "=============================================="

# Match the Coder launcher: Swift builds torchrun from these environment variables.
NNODES=${NNODES:-1}
NODE_RANK=${NODE_RANK:-0}
MASTER_ADDR=${MASTER_ADDR:-127.0.0.1}
MASTER_PORT=${MASTER_PORT:-29500}
IFS=',' read -r -a devices <<< "$CUDA_DEVICES"
NPROC=${NPROC_PER_NODE:-${#devices[@]}}

PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True' \
CUDA_VISIBLE_DEVICES=$CUDA_DEVICES \
NPROC_PER_NODE=$NPROC \
NNODES=$NNODES \
NODE_RANK=$NODE_RANK \
MASTER_ADDR=$MASTER_ADDR \
MASTER_PORT=$MASTER_PORT \
megatron sft \
    --model "$model_path" \
    --dataset "${data_paths[@]}" \
    --agent_template qwen3_5 \
    --tensor_model_parallel_size 2 \
    --context_parallel_size 1 \
    --sequence_parallel true \
    --micro_batch_size 2 \
    --global_batch_size 64 \
    --num_train_epochs 3 \
    --finetune true \
    --tuner_type full \
    --lr 1e-5 \
    --lr_warmup_fraction 0.05 \
    --min_lr 2e-6 \
    --max_length 131072 \
    --save_safetensors true \
    --output_dir "$output_dir" \
    --save_steps 50 \
    --eval_steps 50 \
    --recompute_granularity full \
    --recompute_method uniform \
    --recompute_num_layers 1 \
    --cross_entropy_loss_fusion true \
    --attention_backend flash \
    --padding_free true \
    --packing false \
    --dataloader_num_workers 4 \
    --dataset_num_proc 4 \
    --no_save_optim true \
    --no_save_rng true \
    --use_distributed_optimizer true \
    "$@"
