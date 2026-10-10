# Copyright 2025 GEM Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Dataset for task-sync style environments.

task-sync envs have the structure:
    task_root/
        category_or_batch/
            task_name/
                v0/
                    data.py
                    env.py
                    prompt.md
                    task_verification.py

This module discovers and validates these envs, producing task_info dicts
compatible with TaskSyncAgentLoop. It also supports splitting discovered
tasks into train / val partitions deterministically.
"""

import logging
import os
import random
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)

_REQUIRED_FILES = ["data.py", "env.py", "prompt.md"]


class TaskSyncTaskInfo(TypedDict, total=False):
    source_path: str
    task_name: str


@dataclass
class TaskSyncEnvGroupBuilder:
    task_info: TaskSyncTaskInfo
    num_envs: int
    max_tool_calls: int = 50


class TaskSyncDataset:
    """Dataset that discovers and samples task-sync environments.

    Scans a directory tree for subdirectories containing the required files
    (data.py, env.py, prompt.md) and optionally validates them by running
    ``python data.py --db_path data.db --workspace workspace`` to ensure
    the data generation step works.

    Each batch contains ``batch_size`` different tasks with ``group_size``
    rollouts per task for GRPO reward centering.

    If ``split="train"`` / ``"val"`` is provided together with ``val_ratio``,
    the discovered tasks are deterministically partitioned: a seeded shuffle
    picks the first ``round(len(tasks) * val_ratio)`` entries as the val set
    and the remainder as train. Pass ``split=None`` to disable partitioning.
    """

    def __init__(
        self,
        tasks_dir: str | list[str],
        batch_size: Optional[int],
        group_size: int,
        max_tool_calls: int = 50,
        filter_pattern: Optional[str] = None,
        seed: int = 0,
        validate_on_discovery: bool = False,
        split: Optional[str] = None,
        val_ratio: float = 0.05,
        shuffle: bool = True,
        drop_last: bool = True,
        max_samples: int = -1,
    ):
        self.tasks_dir = tasks_dir
        self.batch_size = batch_size
        self.group_size = group_size
        self.max_tool_calls = max_tool_calls
        self.filter_pattern = filter_pattern
        self.seed = seed
        self.validate_on_discovery = validate_on_discovery
        self.split = split
        self.val_ratio = val_ratio
        self.shuffle = shuffle
        self.drop_last = drop_last
        if split not in (None, "train", "val") or not 0 <= val_ratio < 1:
            raise ValueError("split must be train, val, or None; val_ratio must be in [0, 1)")
        if group_size < 1 or (batch_size is not None and batch_size < 1):
            raise ValueError("batch_size and group_size must be positive")

        all_tasks = self._discover_tasks()
        self.tasks = self._partition_tasks(all_tasks)
        if 0 < max_samples < len(self.tasks):
            self.tasks = random.Random(seed).sample(self.tasks, max_samples) if shuffle else self.tasks[:max_samples]
        if not self.tasks:
            raise ValueError(f"No valid task-sync tasks found in {tasks_dir} for split={split!r}")

        logger.info(f"TaskSyncDataset: split={split!r} discovered={len(all_tasks)} kept={len(self.tasks)}")

        self.batch_size = batch_size if batch_size is not None else len(self.tasks)
        if drop_last and len(self.tasks) < self.batch_size:
            raise ValueError("Train dataloader is empty: fewer tasks than data.train_batch_size")
        self.rng = random.Random(seed)
        self.shuffled_tasks = self.tasks.copy()
        self.epoch = -1
        self.set_epoch(0)

    def _discover_tasks(self) -> list[TaskSyncTaskInfo]:
        roots = [self.tasks_dir] if isinstance(self.tasks_dir, (str, os.PathLike)) else self.tasks_dir
        tasks = {}
        for root in roots:
            for task in self._discover_root(root):
                tasks.setdefault(task["source_path"], task)
        return list(tasks.values())

    def _discover_root(self, root_path: str) -> list[TaskSyncTaskInfo]:
        import fnmatch

        base = Path(root_path).expanduser().resolve()
        if not base.is_dir():
            raise ValueError(f"TaskSync data source must be a task directory: {root_path}")

        tasks: list[TaskSyncTaskInfo] = []
        failed: list[str] = []

        for root, dirs, files in os.walk(str(base)):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))

            if all(f in files for f in _REQUIRED_FILES):
                task_dir = root
                rel = os.path.relpath(task_dir, str(base))
                task_name = rel.replace(os.sep, "/")

                if self.filter_pattern and not fnmatch.fnmatch(task_name, self.filter_pattern):
                    continue

                task_info: TaskSyncTaskInfo = {
                    "source_path": task_dir,
                    "task_name": task_name,
                }

                if self.validate_on_discovery:
                    if self._validate_task(task_info):
                        tasks.append(task_info)
                    else:
                        failed.append(task_name)
                else:
                    tasks.append(task_info)

                dirs.clear()

        if failed:
            logger.warning(
                f"Filtered out {len(failed)} invalid task-sync tasks. "
                f"Examples: {failed[:5]}{'...' if len(failed) > 5 else ''}"
            )

        return tasks

    def _partition_tasks(self, all_tasks: list[TaskSyncTaskInfo]) -> list[TaskSyncTaskInfo]:
        if self.split is None or self.val_ratio <= 0:
            return all_tasks

        ordered = sorted(all_tasks, key=lambda t: t["task_name"])
        rng = random.Random(self.seed)
        shuffled = ordered.copy()
        rng.shuffle(shuffled)

        n_val = max(1, round(len(shuffled) * self.val_ratio)) if shuffled else 0
        val_set = shuffled[:n_val]
        train_set = shuffled[n_val:]

        if self.split == "train":
            return train_set
        if self.split == "val":
            return val_set
        raise ValueError(f"split must be one of 'train', 'val', None. Got: {self.split!r}")

    def _validate_task(self, task_info: TaskSyncTaskInfo) -> bool:
        import shutil
        import tempfile

        source_path = task_info["source_path"]
        tmp = tempfile.mkdtemp(prefix="tasksync_validate_")
        try:
            for f in _REQUIRED_FILES + ["task_verification.py"]:
                src = os.path.join(source_path, f)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(tmp, f))

            r = subprocess.run(
                [sys.executable, "data.py", "--db_path", "data.db", "--workspace", "workspace"],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode != 0:
                logger.debug(f"Validation failed for {task_info['task_name']}: {r.stderr[:200]}")
                return False

            return os.path.exists(os.path.join(tmp, "data.db"))

        except Exception as e:
            logger.debug(f"Validation error for {task_info['task_name']}: {e}")
            return False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def __len__(self) -> int:
        if self.drop_last:
            return len(self.tasks) // self.batch_size
        return (len(self.tasks) + self.batch_size - 1) // self.batch_size

    def set_epoch(self, epoch: int) -> None:
        if epoch != self.epoch:
            self.shuffled_tasks = self.tasks.copy()
            if self.shuffle:
                self.rng.shuffle(self.shuffled_tasks)
            self.epoch = epoch

    def get_batch(self, index: int) -> list[TaskSyncEnvGroupBuilder]:
        start_idx = (index * self.batch_size) % len(self.shuffled_tasks)

        if self.drop_last and start_idx + self.batch_size > len(self.shuffled_tasks):
            start_idx = 0

        batch_tasks = self.shuffled_tasks[start_idx : start_idx + self.batch_size]

        return [
            TaskSyncEnvGroupBuilder(
                task_info=task,
                num_envs=self.group_size,
                max_tool_calls=self.max_tool_calls,
            )
            for task in batch_tasks
        ]

    def state_dict(self) -> dict:
        return {
            "rng_state": self.rng.getstate(),
            "shuffled_tasks": self.shuffled_tasks.copy(),
            "epoch": self.epoch,
        }

    def load_state_dict(self, state_dict: dict) -> None:
        self.rng.setstate(state_dict["rng_state"])
        self.shuffled_tasks = state_dict["shuffled_tasks"]
        self.epoch = state_dict.get("epoch", 0)

    def get_task_by_name(self, task_name: str) -> Optional[TaskSyncTaskInfo]:
        for task in self.tasks:
            if task["task_name"] == task_name:
                return task
        return None


def build_tasksync_datasets(config):
    """Use verl data/rollout settings with TaskSync directory sources."""
    data = config.data
    env = config.actor_rollout_ref.env
    rollout = config.actor_rollout_ref.rollout
    legacy_keys = {"tasks_dir", "batch_size", "group_size", "val_ratio", "filter_pattern", "validate_on_discovery"}
    obsolete = legacy_keys.intersection(env)
    if obsolete:
        raise ValueError(
            f"Move legacy env dataset settings {sorted(obsolete)} to data.* / rollout.n; "
            "see ptc_training_recipe/README.md"
        )
    options = data.get("tasksync", {})
    val_ratio = options.get("val_ratio", 0.0)
    if data.val_files and val_ratio:
        raise ValueError("Use either data.val_files or data.tasksync.val_ratio, not both")
    if not data.train_files:
        raise ValueError("data.train_files must specify at least one TaskSync task directory")
    common = dict(
        max_tool_calls=env.get("max_tool_calls", 50),
        filter_pattern=options.get("filter_pattern"),
        validate_on_discovery=options.get("validate_on_discovery", False),
        seed=data.get("seed"),
        val_ratio=val_ratio,
    )
    if val_ratio and common["seed"] is None:
        raise ValueError("Set data.seed when using data.tasksync.val_ratio for a reproducible split")
    train = TaskSyncDataset(
        tasks_dir=data.train_files,
        batch_size=data.get("gen_batch_size", data.train_batch_size),
        group_size=rollout.n,
        split="train" if val_ratio else None,
        shuffle=data.get("shuffle", True),
        max_samples=data.get("train_max_samples", -1),
        **common,
    )
    val = None
    if data.val_files or val_ratio:
        val = TaskSyncDataset(
            tasks_dir=data.val_files or data.train_files,
            batch_size=data.get("val_batch_size"),
            group_size=rollout.get("val_kwargs", {}).get("n", 1),
            split="val" if val_ratio else None,
            shuffle=data.get("validation_shuffle", False),
            drop_last=False,
            max_samples=data.get("val_max_samples", -1),
            **common,
        )
    return train, val
