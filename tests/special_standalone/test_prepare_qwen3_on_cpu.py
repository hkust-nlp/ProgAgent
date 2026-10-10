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

"""Offline metadata preparation and template rendering regression tests."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("prepare_qwen3", ROOT / "ptc_training_recipe/prepare_qwen3.py")
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


def make_model(path, size="8b"):
    """Create representative official model metadata without downloading weights."""
    path.mkdir()
    hidden, layers = (4096, 36) if size == "8b" else (5120, 40)
    config = {
        "model_type": "qwen3",
        "architectures": ["Qwen3ForCausalLM"],
        "hidden_size": hidden,
        "num_hidden_layers": layers,
        "max_position_embeddings": 40960,
        "rope_theta": 1000000,
        "rope_scaling": None,
        "vocab_size": 151936,
    }
    (path / "config.json").write_text(json.dumps(config))
    (path / "tokenizer_config.json").write_text(json.dumps({"chat_template": "original", "eos_token": "<|im_end|>"}))
    (path / "chat_template.jinja").write_text("original standalone template")
    (path / "weights.safetensors").write_bytes(b"untouched weights")
    return config


@pytest.mark.parametrize("size", ["8b", "14b"])
def test_prepare_backup_check_idempotence(tmp_path, size):
    model = tmp_path / size
    original = make_model(model, size)
    before = {p.name: p.read_bytes() for p in model.iterdir()}
    assert prepare.main(["--model", str(model), "--check"]) == 1
    assert {p.name: p.read_bytes() for p in model.iterdir()} == before
    assert prepare.main(["--model", str(model)]) == 0
    config = json.loads((model / "config.json").read_text())
    for key in ("hidden_size", "num_hidden_layers", "vocab_size", "architectures"):
        assert config[key] == original[key]
    assert config["max_position_embeddings"] == 131072
    assert config["rope_scaling"] == prepare.YARN
    assert config["rope_parameters"] == {**prepare.YARN, "rope_theta": 1000000}
    tokenizer = json.loads((model / "tokenizer_config.json").read_text())
    assert tokenizer["chat_template"] == prepare.TEMPLATE_PATH.read_text()
    assert tokenizer["eos_token"] == "<|im_end|>"
    assert tokenizer["model_max_length"] == 131072
    for name in ("config.json", "tokenizer_config.json", "chat_template.jinja"):
        assert (model / (name + prepare.BACKUP_SUFFIX)).read_bytes() == before[name]
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in model.iterdir()}
    assert prepare.main(["--model", str(model)]) == 0
    assert prepare.main(["--model", str(model), "--check"]) == 0
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in model.iterdir()} == after
    assert (model / "weights.safetensors").read_bytes() == before["weights.safetensors"]


@pytest.mark.parametrize("model_type", ["qwen3_moe", "qwen2"])
def test_reject_other_model_types_without_writes(tmp_path, model_type):
    model = tmp_path / "model"
    config = make_model(model)
    config["model_type"] = model_type
    (model / "config.json").write_text(json.dumps(config))
    before = {p.name: p.read_bytes() for p in model.iterdir()}
    with pytest.raises(ValueError, match="dense Qwen3"):
        prepare.prepare_model(model)
    assert {p.name: p.read_bytes() for p in model.iterdir()} == before


def test_hf_snapshot_symlinks_do_not_modify_cache_blobs(tmp_path):
    model = tmp_path / "model"
    make_model(model)
    blob = tmp_path / "config-blob"
    (model / "config.json").rename(blob)
    original = blob.read_bytes()
    (model / "config.json").symlink_to(blob)
    prepare.prepare_model(model)
    assert blob.read_bytes() == original
    assert not (model / "config.json").is_symlink()


def test_invalid_tokenizer_leaves_model_unchanged(tmp_path):
    model = tmp_path / "model"
    make_model(model)
    (model / "tokenizer_config.json").write_text("not json")
    before = {p.name: p.read_bytes() for p in model.iterdir()}
    with pytest.raises(ValueError):
        prepare.prepare_model(model)
    assert {p.name: p.read_bytes() for p in model.iterdir()} == before


def test_template_and_yarn_load_through_transformers(tmp_path):
    transformers = pytest.importorskip("transformers")
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel

    model = tmp_path / "model"
    make_model(model)
    tokenizer = transformers.PreTrainedTokenizerFast(
        tokenizer_object=Tokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]")), unk_token="[UNK]"
    )
    tokenizer.save_pretrained(model)
    prepare.prepare_model(model)
    loaded = transformers.AutoTokenizer.from_pretrained(model, local_files_only=True)
    assert loaded.chat_template == prepare.TEMPLATE_PATH.read_text()
    config = transformers.AutoConfig.from_pretrained(model, local_files_only=True)
    rope = getattr(config, "rope_parameters", None) or config.rope_scaling
    assert rope["rope_type"] == "yarn" and rope["factor"] == 4.0
    assert config.max_position_embeddings == 131072
    messages = [
        {"role": "user", "content": "Look up record 42"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"type": "function", "function": {"name": "lookup", "arguments": {"id": 42, "tags": ["a", "b"]}}}
            ],
        },
        {"role": "tool", "content": "found"},
    ]
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
    rendered = loaded.apply_chat_template(
        messages, tools=tools, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    assert "<function=lookup>" in rendered
    assert "<parameter=id>\n42\n</parameter>" in rendered
    assert '<parameter=tags>\n["a", "b"]\n</parameter>' in rendered
    assert "<tool_response>\nfound\n</tool_response>" in rendered
    assert rendered.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")


def test_combined_cli_patches_mbridge_and_is_idempotent(tmp_path):
    model = tmp_path / "model"
    make_model(model)
    bridge = tmp_path / "mbridge"
    (bridge / "models").mkdir(parents=True)
    (bridge / "__init__.py").write_text("")
    source = bridge / "models/qwen3.py"
    source.write_text(
        "class Qwen3Bridge:\n    def _build_config(self):\n        return self._build_base_config(qk_layernorm=True)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    command = [
        sys.executable,
        str(ROOT / "ptc_training_recipe/prepare_qwen3.py"),
        "--model",
        str(model),
        "--patch-mbridge",
    ]
    # A prepared model must not hide a missing environment patch in --check.
    prepare.prepare_model(model)
    original_bridge = source.read_bytes()
    result = subprocess.run([*command, "--check"], env=env, capture_output=True)
    assert result.returncode == 1
    assert source.read_bytes() == original_bridge
    assert not source.with_suffix(".py.orig").exists()
    subprocess.run(command, env=env, check=True, capture_output=True)
    assert source.with_suffix(".py.orig").read_bytes() == original_bridge
    assert "# YARN_PATCH_APPLIED_V2" in source.read_text()
    assert 'getattr(self.hf_config, "rope_parameters", None)' in source.read_text()
    subprocess.run([*command, "--check"], env=env, check=True, capture_output=True)
    before = source.read_bytes()
    subprocess.run(command, env=env, check=True, capture_output=True)
    assert source.read_bytes() == before


@pytest.mark.parametrize("field", ["rope_scaling", "rope_parameters"])
def test_bridge_patch_preserves_yarn_behavior(tmp_path, field):
    from types import SimpleNamespace

    bridge = tmp_path / "mbridge"
    (bridge / "models").mkdir(parents=True)
    (bridge / "__init__.py").write_text("")
    source = bridge / "models/qwen3.py"
    source.write_text(
        "class Qwen3Bridge:\n    def _build_config(self):\n        return self._build_base_config(qk_layernorm=True)\n"
    )
    model = tmp_path / "model"
    make_model(model)
    subprocess.run(
        [sys.executable, str(ROOT / "ptc_training_recipe/prepare_qwen3.py"), "--model", str(model), "--patch-mbridge"],
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        check=True,
        capture_output=True,
    )
    namespace = {}
    exec(compile(source.read_text(), str(source), "exec"), namespace)
    instance = namespace["Qwen3Bridge"]()
    instance.hf_config = SimpleNamespace(**{field: dict(prepare.YARN)})
    instance._build_base_config = lambda **kwargs: SimpleNamespace(**kwargs)
    config = instance._build_config()
    assert config.position_embedding_type == "yarn"
    assert config.yarn_rotary_scaling_factor == 4.0
    assert config.yarn_original_max_position_embeddings == 32768
    assert config.apply_rope_fusion is False
    assert config.qk_layernorm is True
