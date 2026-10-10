# Checkpoint engine

Synchronizes model weights between training and rollout workers.

- `send_weights`: streams named tensors to receivers.
- `receive_weights`: yields received tensors.
- `get_weights`: reads tensors from a local cache.

The interface is defined in [base.py](base.py). Backends include NCCL, HCCL,
NIXL, Mooncake, and Kimi checkpoint-engine; select one supported by your hardware
and installed communication libraries.

Kimi's backend requires `checkpoint-engine[p2p]>=0.4.0`. Ascend needs a compatible
Mooncake build; with CANN >= 8.5.0, set `HCCL_INTRA_ROCE_ENABLE=1`.
