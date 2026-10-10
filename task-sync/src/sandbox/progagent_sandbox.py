"""Stateful Python and shell execution with shared filesystem isolation."""

import codecs
import collections
import contextlib
import ctypes
import functools
import os
import re
import resource
import select
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import warnings
import weakref
from pathlib import Path

_DEFAULT_MEM_LIMIT_BYTES = int(os.getenv("TASKSYNC_SANDBOX_MEM_LIMIT_BYTES", str(8 * 1024**3)))
_DEFAULT_MAX_OUTPUT_CHARS = int(os.getenv("TASKSYNC_SANDBOX_MAX_OUTPUT_CHARS", "50000"))

_KERNEL_START_LOCK = threading.Lock()

_LIVE_SANDBOXES = weakref.WeakSet()
_PID_LOCK = threading.Lock()


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


class _BoundedStreamBuffer:
    """Keep a bounded head and rolling tail during execution."""

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


def kill_all_kernels():
    """Close owned sandboxes without signalling stale/recycled process IDs."""
    with _PID_LOCK:
        sandboxes = list(_LIVE_SANDBOXES)
    for sandbox in sandboxes:
        sandbox.cleanup()


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
    """Allow host reads, writes in supplied directories, and safe device writes.

    Return False on failure; the selected backend must abort child startup.
    """
    try:
        libc = ctypes.CDLL(None, use_errno=True)

        SYS_landlock_create_ruleset = 444
        SYS_landlock_add_rule = 445
        SYS_landlock_restrict_self = 446
        LANDLOCK_RULE_PATH_BENEATH = 1

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

        LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
        abi = libc.syscall(
            ctypes.c_long(SYS_landlock_create_ruleset),
            None,
            ctypes.c_size_t(0),
            ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION),
        )
        if abi < 1:
            return False

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

        class RulesetAttr(ctypes.Structure):
            _fields_ = [("handled_access_fs", ctypes.c_uint64)]

        class PathBeneathAttr(ctypes.Structure):
            _fields_ = [
                ("allowed_access", ctypes.c_uint64),
                ("parent_fd", ctypes.c_int32),
                ("_pad", ctypes.c_uint32),
            ]

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

            for device in ("/dev/null", "/dev/zero", "/dev/random", "/dev/urandom"):
                dfd = os.open(device, os.O_PATH | os.O_CLOEXEC)
                try:
                    rule = PathBeneathAttr(allowed_access=_BIT["WRITE_FILE"], parent_fd=dfd)
                    if (
                        libc.syscall(
                            ctypes.c_long(SYS_landlock_add_rule),
                            ctypes.c_int(rfd),
                            ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH),
                            ctypes.byref(rule),
                            ctypes.c_uint32(0),
                        )
                        < 0
                    ):
                        return False
                finally:
                    os.close(dfd)

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


class StatefulSandbox:
    """Persistent IPython kernel. execute() returns text; cleanup() is idempotent."""

    def __init__(
        self,
        workspace_path: str,
        timeout: float = 10.0,
        env_file: str | None = None,
        db_path: str | None = None,
        mem_limit_bytes: int | None = None,
        interrupt_grace_seconds: float = 2.0,
        max_output_chars: int | None = None,
    ):
        self.workspace_path = os.path.realpath(workspace_path)
        self.timeout = timeout
        self.max_output_chars = max_output_chars if max_output_chars is not None else _DEFAULT_MAX_OUTPUT_CHARS
        self.mem_limit_bytes = mem_limit_bytes if mem_limit_bytes is not None else _DEFAULT_MEM_LIMIT_BYTES
        self.interrupt_grace_seconds = interrupt_grace_seconds
        self._env_file = os.path.realpath(env_file) if env_file else None
        self._db_path = os.path.realpath(db_path) if db_path else None
        self._tmpdir: str | None = None
        self._proc: subprocess.Popen | None = None
        self._client = None
        self._conn_file: Path | None = None
        self._cleaned_up = False
        self._dead = False
        self._landlock_active = False
        self._operation_lock = threading.RLock()
        self._close_requested = threading.Event()
        self._started = False
        self.isolation_backend = None
        self._stderr_thread = None
        self._stderr_stop = threading.Event()
        self._stderr_buffer = _output_buffer(4000)
        self._kernel_pid = None
        self._kernel_starttime = None
        self._stderr_lock = threading.Lock()

    def _check_open(self):
        if self._close_requested.is_set():
            raise RuntimeError("Sandbox has been closed")

    @contextlib.contextmanager
    def _operation(self):
        with self._operation_lock:
            self._check_open()
            try:
                yield
            finally:
                if self._close_requested.is_set():
                    self._dispose_resources()

    def start(self):
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

        os.makedirs(self.workspace_path, exist_ok=True)
        writable = [self.workspace_path, self._tmpdir]
        if self._env_file and self._db_path:
            # SQLite needs its database directory for journal/WAL sidecars.
            writable.append(os.path.dirname(self._db_path))
        self.isolation_backend = select_isolation_backend(writable)
        backend = self.isolation_backend
        self._proc = subprocess.Popen(
            backend.wrap_command([sys.executable, "-m", "ipykernel_launcher", "-f", str(self._conn_file)]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=self.workspace_path,
            start_new_session=True,
            env={
                **os.environ,
                "TMPDIR": self._tmpdir,
                "IPYTHONDIR": self._tmpdir,
                "JUPYTER_RUNTIME_DIR": self._tmpdir,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            preexec_fn=backend.child_setup(self.mem_limit_bytes),
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        self._proc._sandbox_starttime = _proc_starttime(self._proc.pid)
        with _PID_LOCK:
            _LIVE_SANDBOXES.add(self)

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            self._check_open()
            if self._conn_file.exists():
                break
            if self._proc.poll() is not None:
                raise RuntimeError(
                    f"IPython kernel exited early with code {self._proc.returncode}: {self._startup_error()}"
                )
            time.sleep(0.05)
        else:
            raise RuntimeError(f"Timeout waiting for IPython kernel to start: {self._startup_error()}")

        client = BlockingKernelClient(connection_file=str(self._conn_file))
        self._client = client
        client.load_connection_file()

        acquired = _KERNEL_START_LOCK.acquire(timeout=30)
        if not acquired:
            raise RuntimeError("Timed out waiting for kernel start lock")
        try:
            # Only channel/connection bring-up needs serializing (jupyter_client
            # connection-file load + ZMQ port setup is not concurrency-safe).
            client.start_channels()
        finally:
            _KERNEL_START_LOCK.release()
        self._check_open()
        client.wait_for_ready(timeout=10.0)
        self._check_open()
        self._landlock_active = backend.name == "landlock"
        self._kernel_pid = _find_kernel_pid(self._proc.pid) if backend.name == "bubblewrap" else self._proc.pid
        self._kernel_starttime = _proc_starttime(self._kernel_pid) if self._kernel_pid is not None else None
        init_code = (
            f"import os, json, csv, sys\nworkspace = {self.workspace_path!r}\n"
            f"os.chdir({self.workspace_path!r})\n"
            "_open_orig = open\n"
            "def open(file, mode='r', *args, **kwargs):\n"
            "    if frozenset('wax+') & set(str(mode)):\n"
            "        _abs = os.path.realpath(str(file))\n"
            "        if os.path.commonpath([_abs, workspace]) != workspace:\n"
            "            raise PermissionError('Write denied outside workspace')\n"
            "    return _open_orig(file, mode, *args, **kwargs)\n"
        )
        self._initialize(init_code)

        # Inject Task_Env + tools into the kernel so programmatic_tool_call
        # can run inside the sandbox rather than in the parent process.
        if self._env_file and self._db_path:
            env_init_code = (
                f"import importlib.util as _ilu\n"
                f"_spec = _ilu.spec_from_file_location('_task_env_mod', {repr(self._env_file)})\n"
                f"_mod = _ilu.module_from_spec(_spec)\n"
                f"_spec.loader.exec_module(_mod)\n"
                f"env = _mod.Task_Env(db_path={repr(self._db_path)}, workspace={repr(self.workspace_path)})\n"
                f"class _ToolsProxy:\n"
                f"    @staticmethod\n"
                f"    def _unknown(name):\n"
                f"        return \"Unknown tool '%s'. Available tools: %s\" % (name, ', '.join(sorted(env.tools)))\n"
                f"    def __getitem__(self, name):\n"
                f"        if name not in env.tools:\n"
                f"            raise KeyError(self._unknown(name))\n"
                f"        def _call(*args, **kwargs):\n"
                f"            return env.tools[name](*args, **kwargs)\n"
                f"        return _call\n"
                f"    def __getattr__(self, name):\n"
                f"        if name not in env.tools:\n"
                f"            raise AttributeError(self._unknown(name))\n"
                f"        def _call(*args, **kwargs):\n"
                f"            return env.tools[name](*args, **kwargs)\n"
                f"        return _call\n"
                f"tools = _ToolsProxy()\n"
            )
            self._initialize(env_init_code)

    def _drain_stderr(self):
        stream = self._proc.stderr
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while not self._stderr_stop.is_set():
                if not select.select([stream], [], [], 0.1)[0]:
                    continue
                chunk = os.read(stream.fileno(), 65536)
                with self._stderr_lock:
                    self._stderr_buffer.append(decoder.decode(chunk, final=not chunk))
                if not chunk:
                    break
        finally:
            stream.close()

    def _startup_error(self):
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=0.2)
        with self._stderr_lock:
            return self._stderr_buffer.value().strip()

    def _initialize(self, code):
        _, error, success = self._run(code)
        if not success:
            raise RuntimeError(f"Sandbox initialization failed: {error}")

    def _try_interrupt_to_idle(self, msg_id: str, grace_seconds: float) -> bool:
        """Send SIGINT to the kernel and wait up to grace_seconds for the
        in-flight execution (msg_id) to reach an idle status. Returns True if
        the kernel recovered (state preserved), False otherwise."""
        if self._proc is None or self._proc.poll() is not None:
            return False
        try:
            if self.isolation_backend.name == "bubblewrap":
                if (
                    self._kernel_pid is None
                    or self._kernel_starttime is None
                    or _proc_starttime(self._kernel_pid) != self._kernel_starttime
                ):
                    return False
                os.kill(self._kernel_pid, signal.SIGINT)
            else:
                os.killpg(self._proc.pid, signal.SIGINT)
        except (ProcessLookupError, PermissionError, OSError):
            return False
        deadline = time.monotonic() + grace_seconds
        client = self._client
        while True:
            self._check_open()
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
        self._dead = True
        if self._proc is not None:
            _stop_process(self._proc)

    def _run(self, code: str) -> tuple[str, str, bool]:
        """Execute code in the kernel and return (stdout, stderr, success)."""
        if self._dead:
            raise RuntimeError("Kernel was killed after a previous timeout")
        if self._proc is not None and self._proc.poll() is not None:
            self._dead = True
            raise RuntimeError(f"Kernel process has exited unexpectedly (code {self._proc.returncode})")
        client = self._client
        msg_id = client.execute(code, silent=False, store_history=True)
        deadline = time.monotonic() + self.timeout

        out_parts = _output_buffer(self.max_output_chars)
        err_parts = _output_buffer(self.max_output_chars)
        success = True

        while True:
            self._check_open()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                recovered = self._try_interrupt_to_idle(msg_id, self.interrupt_grace_seconds)
                if not recovered:
                    self._kill_kernel_now()
                raise TimeoutError("Kernel execution timed out") from None
            try:
                msg = client.get_iopub_msg(timeout=remaining)
            except Exception:
                recovered = self._try_interrupt_to_idle(msg_id, self.interrupt_grace_seconds)
                if not recovered:
                    self._kill_kernel_now()
                raise TimeoutError("Kernel execution timed out") from None

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

    def execute(self, code: str) -> str:
        try:
            with self._operation():
                return self._execute_impl(code)
        except Exception as exc:
            return f"[Error] {exc}"

    def _execute_impl(self, code: str) -> str:
        """Execute code and return output as a string.

        State from previous calls is preserved. Returns an error string on
        failure rather than raising, to match the old run_python_code interface.
        """
        if self._client is None:
            return "[Error] Sandbox not started. Call start() first."
        if self._dead:
            return (
                "[Error] Sandbox is no longer available "
                "(killed after a previous timeout / crash). Subsequent code will not run."
            )
        try:
            output, error, success = self._run(code)
            result = output
            if error.strip():
                result += ("\n[stderr]:\n" if result else "") + error.strip()
            result = truncate_output(result.strip(), self.max_output_chars)
            return result if result else "(no output)"
        except TimeoutError:
            suffix = (
                " Sandbox killed; subsequent code will not run."
                if self._dead
                else " Sandbox interrupted; state preserved."
            )
            return f"[Error] Code execution timed out ({self.timeout}-second limit).{suffix}"
        except Exception as e:
            return f"[Error] {e}"

    def cleanup(self):
        self._close_requested.set()
        with self._operation_lock:
            self._dispose_resources()

    def _dispose_resources(self):
        self._dead = True
        if self._proc is not None:
            _stop_process(self._proc)
            self._stderr_stop.set()
            if self._stderr_thread is not None:
                self._stderr_thread.join(timeout=1)
            self._proc = None
        client = self._client
        if client is not None:
            client.stop_channels()
            context = getattr(client, "context", None)
            if context is not None:
                context.destroy(linger=0)
            self._client = None
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir)
            self._tmpdir = None
        with _PID_LOCK:
            _LIVE_SANDBOXES.discard(self)
        self._cleaned_up = True

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


def _output_buffer(limit):
    return (
        _BoundedStreamBuffer(max(1, int(limit * 0.7)), max(1, limit - int(limit * 0.7)))
        if limit > 0
        else _BoundedStreamBuffer(0, 0)
    )


@functools.lru_cache(maxsize=1)
def bwrap_usable():
    if os.getenv("TASKSYNC_SANDBOX_USE_BWRAP", "1") == "0" or not shutil.which("bwrap"):
        return False
    try:
        return (
            subprocess.run(
                ["bwrap", "--unshare-user-try", "--ro-bind", "/", "/", "--", "true"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


class IsolationBackend:
    """Shared write confinement; host reads and networking remain available."""

    def __init__(self, name, writable_dirs):
        self.name = name
        self.restricted_reads = False
        self.restricted_writes = name != "none"
        self.writable_dirs = tuple(dict.fromkeys(os.path.realpath(p) for p in writable_dirs))

    def wrap_command(self, command):
        if self.name != "bubblewrap":
            return command
        argv = [
            "bwrap",
            "--die-with-parent",
            "--unshare-user-try",
            "--ro-bind",
            "/",
            "/",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
        ]
        for path in sorted(self.writable_dirs, key=len):
            argv += ["--bind", path, path]
        return argv + ["--"] + command

    def child_setup(self, mem_limit=0):
        def setup():
            if mem_limit > 0:
                resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))
            if self.name == "landlock" and not _apply_landlock(list(self.writable_dirs)):
                raise RuntimeError("Failed to install selected Landlock policy")

        return setup


def select_isolation_backend(writable_dirs):
    name = "bubblewrap" if bwrap_usable() else "landlock" if _landlock_abi_version() else "none"
    if name == "none":
        warnings.warn(
            "No OS sandbox available: shell commands are unrestricted; Python open guard is bypassable.",
            RuntimeWarning,
            stacklevel=2,
        )
    return IsolationBackend(name, writable_dirs)


def _find_kernel_pid(launcher):
    frontier = [launcher]
    for _ in range(4):
        children = []
        for pid in frontier:
            try:
                child_pids = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
            except OSError:
                continue
            for child in child_pids:
                try:
                    argv = Path(f"/proc/{child}/cmdline").read_bytes().split(b"\0")
                except OSError:
                    continue
                if argv and os.path.basename(argv[0]) != b"bwrap" and b"ipykernel_launcher" in argv:
                    return int(child)
                children.append(int(child))
        frontier = children
    return None


def _proc_starttime(pid):
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        return int(text[text.rfind(")") + 2 :].split()[19])
    except (OSError, IndexError, ValueError):
        return None


def _stop_process(proc):
    # Own the Popen until its group is stopped; never keep raw PIDs after cleanup.
    current = _proc_starttime(proc.pid)
    expected = getattr(proc, "_sandbox_starttime", None)
    if current is not None and current != expected:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait(timeout=5)


class TerminalError(Exception):
    pass


class TerminalExecutor:
    """Run shell commands with the same write policy as the Python kernel."""

    def __init__(self, workspace: str, timeout: int = 60, max_output_chars: int | None = None):
        self.workspace = os.path.realpath(workspace)
        self.timeout = timeout
        self.max_output_chars = _DEFAULT_MAX_OUTPUT_CHARS if max_output_chars is None else max_output_chars
        self.isolation_backend = None

    def execute(self, command_string: str) -> str:
        if not command_string or not command_string.strip():
            raise TerminalError("The 'command' argument is empty. Pass a non-empty shell command.")
        try:
            with tempfile.TemporaryDirectory(prefix="sandbox_terminal_") as tmpdir:
                backend = select_isolation_backend([self.workspace, tmpdir])
                self.isolation_backend = backend
                proc = subprocess.Popen(
                    backend.wrap_command(["/bin/bash", "-c", command_string]),
                    cwd=self.workspace,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    env={**os.environ, "TMPDIR": tmpdir},
                    preexec_fn=backend.child_setup(),
                )
                proc._sandbox_starttime = _proc_starttime(proc.pid)
                try:
                    output, error = self._capture(proc)
                finally:
                    try:
                        _stop_process(proc)
                    finally:
                        proc.stdout.close()
                        proc.stderr.close()
                result = output + (f"\n[stderr]: {error}" if error else "")
                return (
                    truncate_output(result, self.max_output_chars)
                    if result.strip()
                    else f"(no output, exit code: {proc.returncode})"
                )
        except TerminalError:
            raise
        except Exception as exc:
            raise TerminalError(f"Execution failed: {exc}") from exc

    def _capture(self, proc):
        deadline = time.monotonic() + self.timeout
        buffers = [_output_buffer(self.max_output_chars), _output_buffer(self.max_output_chars)]
        decoders = [codecs.getincrementaldecoder("utf-8")(errors="replace") for _ in buffers]
        with selectors.DefaultSelector() as selector:
            for index, stream in enumerate((proc.stdout, proc.stderr)):
                selector.register(stream, selectors.EVENT_READ, index)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TerminalError(f"Command timed out after {self.timeout}s")
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    index = key.data
                    buffers[index].append(decoders[index].decode(chunk, final=not chunk))
                    if not chunk:
                        selector.unregister(key.fileobj)
            try:
                proc.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as exc:
                raise TerminalError(f"Command timed out after {self.timeout}s") from exc
        return tuple(buffer.value() for buffer in buffers)
