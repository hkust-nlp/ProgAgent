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

"""Trainer for task-sync style environments (verl 0.7.1).

Delegates multi-turn tool execution to ``TaskSyncAgentLoop`` via
``async_rollout_manager.generate_sequences``. Replaces the base
``RayPPOTrainer.fit()`` with a task-sync specific flow:

    - samples a batch of tasks from ``TaskSyncDataset``
    - builds ``raw_prompt`` + ``task_info`` DataProto
    - runs rollout, computes old_log_prob / ref_log_prob / advantages
    - dispatches to actor update and manages rollout sleep/wake via the
      new ``CheckpointEngineManager``.
"""

import json
import logging
import os
import time
from collections import defaultdict
from pprint import pprint
from typing import Optional

import numpy as np
import torch
import torch.utils.data
from omegaconf import OmegaConf, open_dict
from tensordict import TensorDict
from torch.utils.data import SequentialSampler
from torchdata.stateful_dataloader import StatefulDataLoader
from tqdm import tqdm

from verl import DataProto
from verl.single_controller.ray import RayWorkerGroup
from verl.trainer.ppo.metric_utils import (
    compute_data_metrics,
    compute_throughout_metrics,
    compute_timing_metrics,
    compute_variance_proxy_metrics,
)
from verl.trainer.ppo.ray_trainer import (
    RayPPOTrainer,
    ResourcePoolManager,
    Role,
    apply_kl_penalty,
    compute_advantage,
    compute_response_mask,
)
from verl.utils.debug import marked_timer
from verl.utils.metric import reduce_metrics

from .tasksync_dataset import TaskSyncDataset, build_tasksync_datasets

logger = logging.getLogger(__name__)


class _DummyPromptDataset(torch.utils.data.Dataset):
    """Placeholder dataset that yields empty strings.

    ``RayPPOTrainer._create_dataloader`` requires real Dataset objects; the
    actual prompts come from ``TaskSyncDataset.get_batch()`` inside
    ``run_planning_rollout``.
    """

    def __init__(self, size: int = 1):
        self.size = max(1, size)

    def __len__(self) -> int:
        return self.size

    def __getitem__(self, idx: int) -> dict:
        del idx
        return {}


def _identity_collate(batch):
    return {"_tasksync_placeholder": batch}


class TaskSyncTrainer(RayPPOTrainer):
    """Trainer for task-sync environments with dynamic task sampling."""

    def __init__(
        self,
        config,
        tokenizer,
        role_worker_mapping: dict,
        resource_pool_manager: ResourcePoolManager,
        ray_worker_group_cls=RayWorkerGroup,
        processor=None,
        device_name=None,
    ):
        # Build TaskSyncDataset BEFORE super().__init__ so we know the sizes
        # that the dummy dataloaders must report.
        env_cfg = config.actor_rollout_ref.env

        # PTC and hybrid enable programmatic calls; the selected agent loop
        # controls whether direct environment calls are allowed.
        self.ptc_mode = env_cfg.get("ptc_mode", "hybrid")
        if self.ptc_mode not in ("ptc", "hybrid", "dtc"):
            raise ValueError(f"ptc_mode must be ptc, hybrid, or dtc, got {self.ptc_mode!r}")
        self.ptc_desc = env_cfg.get("ptc_desc", "rich")

        self.planning_dataset, self.val_planning_dataset = build_tasksync_datasets(config)

        steps_per_epoch = max(1, len(self.planning_dataset))
        val_steps_per_epoch = (
            max(1, len(self.val_planning_dataset)) if self.val_planning_dataset is not None else 1
        )

        self._tasksync_train_size = steps_per_epoch
        self._tasksync_val_size = val_steps_per_epoch

        super().__init__(
            config=config,
            tokenizer=tokenizer,
            role_worker_mapping=role_worker_mapping,
            resource_pool_manager=resource_pool_manager,
            ray_worker_group_cls=ray_worker_group_cls,
            processor=processor,
            train_dataset=_DummyPromptDataset(steps_per_epoch),
            val_dataset=_DummyPromptDataset(val_steps_per_epoch),
            collate_fn=_identity_collate,
            train_sampler=SequentialSampler(_DummyPromptDataset(steps_per_epoch)),
            device_name=device_name,
        )

        # Experience dumping for debugging/analysis
        self.dump_experience_every = int(
            config.actor_rollout_ref.get("dump_experience_every", -1)
        )
        self.actor_id = 0
        self.game_state_save_path = os.path.join(
            self.config.trainer.default_local_dir,
            "game_states",
        )
        os.makedirs(self.game_state_save_path, exist_ok=True)

    def _create_dataloader(self, train_dataset, val_dataset, collate_fn, train_sampler):
        """Override parent's dataloader creation to bypass ``create_rl_dataset``.

        We keep the StatefulDataLoader shape so ``_save_checkpoint`` / ``_load_checkpoint``
        can still serialize / restore the loader state, but the data is meaningless --
        we only use the dataloader as a pacing device for the outer for-loop.
        """
        self.train_dataset = train_dataset
        self.val_dataset = val_dataset

        self.train_dataloader = StatefulDataLoader(
            dataset=train_dataset,
            batch_size=1,
            num_workers=0,
            drop_last=False,
            collate_fn=collate_fn,
            sampler=train_sampler,
        )
        self.val_dataloader = StatefulDataLoader(
            dataset=val_dataset,
            batch_size=1,
            num_workers=0,
            shuffle=False,
            drop_last=False,
            collate_fn=collate_fn,
        )

        total_training_steps = len(self.train_dataloader) * self.config.trainer.total_epochs
        if self.config.trainer.total_training_steps is not None:
            total_training_steps = self.config.trainer.total_training_steps
        self.total_training_steps = total_training_steps
        print(f"Total training steps: {self.total_training_steps}")

        try:
            OmegaConf.set_struct(self.config, True)
            with open_dict(self.config):
                if OmegaConf.select(self.config, "actor_rollout_ref.actor.optim"):
                    self.config.actor_rollout_ref.actor.optim.total_training_steps = (
                        total_training_steps
                    )
                if OmegaConf.select(self.config, "critic.optim"):
                    self.config.critic.optim.total_training_steps = total_training_steps
        except Exception as e:
            logger.warning(f"Could not set total_training_steps in optim config: {e}")

    # ------------------------------------------------------------------
    # Validation — runs rollouts over the held-out task partition without a
    # gradient step, and mirrors the training-time metric layout exactly
    # (val/reward/* and val/group_status/*) so val / train are directly
    # comparable on the same plot.
    # ------------------------------------------------------------------
    def _validate(self) -> dict:
        if self.val_planning_dataset is None:
            return {}
        self.val_planning_dataset.set_epoch(self.global_steps)

        # Rewards / episode outcome
        dense_rewards: list[float] = []
        episode_rewards: list[float] = []
        episode_successes: list[bool] = []
        episode_claim_dones: list[bool] = []

        # Per-episode shape
        episode_turns: list[int] = []
        rollout_lengths: list[int] = []
        truncated_flags: list[int] = []
        generated_tokens: list[int] = []
        thinking_tokens: list[int] = []
        ptc_code_tokens: list[int] = []
        tool_obs_tokens: list[int] = []

        # Tool usage
        ptc_counts: list[int] = []
        ptc_error_counts: list[int] = []
        ptc_error_penalties: list[float] = []
        python_counts: list[int] = []
        terminal_counts: list[int] = []
        env_tool_counts: list[int] = []

        # Group-level aggregation buckets: uid -> list of per-sample rewards
        uid2rewards: dict = defaultdict(list)

        for batch_idx in range(len(self.val_planning_dataset)):
            output = self._run_rollout(
                dataset=self.val_planning_dataset,
                batch_index=batch_idx,
                validate=True,
            )
            if output is None or output.non_tensor_batch is None:
                continue
            ntb = output.non_tensor_batch

            def _as_list(key: str) -> list:
                arr = ntb.get(key)
                if arr is None:
                    return []
                return arr.tolist() if hasattr(arr, "tolist") else list(arr)

            dense_rewards.extend(_as_list("dense_reward"))
            episode_rewards.extend(_as_list("episode_reward"))
            episode_successes.extend(_as_list("episode_success"))
            episode_claim_dones.extend(_as_list("episode_claim_done"))
            episode_turns.extend(_as_list("episode_turns"))
            rollout_lengths.extend(_as_list("rollout_length"))
            truncated_flags.extend(_as_list("truncated"))
            generated_tokens.extend(_as_list("generated_tokens"))
            thinking_tokens.extend(_as_list("thinking_tokens"))
            ptc_code_tokens.extend(_as_list("ptc_code_tokens"))
            tool_obs_tokens.extend(_as_list("tool_obs_tokens"))
            ptc_counts.extend(_as_list("programmatic_tool_call_count"))
            ptc_error_counts.extend(_as_list("programmatic_tool_call_error_count"))
            ptc_error_penalties.extend(_as_list("ptc_error_penalty"))
            python_counts.extend(_as_list("execute_python_count"))
            terminal_counts.extend(_as_list("terminal_count"))
            env_tool_counts.extend(_as_list("env_tool_count"))

            # Group stats require uid + per-sample reward. Rebuild from
            # token_level_rewards if the raw scalar isn't in non_tensor_batch.
            uids = _as_list("uid")
            if uids:
                if "reward" in ntb:
                    sample_rewards = _as_list("reward")
                elif output.batch is not None and "token_level_rewards" in output.batch:
                    sample_rewards = (
                        output.batch["token_level_rewards"].sum(dim=-1).tolist()
                    )
                else:
                    sample_rewards = episode_rewards[-len(uids):]
                for uid, r in zip(uids, sample_rewards, strict=False):
                    uid2rewards[uid].append(r)

        if not dense_rewards:
            return {}

        # ---- reward/* (mirror of training-side planning_stats) ----
        # `score`         : raw env-reported reward (dense_reward), unmodified.
        # `episode_reward_mean` : reward actually fed to GRPO (post binary
        #                   conversion + PTC penalty + non-negative clip).
        reward_metrics = {
            "val/reward/score": float(np.mean(dense_rewards)),
            "val/reward/score_min": float(np.min(dense_rewards)),
            "val/reward/score_max": float(np.max(dense_rewards)),
            "val/reward/zero_reward_ratio": (
                dense_rewards.count(0) / len(dense_rewards) if dense_rewards else 1.0
            ),
            "val/reward/episode_reward_mean": (
                float(np.mean(episode_rewards)) if episode_rewards else 0.0
            ),
            "val/reward/success_rate": (
                float(np.mean(episode_successes)) if episode_successes else 0.0
            ),
            "val/reward/claim_done_rate": (
                float(np.mean(episode_claim_dones)) if episode_claim_dones else 0.0
            ),
        }

        # ---- group_status/* ----
        total_groups = len(uid2rewards)
        all_zero_groups = sum(1 for vals in uid2rewards.values() if all(v == 0 for v in vals))
        all_one_groups = sum(1 for vals in uid2rewards.values() if all(v == 1 for v in vals))
        zero_std_groups = sum(
            1
            for vals in uid2rewards.values()
            if len(vals) <= 1 or min(vals) == max(vals)
        )
        all_zero_ratio = all_zero_groups / total_groups if total_groups else 0.0
        all_one_ratio = all_one_groups / total_groups if total_groups else 0.0
        zero_std_ratio = zero_std_groups / total_groups if total_groups else 0.0

        group_metrics = {
            "val/group_status/mean_episode_len": (
                float(np.mean(episode_turns)) if episode_turns else 0.0
            ),
            "val/group_status/mean_rollout_length": (
                float(np.mean(rollout_lengths)) if rollout_lengths else 0.0
            ),
            "val/group_status/truncated_rollouts": (
                int(sum(truncated_flags)) if truncated_flags else 0
            ),
            "val/group_status/all_zero_groups": all_zero_groups,
            "val/group_status/all_zero_ratio": all_zero_ratio,
            "val/group_status/all_one_groups": all_one_groups,
            "val/group_status/all_one_ratio": all_one_ratio,
            "val/group_status/zero_std_groups": zero_std_groups,
            "val/group_status/zero_std_ratio": zero_std_ratio,
            "val/group_status/mean_ptc_count": (
                float(np.mean(ptc_counts)) if ptc_counts else 0.0
            ),
            "val/group_status/mean_ptc_error_count": (
                float(np.mean(ptc_error_counts)) if ptc_error_counts else 0.0
            ),
            "val/group_status/mean_python_count": (
                float(np.mean(python_counts)) if python_counts else 0.0
            ),
            "val/group_status/mean_terminal_count": (
                float(np.mean(terminal_counts)) if terminal_counts else 0.0
            ),
            "val/group_status/mean_env_tool_count": (
                float(np.mean(env_tool_counts)) if env_tool_counts else 0.0
            ),
            "val/length/mean_generated_tokens": (
                float(np.mean(generated_tokens)) if generated_tokens else 0.0
            ),
            "val/length/mean_thinking_tokens": (
                float(np.mean(thinking_tokens)) if thinking_tokens else 0.0
            ),
            "val/length/mean_ptc_code_tokens": (
                float(np.mean(ptc_code_tokens)) if ptc_code_tokens else 0.0
            ),
            "val/length/mean_tool_obs_tokens": (
                float(np.mean(tool_obs_tokens)) if tool_obs_tokens else 0.0
            ),
            "val/reward/mean_ptc_error_penalty": (
                float(np.mean(ptc_error_penalties)) if ptc_error_penalties else 0.0
            ),
        }

        metrics = {**reward_metrics, **group_metrics, "val/num_samples": float(len(dense_rewards))}
        return metrics

    # ------------------------------------------------------------------
    # Main fit loop
    # ------------------------------------------------------------------
    def fit(self):
        from verl.utils.tracking import Tracking

        tracking_logger = Tracking(
            project_name=self.config.trainer.project_name,
            experiment_name=self.config.trainer.experiment_name,
            default_backend=self.config.trainer.logger,
            config=OmegaConf.to_container(self.config, resolve=True),
        )

        self.global_steps = 0

        # Load checkpoint if any; update weights so rollout replicas wake up.
        self._load_checkpoint()
        self.checkpoint_manager.update_weights(self.global_steps)

        # Resume position comes from the checkpoint's training_state (epoch +
        # next batch index), NOT from ``global_steps // steps_per_epoch``: the
        # division breaks whenever global_steps and dataloader consumption
        # desync (e.g. filter_groups' continue path), and it carries no
        # intra-epoch position at all. The inner loop below fast-forwards past
        # already-trained batches of the resumed epoch; without that skip every
        # mid-epoch resume replayed the epoch from batch 0 (duplicate training
        # on the epoch head, tail of the data never seen before the
        # total_training_steps cap).
        current_epoch = self._resume_epoch

        if self.val_planning_dataset is not None and self.config.trainer.get("val_before_train", False):
            val_metrics = self._validate()
            if val_metrics:
                pprint(f"Initial validation metrics: {val_metrics}")
                tracking_logger.log(data=val_metrics, step=self.global_steps)
            if self.config.trainer.get("val_only", False):
                return

        progress_bar = tqdm(
            total=self.total_training_steps,
            initial=self.global_steps,
            desc="Training Progress",
        )

        self.global_steps += 1
        last_val_metrics = None
        self.max_steps_duration = 0

        batch = None
        num_prompt_in_batch = 0
        num_gen_batches = 0

        for epoch in range(current_epoch, self.config.trainer.total_epochs):
            self.planning_dataset.set_epoch(epoch)
            for batch_idx, _ in enumerate(self.train_dataloader):
                # Fast-forward to the resume point within the resumed epoch.
                # Skipped batches consume neither global_steps nor data: the
                # dataset state (rng + shuffled order) restored from the
                # checkpoint keeps get_batch(batch_idx) aligned, preserving the
                # invariant global_steps == epoch * steps_per_epoch + batch_idx + 1.
                if epoch == self._resume_epoch and batch_idx < self._resume_batch_idx:
                    continue
                self._current_epoch = epoch
                self._current_batch_idx = batch_idx
                metrics: dict = {}
                timing_raw: dict = {}
                num_gen_batches += 1

                is_last_step = self.global_steps >= self.total_training_steps

                with marked_timer("step", timing_raw):
                    # dense -> binary reward curriculum
                    dense_epoch = self.config.trainer.get("dense_epoch", 0)
                    if dense_epoch > 0:
                        self._effective_reward_type = (
                            "dense" if epoch < dense_epoch else "binary"
                        )
                        metrics["reward/reward_type"] = (
                            0.0 if self._effective_reward_type == "dense" else 1.0
                        )
                    else:
                        self._effective_reward_type = None

                    with marked_timer("gen", timing_raw, color="red"):
                        gen_batch_output = self._run_rollout(
                            dataset=self.planning_dataset,
                            batch_index=batch_idx,
                            validate=False,
                        )
                        # Sleep rollout replicas so trainer forward/backward gets the GPUs.
                        self.checkpoint_manager.sleep_replicas()
                        timing_raw.update(gen_batch_output.meta_info.get("timing", {}))
                        gen_batch_output.meta_info.pop("timing", None)

                    if gen_batch_output.batch is None or "input_ids" not in gen_batch_output.batch:
                        logger.warning(
                            f"Step {self.global_steps}: invalid batch, skipping training step"
                        )
                        self.checkpoint_manager.update_weights(self.global_steps)
                        progress_bar.update(1)
                        self.global_steps += 1
                        continue

                    new_batch_size = gen_batch_output.batch["input_ids"].shape[0]
                    if new_batch_size == 0:
                        logger.warning(
                            f"Step {self.global_steps}: empty batch, skipping training step"
                        )
                        self.checkpoint_manager.update_weights(self.global_steps)
                        progress_bar.update(1)
                        self.global_steps += 1
                        continue

                    new_batch = gen_batch_output

                    if "response_mask" not in new_batch.batch.keys():
                        new_batch.batch["response_mask"] = compute_response_mask(new_batch)

                    # Balance valid tokens across DP ranks so dynamic_bsz + MoE packing
                    # doesn't leave one rank starved / another OOM. Mirrors RayPPOTrainer.fit
                    # (ray_trainer.py:1397-1398). Changes row order -- safe because advantage
                    # computation groups by uid, not by position.
                    if self.config.trainer.get("balance_batch", True):
                        self._balance_batch(new_batch, metrics=metrics)

                    if "reward" not in new_batch.non_tensor_batch:
                        if "episode_reward" in new_batch.non_tensor_batch:
                            new_batch.non_tensor_batch["reward"] = (
                                new_batch.non_tensor_batch["episode_reward"].astype(np.float32)
                            )
                        else:
                            rewards_sum = new_batch.batch["token_level_rewards"].sum(dim=-1).numpy()
                            new_batch.non_tensor_batch["reward"] = rewards_sum.astype(np.float32)

                    prompt_uid2reward_vals = defaultdict(list)
                    for uid, reward_val in zip(
                        new_batch.non_tensor_batch["uid"],
                        new_batch.non_tensor_batch["reward"],
                        strict=True,
                    ):
                        prompt_uid2reward_vals[uid].append(reward_val)

                    total_groups = len(prompt_uid2reward_vals)
                    all_zero_groups = 0
                    all_one_groups = 0
                    zero_std_groups = 0
                    for _uid, reward_vals in prompt_uid2reward_vals.items():
                        if all(v == 0 for v in reward_vals):
                            all_zero_groups += 1
                        elif all(v == 1 for v in reward_vals):
                            all_one_groups += 1
                        # Any zero-variance group (identical rewards, incl.
                        # fractional dense scores) gets zero advantage in GRPO
                        # -- these samples contribute no gradient. Superset of
                        # all_zero/all_one under dense rewards.
                        if len(reward_vals) <= 1 or min(reward_vals) == max(reward_vals):
                            zero_std_groups += 1

                    all_zero_ratio = all_zero_groups / total_groups if total_groups else 0.0
                    all_one_ratio = all_one_groups / total_groups if total_groups else 0.0
                    zero_std_ratio = zero_std_groups / total_groups if total_groups else 0.0

                    def _mean_of(key: str) -> float:
                        arr = new_batch.non_tensor_batch.get(key)
                        if arr is None:
                            return 0.0
                        vals = arr.tolist() if hasattr(arr, "tolist") else list(arr)
                        return float(np.mean(vals)) if vals else 0.0

                    mean_ptc_count = _mean_of("programmatic_tool_call_count")
                    mean_ptc_error_count = _mean_of("programmatic_tool_call_error_count")
                    mean_ptc_error_penalty = _mean_of("ptc_error_penalty")
                    mean_python_count = _mean_of("execute_python_count")
                    mean_terminal_count = _mean_of("terminal_count")
                    mean_env_tool_count = _mean_of("env_tool_count")
                    mean_tool_call_parse_error_count = _mean_of("tool_call_parse_error_count")
                    # Token-budget breakdown of the response region (see
                    # TaskSyncAgentLoop._build_output for the accounting).
                    mean_generated_tokens = _mean_of("generated_tokens")
                    mean_thinking_tokens = _mean_of("thinking_tokens")
                    mean_ptc_code_tokens = _mean_of("ptc_code_tokens")
                    mean_tool_obs_tokens = _mean_of("tool_obs_tokens")

                    logger.info(
                        f"Group statistics: total={total_groups}, "
                        f"all_zero={all_zero_groups} ({all_zero_ratio:.2%}), "
                        f"all_one={all_one_groups} ({all_one_ratio:.2%}), "
                        f"zero_std={zero_std_groups} ({zero_std_ratio:.2%}), "
                        f"mean_ptc={mean_ptc_count:.2f}, mean_ptc_err={mean_ptc_error_count:.2f}, "
                        f"mean_ptc_penalty={mean_ptc_error_penalty:.4f}, "
                        f"mean_py={mean_python_count:.2f}, "
                        f"mean_term={mean_terminal_count:.2f}, mean_env_tool={mean_env_tool_count:.2f}, "
                        f"mean_parse_err={mean_tool_call_parse_error_count:.2f}"
                    )

                    metrics.update({
                        "group_status/all_zero_groups": all_zero_groups,
                        "group_status/all_zero_ratio": all_zero_ratio,
                        "group_status/all_one_groups": all_one_groups,
                        "group_status/all_one_ratio": all_one_ratio,
                        "group_status/zero_std_groups": zero_std_groups,
                        "group_status/zero_std_ratio": zero_std_ratio,
                        "group_status/mean_ptc_count": mean_ptc_count,
                        "group_status/mean_ptc_error_count": mean_ptc_error_count,
                        "group_status/mean_python_count": mean_python_count,
                        "group_status/mean_terminal_count": mean_terminal_count,
                        "group_status/mean_env_tool_count": mean_env_tool_count,
                        "group_status/mean_tool_call_parse_error_count": mean_tool_call_parse_error_count,
                        "length/mean_generated_tokens": mean_generated_tokens,
                        "length/mean_thinking_tokens": mean_thinking_tokens,
                        "length/mean_ptc_code_tokens": mean_ptc_code_tokens,
                        "length/mean_tool_obs_tokens": mean_tool_obs_tokens,
                        "reward/mean_ptc_error_penalty": mean_ptc_error_penalty,
                    })

                    # ============================
                    # Filter groups (optional)
                    # ============================
                    filter_groups_config = self.config.algorithm.get("filter_groups", {}) or {}
                    if not filter_groups_config.get("enable", False):
                        batch = new_batch
                    else:
                        metric_name = filter_groups_config.get("metric", "seq_final_reward")
                        if metric_name == "seq_final_reward":
                            new_batch.non_tensor_batch["seq_final_reward"] = (
                                new_batch.batch["token_level_rewards"].sum(dim=-1).numpy()
                            )
                        elif metric_name == "seq_reward":
                            new_batch.non_tensor_batch["seq_reward"] = (
                                new_batch.batch["token_level_scores"].sum(dim=-1).numpy()
                            )

                        prompt_uid2metric_vals = defaultdict(list)
                        for uid, metric_val in zip(
                            new_batch.non_tensor_batch["uid"],
                            new_batch.non_tensor_batch[metric_name],
                            strict=True,
                        ):
                            prompt_uid2metric_vals[uid].append(metric_val)

                        prompt_uid2metric_std = {
                            uid: np.std(vals) for uid, vals in prompt_uid2metric_vals.items()
                        }
                        kept_prompt_uids = [
                            uid
                            for uid, std in prompt_uid2metric_std.items()
                            if std > 0 or len(prompt_uid2metric_vals[uid]) == 1
                        ]
                        filtered_groups = total_groups - len(kept_prompt_uids)

                        metrics.update({
                            "filter_groups/kept_groups": len(kept_prompt_uids),
                            "filter_groups/filtered_groups": filtered_groups,
                        })

                        if len(kept_prompt_uids) == 0 and total_groups > 0:
                            logger.warning(
                                f"filter_groups: ALL {total_groups} groups filtered. "
                                f"Keeping all to avoid deadlock."
                            )
                            kept_prompt_uids = list(prompt_uid2metric_std.keys())

                        num_prompt_in_batch += len(kept_prompt_uids)

                        kept_idxs = [
                            idx
                            for idx, uid in enumerate(new_batch.non_tensor_batch["uid"])
                            if uid in set(kept_prompt_uids)
                        ]
                        new_batch = new_batch[kept_idxs]
                        new_batch.meta_info = {}
                        if batch is not None:
                            batch.meta_info = {}
                        batch = new_batch if batch is None else DataProto.concat([batch, new_batch])

                        prompt_bsz = self.config.data.train_batch_size
                        if num_prompt_in_batch < prompt_bsz:
                            max_num_gen_batches = filter_groups_config.get("max_num_gen_batches", 0)
                            if max_num_gen_batches <= 0 or num_gen_batches < max_num_gen_batches:
                                # wake rollout before continuing
                                self.checkpoint_manager.update_weights(self.global_steps)
                                continue
                            raise ValueError(
                                f"{num_gen_batches=} >= {max_num_gen_batches=}."
                            )
                        group_size = self.config.actor_rollout_ref.rollout.n
                        batch = batch[: prompt_bsz * group_size]

                    # Compute old log probs
                    with marked_timer("old_log_prob", timing_raw, color="blue"):
                        # The base RayPPOTrainer.fit() sets both of these on every
                        # iteration's batch BEFORE old_log_prob; our override doesn't,
                        # and the filter_groups branch above wipes meta_info to {}.
                        # - temperature: read unconditionally in Megatron forward_step
                        #   (workers/engine/megatron/transformer_impl.py:823).
                        # - global_token_num: engine_workers._postprocess_output only
                        #   writes the `mfu` metric when this is set; _compute_old_log_prob
                        #   then does `tu.get(output, "metrics")["mfu"]` (ray_trainer:1177).
                        batch.meta_info["temperature"] = (
                            self.config.actor_rollout_ref.rollout.temperature
                        )
                        batch.meta_info["global_token_num"] = torch.sum(
                            batch.batch["attention_mask"], dim=-1
                        ).tolist()
                        old_log_prob, old_log_prob_mfu = self._compute_old_log_prob(batch)
                        if "entropys" in old_log_prob.batch:
                            from verl.trainer.ppo.core_algos import agg_loss

                            entropys = old_log_prob.batch["entropys"]
                            response_masks = batch.batch["response_mask"]
                            actor_config = self.config.actor_rollout_ref.actor
                            entropy_agg = agg_loss(
                                loss_mat=entropys,
                                loss_mask=response_masks,
                                loss_agg_mode=actor_config.loss_agg_mode,
                                loss_scale_factor=actor_config.loss_scale_factor,
                            )
                            metrics.update({
                                "actor/entropy": entropy_agg.detach().item(),
                                "perf/mfu/actor_infer": old_log_prob_mfu,
                            })
                            old_log_prob.batch.pop("entropys")
                        batch = batch.union(old_log_prob)

                        assert "old_log_probs" in batch.batch, (
                            f'"old_log_probs" not in {list(batch.batch.keys())=}'
                        )

                        # Surface π_rollout vs π_old drift metrics (KL/PPL/pearson).
                        # Critical in async rollout mode where rollout weights lag
                        # behind the actor. Mirrors ray_trainer.py:1459-1463.
                        if "rollout_log_probs" in batch.batch.keys():
                            from verl.utils.debug.metrics import calculate_debug_metrics

                            metrics.update(calculate_debug_metrics(batch))

                    if self.use_reference_policy:
                        with marked_timer("ref", timing_raw, color="yellow"):
                            ref_log_prob = self._compute_ref_log_prob(batch)
                            batch = batch.union(ref_log_prob)

                    if self.config.algorithm.use_kl_in_reward:
                        batch, kl_metrics = apply_kl_penalty(
                            batch,
                            kl_ctrl=self.kl_ctrl_in_reward,
                            kl_penalty=self.config.algorithm.kl_penalty,
                        )
                        metrics.update(kl_metrics)
                    else:
                        batch.batch["token_level_rewards"] = batch.batch["token_level_scores"]

                    # Rollout correction (optional)
                    rollout_corr_config = self.config.algorithm.get("rollout_correction", None)
                    if (
                        rollout_corr_config is not None
                        and "rollout_log_probs" in batch.batch
                    ):
                        with marked_timer("rollout_corr", timing_raw, color="cyan"):
                            from verl.trainer.ppo.rollout_corr_helper import (
                                compute_rollout_correction_and_add_to_batch,
                            )
                            batch, rollout_corr_metrics = compute_rollout_correction_and_add_to_batch(
                                batch, rollout_corr_config
                            )
                            metrics.update(rollout_corr_metrics)

                    batch = compute_advantage(
                        batch,
                        adv_estimator=self.config.algorithm.adv_estimator,
                        gamma=self.config.algorithm.gamma,
                        lam=self.config.algorithm.lam,
                        num_repeat=self.config.actor_rollout_ref.rollout.get("n", 1),
                        norm_adv_by_std_in_grpo=self.config.algorithm.get(
                            "norm_adv_by_std_in_grpo", True
                        ),
                        config=self.config.algorithm,
                    )

                    batch.meta_info["global_token_num"] = torch.sum(
                        batch.batch["attention_mask"], dim=-1
                    ).tolist()

                    if self.global_steps > self.config.trainer.get("critic_warmup", 0):
                        with marked_timer("update_actor", timing_raw, color="green"):
                            actor_output = self._update_actor(batch)
                        actor_output_metrics = reduce_metrics(actor_output.meta_info["metrics"])
                        metrics.update(actor_output_metrics)

                    # Save checkpoint BEFORE waking rollout (so ckpt path is stable).
                    if self.config.trainer.save_freq > 0 and (
                        is_last_step or self.global_steps % self.config.trainer.save_freq == 0
                    ):
                        with marked_timer("save_checkpoint", timing_raw, color="green"):
                            self._save_checkpoint()

                    # Wake rollout + update weights for next iteration.
                    with marked_timer("update_weights", timing_raw, color="red"):
                        self.checkpoint_manager.update_weights(self.global_steps)

                # end marked_timer("step")

                # Stats / metrics
                metrics.update(gen_batch_output.meta_info.get("planning_stats", {}))
                metrics.update(compute_timing_metrics(batch, timing_raw))
                metrics.update(compute_data_metrics(batch, use_critic=self.use_critic))
                # perf/samples_per_sec, perf/tokens_per_sec, etc.
                n_gpus = self.resource_pool_manager.get_n_gpus()
                metrics.update(
                    compute_throughout_metrics(batch=batch, timing_raw=timing_raw, n_gpus=n_gpus)
                )
                # advantage/reward variance vs. grad norm -- health signal for GSPO/GRPO.
                gradient_norm = metrics.get("actor/grad_norm", None)
                metrics.update(
                    compute_variance_proxy_metrics(batch=batch, gradient_norm=gradient_norm)
                )
                metrics["train/num_gen_batches"] = num_gen_batches
                metrics["training/global_step"] = self.global_steps
                metrics["training/epoch"] = epoch

                # reset batch accumulation
                batch = None
                num_prompt_in_batch = 0
                num_gen_batches = 0

                # Validation
                if (
                    self.val_planning_dataset is not None
                    and self.config.trainer.test_freq > 0
                    and self.global_steps % self.config.trainer.test_freq == 0
                ):
                    val_metrics = self._validate()
                    if val_metrics:
                        last_val_metrics = val_metrics
                        metrics.update(val_metrics)

                tracking_logger.log(data=metrics, step=self.global_steps)

                progress_bar.update(1)
                self.global_steps += 1

                if is_last_step:
                    pprint(f"Final validation metrics: {last_val_metrics}")
                    progress_bar.close()
                    return

        # Loop exhausted before hitting total_training_steps — persist a final ckpt.
        if self.config.trainer.save_freq > 0:
            self._save_checkpoint()
        pprint(f"Final validation metrics: {last_val_metrics}")
        progress_bar.close()

    # ------------------------------------------------------------------
    # Rollout driver
    # ------------------------------------------------------------------
    def _run_rollout(
        self, dataset: TaskSyncDataset, batch_index: int, validate: bool = False
    ) -> Optional[DataProto]:
        generate_st = time.time()

        env_groups = dataset.get_batch(batch_index)

        raw_prompts = []
        task_uids = []
        for group_idx, group_builder in enumerate(env_groups):
            task_info = group_builder.task_info
            task_name = task_info.get("task_name", "unknown")
            task_uid = f"{task_name}_{group_idx}_{self.ptc_mode}"
            for _ in range(group_builder.num_envs):
                raw_prompts.append({
                    "task_info": task_info,
                    "max_tool_calls": group_builder.max_tool_calls,
                    "ptc_desc": self.ptc_desc,
                })
                task_uids.append(task_uid)

        if not raw_prompts:
            logger.warning("No tasks to process, returning empty batch")
            return self._create_empty_batch()

        batch_size = len(raw_prompts)
        size_divisor = max(1, self.config.actor_rollout_ref.rollout.agent.num_workers)
        padded_batch_size = ((batch_size + size_divisor - 1) // size_divisor) * size_divisor
        padding_needed = padded_batch_size - batch_size

        if padding_needed > 0:
            raw_prompts.extend([raw_prompts[0]] * padding_needed)
            task_uids.extend([task_uids[0]] * padding_needed)

        non_tensor_batch = {
            "raw_prompt": np.array(raw_prompts, dtype=object),
        }

        effective_reward_type = getattr(self, "_effective_reward_type", None)
        if effective_reward_type is not None:
            non_tensor_batch["reward_type"] = np.array(
                [effective_reward_type] * len(raw_prompts), dtype=object
            )

        data = DataProto(
            batch=TensorDict({}, batch_size=[len(raw_prompts)]),
            non_tensor_batch=non_tensor_batch,
            meta_info={
                "global_steps": self.global_steps,
                "validate": validate,
            },
        )

        output = self.async_rollout_manager.generate_sequences(data)

        # Strip padding
        if padding_needed > 0 and output.batch is not None:
            for key in list(output.batch.keys()):
                output.batch[key] = output.batch[key][:batch_size]
            output.batch = TensorDict(
                {k: v for k, v in output.batch.items()},
                batch_size=torch.Size([batch_size]),
            )
            if output.non_tensor_batch:
                for key in list(output.non_tensor_batch.keys()):
                    arr = output.non_tensor_batch[key]
                    if isinstance(arr, np.ndarray):
                        output.non_tensor_batch[key] = arr[:batch_size]
            task_uids = task_uids[:batch_size]

        # Extract reward metrics
        episode_rewards, episode_successes, dense_rewards, episode_turns = [], [], [], []
        rollout_lengths, truncated_flags, ptc_counts = [], [], []
        claim_done_flags = []

        if output.non_tensor_batch:
            ntb = output.non_tensor_batch
            if "episode_reward" in ntb:
                episode_rewards = ntb["episode_reward"].tolist()
            if "episode_success" in ntb:
                episode_successes = ntb["episode_success"].tolist()
            if "episode_claim_done" in ntb:
                claim_done_flags = ntb["episode_claim_done"].tolist()
            if "dense_reward" in ntb:
                dense_rewards = ntb["dense_reward"].tolist()
            if "episode_turns" in ntb:
                episode_turns = ntb["episode_turns"].tolist()
            if "rollout_length" in ntb:
                rollout_lengths = ntb["rollout_length"].tolist()
            if "truncated" in ntb:
                truncated_flags = ntb["truncated"].tolist()
            if "programmatic_tool_call_count" in ntb:
                ptc_counts = ntb["programmatic_tool_call_count"].tolist()

        # Token-level scores for GRPO advantage computation
        if output.batch is not None and "response_mask" in output.batch:
            response_mask = output.batch["response_mask"]
            response_length = response_mask.shape[-1]

            scalar_rewards = (
                [float(r) for r in episode_rewards]
                if episode_rewards
                else [0.0] * batch_size
            )

            token_level_scores = torch.zeros(
                (batch_size, response_length), dtype=torch.float32
            )
            for i, reward in enumerate(scalar_rewards):
                valid_positions = response_mask[i].nonzero()
                if len(valid_positions) > 0:
                    last_pos = valid_positions[-1].item()
                    token_level_scores[i, last_pos] = reward
                else:
                    token_level_scores[i, -1] = reward

            output.batch["token_level_scores"] = token_level_scores
            output.batch["token_level_rewards"] = token_level_scores.clone()
            output.non_tensor_batch["uid"] = np.array(task_uids, dtype=object)

        output.meta_info["timing"] = {"actor_time": time.time() - generate_st}
        planning_stats = {
            "group_status/mean_episode_len": float(np.mean(episode_turns)) if episode_turns else 0.0,
            "group_status/mean_rollout_length": float(np.mean(rollout_lengths)) if rollout_lengths else 0.0,
            "group_status/truncated_rollouts": int(sum(truncated_flags)) if truncated_flags else 0,
            "reward/score": float(np.mean(dense_rewards)) if dense_rewards else 0.0,
            "reward/score_min": float(np.min(dense_rewards)) if dense_rewards else 0.0,
            "reward/score_max": float(np.max(dense_rewards)) if dense_rewards else 0.0,
            "reward/zero_reward_ratio": (
                dense_rewards.count(0) / len(dense_rewards) if dense_rewards else 1.0
            ),
            "reward/episode_reward_mean": (
                float(np.mean(episode_rewards)) if episode_rewards else 0.0
            ),
            "reward/success_rate": (
                float(np.mean(episode_successes)) if episode_successes else 0.0
            ),
            # Fraction of rollouts that reached claim_done at all (regardless
            # of score) -- success_rate is conditioned on solving the task.
            "reward/claim_done_rate": (
                float(np.mean(claim_done_flags)) if claim_done_flags else 0.0
            ),
        }
        output.meta_info["planning_stats"] = planning_stats

        if not validate:
            logger.info(
                f"Rollout done: bsz={batch_size}, success_rate={planning_stats['reward/success_rate']:.2%}, "
                f"score={planning_stats['reward/score']:.4f}, "
                f"episode_reward={planning_stats['reward/episode_reward_mean']:.4f}, "
                f"mean_rollout_length={planning_stats['group_status/mean_rollout_length']:.1f}, "
                f"truncated={planning_stats['group_status/truncated_rollouts']}, "
                f"mean_ptc={np.mean(ptc_counts) if ptc_counts else 0:.2f}"
            )

        # Dump experience for training rollouts only. Keyed on global_steps
        # (restored from the checkpoint on resume) rather than a local step
        # counter, so dumps continue numbering across resumes instead of
        # restarting at 0 and overwriting the earlier run's files.
        if (
            not validate
            and self.dump_experience_every > 0
            and self.global_steps % self.dump_experience_every == 0
        ):
            self._dump_experience(
                output=output,
                raw_prompts=raw_prompts[:batch_size],
                task_uids=task_uids[:batch_size],
                episode_rewards=episode_rewards,
                episode_successes=episode_successes,
                episode_turns=episode_turns,
            )

        return output

    def _create_empty_batch(self) -> DataProto:
        prompt_length = self.config.actor_rollout_ref.rollout.get("prompt_length", 8192)
        response_length = self.config.actor_rollout_ref.rollout.get("response_length", 4096)
        total_length = prompt_length + response_length

        batch = TensorDict(
            {
                "input_ids": torch.zeros((0, total_length), dtype=torch.long),
                "prompts": torch.zeros((0, prompt_length), dtype=torch.long),
                "responses": torch.zeros((0, response_length), dtype=torch.long),
                "attention_mask": torch.zeros((0, total_length), dtype=torch.long),
                "position_ids": torch.zeros((0, total_length), dtype=torch.long),
                "response_mask": torch.zeros((0, response_length), dtype=torch.long),
                "token_level_scores": torch.zeros((0, response_length), dtype=torch.float32),
                "token_level_rewards": torch.zeros((0, response_length), dtype=torch.float32),
            },
            batch_size=torch.Size([0]),
        )
        return DataProto(
            batch=batch,
            non_tensor_batch={"uid": np.array([], dtype=object)},
            meta_info={},
        )

    # ------------------------------------------------------------------
    # Checkpointing
    # ------------------------------------------------------------------
    def _save_checkpoint(self):
        from verl.utils.fs import local_mkdir_safe

        local_global_step_folder = os.path.join(
            self.config.trainer.default_local_dir, f"global_step_{self.global_steps}"
        )
        actor_local_path = os.path.join(local_global_step_folder, "actor")
        actor_remote_path = (
            None
            if self.config.trainer.default_hdfs_dir is None
            else os.path.join(
                self.config.trainer.default_hdfs_dir,
                f"global_step_{self.global_steps}",
                "actor",
            )
        )

        remove_previous_ckpt_in_save = self.config.trainer.get("remove_previous_ckpt_in_save", False)
        max_actor_ckpt_to_keep = (
            self.config.trainer.get("max_actor_ckpt_to_keep", None)
            if not remove_previous_ckpt_in_save
            else 1
        )

        self.actor_rollout_wg.save_checkpoint(
            actor_local_path,
            actor_remote_path,
            self.global_steps,
            max_ckpt_to_keep=max_actor_ckpt_to_keep,
        )

        local_mkdir_safe(local_global_step_folder)
        training_state = {
            "epoch": getattr(self, "_current_epoch", 0),
            "batch_idx": getattr(self, "_current_batch_idx", 0),
            "dataset_state": self.planning_dataset.state_dict(),
        }
        torch.save(training_state, os.path.join(local_global_step_folder, "training_state.pt"))
        logger.info(
            f"Saved training state: epoch={training_state['epoch']}, "
            f"batch_idx={training_state['batch_idx']}, global_steps={self.global_steps}"
        )

        actor_ckpt_cfg = self.config.actor_rollout_ref.actor.checkpoint
        async_save = (
            (hasattr(actor_ckpt_cfg, "async_save") and actor_ckpt_cfg.async_save)
            or ("async_save" in actor_ckpt_cfg and actor_ckpt_cfg["async_save"])
        )
        if async_save:
            return

        with open(
            os.path.join(self.config.trainer.default_local_dir, "latest_checkpointed_iteration.txt"),
            "w",
        ) as f:
            f.write(str(self.global_steps))

    def _load_checkpoint(self):
        from verl.utils.checkpoint.checkpoint_manager import find_latest_ckpt_path

        self._resume_epoch = 0
        self._resume_batch_idx = 0
        self._current_epoch = 0
        self._current_batch_idx = 0

        if self.config.trainer.resume_mode == "disable":
            return 0

        if self.config.trainer.default_hdfs_dir is not None:
            raise NotImplementedError("load from hdfs is not implemented yet")

        checkpoint_folder = self.config.trainer.default_local_dir
        if not os.path.isabs(checkpoint_folder):
            checkpoint_folder = os.path.join(os.getcwd(), checkpoint_folder)
        global_step_folder = find_latest_ckpt_path(checkpoint_folder)

        if self.config.trainer.resume_mode == "auto":
            if global_step_folder is None:
                logger.info("Training from scratch")
                return 0
        elif self.config.trainer.resume_mode == "resume_path":
            assert isinstance(self.config.trainer.resume_from_path, str)
            assert "global_step_" in self.config.trainer.resume_from_path
            global_step_folder = self.config.trainer.resume_from_path
            if not os.path.isabs(global_step_folder):
                global_step_folder = os.path.join(os.getcwd(), global_step_folder)

        logger.info(f"Load from checkpoint folder: {global_step_folder}")
        self.global_steps = int(global_step_folder.split("global_step_")[-1])

        actor_path = os.path.join(global_step_folder, "actor")
        self.actor_rollout_wg.load_checkpoint(
            actor_path, del_local_after_load=self.config.trainer.del_local_ckpt_after_load
        )

        training_state_path = os.path.join(global_step_folder, "training_state.pt")
        if os.path.exists(training_state_path):
            training_state = torch.load(training_state_path, weights_only=False)
            self._resume_epoch = training_state["epoch"]
            self._resume_batch_idx = training_state["batch_idx"] + 1
            if "dataset_state" in training_state:
                self.planning_dataset.load_state_dict(training_state["dataset_state"])
                # Older checkpoints did not store the dataset epoch.
                if "epoch" not in training_state["dataset_state"]:
                    self.planning_dataset.epoch = training_state["epoch"]
        else:
            steps_per_epoch = len(self.planning_dataset)
            self._resume_epoch = self.global_steps // max(1, steps_per_epoch)
            self._resume_batch_idx = self.global_steps % max(1, steps_per_epoch)
            logger.warning(
                f"No training_state.pt found, estimating resume position from global_steps"
            )

        # Carry: a checkpoint on an epoch's last batch means "resume at the
        # next epoch's batch 0", otherwise fit()'s fast-forward would skip the
        # whole (already finished) epoch's worth of batches... of the wrong
        # epoch. steps_per_epoch mirrors len(train_dataloader) in fit().
        steps_per_epoch = max(1, len(self.planning_dataset))
        if self._resume_batch_idx >= steps_per_epoch:
            self._resume_epoch += 1
            self._resume_batch_idx = 0
        logger.info(
            f"Restored training state: resume_epoch={self._resume_epoch}, "
            f"resume_batch_idx={self._resume_batch_idx}, global_steps={self.global_steps}"
        )

    # ------------------------------------------------------------------
    # Experience dumping
    # ------------------------------------------------------------------
    def _dump_experience(
        self,
        output: DataProto,
        raw_prompts: list[dict],
        task_uids: list[str],
        episode_rewards: list[float],
        episode_successes: list[bool],
        episode_turns: list[int],
    ):
        try:
            experiences: dict = {}
            batch_size = len(raw_prompts)
            ntb = output.non_tensor_batch or {}

            messages_arr = ntb.get("messages", None)
            tool_rewards_arr = ntb.get("tool_rewards", None)
            reward_extra_infos = list(ntb["reward_extra_info"]) if "reward_extra_info" in ntb else []

            for i in range(batch_size):
                task_info = raw_prompts[i].get("task_info", {})
                task_name = task_info.get("task_name", f"unknown_{i}")
                episode_key = f"episode_{i}_{task_name}"

                episode_data = {
                    "task_name": task_name,
                    "task_uid": task_uids[i] if i < len(task_uids) else None,
                    "reward": episode_rewards[i] if i < len(episode_rewards) else 0.0,
                    "success": bool(episode_successes[i]) if i < len(episode_successes) else False,
                    "num_turns": episode_turns[i] if i < len(episode_turns) else 0,
                }

                if messages_arr is not None and i < len(messages_arr) and messages_arr[i] is not None:
                    episode_data["messages"] = (
                        list(messages_arr[i])
                        if hasattr(messages_arr[i], "__iter__")
                        else messages_arr[i]
                    )

                if (
                    tool_rewards_arr is not None
                    and i < len(tool_rewards_arr)
                    and tool_rewards_arr[i] is not None
                ):
                    episode_data["tool_rewards"] = (
                        list(tool_rewards_arr[i])
                        if hasattr(tool_rewards_arr[i], "__iter__")
                        else tool_rewards_arr[i]
                    )

                if "messages" not in episode_data and i < len(reward_extra_infos):
                    extra = reward_extra_infos[i]
                    if isinstance(extra, dict):
                        if "messages" in extra:
                            episode_data["messages"] = extra["messages"]
                        if "tool_rewards" in extra:
                            episode_data["tool_rewards"] = extra["tool_rewards"]

                experiences[episode_key] = episode_data

            dump_path = os.path.join(
                self.game_state_save_path,
                f"actor{self.actor_id}_step{self.global_steps}.json",
            )
            with open(dump_path, "w", encoding="utf-8") as f:
                json.dump(experiences, f, indent=2, default=str, ensure_ascii=False)

            logger.info(f"Dumped {len(experiences)} experiences to {dump_path}")
        except Exception as e:
            logger.warning(f"Failed to dump experience: {e}")
