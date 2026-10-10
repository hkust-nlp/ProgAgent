# Copyright 2026 The ProgAgent Authors
# SPDX-License-Identifier: Apache-2.0
"""Sandbox regression tests without GPU, Jupyter, or host isolation changes."""

import asyncio
import concurrent.futures
import importlib.util
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

MODULE_PATH = Path(__file__).resolve().parents[2] / "verl/experimental/agent_loop/progagent_sandbox.py"
spec = importlib.util.spec_from_file_location("sandbox_under_test", MODULE_PATH)
sandbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sandbox)


class SandboxTests(unittest.TestCase):
    def test_repeated_start_is_idempotent_and_cleanup_is_terminal(self):
        sb = sandbox.StatefulSandbox("/unused")
        with patch.object(sb, "_start_impl") as start:
            sb.start()
            sb.start()
            start.assert_called_once()
            sb.cleanup()
            sb.cleanup()
            with self.assertRaisesRegex(RuntimeError, "closed"):
                sb.start()
        output, success = sb.execute("1")
        self.assertFalse(success)
        self.assertIn("closed", output)

    def test_simultaneous_starts_spawn_once(self):
        sb = sandbox.StatefulSandbox("/unused")
        entered = threading.Event()
        resume = threading.Event()

        def start():
            entered.set()
            if not resume.wait(5):
                raise RuntimeError("Test failed to release startup")

        with patch.object(sb, "_start_impl", side_effect=start) as spawn:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(sb.start)
                try:
                    self.assertTrue(entered.wait(3))
                    second = pool.submit(sb.start)
                finally:
                    resume.set()
                first.result(timeout=3)
                second.result(timeout=3)
            spawn.assert_called_once()
        sb.cleanup()

    def test_queued_start_cannot_reopen_closed_sandbox(self):
        sb = sandbox.StatefulSandbox("/unused")
        with patch.object(sb, "_start_impl") as spawn:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                with sb._operation_lock:
                    starting = pool.submit(sb.start)
                    closing = pool.submit(sb.cleanup)
                    self.assertTrue(sb._close_requested.wait(3))
                with self.assertRaisesRegex(RuntimeError, "closed"):
                    starting.result(timeout=3)
                closing.result(timeout=3)
            spawn.assert_not_called()

    def test_concurrent_executions_use_one_client_at_a_time(self):
        sb = sandbox.StatefulSandbox("/unused")
        sb._client = MagicMock()
        entered = threading.Event()
        resume = threading.Event()

        def run(code, timeout):
            if code == "first":
                entered.set()
                if not resume.wait(5):
                    raise RuntimeError("Test failed to release execution")
            return code, "", True

        with patch.object(sb, "_run", side_effect=run) as run_mock:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(sb.execute, "first")
                try:
                    self.assertTrue(entered.wait(3))
                    second = pool.submit(sb.execute, "second")
                    self.assertEqual(run_mock.call_count, 1)
                finally:
                    resume.set()
                self.assertEqual(first.result(timeout=3), ("first", True))
                self.assertEqual(second.result(timeout=3), ("second", True))
            self.assertEqual(run_mock.call_count, 2)
        sb.cleanup()

    def test_cleanup_waits_for_start_and_releases_late_resources(self):
        for publish_before_close in (False, True):
            with self.subTest(publish_before_close=publish_before_close):
                sb = sandbox.StatefulSandbox("/unused")
                entered = threading.Event()
                resume = threading.Event()
                client = MagicMock()
                temp = tempfile.mkdtemp(prefix="sandbox_test_")
                self.addCleanup(sandbox.shutil.rmtree, temp, ignore_errors=True)
                cgroup = tempfile.mkdtemp(prefix="sandbox_cgroup_test_")
                self.addCleanup(sandbox.shutil.rmtree, cgroup, ignore_errors=True)

                def publish(sb=sb, temp=temp, client=client, cgroup=cgroup):
                    sb._tmpdir = temp
                    sb._cgroup_dir = cgroup
                    sb._client = client
                    sb._proc = MagicMock(pid=987654321)
                    sb._proc.poll.return_value = 0

                def start(publish_before_close=publish_before_close, publish=publish, entered=entered, resume=resume):
                    if publish_before_close:
                        publish()
                    entered.set()
                    if not resume.wait(5):
                        raise RuntimeError("Test failed to release startup")
                    if not publish_before_close:
                        publish()

                with patch.object(sb, "_start_impl", side_effect=start):
                    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                        starting = pool.submit(sb.start)
                        try:
                            self.assertTrue(entered.wait(3))
                            closing = pool.submit(sb.cleanup)
                            self.assertTrue(sb._close_requested.wait(3))
                            closing_again = pool.submit(sb.cleanup)
                            self.assertFalse(closing.done())
                            client.stop_channels.assert_not_called()
                        finally:
                            resume.set()
                        with self.assertRaisesRegex(RuntimeError, "closed"):
                            starting.result(timeout=3)
                        closing.result(timeout=3)
                        closing_again.result(timeout=3)
                client.stop_channels.assert_called_once()
                client.context.destroy.assert_called_once_with(linger=0)
                self.assertIsNone(sb._proc)
                self.assertIsNone(sb._client)
                self.assertFalse(Path(temp).exists())
                self.assertFalse(Path(cgroup).exists())

    def test_cleanup_cancels_execution_before_destroying_client(self):
        sb = sandbox.StatefulSandbox("/unused", timeout=60)
        client = MagicMock()
        sb._client = client
        reading = threading.Event()
        resume = threading.Event()

        def receive(**kwargs):
            reading.set()
            if not resume.wait(5):
                raise RuntimeError("Test failed to release receive")
            client.context.destroy.assert_not_called()
            raise queue.Empty

        client.get_iopub_msg.side_effect = receive
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            running = pool.submit(sb.execute, "while True: pass")
            try:
                self.assertTrue(reading.wait(3))
                closing = pool.submit(sb.cleanup)
                self.assertTrue(sb._close_requested.wait(3))
                self.assertFalse(closing.done())
            finally:
                resume.set()
            output, success = running.result(timeout=3)
            closing.result(timeout=3)
        self.assertFalse(success)
        self.assertIn("closed", output)
        client.stop_channels.assert_called_once()
        client.context.destroy.assert_called_once_with(linger=0)

    def test_base_exception_during_start_releases_resources(self):
        sb = sandbox.StatefulSandbox("/unused")
        client = MagicMock()

        def start():
            sb._client = client
            raise KeyboardInterrupt

        with patch.object(sb, "_start_impl", side_effect=start):
            with self.assertRaises(KeyboardInterrupt):
                sb.start()
        client.stop_channels.assert_called_once()
        self.assertIsNone(sb._client)

    def test_bubblewrap_interrupt_never_signals_launcher_group(self):
        for cached_pid, found_pid in ((456, None), (123, 456), (None, 456), (123, None), (123, 123)):
            with self.subTest(cached_pid=cached_pid, found_pid=found_pid):
                sb = sandbox.StatefulSandbox("/unused")
                sb.isolation_backend = SimpleNamespace(name="bubblewrap")
                sb._proc = MagicMock(pid=123)
                sb._proc.poll.return_value = None
                with patch.object(sandbox, "_proc_starttime", return_value=100):
                    sb._kernel_pid = cached_pid
                sb._client = MagicMock()
                sb._client.get_iopub_msg.return_value = {
                    "parent_header": {"msg_id": "msg"},
                    "header": {"msg_type": "status"},
                    "content": {"execution_state": "idle"},
                }
                with (
                    patch.object(sandbox, "_find_kernel_pid", return_value=found_pid),
                    patch.object(sandbox, "_proc_starttime", return_value=100),
                    patch.object(sandbox.os, "kill") as kill,
                    patch.object(sandbox.os, "killpg") as killpg,
                ):
                    recovered = sb._try_interrupt_to_idle("msg", 1)
                    self.assertEqual(recovered, cached_pid == 456 or found_pid == 456)
                    if recovered:
                        kill.assert_called_once_with(456, sandbox.signal.SIGINT)
                    else:
                        kill.assert_not_called()
                    killpg.assert_not_called()
                # Mock handles must not reach real process cleanup.
                sb._proc = None
                sb._client = None
                sb.cleanup()

    def test_bubblewrap_interrupt_rejects_reused_kernel_pid(self):
        sb = sandbox.StatefulSandbox("/unused")
        sb.isolation_backend = SimpleNamespace(name="bubblewrap")
        sb._proc = MagicMock(pid=123)
        sb._proc.poll.return_value = None
        with patch.object(sandbox, "_proc_starttime", return_value=100):
            sb._kernel_pid = 456
        with (
            patch.object(sandbox, "_proc_starttime", return_value=200),
            patch.object(sandbox.os, "kill") as kill,
            patch.object(sandbox.os, "killpg") as killpg,
        ):
            self.assertFalse(sb._try_interrupt_to_idle("msg", 1))
            kill.assert_not_called()
            killpg.assert_not_called()
        sb._proc = None
        sb.cleanup()

    def test_timeout_recovery_preserves_or_kills_kernel(self):
        for recovered in (False, True):
            with self.subTest(recovered=recovered):
                sb = sandbox.StatefulSandbox("/unused")
                sb._client = MagicMock()
                with (
                    patch.object(sb, "_try_interrupt_to_idle", return_value=recovered) as interrupt,
                    patch.object(sb, "_kill_kernel_now", wraps=sb._kill_kernel_now) as kill,
                ):
                    output, success = sb.execute("while True: pass", timeout=0)
                self.assertFalse(success)
                self.assertIn("state preserved" if recovered else "Sandbox killed", output)
                interrupt.assert_called_once()
                self.assertEqual(kill.call_count, int(not recovered))
                sb.cleanup()

    def test_stream_keeps_exact_tail_across_chunk_boundaries(self):
        buffer = sandbox._BoundedStreamBuffer(3, 5)
        for chunk in ["abc", "1234", "56"]:
            buffer.append(chunk)
        self.assertEqual(buffer.value(), "abc\n...[1 chars dropped during execution]...\n23456")

    def test_stream_chunking_does_not_change_output(self):
        text = "abcdefghijklmnopqrstuvwxyz"
        outputs = []
        for size in [1, 2, 5, 26]:
            buffer = sandbox._BoundedStreamBuffer(4, 7)
            for offset in range(0, len(text), size):
                buffer.append(text[offset : offset + size])
            outputs.append(buffer.value())
        self.assertEqual(len(set(outputs)), 1)

    def test_unbounded_stream(self):
        buffer = sandbox._BoundedStreamBuffer(0, 0)
        buffer.append("abc")
        buffer.append("def")
        self.assertEqual(buffer.value(), "abcdef")

    def test_landlock_rights_follow_kernel_abi(self):
        for abi in [1, 2, 3, 4, 5]:
            with self.subTest(abi=abi):
                libc = MagicMock()
                masks = []

                def syscall(number, *args, abi=abi, masks=masks):
                    if number.value == 444:
                        if args[0] is None:
                            return abi
                        masks.append(args[0]._obj.handled_access_fs)
                        return 123
                    return 0

                libc.syscall.side_effect = syscall
                libc.prctl.return_value = 0
                with (
                    patch.object(sandbox.ctypes, "CDLL", return_value=libc),
                    patch.object(sandbox.os, "open", return_value=456),
                    patch.object(sandbox.os, "close"),
                ):
                    self.assertTrue(sandbox._apply_landlock([]))
                self.assertEqual(bool(masks[0] & (1 << 13)), abi >= 2)
                self.assertEqual(bool(masks[0] & (1 << 14)), abi >= 3)
                self.assertEqual(bool(masks[0] & (1 << 15)), abi >= 5)

    def test_no_new_privs_failure_closes_ruleset(self):
        libc = MagicMock()
        libc.syscall.side_effect = [4, 123, 0]
        libc.prctl.return_value = -1
        with (
            patch.object(sandbox.ctypes, "CDLL", return_value=libc),
            patch.object(sandbox.os, "open", return_value=456),
            patch.object(sandbox.os, "close") as close,
        ):
            self.assertFalse(sandbox._apply_landlock([]))
        self.assertEqual(close.call_count, 2)
        self.assertEqual(libc.syscall.call_count, 3)

    def _startup_failure(self, phase):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as temp:
            Path(temp, "kernel.json").touch()
            client = MagicMock()
            getattr(client, phase).side_effect = RuntimeError("startup failure")
            proc = MagicMock()
            proc.pid = 987654321
            proc.poll.return_value = 0
            executor = MagicMock()
            executor.submit.return_value.result.return_value = proc
            module = SimpleNamespace(BlockingKernelClient=MagicMock(return_value=client))
            sb = sandbox.StatefulSandbox(workspace)
            with (
                patch.dict("sys.modules", {"jupyter_client": module}),
                patch.object(sandbox.tempfile, "mkdtemp", return_value=temp),
                patch.object(sandbox, "bwrap_usable", return_value=False),
                patch.object(sandbox, "_landlock_abi_version", return_value=0),
                patch.object(sandbox, "_CGROUP_ENABLE", False),
                patch.object(sandbox, "_FORK_EXECUTOR", executor),
            ):
                with self.assertRaisesRegex(RuntimeError, "startup failure"):
                    sb.start()
            client.stop_channels.assert_called_once()
            client.context.destroy.assert_called_once_with(linger=0)
            self.assertIsNone(sb._client)
            self.assertNotIn(proc.pid, sandbox._SPAWNED_PIDS)

    def test_client_released_when_connection_loading_fails(self):
        self._startup_failure("load_connection_file")

    def test_client_released_when_ready_wait_fails(self):
        self._startup_failure("wait_for_ready")

    def test_landlock_install_failure_aborts_startup(self):
        with tempfile.TemporaryDirectory() as workspace:
            executor = MagicMock()

            def spawn(*args, **kwargs):
                kwargs["preexec_fn"]()
                self.fail("Kernel must not start without the selected Landlock rules")

            executor.submit.side_effect = spawn
            module = SimpleNamespace(BlockingKernelClient=MagicMock())
            sb = sandbox.StatefulSandbox(workspace, mem_limit_bytes=0)
            with (
                patch.dict("sys.modules", {"jupyter_client": module}),
                patch.object(sandbox, "bwrap_usable", return_value=False),
                patch.object(sandbox, "_landlock_abi_version", return_value=4),
                patch.object(sandbox, "_apply_landlock", return_value=False),
                patch.object(sandbox, "_set_pdeathsig"),
                patch.object(sandbox, "_CGROUP_ENABLE", False),
                patch.object(sandbox, "_FORK_EXECUTOR", executor),
            ):
                with self.assertRaisesRegex(RuntimeError, "Failed to apply Landlock"):
                    sb.start()
            self.assertIsNone(sb._tmpdir)
            self.assertIsNone(sb._proc)


class RolloutCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_cancellation_waits_for_cleanup_before_release(self):
        entered = threading.Event()
        resume = threading.Event()
        events = []

        def close():
            entered.set()
            if not resume.wait(5):
                raise RuntimeError("Cleanup was not resumed")
            events.append("kernel")

        with (
            patch.object(sandbox, "teardown_env", side_effect=lambda _: events.append("env")),
            patch.object(sandbox, "cleanup_env_dir", side_effect=lambda _: events.append("directory")),
            patch.object(sandbox, "release_rollout_slot", side_effect=lambda: events.append("slot")),
        ):
            task = asyncio.create_task(sandbox.cleanup_rollout(None, "/unused", SimpleNamespace(cleanup=close)))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertEqual(events, [])
            finally:
                resume.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(events, ["kernel", "env", "directory", "slot"])

    async def test_cancelled_preparation_removes_late_directory(self):
        entered = threading.Event()
        resume = threading.Event()
        events = []

        def prepare():
            entered.set()
            if not resume.wait(5):
                raise RuntimeError("Preparation was not resumed")
            events.append("prepared")
            return "/late/env"

        task = asyncio.create_task(
            sandbox.run_sandbox_work(
                asyncio.get_running_loop(),
                None,
                prepare,
                on_cancel=lambda path: events.append(path),
            )
        )
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 3))
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertEqual(events, [])
        finally:
            resume.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(events, ["prepared", "/late/env"])

    async def test_worker_failure_does_not_replace_cancellation(self):
        entered = threading.Event()
        resume = threading.Event()

        def work():
            entered.set()
            resume.wait(5)
            raise RuntimeError("late worker failure")

        task = asyncio.create_task(sandbox.run_sandbox_work(asyncio.get_running_loop(), None, work))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 3))
            task.cancel()
            await asyncio.sleep(0)
        finally:
            resume.set()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_cancel_cleanup_failure_preserves_cancellation(self):
        entered = threading.Event()
        resume = threading.Event()

        def work():
            entered.set()
            resume.wait(5)
            return "/late/env"

        cleanup = MagicMock(side_effect=OSError("cleanup failed"))
        task = asyncio.create_task(
            sandbox.run_sandbox_work(
                asyncio.get_running_loop(),
                None,
                work,
                on_cancel=cleanup,
            )
        )
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 3))
            task.cancel()
            await asyncio.sleep(0)
        finally:
            resume.set()
        with self.assertLogs(sandbox.logger, level="ERROR"):
            with self.assertRaises(asyncio.CancelledError):
                await task
        cleanup.assert_called_once_with("/late/env")

    async def test_failed_cleanup_waits_for_other_sandbox(self):
        entered = threading.Event()
        resume = threading.Event()
        events = []

        def close():
            entered.set()
            resume.wait(5)
            events.append("kernel")

        broken = SimpleNamespace(cleanup=MagicMock(side_effect=RuntimeError("stop failed")))
        with (
            patch.object(sandbox, "teardown_env"),
            patch.object(sandbox, "cleanup_env_dir", side_effect=lambda _: events.append("directory")),
            patch.object(sandbox, "release_rollout_slot", side_effect=lambda: events.append("slot")),
        ):
            task = asyncio.create_task(sandbox.cleanup_rollout(None, "/unused", broken, SimpleNamespace(cleanup=close)))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertEqual(events, [])
            finally:
                resume.set()
            await task
        self.assertEqual(events, ["kernel", "directory", "slot"])


class ResourceOwnerTests(unittest.TestCase):
    def test_process_disposal_failure_still_closes_remaining_handles(self):
        owner = sandbox._SandboxResources()
        owner.client = MagicMock()
        client = owner.client
        with tempfile.TemporaryDirectory() as root:
            owner.tmpdir = str(Path(root) / "kernel")
            Path(owner.tmpdir).mkdir()
            owner.cgroup_dir = str(Path(root) / "cgroup")
            Path(owner.cgroup_dir).mkdir()
            with patch.object(owner, "_stop_process", side_effect=OSError("wait failed")):
                with self.assertRaises(OSError):
                    owner.close()
            self.assertIsNone(owner.tmpdir)
            self.assertIsNone(owner.cgroup_dir)
            self.assertIsNone(owner.client)
            client.stop_channels.assert_called_once()
            client.context.destroy.assert_called_once_with(linger=0)

    def test_failed_stop_can_be_retried(self):
        sb = sandbox.StatefulSandbox("/unused")
        sb._proc = MagicMock(pid=987654321)
        sb._proc.poll.side_effect = OSError("poll failed")
        with self.assertRaises(OSError):
            sb.cleanup()
        self.assertFalse(sb._cleaned_up)
        self.assertIsNotNone(sb._proc)
        sb._proc.poll.side_effect = None
        sb._proc.poll.return_value = 0
        sb.cleanup()
        self.assertTrue(sb._cleaned_up)
        self.assertIsNone(sb._proc)


class IsolationBackendTests(unittest.TestCase):
    def test_bubblewrap_preferred_without_landlock_probe_or_application(self):
        with (
            patch.object(sandbox, "bwrap_usable", return_value=True),
            patch.object(sandbox, "bwrap_pid_ns_usable", return_value=True),
            patch.object(sandbox, "_BWRAP_BIN", "/usr/bin/bwrap"),
            patch.object(sandbox, "_landlock_abi_version") as abi,
            patch.object(sandbox, "_apply_landlock") as apply,
        ):
            backend = sandbox.select_isolation_backend(
                sandbox.IsolationConfig("/work", read_paths=("/env",), write_paths=("/connection",))
            )
            argv = backend.wrap_command(["python", "-V"])
            backend.apply_child_restrictions()
        self.assertEqual(backend.name, "bubblewrap")
        self.assertTrue(backend.capabilities.restricted_reads)
        self.assertTrue(backend.capabilities.restricted_writes)
        self.assertTrue(backend.capabilities.pid_namespace)
        self.assertFalse(backend.capabilities.network_namespace)
        self.assertLess(argv.index("--tmpfs"), argv.index("/env"))
        self.assertLess(argv.index("/env"), argv.index("/work"))
        self.assertLess(argv.index("/work"), argv.index("/connection"))
        self.assertEqual(argv[-2:], ["python", "-V"])
        abi.assert_not_called()
        apply.assert_not_called()

    def test_bubblewrap_devices_and_proc_overlay_readonly_root(self):
        with (
            patch.object(sandbox, "_BWRAP_READ_PATHS", ["/"]),
            patch.object(sandbox, "bwrap_pid_ns_usable", return_value=False),
        ):
            argv = sandbox._build_bwrap_argv("/work")
        root_bind = argv.index("--ro-bind-try")
        for option, path in (("--dev", "/dev"), ("--proc", "/proc")):
            index = argv.index(option)
            self.assertGreater(index, root_bind)
            self.assertEqual(argv[index + 1], path)

    def test_broad_bind_and_disabled_pid_namespace_report_actual_capabilities(self):
        for config in (
            sandbox.IsolationConfig("/work", read_paths=("/",)),
            sandbox.IsolationConfig("/"),
        ):
            with (
                patch.object(sandbox, "bwrap_usable", return_value=True),
                patch.object(sandbox, "bwrap_pid_ns_usable", return_value=False),
            ):
                backend = sandbox.select_isolation_backend(config)
            self.assertFalse(backend.capabilities.restricted_reads)
            self.assertFalse(backend.capabilities.pid_namespace)
            self.assertEqual(backend.capabilities.restricted_writes, config.workspace != "/")

    def test_landlock_fallback_policy_and_fail_closed_application(self):
        with (
            patch.object(sandbox, "bwrap_usable", return_value=False),
            patch.object(sandbox, "_landlock_abi_version", return_value=4),
        ):
            backend = sandbox.select_isolation_backend(
                sandbox.IsolationConfig("/work", read_paths=("/env",), write_paths=("/connection",))
            )
        self.assertEqual(backend.name, "landlock")
        self.assertEqual(backend.abi, 4)
        self.assertEqual(backend.capabilities, sandbox.IsolationCapabilities(restricted_writes=True))
        self.assertEqual(backend.wrap_command(["python"]), ["python"])
        with patch.object(sandbox, "_apply_landlock", return_value=True) as apply:
            backend.apply_child_restrictions()
        apply.assert_called_once_with(["/work", "/connection", "/tmp"])
        with patch.object(sandbox, "_apply_landlock", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "Failed to apply Landlock"):
                backend.apply_child_restrictions()

    def test_no_backend_and_explicit_terminal_policy(self):
        for allow_landlock in (False, True):
            with (
                patch.object(sandbox, "bwrap_usable", return_value=False),
                patch.object(sandbox, "_landlock_abi_version", return_value=0) as abi,
            ):
                backend = sandbox.select_isolation_backend(
                    sandbox.IsolationConfig("/work", allow_landlock=allow_landlock)
                )
            self.assertEqual(backend.name, "none")
            self.assertEqual(backend.capabilities, sandbox.IsolationCapabilities())
            self.assertEqual(backend.wrap_command(["bash"]), ["bash"])
            self.assertEqual(abi.call_count, int(allow_landlock))

    def test_kernel_preparation_failure_disposes_owned_directory(self):
        with tempfile.TemporaryDirectory() as workspace:
            sb = sandbox.StatefulSandbox(workspace)
            with (
                patch.dict("sys.modules", {"jupyter_client": SimpleNamespace(BlockingKernelClient=MagicMock())}),
                patch.object(sandbox, "select_isolation_backend", side_effect=RuntimeError("prepare failed")),
                patch.object(sandbox, "_FORK_EXECUTOR") as fork,
            ):
                with self.assertRaisesRegex(RuntimeError, "prepare failed"):
                    sb.start()
            self.assertIsNone(sb._tmpdir)
            self.assertFalse(sb.isolation_active)
            fork.submit.assert_not_called()

    def test_terminal_preparation_failure_allocates_no_cgroup_or_process(self):
        spec = importlib.util.spec_from_file_location("terminal_failure_test", MODULE_PATH.with_name("terminal.py"))
        terminal = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {"verl.experimental.agent_loop.progagent_sandbox": sandbox}):
            spec.loader.exec_module(terminal)
        with (
            tempfile.TemporaryDirectory() as workspace,
            patch.object(terminal, "select_isolation_backend", side_effect=RuntimeError("prepare failed")),
            patch.object(terminal, "_create_cgroup") as create,
            patch.object(terminal.subprocess, "Popen") as spawn,
        ):
            with self.assertRaisesRegex(RuntimeError, "prepare failed"):
                terminal.TerminalExecutor(workspace).execute("true")
        create.assert_not_called()
        spawn.assert_not_called()

    def test_terminal_uses_shared_interface_without_landlock_fallback(self):
        spec = importlib.util.spec_from_file_location("terminal_under_test", MODULE_PATH.with_name("terminal.py"))
        terminal = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {"verl.experimental.agent_loop.progagent_sandbox": sandbox}):
            spec.loader.exec_module(terminal)
        backend = MagicMock()
        backend.wrap_command.side_effect = lambda command: command
        proc = MagicMock()
        # A failed bubblewrap startup is only a selected policy, never reported active.
        proc.returncode = 1
        proc.stdout.read.return_value = ""
        proc.stderr.read.return_value = ""

        def spawn(*args, **kwargs):
            kwargs["preexec_fn"]()
            return proc

        with (
            tempfile.TemporaryDirectory() as workspace,
            patch.object(terminal, "select_isolation_backend", return_value=backend) as select,
            patch.object(terminal, "_CGROUP_ENABLE", False),
            patch.object(terminal.subprocess, "Popen", side_effect=spawn),
        ):
            executor = terminal.TerminalExecutor(workspace, mem_limit_bytes=0)
            self.assertIn("exit code: 1", executor.execute("true"))
            self.assertFalse(select.call_args.args[0].allow_landlock)
            self.assertIs(executor.isolation_backend, backend)
        backend.wrap_command.assert_called_once_with(["/bin/bash", "-c", "true"])
        backend.apply_child_restrictions.assert_called_once()
        backend.log_policy.assert_called_once_with("terminal", False)


if __name__ == "__main__":
    unittest.main()
