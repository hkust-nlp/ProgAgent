## Task Topic

Ensure labor law compliance by analyzing employee time-clock punches, union contract break rules, machine energy usage logs, and mandatory skill-refresher training schedules to produce a weekly shift report flagging potential violations.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

The task exhibits the following structural dimensions:

- **Conditional Constraints**: Violation detection depends on cross-referencing multiple tables and configuration files. Break violations require matching employee union codes to contract rules with specific hour thresholds; training violations require checking department-specific skill requirements against per-employee certification expiry dates; energy violations require comparing machine usage against type-specific kWh thresholds.

- **Information Scattering**: Task-critical data is split across database tables (employees, time punches, break records, training records) accessible only via tools, and workspace files in multiple formats (JSON union rules, YAML energy thresholds, YAML severity config, CSV training requirements, CSV machine energy logs, Markdown supervisor notes). No single source is sufficient to detect all violation types.

- **Multi-Hop Reasoning**: Detecting break violations requires a chain of at least length 3: list employees (Tool) -> get time punches per employee (Tool) -> get break records per punch (Tool) -> compare against union contract rules (File). Training violations similarly require: employee lookup (Tool) -> training records (Tool) -> department requirements (File) -> date comparison. Energy violations cross from workspace CSV files to employee lookup tools to threshold configuration files.

## Harness Report

**v3 solver reward: 1.0 (100/100)**

**Eval criteria (6 total):**

| Criterion | Max pts | Description |
|-----------|---------|-------------|
| report_file_exists | 10 | `weekly_violation_report.csv` present in workspace |
| report_columns | 10 | All 6 required columns present |
| violation_count | 20 | Reported count within tolerance of ground truth (1973 at v3) |
| violation_type_coverage | 20 | All 8 violation types represented |
| violation_matching | 25 | F1-score on (employee_id, violation_type, violation_date) triples |
| response_summary | 15 | Summary contains correct total, type breakdown, per-type counts, and top-5 employee IDs |

**Issues found and fixed:**

1. **Completeness gap in criterion 6 (env.py)** — The response summary criterion originally checked 3 sub-conditions (total count, violation type names, per-type counts) but omitted verification of the top-5 employee list, which `prompt.md` explicitly requires. Fixed by adding a 4th sub-check that verifies at least 3 of the top-5 employees by violation count (by employee ID) appear in the response. `total_checks` updated from 3 to 4. Change made in `v0/env.py` and propagated to `v1–v3`. Reward remained 1.0 after the fix.
