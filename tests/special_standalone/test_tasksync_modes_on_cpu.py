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

"""Exercise real TaskSync loops with CPU fakes at the GPU and sandbox boundaries."""

import asyncio
import importlib.util
import io
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, redirect_stdout
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from omegaconf import OmegaConf

ROOT = Path(__file__).resolve().parents[2]
LOOPS = ROOT / "verl/experimental/agent_loop"


def load_module(monkeypatch, name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


class FakeSandbox:
    """Run trusted test tools on one interpreter thread, like an ipykernel."""

    def __init__(self, **kwargs):
        self.namespace = {}
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.calls = []

    def start(self):
        pass

    def execute(self, code, **kwargs):
        self.calls.append(code)

        def evaluate():
            output = io.StringIO()
            try:
                with redirect_stdout(output):
                    exec(code, self.namespace)
                return output.getvalue(), True
            except Exception as exc:
                return str(exc), False

        return self.executor.submit(evaluate).result()

    def cleanup(self):
        self.executor.shutdown()


@pytest.fixture
def modules(monkeypatch):
    def stub(name, **attrs):
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)

    class Base:
        def __init__(self, config):
            self.config = config
            self.rollout_config = config.actor_rollout_ref.rollout
            self.tokenizer = SimpleNamespace(
                unk_token_id=None,
                convert_tokens_to_ids=lambda _: None,
                encode=lambda text, **kw: list(text),
            )
            self.loop = asyncio.get_running_loop()

        async def apply_chat_template(self, *args, **kwargs):
            return [1]

    @asynccontextmanager
    async def gate():
        yield

    async def acquire():
        pass

    stub(
        "verl.experimental.agent_loop.agent_loop",
        AgentLoopBase=Base,
        AgentLoopMetrics=SimpleNamespace,
        AgentLoopOutput=SimpleNamespace,
        register=lambda _: lambda cls: cls,
    )
    lifecycle = load_module(monkeypatch, "_test_sandbox_lifecycle", LOOPS / "progagent_sandbox.py")
    lifecycle.release_rollout_slot = lambda: None
    lifecycle.cleanup_env_dir = lambda _: None
    lifecycle.teardown_env = lambda _: None
    stub(
        "verl.experimental.agent_loop.progagent_sandbox",
        StatefulSandbox=FakeSandbox,
        cleanup_rollout=lifecycle.cleanup_rollout,
        run_sandbox_work=lifecycle.run_sandbox_work,
        acquire_rollout_slot=acquire,
        release_rollout_slot=lambda: None,
        sandbox_startup_gate=gate,
        cleanup_env_dir=lambda _: None,
        teardown_env=lambda _: None,
        track_env_dir=lambda _: None,
        get_tool_executor=lambda: None,
        truncate_output=lambda s, n: s[:n],
    )
    stub("verl.experimental.agent_loop.terminal", TerminalError=RuntimeError, TerminalExecutor=lambda _: None)
    stub("verl.utils.profiler", simple_timer=lambda *args: None)
    stub("verl.utils.rollout_trace", rollout_trace_op=lambda f: f)
    stub("verl.workers.rollout.replica", TokenOutput=SimpleNamespace)
    shared = load_module(monkeypatch, "verl.experimental.agent_loop.tasksync_tools", LOOPS / "tasksync_tools.py")
    hybrid = load_module(monkeypatch, "_test_tasksync_hybrid", LOOPS / "prog_agent_loop.py")
    ptc = load_module(monkeypatch, "_test_tasksync_ptc", LOOPS / "prog_ptc_agent_loop.py")
    modes = load_module(monkeypatch, "_test_training_modes", ROOT / "examples/train_verl_tasksync/training_modes.py")
    return SimpleNamespace(shared=shared, hybrid=hybrid, ptc=ptc, modes=modes)


def config(mode):
    return OmegaConf.create(
        {
            "actor_rollout_ref": {
                "env": {"ptc_mode": mode, "max_tool_calls": 2},
                "rollout": {"prompt_length": 1000, "response_length": 1000, "agent": {"default_agent_loop": "wrong"}},
            }
        }
    )


ENV_SOURCE = """
import sqlite3

class Task_Env:
    def __init__(self, db_path, workspace):
        self.db_path = db_path
        self.calls = 0
        self.tools = {"add": self.add, "read": self.read}
        self.schemas = [
            {"type": "function", "function": {"name": "add", "parameters": {
                "type": "object", "properties": {"amount": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "read", "parameters": {
                "type": "object", "properties": {}}}},
        ]
    def get_assistant_tools(self):
        return self.schemas
    def add(self, amount=100):
        self.calls += 1
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE items SET value=value+? WHERE id=1", (amount,))
        return self.read()
    def read(self):
        with sqlite3.connect(self.db_path) as conn:
            return {"value": conn.execute("SELECT value FROM items WHERE id=1").fetchone()[0], "calls": self.calls}
    def step(self, action):
        value = self.read()["value"]
        return float(value == 3), {"value": value}
"""


def make_env(tmp_path, module, mode):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db = tmp_path / "data.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, value INTEGER)")
        conn.executemany("INSERT INTO items VALUES (?,?)", [(1, 0), (2, 10)])
    env_file = tmp_path / "env.py"
    env_file.write_text(ENV_SOURCE)
    namespace = {}
    exec(ENV_SOURCE, namespace)
    args = dict(
        task_env=namespace["Task_Env"](str(db), str(workspace)),
        task_prompt="test",
        workspace=str(workspace),
        env_dir=str(tmp_path),
        db_path=str(db),
        env_file=str(env_file),
        task_name="test",
    )
    if mode != "ptc":
        args["enable_ptc"] = mode == "hybrid"
    return module.TaskSyncEnvState(**args)


def loop_and_data(modules, tmp_path, mode):
    module = modules.ptc if mode == "ptc" else modules.hybrid
    loop_type = module.TaskSyncPTCAgentLoop if mode == "ptc" else module.TaskSyncAgentLoop
    loop = loop_type(config(mode))
    env = make_env(tmp_path, module, mode)
    data = module.TaskSyncAgentData([], env, env.get_tool_schemas(), {}, "test")
    loop.tool_schemas = data.tool_schemas
    return module, loop, env, data


@pytest.mark.parametrize(
    "mode,expected", [("ptc", "tasksync_ptc_agent"), ("hybrid", "tasksync_agent"), ("dtc", "tasksync_agent")]
)
def test_routing_and_schemas(modules, tmp_path, mode, expected):
    cfg = config(mode)
    modules.modes.configure_training_mode(cfg)
    assert cfg.actor_rollout_ref.rollout.agent.default_agent_loop == expected

    async def run():
        _, _, env, data = loop_and_data(modules, tmp_path, mode)
        names = [s["function"]["name"] for s in data.tool_schemas]
        assert ("programmatic_tool_call" in names) == (mode != "dtc")
        assert ("execute_python" in names) == (mode != "ptc")
        assert env.get_tool_schemas() == data.tool_schemas
        assert len(env.task_env.get_assistant_tools()) == 2

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["ptc", "hybrid", "dtc"])
def test_tool_access_and_database_visibility(modules, tmp_path, mode):
    async def run():
        _, loop, env, data = loop_and_data(modules, tmp_path, mode)
        # Even an accidentally attached sandbox must not enable PTC in DTC mode.
        sandbox = FakeSandbox()
        env.ptc_sandbox = sandbox
        try:
            if mode != "dtc":
                assert loop._setup_ptc_sandbox_tools(sandbox, env)["success"]
            observation, _, done = await loop._execute_tool(env, "add", {"amount": 1}, data, "dense")
            assert not done
            if mode == "ptc":
                assert "cannot be invoked directly" in observation
                assert env.task_env.read()["value"] == 0
                amount = 3
            else:
                assert json.loads(observation)["value"] == 1
                amount = 2
            result, _, _ = await loop._execute_tool(
                env, "programmatic_tool_call", {"code": f"print(tools['add'](amount={amount}))"}, data, "dense"
            )
            if mode == "dtc":
                assert "unavailable in dtc" in result
                assert sandbox.calls == []
                await loop._execute_tool(env, "add", {"amount": 2}, data, "dense")
            elif mode == "hybrid":
                result, _, _ = await loop._execute_tool(env, "read", {}, data, "dense")
                assert json.loads(result) == {"value": 3, "calls": 2}
            result, reward, done = await loop._execute_tool(env, "claim_done", {"action": "done"}, data, "dense")
            assert done and reward == 1.0
            assert json.loads(result)["value"] == 3
        finally:
            sandbox.cleanup()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["ptc", "hybrid", "dtc"])
def test_sample_cannot_override_mode_and_tool_budget(modules, tmp_path, mode):
    async def run():
        module, loop, env, _ = loop_and_data(modules, tmp_path, mode)

        async def create(task_info, **kwargs):
            if "enable_ptc" in kwargs:
                env.enable_ptc = kwargs["enable_ptc"]
            return env

        async def generate(data, sampling_params):
            data.current_tool_calls = [
                {"name": "add", "arguments": {"amount": 1}},
                {"name": "add", "arguments": {"amount": 2}},
                {"name": "claim_done", "arguments": {"action": "over budget"}},
            ]
            return module.AgentState.PROCESSING_TOOL

        loop._create_env_from_task_info = create
        loop._handle_generating_state = generate
        loop._build_output = lambda data: data
        result = await loop.run({}, raw_prompt={"task_info": {}, "max_tool_calls": 2, "enable_ptc": mode == "dtc"})
        assert not result.claimed_done
        assert result.final_reward == 0.0
        if mode != "ptc":
            assert env.enable_ptc == (mode == "hybrid")
            assert result.env_tool_count == 2
        else:
            assert result.programmatic_tool_call_error_count == 2

    asyncio.run(run())


@pytest.mark.parametrize("variant", ["hybrid", "ptc"])
@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("arguments", ['"not json"', "[]", "null"])
def test_bad_json_arguments_never_become_empty_calls(modules, variant, wrapped, arguments):
    cls = modules.hybrid.TaskSyncAgentLoop if variant == "hybrid" else modules.ptc.TaskSyncPTCAgentLoop
    parser = cls.__new__(cls)
    parser.tool_call_format = "auto"
    text = '{"name":"add","arguments":' + arguments + "}"
    if wrapped:
        text = "<tool_call>" + text + "</tool_call>"
    calls, errors = parser._parse_tool_calls(text)
    assert calls == [] and errors


def test_xml_types_and_format_are_respected(modules):
    parser = modules.shared.TaskSyncToolParser()
    parser.tool_call_format = "xml"
    parser.tool_schemas = [
        {
            "function": {
                "name": "lookup",
                "parameters": {
                    "properties": {
                        "id": {"type": "string"},
                        "code": {"type": "string"},
                        "count": {"type": "integer"},
                    }
                },
            }
        }
    ]
    text = (
        "<tool_call><function=lookup><parameter=id>001</parameter>"
        "<parameter=code>False</parameter><parameter=count>2</parameter></function></tool_call>"
    )
    calls, errors = parser._parse_tool_calls(text)
    assert not errors
    assert calls[0]["arguments"] == {"id": "001", "code": "False", "count": 2}
    assert parser._parse_tool_calls("<think>" + text) == ([], [])
    calls, errors = parser._parse_tool_calls('{"name":"lookup","arguments":{}}')
    assert calls == [] and errors


def test_database_snapshot_preserves_updates_deletes_schema_and_wal(modules, tmp_path):
    src, dst = tmp_path / "ptc.db", tmp_path / "score.db"
    with sqlite3.connect(dst) as conn:
        conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, value INTEGER)")
        conn.executemany("INSERT INTO items VALUES (?, ?)", [(1, 1), (2, 2)])
    modules.shared.copy_sqlite_database(str(dst), str(src))
    conn = sqlite3.connect(src)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("UPDATE items SET value=3 WHERE id=1")
        conn.execute("DELETE FROM items WHERE id=2")
        conn.execute("CREATE UNIQUE INDEX item_value ON items(value)")
        conn.commit()
        modules.shared.copy_sqlite_database(str(src), str(dst))
        with sqlite3.connect(dst) as score:
            assert score.execute("SELECT * FROM items").fetchall() == [(1, 3)]
            assert score.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall() == [("item_value",)]
    finally:
        conn.close()


@pytest.mark.parametrize("variant", ["hybrid", "ptc"])
def test_missing_database_is_a_setup_error(modules, tmp_path, variant):
    async def run():
        _, loop, env, _ = loop_and_data(modules, tmp_path, variant)
        Path(env.db_path).unlink()
        sandbox = FakeSandbox()
        try:
            result = loop._setup_ptc_sandbox_tools(sandbox, env)
            assert result["success"] is False
            assert sandbox.calls == []
            assert not Path(env.db_path).exists()
        finally:
            sandbox.cleanup()

    asyncio.run(run())


def test_locked_scoring_database_fails_instead_of_hanging(modules, tmp_path):
    src, dst = tmp_path / "source.db", tmp_path / "destination.db"
    for path in [src, dst]:
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE items(value)")
    locked = sqlite3.connect(dst)
    try:
        locked.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="transaction holds its lock"):
            modules.shared.copy_sqlite_database(str(src), str(dst))
    finally:
        locked.close()


@pytest.mark.parametrize("variant", ["hybrid", "ptc"])
def test_prompt_failure_closes_partial_environment_before_removal(modules, tmp_path, monkeypatch, variant):
    async def run():
        module, loop, _, _ = loop_and_data(modules, tmp_path, variant)
        monkeypatch.setattr(loop, "_prepare_env_dir", lambda *args: str(tmp_path))
        events = []

        def close(state):
            assert state.task_env is not None
            events.append("close")

        monkeypatch.setattr(module, "teardown_env", close)
        monkeypatch.setattr(module, "cleanup_env_dir", lambda _: events.append("remove"))
        kwargs = {"enable_ptc": True} if variant == "hybrid" else {}
        with pytest.raises(FileNotFoundError):
            await loop._create_env_from_task_info({"source_path": str(tmp_path)}, **kwargs)
        assert events == ["close", "remove"]
        assert str(tmp_path) not in sys.path

    asyncio.run(run())
