# Experimental VLA training

Upstream experiments for SimpleVLA-OFT with Libero/Mujoco and IsaacSim.
This module is independent of ProgAgent's tool-use training.

The implementation still references legacy worker modules removed from this
repository and requires migration to the unified model engine before use.
The repository's compile check excludes this directory.

Simulation requires its own dependencies and GPU resources; IsaacSim requires
RT-capable GPUs. Training code is provided here for development, without a
validated launch recipe in this trimmed repository.
