# multi_tenant_billing_reconciliation

Reconcile billed amounts against actual consumption for multi-tenant commercial buildings. For each tenant, utility type, and billing period the agent must apply the tenant's lease clause (sub_metered, pro_rata_sqft, pro_rata_units, or fixed) together with master meter readings, sub-meter readings, common-area allocation parameters, and tariff rates to compute the correct charge, compare it against the historical equal-share billing, and output a corrected chargeback ledger.

## v0 → v3 progression

| Version | num_buildings | tenants_per_building | Total tenants | Total rows (tenants × 3 utils × 2 periods) | Workspace files |
|---------|--------------|---------------------|---------------|---------------------------------------------|-----------------|
| v0      | 4            | 5                   | 20            | 120                                         | 8               |
| v1      | 8            | 5                   | 40            | 240                                         | 16              |
| v2      | 16           | 5                   | 80            | 480                                         | 24              |
| v3      | 32           | 5                   | 160           | 960                                         | 32              |

Row count doubles v0→v1 (2×), v0→v2 (4×), v0→v3 (8×). Workspace files scale +8/+16/+24 from v0.

## Harness Report

**v3 reward:** 1.0 (100/100)

**Eval criteria (7 total):**

| Criterion | Points | Description |
|-----------|--------|-------------|
| file_structure | 15 | `chargeback_ledger.csv` exists, has all 11 required columns, rows sorted by building_id → tenant_id → utility_type → period |
| coverage | 10 | All (tenant, utility, period) combinations present |
| metered_ca_accuracy | 10 | `metered_charge` and `ca_charge` correct within $0.02 tolerance for every row |
| total_charge_accuracy | 20 | `total_charge` correct within $0.02 for every row |
| original_billed_accuracy | 15 | `original_billed` matches historical billing records |
| adjustment_accuracy | 20 | `adjustment = total_charge − original_billed` correct |
| response_summary | 10 | Final response names every tenant whose adjustment exceeds 5% of original billed |

**Issues found and fixed:**

1. **gen session did not complete** — The `multi_tenant_billing_reconciliation` task directory existed but was empty. The harness built the task from scratch: designed DB schema, data generation (`data.py`), evaluation environment (`env.py`), and task description (`prompt.md`).

2. **Missing `metered_ca_accuracy` criterion (Section 3)** — The initial `step()` verified `total_charge` but did not separately verify `metered_charge` and `ca_charge`, which `prompt.md` explicitly defines. Added a dedicated criterion (10 pts) and redistributed points from `total_charge_accuracy` (30 → 20 pts), keeping the overall max at 100.

3. **Ambiguous "units" CA allocation wording (Section 4)** — `prompt.md` said "one divided by the total number of tenants in the building multiplied by the total common-area cost", which could be parsed as either `(1/n)×cost` or `1/(n×cost)`. Rewritten to "the total common-area cost divided equally among all tenants in the building".

4. **v3/workspace/ stale artifact (Section 1)** — Found residual workspace directory from a prior run in v3; removed.

All fixes applied to `v0/` first and propagated byte-for-byte to `v1/`, `v2/`, `v3/`. Final `diff` confirms `env.py` and `prompt.md` are identical across all four versions; `data.py` differs only in the `SCALE` dict.
