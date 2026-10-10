# Copyright 2025 GEM Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Shared parsing and SQLite snapshot handling for TaskSync tool modes."""

import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def copy_sqlite_database(source: str, destination: str) -> None:
    """Copy committed SQLite state, including WAL data, schema, updates and deletes."""
    # Open the source read-only so a missing snapshot cannot become an empty DB.
    source_uri = Path(source).resolve().as_uri() + "?mode=ro"

    def check_lock(status, remaining, total):
        # backup() otherwise retries indefinitely on a live destination transaction.
        if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise sqlite3.OperationalError("Cannot copy TaskSync database while a transaction holds its lock")

    with closing(sqlite3.connect(source_uri, uri=True)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst, progress=check_lock)


class TaskSyncToolParser:
    """Use the same tool-call parsing rules for ptc, hybrid, and dtc."""

    def _parse_tool_calls(self, response: str) -> tuple[list[dict[str, Any]], list[str]]:
        """Parse all tool calls in the response.

        Returns (calls, errors). ``errors`` is non-empty when the response
        *attempted* a tool call (had <tool_call> / <function=> / a JSON object
        with a "name" key) but parsing failed somewhere. Callers can use this
        signal to surface the error back to the model instead of silently
        terminating the rollout with reward 0.
        """
        calls: list[dict[str, Any]] = []
        errors: list[str] = []

        # Ignore anything emitted inside the model's reasoning block. Qwen3
        # thinking models sometimes leak a <tool_call> into <think>...</think>;
        # only the post-reasoning answer should drive tool execution. If a
        # </think> terminator is present, restrict parsing to the text after the
        # final one. Models without a reasoning block (e.g. the Coder instruct
        # variant) have no </think>, so the full response is parsed unchanged.
        think_close = "</think>"
        think_end = response.rfind(think_close)
        if think_end != -1:
            response = response[think_end + len(think_close) :]
        elif "<think>" in response:
            return calls, errors

        # XML-style: strict format -- requires <tool_call>...</tool_call> wrapper,
        # with a properly closed <function=NAME>...</function> inside.
        open_tag = "<tool_call>"
        close_tag = "</tool_call>"
        if open_tag in response:
            idx = 0
            while True:
                start = response.find(open_tag, idx)
                if start == -1:
                    break
                end = response.find(close_tag, start + len(open_tag))
                if end == -1:
                    msg = "Unclosed <tool_call> wrapper (missing </tool_call>)"
                    logger.warning("%s; dropping call", msg)
                    errors.append(msg)
                    break
                inner = response[start + len(open_tag) : end]
                parsed = self._parse_tool_call(inner, errors)
                if parsed is not None:
                    calls.append(parsed)
                idx = end + len(close_tag)
            return calls, errors

        # JSON-style: scan for all top-level {...} blocks containing a "name" field.
        pos = 0
        while pos < len(response):
            start = response.find("{", pos)
            if start == -1:
                break
            end = self._find_balanced_brace(response, start)
            if end == -1:
                if '"name"' in response[start:]:
                    errors.append("Unbalanced braces in JSON tool call (could not find matching '}').")
                break
            blob = response[start : end + 1]
            if '"name"' in blob:
                parsed = self._parse_tool_call(blob, errors)
                if parsed is not None:
                    calls.append(parsed)
            # Do not reinterpret nested argument objects as separate tool calls.
            pos = end + 1
        return calls, errors

    @staticmethod
    def _find_balanced_brace(s: str, start: int) -> int:
        """Return index of `}` that closes `s[start]` (which must be `{`),
        respecting string literals. Returns -1 if unbalanced."""
        depth = 0
        in_str = False
        esc = False
        for j in range(start, len(s)):
            c = s[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return j
        return -1

    def _parse_tool_call(self, block: str, errors: list[str]) -> Optional[dict[str, Any]]:
        """Parse a single tool call from the contents of a <tool_call>...</tool_call>
        block. Dispatches on self.tool_call_format. Appends a descriptive message
        to ``errors`` on failure so the caller can surface it to the model."""
        fmt = getattr(self, "tool_call_format", "auto")
        stripped = block.strip()

        if fmt == "json":
            return self._parse_tool_call_json(stripped, errors)
        if fmt == "xml":
            return self._parse_tool_call_xml(block, errors)
        # auto
        if "<function=" in block:
            return self._parse_tool_call_xml(block, errors)
        if stripped.startswith("{"):
            return self._parse_tool_call_json(stripped, errors)
        msg = "Tool call inside <tool_call> has neither <function=...> nor a JSON object."
        logger.warning("%s Dropping.", msg)
        errors.append(msg)
        return None

    def _parse_tool_call_json(self, blob: str, errors: list[str]) -> Optional[dict[str, Any]]:
        """Parse Hermes-style JSON tool call: {"name": ..., "arguments": {...}}."""
        try:
            obj = json.loads(blob)
        except (json.JSONDecodeError, ValueError) as e:
            preview = blob[:200].replace("\n", "\\n")
            logger.error(f"tool_call_format=json: JSON parse failed ({e}); dropping. raw='{preview}'")
            errors.append(f"JSON parse failed: {e}. Snippet: {preview}")
            return None
        if not isinstance(obj, dict) or "name" not in obj:
            preview = blob[:200].replace("\n", "\\n")
            logger.error(f"tool_call_format=json: missing 'name' field; dropping. raw='{preview}'")
            errors.append("JSON tool call missing required 'name' field.")
            return None
        name = obj["name"]
        if not isinstance(name, str) or not name:
            logger.error(f"tool_call_format=json: invalid 'name' field; dropping. raw='{blob[:200]}'")
            errors.append("JSON tool call 'name' field is empty or not a string.")
            return None
        args = obj.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, ValueError) as e:
                errors.append(f"'arguments' for tool '{name}' was a string but not valid JSON: {e}")
                return None
        if not isinstance(args, dict):
            errors.append(f"'arguments' for tool '{name}' must be a JSON object, got {type(args).__name__}.")
            return None
        return {"name": name, "arguments": args}

    def _parse_tool_call_xml(self, block: str, errors: list[str]) -> Optional[dict[str, Any]]:
        try:
            func_start = block.find("<function=")
            if func_start == -1:
                msg = "Tool call missing <function=...> tag."
                logger.warning("%s Dropping.", msg)
                errors.append(msg)
                return None

            func_part = block[func_start + len("<function=") :]
            name_end = func_part.find(">")
            if name_end == -1:
                msg = "Malformed <function=...> tag (missing '>')."
                logger.warning("%s Dropping.", msg)
                errors.append(msg)
                return None
            func_name = func_part[:name_end].strip()
            if not func_name:
                msg = "Empty function name in <function=...> tag."
                logger.warning("%s Dropping.", msg)
                errors.append(msg)
                return None

            remaining = func_part[name_end + 1 :]
            close_idx = remaining.find("</function>")
            if close_idx == -1:
                msg = f"Tool call '{func_name}' missing </function> closing tag."
                logger.warning("%s Dropping.", msg)
                errors.append(msg)
                return None
            params_block = remaining[:close_idx]

            arguments: dict[str, Any] = {}
            if "<parameter=" in params_block:
                params = params_block.split("<parameter=")
                for param in params[1:]:
                    pname_end = param.find(">")
                    if pname_end == -1:
                        msg = f"Malformed <parameter=...> in '{func_name}' (missing '>')."
                        logger.warning("%s Dropping call.", msg)
                        errors.append(msg)
                        return None
                    param_name = param[:pname_end].strip()
                    if not param_name:
                        msg = f"Empty parameter name in '{func_name}'."
                        logger.warning("%s Dropping call.", msg)
                        errors.append(msg)
                        return None
                    after = param[pname_end + 1 :]
                    pclose_idx = after.find("</parameter>")
                    if pclose_idx == -1:
                        msg = f"Parameter '{param_name}' in '{func_name}' missing </parameter> closing tag."
                        logger.warning("%s Dropping call.", msg)
                        errors.append(msg)
                        return None
                    param_value_raw = after[:pclose_idx].strip()
                    schema = next(
                        (
                            tool["function"].get("parameters", {}).get("properties", {}).get(param_name, {})
                            for tool in getattr(self, "tool_schemas", [])
                            if tool.get("function", {}).get("name") == func_name
                        ),
                        {},
                    )
                    arguments[param_name] = (
                        param_value_raw if schema.get("type") == "string" else self._parse_param_value(param_value_raw)
                    )

            return {"name": func_name, "arguments": arguments}
        except Exception as e:
            logger.warning(f"Error parsing tool call: {e}")
            errors.append(f"Unexpected error parsing XML tool call: {e}")
            return None

    def _parse_param_value(self, param_value_raw: str) -> Any:
        if not param_value_raw:
            return param_value_raw

        if param_value_raw.lower() in {"true", "false"}:
            return param_value_raw.lower() == "true"

        try:
            if "." in param_value_raw:
                return float(param_value_raw)
            else:
                return int(param_value_raw)
        except (ValueError, TypeError):
            pass

        try:
            return json.loads(param_value_raw)
        except (json.JSONDecodeError, ValueError):
            pass

        return param_value_raw
