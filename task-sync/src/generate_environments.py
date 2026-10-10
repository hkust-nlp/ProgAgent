"""
ClaudeAgent runner using ClaudeSDKClient for multi-turn conversations with concurrency.
"""

import asyncio
import json
import sys
import textwrap
from pathlib import Path

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, HookMatcher

from path_guard import make_path_guard_hook


_ALLOWED_TOOLS = [
    "Read", "Write", "Edit",
    "Bash",
    "Glob", "Grep",
    "BashOutput", "KillBash", "TodoWrite",
]


def _make_options(
    cwd: Path,
    model: str,
    permission_mode: str,
    effort: str | None = None,
) -> ClaudeAgentOptions:
    guard = make_path_guard_hook(cwd)
    return ClaudeAgentOptions(
        cwd=str(cwd),
        setting_sources=["project"],
        permission_mode=permission_mode,
        model=model,
        effort=effort,
        allowed_tools=_ALLOWED_TOOLS,
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Write|Edit|NotebookEdit|Bash", hooks=[guard]),
            ],
        },
        stderr=lambda line: print(f"\033[90m[stderr] {line}\033[0m", file=sys.stderr),
    )


def _print_result(message, label: str = "") -> None:
    duration_sec = getattr(message, "duration_ms", 0) / 1000
    turns = getattr(message, "num_turns", 0)
    cost = getattr(message, "total_cost_usd", 0.0) or 0.0
    result_text = getattr(message, "result", "") or ""

    sep = "─" * 60
    prefix = f" [{label}]" if label else ""
    print(f"\n\033[1;36m{sep}\033[0m")
    print(f"\033[1;32m✓ Agent 完成{prefix}\033[0m  "
          f"\033[90m耗时 {duration_sec:.1f}s · {turns} turns · ${cost:.4f}\033[0m")
    print(f"\033[1;36m{sep}\033[0m")

    for line in result_text.splitlines():
        if line.strip():
            wrapped = textwrap.wrap(line, width=80, subsequent_indent="  ")
            print("\n".join(f"  {l}" for l in wrapped))
        else:
            print()

    print(f"\033[1;36m{sep}\033[0m\n")


async def run_agent(
    prompts: list[str],
    cwd: str | Path,
    model: str = "sonnet",
    permission_mode: str = "acceptEdits",
    effort: str | None = None,
) -> dict:
    """
    Run a multi-turn Claude Agent.

    Args:
        prompts: Ordered list of prompts sent in the same conversation session.
        cwd: Working directory for the agent (CLAUDE.md loaded from here).
        model: Claude model to use.
        permission_mode: Permission mode for file operations.
        effort: Thinking effort (low/medium/high/max); None leaves it disabled.

    Returns:
        dict with success, duration_sec, turns, cost_usd, error.
    """
    cwd = Path(cwd).resolve()
    options = _make_options(cwd, model, permission_mode, effort=effort)

    result = {
        "success": False,
        "duration_sec": 0.0,
        "turns": 0,
        "cost_usd": 0.0,
        "error": None,
    }

    try:
        async with ClaudeSDKClient(options) as client:
            for turn_idx, prompt in enumerate(prompts):
                is_last = (turn_idx == len(prompts) - 1)
                await client.query(prompt)

                async for message in client.receive_response():
                    if not hasattr(message, "subtype"):
                        continue
                    if message.subtype == "success":
                        result["duration_sec"] += getattr(message, "duration_ms", 0) / 1000
                        result["turns"] += getattr(message, "num_turns", 0)
                        result["cost_usd"] += getattr(message, "total_cost_usd", 0.0) or 0.0
                        if is_last:
                            result["success"] = True
                            _print_result(message)
                    elif message.subtype == "error":
                        result["error"] = getattr(message, "result", "Unknown error")
                        return result
    except Exception as e:
        result["error"] = str(e)

    return result


def _merge_results(base: dict, extra: dict) -> None:
    """Merge stats from extra into base result."""
    base["duration_sec"] += extra["duration_sec"]
    base["turns"] += extra["turns"]
    base["cost_usd"] += extra["cost_usd"]
    if extra["error"]:
        base["error"] = extra["error"]
        base["success"] = False


def _is_task_complete(task_dir: Path) -> bool:
    """A topic is complete only when all four versions + README.md exist with the expected files."""
    if not (task_dir / "README.md").exists():
        return False
    for v in ("v0", "v1", "v2", "v3"):
        vd = task_dir / v
        if not vd.is_dir():
            return False
        for fname in ("data.py", "env.py", "prompt.md"):
            if not (vd / fname).exists():
                return False
    return True


async def _run_topic(
    entry: dict,
    gen_templates: list[str],
    output_dir: Path,
    gen_model: str,
    gen_effort: str | None,
    semaphore: asyncio.Semaphore,
    idx: int,
    total: int,
    harness_templates: list[str] | None = None,
    harness_model: str | None = None,
    harness_effort: str | None = None,
) -> dict:
    topic = entry["TOPIC"]
    task_folder = entry["TASK_FOLDER"]
    task_dir = (output_dir / task_folder).resolve()

    if _is_task_complete(task_dir):
        print(f"\033[90m[{idx+1}/{total}] 跳过 {task_folder}（已完整）\033[0m")
        return {
            "success": True,
            "duration_sec": 0.0,
            "turns": 0,
            "cost_usd": 0.0,
            "error": None,
            "topic": topic,
            "task_folder": task_folder,
            "skipped": True,
        }

    async with semaphore:
        print(f"\n\033[1;35m[{idx+1}/{total}] {task_folder}\033[0m  {topic[:60]}…")

        gen_prompts = [t.replace("{TOPIC}", topic) for t in gen_templates]
        task_dir.mkdir(parents=True, exist_ok=True)

        result = await run_agent(
            gen_prompts, cwd=task_dir, model=gen_model, effort=gen_effort,
        )
        result["topic"] = topic
        result["task_folder"] = task_folder
        result["skipped"] = False

        # Harness runs in a fresh session (independent context, possibly different model)
        if harness_templates and result["success"]:
            h_model = harness_model or gen_model
            h_effort = harness_effort if harness_effort is not None else gen_effort
            print(f"\033[1;33m  ↻ harness (model={h_model}, effort={h_effort}) {task_folder}\033[0m")
            harness_prompts = [t.replace("{TOPIC}", topic) for t in harness_templates]
            harness_result = await run_agent(
                harness_prompts, cwd=task_dir, model=h_model, effort=h_effort,
            )
            _merge_results(result, harness_result)

        status = "\033[1;32m✓\033[0m" if result["success"] else "\033[1;31m✗\033[0m"
        print(f"{status}  {task_folder}  耗时 {result['duration_sec']:.1f}s · "
              f"{result['turns']} turns · ${result['cost_usd']:.4f}")
        if result["error"]:
            print(f"\033[1;31m  错误: {result['error']}\033[0m")

        return result


async def batch_run_async(
    topics_path: str | Path,
    gen_md_paths: list[str | Path],
    output_dir: str | Path,
    gen_model: str = "sonnet",
    gen_effort: str | None = None,
    count: int | None = None,
    max_concurrent: int = 4,
    harness_md_paths: list[str | Path] | None = None,
    harness_model: str | None = None,
    harness_effort: str | None = None,
) -> list[dict]:
    """
    Batch run agents for topics in order with concurrency control.

    Args:
        topics_path: Path to topics.json.
        gen_md_paths: Ordered list of gen-stage template .md files, each sent as one turn.
        output_dir: Base directory for task folders.
        gen_model: Claude model for gen stage.
        gen_effort: Thinking effort for gen stage.
        count: Number of topics to process from the beginning (None = all).
        max_concurrent: Maximum number of concurrent agents.
        harness_md_paths: Optional harness template files, run in a fresh session after gen.
        harness_model: Model for harness stage. Defaults to gen_model.
        harness_effort: Effort for harness stage. Defaults to gen_effort.
    """
    topics_path = Path(topics_path)
    output_dir = Path(output_dir)

    with open(topics_path, "r", encoding="utf-8") as f:
        topics = json.load(f)

    gen_templates = []
    for p in gen_md_paths:
        with open(p, "r", encoding="utf-8") as f:
            gen_templates.append(f.read())

    harness_templates = None
    if harness_md_paths:
        harness_templates = []
        for p in harness_md_paths:
            with open(p, "r", encoding="utf-8") as f:
                harness_templates.append(f.read())

    if count is not None:
        topics = topics[:count]

    total = len(topics)
    semaphore = asyncio.Semaphore(max_concurrent)

    tasks = [
        _run_topic(
            entry, gen_templates, output_dir, gen_model, gen_effort,
            semaphore, i, total,
            harness_templates=harness_templates,
            harness_model=harness_model,
            harness_effort=harness_effort,
        )
        for i, entry in enumerate(topics)
    ]
    results = await asyncio.gather(*tasks)

    sep = "─" * 60
    skipped_count = sum(1 for r in results if r.get("skipped"))
    success_count = sum(1 for r in results if r["success"])
    total_cost = sum(r["cost_usd"] for r in results)
    print(f"\n\033[1;36m{sep}\033[0m")
    print(f"完成 {success_count}/{total}  跳过 {skipped_count}  总花费 ${total_cost:.4f}")
    print(f"\033[1;36m{sep}\033[0m\n")

    return list(results)


def batch_run(
    topics_path: str | Path,
    gen_md_paths: list[str | Path],
    output_dir: str | Path,
    gen_model: str = "sonnet",
    gen_effort: str | None = None,
    count: int | None = None,
    max_concurrent: int = 4,
    harness_md_paths: list[str | Path] | None = None,
    harness_model: str | None = None,
    harness_effort: str | None = None,
) -> list[dict]:
    """Synchronous wrapper around batch_run_async."""
    return asyncio.run(
        batch_run_async(
            topics_path=topics_path,
            gen_md_paths=gen_md_paths,
            output_dir=output_dir,
            gen_model=gen_model,
            gen_effort=gen_effort,
            count=count,
            max_concurrent=max_concurrent,
            harness_md_paths=harness_md_paths,
            harness_model=harness_model,
            harness_effort=harness_effort,
        )
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run agents from generate.md template and topics.json"
    )
    parser.add_argument("--topics", default="topics/topics.json", help="Path to topic definitions")
    parser.add_argument("--gen", nargs="+", default=["prompts/generate.md"],
                        help="One or more gen-stage template .md files sent as sequential turns")
    parser.add_argument("--harness", nargs="*", default=None,
                        help="Harness template .md files run in a fresh session after gen")
    parser.add_argument("--output-dir", default="environments/generated", help="Output directory containing task folders directly")
    parser.add_argument("--gen-model", default="opus", help="Gen-stage Claude model (default: opus)")
    parser.add_argument("--gen-effort", default="medium",
                        choices=["low", "medium", "high", "max"],
                        help="Gen-stage thinking effort (default: high)")
    parser.add_argument("--harness-model", default="sonnet",
                        help="Harness-stage model (default: sonnet)")
    parser.add_argument("--harness-effort", default="high",
                        choices=["low", "medium", "high", "max"],
                        help="Harness-stage thinking effort (default: high)")
    parser.add_argument("--count", type=int, help="Number of topics to process from the beginning")
    parser.add_argument("--max-concurrent", type=int, default=10, help="Max concurrent agents")
    args = parser.parse_args()

    batch_run(
        topics_path=args.topics,
        gen_md_paths=args.gen,
        output_dir=args.output_dir,
        gen_model=args.gen_model,
        gen_effort=args.gen_effort,
        count=args.count,
        max_concurrent=args.max_concurrent,
        harness_md_paths=args.harness,
        harness_model=args.harness_model,
        harness_effort=args.harness_effort,
    )
