## Task Topic

Detect fraudulent credit card applications by analyzing application form data, credit bureau scores, device fingerprinting logs, and known fraudster databases to flag high-risk submissions, producing a rejection roster with reason codes.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 6                   |
| v1      | 100           | 12                  |
| v2      | 200           | 18                  |
| v3      | 400           | 24                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N = 6.

### Structural Dimensions

- **Information Scattering**: Application submission metadata (self-reported income, document status, referral codes, submission channel) lives in workspace batch CSVs, while verified income, credit bureau data, device fingerprints, and fraudster matches are only accessible through tool calls. Scoring thresholds and fraud-pattern lists reside in separate workspace config files (YAML, JSON, CSV). Solving the task requires combining all sources.
- **Conditional Constraints**: Rejection depends on accumulating risk points from up to ten distinct factors (R01–R10), each with its own threshold or condition drawn from 2–3 data sources. For example, R03 requires both a VPN/proxy flag (device tool) and a high requested limit (applicant tool), compared against a threshold in the YAML policy file.
- **Multi-Hop Reasoning**: Several factors require multi-step resolution, e.g. R02: read self-reported income from batch CSV → call applicant lookup for verified income → compute discrepancy ratio → compare against policy threshold. R04: call fraud screen → get severity of best match → look up severity-to-points mapping in policy → add points.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (`roster_format`, `correct_app_ids`, `correct_risk_scores`, `correct_reason_codes`, `correct_sorting`, `response_rejection_count`, `response_rejection_rate`)
- Source-access: clean — solver written using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`; no step-6 escalation needed.
- Structural integrity: passed. v0 vs v1/v2/v3 differ only in the `SCALE` block of `data.py`; `env.py` and `prompt.md` are byte-identical across versions. SCALE ratios verified (rows ×1/2/4/8 = 50/100/200/400; files +0/N/2N/3N = 6/12/18/24, N=6).
- Issues found: none. Solver passed all 7 criteria on first end-to-end submission at v3 scale.
- Fixes applied: none.
- Cleanup: removed `data.db`, `workspace/`, `__pycache__/` from every `v_n/`; removed `/tmp/solve_credit_card_application_fraud_detection.py`.
