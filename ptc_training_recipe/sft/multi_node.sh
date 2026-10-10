#!/bin/bash
# SFT multi-node launcher
# Usage: bash ptc_training_recipe/sft/multi_node.sh <train_script.sh>
#
# Multi-node launcher for megatron training (torchrun-based).
# Run this script on EVERY node with the same env vars, only NODE_RANK differs.
#
# Example (2 nodes, 8 GPUs each):
#   Node 0: NNODES=2 NODE_RANK=0 MASTER_ADDR=10.0.0.1 MASTER_PORT=29500 NGPUS_PER_NODE=8 bash ptc_training_recipe/sft/multi_node.sh ptc_training_recipe/sft/sft_qwen3_coder.sh
#   Node 1: NNODES=2 NODE_RANK=1 MASTER_ADDR=10.0.0.1 MASTER_PORT=29500 NGPUS_PER_NODE=8 bash ptc_training_recipe/sft/multi_node.sh ptc_training_recipe/sft/sft_qwen3_coder.sh

set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <train_script.sh> [args...]"
    exit 1
fi

TRAIN_SCRIPT=$1
shift

# Environment variables setup (defaults if not provided).
# JD/ECP (Kubernetes) injects torchrun-style rendezvous vars with different
# names:
#     WORLD_SIZE  -> number of NODES (NOT total GPUs) in the job
#     RANK        -> this node's rank, 0..WORLD_SIZE-1
#     MASTER_ADDR -> head node DNS hostname (torchrun resolves it lazily)
#     MASTER_PORT -> rendezvous port
# Explicit NNODES/NODE_RANK still take precedence; SENSECORE_* are the
# platform's redundant second family.
NNODES=${NNODES:-${WORLD_SIZE:-${SENSECORE_PYTORCH_NNODES:-1}}}
NODE_RANK=${NODE_RANK:-${RANK:-${SENSECORE_PYTORCH_NODE_RANK:-0}}}
NGPUS_PER_NODE=${NGPUS_PER_NODE:-${SENSECORE_ACCELERATE_DEVICE_COUNT:-8}}
MASTER_ADDR=${MASTER_ADDR:-"127.0.0.1"}
MASTER_PORT=${MASTER_PORT:-29500}

# JD network fabric (eth0 + IB): without these, cross-node NCCL picks the
# wrong interface. All values below are overridable.
export NCCL_SOCKET_IFNAME=${NCCL_SOCKET_IFNAME:-eth0}
export NCCL_IB_GID_INDEX=${NCCL_IB_GID_INDEX:-5}
export NCCL_IB_TC=${NCCL_IB_TC:-138}
export NCCL_IB_QPS_PER_CONNECTION=${NCCL_IB_QPS_PER_CONNECTION:-8}
export NCCL_IB_TIMEOUT=${NCCL_IB_TIMEOUT:-22}
export NCCL_PXN_DISABLE=${NCCL_PXN_DISABLE:-0}
export NCCL_CROSS_NIC=${NCCL_CROSS_NIC:-1}
export NCCL_NVLS_ENABLE=${NCCL_NVLS_ENABLE:-0}

echo "========================================"
echo " Multi-Node Cluster Info"
echo "========================================"
echo " NNODES:          $NNODES"
echo " NODE_RANK:       $NODE_RANK"
echo " MASTER_ADDR:     $MASTER_ADDR"
echo " MASTER_PORT:     $MASTER_PORT"
echo " NGPUS_PER_NODE:  $NGPUS_PER_NODE"
echo " HOSTNAME:        $(hostname)"
echo " LOCAL_IP:        $(hostname -I 2>/dev/null | awk '{print $1}' || echo 'unknown')"
echo " TRAIN_SCRIPT:    $TRAIN_SCRIPT"
echo "========================================"

export NNODES NODE_RANK MASTER_ADDR MASTER_PORT
export NPROC_PER_NODE=${NPROC_PER_NODE:-$NGPUS_PER_NODE}

echo "[Node $NODE_RANK] Starting training (torchrun handles rendezvous)..."
exec bash "$TRAIN_SCRIPT" "$@"
