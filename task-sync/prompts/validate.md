You have just built a task at `v0/` and copied it to `v1/..v3/`. Your job is to verify the four versions hold together and fix any issues. You can use the conda environment `eval`.

Work through the sections below in order. If any check fails, fix it in `v0/` first (the single source of truth), re-propagate to `v1/..v3/`, then re-run the relevant check.

---

### 1. Structural Integrity

Confirm without opening any Python files:

1. The top-level directory contains exactly `README.md` and `v0/`, `v1/`, `v2/`, `v3/`. No stale databases, workspace folders, bytecode caches, or loose scripts.
2. Each `v_n/` contains exactly `data.py`, `env.py`, `prompt.md`. No `data.db`, `workspace/`, `__pycache__/`.
3. `diff v0/env.py v_n/env.py` returns no output for v1, v2, v3. Same for `prompt.md`. Only `data.py` differs.
4. Each `v_n/data.py` differs from the others only in the `SCALE` dict at the top.

Use `ls` and `diff` only.

If any violation is found, fix `v0/` first, then re-copy `env.py` / `prompt.md` / `data.py` to `v1/..v3/` and re-edit only the `SCALE` block in each.

---

### 2. Solvability Verification at v3 Scale

Verify the task is solvable on the hardest version

The point of this section is to confirm the task can be solved using only the same information any evaluated agent gets — `prompt.md` plus the public `Task_Env` interface. **You must write your own solver and submit its answer via `env.step(action)`. Do NOT call `env.verify()`, and do NOT read `env.py` (or `data.py`) until step 6 below explicitly permits it.**

**Source-access rule for this section:** the only source file you may read is `v3/prompt.md`. Every other source file (`env.py`, `data.py`, `README.md`, the contents of `v0/v1/v2/`) is off-limits at this stage — do not `cat`, `Read`, `grep`, or otherwise inspect them. Runtime artifacts produced by `data.py` (`data.db`, files under `workspace/`) are fair game; you may inspect them with `sqlite3`, `pandas`, file reads, etc.

**Default output location:** unless `prompt.md` explicitly states otherwise, all deliverable files (CSVs, JSONs, reports) are written into `workspace/`. This is a harness convention — `prompt.md` does not need to spell it out, and the absence of an explicit path is NOT an issue to flag in the Harness Report.

1. `cd v3`.
2. Run `python data.py --db_path data.db --workspace workspace`. If it errors, fix `data.py` in `v0/`, re-propagate, and retry. 
3. **Discover the public interface only — do not open `env.py`.** To learn what helper tools the env exposes, run:
   ```bash
   python -c "
   from env import Task_Env
   env = Task_Env(db_path='data.db', workspace='workspace')
   import json; print(json.dumps(env.get_assistant_tools(), indent=2))
   "
   ```
   This is the same tool list a real agent would see. Combined with `v3/prompt.md`, it is the entire spec you may work from.
4. **Write a python solver.** Place it outside `v3/` (e.g. `/tmp/solve_<task>.py`) so the env directory stays clean. The solver should:
   - Construct `Task_Env(db_path='data.db', workspace='workspace')`.
   - Read `data.db` / `workspace/` as the prompt directs (using `sqlite3`, `pandas`, file IO, or the env's helper tools).
   - Produce every deliverable the prompt specifies (output files with the exact names, columns, precision, and sort order described).
   - Build the final response text exactly as `prompt.md` requires.
   - Call `reward, info = env.step(final_response)` and print both.
5. **If `reward == 1.0`, the task is solvable and `step` agrees with the prompt — proceed to Section 3.**
6. **If `reward < 1.0`, debug in this order, and only escalate when the previous step is exhausted:**
   1. Assume your solver is wrong. Re-read `info["reason"]` and re-read the relevant part of `v3/prompt.md`. Adjust the solver. Do NOT yet open `env.py`.
   2. If, after an honest re-reading, you are confident the solver matches the prompt's requirements but `step` still rejects it, you may now open `v3/env.py` to inspect `step()`.
   3. Diagnose whether the bug is in `step()` or in `prompt.md` (ambiguous wording). Fix the root cause. Do not weaken `step()` just to accept the solver's output, and do not contort the solver to match buggy `step()` logic.
   4. Any edit to `env.py` or `prompt.md` must be made in `v0/` first and re-propagated to `v1/v2/v3`; rerun `diff` to confirm the byte-for-byte invariant.
7. Re-run the solver. Repeat until `reward == 1.0`. The terminal state must be: a solver that succeeded using only `prompt.md` + `get_assistant_tools()`.

---

### 3. Env Quality

Read `v3/prompt.md` and `v3/env.py`'s `step` function side by side.

Prompt-step alignment:
1. Coverage: every eval criterion scored in `step` corresponds to a requirement explicitly stated in `prompt.md`. No hidden criteria.
2. Completeness: every deliverable or conclusion required by `prompt.md` is evaluated by at least one criterion in `step`.

Evaluation strictness:
3. Precise matching: if `prompt.md` specifies a format (column names, numeric precision, sort order), `step` enforces it.
4. No over-normalization: `step` does not blindly lowercase, strip whitespace, or remove punctuation before comparing.
5. No over-strict regex: `step` does not reject correct answers due to formatting differences not specified in `prompt.md` (e.g., failing on `3.0` vs `3.00` when no precision is prescribed).

Scale invariance:
6. `step` derives ground truth from the current `data.db` / workspace / `data.py`. No hard-coded row counts, file counts, or data-distribution assumptions.
7. The number and weights of eval criteria are the same across v0..v3 (enforced by the byte-for-byte invariant).

If any issue is found, fix in `v0/` and re-propagate. Rerun the v3 verify.

---

### 4. prompt.md Quality

Formatting:
1. No title or heading at the top of the file.
2. No bold section headers. Transitions use natural prose.
3. No numbered or bulleted lists for deliverables or final-response items. Weave them into prose.
4. Computation logic in natural language, not code.

Content:
5. No tool names, source data filenames, or `env.py` internals mentioned. Output filenames like `report.csv` are fine.
6. Output deliverables have explicit naming and specify exact field/column names.
7. Task constraints are unambiguous.
8. Scale-invariant wording: no absolute counts like "40 pending claims". Use "all pending claims" or "every X".

If any issue is found, fix in `v0/prompt.md` and re-propagate.

---

### 5. Final Clean-Up and Report

1. Remove runtime artifacts from every `v_n/`: `data.db`, `workspace/`, `__pycache__/`.
2. Confirm the top-level directory structure:
   ```
   ./
   ├── README.md
   ├── v0/
   ├── v1/
   ├── v2/
   └── v3/
   ```
3. Append a `## Harness Report` section to `README.md`. Record the v3 reward, number of eval criteria, and every issue found and how it was fixed.
