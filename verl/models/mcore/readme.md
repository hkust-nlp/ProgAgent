# Megatron model integration

This directory contains model configuration, forward, and weight-conversion
adapters for Megatron-Core. Bridge selection uses the Megatron configuration:
`use_mbridge` enables bridge loading, and `vanilla_mbridge` selects mbridge versus
Megatron-Bridge. Match the model architecture across the bridge and rollout engine.

- [bridge.py](bridge.py) and [mbridge.py](mbridge.py): Bridge integration.
- [registry.py](registry.py): Architecture registration.
- [config_converter.py](config_converter.py): Model configuration conversion.
- [loader.py](loader.py), [saver.py](saver.py), and
  [weight_converter.py](weight_converter.py): Weight handling.

ProgAgent's Qwen3-8B/14B recipes need model preparation and the mbridge YaRN patch.
See the [training guide](../../../ptc_training_recipe/README.md).
Offline conversion is available in [converter_hf_to_mcore.py](../../../scripts/converter_hf_to_mcore.py).
