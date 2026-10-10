"""
Multi-cloud infrastructure spend reconciliation – Data Generator.
Generates SQLite DB + workspace files for the showback / chargeback task.
"""
import argparse
import os
import json
import sqlite3
import math
import numpy as np
import pandas as pd
from faker import Faker

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 100,       # v0 base; v1=2×, v2=4×, v3=8×
    "num_workspace_files": 10,   # v0 base; v1=+N, v2=+2N, v3=+3N  (N=base)
}

# ── Fixed domain constants ───────────────────────────────────────────────────
CLOUD_PROVIDERS = ["AWS", "Azure", "GCP"]
DEPARTMENTS = [
    "DataScience", "Engineering", "Finance",
    "HumanResources", "Marketing", "Operations",
]
BASE_SUB_DEPARTMENTS = {
    "Engineering":    ["Frontend", "Backend", "DevOps", "QA", "Security"],
    "Marketing":      ["Digital", "Content", "Events", "Analytics"],
    "Finance":        ["Accounting", "Treasury", "Tax", "Audit"],
    "Operations":     ["Infrastructure", "Logistics", "Procurement", "Facilities"],
    "DataScience":    ["ML", "Analytics", "DataEngineering", "Research"],
    "HumanResources": ["Recruiting", "Training", "Compensation", "Benefits"],
}
SERVICE_TYPES = [
    "Compute", "Storage", "Database", "Networking",
    "Analytics", "ML", "Security", "Monitoring",
]
REGIONS = {
    "AWS":   ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"],
    "Azure": ["eastus", "westeurope", "southeastasia", "centralus"],
    "GCP":   ["us-central1", "europe-west1", "asia-east1", "us-east1"],
}
INSTANCE_TYPES = {
    "AWS":   ["m5.large", "m5.xlarge", "c5.2xlarge", "r5.large", "t3.medium"],
    "Azure": ["Standard_D2s_v3", "Standard_D4s_v3", "Standard_E2s_v3", "Standard_B2ms"],
    "GCP":   ["n1-standard-2", "n1-standard-4", "n2-standard-2", "e2-medium"],
}
N_ACCOUNTS = 18  # 6 per cloud provider, round-robin across departments


def main(db_path: str, workspace: str) -> None:
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    n_resources = SCALE["rows_per_table"]
    n_days = SCALE["num_workspace_files"]
    n_ri = max(SCALE["rows_per_table"] // 3, 20)

    # ── Dates (January 2025 onwards) ────────────────────────────────────────
    dates = pd.date_range("2025-01-01", periods=n_days, freq="D")
    date_strs = [d.strftime("%Y-%m-%d") for d in dates]

    # ── Accounts ────────────────────────────────────────────────────────────
    accounts = []
    for i in range(N_ACCOUNTS):
        cloud = CLOUD_PROVIDERS[i % len(CLOUD_PROVIDERS)]
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        accounts.append({
            "account_id": f"ACC-{cloud[:3].upper()}-{i + 1:03d}",
            "cloud_provider": cloud,
            "department": dept,
            "account_name": f"{dept}-{cloud}-{i + 1}",
        })

    # ── Resources ───────────────────────────────────────────────────────────
    resources = []
    for i in range(n_resources):
        acct = accounts[i % N_ACCOUNTS]
        cloud = acct["cloud_provider"]
        resources.append({
            "resource_id": f"RES-{i + 1:05d}",
            "account_id": acct["account_id"],
            "cloud_provider": cloud,
            "service_type": SERVICE_TYPES[int(np.random.randint(0, len(SERVICE_TYPES)))],
            "region": REGIONS[cloud][int(np.random.randint(0, len(REGIONS[cloud])))],
        })

    # ── Billing records ─────────────────────────────────────────────────────
    billing_records = []
    for res in resources:
        base_daily = round(float(np.random.uniform(5.0, 200.0)), 2)
        for d in date_strs:
            daily_cost = round(base_daily * float(np.random.uniform(0.85, 1.15)), 2)
            billing_records.append({
                "resource_id": res["resource_id"],
                "account_id": res["account_id"],
                "cloud_provider": res["cloud_provider"],
                "service_type": res["service_type"],
                "region": res["region"],
                "date": d,
                "base_cost": daily_cost,
            })

    # ── Resource tags ───────────────────────────────────────────────────────
    resource_tags = []
    for res in resources:
        acct = next(a for a in accounts if a["account_id"] == res["account_id"])
        dept = acct["department"]
        is_compliant = int(np.random.random() > 0.2)  # ~80 % compliant
        if is_compliant:
            dept_tag = dept
            proj_tag = fake.word()
            env_tag = ["production", "staging", "development"][int(np.random.randint(0, 3))]
            owner_tag = fake.email()
        else:
            other_depts = [d for d in DEPARTMENTS if d != dept]
            dept_tag = (
                other_depts[int(np.random.randint(0, len(other_depts)))]
                if np.random.random() > 0.5
                else ""
            )
            proj_tag = fake.word() if np.random.random() > 0.3 else ""
            env_tag = (
                ["production", "staging", "development"][int(np.random.randint(0, 3))]
                if np.random.random() > 0.4
                else ""
            )
            owner_tag = fake.email() if np.random.random() > 0.5 else ""
        resource_tags.append({
            "resource_id": res["resource_id"],
            "cloud_provider": res["cloud_provider"],
            "account_id": res["account_id"],
            "department_tag": dept_tag,
            "project_tag": proj_tag,
            "environment_tag": env_tag,
            "owner_tag": owner_tag,
            "is_compliant": is_compliant,
        })

    # ── Reserved-instance utilisation ───────────────────────────────────────
    ri_indices = sorted(np.random.choice(n_resources, size=min(n_ri, n_resources), replace=False))
    ri_records = []
    for ri_num, ri_idx in enumerate(ri_indices):
        res = resources[int(ri_idx)]
        cloud = res["cloud_provider"]
        inst_type = INSTANCE_TYPES[cloud][int(np.random.randint(0, len(INSTANCE_TYPES[cloud])))]
        ri_rate = round(float(np.random.uniform(0.05, 2.0)), 4)
        od_rate = round(ri_rate * float(np.random.uniform(1.3, 2.0)), 4)
        ri_id = f"RI-{ri_num + 1:04d}"
        for d in date_strs:
            util = round(float(np.random.uniform(30, 100)), 1)
            hours_reserved = 24
            hours_used = round(hours_reserved * util / 100, 1)
            ri_records.append({
                "ri_id": ri_id,
                "resource_id": res["resource_id"],
                "cloud_provider": cloud,
                "instance_type": inst_type,
                "region": res["region"],
                "date": d,
                "hours_reserved": hours_reserved,
                "hours_used": hours_used,
                "utilisation_pct": util,
                "ri_hourly_rate": ri_rate,
                "on_demand_rate": od_rate,
            })

    # ── Cost centres ────────────────────────────────────────────────────────
    base_sub_count = sum(len(v) for v in BASE_SUB_DEPARTMENTS.values())  # 25
    n_periods = max(4, math.ceil(SCALE["rows_per_table"] / base_sub_count))
    budget_periods = []
    start = pd.Timestamp("2025-01-01")
    for i in range(n_periods):
        p = start + pd.DateOffset(months=i)
        budget_periods.append(p.strftime("%Y-%m"))

    cost_centres = []
    cc_id = 0
    for dept in DEPARTMENTS:
        for sub in BASE_SUB_DEPARTMENTS[dept]:
            for period in budget_periods:
                cc_id += 1
                budget = round(float(np.random.uniform(50000, 500000)), 2)
                carry = round(float(np.random.uniform(0, budget * 0.08)), 2)
                cost_centres.append({
                    "cost_centre_id": f"CC-{cc_id:04d}",
                    "department": dept,
                    "sub_department": sub,
                    "budget_period": period,
                    "budget_amount": budget,
                    "carry_over": carry,
                    "manager": fake.name(),
                })

    # ══════════════════════════════════════════════════════════════════════════
    #  DATABASE
    # ══════════════════════════════════════════════════════════════════════════
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE billing_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        resource_id TEXT, account_id TEXT, cloud_provider TEXT,
        service_type TEXT, region TEXT, date TEXT, base_cost REAL
    )""")
    c.execute("""CREATE TABLE resource_tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        resource_id TEXT, cloud_provider TEXT, account_id TEXT,
        department_tag TEXT, project_tag TEXT, environment_tag TEXT,
        owner_tag TEXT, is_compliant INTEGER
    )""")
    c.execute("""CREATE TABLE ri_utilisation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ri_id TEXT, resource_id TEXT, cloud_provider TEXT,
        instance_type TEXT, region TEXT, date TEXT,
        hours_reserved INTEGER, hours_used REAL, utilisation_pct REAL,
        ri_hourly_rate REAL, on_demand_rate REAL
    )""")
    c.execute("""CREATE TABLE cost_centres (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cost_centre_id TEXT, department TEXT, sub_department TEXT,
        budget_period TEXT, budget_amount REAL, carry_over REAL,
        manager TEXT
    )""")

    for r in billing_records:
        c.execute(
            "INSERT INTO billing_records "
            "(resource_id,account_id,cloud_provider,service_type,region,date,base_cost) "
            "VALUES (?,?,?,?,?,?,?)",
            (r["resource_id"], r["account_id"], r["cloud_provider"],
             r["service_type"], r["region"], r["date"], r["base_cost"]),
        )
    for r in resource_tags:
        c.execute(
            "INSERT INTO resource_tags "
            "(resource_id,cloud_provider,account_id,department_tag,project_tag,"
            "environment_tag,owner_tag,is_compliant) VALUES (?,?,?,?,?,?,?,?)",
            (r["resource_id"], r["cloud_provider"], r["account_id"],
             r["department_tag"], r["project_tag"], r["environment_tag"],
             r["owner_tag"], r["is_compliant"]),
        )
    for r in ri_records:
        c.execute(
            "INSERT INTO ri_utilisation "
            "(ri_id,resource_id,cloud_provider,instance_type,region,date,"
            "hours_reserved,hours_used,utilisation_pct,ri_hourly_rate,on_demand_rate) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (r["ri_id"], r["resource_id"], r["cloud_provider"],
             r["instance_type"], r["region"], r["date"],
             r["hours_reserved"], r["hours_used"], r["utilisation_pct"],
             r["ri_hourly_rate"], r["on_demand_rate"]),
        )
    for r in cost_centres:
        c.execute(
            "INSERT INTO cost_centres "
            "(cost_centre_id,department,sub_department,budget_period,"
            "budget_amount,carry_over,manager) VALUES (?,?,?,?,?,?,?)",
            (r["cost_centre_id"], r["department"], r["sub_department"],
             r["budget_period"], r["budget_amount"], r["carry_over"],
             r["manager"]),
        )

    conn.commit()
    conn.close()

    # ══════════════════════════════════════════════════════════════════════════
    #  WORKSPACE – scalable files  (daily billing-adjustment CSVs)
    # ══════════════════════════════════════════════════════════════════════════
    for day_idx, d in enumerate(date_strs):
        rows = []
        for res in resources:
            discount = round(float(np.random.uniform(0, 25)), 2)
            credit = (
                round(float(np.random.uniform(0, 10)), 2)
                if np.random.random() > 0.7
                else 0.0
            )
            surcharge = float(np.random.choice([0, 3, 5, 8]))
            rows.append({
                "resource_id": res["resource_id"],
                "date": d,
                "negotiated_discount_pct": discount,
                "volume_credit": credit,
                "support_tier_surcharge_pct": surcharge,
            })
        pd.DataFrame(rows).to_csv(
            os.path.join(workspace, f"billing_adjustments_day_{day_idx + 1:02d}.csv"),
            index=False,
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  WORKSPACE – fixed / policy files
    # ══════════════════════════════════════════════════════════════════════════

    # 1. chargeback_policy.yaml
    with open(os.path.join(workspace, "chargeback_policy.yaml"), "w") as f:
        f.write("tag_compliance:\n")
        f.write("  non_compliant_surcharge_pct: 15\n")
        f.write("  description: Resources failing tag compliance receive a percentage surcharge on their adjusted cost\n\n")
        f.write("ri_utilisation:\n")
        f.write("  underutilisation_threshold_pct: 60\n")
        f.write("  penalty_pct: 25\n")
        f.write("  description: RIs averaging below threshold utilisation incur a penalty on wasted capacity cost\n\n")
        f.write("shared_services:\n")
        f.write("  allocation_method: headcount_proportional\n")
        f.write("  description: Shared service costs allocated proportionally by department headcount\n\n")
        f.write("rounding:\n")
        f.write("  decimal_places: 2\n")

    # 2. account_directory.json
    acct_dir = {}
    for a in accounts:
        acct_dir[a["account_id"]] = {
            "cloud_provider": a["cloud_provider"],
            "department": a["department"],
            "account_name": a["account_name"],
        }
    with open(os.path.join(workspace, "account_directory.json"), "w") as f:
        json.dump(acct_dir, f, indent=2)

    # 3. shared_services_costs.csv
    shared = [
        {"service": "Network Infrastructure",
         "monthly_cost": round(float(np.random.uniform(10000, 50000)), 2)},
        {"service": "Security Operations Center",
         "monthly_cost": round(float(np.random.uniform(20000, 80000)), 2)},
        {"service": "Central Monitoring",
         "monthly_cost": round(float(np.random.uniform(5000, 30000)), 2)},
        {"service": "DNS and CDN",
         "monthly_cost": round(float(np.random.uniform(3000, 15000)), 2)},
    ]
    pd.DataFrame(shared).to_csv(
        os.path.join(workspace, "shared_services_costs.csv"), index=False,
    )

    # 4. department_headcount.json
    hc = {}
    for dept in DEPARTMENTS:
        hc[dept] = int(np.random.randint(20, 150))
    with open(os.path.join(workspace, "department_headcount.json"), "w") as f:
        json.dump(hc, f, indent=2)

    # 5. budget_rules.txt
    with open(os.path.join(workspace, "budget_rules.txt"), "w") as f:
        f.write("Budget Variance Assessment Rules\n")
        f.write("================================\n\n")
        f.write("Over-budget threshold: 10\n")
        f.write("  Departments whose actual spend exceeds their effective budget\n")
        f.write("  by more than 10 percent are flagged as over-budget.\n\n")
        f.write("Effective budget calculation:\n")
        f.write("  effective_budget = sum of budget_amount + sum of carry_over\n")
        f.write("  for the billing period across all sub-departments.\n\n")
        f.write("Billing period for current assessment: 2025-01\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
