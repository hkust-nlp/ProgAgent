# Dataset adapters

Standard RL datasets store chat prompts and reward metadata in Parquet, e.g.:

```json
{
  "data_source": "math",
  "prompt": [{"role": "user", "content": "What is 6 times 12?"}],
  "ability": "math",
  "reward_model": {"style": "rule", "ground_truth": "72"}
}
```

ProgAgent uses [TaskSyncDataset](../../../examples/train_verl_tasksync/tasksync_dataset.py)
to load task directories instead. SFT recipes take JSONL trajectories.
