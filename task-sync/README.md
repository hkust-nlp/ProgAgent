# TaskSync

Task environments, synthesis, evaluation, and SFT trajectory conversion for
ProgAgent. Training launchers are in [ptc_training_recipe](../ptc_training_recipe/README.md).

| Path | Contents |
| --- | --- |
| `environments/standard/` | 215 tasks, each at scales `v0`–`v3` |
| `environments/hard/` | 50 tasks with more complex tool interfaces |
| `topics/topics.json` | Task topics and generation seeds |
| `prompts/` | Generation, validation, and hardening templates |
| `src/` | Synthesis, evaluation, conversion, and sandbox tools |

Each task version contains `data.py`, `env.py`, and `prompt.md`.
Run the following commands from `task-sync/`.

## Synthesis

Requires the Claude Agent SDK, authentication, and its runtime dependencies.
Topic generation uses the provider configured in `src/generate_topics.py`.

```bash
python src/generate_topics.py --num 20 --output generated_topics.json
python src/generate_environments.py \
  --topics generated_topics.json \
  --gen prompts/generate.md --harness prompts/validate.md \
  --output-dir environments/generated --max-concurrent 5
```

Complete tasks are skipped on repeat runs. To harden existing tasks, use
`--topics prompts/hardening.json --gen prompts/harden.md` and a separate output
directory. Hardening `SOURCE` paths are relative to `task-sync/`.

## Evaluation and SFT export

Requires `httpx`, `openai`, `jupyter_client`, and `ipykernel`; Anthropic evaluation
also needs `anthropic`. Tasks may require `numpy`, `pandas`, and `faker`.
Configure the model endpoint and credentials before evaluation.
Remote presets read `KIMI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or
`DEEPSEEK_API_KEY` from the environment. Topic generation uses
`OPENROUTER_API_KEY`, `KIMI_API_KEY`, or `DEEPSEEK_API_KEY` for the selected provider.

```bash
python src/evaluate.py environments/standard/adjuster_workload_optimization/v3 \
  --model local --k 2 --n 8
python src/convert_trajectories_to_sft.py <eval_results_dir> \
  -o trajectories.jsonl --best-per-env
```

Evaluation accepts a task version, directory tree, or file listing task paths.
Use `--only-ptc` for programmatic calls, `--no-ptc` for direct calls, and
`--resume` with a previous result directory. Outputs go to `eval_results/`.
For RL from the repository root, pass `--train_files task-sync/environments/standard`.
