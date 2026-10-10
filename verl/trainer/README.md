# Training entry points

| File | Purpose |
| --- | --- |
| [main_ppo.py](main_ppo.py) | Standard PPO/GRPO training |
| [sft_trainer.py](sft_trainer.py) | SFT launched with torchrun |
| [sft_trainer_ray.py](sft_trainer_ray.py) | Experimental Ray-driven SFT |
| [main_generation_server.py](main_generation_server.py) | Generation for prompt datasets |
| [main_eval.py](main_eval.py) | Reward-based evaluation of generated responses |

ProgAgent uses [train_tasksync.py](../../examples/train_verl_tasksync/train_tasksync.py)
for RL and Megatron-SWIFT for SFT. See the [training guide](../../ptc_training_recipe/README.md).
