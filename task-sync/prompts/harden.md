You are hardening an existing task environment's **tool surface** so that RL training covers the messy tool interfaces found in real-world MCP/API benchmarks (JSON-string parameters, deep nesting, mixed return encodings, unbounded bulk returns, layered write-payload validation). You can use the conda environment `eval`.

Your assignment:

**{TOPIC}**

The assignment has the form `SOURCE=<path> MUTATORS=<list>`. `SOURCE` is relative to the repository root `task-sync/`. `MUTATORS` names the mutations (from M0–M5 below) you must apply.

---

### 0. Prime Directive

The task itself must NOT change. Same data, same business logic, same deliverables, same scoring. You are re-skinning the *tool surface* only, so that a well-known-good solution still earns reward 1.0 — it just has to work harder to parse parameters and returns.

- `data.py`: **never modified** (M0 exception: additive policy-document changes only, see M0).
- `prompt.md`: **never modified** unless M0 is assigned (plus the narrow M4 exception below); under M0 the deliverable contract must survive verbatim.
- `step()` and `_compute_ground_truth()` (or equivalents): **never modified** — the ground truth and criteria weights stay exactly as in SOURCE.
- Only the `@tool` methods, their schemas/descriptions, and `verify()` change. `verify()` must be updated to consume the new surface and still return reward 1.0 — it is your existence proof that the hardened surface is fully parseable.

Reference exemplars (read them before writing code; all three also demonstrate M0 on `prompt.md` + `data.py`):
- M2+M3: `environments/hard/ad_inventory_pricing_optimization_harden/v0/`
- M1+M4: `environments/hard/technical_ticket_assignment_harden/v0/`
- M5+M2: `environments/hard/listener_retention_audit_harden/v0/`

### 1. Setup

1. Copy the SOURCE task into the current directory: `README.md` and `v0/ v1/ v2/ v3/` each with `data.py`, `env.py`, `prompt.md`. Remove any `__pycache__`, `data.db`, or `workspace/` artifacts that came along.
2. Read `v0/env.py` end to end: tools, `step()`, `verify()`. Read `prompt.md`. You will edit only `v0/env.py`, then re-propagate.

### 2. Shared helpers (copy verbatim into env.py)

```python
import ast
import hashlib
import json

def _request_id(message: str) -> str:
    return "req_" + hashlib.md5(message.encode("utf-8")).hexdigest()[:12]

def _error(status: int, code: str, message: str) -> dict:
    """Error responses share NO keys with success responses."""
    return {
        "status": status,
        "object": "error",
        "code": code,
        "message": message,
        "request_id": _request_id(f"{status}:{code}:{message}"),
    }

def _envelope(payload) -> dict:
    """MCP-style envelope: payload is JSON-encoded into a text content block."""
    return {
        "meta": None,
        "content": [
            {"type": "text",
             "text": json.dumps(payload, ensure_ascii=False, default=str)}
        ],
        "isError": False,
    }

def _shape(value) -> str:
    """Short rendering of a wrong-typed value for error text."""
    if value is None:
        return "'undefined'"
    r = repr(value)
    if len(r) > 60:
        r = r[:57] + "..."
    return f"'{r}'"
```

Universal error rules, regardless of mutator set:
- Tools NEVER raise. Every failure returns `_error(...)` (or its JSON-string form if that tool returns strings) so the model gets a *recoverable* mid-trajectory signal.
- Not-found → `_error(404, "object_not_found", "Could not find <entity> with ID: <id>.")`. Bad input → `_error(400, "validation_error", ...)` / `_error(400, "invalid_json", ...)`.
- Success and error responses must share **no keys** — the model has to branch on shape, not on an `error` field being present.

### 3. Mutators

Apply exactly the mutators named in your assignment. Where mutators overlap on one tool, pick one form per tool; across the env the assigned mutators must all be clearly represented.

#### M0 — de-proceduralized prompt

The SOURCE prompt typically narrates the solution route step by step. Rewrite `prompt.md` so it specifies the *goal and the deliverable contract*, not the route. Classify every sentence of the SOURCE prompt and act accordingly:

1. **Deliverable contract — keep verbatim.** The paragraph(s) stating output file names, exact column lists and order, precision, sort keys, tie-breakers, field definitions (e.g. what a count column counts), and any required content of the final response. These are enforced by `step()` and must remain in the prompt word for word (light joining edits allowed, no information removed).
2. **Route narration — delete unconditionally.** Tool hand-holding ("a dedicated tool returns...", "use the lookup function", "the statistics tool returns X directly"), sequencing scaffolds ("Start by...", "Once you have...", "before proceeding"), and per-file navigation ("One file lays out... Another file specifies..." — compress to a single sentence pointing at "the policy and configuration documents stored alongside the data" as the authoritative specification).
3. **Business-rule restatements — delete only after verifying discoverability.** Before deleting a rule sentence (formulas, eligibility criteria, boundary conventions, default values), grep the *generated workspace* and confirm the same rule is stated in some workspace document. If it is not, either keep the sentence or apply rule 4.
4. **Prompt-only rules — move into a workspace document, then delete.** Extend an existing policy document or add a new methodology document (e.g. `audit_methodology.md`) via `data.py`, containing the precise formulas/conventions, then drop them from the prompt. This is the ONLY permitted `data.py` change: adding or extending fixed (non-scaling) policy/config documents. Never touch tables, row generation, seeds, scalable files, or the `SCALE` dict.

The rewritten prompt keeps the original tone rules (prose, no headings, no lists, no tool names, no source-data filenames) and typically lands at 3–5 short paragraphs: scenario/goal, "the policy documents govern everything" pointer, the verbatim deliverable contract, the final-response requirement.

**Gate (mandatory when M0 is applied):** build a completeness audit — for every criterion `step()` scores, record where the information needed to satisfy it now lives (prompt paragraph, or named workspace document). Every criterion must be traceable; if any rule is reachable only by reading `env.py` source, the task has become underspecified and you must fix it via rule 4. Include this audit table in the README Hardening section. Note that `verify()` passing does NOT validate prompt sufficiency — it never reads the prompt — which is why this audit is required.

#### M1 — JSON-encoded string parameters

Pick 1–2 query tools with multiple optional filters and collapse the filters into a single `filter` parameter of JSON-Schema type `string`, documented as a JSON-encoded string with an inline example. Validation template:

```python
def _parse_json_string_param(raw, param_name: str):
    if raw is None or raw == "":
        return {}, None
    if isinstance(raw, (dict, list)):
        return None, _error(400, "invalid_request",
            f"body.{param_name} should be a JSON-encoded string, instead was an object. "
            f"Serialize it to a JSON string before passing it.")
    if not isinstance(raw, str):
        return None, _error(400, "invalid_request",
            f"body.{param_name} should be a JSON-encoded string, instead was {type(raw).__name__}.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, _error(400, "invalid_json",
            f"Failed to parse {param_name}: {e.msg}: line {e.lineno} column {e.colno} (char {e.pos})")
    if not isinstance(value, dict):
        return None, _error(400, "invalid_request",
            f"body.{param_name} should encode a JSON object, instead was {type(value).__name__}.")
    return value, None
```

After parsing, validate keys/types one error at a time: unsupported key → `body.filter.<key> is not a supported filter property. Supported properties: <list>.`; wrong type → `body.filter.<key> should be a boolean, instead was {_shape(v)}.` The `filter` method parameter must be typed `Any` with default `None` so wrong-typed inputs reach your validation instead of crashing.

#### M2 — mixed return encodings

Distribute these five return forms across the env's tools (descriptions state WHAT the tool returns, never HOW it is encoded — the model must probe):

1. **native dict** — keep ~30–40% of tools unchanged so the model cannot assume "everything is a string";
2. **JSON-encoded string** — `return json.dumps(payload, ensure_ascii=False)`;
3. **MCP envelope** — `return _envelope(payload)`; consumers need `json.loads(resp["content"][0]["text"])`;
4. **plain `key: value` text** — `return "\n".join(f"{k}: {v}" for k, v in fields.items())` (single flat record tools only);
5. **Python-repr string** — `return repr(payload)` (single quotes; `json.loads` fails, needs `ast.literal_eval`).

Assign one form per tool and keep it stable. Error paths still return the `_error` dict (or `json.dumps(_error(...))` for JSON-string tools) — deliberately a different shape from that tool's success form.

#### M3 — deep-nested record structures

Reshape list/detail tool returns into Notion-style records, 3–4 levels deep. Builders:

```python
def _select(name):
    return {"type": "select", "select": {"name": name}}

def _number(value):
    return {"type": "number", "number": value}

def _title(text):
    return {"type": "title", "title": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}

def _relation(*ids):
    return {"type": "relation", "relation": [{"id": i} for i in ids]}
```

List tools return `{"object": "list", "results": [{"object": "<entity>", "id": ..., "properties": {...}}, ...], "has_more": bool, "next_cursor": <page+1 or None>}` — cursor-style pagination instead of `total`/`total_pages`. Keep the deliberate traps: display text lives at `title[0].plain_text` (NOT `title[0].text.plain_text`), category-ish values at `select.name`, foreign keys at `relation[0].id`.

#### M4 — nested write payloads with layered validation

Replace (or add) a write tool whose single `payload` parameter is a nested object: `parent` (`{"type": "<queue/collection kind>", "<entity>_id": "..."}`) + `properties` (must contain a required reference/typed property; may allow an optional `rich_text` property). Schema type `object` with nested `properties`, `required`, and `"additionalProperties": True`; include one full example body in the tool description.

Validation is **layered, one error per call**, in order: body defined → body is object (a string body gets `body should be an object, instead was '...'. Pass a JSON object, not a string.`) → `parent` defined/object → `parent.type` exact value → `parent.<id>` non-empty string → `properties` defined/object → required property defined → its `type` field exact → its nested reference object → the innermost id string → optional property shape. Messages follow the Notion pattern: `body.parent.engineer_id should be a non-empty string, instead was 'undefined'.` Only after structural validation run the business checks (entity exists, correct state) as `_error(404/400, ...)`. Success returns a deep echo (`{"object": "<kind>", "id": "...", "parent": {...}, "properties": {...}, "created": True}`) sharing no keys with errors. The Python parameter must be `payload: Any = None` — never let a malformed payload raise.

The underlying DB write must be exactly what the SOURCE write tool did (same UPDATE/INSERT), so `step()`'s DB-state criteria keep working unchanged. If SOURCE has no write tool, converting one deliverable from "write a workspace file" to "record via the write API" is allowed — this is the only case where `step()` gains a DB-state criterion and `prompt.md` may be minimally reworded; rebalance criterion weights minimally and keep everything scale-invariant.

#### M5 — unbounded bulk export (context-pressure trap)

Add one parameterless (or near-parameterless) export/search tool that returns the full joined dataset as ONE JSON string, no pagination. Requirements:

- The description must be enticing and honest about content but silent about size: "Returns the complete <X> dataset in a single response ... No pagination required."
- It must be genuinely sufficient to solve the core filtering step of the task — consuming it *inside the programmatic sandbox* and printing only a filtered summary is the intended winning strategy.
- **Calibrate the size.** Measure with `len(raw) // 4` ≈ tokens after generating data:
  - at v3 scale: ≥ ~100k tokens (echoing it natively into context is fatal under a ~70k-token response budget);
  - at v0 scale: ≤ ~20k tokens (survivable but expensive).
  Tune by selecting/dropping joined columns until both bounds hold. Flat one-record-per-row JSON (ids + names + the key metrics) usually lands right; full nested dumps are far too big.
- Keep all existing paginated/per-entity tools available as the safe alternative.

### 4. Rewrite `verify()`

Port the SOURCE `verify()` computation logic 1:1, changing only the tool-consumption layer: unwrap envelopes, `json.loads` JSON strings, `ast.literal_eval` repr strings, parse `key: value` text, walk nested properties, follow `has_more`/`next_cursor` pagination, build JSON-string filters, construct nested write payloads. For M5 envs, `verify()` should consume the bulk export once, in memory. The tool-call floor still applies: ≥ 15 `self.tools[...]` calls at v0 scale.

### 5. Test, propagate, document

1. In `v3/`: run `python data.py --db_path data.db --workspace workspace`, then construct the env and assert `verify()` returns reward 1.0. Debug the surface (not the ground truth) until it does.
2. Negative-path smoke tests for each mutator you applied, e.g.: malformed JSON in an M1 filter (expect `invalid_json` with line/column/char), a dict passed where a JSON string is required, an M4 payload missing `parent` then missing the required property (expect the layered messages, one at a time), an M3 lookup with a nonexistent id (expect the 404 error dict).
3. For M5: print the measured export token estimate at v0 and v3 and confirm the calibration bounds.
4. Copy `v0/env.py` to `v1/ v2/ v3/`. `diff v0/env.py v_n/env.py` must be empty. Without M0, `data.py` and `prompt.md` must be byte-identical to SOURCE (per-version `data.py` differs only in its original SCALE block). With M0, copy the edited `v0/prompt.md` to all versions, and propagate the edited `v0/data.py` to `v1/ v2/ v3/` while preserving each version's original `SCALE` block — after propagation, per-version `data.py` files must differ from each other only in `SCALE`.
5. Remove runtime artifacts (`data.db`, `workspace/`, `__pycache__`) from every version directory.
6. Append a `## Hardening (<mutators>)` section to `README.md`: which mutators were applied, the per-tool return-shape map, the error contract, M5 size measurements, and the v0/v3 verify results.

### 6. Final checklist

- [ ] Without M0: `data.py` byte-identical to SOURCE in all four versions and `prompt.md` unchanged (M4 exception only). With M0: `data.py` changes are additive policy documents only (SCALE blocks preserved per version), the prompt's deliverable contract survives verbatim, and the completeness audit maps every `step()` criterion to a prompt paragraph or workspace document.
- [ ] `step()` ground truth and criteria unchanged (M4 DB-state exception only).
- [ ] Every assigned mutator clearly present; tool descriptions do not leak encoding/parsing recipes.
- [ ] Success and error responses share no keys; tools never raise.
- [ ] `verify()` == 1.0 at v3 scale (and spot-check v0); ≥ 15 tool calls at v0.
- [ ] `diff v0/env.py v_n/env.py` empty for v1–v3; no runtime artifacts left.
