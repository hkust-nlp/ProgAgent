## Task Topic

Dynamic route optimization for same-day deliveries cross-references real-time courier GPS locations, incoming order volumes, live traffic API data, vehicle capacity constraints, and customer delivery windows to generate an updated driver assignment manifest every 15 minutes.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

Scaling ratios: rows grow as 1×, 2×, 4×, 8× of the v0 base (50). Workspace files grow as base, base+N, base+2N, base+3N where N = 8.

**Structural dimensions used:**

- **Information Scattering**: Order logistics data (location, timing, weight) lives in the database and is accessible only through tools, while handling classifications (STANDARD, FRAGILE, COLD_CHAIN, HEAVY, OVERSIZED, HAZMAT) are distributed across workspace batch CSV files. Vehicle compatibility rules, SLA thresholds, zone adjacency, and dispatch policy each reside in separate workspace config files of different formats (JSON, YAML, CSV, MD).

- **Conditional Constraints**: Assignment eligibility depends on multi-table business rules — a courier's vehicle type must support the order's handling code (vehicle compatibility config), the courier's remaining capacity must accommodate the order's weight and parcel count (courier table + cumulative tracking), and the estimated delivery time must fall within the SLA deadline derived from the customer's membership tier (customer table) crossed with the order's priority level (SLA config).

- **Multi-Hop Reasoning**: The dependency chain for each assignment is: pending order (tool) → customer tier (tool) → SLA deadline (workspace CSV) → handling code (workspace batch CSV) → vehicle compatibility (workspace YAML) → eligible couriers (tool) → traffic estimate (tool) → speed factor (workspace YAML) → cross-zone penalty (workspace JSON) → final estimated delivery time.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (manifest_format=10, order_completeness=20, vehicle_compatibility=20, capacity_constraints=15, sla_compliance=15, summary_statistics=20)
- Source-access: step-6 escalation. The first solver run scored 0.95 because the regex extracting summary stats in `step()` (e.g., `r"average\s+(?:estimated\s+)?delivery\s+time[:\s]*([\d.]+)"`) only allowed whitespace/colon between the phrase and the number, rejecting natural phrasings like "average estimated delivery time across all assigned orders: 18.7 minutes" — wording that the prompt itself encourages. The solver answer was correct; the parser was over-strict. Opened `v3/env.py` to confirm and patched the four summary-stat regexes in `v0/env.py` to use `[^\d\n]*?` between the keyword phrase and the captured number, then propagated to v1/v2/v3 byte-identically. Re-ran solver: reward 1.0.
- Structural integrity, prompt quality, and scale invariance all clean. No other issues found.
