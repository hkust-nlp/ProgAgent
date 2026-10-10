"""
Stateful Python sandbox backed by an IPython kernel.

Variables, imports, and other state persist across execute() calls within
the same sandbox instance, enabling multi-turn code execution.

Isolation strategy (layered):
  1. bubblewrap (bwrap), when available -- the PRIMARY fs layer. The kernel runs
     in a mount namespace with DEFAULT-DENY reads: only an allowlist of system
     dirs plus the rollout's own paths (workspace, env_dir, tmpdir) are visible;
     /tmp is a fresh tmpfs so sibling rollouts' env_dirs (and their data.db /
     answers), /mnt model weights, /root, etc. are invisible. Writes stay
     confined to the workspace + private /tmp & /dev/shm + tmpdir. Network is
     NOT isolated. Disable with VERL_SANDBOX_USE_BWRAP=0.
  2. Linux Landlock (kernel >= 5.13, no root required) -- FALLBACK when bwrap is
     unavailable. Applied in the kernel child via preexec_fn. Grants
     read+execute everywhere, but confines writes to the workspace, kernel tmpdir, and host /tmp.
     It does not isolate sibling rollouts under /tmp.
  3. cgroup v2 leaf per kernel (when writable) -- the memory cap: aggregate
     memory.max + pids.max over the whole {bwrap -> kernel -> children} subtree.
     A per-process RLIMIT_AS in preexec is only a fallback for when the cgroup is
     unavailable (never stacked: AS over-counts mmap and false-positives).
  4. Python-level open() guard -- defense-in-depth for write-mode built-in
     open() calls outside the workspace.
"""

import asyncio
import collections
import concurrent.futures
import contextlib
import ctypes
import gc
import logging
import os
import queue
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__file__)
logger.setLevel(os.getenv("VERL_LOGGING_LEVEL", "INFO"))

# Deduplicate startup diagnostics across kernels in the same worker.
_LOGGED_ONCE: set[str] = set()
_LOG_ONCE_LOCK = threading.Lock()


def _log_once(key: str, level: int, msg: str) -> None:
    """Emit `msg` at `level` the first time `key` is seen in this process."""
    with _LOG_ONCE_LOCK:
        if key in _LOGGED_ONCE:
            return
        _LOGGED_ONCE.add(key)
    logger.log(level, msg)


# Per-kernel memory limit; cgroups are preferred over RLIMIT_AS. Zero disables it.
_DEFAULT_MEM_LIMIT_BYTES = int(os.getenv("VERL_SANDBOX_MEM_LIMIT_BYTES", str(2 * 1024**3)))

# Maximum returned output length; zero disables truncation.
_DEFAULT_MAX_OUTPUT_CHARS = int(os.getenv("VERL_SANDBOX_MAX_OUTPUT_CHARS", "50000"))

# Bubblewrap provides read isolation; Landlock is the write-only fallback.
# Do not stack them: bwrap tmpfs mounts are absent from host Landlock rules.
_BWRAP_BIN = shutil.which("bwrap")
_USE_BWRAP = os.getenv("VERL_SANDBOX_USE_BWRAP", "1") != "0" and _BWRAP_BIN is not None
# PID isolation prevents sandbox processes from signaling the Ray runtime.
_UNSHARE_PID = os.getenv("VERL_SANDBOX_UNSHARE_PID", "1") != "0"
# Read-only system paths; override with a colon-separated allowlist.
_BWRAP_READ_PATHS = [
    p
    for p in os.getenv(
        "VERL_SANDBOX_BWRAP_READ_PATHS",
        "/usr:/lib:/lib64:/bin:/sbin:/etc:/opt:/run:/sys",
    ).split(":")
    if p
]

# Cache namespace probes because container policies may reject bwrap.
_BWRAP_USABLE: "bool | None" = None
_BWRAP_PROBE_LOCK = threading.Lock()


def bwrap_usable() -> bool:
    """True iff bwrap is enabled and a trivial sandbox actually starts here.

    Probed once with `bwrap --ro-bind / / -- true` and cached process-wide.
    Used by both the kernel sandbox and the terminal executor so they agree on
    whether to wrap commands in bwrap."""
    global _BWRAP_USABLE
    if not _USE_BWRAP:
        return False
    if _BWRAP_USABLE is not None:
        return _BWRAP_USABLE
    with _BWRAP_PROBE_LOCK:
        if _BWRAP_USABLE is not None:
            return _BWRAP_USABLE
        try:
            r = subprocess.run(
                [_BWRAP_BIN, "--unshare-user-try", "--ro-bind", "/", "/", "--", "true"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=10,
            )
            ok = r.returncode == 0
            if not ok:
                _log_once(
                    "bwrap_unusable",
                    logging.WARNING,
                    f"[sandbox] bwrap is present but cannot create namespaces here "
                    f"({r.stderr.decode(errors='replace').strip() or 'unknown error'}); "
                    f"falling back to Landlock. NOTE: Landlock confines WRITES but not "
                    f"READS, so read-isolation (hiding data.db / model weights / sibling "
                    f"rollouts) is OFF. Enable userns / CAP_SYS_ADMIN in the pod "
                    f"securityContext to use bwrap, or set VERL_SANDBOX_USE_BWRAP=0 to "
                    f"silence this.",
                )
        except (OSError, subprocess.SubprocessError) as e:
            _log_once(
                "bwrap_probe_error",
                logging.WARNING,
                f"[sandbox] bwrap probe failed ({e}); falling back to Landlock.",
            )
            ok = False
        _BWRAP_USABLE = ok
        return ok


# Probe PID namespaces separately; some runtimes block CLONE_NEWPID.
_BWRAP_PID_NS: "bool | None" = None
_BWRAP_PID_NS_LOCK = threading.Lock()


def bwrap_pid_ns_usable() -> bool:
    """True iff bwrap can create a PID namespace here (probed once, cached)."""
    global _BWRAP_PID_NS
    if not _UNSHARE_PID or not bwrap_usable():
        return False
    if _BWRAP_PID_NS is not None:
        return _BWRAP_PID_NS
    with _BWRAP_PID_NS_LOCK:
        if _BWRAP_PID_NS is not None:
            return _BWRAP_PID_NS
        try:
            r = subprocess.run(
                [
                    _BWRAP_BIN,
                    "--unshare-user-try",
                    "--unshare-pid",
                    "--ro-bind",
                    "/",
                    "/",
                    "--proc",
                    "/proc",
                    "--",
                    "true",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=10,
            )
            ok = r.returncode == 0
            if ok:
                _log_once(
                    "bwrap_pid_ns_ok",
                    logging.INFO,
                    "[sandbox] PID-namespace isolation ON: sandboxed code cannot "
                    "see or signal processes outside its own rollout.",
                )
            else:
                _log_once(
                    "bwrap_pid_ns_unusable",
                    logging.WARNING,
                    f"[sandbox] bwrap cannot create a PID namespace here "
                    f"({r.stderr.decode(errors='replace').strip() or 'unknown error'}); "
                    f"running WITHOUT PID isolation. Sandboxed code shares the pod's "
                    f"PID namespace and can signal the Ray runtime (pkill / kill -1 "
                    f"will take the node down). Allow CLONE_NEWPID in the pod "
                    f"securityContext, or set VERL_SANDBOX_UNSHARE_PID=0 to silence.",
                )
        except (OSError, subprocess.SubprocessError) as e:
            _log_once(
                "bwrap_pid_ns_probe_error",
                logging.WARNING,
                f"[sandbox] bwrap PID-namespace probe failed ({e}); running WITHOUT PID isolation.",
            )
            ok = False
        _BWRAP_PID_NS = ok
        return ok


# Cgroup v2 caps aggregate memory and processes for each kernel subtree.
# RLIMIT_AS is a fallback: stacking it can reject legitimate mmap allocations.
_CGROUP_ENABLE = os.getenv("VERL_SANDBOX_CGROUP_ENABLE", "1") != "0"
_CGROUP_ROOT = os.getenv("VERL_SANDBOX_CGROUP_ROOT", "/sys/fs/cgroup/verl_sandbox")
_CGROUP_PIDS_MAX = os.getenv("VERL_SANDBOX_CGROUP_PIDS_MAX", "256")
# Cap the complete sandbox subtree: default 25% of MemTotal; zero disables it.
_CGROUP_TOTAL_MEM_ENV = os.getenv("VERL_SANDBOX_CGROUP_TOTAL_MEM_BYTES") or ""
_CGROUP_BASE_READY = False
_CGROUP_BASE_LOCK = threading.Lock()

_KERNEL_START_LOCK = threading.Lock()

# Track process start times to avoid signaling recycled PIDs during cleanup.
_SPAWNED_PIDS: dict[int, int | None] = {}
_PID_LOCK = threading.Lock()


def _proc_starttime(pid: int) -> int | None:
    """Kernel starttime (clock ticks since boot) of `pid`, or None if gone.
    (pid, starttime) uniquely identifies a process across pid reuse."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            data = f.read()
        # Field 22 counting from 1, but fields 1-2 include the parenthesized
        # comm which may contain spaces — split after the closing paren.
        return int(data[data.rfind(")") + 2 :].split()[19])
    except (OSError, IndexError, ValueError):
        return None


# prctl(PR_SET_PDEATHSIG, sig) -- kernel sends `sig` to this process when its
# parent dies. Linux-only; key=1 per <sys/prctl.h>. Preserved across execve()
# for the no-setuid case we use here.
_PR_SET_PDEATHSIG = 1


# Limit concurrent kernel initialization per AgentLoopWorker.
_DEFAULT_MAX_CONCURRENT_STARTUPS = int(os.getenv("VERL_SANDBOX_MAX_CONCURRENT_STARTUPS", "16"))
_STARTUP_SEM: asyncio.Semaphore | None = None


def _get_startup_sem() -> asyncio.Semaphore:
    """Lazily build the worker-wide sandbox-startup semaphore.

    Bound to the running event loop on first call. Safe under single-threaded
    asyncio (AgentLoopWorker has one event loop), no extra locking needed.
    """
    global _STARTUP_SEM
    if _STARTUP_SEM is None:
        _STARTUP_SEM = asyncio.Semaphore(_DEFAULT_MAX_CONCURRENT_STARTUPS)
    return _STARTUP_SEM


@contextlib.asynccontextmanager
async def sandbox_startup_gate():
    """Async gate around the sandbox bring-up phase. See _get_startup_sem()."""
    sem = _get_startup_sem()
    async with sem:
        yield


# Bound live episodes per worker, including their kernels and environment state.
# Shared across agent loops so an idle sweep cannot kill another active episode.
_DEFAULT_MAX_CONCURRENT_ROLLOUTS = int(os.getenv("VERL_TASKSYNC_MAX_CONCURRENT_ROLLOUTS") or "64")
_ROLLOUT_SEM: asyncio.Semaphore | None = None

# Episodes currently holding an admission slot. Maintained on the event-loop
# thread only (AgentLoopWorker has one loop), so plain int updates are safe.
_INFLIGHT_ROLLOUTS = 0


def _get_rollout_sem() -> asyncio.Semaphore:
    """Lazily build the worker-wide rollout admission semaphore."""
    global _ROLLOUT_SEM
    if _ROLLOUT_SEM is None:
        _ROLLOUT_SEM = asyncio.Semaphore(_DEFAULT_MAX_CONCURRENT_ROLLOUTS)
    return _ROLLOUT_SEM


# Delay admission while MemAvailable is below the configured floor.
# Default: 5% of MemTotal; proceed after the maximum wait to avoid deadlock.
_MEM_FLOOR_POLL_S = 5.0
_MEM_FLOOR_MAX_WAIT_S = float(os.getenv("VERL_SANDBOX_MEM_FLOOR_MAX_WAIT_S") or "600")
_MEM_FLOOR_BYTES: int | None = None  # resolved lazily; 0 disables the check
_LAST_FLOOR_LOG = 0.0


def _read_meminfo_bytes(field: str) -> int | None:
    """Read a /proc/meminfo field (kB) as bytes; None if unreadable."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith(field + ":"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _get_mem_floor_bytes() -> int:
    global _MEM_FLOOR_BYTES
    if _MEM_FLOOR_BYTES is None:
        env_val = os.getenv("VERL_SANDBOX_MEM_FLOOR_BYTES") or ""
        if env_val:
            _MEM_FLOOR_BYTES = int(env_val)
        else:
            total = _read_meminfo_bytes("MemTotal")
            _MEM_FLOOR_BYTES = int(total * 0.05) if total else 0
    return _MEM_FLOOR_BYTES


async def _wait_for_memory_headroom() -> None:
    floor = _get_mem_floor_bytes()
    if floor <= 0:
        return
    global _LAST_FLOOR_LOG
    waited = 0.0
    while waited < _MEM_FLOOR_MAX_WAIT_S:
        avail = _read_meminfo_bytes("MemAvailable")
        if avail is None or avail >= floor:
            return
        now = time.monotonic()
        if now - _LAST_FLOOR_LOG > 60.0:
            _LAST_FLOOR_LOG = now
            logger.warning(
                f"[sandbox] node MemAvailable {avail / 2**30:.1f}GiB below floor "
                f"{floor / 2**30:.1f}GiB; holding new rollout admissions "
                f"({_INFLIGHT_ROLLOUTS} in flight)."
            )
        await asyncio.sleep(_MEM_FLOOR_POLL_S)
        waited += _MEM_FLOOR_POLL_S
    logger.warning(
        f"[sandbox] memory floor still unmet after {_MEM_FLOOR_MAX_WAIT_S:.0f}s; "
        f"admitting rollout anyway to avoid stalling the step."
    )


async def acquire_rollout_slot() -> None:
    """Block until this episode may hold live sandboxes (see _ROLLOUT_SEM).

    Pair every successful acquire with exactly one release_rollout_slot() in a
    finally block that runs AFTER the episode's sandbox cleanup.
    """
    global _INFLIGHT_ROLLOUTS
    await _get_rollout_sem().acquire()
    try:
        # Memory check runs while holding the slot so waiters also count
        # against the concurrency cap; released on cancellation so a slot is
        # never leaked before the caller's release pairing is armed.
        await _wait_for_memory_headroom()
    except BaseException:
        _get_rollout_sem().release()
        raise
    _INFLIGHT_ROLLOUTS += 1


def release_rollout_slot() -> None:
    """Release an admission slot; sweep orphan kernels when the worker idles.

    Synchronous on purpose: it must run to completion even while the caller is
    unwinding a CancelledError (awaits in a cancelled task's finally are
    aborted, plain calls are not). When the in-flight count hits zero no
    episode is active, so any PID still tracked in _SPAWNED_PIDS belongs to a
    sandbox whose per-rollout cleanup failed or was cancelled mid-await; those
    orphans used to accumulate monotonically across training steps until the
    node OOMed. kill_all_kernels() is a no-op when nothing leaked.
    """
    global _INFLIGHT_ROLLOUTS
    _INFLIGHT_ROLLOUTS -= 1
    _get_rollout_sem().release()
    if _INFLIGHT_ROLLOUTS == 0:
        kill_all_kernels()
        # Same invariant for env_dirs: with no episode active, anything still
        # tracked is an orphan (episode cancelled before its cleanup ran, or a
        # removal that partially failed). rmtree on the tool executor so the
        # event loop is not blocked.
        with _ENV_DIR_LOCK:
            orphan_dirs = list(_TRACKED_ENV_DIRS)
        for d in orphan_dirs:
            _TOOL_EXECUTOR.submit(cleanup_env_dir, d)
        # Reclaim reference cycles now that no episode is active. Each rollout's
        # Task_Env is a self-referential cycle (Task_Env.tools holds bound
        # methods of the Task_Env, whose __globals__ pin the whole exec'd env
        # module namespace) so it -- and any large module-level data env.py
        # loaded -- is freed only by the cyclic collector, never by refcounting.
        # teardown_env() breaks the cycle per rollout, but a cancellation can
        # skip that; collecting at idle (once per step) keeps the cyclic-garbage
        # backlog from growing without bound across steps until the node OOMs.
        gc.collect()


# Track directories before initialization so cancellation cannot orphan them.
_TRACKED_ENV_DIRS: set[str] = set()
_ENV_DIR_LOCK = threading.Lock()


def track_env_dir(env_dir: str) -> None:
    """Register an episode env_dir for orphan sweeping. Thread-safe."""
    with _ENV_DIR_LOCK:
        _TRACKED_ENV_DIRS.add(env_dir)


async def _drain_future(future):
    """Wait through repeated cancellation without cancelling executor work."""
    cancellation = None
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError as exc:
            cancellation = exc
        except BaseException:
            break
    return cancellation


async def run_sandbox_work(loop, executor, function, *args, on_cancel=None):
    """Keep ownership until work finishes, even when cancellation waits for its timeout."""
    future = loop.run_in_executor(executor, function, *args)
    cancellation = await _drain_future(future)
    if cancellation is not None:
        try:
            result = future.result()
        except BaseException:
            pass
        else:
            if on_cancel is not None:
                cleanup = loop.run_in_executor(executor, on_cancel, result)
                await _drain_future(cleanup)
                try:
                    cleanup.result()
                except BaseException:
                    logger.exception("Cleanup of cancelled sandbox work failed")
        raise cancellation
    return future.result()


async def cleanup_rollout(env, env_dir, *sandboxes):
    """Stop kernels, remove their files, and only then release admission."""

    async def finish():
        try:
            loop = asyncio.get_running_loop()
            # Shutdown may wait for startup or execution holding the operation lock.
            results = await asyncio.gather(
                *(loop.run_in_executor(None, sb.cleanup) for sb in sandboxes if sb is not None),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    logger.error("Sandbox cleanup failed: %s", result)
            teardown_env(env)
            if env_dir:
                with contextlib.suppress(ValueError):
                    sys.path.remove(env_dir)
            if env_dir:
                await loop.run_in_executor(None, cleanup_env_dir, env_dir)
        finally:
            release_rollout_slot()

    task = asyncio.create_task(finish())
    cancellation = await _drain_future(task)
    if cancellation is not None:
        try:
            task.result()
        except BaseException:
            logger.exception("Cancelled rollout cleanup failed")
        raise cancellation
    task.result()


def cleanup_env_dir(env_dir: str) -> None:
    """Blocking rmtree + untrack; safe to call from any thread.

    Untracks only once the directory is actually gone, so a partial removal
    (e.g. a dying kernel still writing into its workspace) is retried by the
    next idle sweep instead of silently leaking.
    """
    shutil.rmtree(env_dir, ignore_errors=True)
    if not os.path.exists(env_dir):
        with _ENV_DIR_LOCK:
            _TRACKED_ENV_DIRS.discard(env_dir)


def teardown_env(env) -> None:
    """Release a finished episode's Task_Env so its memory is reclaimed now.

    The agent loops construct a fresh user ``Task_Env`` per rollout (tens of
    thousands per run). That object is a reference cycle -- ``task_env.tools``
    maps each tool name to a *bound method* of ``task_env``, and every bound
    method keeps ``task_env`` alive (``__self__``) *and* pins the entire exec'd
    env-module namespace (``__func__.__globals__``), which may include large
    objects env.py loaded at import time (DataFrames, parsed datasets, ...).
    Because of the cycle none of this is freed by refcounting when the rollout
    returns; it survives until the cyclic collector happens to run. Under
    per-rollout churn plus the node's Megatron CPU-offload pressure that
    backlog grows until the OOM killer takes out a worker.

    Breaking the cycle here (clearing ``tools`` and dropping ``env``'s handles)
    makes the Task_Env, its class, and the module namespace collectable by
    refcounting immediately. Best-effort and exception-safe: it runs on the
    episode's cleanup path, which must not raise. Idempotent.
    """
    if env is None:
        return
    task_env = getattr(env, "task_env", None)
    if task_env is not None:
        # Defensive: let envs that hold a persistent handle (sqlite connection,
        # open file, ...) release it. Most envs open/close per tool call and
        # expose no closer; that is fine.
        for closer in ("close", "cleanup"):
            fn = getattr(task_env, closer, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
                break
        tools = getattr(task_env, "tools", None)
        if isinstance(tools, dict):
            tools.clear()
    # Drop every back-reference the episode held so the chain collapses under
    # refcounting. setattr is guarded because the env-state dataclasses differ
    # slightly between agent loops (e.g. only the PTC loop omits `sandbox`).
    for attr in ("task_env", "sandbox", "ptc_sandbox", "terminal_executor"):
        if hasattr(env, attr):
            try:
                setattr(env, attr, None)
            except Exception:
                pass


def _set_pdeathsig(sig: int) -> None:
    """Best-effort: ask the kernel to deliver `sig` when our parent dies.

    Called from preexec_fn (already in the forked child). Failure is silent --
    we still have the explicit cleanup() path and kill_all_kernels() as
    fallbacks if the syscall is unavailable.
    """
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(
            ctypes.c_int(_PR_SET_PDEATHSIG),
            ctypes.c_ulong(sig),
            ctypes.c_ulong(0),
            ctypes.c_ulong(0),
            ctypes.c_ulong(0),
        )
    except Exception:
        pass


# Fork from a persistent thread: PR_SET_PDEATHSIG follows the forking thread,
# so recycling an executor thread would otherwise kill live kernels.
_FORK_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="sandbox-fork")


# Offload blocking sandbox/terminal calls without blocking the event loop.
# Each sandbox must be used sequentially. In-process Task_Env calls stay on
# their owning thread because resources such as SQLite connections are thread-affine.
_DEFAULT_MAX_CONCURRENT_TOOL_EXEC = int(os.getenv("VERL_SANDBOX_MAX_CONCURRENT_EXEC", "32"))
_TOOL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=_DEFAULT_MAX_CONCURRENT_TOOL_EXEC, thread_name_prefix="sandbox-tool"
)


def get_tool_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Worker-wide executor for blocking sandbox/terminal tool calls.

    See _TOOL_EXECUTOR. Bounded by VERL_SANDBOX_MAX_CONCURRENT_EXEC.
    """
    return _TOOL_EXECUTOR


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


class _BoundedStreamBuffer:
    """Accumulates kernel stream text with a bounded memory footprint.

    Keeps a fixed head plus a rolling tail (so the final traceback stays
    visible) and drops the middle DURING accumulation. Previously the full
    stream was accumulated and truncate_output applied only after execution
    finished, so a print-storm could balloon the worker process RSS by
    (timeout x zmq throughput) bytes before truncation ever ran.

    ``head_cap``/``tail_cap`` <= 0 disables the bound (old behavior).
    """

    def __init__(self, head_cap: int, tail_cap: int):
        self._head: list[str] = []
        self._head_len = 0
        self._tail: collections.deque = collections.deque()
        self._tail_len = 0
        self._dropped = 0
        self._head_cap = head_cap
        self._tail_cap = tail_cap

    def append(self, text: str) -> None:
        if not text:
            return
        if self._head_cap <= 0 or self._tail_cap <= 0:
            self._head.append(text)
            return
        if self._head_len < self._head_cap:
            take = min(len(text), self._head_cap - self._head_len)
            self._head.append(text[:take])
            self._head_len += take
            text = text[take:]
            if not text:
                return
        if len(text) > self._tail_cap:
            self._dropped += len(text) - self._tail_cap
            text = text[-self._tail_cap :]
        self._tail.append(text)
        self._tail_len += len(text)
        while self._tail_len > self._tail_cap:
            chunk = self._tail.popleft()
            drop = min(len(chunk), self._tail_len - self._tail_cap)
            self._tail_len -= drop
            self._dropped += drop
            if drop < len(chunk):
                self._tail.appendleft(chunk[drop:])

    def value(self) -> str:
        head = "".join(self._head)
        tail = "".join(self._tail)
        if self._dropped:
            return f"{head}\n...[{self._dropped} chars dropped during execution]...\n{tail}"
        return head + tail


def truncate_output(text: str, limit: int) -> str:
    """Middle-truncate `text` to ~`limit` chars, keeping head and tail.

    The head usually carries the model's own progress prints and the tail the
    final summary/traceback, so both are preserved. `limit <= 0` disables.
    """
    if limit <= 0 or len(text) <= limit:
        return text
    head = int(limit * 0.7)
    tail = limit - head
    omitted = len(text) - head - tail
    return (
        f"{text[:head]}\n...[output truncated: {omitted} chars omitted; "
        f"print concise summaries instead of large raw data]...\n{text[-tail:]}"
    )


def _child_pids(ppid: int) -> list[int]:
    """Immediate children of `ppid`, in HOST pid terms.

    Tries the cheap children file (needs CONFIG_PROC_CHILDREN), then falls back
    to scanning /proc for entries whose stat ppid matches.
    """
    try:
        with open(f"/proc/{ppid}/task/{ppid}/children") as f:
            kids = [int(x) for x in f.read().split()]
        if kids:
            return kids
    except (OSError, ValueError):
        pass
    out = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return out
    for e in entries:
        if not e.isdigit():
            continue
        try:
            with open(f"/proc/{e}/stat") as f:
                data = f.read()
            # Fields after the (possibly space/paren-containing) comm: state ppid
            after = data[data.rfind(")") + 2 :].split()
            if int(after[1]) == ppid:
                out.append(int(e))
        except (OSError, IndexError, ValueError):
            continue
    return out


def _find_kernel_pid(bwrap_pid: int, max_depth: int = 4) -> int | None:
    """Locate the ipykernel process beneath `bwrap_pid`, in HOST pid terms.

    The layering depends on whether the PID namespace was unshared:

        bwrap -> kernel                     (shared PID namespace)
        bwrap -> ns-init -> kernel          (--unshare-pid; bwrap's do_init()
                                             is PID 1 inside and reaps zombies)

    So we can't just take the immediate child -- under --unshare-pid that is the
    init, and SIGINTing it would not interrupt the running cell. Walk the
    descendants and pick the one that is actually the kernel. Called right after
    wait_for_ready(), before any user code runs, so the tree is still the plain
    chain above. Returns None if it can't be identified; the caller then falls
    back to the process-group path.
    """
    frontier = [bwrap_pid]
    deepest = None
    for _ in range(max_depth):
        nxt = []
        for pid in frontier:
            for kid in _child_pids(pid):
                nxt.append(kid)
                try:
                    with open(f"/proc/{kid}/cmdline", "rb") as f:
                        argv = f.read().split(b"\0")
                except OSError:
                    continue
                if not argv or not argv[0]:
                    continue
                # bwrap's init keeps bwrap's own argv, which ENDS in
                # "... -- python -m ipykernel_launcher" -- so a plain substring
                # match would pick the init and SIGINT would never reach the
                # kernel. Require argv[0] to be the interpreter, not bwrap.
                if os.path.basename(argv[0]) == b"bwrap":
                    continue
                if b"ipykernel" in b" ".join(argv):
                    return kid
        if not nxt:
            break
        deepest = nxt[0]
        frontier = nxt
    return deepest


def _force_kill_pid(pid: int, expected_starttime: int | None = None):
    """Best-effort kill a process group, then the PID itself.

    When `expected_starttime` is given, the kill is skipped if the live
    process's starttime no longer matches — the pid has been recycled to an
    unrelated process (possibly a Ray daemon/actor) and must not be touched.
    """
    if expected_starttime is not None:
        current = _proc_starttime(pid)
        if current is None:
            return  # already gone
        if current != expected_starttime:
            print(
                f"[sandbox] skip stale-PID kill: pid={pid} was recycled (starttime {expected_starttime} -> {current})",
                flush=True,
            )
            return
    for sig in (signal.SIGKILL,):
        try:
            os.killpg(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def kill_all_kernels():
    """Force-kill every kernel process we ever spawned. Call between envs."""
    with _PID_LOCK:
        pids = dict(_SPAWNED_PIDS)
        _SPAWNED_PIDS.clear()
    for pid, starttime in pids.items():
        _force_kill_pid(pid, expected_starttime=starttime)
    # Reap zombies
    for pid in pids:
        try:
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass
    # Reclaim cgroup leaves whose kernels just died (incl. cancelled rollouts
    # whose StatefulSandbox.cleanup() never ran). Done after the reap so the
    # leaves are empty and removable.
    _sweep_cgroup_leaves()


# -- Landlock isolation --------------------------------------------------------


def _landlock_abi_version() -> int:
    """Return the kernel's Landlock ABI version, or 0 if unavailable."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        # SYS_landlock_create_ruleset = 444 (x86_64 and aarch64)
        LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
        ver = libc.syscall(
            ctypes.c_long(444),  # SYS_landlock_create_ruleset
            None,
            ctypes.c_size_t(0),
            ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION),
        )
        return max(int(ver), 0)
    except Exception:
        return 0


def _apply_landlock(writable_dirs: list[str]) -> bool:
    """Apply Landlock FS restrictions to the calling process.

    Called inside the child process (preexec_fn) before exec.
    After this call the kernel process and any subprocess it spawns will:
      - be allowed to read / execute anywhere on the filesystem
      - be allowed to write ONLY inside the directories in *writable_dirs*

    Returns True on success, False if Landlock is unsupported or failed
    (the caller should then fall back gracefully).

    No special privileges are required (works without root / sudo).
    Requires Linux kernel >= 5.13 with CONFIG_SECURITY_LANDLOCK=y.
    """
    try:
        libc = ctypes.CDLL(None, use_errno=True)

        # Syscall numbers -- identical on x86_64 and aarch64
        SYS_landlock_create_ruleset = 444
        SYS_landlock_add_rule = 445
        SYS_landlock_restrict_self = 446
        LANDLOCK_RULE_PATH_BENEATH = 1

        # FS access-right bit positions (cumulative across Landlock ABI versions)
        _BIT = {
            "EXECUTE": 1 << 0,  # v1
            "WRITE_FILE": 1 << 1,  # v1
            "READ_FILE": 1 << 2,  # v1
            "READ_DIR": 1 << 3,  # v1
            "REMOVE_DIR": 1 << 4,  # v1
            "REMOVE_FILE": 1 << 5,  # v1
            "MAKE_CHAR": 1 << 6,  # v1
            "MAKE_DIR": 1 << 7,  # v1
            "MAKE_REG": 1 << 8,  # v1
            "MAKE_SOCK": 1 << 9,  # v1
            "MAKE_FIFO": 1 << 10,  # v1
            "MAKE_BLOCK": 1 << 11,  # v1
            "MAKE_SYM": 1 << 12,  # v1
            "REFER": 1 << 13,  # v2 (kernel >= 5.19)
            "TRUNCATE": 1 << 14,  # v3 (kernel >= 6.2)
            "IOCTL_DEV": 1 << 15,  # v5 (kernel >= 6.10)
        }

        # Query ABI version
        LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
        abi = libc.syscall(
            ctypes.c_long(SYS_landlock_create_ruleset),
            None,
            ctypes.c_size_t(0),
            ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION),
        )
        if abi < 1:
            return False

        # Build flag sets according to the ABI version the kernel supports
        READ_FLAGS = _BIT["EXECUTE"] | _BIT["READ_FILE"] | _BIT["READ_DIR"]
        WRITE_FLAGS = (
            _BIT["WRITE_FILE"]
            | _BIT["REMOVE_FILE"]
            | _BIT["REMOVE_DIR"]
            | _BIT["MAKE_CHAR"]
            | _BIT["MAKE_DIR"]
            | _BIT["MAKE_REG"]
            | _BIT["MAKE_SOCK"]
            | _BIT["MAKE_FIFO"]
            | _BIT["MAKE_BLOCK"]
            | _BIT["MAKE_SYM"]
        )
        if abi >= 2:
            WRITE_FLAGS |= _BIT["REFER"]
        if abi >= 3:
            WRITE_FLAGS |= _BIT["TRUNCATE"]
        if abi >= 5:
            WRITE_FLAGS |= _BIT["IOCTL_DEV"]

        ALL_FLAGS = READ_FLAGS | WRITE_FLAGS

        # Struct layout used by landlock_create_ruleset (v1 layout: 8 bytes)
        class RulesetAttr(ctypes.Structure):
            _fields_ = [("handled_access_fs", ctypes.c_uint64)]

        # Struct layout used by landlock_add_rule with LANDLOCK_RULE_PATH_BENEATH
        class PathBeneathAttr(ctypes.Structure):
            _fields_ = [
                ("allowed_access", ctypes.c_uint64),
                ("parent_fd", ctypes.c_int32),
                ("_pad", ctypes.c_uint32),
            ]

        # Create ruleset -- we declare that we handle all known FS rights
        rs_attr = RulesetAttr(handled_access_fs=ALL_FLAGS)
        rfd = libc.syscall(
            ctypes.c_long(SYS_landlock_create_ruleset),
            ctypes.byref(rs_attr),
            ctypes.c_size_t(ctypes.sizeof(rs_attr)),
            ctypes.c_uint32(0),
        )
        if rfd < 0:
            return False

        try:
            # Rule 1: read + execute on the entire filesystem "/"
            root_fd = os.open("/", os.O_RDONLY | os.O_CLOEXEC)
            try:
                rule = PathBeneathAttr(allowed_access=READ_FLAGS, parent_fd=root_fd)
                ret = libc.syscall(
                    ctypes.c_long(SYS_landlock_add_rule),
                    ctypes.c_int(rfd),
                    ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH),
                    ctypes.byref(rule),
                    ctypes.c_uint32(0),
                )
                if ret < 0:
                    return False
            finally:
                os.close(root_fd)

            # Rule 2: full access (read + write) on each explicitly allowed directory
            for d in writable_dirs:
                os.makedirs(d, exist_ok=True)
                dfd = os.open(d, os.O_RDONLY | os.O_CLOEXEC)
                try:
                    rule = PathBeneathAttr(allowed_access=ALL_FLAGS, parent_fd=dfd)
                    ret = libc.syscall(
                        ctypes.c_long(SYS_landlock_add_rule),
                        ctypes.c_int(rfd),
                        ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH),
                        ctypes.byref(rule),
                        ctypes.c_uint32(0),
                    )
                    if ret < 0:
                        return False
                finally:
                    os.close(dfd)

            # no_new_privs must be set before landlock_restrict_self
            PR_SET_NO_NEW_PRIVS = 38
            ret = libc.prctl(
                ctypes.c_int(PR_SET_NO_NEW_PRIVS),
                ctypes.c_ulong(1),
                ctypes.c_ulong(0),
                ctypes.c_ulong(0),
                ctypes.c_ulong(0),
            )
            if ret != 0:
                return False

            # Apply the ruleset to the current process (and all future children)
            ret = libc.syscall(
                ctypes.c_long(SYS_landlock_restrict_self),
                ctypes.c_int(rfd),
                ctypes.c_uint32(0),
            )
            return ret == 0

        finally:
            os.close(rfd)

    except Exception:
        return False


# -- Sandbox class -------------------------------------------------------------


def _ensure_cgroup_base() -> bool:
    """Create the parent cgroup once and enable the memory+pids controllers in
    its subtree so per-kernel leaves can set memory.max / pids.max. Best effort;
    returns True if the base looks usable. Safe to call concurrently."""
    global _CGROUP_BASE_READY
    if _CGROUP_BASE_READY:
        return True
    with _CGROUP_BASE_LOCK:
        if _CGROUP_BASE_READY:
            return True
        try:
            os.makedirs(_CGROUP_ROOT, exist_ok=True)
            # Delegate memory+pids to children. May already be on, or the real
            # root may not have delegated them -- in that case the leaf write
            # below fails and we fall back to RLIMIT_AS only.
            try:
                with open(os.path.join(_CGROUP_ROOT, "cgroup.subtree_control"), "w") as f:
                    f.write("+memory +pids")
            except OSError:
                pass
            # Aggregate cap over the whole sandbox subtree (see
            # _CGROUP_TOTAL_MEM_ENV). Best effort: requires the memory
            # controller enabled in _CGROUP_ROOT's parent.
            total_mem_max = 0
            if _CGROUP_TOTAL_MEM_ENV:
                total_mem_max = int(_CGROUP_TOTAL_MEM_ENV)
            else:
                mem_total = _read_meminfo_bytes("MemTotal")
                total_mem_max = int(mem_total * 0.25) if mem_total else 0
            if total_mem_max > 0:
                try:
                    with open(os.path.join(_CGROUP_ROOT, "memory.max"), "w") as f:
                        f.write(str(total_mem_max))
                    with open(os.path.join(_CGROUP_ROOT, "memory.swap.max"), "w") as f:
                        f.write("0")
                    logger.info(
                        f"[sandbox] aggregate sandbox memory.max set to "
                        f"{total_mem_max / 2**30:.0f}GiB on {_CGROUP_ROOT}"
                    )
                except OSError as e:
                    _log_once(
                        "cgroup_total_mem_failed",
                        logging.WARNING,
                        f"[sandbox] could not set aggregate memory.max on "
                        f"{_CGROUP_ROOT} ({e}); per-leaf caps only (logged once).",
                    )
            _CGROUP_BASE_READY = True
            return True
        except OSError as e:
            _log_once(
                "cgroup_base_unusable",
                logging.WARNING,
                f"[sandbox] cgroup base {_CGROUP_ROOT} unusable ({e}); falling back to RLIMIT_AS only (logged once).",
            )
            return False


def _create_cgroup(name: str, mem_max: int, pids_max: str) -> str | None:
    """Create a per-kernel cgroup-v2 leaf with the given memory / pids caps.
    Returns the leaf path, or None on any failure (caller keeps RLIMIT_AS)."""
    if not _ensure_cgroup_base():
        return None
    leaf = os.path.join(_CGROUP_ROOT, name)
    try:
        os.makedirs(leaf, exist_ok=True)
        if mem_max and mem_max > 0:
            with open(os.path.join(leaf, "memory.max"), "w") as f:
                f.write(str(mem_max))
            # Forbid swap so memory.max is a hard ceiling, not soft.
            try:
                with open(os.path.join(leaf, "memory.swap.max"), "w") as f:
                    f.write("0")
            except OSError:
                pass
        if pids_max:
            try:
                with open(os.path.join(leaf, "pids.max"), "w") as f:
                    f.write(str(pids_max))
            except OSError:
                pass
        return leaf
    except OSError as e:
        _log_once(
            "cgroup_create_failed",
            logging.WARNING,
            f"[sandbox] could not create cgroup leaf ({e}); falling back to RLIMIT_AS only (logged once).",
        )
        try:
            os.rmdir(leaf)
        except OSError:
            pass
        return None


def _sweep_cgroup_leaves() -> None:
    """Best-effort rmdir of empty cgroup leaves under _CGROUP_ROOT. A leaf is
    only removable once empty (all its procs are gone), so this reclaims the
    dirs of kernels that died without their StatefulSandbox.cleanup() running
    (e.g. a cancelled rollout). Leaves still holding live procs fail rmdir and
    are skipped."""
    if not _CGROUP_ENABLE:
        return
    try:
        names = os.listdir(_CGROUP_ROOT)
    except OSError:
        return
    for name in names:
        leaf = os.path.join(_CGROUP_ROOT, name)
        try:
            os.rmdir(leaf)  # fails (and is skipped) if non-empty or not a dir
        except OSError:
            pass


def _build_bwrap_argv(
    workspace: str,
    read_paths_extra: "list[str] | tuple" = (),
    write_paths_extra: "list[str] | tuple" = (),
) -> list[str]:
    """bwrap args implementing default-deny reads (see _BWRAP_READ_PATHS).

    Read-only: the system allowlist + each path in read_paths_extra (e.g. the
    rollout's env_dir, so the PTC kernel can import env.py / open data.db).
    Writable: workspace + each path in write_paths_extra (e.g. the kernel's
    connection-file tmpdir) + a private /tmp & /dev/shm. /tmp is a fresh tmpfs
    so sibling rollouts' env_dirs are hidden; the caller's own paths are bound
    back AFTER it. workspace is bound after the read-only extras so it overlays
    read-write even when it sits inside one (workspace == env_dir/workspace).

    --unshare-pid (when the runtime allows it, see bwrap_pid_ns_usable) puts the
    sandbox in its own PID namespace so model-generated `pkill` / `kill -TERM -1`
    cannot reach the Ray runtime. The network namespace is deliberately NOT
    unshared: the kernel<->client ZMQ transport needs loopback. Teardown is
    unaffected -- start_new_session=True sets the process group on the HOST side,
    so os.killpg(proc.pid, ...) still reaches bwrap, and killing the namespace's
    init tears down everything inside it."""
    # --unshare-user-try: when running as root WITHOUT CAP_SYS_ADMIN (the jd k8s
    # container), bwrap won't create a user namespace by default and the mount
    # namespace then fails with "Operation not permitted". Forcing a user
    # namespace first grants the caps needed for the mount ns. No-op where bwrap
    # already unshares userns (e.g. unprivileged callers).
    argv = [_BWRAP_BIN, "--unshare-user-try"]
    if bwrap_pid_ns_usable():
        # Must be paired with the --proc below: a fresh procfs is what makes the
        # new namespace's process list the only one visible.
        argv += ["--unshare-pid"]
    for p in _BWRAP_READ_PATHS:
        argv += ["--ro-bind-try", p, p]
    argv += [
        "--proc",
        "/proc",  # fresh /proc for the namespace
        "--dev",
        "/dev",  # minimal writable device nodes
        "--tmpfs",
        "/tmp",  # private writable /tmp (hides siblings)
        "--tmpfs",
        "/dev/shm",  # private writable shm
    ]
    for p in read_paths_extra:  # e.g. env_dir: env.py / data.db, read-only
        argv += ["--ro-bind-try", p, p]
    argv += ["--bind", workspace, workspace]  # workspace: writable (overlays env_dir)
    for p in write_paths_extra:  # e.g. kernel.json dir: writable
        argv += ["--bind", p, p]
    argv += [
        "--setenv",
        "HOME",
        workspace,  # libs write ~/.cache into the workspace
        "--chdir",
        workspace,
        "--die-with-parent",
        "--",
    ]
    return argv


class IsolationConfig(NamedTuple):
    """Filesystem policy shared by kernel and terminal launchers."""

    workspace: str
    read_paths: tuple[str, ...] = ()
    write_paths: tuple[str, ...] = ()
    # Landlock cannot provide private tmpfs; retain the kernel's shared /tmp policy.
    landlock_write_paths: tuple[str, ...] = ("/tmp",)
    allow_landlock: bool = True


class IsolationCapabilities(NamedTuple):
    """OS guarantees of a selected backend, conditional on successful launch.

    Read allowlists still expose configured paths. Write restrictions cover the
    configured paths and supported ABI operations (Landlock truncation needs ABI 3).
    Network isolation is deliberately absent for the kernel's ZMQ transport.
    """

    restricted_reads: bool = False
    restricted_writes: bool = False
    pid_namespace: bool = False
    network_namespace: bool = False


class IsolationBackend:
    """Selected launch policy; selection alone does not mean isolation is active."""

    name = "none"
    abi = 0

    def __init__(self, config: IsolationConfig):
        self.config = config
        self.capabilities = IsolationCapabilities()

    def wrap_command(self, command: list[str]) -> list[str]:
        return list(command)

    def apply_child_restrictions(self) -> None:
        """Apply pre-exec restrictions; failure must abort the child launch."""

    def kernel_pid(self, launcher_pid: int) -> int:
        return launcher_pid

    def log_policy(self, caller: str, cgroup: bool = False, *, active: bool = False) -> None:
        caps = self.capabilities
        _log_once(
            f"confine:{caller}:{self.name}:{caps}:{active}:{cgroup}",
            logging.INFO if caps.restricted_writes else logging.WARNING,
            f"[{caller}] {'active' if active else 'selected'} isolation={self.name}"
            f"{f' ABI v{self.abi}' if self.abi else ''}; "
            f"restricted reads={caps.restricted_reads}, restricted writes={caps.restricted_writes}, "
            f"PID namespace={caps.pid_namespace}, network namespace={caps.network_namespace}"
            f"{' + cgroup memory/pids cap' if cgroup else ''}.",
        )


class _BubblewrapBackend(IsolationBackend):
    name = "bubblewrap"

    def __init__(self, config: IsolationConfig):
        super().__init__(config)
        self._prefix = tuple(_build_bwrap_argv(config.workspace, config.read_paths, config.write_paths))
        read_paths = (*_BWRAP_READ_PATHS, config.workspace, *config.read_paths, *config.write_paths)
        write_paths = (config.workspace, *config.write_paths)
        self.capabilities = IsolationCapabilities(
            restricted_reads=not any(os.path.realpath(path) == "/" for path in read_paths),
            restricted_writes=not any(os.path.realpath(path) == "/" for path in write_paths),
            pid_namespace="--unshare-pid" in self._prefix,
        )

    def wrap_command(self, command: list[str]) -> list[str]:
        return [*self._prefix, *command]

    def kernel_pid(self, launcher_pid: int) -> int:
        return _find_kernel_pid(launcher_pid) or launcher_pid


class _LandlockBackend(IsolationBackend):
    name = "landlock"

    def __init__(self, config: IsolationConfig, abi: int):
        super().__init__(config)
        self.abi = abi
        self._writable = (config.workspace, *config.write_paths, *config.landlock_write_paths)
        self.capabilities = IsolationCapabilities(
            restricted_writes=not any(os.path.realpath(path) == "/" for path in self._writable)
        )

    def apply_child_restrictions(self) -> None:
        if not _apply_landlock(list(self._writable)):
            raise RuntimeError("Failed to apply Landlock filesystem restrictions")


def select_isolation_backend(config: IsolationConfig) -> IsolationBackend:
    """Prefer bubblewrap, then permitted Landlock, then no OS filesystem isolation.

    Never retry with a weaker backend after a selected backend fails to launch.
    Bubblewrap and Landlock are not stacked: host rules do not cover private tmpfs.
    """
    if bwrap_usable():
        return _BubblewrapBackend(config)
    if config.allow_landlock:
        abi = _landlock_abi_version()
        if abi >= 1:
            return _LandlockBackend(config, abi)
    return IsolationBackend(config)


class _SandboxResources:
    """Own kernel handles; disposal runs under the sandbox operation lock."""

    def __init__(self):
        self.tmpdir = None
        self.proc = None
        self.kernel_pid = None
        self.kernel_starttime = None
        self.client = None
        self.conn_file = None
        self.cgroup_dir = None

    def close(self):
        try:
            self._stop_process()
        finally:
            try:
                self._close_client()
            finally:
                if self.tmpdir is not None:
                    shutil.rmtree(self.tmpdir, ignore_errors=True)
                    self.tmpdir = None
                self._remove_cgroup()
                self.conn_file = None
                self.kernel_pid = None
                self.kernel_starttime = None

    def _stop_process(self):
        proc = self.proc
        if proc is not None:
            pid = proc.pid
            if proc.poll() is None:
                try:
                    os.killpg(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
            else:
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass
            if proc.poll() is not None:
                self.proc = None
                with _PID_LOCK:
                    _SPAWNED_PIDS.pop(pid, None)

    def _close_client(self):
        client = self.client
        self.client = None
        if client is not None:
            try:
                client.stop_channels()
            except Exception:
                pass
            # Force-destroy the underlying ZMQ context to release ports immediately
            try:
                if hasattr(client, "context") and client.context is not None:
                    client.context.destroy(linger=0)
            except Exception:
                pass

    def _remove_cgroup(self):
        # rmdir the cgroup leaf -- only succeeds once empty (all procs reaped).
        # Retry briefly in case the kernel hasn't fully exited yet.
        cgroup_dir = self.cgroup_dir
        if cgroup_dir is not None:
            for _ in range(20):
                try:
                    os.rmdir(cgroup_dir)
                    self.cgroup_dir = None
                    break
                except FileNotFoundError:
                    self.cgroup_dir = None
                    break
                except OSError:
                    time.sleep(0.05)


class StatefulSandbox:
    """Persistent IPython execution with best-effort OS isolation.

    Bubblewrap restricts visible paths; Landlock is a write-only fallback.
    The fallback currently permits writes throughout /tmp. Without either
    backend, the Python open guard alone does not confine untrusted code.
    Use as a context manager to release the kernel and its temporary files.
    """

    def __init__(
        self,
        workspace_path: str,
        timeout: float = 10.0,
        mem_limit_bytes: int | None = None,
        interrupt_grace_seconds: float = 2.0,
        extra_read_paths: list[str] | None = None,
        max_output_chars: int | None = None,
    ):
        self.workspace_path = workspace_path
        self.max_output_chars = max_output_chars if max_output_chars is not None else _DEFAULT_MAX_OUTPUT_CHARS
        # Extra dirs to expose read-only under bwrap (besides the system
        # allowlist), e.g. the rollout's env_dir so the PTC kernel can import
        # env.py / open data.db. Leave empty for the main code-exec sandbox so
        # agent code cannot read the task's data.db / answers.
        self.extra_read_paths = list(extra_read_paths or [])
        self.timeout = timeout
        self.mem_limit_bytes = mem_limit_bytes if mem_limit_bytes is not None else _DEFAULT_MEM_LIMIT_BYTES
        self.interrupt_grace_seconds = interrupt_grace_seconds
        self._resources = _SandboxResources()
        self._operation_lock = threading.RLock()
        self._close_requested = threading.Event()
        self._started = False
        self._cleaned_up = False
        self._dead = False
        self._landlock_active = False
        self.isolation_backend: IsolationBackend | None = None
        self.isolation_active = False
        # cgroup memory.max for this kernel's subtree; defaults to the same
        # value as the RLIMIT_AS cap. 0 disables the cgroup memory cap.
        self.cgroup_mem_max = int(os.getenv("VERL_SANDBOX_CGROUP_MEM_MAX", str(self.mem_limit_bytes or 0)))

    @property
    def _tmpdir(self):
        return self._resources.tmpdir

    @_tmpdir.setter
    def _tmpdir(self, value):
        self._resources.tmpdir = value

    @property
    def _proc(self):
        return self._resources.proc

    @_proc.setter
    def _proc(self, value):
        self._resources.proc = value

    @property
    def _kernel_pid(self):
        return self._resources.kernel_pid

    @_kernel_pid.setter
    def _kernel_pid(self, value):
        self._resources.kernel_pid = value
        self._resources.kernel_starttime = _proc_starttime(value) if value is not None else None

    @property
    def _client(self):
        return self._resources.client

    @_client.setter
    def _client(self, value):
        self._resources.client = value

    @property
    def _conn_file(self):
        return self._resources.conn_file

    @_conn_file.setter
    def _conn_file(self, value):
        self._resources.conn_file = value

    @property
    def _cgroup_dir(self):
        return self._resources.cgroup_dir

    @_cgroup_dir.setter
    def _cgroup_dir(self, value):
        self._resources.cgroup_dir = value

    def _check_open(self):
        if self._close_requested.is_set():
            raise RuntimeError("Sandbox has been closed")

    @contextlib.contextmanager
    def _operation(self):
        # A client and its ZMQ context must only be used/disposed by one thread.
        with self._operation_lock:
            self._check_open()
            try:
                yield
            finally:
                if self._close_requested.is_set():
                    self._dispose_resources()

    def start(self):
        """Start once; a closed or failed sandbox cannot be restarted."""
        with self._operation():
            if self._started:
                return
            try:
                self._start_impl()
                self._check_open()
                self._started = True
            except BaseException:
                self._close_requested.set()
                raise

    def _start_impl(self):
        try:
            from jupyter_client import BlockingKernelClient
        except ImportError as exc:
            raise RuntimeError(
                "jupyter_client is required for StatefulSandbox. Install it with: pip install jupyter_client ipykernel"
            ) from exc

        self._tmpdir = tempfile.mkdtemp(prefix="sandbox_")
        self._conn_file = Path(self._tmpdir) / "kernel.json"

        backend = self._launch_kernel()
        self._wait_for_connection(backend)
        self._check_open()
        self._connect_client(BlockingKernelClient)
        self._check_open()
        self._landlock_active = backend.name == "landlock"
        self._kernel_pid = self.isolation_backend.kernel_pid(self._proc.pid)
        self._initialize_workspace()
        self.isolation_active = self.isolation_backend.name != "none"
        self.isolation_backend.log_policy("sandbox", bool(self._cgroup_dir), active=self.isolation_active)

    def _launch_kernel(self):
        self._check_open()
        os.makedirs(self.workspace_path, exist_ok=True)  # bwrap --bind needs it to exist
        backend = select_isolation_backend(
            IsolationConfig(
                workspace=self.workspace_path,
                read_paths=tuple(self.extra_read_paths),
                write_paths=(self._tmpdir,),
            )
        )
        self.isolation_backend = backend
        mem_limit = self.mem_limit_bytes

        # Descendants inherit the cgroup joined by the child before exec.
        if _CGROUP_ENABLE:
            self._cgroup_dir = _create_cgroup(
                os.path.basename(self._tmpdir),
                mem_max=self.cgroup_mem_max,
                pids_max=_CGROUP_PIDS_MAX,
            )
        cgroup_procs = os.path.join(self._cgroup_dir, "cgroup.procs") if self._cgroup_dir else None

        def _preexec():
            _set_pdeathsig(signal.SIGKILL)
            joined_cgroup = False
            if cgroup_procs is not None:
                try:
                    with open(cgroup_procs, "w") as f:
                        f.write(str(os.getpid()))
                    joined_cgroup = True
                except OSError:
                    joined_cgroup = False
            # Avoid stacking RLIMIT_AS on cgroups: mmap inflates virtual memory.
            if not joined_cgroup and mem_limit and mem_limit > 0:
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))
                except (ValueError, OSError):
                    pass
            backend.apply_child_restrictions()

        kernel_cmd = backend.wrap_command([sys.executable, "-m", "ipykernel_launcher", "-f", str(self._conn_file)])

        self._check_open()
        # Both bwrap and kernel startup failures are captured on the host.
        stderr_path = os.path.join(self._tmpdir, "kernel_stderr.log")
        stderr_f = open(stderr_path, "wb")

        # Fork on the dedicated lifetime thread (see _FORK_EXECUTOR) so the
        # kernel's PR_SET_PDEATHSIG is bound to a thread that lives as long as
        # the worker process, not a recyclable run_in_executor() pool thread.
        try:
            self._proc = _FORK_EXECUTOR.submit(
                subprocess.Popen,
                kernel_cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_f,
                cwd=self.workspace_path,
                start_new_session=True,
                preexec_fn=_preexec,
            ).result()
        finally:
            stderr_f.close()  # parent's copy; the child keeps its own dup

        with _PID_LOCK:
            _SPAWNED_PIDS[self._proc.pid] = _proc_starttime(self._proc.pid)

        return backend

    def _wait_for_connection(self, backend: IsolationBackend):
        stderr_path = os.path.join(self._tmpdir, "kernel_stderr.log")

        def _stderr_tail(limit: int = 4000) -> str:
            try:
                with open(stderr_path, errors="replace") as f:
                    txt = f.read().strip()
            except OSError:
                return ""
            return txt[-limit:] if txt else ""

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            self._check_open()
            if self._conn_file.exists():
                break
            if self._proc.poll() is not None:
                tail = _stderr_tail()
                mode = backend.name
                raise RuntimeError(
                    f"IPython kernel exited early with code {self._proc.returncode} "
                    f"(confinement={mode}). stderr:\n{tail or '<empty>'}"
                )
            time.sleep(0.05)
        else:
            raise RuntimeError(f"Timeout waiting for IPython kernel to start. stderr:\n{_stderr_tail() or '<empty>'}")

    def _connect_client(self, client_type):
        client = client_type(connection_file=str(self._conn_file))
        self._client = client  # cleanup must own even a partially started client
        client.load_connection_file()

        deadline = time.monotonic() + 30
        while not _KERNEL_START_LOCK.acquire(timeout=0.1):
            self._check_open()
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out waiting for kernel start lock")
        try:
            self._check_open()
            # Only channel/connection bring-up needs serializing (jupyter_client
            # connection-file load + ZMQ port setup is not concurrency-safe).
            client.start_channels()
        finally:
            _KERNEL_START_LOCK.release()
        # Readiness can take seconds; do not serialize it across sandboxes.
        self._check_open()
        client.wait_for_ready(timeout=10.0)

    def _initialize_workspace(self):
        # This guard supplements OS isolation; it is not a security boundary.
        init_code = (
            f"import os, json, csv, sys\n"
            f"workspace = {self.workspace_path!r}\n"
            f"os.chdir(workspace)\n"
            f"_open_orig = open\n"
            f"_WRITE_MODES = frozenset('wax+')\n"
            f"def open(file, mode='r', *args, **kwargs):\n"
            f"    if _WRITE_MODES & set(str(mode)):\n"
            f"        _abs = os.path.realpath(str(file))\n"
            f"        _ws = os.path.realpath({self.workspace_path!r})\n"
            f"        if not (_abs.startswith(_ws + os.sep) or _abs == _ws):\n"
            f"            raise PermissionError(f'Write denied: {{file!r}} is outside workspace.')\n"
            f"    return _open_orig(file, mode, *args, **kwargs)\n"
        )

        _, error, success = self._run(init_code)
        if not success:
            raise RuntimeError(f"Sandbox initialization failed: {error.strip()}")

    def _try_interrupt_to_idle(self, msg_id: str, grace_seconds: float) -> bool:
        """Send SIGINT to the kernel and wait up to grace_seconds for the
        in-flight execution (msg_id) to reach an idle status. Returns True if
        the kernel recovered, False otherwise. State (variables/imports) is
        preserved on a successful interrupt."""
        if self._proc is None or self._proc.poll() is not None:
            return False
        try:
            if self.isolation_backend is not None and self.isolation_backend.name == "bubblewrap":
                if self._kernel_pid is None or self._kernel_pid == self._proc.pid:
                    self._kernel_pid = _find_kernel_pid(self._proc.pid)
                if self._kernel_pid is None or self._kernel_pid == self._proc.pid:
                    return False
                expected_starttime = self._resources.kernel_starttime
                if expected_starttime is None or _proc_starttime(self._kernel_pid) != expected_starttime:
                    return False
            if self._kernel_pid is not None and self._kernel_pid != self._proc.pid:
                # Under bwrap: SIGINT only the kernel, NOT the process group --
                # the group leader is bwrap, which would die on SIGINT and take
                # the kernel with it (--die-with-parent), turning a state-
                # preserving interrupt into a hard kill.
                os.kill(self._kernel_pid, signal.SIGINT)
            else:
                os.killpg(self._proc.pid, signal.SIGINT)
        except (ProcessLookupError, PermissionError, OSError):
            return False
        deadline = time.monotonic() + grace_seconds
        client = self._client
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                msg = client.get_iopub_msg(timeout=remaining)
            except Exception:
                return False
            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            msg_type = msg.get("header", {}).get("msg_type", "")
            content = msg.get("content", {})
            if msg_type == "status" and content.get("execution_state") == "idle":
                return True

    def _kill_kernel_now(self):
        """Hard-kill the kernel process group and mark sandbox dead."""
        self._dead = True
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                os.kill(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        if proc.poll() is not None:
            # The child is reaped, so the OS may recycle its PID. Stop
            # tracking it now: if this sandbox's cleanup() never runs (e.g.
            # the rollout task is cancelled), a later kill_all_kernels()
            # sweep would otherwise SIGKILL whatever unrelated process
            # inherited the recycled PID.
            with _PID_LOCK:
                _SPAWNED_PIDS.pop(proc.pid, None)

    def _run(self, code: str, timeout: float | None = None) -> tuple[str, str, bool]:
        """Execute code in the kernel and return (stdout, stderr, success)."""
        if self._dead:
            raise RuntimeError("Kernel was killed after a previous timeout")
        if self._proc is not None and self._proc.poll() is not None:
            self._dead = True
            # poll() reaped the child, so the OS may recycle its PID. Stop
            # tracking it now (same hazard as in _kill_kernel_now): if this
            # sandbox's cleanup() never runs, a later kill_all_kernels()
            # sweep must not SIGKILL whatever inherited the recycled PID.
            with _PID_LOCK:
                _SPAWNED_PIDS.pop(self._proc.pid, None)
            raise RuntimeError(f"Kernel process has exited unexpectedly (code {self._proc.returncode})")
        client = self._client
        msg_id = client.execute(code, silent=False, store_history=True)
        effective_timeout = self.timeout if timeout is None else timeout
        deadline = time.monotonic() + effective_timeout

        # Bound the in-flight accumulation (not just the final result): a
        # print-storm can stream far more than max_output_chars before the
        # execution finishes, and truncate_output only runs at the end.
        if self.max_output_chars > 0:
            head_cap = max(2 * self.max_output_chars, 131072)
            tail_cap = max(self.max_output_chars, 65536)
        else:
            head_cap = tail_cap = 0  # truncation disabled -> unbounded
        out_parts = _BoundedStreamBuffer(head_cap, tail_cap)
        err_parts = _BoundedStreamBuffer(head_cap, tail_cap)
        success = True

        while True:
            self._check_open()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # Try to interrupt cleanly so kernel state survives; otherwise
                # SIGKILL the kernel so subsequent execute() calls don't block
                # for another full timeout each.
                recovered = self._try_interrupt_to_idle(msg_id, self.interrupt_grace_seconds)
                if not recovered:
                    self._kill_kernel_now()
                raise TimeoutError("Kernel execution timed out")
            try:
                msg = client.get_iopub_msg(timeout=min(remaining, 0.1))
            except queue.Empty:
                continue
            except Exception as exc:
                recovered = self._try_interrupt_to_idle(msg_id, self.interrupt_grace_seconds)
                if not recovered:
                    self._kill_kernel_now()
                raise TimeoutError("Kernel execution timed out") from exc

            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue

            msg_type = msg.get("header", {}).get("msg_type", "")
            content = msg.get("content", {})

            if msg_type == "stream":
                target = out_parts if content.get("name") == "stdout" else err_parts
                target.append(content.get("text", ""))
            elif msg_type in ("execute_result", "display_data"):
                data = content.get("data", {})
                if "text/plain" in data:
                    out_parts.append(f"{data['text/plain']}\n")
            elif msg_type == "error":
                success = False
                tb = content.get("traceback") or []
                if tb:
                    err_parts.append("\n".join(tb) + "\n")
                else:
                    err_parts.append(f"{content.get('ename', 'Error')}: {content.get('evalue', '')}\n")
            elif msg_type == "status" and content.get("execution_state") == "idle":
                break

        return strip_ansi(out_parts.value()), strip_ansi(err_parts.value()), success

    def execute(self, code: str, timeout: float | None = None) -> tuple[str, bool]:
        """Execute code and return (output, success).

        State from previous calls is preserved. Returns an error string on
        failure rather than raising. ``success`` is False whenever the kernel
        reported an exception, the sandbox was unavailable, or execution timed
        out -- i.e. any case where ``output`` carries an error message.

        ``timeout`` overrides the sandbox-level default for this single call.
        """
        try:
            with self._operation():
                return self._execute_impl(code, timeout)
        except Exception as exc:
            return f"[Error] {exc}", False

    def _execute_impl(self, code: str, timeout: float | None) -> tuple[str, bool]:
        if not isinstance(code, str):
            return (
                f"[Error] The 'code' argument must be a string, got {type(code).__name__}: {code!r}.",
                False,
            )
        if self._client is None:
            return "[Error] Sandbox not started. Call start() first.", False
        if self._dead:
            return (
                "[Error] Sandbox is no longer available "
                "(killed after a previous timeout / crash). Subsequent code will not run."
            ), False
        effective_timeout = self.timeout if timeout is None else timeout
        try:
            output, error, success = self._run(code, timeout=effective_timeout)
            result = output
            if error.strip():
                result += ("\n[stderr]:\n" if result else "") + error.strip()
            result = truncate_output(result.strip(), self.max_output_chars)
            return (result if result else "(no output)"), success
        except TimeoutError:
            suffix = (
                " Sandbox killed; subsequent code will not run."
                if self._dead
                else " Sandbox interrupted; state preserved."
            )
            return (
                f"[Error] Code execution timed out ({effective_timeout}-second limit).{suffix}",
                False,
            )
        except Exception as e:
            return f"[Error] {e}", False

    def cleanup(self):
        """Cancel active work, then wait until all owned resources are released."""
        self._close_requested.set()
        with self._operation_lock:
            self._dispose_resources()

    def _dispose_resources(self):
        if self._cleaned_up:
            return
        self._dead = True
        self.isolation_active = False
        self._resources.close()
        self._cleaned_up = self._proc is None and self._cgroup_dir is None
        self._landlock_active = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.cleanup()

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass
