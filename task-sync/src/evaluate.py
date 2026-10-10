"""评测脚本：支持 OpenAI 兼容接口和 Anthropic API。"""

import gc
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime

import httpx
from openai import OpenAI

from sandbox import StatefulSandbox, TerminalError, TerminalExecutor, kill_all_kernels


PRESETS = {
    "kimi": {
        "client": "openai",
        "model": "kimi-k2.6",
        "api_key": os.environ.get("KIMI_API_KEY", ""),
        "base_url": "https://api.moonshot.cn/v1",
    },
    "local": {
        "client": "openai",
        "model": "Qwen3-Coder-30B-A3B-Instruct",
        "api_key": "EMPTY",
        "base_url": "http://localhost:18025/v1",
        "timeout": 300,
        "minimal_params": True,
        "no_proxy": True,
    },
    "claude": {
        "client": "anthropic",
        "model": "claude-sonnet-4-6",
        "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    },
    "gpt": {
        "client": "openai",
        "model": "gpt-5.2-2025-12-11",
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "base_url": "http://maas.byteintl.net/gateway/v1",
    },
    "deepseek": {
        "client": "openai",
        "model": "deepseek-reasoner",
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "base_url": "https://api.deepseek.com/v1",
        "timeout": 600,
    },
}

MAX_TURNS = 40
OUTPUT_DIR = "eval_results"
_ENV_FILES = ["data.py", "env.py", "prompt.md"]

SYSTEM_PROMPT = (
    "You are a helpful assistant. Use the provided tools to complete the task. "
    "When you have finished the task, call the 'claim_done' tool to submit your result."
)

SYSTEM_PROMPT_PTC = (
    "You are a helpful assistant. Complete the task using the provided tools.\n\n"
    "Tools you may call directly:\n"
    "- `programmatic_tool_call` — Python sandbox; the only way to invoke env tools.\n"
    "- `terminal` — shell in the workspace directory.\n"
    "- `claim_done` — submit your final answer when the task is complete."
)

PTC_TOOL_DESCRIPTION_MINIMAL = 'Run Python that calls the tools listed above as `tools["tool_name"](*args, **kwargs)`. State (variables, imports) persists across calls; use print() to see output.'

PTC_TOOL_DESCRIPTION_RICH = (
    'Run Python that calls the tools listed above as `tools["tool_name"](*args, **kwargs)`. State (variables, imports) persists across calls. Use print() to see output.\n'
    "USE WHEN: loops, conditionals, error handling, or chaining multiple tool calls with intermediate processing.\n\n"
    "Notes:\n"
    "- Code runs in the workspace directory and file writes are restricted to it, don't write to `/tmp`; always use absolute paths for file writes; os, json, csv, sys are pre-imported.\n"
    "- Tools return native Python values; the type and structure vary by tool (e.g. dict, list, or str). Always print and inspect the first result before processing many items; do not assume a result is a list and loop over it.\n"
    "- Very large printed output is truncated; print summaries rather than large raw data.\n"
    "- Tools may raise an exception; wrap calls in try/except to handle failures.\n"
    "Usage examples:\n\n"
    "Batch + conditional workflow:\n"
    "```python\n"
    "print(type(tools[\"get_info\"](id='A001')))  # inspect return type first, then loop\n"
    "results = []\n"
    "for item in ['A001', 'A002', 'A003']:\n"
    "    info = tools[\"get_info\"](id=item)\n"
    "    if info.get('status') == 'active': # info is a dict, confirmed above\n"
    "        results.append(tools[\"get_details\"](id=item))\n"
    "    else:\n"
    "        print(f'Skipping {item}')\n"
    "    print(f'Processed {item}')\n"
    "print('Collected', len(results))\n"
    "```\n\n"
    "Error handling:\n"
    "```python\n"
    "ok, failed = [], []\n"
    "for item_id in ['A001', 'A002', 'A003']:\n"
    "    try:\n"
    "        r = tools[\"get_info\"](id=item_id)\n"
    "        ok.append(r)\n"
    "    except Exception as e:\n"
    "        failed.append((item_id, str(e)))\n"
    "    print(f'{len(ok)} ok, {len(failed)} failed')\n"
    "print('Failed:', failed[:3] if failed else 'none')\n"
    "```"
)

PTC_DESCRIPTIONS = {
    "minimal": PTC_TOOL_DESCRIPTION_MINIMAL,
    "rich": PTC_TOOL_DESCRIPTION_RICH,
}

# Same as RICH, but the opening line emphasizes PTC is the ONLY way to invoke env
# tools (used by --mode ptc). Body is reused from RICH so the two stay in sync.
PTC_TOOL_DESCRIPTION_PTC = (
    'Run Python that calls the tools listed above as `tools["tool_name"](*args, **kwargs)`. '
    "**This is the ONLY way to invoke env tools** — they cannot be called as standalone tool "
    "calls, so every env tool must go through this sandbox. "
    "State (variables, imports) persists across calls. Use print() to see output.\n"
    + PTC_TOOL_DESCRIPTION_RICH.split("\n", 1)[1]
)


@contextmanager
def prepare_eval_env(source_path: str):
    tmp = tempfile.mkdtemp(prefix="eval_env_")
    try:
        for fname in _ENV_FILES:
            src = os.path.join(source_path, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(tmp, fname))
        r = subprocess.run(
            [sys.executable, "data.py", "--db_path", "data.db", "--workspace", "workspace"],
            cwd=tmp, capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            raise RuntimeError(f"data.py 失败:\n{r.stderr}")
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"[eval] 已清理: {tmp}")


def _import_task_env(env_dir: str):
    import importlib.util
    if env_dir not in sys.path:
        sys.path.insert(0, env_dir)
    spec = importlib.util.spec_from_file_location("env", os.path.join(env_dir, "env.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Task_Env


def _teardown_task_env(env) -> None:
    """Break the Task_Env reference cycle so it frees by refcounting instead of
    waiting for a cyclic GC pass.

    Every generated Task_Env stores bound methods of *itself* in ``self.tools``
    (a reference cycle), and each bound method's ``__func__.__globals__`` pins
    the entire exec'd env module namespace (pandas/sqlite data loaded at import
    time). Across a long eval batch — ``k`` runs x many envs — these accumulate
    in the parent process until a cyclic GC pass and can slowly OOM the node.
    Mirrors the training-side fix (verl ``progagent_sandbox.teardown_env``).

    None-safe and idempotent.
    """
    if env is None:
        return
    # Close any resource the env exposes (e.g. a persistent sqlite handle).
    for closer in ("close", "cleanup"):
        fn = getattr(env, closer, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
    # Clear the tools dict -- this is the bound-method cycle that pins the module.
    tools = getattr(env, "tools", None)
    if isinstance(tools, dict):
        tools.clear()
    # Null out tools + common handle attributes so nothing keeps the env alive.
    for attr in ("tools", "conn", "_conn", "db", "_db", "connection"):
        if hasattr(env, attr):
            try:
                setattr(env, attr, None)
            except Exception:
                pass


def _drop_sys_path(env_dir: str) -> None:
    """Remove the entry _import_task_env inserted at sys.path[0]. The temp dir
    is rmtree'd by prepare_eval_env, so leaving it on sys.path both leaks
    (one stale entry per run) and risks stale 'env' import resolution."""
    while env_dir in sys.path:
        sys.path.remove(env_dir)


def _json_default(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return str(obj)


def execute_tool(env, name: str, args: dict) -> str:
    if name not in env.tools:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return json.dumps(env.tools[name](**args), ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _build_tools(env, workspace=None, mode: str = "hybrid", ptc_desc: str = "rich") -> list:
    """按 dtc / hybrid / ptc 模式构建工具列表。

    mode="ptc": 不提供 execute_python，programmatic_tool_call 成为调用 env 工具的唯一入口
    （env 工具 schema 仍列出供模型阅读参数，但只能经 tools["name"](**kwargs) 调用）。
    """
    if mode not in {"dtc", "hybrid", "ptc"}:
        raise ValueError("mode must be dtc, hybrid, or ptc")
    tools = env.get_assistant_tools()
    if mode != "ptc":
        exec_py_desc = (
            "Execute Python 3 code in a stateful session. "
            "os, json, csv, sys are pre-imported. Use print() to return results. "
            "State (variables, imports) persists across calls. "
            "Use relative file paths (e.g., 'data.csv')."
        )
        if mode != "dtc":
            exec_py_desc += (
                " This session is a separate interpreter from programmatic_tool_call; "
                "variables are not shared between the two."
            )
        tools.append({
            "type": "function",
            "function": {
                "name": "execute_python",
                "description": exec_py_desc,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python 3 code to execute.",
                        }
                    },
                    "required": ["code"],
                },
            },
        })
    ptc_tool = {
        "type": "function",
        "function": {
            "name": "programmatic_tool_call",
            "description": PTC_TOOL_DESCRIPTION_PTC if mode == "ptc" else PTC_DESCRIPTIONS[ptc_desc],
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code. Use tools[\"func_name\"](*args, **kwargs) to call env tools.",
                    }
                },
                "required": ["code"],
            },
        },
    }
    if mode != "dtc":
        tools.append(ptc_tool)
    tools.append({"type": "function", "function": {
        "name": "terminal",
        "description": "Execute a shell command in the workspace directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute (e.g., \"ls -la\", \"grep -c foo data.csv\").",
                }
            },
            "required": ["command"],
        },
    }})
    tools.append({"type": "function", "function": {
        "name": "claim_done",
        "description": (
            "Call when tasks are complete to submit your final answer. "
            "You MUST provide the 'action' parameter containing your complete final response."
        ),
        "parameters": {"type": "object",
                       "properties": {"action": {
                           "type": "string",
                           "description": "Your final response.",
                       }},
                       "required": ["action"]},
    }})
    return tools


def _is_context_overflow(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "maximum context length" in msg or "context_length_exceeded" in msg


def _run_openai(cfg: dict, env, task_prompt: str, sandbox: StatefulSandbox, temperature: float = 1.0, terminal_executor: TerminalExecutor = None, max_total_tokens: int = 0, ptc_sandbox: StatefulSandbox = None, mode: str = "hybrid", ptc_desc: str = "rich"):
    timeout = float(cfg.get("timeout", 600))
    http_client = httpx.Client(proxy=None, timeout=timeout) if cfg.get("no_proxy") else None
    client = OpenAI(
        api_key=cfg["api_key"], base_url=cfg["base_url"],
        timeout=timeout, max_retries=2,
        http_client=http_client,
    )
    tools = _build_tools(env, mode=mode, ptc_desc=ptc_desc)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_PTC if mode == "ptc" else SYSTEM_PROMPT},
        {"role": "user", "content": task_prompt},
    ]

    for turn in range(MAX_TURNS):
        print(f"\n[Turn {turn + 1}] 调用模型...")
        try:
            kwargs = dict(model=cfg["model"], messages=messages, tools=tools, temperature=temperature)
            if not cfg.get("minimal_params"):
                kwargs["tool_choice"] = "auto"
            response = client.chat.completions.create(**kwargs)
        except Exception as e:
            if _is_context_overflow(e):
                reward, info = env.step("")
                info.update({"context_overflow": True, "overflow_turn": turn + 1})
                observation = json.dumps(info, ensure_ascii=False, default=str)
                return observation, reward, info, messages
            raise

        msg = response.choices[0].message
        messages.append(msg)
        total_tokens = response.usage.total_tokens if response.usage else 0
        print(f"  [usage] total_tokens={total_tokens}")
        if msg.content:
            print(f"  [content] {msg.content}")
        if getattr(msg, "reasoning", None):
            print(f"  [reasoning] {msg.reasoning}")
        if msg.tool_calls:
            for _tc in msg.tool_calls:
                print(f"  [raw tool_call] name={_tc.function.name} arguments={_tc.function.arguments!r}")
        if max_total_tokens > 0 and total_tokens >= max_total_tokens:
            print(f"[Token limit] 总 token {total_tokens} >= 限制 {max_total_tokens}，强制结束")
            info = {"token_limit_exceeded": True, "total_tokens": total_tokens}
            observation = json.dumps(info, ensure_ascii=False, default=str)
            return observation, 0, info, messages
        if not msg.tool_calls:
            print(f"\n[无工具调用]:\n{msg.content}")
            break

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError as e:
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": (
                    f"[Error] Failed to parse tool arguments for '{tc.function.name}': {e}. "
                    f"Arguments must be a valid JSON object matching the tool schema. "
                    f"Received: {tc.function.arguments!r}"
                )})
                continue

            print(f"  -> {tc.function.name}({json.dumps(args, ensure_ascii=False)})")

            if tc.function.name == "claim_done":
                reward, info = env.step(args.get("action", ""))
                observation = json.dumps(info, ensure_ascii=False, default=str)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": observation})
                return observation, reward, info, messages

            if tc.function.name == "execute_python" and mode != "ptc":
                result = sandbox.execute(args.get("code", ""))
            elif tc.function.name == "programmatic_tool_call" and mode != "dtc":
                result = ptc_sandbox.execute(args.get("code", ""))
            elif tc.function.name == "terminal":
                try:
                    result = terminal_executor.execute(args.get("command", "")) if terminal_executor else json.dumps({"error": "Terminal not available"})
                except TerminalError as e:
                    result = f"[Terminal Error] {e}"
            elif mode == "ptc" and tc.function.name in env.tools:
                result = json.dumps({
                    "error": (
                        f"Env tool '{tc.function.name}' cannot be invoked directly. "
                        f"Use programmatic_tool_call and call it as tools[\"{tc.function.name}\"](**kwargs)."
                    )
                })
            else:
                result = execute_tool(env, tc.function.name, args)

            print(f"     {result[:300]}{'...' if len(result) > 300 else ''}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    reward, info = env.step("")
    observation = json.dumps(info, ensure_ascii=False, default=str)
    return observation, reward, info, messages


def _run_anthropic(cfg: dict, env, task_prompt: str, sandbox: StatefulSandbox, temperature: float = 1.0, terminal_executor: TerminalExecutor = None, max_total_tokens: int = 0, ptc_sandbox: StatefulSandbox = None, mode: str = "hybrid", ptc_desc: str = "rich"):
    import anthropic
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or os.environ.get("all_proxy") or os.environ.get("ALL_PROXY")
    http_client = httpx.Client(proxy=proxy) if proxy else None
    client = anthropic.Anthropic(api_key=cfg["api_key"], http_client=http_client)
    openai_tools = _build_tools(env, mode=mode, ptc_desc=ptc_desc)
    tools = [{"name": t["function"]["name"],
               "description": t["function"].get("description", ""),
               "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}})}
              for t in openai_tools]
    messages = [{"role": "user", "content": task_prompt}]

    for turn in range(MAX_TURNS):
        print(f"\n[Turn {turn + 1}] 调用模型...")
        try:
            response = client.messages.create(
                model=cfg["model"], max_tokens=8192,
                system=SYSTEM_PROMPT_PTC if mode == "ptc" else SYSTEM_PROMPT,
                messages=messages, tools=tools,
                temperature=temperature,
            )
        except Exception as e:
            if _is_context_overflow(e):
                reward, info = env.step("")
                info.update({"context_overflow": True, "overflow_turn": turn + 1})
                observation = json.dumps(info, ensure_ascii=False, default=str)
                return observation, reward, info, messages
            raise

        messages.append({"role": "assistant", "content": response.content})
        total_tokens = response.usage.input_tokens + response.usage.output_tokens
        print(f"  [usage] total_tokens={total_tokens}")
        if max_total_tokens > 0 and total_tokens >= max_total_tokens:
            print(f"[Token limit] 总 token {total_tokens} >= 限制 {max_total_tokens}，强制结束")
            info = {"token_limit_exceeded": True, "total_tokens": total_tokens}
            observation = json.dumps(info, ensure_ascii=False, default=str)
            return observation, 0, info, messages
        if response.stop_reason != "tool_use":
            text = next((b.text for b in response.content if b.type == "text"), "")
            print(f"\n[无工具调用]:\n{text}")
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"  -> {block.name}({json.dumps(block.input, ensure_ascii=False)})")

            if block.name == "claim_done":
                reward, info = env.step(block.input.get("action", ""))
                observation = json.dumps(info, ensure_ascii=False, default=str)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": observation})
                messages.append({"role": "user", "content": tool_results})
                return observation, reward, info, messages

            if block.name == "execute_python" and mode != "ptc":
                result = sandbox.execute(block.input.get("code", ""))
            elif block.name == "programmatic_tool_call" and mode != "dtc":
                result = ptc_sandbox.execute(block.input.get("code", ""))
            elif block.name == "terminal":
                try:
                    result = terminal_executor.execute(block.input.get("command", "")) if terminal_executor else json.dumps({"error": "Terminal not available"})
                except TerminalError as e:
                    result = f"[Terminal Error] {e}"
            elif mode == "ptc" and block.name in env.tools:
                result = json.dumps({
                    "error": (
                        f"Env tool '{block.name}' cannot be invoked directly. "
                        f"Use programmatic_tool_call and call it as tools[\"{block.name}\"](**kwargs)."
                    )
                })
            else:
                result = execute_tool(env, block.name, block.input)

            print(f"     {result[:300]}{'...' if len(result) > 300 else ''}")
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    reward, info = env.step("")
    observation = json.dumps(info, ensure_ascii=False, default=str)
    return observation, reward, info, messages


def run_eval(preset: str, run_id: int, output_dir: str, source_path: str, temperature: float = 1.0, max_total_tokens: int = 0, mode: str = "hybrid", ptc_desc: str = "rich") -> float | None:
    if mode not in {"dtc", "hybrid", "ptc"}:
        raise ValueError("mode must be dtc, hybrid, or ptc")
    cfg = PRESETS[preset]
    print(f"\n[Run {run_id}] model={cfg['model']}  env={source_path}")

    observation: str = ""
    reward: float = 0
    info: dict = {}
    messages: list = []
    tools: list = []
    error: dict | None = None

    try:
        with prepare_eval_env(source_path) as env_dir:
            env = None
            try:
                Task_Env = _import_task_env(env_dir)
                db_path = os.path.join(env_dir, "data.db")
                workspace = os.path.join(env_dir, "workspace")
                env_file = os.path.join(env_dir, "env.py")
                env = Task_Env(db_path=db_path, workspace=workspace)
                task_prompt = open(os.path.join(env_dir, "prompt.md"), encoding="utf-8").read()

                terminal_executor = TerminalExecutor(workspace)
                # sandbox: plain Python execution (no tools access); skipped in ptc mode
                #   since execute_python is not offered there.
                # ptc_sandbox: programmatic_tool_call with `tools` proxy injected
                #   (whenever mode != "dtc").
                from contextlib import nullcontext
                plain_ctx = (nullcontext() if mode == "ptc"
                             else StatefulSandbox(workspace_path=workspace))
                ptc_ctx = (StatefulSandbox(workspace_path=workspace, env_file=env_file, db_path=db_path)
                           if (mode != "dtc") else nullcontext())
                tools = _build_tools(env, workspace=workspace, mode=mode, ptc_desc=ptc_desc)
                with plain_ctx as sandbox, ptc_ctx as ptc_sandbox:
                    try:
                        if cfg["client"] == "anthropic":
                            observation, reward, info, messages = _run_anthropic(cfg, env, task_prompt, sandbox, temperature, terminal_executor=terminal_executor, max_total_tokens=max_total_tokens, ptc_sandbox=ptc_sandbox, mode=mode, ptc_desc=ptc_desc)
                        else:
                            observation, reward, info, messages = _run_openai(cfg, env, task_prompt, sandbox, temperature, terminal_executor=terminal_executor, max_total_tokens=max_total_tokens, ptc_sandbox=ptc_sandbox, mode=mode, ptc_desc=ptc_desc)
                    except Exception as e:
                        import traceback
                        error = {"error": str(e), "traceback": traceback.format_exc()}
                        reward = 0
                        observation = json.dumps(error, ensure_ascii=False)
                        info = {**error}
                        print(f"[Run {run_id}] 运行失败: {e}")
            finally:
                # Break the env reference cycle and drop the leaked sys.path
                # entry before the temp dir is rmtree'd, so this run's Task_Env
                # (and the module data its tools pin) frees by refcounting
                # instead of accumulating across the batch. Both kernels are
                # already reaped by the StatefulSandbox `with` exits above.
                _teardown_task_env(env)
                _drop_sys_path(env_dir)
                env = None
                gc.collect()
    except Exception as e:
        import traceback
        error = {"error": str(e), "traceback": traceback.format_exc()}
        reward = 0
        observation = json.dumps(error, ensure_ascii=False)
        info = {**error}
        print(f"[Run {run_id}] 环境准备失败: {e}")

    print(f"[Run {run_id}] 得分: {reward}")

    os.makedirs(output_dir, exist_ok=True)
    traj = {"preset": preset, "model": cfg["model"], "temperature": temperature, "run_id": run_id,
            "mode": mode,
            "ptc_desc": "ptc" if mode == "ptc" else (ptc_desc if mode != "dtc" else None),
            "turns": sum(1 for m in messages
                         if (isinstance(m, dict) and m.get("role") == "assistant")
                         or (hasattr(m, "role") and m.role == "assistant")),
            "messages": messages,
            "tools": tools}
    if error:
        traj["error"] = error
    with open(os.path.join(output_dir, "traj.json"), "w", encoding="utf-8") as f:
        json.dump(traj, f, ensure_ascii=False, indent=2, default=_json_default)
    result = {"preset": preset, "model": cfg["model"], "temperature": temperature, "run_id": run_id,
              "mode": mode, "reward": reward, "observation": observation, "info": info}
    if error:
        result["error"] = error["error"]
        result["traceback"] = error["traceback"]
    with open(os.path.join(output_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return reward


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="评测模型在合成环境上的表现")
    parser.add_argument("envs", help="环境目录（自动发现含 env.py 的子目录）或环境路径文件（每行一个，# 开头为注释）")
    parser.add_argument("--model", choices=list(PRESETS), default="local", help="评测模型预设")
    parser.add_argument("--k", type=int, default=1, help="每个环境运行次数（pass@k 的 k）")
    parser.add_argument("--n", type=int, default=1, help="全局并行度（同时进行的 run 数，跨环境统一调度）")
    parser.add_argument("--temperature", type=float, default=1.0, help="采样温度")
    parser.add_argument("--max_total_tokens", type=int, default=0, help="每次 API 调用的总 token 上限（input+output），超过则强制结束并得分为 0，0 表示不限制")
    parser.add_argument("--mode", choices=["dtc", "hybrid", "ptc"], default="hybrid",
                        help="dtc=直接调用；hybrid=直接调用+PTC；ptc=环境工具仅通过 PTC 调用")
    parser.add_argument("--ptc-desc", choices=list(PTC_DESCRIPTIONS), default="rich",
                        help="programmatic_tool_call 工具描述版本：minimal=纯净版，rich=含 few-shot 示例（--mode ptc 时忽略）")
    parser.add_argument("--resume", type=str, default=None, help="断点续推：提供已有的 eval results 文件夹路径，跳过已成功的 run，只重跑失败或缺失的")
    args = parser.parse_args()

    base = os.path.dirname(os.path.abspath(__file__))
    envs_path = os.path.abspath(args.envs)

    if os.path.isdir(envs_path):
        # 自动发现目录下所有含 env.py 的子目录
        env_paths = sorted(
            os.path.dirname(os.path.join(root, name))
            for root, _dirs, files in os.walk(envs_path)
            for name in files if name == "env.py"
        )
        if not env_paths:
            print(f"在 {envs_path} 下未找到任何包含 env.py 的环境目录")
            sys.exit(1)
        print(f"发现 {len(env_paths)} 个环境")
    else:
        with open(envs_path, encoding="utf-8") as f:
            env_paths = [
                p if os.path.isabs(p) else os.path.join(base, p)
                for line in f if (p := line.strip()) and not p.startswith("#")
            ]

    if args.resume:
        batch_dir = os.path.abspath(args.resume)
        if not os.path.isdir(batch_dir):
            print(f"Resume 目录不存在: {batch_dir}")
            sys.exit(1)
        print(f"[Resume] 从已有结果目录续推: {batch_dir}")
    else:
        batch_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_dir = os.path.join(OUTPUT_DIR, f"{args.model}_{args.mode}_t{args.temperature}_{batch_ts}")
    cfg = PRESETS[args.model]

    # 为每个 env 确定 env_name 并收集待跑任务
    def _check_run_done(env_name: str, run_id: int) -> float | None:
        result_file = os.path.join(batch_dir, env_name, f"run_{run_id}", "result.json")
        if not os.path.exists(result_file):
            return None
        try:
            with open(result_file, encoding="utf-8") as f:
                data = json.load(f)
            if "error" in data or data.get("mode") != args.mode:
                return None
            reward = data.get("reward")
            if reward is not None:
                return reward
        except (json.JSONDecodeError, KeyError):
            pass
        return None

    def _run_one(env_path: str, env_name: str, run_id: int):
        run_dir = os.path.join(batch_dir, env_name, f"run_{run_id}")
        try:
            return run_eval(args.model, run_id, run_dir, env_path, args.temperature, args.max_total_tokens,
                            mode=args.mode, ptc_desc=args.ptc_desc)
        except Exception as e:
            import traceback
            print(f"[{env_name} Run {run_id}] 失败(未捕获): {e}")
            os.makedirs(run_dir, exist_ok=True)
            err = {"error": str(e), "traceback": traceback.format_exc()}
            cfg_m = PRESETS[args.model]["model"]
            with open(os.path.join(run_dir, "traj.json"), "w", encoding="utf-8") as f:
                json.dump({"preset": args.model, "model": cfg_m, "temperature": args.temperature,
                           "run_id": run_id, "mode": args.mode, "turns": 0, "messages": [], "tools": [], "error": err},
                          f, ensure_ascii=False, indent=2)
            with open(os.path.join(run_dir, "result.json"), "w", encoding="utf-8") as f:
                json.dump({"preset": args.model, "model": cfg_m, "temperature": args.temperature,
                           "run_id": run_id, "mode": args.mode, "reward": 0, "observation": "", "info": err, **err},
                          f, ensure_ascii=False, indent=2)
            return 0

    env_infos = []  # [(env_path, env_name)]
    env_scores: dict[str, dict[int, float | None]] = {}
    pending: list[tuple[str, str, int]] = []

    for env_path in env_paths:
        abs_env = os.path.abspath(env_path.rstrip("/"))
        try:
            env_name = os.path.relpath(abs_env, base).replace(os.sep, "_")
        except ValueError:
            env_name = os.path.basename(abs_env)
        env_infos.append((env_path, env_name))
        env_scores[env_name] = {}

        if args.resume:
            existing = {i: _check_run_done(env_name, i) for i in range(1, args.k + 1)}
            if any(v is not None for v in existing.values()):
                for i, v in existing.items():
                    env_scores[env_name][i] = v
                    if v is not None:
                        print(f"  [{env_name} Run {i}] 已有结果 reward={v}")
                continue
        for rid in range(1, args.k + 1):
            pending.append((env_path, env_name, rid))

    # 全局并行池：所有 (env, run_id) 任务一起调度，max_workers=args.n
    if pending:
        print(f"\n[调度] 待跑任务 {len(pending)} 个，并行度 n={args.n}，每环境 k={args.k}")
        workers = max(1, args.n)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_run_one, ep, en, rid): (en, rid) for ep, en, rid in pending}
            for fut in as_completed(futures):
                en, rid = futures[fut]
                env_scores[en][rid] = fut.result()

    all_scores: dict[str, dict] = {}
    for env_path, env_name in env_infos:
        scores = env_scores[env_name]
        numeric = [v for v in scores.values() if v is not None]
        avg = sum(numeric) / len(numeric) if numeric else None
        env_dir = os.path.join(batch_dir, env_name)
        os.makedirs(env_dir, exist_ok=True)
        with open(os.path.join(env_dir, "summary.json"), "w") as f:
            json.dump({"model": cfg["model"], "mode": args.mode, "env": env_name, "k": args.k,
                       "scores": scores, "avg": avg},
                      f, ensure_ascii=False, indent=2, default=str)
        print(f"  [{env_name}] avg={avg}  ({len(numeric)}/{args.k} 成功)")
        all_scores[env_name] = {
            "scores": scores,
            "avg_score": avg,
            f"pass_at_{args.k}": any(v == 1.0 for v in numeric),
        }

    gc.collect()
    kill_all_kernels()
    time.sleep(2)  # let TIME_WAIT ports release

    all_numeric = [v for s in all_scores.values() for v in s["scores"].values() if v is not None]
    overall = sum(all_numeric) / len(all_numeric) if all_numeric else None
    with open(os.path.join(batch_dir, "summary.json"), "w") as f:
        json.dump({"model": cfg["model"], "mode": args.mode, "batch": os.path.basename(batch_dir),
                   "k": args.k, "n": args.n,
                   "envs": all_scores, "overall_avg": overall, "total_success": len(all_numeric)},
                  f, ensure_ascii=False, indent=2, default=str)

    total = args.k * len(env_paths)
    print(f"\n总体: {overall:.1f}/100  ({len(all_numeric)}/{total} 成功)  -> {batch_dir}" if overall
          else f"\n无成功结果  -> {batch_dir}")
