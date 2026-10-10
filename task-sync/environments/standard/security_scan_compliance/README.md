## Task Topic

Validate compliance with mandatory security scans by cross-referencing pull request commits, CI pipeline execution logs, security tool findings databases, and merge approval timestamps to flag unreviewed vulnerabilities, producing a remediation backlog.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Compliance tier assignments live in workspace JSON metadata files, scan requirements live in a YAML policy file, reviewer authorizations live in a CSV file, while actual PR details, commits, pipeline runs, findings, and approvals are only accessible through tool calls. No single source contains all the information needed to determine a violation.
- **Multi-Hop Reasoning**: Determining a violation requires chaining PR metadata (tier) → scan policy (required scans per tier) → tool: list PRs → tool: get commits → tool: get pipelines → tool: get findings → authorized reviewers CSV → compare timestamps with merge approval. This is a dependency chain of length 5+.
- **Conditional Constraints**: Whether a scan is required depends on the PR's compliance tier; whether a finding needs review depends on its severity and the tier's review requirements; whether a reviewer is authorized depends on their max severity certification compared to the finding's severity.

## Harness Report

- **v3 reward**: 1.0 (100/100)
- **Eval criteria count**: 7 (`backlog_file_structure` 10pt, `non_compliant_pr_identification` 20pt, `violation_type_accuracy` 20pt, `priority_assignment` 15pt, `backlog_sort_order` 10pt, `summary_statistics` 15pt, `violation_count_accuracy` 10pt)
- **Source-access escalation**: clean for finding the contract; one Section 6 escalation read of `v3/env.py` was needed to confirm semantics around findings on skipped pipelines (see below).
- **Issue 1 — solver vs `step` semantics for skipped pipelines**: The prompt says "A scan counts as having been performed... only if at least one pipeline run completed with a status other than skipped" but also "for every pipeline run that corresponds to a security scan type, retrieve the findings it produced." `_compute_ground_truth` follows the literal latter reading and includes findings from `status=='skipped'` pipelines (data.py does emit findings on some skipped pipelines). The solver's first attempt skipped them and undercounted by 57 violations. **Fix**: solver was aligned to include findings from skipped security pipelines; no env edit needed — the prompt's "every pipeline run" wording is consistent with `step()`.
- **Issue 2 — none beyond the above**. Structural integrity, byte-identical env.py/prompt.md across v0..v3, and SCALE-only diffs in data.py all hold.
- **Blockers**: none.

