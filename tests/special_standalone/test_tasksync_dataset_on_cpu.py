# Copyright 2026 The TaskSync Authors
# SPDX-License-Identifier: Apache-2.0
"""Test TaskSync data configuration without GPU or sandbox dependencies."""

import os
import subprocess
from pathlib import Path

import pytest
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from examples.train_verl_tasksync.tasksync_dataset import TaskSyncDataset, build_tasksync_datasets

ROOT = Path(__file__).resolve().parents[2]


def tasks(root, count):
    for i in reversed(range(count)):
        task = root / f"task{i:02d}"
        task.mkdir(parents=True)
        for name in ("data.py", "env.py", "prompt.md"):
            (task / name).write_text("")
    return str(root)


def config(train, val=None):
    return OmegaConf.create(
        {
            "data": {
                "train_files": train,
                "val_files": val,
                "train_batch_size": 3,
                "val_batch_size": 2,
                "seed": 42,
                "shuffle": False,
                "validation_shuffle": False,
                "tasksync": {"val_ratio": 0.0},
            },
            "actor_rollout_ref": {"env": {}, "rollout": {"n": 4, "val_kwargs": {"n": 2}}},
        }
    )


def names(dataset, index):
    return [group.task_info["source_path"] for group in dataset.get_batch(index)]


def test_native_batch_and_validation_settings(tmp_path):
    cfg = config(tasks(tmp_path / "train", 7), tasks(tmp_path / "val", 5))
    train, val = build_tasksync_datasets(cfg)
    assert len(train) == 2  # Train drops the incomplete batch, like verl.
    assert [len(val.get_batch(i)) for i in range(len(val))] == [2, 2, 1]
    assert len({name for i in range(len(val)) for name in names(val, i)}) == 5
    assert all(group.num_envs == 4 for group in train.get_batch(0))
    assert all(group.num_envs == 2 for group in val.get_batch(0))
    cfg.data.val_batch_size = None
    _, val = build_tasksync_datasets(cfg)
    assert len(val) == 1 and len(val.get_batch(0)) == 5


def test_multiple_sources_limits_and_no_validation(tmp_path):
    first, second = tasks(tmp_path / "a", 4), tasks(tmp_path / "b", 4)
    cfg = config([first, second, first])
    cfg.data.train_max_samples = 6
    train, val = build_tasksync_datasets(cfg)
    assert val is None and len(train.tasks) == 6
    assert len({task["source_path"] for task in train.tasks}) == 6
    assert train.tasks[0]["task_name"] == "task00"
    cfg.data.gen_batch_size = 2
    train, _ = build_tasksync_datasets(cfg)
    assert len(train) == 3


def test_disjoint_deterministic_split(tmp_path):
    cfg = config(tasks(tmp_path / "tasks", 20))
    cfg.data.tasksync.val_ratio = 0.25
    cfg.data.shuffle = True
    train, val = build_tasksync_datasets(cfg)
    other_train, other_val = build_tasksync_datasets(cfg)
    assert len(train.tasks) == 15 and len(val.tasks) == 5
    assert train.tasks == other_train.tasks and val.tasks == other_val.tasks
    assert not ({t["source_path"] for t in train.tasks} & {t["source_path"] for t in val.tasks})
    cfg.data.val_files = cfg.data.train_files
    with pytest.raises(ValueError, match="not both"):
        build_tasksync_datasets(cfg)
    cfg.data.val_files = None
    cfg.data.seed = None
    with pytest.raises(ValueError, match="data.seed"):
        build_tasksync_datasets(cfg)


def test_epoch_shuffle_and_checkpoint_resume(tmp_path):
    root = tasks(tmp_path / "tasks", 20)
    dataset = TaskSyncDataset(root, 4, 2, seed=17)
    original = dataset.shuffled_tasks.copy()
    dataset.set_epoch(1)
    assert original != dataset.shuffled_tasks
    restored = TaskSyncDataset(root, 4, 2, seed=17)
    restored.load_state_dict(dataset.state_dict())
    restored.set_epoch(1)
    assert names(restored, 2) == names(dataset, 2)
    restored.set_epoch(2)
    dataset.set_epoch(2)
    assert restored.shuffled_tasks == dataset.shuffled_tasks
    sequential = TaskSyncDataset(root, 4, 2, shuffle=False)
    original = sequential.shuffled_tasks.copy()
    sequential.set_epoch(1)
    assert sequential.shuffled_tasks == original


def test_invalid_sources_and_empty_train_fail(tmp_path):
    cfg = config(tasks(tmp_path / "small", 2))
    with pytest.raises(ValueError, match="Train dataloader is empty"):
        build_tasksync_datasets(cfg)
    cfg.data.train_batch_size = 1
    cfg.data.val_files = str(tmp_path / "missing")
    with pytest.raises(ValueError, match="task directory"):
        build_tasksync_datasets(cfg)
    cfg.data.val_files = None
    cfg.actor_rollout_ref.env.batch_size = 1
    with pytest.raises(ValueError, match="legacy"):
        build_tasksync_datasets(cfg)


@pytest.mark.parametrize("model", ["8b", "14b", "coder"])
@pytest.mark.parametrize("legacy", [False, True])
def test_launcher_and_hydra_config(tmp_path, model, legacy):
    capture = tmp_path / "args.json"
    executable = tmp_path / "python3"
    executable.write_text('#!/bin/bash\nprintf "%s\\0" "$@" > "$PTC_CAPTURE"\n')
    executable.chmod(0o755)
    env = dict(
        os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}", LOG_DIR=str(tmp_path / "logs"), PTC_CAPTURE=str(capture)
    )
    subprocess.run(
        [
            "bash",
            str(ROOT / f"ptc_training_recipe/rl/train_megatron_qwen3_{model}.sh"),
            "--model_path",
            "/tmp/model",
            "--data_dir" if legacy else "--train_files",
            "[/tmp/train-a,/tmp/train-b]",
            "--env_batch_size" if legacy else "--train_batch_size",
            "4",
            "--env_group_size" if legacy else "--rollout_n",
            "3",
            "--val_files",
            "/tmp/val",
            "--val_batch_size",
            "2",
            "--seed",
            "17",
        ],
        env=env,
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    args = capture.read_bytes().decode().rstrip("\0").split("\0")
    with initialize_config_dir(config_dir=str(ROOT / "examples/train_verl_tasksync/config"), version_base=None):
        cfg = compose(config_name="tasksync_grpo_megatron", overrides=args[3:])
    assert list(cfg.data.train_files) == ["/tmp/train-a", "/tmp/train-b"]
    assert cfg.data.val_files == "/tmp/val" and cfg.data.val_batch_size == 2
    assert cfg.data.seed == 17
    assert cfg.data.train_batch_size == 4 and cfg.actor_rollout_ref.rollout.n == 3
    assert cfg.actor_rollout_ref.actor.ppo_mini_batch_size == 4
    assert cfg.data.max_prompt_length == cfg.actor_rollout_ref.rollout.prompt_length
    assert cfg.data.max_response_length == cfg.actor_rollout_ref.rollout.response_length
    assert "tasks_dir" not in cfg.actor_rollout_ref.env
