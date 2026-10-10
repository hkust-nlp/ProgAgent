# Fully asynchronous policy training

Upstream experimental trainer that runs rollout and optimization on separate
resources. ProgAgent's TaskSync recipes use their own training entry point.

See [fully_async_main.py](fully_async_main.py), [configuration](config/), and
[launch scripts](shell/) for setup. Supply model/data paths and GPU allocations
for your environment.

| Setting | Purpose |
| --- | --- |
| `trainer.nnodes`, `trainer.n_gpus_per_node` | Training resources |
| `rollout.nnodes`, `rollout.n_gpus_per_node` | Rollout resources |
| `async_training.require_batches` | Mini-batches consumed per update cycle |
| `async_training.trigger_parameter_sync_step` | Updates between weight synchronizations |
| `async_training.staleness_threshold` | Allowed sample staleness; zero is synchronous |
| `async_training.partial_rollout` | Partial rollout; requires positive staleness |

Use rollout log probabilities for the policy that generated each sample.
Configure correction through `algorithm.rollout_correction`; the streaming
trainer uses `data.gen_batch_size` rather than `data.train_batch_size`.

Originally contributed by [Meituan Search](https://github.com/meituan-search).
