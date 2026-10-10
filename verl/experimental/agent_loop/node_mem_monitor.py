"""Per-node memory watchdog for diagnosing OOM-killed Ray workers.

One AgentLoopWorker is scheduled per node (round-robin, see
AgentLoopManager._init_agent_loop_workers), so starting this monitor from
AgentLoopWorker.__init__ gives one memory-trend log line per node per
interval. Output goes through print() so Ray forwards it to the driver
console regardless of logger levels — the same channel the rollout logs use.

Log format (one line, grep for "[node-mem]"):

    [node-mem] host=<hostname> avail=12.3/128.0GiB cgroup=110.2/120.0GiB \
        self_rss=4.2GiB top: python(1234)=38.2GiB ray::WorkerDict(555)=21.0GiB ...

A "[node-mem][LOW]" prefix is used when available memory (host or cgroup,
whichever is tighter) drops below 10% — the last few of these lines before a
crash identify which process was ballooning when the OOM killer fired.

Env knobs:
    VERL_NODE_MEM_MONITOR=0             disable entirely
    VERL_NODE_MEM_MONITOR_INTERVAL_S    seconds between samples (default 60)
"""

import os
import socket
import threading
import time

_GIB = 1024**3

_started_lock = threading.Lock()
_started = False


def _read_meminfo() -> tuple[int, int]:
    """Return (available_bytes, total_bytes) from /proc/meminfo; (-1, -1) on failure."""
    avail = total = -1
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) * 1024
                elif line.startswith("MemTotal:"):
                    total = int(line.split()[1]) * 1024
                if avail >= 0 and total >= 0:
                    break
    except OSError:
        pass
    return avail, total


def _read_cgroup_mem() -> tuple[int, int]:
    """Return (current_bytes, limit_bytes) of this process's memory cgroup.

    Kubernetes pods are killed on the POD cgroup limit, which can be far below
    host MemTotal, so this is often the number that actually matters. Returns
    (-1, -1) when unavailable or unlimited.
    """
    # cgroup v2
    try:
        with open("/sys/fs/cgroup/memory.current") as f:
            current = int(f.read())
        with open("/sys/fs/cgroup/memory.max") as f:
            raw = f.read().strip()
        limit = -1 if raw == "max" else int(raw)
        return current, limit
    except (OSError, ValueError):
        pass
    # cgroup v1
    try:
        with open("/sys/fs/cgroup/memory/memory.usage_in_bytes") as f:
            current = int(f.read())
        with open("/sys/fs/cgroup/memory/memory.limit_in_bytes") as f:
            limit = int(f.read())
        if limit >= 2**60:  # effectively unlimited
            limit = -1
        return current, limit
    except (OSError, ValueError):
        pass
    return -1, -1


def _read_cgroup_peak() -> int:
    """High-water mark of this cgroup's memory (bytes), or -1. Catches spikes
    that rise and get OOM-killed between two monitor samples."""
    for path in ("/sys/fs/cgroup/memory.peak", "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"):
        try:
            with open(path) as f:
                return int(f.read())
        except (OSError, ValueError):
            continue
    return -1


def _read_cgroup_oom_kills() -> int:
    """Cumulative count of kernel OOM kills inside this cgroup, or -1.
    Discriminates 'the pod OOM-killed something' from 'an external agent
    SIGKILLed our processes' when Ray workers die without memory pressure."""
    # cgroup v2
    try:
        with open("/sys/fs/cgroup/memory.events") as f:
            for line in f:
                if line.startswith("oom_kill "):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    # cgroup v1
    try:
        with open("/sys/fs/cgroup/memory/memory.oom_control") as f:
            for line in f:
                if line.startswith("oom_kill "):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return -1


def _read_rss(pid: int | str = "self") -> int:
    """RSS in bytes of `pid`, or -1."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return -1


def _top_rss_procs(n: int = 3) -> list[tuple[str, int, int]]:
    """Top-n processes by RSS as (comm, pid, rss_bytes)."""
    procs = []
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            rss = _read_rss(entry)
            if rss <= 0:
                continue
            try:
                with open(f"/proc/{entry}/comm") as f:
                    comm = f.read().strip()
            except OSError:
                comm = "?"
            procs.append((comm, int(entry), rss))
    except OSError:
        pass
    procs.sort(key=lambda x: -x[2])
    return procs[:n]


def _fmt(nbytes: int) -> str:
    return "?" if nbytes < 0 else f"{nbytes / _GIB:.1f}"


def _monitor_loop(interval_s: float) -> None:
    host = socket.gethostname()
    last_oom_kills = _read_cgroup_oom_kills()
    while True:
        try:
            avail, total = _read_meminfo()
            cg_cur, cg_max = _read_cgroup_mem()
            cg_peak = _read_cgroup_peak()
            oom_kills = _read_cgroup_oom_kills()
            self_rss = _read_rss()
            top = _top_rss_procs()

            low = False
            if 0 <= avail and total > 0 and avail < 0.10 * total:
                low = True
            if cg_max > 0 and cg_cur >= 0 and (cg_max - cg_cur) < 0.10 * cg_max:
                low = True

            if oom_kills >= 0 and last_oom_kills >= 0 and oom_kills > last_oom_kills:
                print(
                    f"[node-mem][OOM-KILL] host={host} kernel oom_kill count "
                    f"{last_oom_kills} -> {oom_kills} since last sample "
                    f"(peak={_fmt(cg_peak)}GiB limit={_fmt(cg_max)}GiB)",
                    flush=True,
                )
            last_oom_kills = oom_kills

            cg_str = f" cgroup={_fmt(cg_cur)}/{_fmt(cg_max)}GiB" if cg_cur >= 0 else ""
            peak_str = f" peak={_fmt(cg_peak)}GiB" if cg_peak >= 0 else ""
            oom_str = f" oom_kills={oom_kills}" if oom_kills > 0 else ""
            top_str = " ".join(f"{c}({p})={_fmt(r)}GiB" for c, p, r in top)
            print(
                f"[node-mem]{'[LOW]' if low else ''} host={host} "
                f"avail={_fmt(avail)}/{_fmt(total)}GiB{cg_str}{peak_str}{oom_str} "
                f"self_rss={_fmt(self_rss)}GiB top: {top_str}",
                flush=True,
            )
        except Exception:
            pass  # a diagnostics thread must never take the worker down
        time.sleep(interval_s)


def start_node_mem_monitor() -> None:
    """Start the per-process memory watchdog thread (idempotent, daemon)."""
    global _started
    if (os.getenv("VERL_NODE_MEM_MONITOR") or "1") == "0":
        return
    with _started_lock:
        if _started:
            return
        _started = True
    interval_s = float(os.getenv("VERL_NODE_MEM_MONITOR_INTERVAL_S") or "60")
    threading.Thread(target=_monitor_loop, args=(interval_s,), daemon=True).start()
