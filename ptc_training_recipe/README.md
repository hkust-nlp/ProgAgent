# PTC training

Run commands from the repository root. SFT requires Megatron-SWIFT; RL requires
verl, Megatron, mbridge, vLLM, and the TaskSync sandbox dependencies. Use a
compatible GPU environment and tune parallelism and batch sizes for your hardware.

| Model | SFT | RL |
| --- | --- | --- |
| Qwen3-8B | [8B SFT](sft/sft_qwen3_8b.sh) | [8B RL](rl/train_megatron_qwen3_8b.sh) |
| Qwen3-14B | [14B SFT](sft/sft_qwen3_14b.sh) | [14B RL](rl/train_megatron_qwen3_14b.sh) |
| Qwen3-Coder-30B-A3B | [Coder SFT](sft/sft_qwen3_coder.sh) | [Coder RL](rl/train_megatron_qwen3_coder.sh) |

## Model preparation and SFT

For Qwen3-8B/14B, install the XML chat template and YaRN configuration before SFT.
The preparation script backs up modified metadata as `*.before-ptc`; `--check`
checks without writing. Skip preparation for Qwen3-Coder.

```bash
python ptc_training_recipe/prepare_qwen3.py --model /path/to/Qwen3-8B
bash ptc_training_recipe/sft/sft_qwen3_8b.sh \
  --model_path /path/to/Qwen3-8B \
  --data_path /path/to/ptc-thinking.jsonl \
  --output_dir /path/to/sft-output
```

Download JSONL trajectories from [ptc-sft-data](https://huggingface.co/datasets/LLLeo612/ptc-sft-data/tree/main).
Choose `ptc`, `hybrid`, or `dtc`, with thinking or non-thinking trajectories.
Repeat `--data_path` to combine files. Extra Swift arguments
follow `--`, e.g. `-- --micro_batch_size 1 --tensor_model_parallel_size 4`.

## RL

Use the checkpoint directory produced by SFT, containing weights, configuration,
and tokenizer files. The SFT scripts save weights in Hugging Face format;
checkpoints from the preparation and SFT flow above are ready for RL.

```bash
bash ptc_training_recipe/rl/train_megatron_qwen3_8b.sh \
  --model_path /path/to/sft-checkpoint \
  --train_files task-sync/environments/standard \
  --ptc_mode ptc
```

| Option | Meaning |
| --- | --- |
| `--ptc_mode ptc` | Environment calls through Python only |
| `--ptc_mode dtc` | Direct environment calls only |
| `--ptc_mode hybrid` | Both interfaces; launcher default |
| `--val_files PATH --test_freq 10` | Separate validation tasks and evaluation interval |
| `--train_batch_size 32 --rollout_n 16` | Tasks per batch and rollouts per task |
| `--total_epochs 10` | Number of training epochs |
| `--val_batch_size 8` | Validation task batch size |
| `--seed 42` | Dataset ordering and optional split seed |
| `--ckpt_root PATH` | Checkpoint destination; logs use `LOG_DIR` |

RL inputs are task directories containing `data.py`, `env.py`, and `prompt.md`,
not SFT JSONL files. Multiple sources use `--train_files '[/path/a,/path/b]'`.
Without `--val_files`, validation is off unless `--val_ratio` is positive; do not
combine both. Hydra overrides such as `data.train_max_samples=1000` go last.
Training drops incomplete batches; validation keeps them.

For the paper's DTC setting, use only `v0` environments. When passing
`task-sync/environments/standard` as the source, append
`'data.tasksync.filter_pattern=*/v0'`. The 8B/14B launchers also accept the legacy
`--ptc_mode no-ptc` spelling as an alias for `dtc`.

## Multiple nodes

Set these environment variables in your cluster job configuration before running
the launchers. If the scheduler provides different variable names, map them to
the names below.

| Variable | Value |
| --- | --- |
| `NNODES` | Total number of participating nodes |
| `NODE_RANK` | This node's rank, from `0` to `NNODES - 1` |
| `NGPUS_PER_NODE` | Number of GPUs used on each node |
| `MASTER_ADDR` | Rank-zero node's IP or hostname, reachable from every node |
| `MASTER_PORT` | Available port on rank zero; the same on every node |

Run the launcher on every node with shared model/data paths and a distinct
`NODE_RANK`. Rank zero launches the RL driver.

```bash
# SFT: MASTER_PORT defaults to 29500.
bash ptc_training_recipe/sft/multi_node.sh \
  ptc_training_recipe/sft/sft_qwen3_coder.sh \
  --model_path /path/to/model --data_path /path/to/data.jsonl \
  --output_dir /path/to/sft-output

# RL: MASTER_PORT defaults to 6379; start without an existing Ray cluster there.
bash ptc_training_recipe/rl/start_ray.sh \
  ptc_training_recipe/rl/train_megatron_qwen3_coder.sh \
  --model_path /path/to/sft-checkpoint \
  --train_files /path/to/tasks --ptc_mode ptc
```
