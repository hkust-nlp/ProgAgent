# One-step off-policy training

Upstream experimental trainer that overlaps the next rollout batch with the
current optimization step. Training uses trajectories from the previous policy
version. ProgAgent's TaskSync recipes use a separate entry point.

See [main_ppo.py](main_ppo.py), [configuration](config/), and [launch scripts](shell/).

- Set `actor_rollout_ref.hybrid_engine=False` for separate training and rollout resources.
- Configure `trainer.nnodes` / `trainer.n_gpus_per_node` and
  `rollout.nnodes` / `rollout.n_gpus_per_node` for the available GPUs.
- Ensure batch sizes distribute evenly across training workers.
- Use `wait_prev_gen` to identify time spent waiting for rollout completion.

Originally contributed by [Meituan Search](https://github.com/meituan-search).
