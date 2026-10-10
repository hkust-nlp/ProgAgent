#!/usr/bin/env python3
# Copyright 2026 The TaskSync Authors
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

"""Prepare a local official Qwen3-8B/14B model with the project's XML template and YaRN.

Uses only the standard library and a bundled template; never loads model weights.
Optionally applies the training-environment mbridge patch through the same CLI.
"""

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent / "templates" / "qwen3_ptc.jinja"
CONTEXT_LENGTH = 131072
YARN = {"rope_type": "yarn", "factor": 4.0, "original_max_position_embeddings": 32768}
BACKUP_SUFFIX = ".before-ptc"


def planned_updates(model_dir: Path) -> dict[Path, bytes]:
    """Validate dense model identity and build metadata replacements before writing."""
    config_path = model_dir / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("model_type") != "qwen3":
        raise ValueError("This script is for dense Qwen3 models, not Qwen3-Coder.")
    tokenizer_path = model_dir / "tokenizer_config.json"
    tokenizer = json.loads(tokenizer_path.read_text(encoding="utf-8"))
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    config["max_position_embeddings"] = CONTEXT_LENGTH
    # Keep Transformers 4's spelling and Transformers 5's spelling consistent.
    # Replace the whole mapping to remove conflicting attention_factor overrides.
    config["rope_scaling"] = dict(YARN)
    config["rope_parameters"] = {**YARN, "rope_theta": config.get("rope_theta", 1000000)}
    tokenizer["model_max_length"] = CONTEXT_LENGTH
    tokenizer["chat_template"] = template
    return {
        config_path: (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode(),
        tokenizer_path: (json.dumps(tokenizer, ensure_ascii=False, indent=2) + "\n").encode(),
        model_dir / "chat_template.jinja": template.encode(),
    }


def replace_file(path: Path, content: bytes, backup_suffix: str = BACKUP_SUFFIX) -> None:
    """Back up once and atomically replace the directory entry, including HF symlinks."""
    backup = path.with_name(path.name + backup_suffix)
    if path.exists() and not backup.exists():
        backup.write_bytes(path.read_bytes())
    # Replacing the entry, rather than writing through it, preserves HF cache
    # blobs when the model directory contains snapshot symlinks.
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ptc-", delete=False) as f:
        temp_path = Path(f.name)
        f.write(content)
    try:
        os.chmod(temp_path, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def prepare_model(model_dir: Path, *, check: bool = False) -> list[Path]:
    """Apply template and YaRN metadata, or return differences without modifying files."""
    updates = planned_updates(model_dir)
    changed = [p for p, data in updates.items() if not p.exists() or p.read_bytes() != data]
    for path in changed:
        if not check:
            replace_file(path, updates[path])
        print(f"[{'needs update' if check else 'updated'}] {path}")
    if not changed:
        print(f"[already prepared] {model_dir}")
    return changed


MARKER = "# YARN_PATCH_APPLIED_V2"

PATCHED_METHOD = '''    def _build_config(self):
        {marker}
        """Match the rollout's YaRN frequencies and attention scale."""
        config = self._build_base_config(qk_layernorm=True)
        rs = getattr(self.hf_config, "rope_parameters", None) or getattr(self.hf_config, "rope_scaling", None)
        if rs and (rs.get("rope_type") or rs.get("type")) == "yarn":
            config.position_embedding_type = "yarn"
            config.yarn_rotary_scaling_factor = float(rs["factor"])
            config.yarn_original_max_position_embeddings = int(
                rs["original_max_position_embeddings"]
            )
            config.yarn_beta_fast = float(rs.get("beta_fast", 32.0))
            config.yarn_beta_slow = float(rs.get("beta_slow", 1.0))
            config.yarn_mscale = float(rs.get("mscale", 1.0))
            config.yarn_mscale_all_dim = float(rs.get("mscale_all_dim", 0.0))
            config.yarn_correction_range_round_to_int = True
            # REQUIRED: the fused THD RoPE kernel does not apply mscale and would
            # silently drop it under sequence packing -> rollout/training mismatch.
            config.apply_rope_fusion = False
        return config
'''.format(marker=MARKER)

# Matches the stock method: `def _build_config(self):` ... up to and including the
# `return self._build_base_config( ... )` call (single call, no nested parens).
STOCK_RE = re.compile(
    r"[ \t]*def _build_config\(self\):.*?return self\._build_base_config\([^)]*\)\n",
    re.DOTALL,
)


def patch_mbridge(*, check: bool = False) -> bool:
    """Patch the installed dense Qwen3 bridge to use YaRN instead of linear RoPE."""
    # Locate mbridge without importing its GPU dependencies.
    spec = importlib.util.find_spec("mbridge")
    if spec is None or not spec.submodule_search_locations:
        raise ValueError("Install mbridge in this Python environment first.")
    path = Path(next(iter(spec.submodule_search_locations))) / "models" / "qwen3.py"
    src = path.read_text(encoding="utf-8")
    if MARKER in src:
        print(f"[already patched] {path}")
        return False
    if check:
        print(f"[needs patch] {path}")
        return True

    match = STOCK_RE.search(src)
    if match is None:
        raise ValueError(f"Cannot find the expected _build_config method in {path}")
    new_src = src[: match.start()] + PATCHED_METHOD + src[match.end() :]
    compile(new_src, str(path), "exec")
    replace_file(path, new_src.encode("utf-8"), backup_suffix=".orig")
    for pyc in (path.parent / "__pycache__").glob("qwen3.*.pyc"):
        pyc.unlink()
    print(f"[patched] {path}")
    return True


def main(argv=None) -> int:
    """Expose model preparation and the optional mbridge patch through one command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path, help="Local official Qwen3-8B or Qwen3-14B directory")
    parser.add_argument("--check", action="store_true", help="Do not write; exit 1 if preparation is needed")
    parser.add_argument(
        "--patch-mbridge", action="store_true", help="Also patch mbridge in this Python environment for RL YaRN"
    )
    args = parser.parse_args(argv)
    try:
        changed = prepare_model(args.model, check=args.check)
        bridge_changed = patch_mbridge(check=args.check) if args.patch_mbridge else False
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    return int(args.check and (bool(changed) or bridge_changed))


if __name__ == "__main__":
    sys.exit(main())
