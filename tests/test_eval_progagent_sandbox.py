"""Evaluation sandbox regression tests; no verl/torch imports required."""

import importlib.util
import threading
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "eval_progagent_sandbox", Path(__file__).parents[1] / "task-sync/src/sandbox/progagent_sandbox.py"
)
sandbox = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sandbox)


def test_buffer_preserves_tail():
    buffer = sandbox._output_buffer(10)
    for text in ["abcdefg", "12345", "678", "XY"]:
        buffer.append(text)
    assert buffer.value().startswith("abcdefg")
    assert buffer.value().endswith("8XY")
    assert buffer._head_len + buffer._tail_len <= 10


def test_closed_sandbox_cannot_restart(tmp_path):
    instance = sandbox.StatefulSandbox(str(tmp_path))
    instance.cleanup()
    instance.cleanup()
    with pytest.raises(RuntimeError, match="closed"):
        instance.start()
    assert "closed" in instance.execute("1")


def test_start_idempotent_and_initialization_failure(tmp_path, monkeypatch):
    instance = sandbox.StatefulSandbox(str(tmp_path))
    calls = []
    monkeypatch.setattr(instance, "_start_impl", lambda: calls.append(1))
    instance.start()
    instance.start()
    assert calls == [1]
    instance.cleanup()
    instance = sandbox.StatefulSandbox(str(tmp_path))
    monkeypatch.setattr(instance, "_run", lambda code: ("", "broken tools", False))
    monkeypatch.setattr(instance, "_start_impl", lambda: instance._initialize("bad"))
    with pytest.raises(RuntimeError, match="broken tools"):
        instance.start()
    assert instance._cleaned_up


def test_cleanup_during_start(tmp_path, monkeypatch):
    instance = sandbox.StatefulSandbox(str(tmp_path))
    entered, release = threading.Event(), threading.Event()
    errors = []

    def start_impl():
        entered.set()
        assert release.wait(5)

    def start():
        try:
            instance.start()
        except RuntimeError as exc:
            errors.append(str(exc))

    monkeypatch.setattr(instance, "_start_impl", start_impl)
    starter = threading.Thread(target=start)
    starter.start()
    assert entered.wait(5)
    closer = threading.Thread(target=instance.cleanup)
    closer.start()
    assert instance._close_requested.wait(5)
    release.set()
    starter.join(5)
    closer.join(5)
    assert not starter.is_alive() and not closer.is_alive()
    assert errors == ["Sandbox has been closed"]
    assert instance._cleaned_up


def test_selected_landlock_fails_closed(monkeypatch, tmp_path):
    backend = sandbox.IsolationBackend("landlock", [str(tmp_path)])
    monkeypatch.setattr(sandbox, "_apply_landlock", lambda paths: False)
    with pytest.raises(RuntimeError, match="Landlock"):
        backend.child_setup()()


def test_bwrap_keeps_env_readable_and_db_writable(tmp_path):
    workspace = tmp_path / "workspace"
    backend = sandbox.IsolationBackend("bubblewrap", [str(workspace), str(tmp_path)])
    argv = backend.wrap_command(["python", "env.py"])
    assert argv[argv.index("--ro-bind") + 1 :][:2] == ["/", "/"]
    assert argv.index(str(tmp_path)) < argv.index(str(workspace))
    assert backend.restricted_writes and not backend.restricted_reads
    assert argv[argv.index("--dev") + 1] == "/dev"
    assert argv[argv.index("--proc") + 1] == "/proc"


@pytest.fixture
def unconfined(monkeypatch):
    monkeypatch.setattr(sandbox, "select_isolation_backend", lambda paths: sandbox.IsolationBackend("none", paths))


def test_terminal_output_and_timeout(tmp_path, unconfined):
    terminal = sandbox.TerminalExecutor(str(tmp_path), timeout=2, max_output_chars=30)
    output = terminal.execute("printf start; printf error >&2; printf end")
    assert "startend" in output and "error" in output
    output = terminal.execute("printf '%01000d' 1; printf TAIL")
    assert "truncated" in output and output.endswith("TAIL")
    terminal.timeout = 0.1
    with pytest.raises(sandbox.TerminalError, match="timed out"):
        terminal.execute("sleep 10 & wait")


def test_recycled_pid_not_signalled(monkeypatch):
    class Process:
        pid = 123
        _sandbox_starttime = 1

    monkeypatch.setattr(sandbox, "_proc_starttime", lambda pid: 2)
    monkeypatch.setattr(sandbox.os, "killpg", lambda *args: pytest.fail("recycled PID signalled"))
    sandbox._stop_process(Process())


def test_landlock_shell_devices_and_write_confinement(tmp_path, monkeypatch):
    if not sandbox._landlock_abi_version():
        pytest.skip("Landlock unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    forbidden = tmp_path / "forbidden"
    monkeypatch.setattr(sandbox, "bwrap_usable", lambda: False)
    terminal = sandbox.TerminalExecutor(str(workspace))
    assert terminal.execute("echo hello >/dev/null; echo allowed >ok; cat ok").strip() == "allowed"
    import shlex

    output = terminal.execute(f"echo denied >{shlex.quote(str(forbidden))}")
    assert "Permission denied" in output
    assert not forbidden.exists()


def test_bwrap_interrupt_targets_kernel(tmp_path, monkeypatch):
    from types import SimpleNamespace

    instance = sandbox.StatefulSandbox(str(tmp_path))
    instance.isolation_backend = sandbox.IsolationBackend("bubblewrap", [str(tmp_path)])
    instance._proc = SimpleNamespace(pid=100, poll=lambda: None)
    instance._kernel_pid = 101
    instance._kernel_starttime = 123
    monkeypatch.setattr(sandbox, "_proc_starttime", lambda pid: 123)
    instance._client = SimpleNamespace(
        get_iopub_msg=lambda timeout: {
            "parent_header": {"msg_id": "cell"},
            "header": {"msg_type": "status"},
            "content": {"execution_state": "idle"},
        }
    )
    signals = []
    monkeypatch.setattr(sandbox.os, "kill", lambda pid, sig: signals.append(pid))
    monkeypatch.setattr(sandbox.os, "killpg", lambda *args: pytest.fail("must not interrupt launcher"))
    assert instance._try_interrupt_to_idle("cell", 1)
    assert signals == [101]
    monkeypatch.setattr(sandbox, "_proc_starttime", lambda pid: 456)
    assert not instance._try_interrupt_to_idle("cell", 1)
    assert signals == [101]
    instance._proc = instance._client = None
    instance.cleanup()


def test_kernel_stderr_is_drained_and_bounded(tmp_path):
    import os
    from types import SimpleNamespace

    instance = sandbox.StatefulSandbox(str(tmp_path))
    read_fd, write_fd = os.pipe()
    instance._proc = SimpleNamespace(stderr=os.fdopen(read_fd, "rb"))
    thread = threading.Thread(target=instance._drain_stderr)
    thread.start()
    with os.fdopen(write_fd, "wb") as writer:
        writer.write(b"A" * 100000 + b"TAIL")
    thread.join(5)
    assert not thread.is_alive()
    assert instance._stderr_buffer.value().endswith("TAIL")
    assert len(instance._stderr_buffer.value()) < 4200
    instance._proc = None
    instance.cleanup()
