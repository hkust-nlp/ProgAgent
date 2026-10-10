# Models

Model implementations, registries, and weight-loading adapters used by verl.

- [transformers/](transformers/): Transformers integrations.
- [mcore/](mcore/readme.md): Megatron model conversion and bridge integration.
- [diffusers_model/](diffusers_model/): Diffusion model support.
- [registry.py](registry.py): Model registration.
- [weight_loader_registry.py](weight_loader_registry.py): Weight-loader registration.

For a new architecture, check both training-backend and rollout-engine support,
then verify weight conversion and packed-input behavior against the source model.
