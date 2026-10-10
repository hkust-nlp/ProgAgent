#!/bin/bash
# Megatron SFT for Qwen3-Coder-30B-A3B-Instruct
# Usage: bash ptc_training_recipe/sft/sft_qwen3_coder.sh [--model_path /path/to/model] [--data_path /path/to/data.jsonl] [--output_dir /path/to/output]

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

# MoE fusion knobs — the new env's Megatron/TE build may not support all of
# them. Flip off individually without editing the script, e.g.:
#   MOE_PERMUTE_FUSION=false bash ptc_training_recipe/sft/sft_qwen3_coder.sh
MOE_PERMUTE_FUSION=${MOE_PERMUTE_FUSION:-true}
MOE_GROUPED_GEMM=${MOE_GROUPED_GEMM:-true}

# Multi-node settings; run on every node with a unique NODE_RANK.
NNODES=${NNODES:-1}
NODE_RANK=${NODE_RANK:-0}
MASTER_ADDR=${MASTER_ADDR:-127.0.0.1}
MASTER_PORT=${MASTER_PORT:-29500}

echo "=== Megatron SFT Training ==="
echo "Model:   $model_path"
echo "Dataset: ${data_paths[@]}"
echo "Output:  $output_dir"
echo "Nodes:   $NNODES (rank $NODE_RANK, master $MASTER_ADDR:$MASTER_PORT)"
echo "=========================="

IFS=',' read -r -a devices <<< "$CUDA_DEVICES"
NPROC=${NPROC_PER_NODE:-${#devices[@]}}

# swift's `megatron sft` CLI reads NPROC_PER_NODE/NNODES/NODE_RANK/MASTER_ADDR/
# MASTER_PORT from the environment and builds the torchrun command itself.
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
    --tensor_model_parallel_size 4 \
    --expert_model_parallel_size 8 \
    --sequence_parallel true \
    --micro_batch_size 1 \
    --global_batch_size 64 \
    --num_train_epochs 3 \
    --finetune true \
    --tuner_type full \
    --lr 1e-5 \
    --lr_warmup_fraction 0.05 \
    --min_lr 1e-6 \
    --max_length 85536 \
    --save_safetensors true \
    --output_dir "$output_dir" \
    --save_steps 50 \
    --eval_steps 50 \
    --moe_permute_fusion $MOE_PERMUTE_FUSION \
    --moe_grouped_gemm $MOE_GROUPED_GEMM \
    --moe_aux_loss_coeff 1e-3 \
    --recompute_granularity full \
    --recompute_method uniform \
    --recompute_num_layers 1 \
    --cross_entropy_loss_fusion false \
    --attention_backend flash \
    --padding_free true \
    --packing false \
    --dataloader_num_workers 4 \
    --dataset_num_proc 4 \
    --no_save_optim true \
    --no_save_rng true \
    "$@"
