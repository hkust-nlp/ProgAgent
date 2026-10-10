## Task Topic

Identify travelers with high-risk itineraries prone to disruption. Correlate flight booking PNRs, real-time flight status feeds, historical on-time performance data, and alternative route availability to flag itineraries with tight connections or unreliable carriers, outputting a proactive rebooking list for customer service.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

Structural dimensions used by this task:

- **Conditional Constraints**: Risk scoring depends on multi-source business rules — connection tightness thresholds from a YAML config, carrier OTP cutoffs and vulnerability multipliers from a JSON config, and rebooking priority tiers from a policy document. Eligibility for the rebooking list requires the adjusted score to meet or exceed the high-risk threshold.
- **Information Scattering**: Critical data is split across database tools and workspace files. Booking segments and real-time flight statuses are only accessible via tool calls, while historical carrier OTP rates, minimum connection times, risk scoring weights, vulnerability multipliers, and passenger special-needs flags live exclusively in workspace files across four formats (JSON, CSV, TXT, YAML).
- **Multi-Hop Reasoning**: The risk calculation requires a dependency chain of length ≥ 3: list bookings (tool) → get segments per PNR (tool) → get flight status per segment (tool) → read connection rules + carrier OTP + vulnerability from workspace files → compute composite risk score → search alternatives (tool) → look up traveler loyalty tier (tool) → assign rebooking priority from policy document.

## Harness Report

- v3 reward: 1.0 (total_score 110/110)
- Eval criteria count: 8 (file_valid_csv, correct_columns, recall_high_risk, precision_no_false_positives, risk_score_accuracy, priority_accuracy, sort_order, response_summary)
- Source-access: clean — solver written from `v3/prompt.md` + `get_assistant_tools()` only; no escalation to `env.py`/`data.py` was needed.
- Structural integrity: passed; `env.py` and `prompt.md` byte-identical across v0..v3, only `SCALE` differs in `data.py` (v0=50/8, v1=100/16, v2=200/24, v3=400/32, matching the rows ×1/2/4/8 and files +0/+N/+2N/+3N convention with N=8).
- Issues found: none. Prompt-step alignment, scale invariance, and prompt formatting (no headers, no lists, prose-only computation, scale-invariant wording) all check out.
- Fixes applied: none.
- Blockers: none.
