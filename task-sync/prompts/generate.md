You can use the conda environment `eval` to build a complex Agent task. The task topic is:

**{TOPIC}**

The Agent reads `prompt.md` as instruction and completes the task by calling tools defined in `env.py` and reading files in the `workspace`.

You are building the same task realized at multiple data scales (`v0` → `v3`); difficulty is introduced only by scale.

---

### 1. Build the Data Generation Script `data.py`

Create `v0/data.py` to initialize the database and generate workspace files.

- **Python Libraries**: `numpy`, `pandas`, `faker`, `sqlite3`
- **Global Configuration**: All random seeds must be set to `42`.
- **Execution**: initialize the database and workspace with
  ```bash
  python data.py --db_path data.db --workspace workspace
  ```

#### Scale Parameters:

Declare a `SCALE` dict at the top of `data.py`. All row counts and file counts must be read from this dict. No hard-coded numbers elsewhere.

Pick v0 base values that match the task's per-record payload. The defaults below fit structured-record tasks; adjust if each record is unusually large (long text, multi-page document) or small:

```python
SCALE = {
    "rows_per_table": 100,        # v0 base; v1 = 2×, v2 = 4×, v3 = 8×
    "num_workspace_files": 10,    # v0 base; v1 = +N, v2 = +2N, v3 = +3N  (N = base)
}
```

`num_workspace_files` counts only the data/content files that grow with scale. Task-inherent fixed files (policy/config/rule documents that do not scale) are produced by `data.py` independently and are not part of this dict. The v0→v3 ratios are fixed across all tasks; only the v0 base is task-specific. Concrete v1/v2/v3 values are derived in Step 4.

Two boundaries:

- Two boundaries:

- v0 must already make the task meaningful. Concretely, `verify` at v0 SCALE must issue **at least 15 tool calls** to produce the solution.
- v3 must apply real processing pressure, not a size an LLM can brute-memorize without orchestration.

#### Database Construction:
1. Design at least 4 data tables based on the task, each containing multiple columns.
2. Use Python code to generate corresponding data for each table and insert it into the database. Each table's row count must be no less than `SCALE["rows_per_table"]`, with foreign key relationships between tables.
3. Complete the database initialization in the `main` function and save it to `db_path`.
4. The database is **not** directly accessible to the Agent. It can only be queried through the tool functions defined in `env.py`.

#### Workspace Construction:
1. Use Python code to batch-generate files of various types in the `workspace` directory, including `.json`, `.txt`, `.csv`, `.yaml`, `.md`, etc.
2. Files should be primarily based on database content but may include additional information. The information obtainable from files and from tool calls must be complementary and non-overlapping; solving the task must require both. Some files MUST be semi-structured or completely unstructured. For example: **`.md` files**: Generate complex reports that mix bulleted lists, and Markdown tables. 
3. Specific decision parameters (thresholds, multipliers, coefficient tables, tier mappings) belong in workspace configuration files, not in `prompt.md`. Plain-language rule statements (e.g., "process in descending severity order") can stay in the prompt.
4. The workspace MUST contain no fewer than `SCALE["num_workspace_files"]` scalable data files, plus any task-inherent fixed policy/config files; together they span at least 4 formats and constitute a complex environment. As `num_workspace_files` grows (v0 → v3), scale both the *number* of these unstructured files and the *internal complexity*.

---

### 2. Build the Environment `env.py`

Implement `v0/env.py`. `env.py` and `prompt.md` will be copied byte-for-byte to v1/v2/v3; only `data.py`'s `SCALE` block differs across versions. A single implementation must therefore handle every scale from v0 to v3 without special-casing.

1. **Implement `Task_Env` strictly following the template below (always keep parameters and comments unchanged).** The `@tool` decorator stores metadata on each method; `__init__` collects all decorated methods into `self.tools` once, serving both tool dispatch (`self.tools[tool_name]`) and definition export (`get_assistant_tools`).

```python
# --- Define this decorator at the top of env.py, keep unchanged ---
from typing import Tuple, Dict, List, Any

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
        }
        return func
    return decorator


class Task_Env:
    def __init__(self, db_path: str, workspace: str):
        """
        Init env.
        Args:
            db_path: Path to the database file.
            workspace: Path to workspace directory for file isolation.
        """
        self.db_path = db_path
        self.workspace = workspace

        # Auto-collect all @tool decorated methods
        self.tools = {}
        for name in dir(self):
            method = getattr(self, name, None)
            if callable(method) and hasattr(method, "_tool_info"):
                self.tools[name] = method

    # --- keep this implementation unchanged ---
    def get_assistant_tools(self) -> List[Dict[str, Any]]:
        """
        Get tool definitions in OpenAI function calling format.

        Returns:
            List of tool definitions compatible with OpenAI API
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": method._tool_info["description"],
                    "parameters": method._tool_info["parameters"],
                },
            }
            for name, method in self.tools.items()
        ]

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        pass

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        This method proves end-to-end solvability. It must:
          - Use self.tools[name](**params) to gather data (no direct DB queries).
          - Read files from self.workspace as needed.
          - Write all required deliverables to self.workspace.
          - Construct the final action string.
          - Return self.step(action).
        """
        pass
```

2. Add the task's tool methods inside `Task_Env`, keeping each tool single-purpose. Tools should require the Agent to orchestrate calls in code and must not return unbounded full-table results.

Tool methods use the `@tool` decorator for registration. Example:

```python
# --- Tool Method Example (for format reference only, do not copy directly) ---
@tool(
    description="Retrieves current weather for the given location.",
    parameters={
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City and country e.g. Bogotá, Colombia"
            },
            "units": {
                "type": "string",
                "enum": ["celsius", "fahrenheit"],
                "description": "Temperature units for the response"
            }
        },
        "required": ["location", "units"]
    }
)
def get_weather(self, location: str, units: str):
    # implementation
    ...
```

---

### 3. Task Design

#### 3.1 Task Definition (`prompt.md`)

Write the task description `v0/prompt.md` based on the existing data and tools.

- **Tone & Style**: Describe a difficult task using realistic, natural, fluent prose: no title, no tool descriptions, no procedural instructions. Let the requirements emerge through flowing paragraphs.

- **Formatting Constraints**:
  - Do NOT use bold section headers or titles. Use paragraph breaks and natural transitions ("Separately," "Once that is done," "On top of this") to move between topics.
  - Do NOT use numbered or bulleted lists for deliverable requirements or final-response items. Weave them into prose.
  - Do NOT place a title or heading at the top of the file.
  - Express computation logic in natural language. No code block.

- **Core Elements**:
  - The Agent uses relative paths based on the `workspace`. The word "workspace" and specific source data filenames from the workspace should not appear in `prompt.md`. However, output deliverables must have explicit naming requirements (e.g., "save the result as `report.csv`") and specify the exact field/column names expected in the output (e.g., "the CSV should contain columns: `company_name`, `revenue`, `growth_rate`").
  - The task must require both reading files from the `workspace` and calling tools to complete. It should require multiple retrieval, filtering, and cross-referencing steps to reach the final result.
  - The wording must be scale-invariant. Refer to items as "all pending claims" or "every adjuster", never with an absolute count like "40 pending claims". The same prompt is shared across v0..v3.
  - Task constraints must be unambiguous.
  - `prompt.md` must contain sufficient information for the task: an agent with only `prompt.md` and tool descriptions (no access to `env.py` source code) must be able to achieve full reward.

- **Structural Dimensions**: the task must exhibit at least two of the following.
  - **Conditional Constraints**: eligibility depends on business rules involving 2–3 tables/columns (e.g., "severity > threshold requires senior certification"); thresholds live in workspace config files.
  - **Deliverable Constraints**: the output format is nailed down: precision (`3.00` not `3`), delimiter (`, ` not `,`), sort keys with tie-breakers, column order, file name.
  - **Information Scattering**: task-critical fields are split across sources. Half of a record sits in a CSV, the rest is only reachable via tool calls.
  - **Multi-Hop Reasoning**: at least one dependency chain of length ≥ 3, such as `Tool A → File B → Tool C → compute`.

#### 3.2 Task Evaluation (`Task_Env.step`)

Based on `prompt.md`, implement the `Task_Env.step` function in `env.py`.

1. **Evaluation Criteria**: Design at least 5 eval criteria (min 10 pts each, harder ones scored higher).
2. **Evaluation Source**: The `step` function can access `data.db`, all workspace files, and `data.py` to calculate ground truth. It must work at any scale; do not hard-code row or file counts.
3. **Evaluation Logic**: Eval criteria must include both **Workspace checks** and **Response checks**. The `step` function should perform strict, precise matching against the ground truth. If `prompt.md` specifies an exact format, the evaluation must enforce it.
4. **Return Format**: The `step` function returns `(reward, info)`, where `reward` is a dense float in 0.0–1.0 (`total_score / max_score`), not a binary 0/1. `info` is a structured dict with the following format:

```python
info = {
    "eval_criteria": {
        "criterion_name": {
            "passed": True/False,
            "score": <points_earned>,
            "max_score": <max_points>,
            "reason": "<brief failure hint, optional, only when passed=False>"
        },
        ...
    },
    "total_score": <sum of earned scores>,
    "max_score": <sum of max scores>,
}
```

#### 3.3 Task Verification (`Task_Env.verify`)

Implement the `verify` method in `Task_Env` to prove end-to-end solvability. Run verification with:

```bash
python -c "
import subprocess, sys
subprocess.run([sys.executable, 'data.py', '--db_path', 'data.db', '--workspace', 'workspace'], check=True)
from env import Task_Env
env = Task_Env(db_path='data.db', workspace='workspace')
reward, info = env.verify()
print(info)
assert reward == 1.0, f'verify failed: reward={reward}'
"
```

Run verification against the v3 scale: temporarily set `v0/data.py`'s `SCALE` to its v3 values (`rows_per_table = 8 × base_rows`, `num_workspace_files = base_files + 3N` where `N = base_files`), run the command above and confirm `reward == 1.0`, then revert `SCALE` to the v0 column. Passing at the largest scale implies the smaller ones hold.

**Requirements:**

1. The `verify` method must derive its solution **solely from information available to a real Agent**:
   - Tool schemas from `self.get_assistant_tools()`.
   - Tool results from `self.tools[tool_name](**params)`.
   - Files in `self.workspace`.

   **Forbidden:** direct database queries, reading `step` source, or using any internal state not exposed through tools.

2. **Produce all deliverables**: Write every output file required by `prompt.md` into `self.workspace`, and construct a complete `action` string containing all required results and conclusions.

3. **Verification**: Call `return self.step(action)` and ensure reward == 1.0. If verification fails, fix `step` or `prompt.md` and re-run.

4. **Tool-call floor (v0 granularity check)**: At the v0 SCALE, `verify` must issue **at least 15 calls through `self.tools[...]`** before reaching `self.step(action)`.  If it finishes in fewer, the tools are too coarse-grained, tools must be split (add pagination, switch to by-id access, or break one tool into several single-purpose tools).
---

### 4. Replicate to v1, v2, v3

Once `v0/` passes verification at the v3 scale, produce the remaining three versions:

```bash
for v in v1 v2 v3; do
  mkdir -p $v
  cp v0/env.py    $v/env.py
  cp v0/prompt.md $v/prompt.md
  cp v0/data.py   $v/data.py
done
```

Then edit only the `SCALE` dict at the top of each `v_n/data.py`:

| Version | rows_per_table  | num_workspace_files |
|---------|-----------------|---------------------|
| v0      | `base_rows`     | `base_files`        |
| v1      | `2 × base_rows` | `base_files + N`    |
| v2      | `4 × base_rows` | `base_files + 2N`   |
| v3      | `8 × base_rows` | `base_files + 3N`   |

where `base_rows` and `base_files` are the v0 values you declared in Step 1.1, and `N = base_files`.

`diff v0/env.py v_n/env.py` must be empty; same for `prompt.md`. Only `data.py` differs, and only in the `SCALE` block.

Final directory:

```
./
├── README.md
├── v0/   { data.py, env.py, prompt.md }
├── v1/   { data.py, env.py, prompt.md }
├── v2/   { data.py, env.py, prompt.md }
└── v3/   { data.py, env.py, prompt.md }
```

`README.md` has two sections: `## Task Topic` (copied from `{TOPIC}`) and `## Version Overview` (the SCALE table and a note on which structural dimensions the task uses).
