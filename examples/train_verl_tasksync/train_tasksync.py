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

"""Entry script for training on task-sync style environments with VeRL 0.7.1.

Usage:
    python -m examples.train_verl_tasksync.train_tasksync \
        --config-path=./config \
        --config-name=tasksync_grpo_megatron \
        data.train_files=/path/to/tasksync/envs
"""

import logging
import os
import socket
from pprint import pprint

import hydra
import ray
from omegaconf import OmegaConf

from verl.experimental.reward_loop import migrate_legacy_reward_impl
from verl.single_controller.ray import RayWorkerGroup
from verl.trainer.constants_ppo import get_ppo_ray_runtime_env
from verl.trainer.distillation import is_distillation_enabled
from verl.trainer.ppo.ray_trainer import ResourcePoolManager, Role
from verl.trainer.ppo.utils import need_critic, need_reference_policy
from verl.utils.config import validate_config
from verl.utils.device import auto_set_device, is_cuda_available

from .tasksync_trainer import TaskSyncTrainer
from .training_modes import configure_training_mode

logger = logging.getLogger(__name__)


@ray.remote(num_cpus=1)
class TaskRunner:
    """Ray remote class that runs the task-sync training loop.

    Mirrors ``verl.trainer.main_ppo.TaskRunner`` but swaps in
    ``TaskSyncTrainer`` and skips real dataset creation.
    """

    def run(self, config):
        from verl.utils import hf_processor, hf_tokenizer
        from verl.utils.fs import copy_to_local

        print(f"TaskRunner hostname: {socket.gethostname()}, PID: {os.getpid()}")
        pprint(OmegaConf.to_container(config, resolve=True))
        OmegaConf.resolve(config)

        # Worker + role wiring
        from verl.workers.engine_workers import ActorRolloutRefWorker

        role_worker_mapping = {}
        mapping = {}

        lora_rank = config.actor_rollout_ref.model.get("lora", {}).get("rank", 0)
        if lora_rank <= 0:
            lora_rank = config.actor_rollout_ref.model.get("lora_rank", 0)
        ref_in_actor = lora_rank > 0 or config.actor_rollout_ref.model.get("lora_adapter_path") is not None
        if need_reference_policy(config) and not ref_in_actor:
            actor_role = Role.ActorRolloutRef
        else:
            actor_role = Role.ActorRollout

        role_worker_mapping[actor_role] = ray.remote(ActorRolloutRefWorker)
        mapping[actor_role] = "global_pool"

        # Resource pool spec
        global_pool_id = "global_pool"
        resource_pool_spec = {
            global_pool_id: [config.trainer.n_gpus_per_node] * config.trainer.nnodes,
        }
        if config.reward.reward_model.enable and config.reward.reward_model.enable_resource_pool:
            if config.reward.reward_model.n_gpus_per_node <= 0:
                raise ValueError("reward.reward_model.n_gpus_per_node must be > 0")
            if config.reward.reward_model.nnodes <= 0:
                raise ValueError("reward.reward_model.nnodes must be > 0")
            reward_pool = (
                [config.reward.reward_model.n_gpus_per_node] * config.reward.reward_model.nnodes
            )
            resource_pool_spec["reward_pool"] = reward_pool
            mapping[Role.RewardModel] = "reward_pool"
        elif config.reward.reward_model.enable:
            mapping[Role.RewardModel] = "global_pool"
        else:
            config.reward.reward_model.nnodes = config.trainer.nnodes
            config.reward.reward_model.n_gpus_per_node = config.trainer.n_gpus_per_node

        distillation_config = config.get("distillation")
        if is_distillation_enabled(distillation_config):
            if distillation_config.n_gpus_per_node <= 0:
                raise ValueError("distillation.n_gpus_per_node must be > 0")
            if distillation_config.nnodes <= 0:
                raise ValueError("distillation.nnodes must be > 0")
            resource_pool_spec["teacher_pool"] = (
                [distillation_config.n_gpus_per_node] * distillation_config.nnodes
            )
            mapping[Role.TeacherModel] = "teacher_pool"

        resource_pool_manager = ResourcePoolManager(
            resource_pool_spec=resource_pool_spec, mapping=mapping
        )

        # Validate config
        validate_config(
            config=config,
            use_reference_policy=need_reference_policy(config),
            use_critic=need_critic(config),
        )

        # Tokenizer + processor
        local_path = copy_to_local(
            config.actor_rollout_ref.model.path,
            use_shm=config.actor_rollout_ref.model.get("use_shm", False),
        )
        trust_remote_code = config.data.get("trust_remote_code", False)
        tokenizer = hf_tokenizer(local_path, trust_remote_code=trust_remote_code)
        processor = hf_processor(local_path, trust_remote_code=trust_remote_code, use_fast=True)

        trainer = TaskSyncTrainer(
            config=config,
            tokenizer=tokenizer,
            processor=processor,
            role_worker_mapping=role_worker_mapping,
            resource_pool_manager=resource_pool_manager,
            ray_worker_group_cls=RayWorkerGroup,
            device_name=config.trainer.get("device", "cuda"),
        )
        trainer.init_workers()
        trainer.fit()


def run_training(config) -> None:
    configure_training_mode(config)
    auto_set_device(config)
    config = migrate_legacy_reward_impl(config)

    if not ray.is_initialized():
        default_runtime_env = get_ppo_ray_runtime_env()
        ray_init_kwargs = config.get("ray_kwargs", {}).get("ray_init", {})
        runtime_env_kwargs = ray_init_kwargs.get("runtime_env", {})
        runtime_env = OmegaConf.merge(default_runtime_env, runtime_env_kwargs)
        ray_init_kwargs = OmegaConf.create({**ray_init_kwargs, "runtime_env": runtime_env})
        ray.init(**OmegaConf.to_container(ray_init_kwargs))

    if (
        is_cuda_available
        and OmegaConf.select(config, "global_profiler.tool") == "nsys"
        and OmegaConf.select(config, "global_profiler.steps") is not None
        and len(OmegaConf.select(config, "global_profiler.steps", default=[])) > 0
    ):
        nsight_options = OmegaConf.to_container(
            config.global_profiler.global_tool_config.nsys.controller_nsight_options
        )
        runner = TaskRunner.options(runtime_env={"nsight": nsight_options}).remote()
    else:
        runner = TaskRunner.remote()

    ray.get(runner.run.remote(config))

    timeline_json_file = config.get("ray_kwargs", {}).get("timeline_json_file", None)
    if timeline_json_file:
        ray.timeline(filename=timeline_json_file)


@hydra.main(config_path="./config", config_name="tasksync_grpo_megatron", version_base=None)
def main(config):
    run_training(config)


if __name__ == "__main__":
    main()
