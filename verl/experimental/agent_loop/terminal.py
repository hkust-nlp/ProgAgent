"""Terminal executor: runs shell commands inside the workspace directory."""

import itertools
import os
import resource
import signal
import subprocess
import threading

from verl.experimental.agent_loop.progagent_sandbox import (
    _CGROUP_ENABLE,
    _CGROUP_PIDS_MAX,
    IsolationBackend,
    IsolationConfig,
    _create_cgroup,
    select_isolation_backend,
)

# Default per-command memory cap (bytes). Seeds the cgroup memory.max (the
# primary cap, applied over the whole {bash -> children} tree by real RSS) and
# the fallback RLIMIT_AS used only when the cgroup is unavailable. RLIMIT_AS is
# inherited by every child the shell spawns, so a runaway `python3 foo.py` is
# bounded either way. Override via the `mem_limit_bytes` kwarg or the
# VERL_TERMINAL_MEM_LIMIT_BYTES env var. 0 disables the cap.
_DEFAULT_MEM_LIMIT_BYTES = int(os.getenv("VERL_TERMINAL_MEM_LIMIT_BYTES", str(4 * 1024**3)))

# Cap on how many chars of stdout/stderr are KEPT in this process. The old
# communicate() path buffered the child's entire output in the AgentLoopWorker
# process, so a single `cat big_file` / `yes`-style command could balloon the
# worker's RSS by hundreds of MB-GBs and get the node's Ray processes
# OOM-killed (observed as tool observations tokenizing to 53M tokens). Output
# beyond the cap is drained (so the child never blocks on a full pipe) but
# discarded. Override via env var; 0 disables the cap.
_DEFAULT_MAX_CAPTURE_CHARS = int(os.getenv("VERL_TERMINAL_MAX_CAPTURE_CHARS") or str(1 * 1024**2))

# Per-command cgroup leaf names: term_<pid>_<n>, unique within a worker process.
_LEAF_COUNTER = itertools.count()


class TerminalError(Exception):
    pass


class TerminalExecutor:
    """Execute shell commands, including pipes and redirects, via /bin/bash."""

    def __init__(self, workspace: str, timeout: int = 60, mem_limit_bytes: int | None = None):
        self.workspace = os.path.abspath(os.path.realpath(workspace))
        self.isolation_backend: IsolationBackend | None = None
        self.timeout = timeout
        self.mem_limit_bytes = mem_limit_bytes if mem_limit_bytes is not None else _DEFAULT_MEM_LIMIT_BYTES

    def execute(self, command_string: str) -> str:
        if not isinstance(command_string, str):
            raise TerminalError(
                f"The 'command' argument must be a string, got {type(command_string).__name__}: "
                f'{command_string!r}. Pass a shell command, e.g. {{"command": "ls -la"}}.'
            )
        if not command_string or not command_string.strip():
            raise TerminalError(
                'The \'command\' argument is empty. Pass a non-empty shell command, e.g. {"command": "ls -la"}.'
            )

        mem_limit = self.mem_limit_bytes
        os.makedirs(self.workspace, exist_ok=True)
        # Preserve shell compatibility: its historical fallback is unrestricted bash.
        backend = select_isolation_backend(IsolationConfig(self.workspace, allow_landlock=False))
        self.isolation_backend = backend
        argv = backend.wrap_command(["/bin/bash", "-c", command_string])

        # Per-command cgroup leaf: real-RSS memory.max + pids cap over the whole
        # {bash -> children} tree. RLIMIT_AS is only a fallback for when the
        # cgroup isn't available (see progagent_sandbox for the rationale).
        cgroup_dir = None
        if _CGROUP_ENABLE:
            cgroup_dir = _create_cgroup(
                f"term_{os.getpid()}_{next(_LEAF_COUNTER)}",
                mem_max=mem_limit,
                pids_max=_CGROUP_PIDS_MAX,
            )
        cgroup_procs = os.path.join(cgroup_dir, "cgroup.procs") if cgroup_dir else None

        def _preexec():
            # Join the cgroup so its caps cover bash and every child it spawns.
            joined = False
            if cgroup_procs is not None:
                try:
                    with open(cgroup_procs, "w") as f:
                        f.write(str(os.getpid()))
                    joined = True
                except OSError:
                    joined = False
            # RLIMIT_AS only when the cgroup cap isn't in effect; never stacked
            # (AS over-counts mmap and false-positives, e.g. importing torch).
            if not joined and mem_limit and mem_limit > 0:
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))
                except (ValueError, OSError):
                    pass

            backend.apply_child_restrictions()

        # Use Popen + start_new_session so we can kill the *entire process
        # group* on timeout. subprocess.run(timeout=...) only SIGKILLs the
        # shell leader, leaving any children (e.g. a `python3 infinite.py` the
        # shell spawned) running as orphans and burning CPU/RAM until the host
        # OOMs. Killing the pgid takes them all down together.
        try:
            try:
                proc = subprocess.Popen(
                    argv,
                    cwd=self.workspace,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    # Shell tools (file/grep on binaries, locale-mismatched output,
                    # etc.) routinely emit non-UTF-8 bytes. Without ``replace`` the
                    # default strict decoder raises UnicodeDecodeError inside
                    # ``_translate_newlines`` and crashes the rollout worker.
                    errors="replace",
                    start_new_session=True,
                    preexec_fn=_preexec,
                )
            except Exception as e:
                raise TerminalError(f"Execution failed: {e}") from e

            # Popen alone cannot confirm that bubblewrap completed namespace setup.
            backend.log_policy("terminal", bool(cgroup_dir))
            # Drain stdout/stderr on background threads, keeping at most
            # _DEFAULT_MAX_CAPTURE_CHARS per stream. Draining (vs not reading)
            # keeps the child from blocking on a full pipe; capping (vs
            # communicate()) keeps a runaway `cat`/`yes` from ballooning THIS
            # process's RSS until the node's Ray processes are OOM-killed.
            out_state = self._drain_stream(proc.stdout)
            err_state = self._drain_stream(proc.stderr)
            try:
                proc.wait(timeout=self.timeout)
                returncode = proc.returncode
            except subprocess.TimeoutExpired as exc:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                raise TerminalError(f"Command timed out after {self.timeout}s") from exc
            finally:
                # Threads hit EOF once the process (group) is dead and the pipe
                # write ends close; the join timeout guards against a lingering
                # grandchild holding the pipe open.
                out_state["thread"].join(timeout=5)
                err_state["thread"].join(timeout=5)

            stdout = self._collect_stream(out_state, "stdout")
            stderr = self._collect_stream(err_state, "stderr")
        finally:
            # Reclaim the leaf once the process group is gone. rmdir fails if a
            # backgrounded child still lingers; the idle sweep
            # (kill_all_kernels -> _sweep_cgroup_leaves) reclaims those later.
            if cgroup_dir is not None:
                try:
                    os.rmdir(cgroup_dir)
                except OSError:
                    pass

        output = stdout
        if stderr:
            output += f"\n[stderr]: {stderr}"
        if not output.strip():
            output = f"(no output, exit code: {returncode})"
        return output

    @staticmethod
    def _drain_stream(stream) -> dict:
        """Start a daemon thread that reads `stream` to EOF, keeping only the
        first _DEFAULT_MAX_CAPTURE_CHARS chars. Returns the shared state dict:
        {"chunks": [...], "kept": int, "total": int, "thread": Thread}."""
        cap = _DEFAULT_MAX_CAPTURE_CHARS
        state = {"chunks": [], "kept": 0, "total": 0}

        def _drain():
            try:
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        break
                    state["total"] += len(chunk)
                    if cap <= 0 or state["kept"] < cap:
                        keep = chunk if cap <= 0 else chunk[: cap - state["kept"]]
                        state["chunks"].append(keep)
                        state["kept"] += len(keep)
            except (OSError, ValueError):
                pass  # pipe closed mid-read (e.g. after killpg)

        t = threading.Thread(target=_drain, daemon=True)
        t.start()
        state["thread"] = t
        return state

    @staticmethod
    def _collect_stream(state: dict, name: str) -> str:
        text = "".join(state["chunks"])
        dropped = state["total"] - state["kept"]
        if dropped > 0:
            text += (
                f"\n...[{name} truncated: {dropped} chars dropped; pipe large output through head/tail/grep instead]..."
            )
        return text
