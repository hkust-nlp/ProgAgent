"""将 eval_results 中的 traj.json 转换为 ms-swift SFT 格式。

自动检测并转换 Anthropic / OpenAI 两种 traj 消息格式,统一输出为 ms-swift
多轮工具调用 SFT 格式。

ms-swift 格式约定:
  - content 为纯字符串(而非带类型标注的对象列表)
  - 工具调用单独成消息:role="tool_call",content='{"name": ..., "arguments": {...}}'
  - 工具返回为 role="tool" 的纯字符串消息,每个工具调用对应一条
  - 对话以 assistant / tool_call 结尾,满足 SFT 训练对最后一轮的要求
  - reasoning 段:--thinking 时包成 <think>...</think>(供 Qwen3.5 等思考模型),
    否则并入 assistant 的纯文本(供 Qwen3-Coder-Instruct 等非思考变体)

用法:
    python src/convert_trajectories_to_sft.py <eval_results_dir> -o output.jsonl
    python src/convert_trajectories_to_sft.py <eval_results_dir> -o output.jsonl --min-reward 50
    python src/convert_trajectories_to_sft.py <eval_results_dir> -o output.jsonl --best-per-env
    python src/convert_trajectories_to_sft.py <eval_results_dir> -o output.jsonl --thinking
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict


SYSTEM_PROMPT = (
    "You are a helpful assistant. Use the provided tools to complete the task. "
    "When you have finished the task, call the 'claim_done' tool to submit your result."
)


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def detect_format(messages: list) -> str:
    """Detect whether messages follow 'anthropic' or 'openai' format."""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        # Anthropic: assistant content is a list of blocks with "type" field
        if role == "assistant":
            content = msg.get("content")
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict) and "type" in first:
                    typ = first["type"]
                    if typ in ("text", "tool_use", "thinking"):
                        return "anthropic"
            # OpenAI: assistant has tool_calls field
            if msg.get("tool_calls") is not None:
                return "openai"
            # OpenAI: assistant content is a string
            if isinstance(content, str):
                return "openai"
        # Anthropic tool_result pattern
        if role == "user":
            content = msg.get("content")
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict) and first.get("type") == "tool_result":
                    return "anthropic"
        # OpenAI: role == "tool" with tool_call_id
        if role == "tool" and "tool_call_id" in msg:
            return "openai"
    return "openai"


# ---------------------------------------------------------------------------
# Content helpers
# ---------------------------------------------------------------------------

def _wrap(type_: str, value: str) -> dict:
    return {"type": type_, "value": value}


def _text_content(value: str) -> list:
    return [_wrap("text", value)]


# ---------------------------------------------------------------------------
# Anthropic format conversion
# ---------------------------------------------------------------------------

def convert_anthropic(messages: list, tools: list) -> dict | None:
    """Convert Anthropic-format traj messages to target SFT format."""
    out_messages = []

    # Add system message
    out_messages.append({"role": "system", "content": _text_content(SYSTEM_PROMPT)})

    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role", "")

        if role == "user":
            content = msg.get("content")
            # Simple text user message
            if isinstance(content, str):
                out_messages.append({"role": "user", "content": _text_content(content)})
            # Could be tool_result blocks
            elif isinstance(content, list):
                first = content[0] if content else {}
                if isinstance(first, dict) and first.get("type") == "tool_result":
                    # Convert tool_results to a single "tool" message
                    results = []
                    for tr in content:
                        results.append({
                            "tool_call_id": tr.get("tool_use_id") or "",
                            "name": tr.get("name") or "",
                            "content": tr.get("content") or "",
                        })
                    if len(results) == 1:
                        value = results[0].get("content") or ""
                    else:
                        value = json.dumps(results, ensure_ascii=False)
                    out_messages.append({"role": "tool", "content": _text_content(value)})
                else:
                    # Other list content — treat as text
                    text = " ".join(
                        b.get("text", "") if isinstance(b, dict) else str(b)
                        for b in content
                    )
                    out_messages.append({"role": "user", "content": _text_content(text)})

        elif role == "assistant":
            content = msg.get("content")
            if isinstance(content, str):
                out_messages.append({"role": "assistant", "content": _text_content(content)})
            elif isinstance(content, list):
                parts = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type", "")
                    if btype == "thinking":
                        parts.append(_wrap("reasoning", block.get("thinking", "")))
                    elif btype == "text":
                        text = block.get("text", "")
                        if text.strip():
                            parts.append(_wrap("text", text))
                    elif btype == "tool_use":
                        tc = {
                            "name": block.get("name", ""),
                            "arguments": block.get("input", {}),
                        }
                        parts.append(_wrap("tool_call", json.dumps(tc, ensure_ascii=False)))
                if parts:
                    out_messages.append({"role": "assistant", "content": parts})

        i += 1

    tools_str = json.dumps(tools, ensure_ascii=False)
    return {"messages": out_messages, "tools": tools_str}


# ---------------------------------------------------------------------------
# OpenAI format conversion
# ---------------------------------------------------------------------------

def convert_openai(messages: list, tools: list) -> dict | None:
    """Convert OpenAI-format traj messages to target SFT format."""
    out_messages = []
    i = 0

    while i < len(messages):
        msg = messages[i]
        role = msg.get("role", "")

        if role == "system":
            out_messages.append({"role": "system", "content": _text_content(msg.get("content") or "")})

        elif role == "user":
            out_messages.append({"role": "user", "content": _text_content(msg.get("content") or "")})

        elif role == "assistant":
            parts = []
            # Reasoning (e.g. DeepSeek reasoner)
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if reasoning:
                parts.append(_wrap("reasoning", reasoning))
            # Text content
            text = msg.get("content") or ""
            if isinstance(text, str) and text.strip():
                parts.append(_wrap("text", text))
            # Tool calls
            tool_calls = msg.get("tool_calls") or []
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                try:
                    arguments = json.loads(func.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    arguments = func.get("arguments", {})
                tc_obj = {"name": name, "arguments": arguments}
                parts.append(_wrap("tool_call", json.dumps(tc_obj, ensure_ascii=False)))
            if parts:
                out_messages.append({"role": "assistant", "content": parts})

        elif role == "tool":
            # Collect consecutive tool messages into one
            results = []
            while i < len(messages) and messages[i].get("role") == "tool":
                tmsg = messages[i]
                results.append({
                    "tool_call_id": tmsg.get("tool_call_id") or "",
                    "name": tmsg.get("name") or "",
                    "content": tmsg.get("content") or "",
                })
                i += 1
            if len(results) == 1:
                value = results[0].get("content") or ""
            else:
                value = json.dumps(results, ensure_ascii=False)
            out_messages.append({"role": "tool", "content": _text_content(value)})
            continue  # skip the i += 1 at the end

        i += 1

    # Ensure system message is present
    if not out_messages or out_messages[0]["role"] != "system":
        out_messages.insert(0, {"role": "system", "content": _text_content(SYSTEM_PROMPT)})

    tools_str = json.dumps(tools, ensure_ascii=False)
    return {"messages": out_messages, "tools": tools_str}


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def load_traj(traj_path: str) -> tuple[dict | None, float | None]:
    """Load traj.json and its corresponding result.json. Returns (traj_data, reward)."""
    result_path = os.path.join(os.path.dirname(traj_path), "result.json")
    try:
        with open(traj_path, encoding="utf-8") as f:
            traj = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None, None

    reward = None
    if os.path.exists(result_path):
        try:
            with open(result_path, encoding="utf-8") as f:
                result = json.load(f)
            reward = result.get("reward")
        except (json.JSONDecodeError, OSError):
            pass

    return traj, reward


def _rewrite_tools_dot(code: str) -> str:
    """Rewrite tools.func_name(...) to tools["func_name"](...) in code."""
    return re.sub(r'(?<![a-zA-Z0-9_])tools\.([a-zA-Z_][a-zA-Z0-9_]*)', r'tools["\1"]', code)


def _rewrite_ptc_in_messages(messages: list) -> list:
    """Rewrite programmatic_tool_call code in all assistant messages."""
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for item in msg.get("content", []):
            if item.get("type") != "tool_call":
                continue
            try:
                tc = json.loads(item["value"])
            except (json.JSONDecodeError, TypeError):
                continue
            if tc.get("name") != "programmatic_tool_call":
                continue
            arguments = tc.get("arguments")
            # Upstream may leave arguments as a raw JSON string (e.g. when the
            # provider returned an unparseable fragment). Normalise to dict.
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not isinstance(arguments, dict) or "code" not in arguments:
                continue
            code = arguments["code"]
            if not isinstance(code, str):
                continue
            arguments["code"] = _rewrite_tools_dot(code)
            tc["arguments"] = arguments
            item["value"] = json.dumps(tc, ensure_ascii=False)
    return messages


def _rewrite_ptc_in_tools(tools_str: str) -> str:
    """Rewrite tools.xxx examples in programmatic_tool_call description and param descriptions."""
    tool_list = json.loads(tools_str)
    for t in tool_list:
        func = t.get("function", {})
        if func.get("name") != "programmatic_tool_call":
            continue
        # Top-level description
        if "description" in func:
            func["description"] = _rewrite_tools_dot(func["description"])
        # Parameter descriptions (e.g. parameters.properties.code.description)
        for prop in func.get("parameters", {}).get("properties", {}).values():
            if "description" in prop:
                prop["description"] = _rewrite_tools_dot(prop["description"])
    return json.dumps(tool_list, ensure_ascii=False)


def _flatten_content(content) -> str:
    """Flatten an intermediate typed-content list to a plain string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "\n".join((item.get("value") or "") for item in content)


def convert_to_msswift(data: dict, thinking: bool = False) -> dict:
    """Convert the intermediate typed-content format to ms-swift format.

    The intermediate format is produced by convert_anthropic / convert_openai:
    each message's content is a list of ``{"type": ..., "value": ...}`` blocks.

    ms-swift expects:
    - content is a plain string (not a list of typed objects)
    - tool calls are separate messages with role="tool_call" and
      content='{"name": "...", "arguments": {...}}'
    - tool responses have role="tool" with content as a plain string
    - multiple tool responses should be separate "tool" messages (one per tool call),
      so Qwen3-Coder's _get_tool_responses wraps each in <tool_response> tags
    - conversation must end with an assistant message for SFT training

    Args:
        data: intermediate format produced by convert_anthropic / convert_openai.
        thinking: if True, wrap ``reasoning`` blocks in ``<think>...</think>`` so the
            target template (e.g. Qwen3.5, ``is_thinking=True``) recognises them as
            thinking segments. ms-swift's ``_add_non_thinking_prefix`` only treats
            content starting with ``<think>`` as pre-thought; otherwise it prepends
            ``<think>\\n\\n</think>\\n\\n`` and the raw reasoning text becomes visible
            output. If False, reasoning is merged into the plain assistant text
            (appropriate for non-thinking variants like Qwen3-Coder-30B-A3B-Instruct
            that lack ``<think>`` support but can still learn from the reasoning
            trace as regular output).
    """
    out_messages = []
    for msg in data["messages"]:
        role = msg["role"]
        content = msg["content"]

        if role == "assistant":
            # Separate reasoning, surface text, and tool_call items so we can render
            # the assistant turn as:  <think>…</think>\n\n + surface_text + tool_calls
            reasoning_parts = []
            surface_parts = []
            tool_calls = []
            for item in content:
                itype = item.get("type")
                value = item.get("value") or ""
                if itype == "tool_call":
                    tool_calls.append(value)
                elif itype == "reasoning":
                    stripped = value.strip()
                    if not stripped:
                        continue
                    if thinking:
                        reasoning_parts.append(value)
                    else:
                        # thinking=False (e.g. Qwen3-Coder-Instruct): no <think> tags
                        # available in the template, so merge reasoning into the
                        # plain assistant text instead of dropping it. Strip to
                        # avoid stray leading/trailing blank lines.
                        surface_parts.append(stripped)
                elif itype == "text":
                    if value.strip():
                        surface_parts.append(value)

            assistant_content = ""
            if reasoning_parts:
                assistant_content = "<think>\n" + "\n".join(reasoning_parts).strip() + "\n</think>\n\n"
            if surface_parts:
                assistant_content += "\n".join(surface_parts)
            # Always strip trailing whitespace from the natural text portion so
            # noisy `\n` from upstream reasoning/text doesn't leak into the
            # serialized data. Both Qwen3.5 and Qwen3-Coder templates apply
            # `content | trim`, so this is a no-op on training tokens.
            assistant_content = assistant_content.rstrip()
            # Qwen3.5's HF template inserts `\n\n` between assistant content and
            # the first <tool_call>. ms-swift just concatenates the merged
            # tool_call message onto assistant_content, so add the separator
            # manually — but only for thinking=True (Qwen3.5 path). Qwen3-Coder
            # provides the separator itself via `content | trim + '\n'` +
            # `\n<tool_call>`.
            if assistant_content and tool_calls and thinking:
                assistant_content += "\n\n"

            # Emit assistant message if there is any content, or if the turn has no
            # tool calls (so the pairing requirement is satisfied).
            if assistant_content or not tool_calls:
                out_messages.append({"role": "assistant", "content": assistant_content})

            # Emit each tool_call as a separate message. ms-swift's
            # _preprocess_function_call converts these to a trailing assistant
            # message; _swift_prepare_inputs then merges it with the thinking-only
            # assistant above, producing a single turn rendered as
            # <think>…</think>\n\n<tool_call>…</tool_call>.
            for tc_value in tool_calls:
                out_messages.append({"role": "tool_call", "content": tc_value})

        elif role == "tool":
            # Split combined tool results into separate tool messages.
            # The intermediate format may merge multiple results into one JSON array;
            # ms-swift's _get_tool_responses wraps each tool message in <tool_response> tags.
            # Qwen3.5's HF template trims content before wrapping it with
            # `\n<tool_response>\n ... \n</tool_response>`, so trailing `\n` in the
            # raw payload would otherwise produce an extra blank line before the
            # closing tag in ms-swift's output. Strip to match HF behavior.
            text = _flatten_content(content)
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                parsed = None
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) and "tool_call_id" in parsed[0]:
                # Multiple tool results packed as a JSON array — split them
                for result in parsed:
                    result_content = (result.get("content") or "").strip()
                    out_messages.append({"role": "tool", "content": result_content})
            else:
                out_messages.append({"role": "tool", "content": text.strip()})

        elif role in ("system", "user"):
            # Qwen3.5's HF template applies `|trim` to every message's content,
            # so trailing `\n` in source data leaks into ms-swift output as
            # `content\n<|im_end|>` instead of `content<|im_end|>`. Match HF.
            out_messages.append({"role": role, "content": _flatten_content(content).strip()})
        else:
            out_messages.append({"role": role, "content": _flatten_content(content)})

    # ms-swift's _preprocess_function_call merges trailing tool_call messages into the
    # preceding assistant turn, so ending on tool_call is equivalent to ending on assistant.
    # Drop trailing tool responses (e.g. the claim_done result) so the final training
    # signal is the tool_call itself — appending an empty assistant would teach the model
    # to emit <|im_end|> immediately after a tool response.
    while out_messages and out_messages[-1]["role"] == "tool":
        out_messages.pop()

    if not out_messages or out_messages[-1]["role"] not in ("assistant", "tool_call"):
        return None

    return {"messages": out_messages, "tools": data["tools"]}


def _find_bad_tool_call(converted: dict) -> str | None:
    """Return a short description of the first malformed tool_call, or None.

    A tool_call is malformed if its serialized content is not valid JSON, or its
    ``arguments`` field is not a dict. This happens when the source model emitted
    invalid-JSON tool arguments (e.g. an unescaped multi-line ``code`` blob) that
    eval.py rejected but still stored in traj.json. ms-swift's agent_template
    re-parses these during encoding and asserts, crashing training — so such
    trajectories must be dropped entirely.
    """
    for msg in converted["messages"]:
        if msg.get("role") != "tool_call":
            continue
        try:
            tc = json.loads(msg["content"])
        except (json.JSONDecodeError, TypeError):
            return f"tool_call content not valid JSON: {msg['content'][:80]!r}"
        if not isinstance(tc.get("arguments"), dict):
            name = tc.get("name", "?")
            return f"tool_call '{name}' arguments is {type(tc.get('arguments')).__name__}, not dict"
    return None


def convert_traj(traj: dict, thinking: bool = False) -> dict | None:
    """Convert a traj dict to ms-swift SFT format.

    Args:
        traj: parsed traj.json.
        thinking: if True, preserve assistant ``reasoning_content`` / Anthropic
            thinking blocks as ``<think>…</think>`` wrapped content (target:
            Qwen3.5 and other thinking models). If False, reasoning is merged
            into the plain assistant text instead of being dropped, so
            non-thinking templates (Qwen3-Coder-Instruct) still see the reasoning
            trace during SFT.
    """
    messages = traj.get("messages", [])
    tools = traj.get("tools", [])
    if not messages:
        return None

    fmt = detect_format(messages)
    if fmt == "anthropic":
        result = convert_anthropic(messages, tools)
    else:
        result = convert_openai(messages, tools)

    if result is None:
        return None

    # Rewrite tools.xxx → tools["xxx"] in programmatic_tool_call
    _rewrite_ptc_in_messages(result["messages"])
    result["tools"] = _rewrite_ptc_in_tools(result["tools"])

    return convert_to_msswift(result, thinking=thinking)


def find_trajs(eval_dir: str) -> list[str]:
    """Recursively find all traj.json files under eval_dir."""
    trajs = []
    for root, _dirs, files in os.walk(eval_dir, followlinks=True):
        if "traj.json" in files:
            trajs.append(os.path.join(root, "traj.json"))
    return sorted(trajs)


def main():
    parser = argparse.ArgumentParser(
        description="Convert eval traj.json files to ms-swift SFT format."
    )
    parser.add_argument("eval_dir", help="Eval results directory (e.g. eval_results/claude_t1.0_...)")
    parser.add_argument("-o", "--output", required=True, help="Output JSONL path")
    parser.add_argument("--min-reward", type=float, default=0,
                        help="Minimum reward to include (default: 0, i.e. include all non-error runs)")
    parser.add_argument("--best-per-env", action="store_true",
                        help="Only keep the best-reward run per environment")
    parser.add_argument("--version", nargs="*", default=None, metavar="V",
                        help="Only include envs whose difficulty version matches (e.g. "
                             "--version v0). Matches the env-name suffix _v<N>; accepts "
                             "multiple values. Default: include all versions.")
    parser.add_argument("--exclude-tools", nargs="*", default=[],
                        help="Tool names to exclude from the tools list (e.g. execute_python terminal)")
    parser.add_argument("--thinking", action="store_true",
                        help="Wrap assistant reasoning in <think>...</think> (required for "
                             "training thinking models like Qwen3.5). Without this flag, "
                             "reasoning is folded into the plain assistant text so non-thinking "
                             "variants (Qwen3-Coder-30B-A3B-Instruct) still see it.")
    args = parser.parse_args()

    traj_paths = find_trajs(args.eval_dir)
    if not traj_paths:
        print(f"No traj.json files found under {args.eval_dir}")
        sys.exit(1)
    print(f"Found {len(traj_paths)} traj.json files")

    # Normalise requested versions to a {"v0", "v1", ...} set (accept "0" or "v0").
    versions = None
    if args.version:
        versions = {v if v.startswith("v") else f"v{v}" for v in args.version}
        print(f"Filtering to versions: {', '.join(sorted(versions))}")

    # Load all trajectories with rewards
    entries = []
    for path in traj_paths:
        traj, reward = load_traj(path)
        if traj is None:
            print(f"  [skip] failed to load: {path}")
            continue
        if reward is None:
            print(f"  [skip] no reward found: {path}")
            continue
        if reward < args.min_reward:
            print(f"  [skip] reward {reward} < {args.min_reward}: {path}")
            continue
        # env_name is the parent of run_N directory
        env_name = os.path.basename(os.path.dirname(os.path.dirname(path)))
        if versions is not None:
            m = re.search(r"_(v\d+)$", env_name)
            if m is None or m.group(1) not in versions:
                continue
        entries.append((env_name, reward, traj, path))

    print(f"Loaded {len(entries)} valid trajectories")

    # Best-per-env filtering
    if args.best_per_env:
        by_env = defaultdict(list)
        for env_name, reward, traj, path in entries:
            by_env[env_name].append((reward, traj, path))
        entries = []
        for env_name, runs in by_env.items():
            best = max(runs, key=lambda x: x[0])
            entries.append((env_name, best[0], best[1], best[2]))
        print(f"After best-per-env: {len(entries)} trajectories")

    # Convert and write
    written = 0
    skipped = 0
    with open(args.output, "w", encoding="utf-8") as out:
        for env_name, reward, traj, path in entries:
            converted = convert_traj(traj, thinking=args.thinking)
            if converted is None:
                print(f"  [skip] conversion failed: {path}")
                skipped += 1
                continue

            # Drop trajectories containing a malformed tool_call. The source model
            # sometimes emits invalid-JSON tool arguments that eval.py rejected but
            # still stored; ms-swift's agent_template asserts on these during encode.
            bad = _find_bad_tool_call(converted)
            if bad is not None:
                print(f"  [skip] {bad}: {path}")
                skipped += 1
                continue

            # Optionally filter tools
            if args.exclude_tools:
                tools_field = converted["tools"]
                tools_is_str = isinstance(tools_field, str)
                tool_list = json.loads(tools_field) if tools_is_str else tools_field
                tool_list = [
                    t for t in tool_list
                    if t.get("function", {}).get("name") not in args.exclude_tools
                ]
                converted["tools"] = json.dumps(tool_list, ensure_ascii=False) if tools_is_str else tool_list

            out.write(json.dumps(converted, ensure_ascii=False) + "\n")
            written += 1

    print(f"\nDone: {written} entries written to {args.output} "
          f"(backend=ms-swift, {skipped} skipped)")


if __name__ == "__main__":
    main()
