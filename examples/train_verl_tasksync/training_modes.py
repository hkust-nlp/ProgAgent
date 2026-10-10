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


"""Select TaskSync tool access consistently for shell and Hydra entry points."""


def configure_training_mode(config) -> None:
    """Validate the public mode and select the loop that enforces its semantics."""
    mode = config.actor_rollout_ref.env.get("ptc_mode", "hybrid")
    if mode not in ("ptc", "hybrid", "dtc"):
        raise ValueError(f"ptc_mode must be ptc, hybrid, or dtc, got {mode!r}")
    config.actor_rollout_ref.rollout.agent.default_agent_loop = (
        "tasksync_ptc_agent" if mode == "ptc" else "tasksync_agent"
    )
