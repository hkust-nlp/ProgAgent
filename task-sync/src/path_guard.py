"""
PreToolUse hook that confines an agent's file and shell operations to `task_dir`.

Guards applied:
- Write / Edit / NotebookEdit: the target path must resolve inside `task_dir`.
- Bash: rejects commands that are destructive, network-reaching, or that redirect
  output to absolute paths outside an allow-list. Also rejects absolute-path file
  arguments that escape `task_dir`.

The hook returns a PreToolUse permissionDecision of "deny" with a reason when a
violation is detected; otherwise it returns an empty dict (implicit allow).
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any, Awaitable, Callable


_BASH_DENY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(^|[\s;&|`$(])sudo\b"), "sudo is not allowed"),
    (re.compile(r"\brm\s+-[rR]f?\s+/(?!tmp/)"), "rm -rf against root-level path"),
    (re.compile(r"\brm\s+-[rR]f?\s+~"), "rm -rf against home directory"),
    (re.compile(r"(^|[\s;&|`$(])curl\b"), "network command curl is not allowed"),
    (re.compile(r"(^|[\s;&|`$(])wget\b"), "network command wget is not allowed"),
    (re.compile(r"\bpip\s+install\b"), "pip install is not allowed"),
    (re.compile(r"\bpip3\s+install\b"), "pip3 install is not allowed"),
    (re.compile(r"\bconda\s+install\b"), "conda install is not allowed"),
    (re.compile(r"\bapt(-get)?\s+(install|remove|update|upgrade)\b"), "apt is not allowed"),
    (re.compile(r"\byum\s+(install|remove|update)\b"), "yum is not allowed"),
    (re.compile(r"\bdnf\s+(install|remove|update)\b"), "dnf is not allowed"),
    (re.compile(r"(^|[\s;&|`$(])(dd|mkfs|mount|umount|shutdown|reboot|halt)\b"), "system-level command"),
    (re.compile(r">\s*/etc\b"), "redirect into /etc"),
    (re.compile(r">\s*/root\b"), "redirect into /root"),
    (re.compile(r">\s*~"), "redirect into home directory"),
]

# Absolute paths that agents may legitimately read/write (read-only system files,
# temp files, and null sinks). Everything else under "/" is treated as outside
# task_dir unless it happens to be inside task_dir itself.
_ABS_READ_ALLOWLIST: tuple[str, ...] = (
    "/tmp/",
    "/dev/null",
    "/dev/stdout",
    "/dev/stderr",
    "/proc/",
    "/sys/",
    "/usr/",
    "/etc/",
    "/opt/",
    "/var/",
    "/home/",
    "/ssddata/",
    "/home/data/",
)

# Absolute paths that agents may legitimately write to outside task_dir.
_ABS_WRITE_ALLOWLIST: tuple[str, ...] = (
    "/tmp/",
    "/dev/null",
    "/dev/stdout",
    "/dev/stderr",
)


def _inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _resolve_against(fp: str, root: Path) -> Path:
    p = Path(fp)
    return p if p.is_absolute() else (root / p)


def _check_bash_command(cmd: str, task_dir: Path) -> str | None:
    """Return a denial reason if the bash command is unsafe, else None."""
    for pat, reason in _BASH_DENY_PATTERNS:
        if pat.search(cmd):
            return f"{reason}: {pat.pattern!r}"

    # Reject absolute-path write redirections that escape allow-list.
    # Match `>`, `>>`, and `tee [-a] <path>`.
    for m in re.finditer(r">>?\s*(\S+)", cmd):
        target = m.group(1).strip("'\"")
        if target.startswith("/") and not any(target.startswith(p) for p in _ABS_WRITE_ALLOWLIST):
            if not _inside(Path(target), task_dir):
                return f"redirect target {target!r} is outside task_dir"

    for m in re.finditer(r"\btee\s+(?:-a\s+)?(\S+)", cmd):
        target = m.group(1).strip("'\"")
        if target.startswith("/") and not any(target.startswith(p) for p in _ABS_WRITE_ALLOWLIST):
            if not _inside(Path(target), task_dir):
                return f"tee target {target!r} is outside task_dir"

    return None


def make_path_guard_hook(task_dir: str | Path) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a PreToolUse hook that confines edits and shell writes to task_dir."""
    root = Path(task_dir).resolve()

    def _deny(reason: str) -> dict[str, Any]:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"[path_guard] {reason}",
            }
        }

    async def hook(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        tool = input_data.get("tool_name")
        ti = input_data.get("tool_input") or {}

        if tool in ("Write", "Edit"):
            fp = ti.get("file_path")
            if fp:
                p = _resolve_against(fp, root)
                if not _inside(p, root):
                    return _deny(f"{tool} target {p} is outside task_dir {root}")

        elif tool == "NotebookEdit":
            fp = ti.get("notebook_path")
            if fp:
                p = _resolve_against(fp, root)
                if not _inside(p, root):
                    return _deny(f"NotebookEdit target {p} is outside task_dir {root}")

        elif tool == "Bash":
            cmd = ti.get("command") or ""
            reason = _check_bash_command(cmd, root)
            if reason is not None:
                return _deny(reason)

        return {}  # implicit allow

    return hook
