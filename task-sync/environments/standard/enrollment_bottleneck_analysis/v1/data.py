import argparse
import os
import sqlite3
import json
import random
import math
import yaml
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 20,
}

REGIONS = ["Northeast", "Southeast", "Midwest", "West", "Southwest"]
TIERS = ["A", "B", "C"]
STATUSES = ["active", "paused", "closed"]
THERAPEUTIC_AREAS = ["Oncology", "Cardiology", "Neurology", "Immunology", "Endocrinology"]
FAILURE_CATEGORIES = [
    "informed_consent", "medical_history", "lab_values",
    "age_criteria", "concomitant_medications", "prior_therapy"
]
CRITERION_CODES = ["EC01", "EC02", "EC03", "EC04", "EC05", "EC06", "EC07", "EC08"]
CRITERION_NAMES = {
    "EC01": "Age Range Compliance",
    "EC02": "Lab Value Thresholds",
    "EC03": "Prior Treatment History",
    "EC04": "Comorbidity Screen",
    "EC05": "Informed Consent Status",
    "EC06": "Genetic Marker Presence",
    "EC07": "Organ Function Assessment",
    "EC08": "Concomitant Medication Review",
}
PERIODS = ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]
ROLES = ["principal_investigator", "sub_investigator", "study_coordinator", "research_nurse"]

REGIONAL_BENCHMARKS = {
    "Northeast": {"default_monthly_target": 12, "expected_screen_pass_rate": 0.65},
    "Southeast": {"default_monthly_target": 10, "expected_screen_pass_rate": 0.60},
    "Midwest":   {"default_monthly_target": 8,  "expected_screen_pass_rate": 0.58},
    "West":      {"default_monthly_target": 11, "expected_screen_pass_rate": 0.62},
    "Southwest": {"default_monthly_target": 9,  "expected_screen_pass_rate": 0.55},
}

SCORING_CONFIG = {
    "thresholds": {
        "screen_failure_rate": 0.40,
        "eligibility_barrier": 0.35,
        "enrollment_ratio": 0.50,
        "investigator_utilization": 0.85,
        "certification_expiry_days": 90,
    },
    "weights": {
        "screening_failure": 30,
        "eligibility_barrier": 25,
        "enrollment_shortfall": 25,
        "investigator_capacity": 20,
    },
    "tier_multipliers": {
        "A": 1.5,
        "B": 1.0,
        "C": 0.75,
    },
    "reference_date": "2026-04-20",
}

INTERVENTION_CATALOG = {
    "screening_failure": "Implement enhanced pre-screening protocol and conduct site-specific training on inclusion and exclusion criteria",
    "eligibility_barrier": "Initiate eligibility criteria review with medical monitor and consider protocol amendment for problematic criteria",
    "enrollment_shortfall": "Deploy targeted patient recruitment campaign and expand referral network partnerships",
    "investigator_capacity": "Recruit additional qualified staff and redistribute workload among existing team members",
    "multiple": "Execute comprehensive site remediation plan addressing all identified bottleneck areas",
}


def create_tables(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS sites (
            site_id TEXT PRIMARY KEY,
            site_name TEXT NOT NULL,
            region TEXT NOT NULL,
            tier TEXT NOT NULL,
            status TEXT NOT NULL,
            therapeutic_area TEXT NOT NULL,
            study_start_date TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS screening_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            screen_date TEXT NOT NULL,
            outcome TEXT NOT NULL,
            failure_category TEXT,
            FOREIGN KEY (site_id) REFERENCES sites(site_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS eligibility_results (
            result_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            criterion_code TEXT NOT NULL,
            result TEXT NOT NULL,
            FOREIGN KEY (site_id) REFERENCES sites(site_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS investigators (
            investigator_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            site_id TEXT NOT NULL,
            role TEXT NOT NULL,
            max_weekly_hours REAL NOT NULL,
            current_weekly_hours REAL NOT NULL,
            certification_expiry TEXT NOT NULL,
            FOREIGN KEY (site_id) REFERENCES sites(site_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS enrollment_history (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id TEXT NOT NULL,
            period TEXT NOT NULL,
            enrolled_count INTEGER NOT NULL,
            screened_count INTEGER NOT NULL,
            dropout_count INTEGER NOT NULL,
            FOREIGN KEY (site_id) REFERENCES sites(site_id)
        )
    """)
    conn.commit()


def generate_sites(rng, fake, n_sites):
    sites = []
    for i in range(n_sites):
        site_id = f"SITE_{i+1:03d}"
        suffixes = ["Medical Center", "Hospital", "Clinical Research", "Health Institute", "Research Clinic"]
        site_name = fake.company() + " " + suffixes[rng.randint(0, len(suffixes))]
        region = REGIONS[rng.randint(0, len(REGIONS))]
        tier = rng.choice(TIERS, p=[0.2, 0.5, 0.3])
        status = rng.choice(STATUSES, p=[0.50, 0.25, 0.25])
        ta = THERAPEUTIC_AREAS[rng.randint(0, len(THERAPEUTIC_AREAS))]
        month = rng.randint(1, 7)
        day = rng.randint(1, 29)
        start_date = f"2025-{month:02d}-{day:02d}"
        sites.append({
            "site_id": site_id,
            "site_name": site_name,
            "region": region,
            "tier": tier,
            "status": status,
            "therapeutic_area": ta,
            "study_start_date": start_date,
        })
    return pd.DataFrame(sites)


def generate_screening_logs(rng, fake, sites_df, n_logs):
    all_site_ids = sites_df["site_id"].tolist()
    n_sites = len(all_site_ids)

    # Assign a screen-fail propensity per site
    site_propensities = {}
    for sid in all_site_ids:
        site_propensities[sid] = rng.uniform(0.15, 0.60)

    # Distribute logs across sites (weighted toward active)
    active_mask = sites_df["status"] == "active"
    active_ids = sites_df[active_mask]["site_id"].tolist()
    other_ids = sites_df[~active_mask]["site_id"].tolist()

    records = []
    patient_counter = 0
    for i in range(n_logs):
        # 85% of screenings at active sites
        if rng.random() < 0.85 and active_ids:
            sid = active_ids[rng.randint(0, len(active_ids))]
        else:
            sid = all_site_ids[rng.randint(0, n_sites)]

        patient_counter += 1
        patient_id = f"PAT_{patient_counter:05d}"
        days_offset = rng.randint(0, 180)
        screen_date = (datetime(2025, 7, 1) + timedelta(days=int(days_offset))).strftime("%Y-%m-%d")

        prop = site_propensities[sid]
        outcome = "fail" if rng.random() < prop else "pass"
        failure_category = None
        if outcome == "fail":
            failure_category = FAILURE_CATEGORIES[rng.randint(0, len(FAILURE_CATEGORIES))]

        records.append({
            "patient_id": patient_id,
            "site_id": sid,
            "screen_date": screen_date,
            "outcome": outcome,
            "failure_category": failure_category,
        })

    return pd.DataFrame(records), site_propensities


def generate_eligibility_results(rng, sites_df, screening_df, n_results):
    # For each patient, generate eligibility criterion checks
    # Group by site to assign criterion fail propensities per site per criterion
    all_site_ids = sites_df["site_id"].tolist()

    site_criterion_propensities = {}
    for sid in all_site_ids:
        props = {}
        for code in CRITERION_CODES:
            props[code] = rng.uniform(0.05, 0.55)
        site_criterion_propensities[sid] = props

    # Get unique patients with their sites
    patient_sites = screening_df[["patient_id", "site_id"]].drop_duplicates("patient_id")
    patients = patient_sites.values.tolist()

    records = []
    idx = 0
    while len(records) < n_results:
        pat_id, sid = patients[idx % len(patients)]
        # Each patient gets 2-5 criteria checked
        n_criteria = rng.randint(2, 6)
        chosen_criteria = rng.choice(CRITERION_CODES, size=min(n_criteria, len(CRITERION_CODES)), replace=False)
        for code in chosen_criteria:
            prop = site_criterion_propensities[sid][code]
            result = "not_met" if rng.random() < prop else "met"
            records.append({
                "patient_id": pat_id,
                "site_id": sid,
                "criterion_code": code,
                "result": result,
            })
            if len(records) >= n_results:
                break
        idx += 1

    return pd.DataFrame(records[:n_results]), site_criterion_propensities


def generate_investigators(rng, fake, sites_df, n_investigators):
    all_site_ids = sites_df["site_id"].tolist()
    n_sites = len(all_site_ids)

    # Assign utilization propensities per site
    site_util_propensities = {}
    for sid in all_site_ids:
        site_util_propensities[sid] = rng.uniform(0.55, 0.98)

    records = []
    # Ensure each site gets at least 1 investigator, distribute rest
    site_inv_counts = {sid: 1 for sid in all_site_ids}
    remaining = n_investigators - n_sites
    for _ in range(max(0, remaining)):
        sid = all_site_ids[rng.randint(0, n_sites)]
        site_inv_counts[sid] += 1

    inv_counter = 0
    ref_date = datetime.strptime(SCORING_CONFIG["reference_date"], "%Y-%m-%d")
    for sid, count in site_inv_counts.items():
        util_prop = site_util_propensities[sid]
        for j in range(count):
            inv_counter += 1
            inv_id = f"INV_{inv_counter:03d}"
            name = fake.name()
            if j == 0:
                role = "principal_investigator"
            else:
                role = ROLES[rng.randint(1, len(ROLES))]
            max_hours = float(rng.choice([20, 25, 30, 35, 40]))
            current_hours = round(max_hours * util_prop * rng.uniform(0.85, 1.15), 1)
            current_hours = min(current_hours, max_hours)
            current_hours = max(current_hours, 0)

            # Some investigators have certs expiring soon
            if rng.random() < 0.15:
                days_to_expiry = rng.randint(10, 120)
            else:
                days_to_expiry = rng.randint(120, 730)
            cert_expiry = (ref_date + timedelta(days=int(days_to_expiry))).strftime("%Y-%m-%d")

            records.append({
                "investigator_id": inv_id,
                "name": name,
                "site_id": sid,
                "role": role,
                "max_weekly_hours": max_hours,
                "current_weekly_hours": current_hours,
                "certification_expiry": cert_expiry,
            })

    return pd.DataFrame(records), site_util_propensities


def generate_enrollment_history(rng, sites_df):
    records = []
    all_site_ids = sites_df["site_id"].tolist()
    site_regions = dict(zip(sites_df["site_id"], sites_df["region"]))

    for sid in all_site_ids:
        region = site_regions[sid]
        base_target = REGIONAL_BENCHMARKS[region]["default_monthly_target"]
        # Enrollment propensity for this site
        enroll_prop = rng.uniform(0.20, 0.90)

        for period in PERIODS:
            noise = rng.uniform(0.7, 1.3)
            enrolled = max(0, int(round(base_target * enroll_prop * noise)))
            screened = max(enrolled, int(round(enrolled / max(0.3, rng.uniform(0.4, 0.9)))))
            dropout = int(round(enrolled * rng.uniform(0, 0.15)))
            records.append({
                "site_id": sid,
                "period": period,
                "enrolled_count": enrolled,
                "screened_count": screened,
                "dropout_count": dropout,
            })

    return pd.DataFrame(records)


def create_fixed_workspace_files(workspace):
    """Create fixed config files that do not scale."""
    # scoring_config.yaml
    with open(os.path.join(workspace, "scoring_config.yaml"), "w") as f:
        yaml.dump(SCORING_CONFIG, f, default_flow_style=False, sort_keys=False)

    # regional_benchmarks.csv
    rows = []
    for region, data in REGIONAL_BENCHMARKS.items():
        rows.append({
            "region": region,
            "default_monthly_target": data["default_monthly_target"],
            "expected_screen_pass_rate": data["expected_screen_pass_rate"],
        })
    pd.DataFrame(rows).to_csv(os.path.join(workspace, "regional_benchmarks.csv"), index=False)

    # intervention_catalog.yaml
    with open(os.path.join(workspace, "intervention_catalog.yaml"), "w") as f:
        yaml.dump(INTERVENTION_CATALOG, f, default_flow_style=False, sort_keys=False)


def create_scalable_workspace_files(workspace, sites_df, rng, n_files):
    """
    Create scalable workspace files containing per-site supplementary data
    (risk_adjustment_factor, custom_monthly_target) across multiple formats.
    """
    n_sites = len(sites_df)
    site_ids = sites_df["site_id"].tolist()
    site_regions = dict(zip(sites_df["site_id"], sites_df["region"]))

    # Generate supplementary data for each site
    site_supplement = {}
    for sid in site_ids:
        risk_adj = round(rng.uniform(0.80, 1.30), 2)
        # 40% of sites get a custom target, rest use regional default
        if rng.random() < 0.40:
            region = site_regions[sid]
            base = REGIONAL_BENCHMARKS[region]["default_monthly_target"]
            custom_target = int(round(base * rng.uniform(0.6, 1.4)))
        else:
            custom_target = None
        site_supplement[sid] = {
            "risk_adjustment_factor": risk_adj,
            "custom_monthly_target": custom_target,
        }

    # Distribute sites across files round-robin
    file_assignments = {i: [] for i in range(n_files)}
    for idx, sid in enumerate(site_ids):
        file_idx = idx % n_files
        file_assignments[file_idx].append(sid)

    # Determine file format distribution: CSV, JSON, TXT, YAML, MD
    # Proportions: 30% CSV, 30% JSON, 20% TXT, 10% YAML, 10% MD
    n_csv = max(1, round(n_files * 0.30))
    n_json = max(1, round(n_files * 0.30))
    n_txt = max(1, round(n_files * 0.20))
    n_yaml = max(1, round(n_files * 0.10))
    n_md = n_files - n_csv - n_json - n_txt - n_yaml
    if n_md < 1:
        n_md = 1
        # Reduce largest
        if n_csv >= n_json and n_csv >= n_txt:
            n_csv -= 1
        elif n_json >= n_txt:
            n_json -= 1
        else:
            n_txt -= 1

    format_list = (["csv"] * n_csv + ["json"] * n_json +
                   ["txt"] * n_txt + ["yaml"] * n_yaml + ["md"] * n_md)
    # Ensure length matches
    while len(format_list) < n_files:
        format_list.append("csv")
    format_list = format_list[:n_files]

    counters = {"csv": 0, "json": 0, "txt": 0, "yaml": 0, "md": 0}

    for file_idx in range(n_files):
        fmt = format_list[file_idx]
        counters[fmt] += 1
        assigned_sites = file_assignments[file_idx]
        data_for_file = []
        for sid in assigned_sites:
            supp = site_supplement[sid]
            data_for_file.append({
                "site_id": sid,
                "risk_adjustment_factor": supp["risk_adjustment_factor"],
                "custom_monthly_target": supp["custom_monthly_target"],
            })

        filename = f"site_supplement_{counters[fmt]}.{fmt}"
        filepath = os.path.join(workspace, filename)

        if fmt == "csv":
            df = pd.DataFrame(data_for_file)
            df.to_csv(filepath, index=False)

        elif fmt == "json":
            with open(filepath, "w") as f:
                json.dump(data_for_file, f, indent=2)

        elif fmt == "txt":
            with open(filepath, "w") as f:
                f.write("site_id | risk_adjustment_factor | custom_monthly_target\n")
                f.write("-" * 60 + "\n")
                for row in data_for_file:
                    target_str = str(row["custom_monthly_target"]) if row["custom_monthly_target"] is not None else "N/A"
                    f.write(f"{row['site_id']} | {row['risk_adjustment_factor']} | {target_str}\n")

        elif fmt == "yaml":
            yaml_data = {}
            for row in data_for_file:
                yaml_data[row["site_id"]] = {
                    "risk_adjustment_factor": row["risk_adjustment_factor"],
                    "custom_monthly_target": row["custom_monthly_target"],
                }
            with open(filepath, "w") as f:
                yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)

        elif fmt == "md":
            with open(filepath, "w") as f:
                f.write("| site_id | risk_adjustment_factor | custom_monthly_target |\n")
                f.write("|---------|----------------------|----------------------|\n")
                for row in data_for_file:
                    target_str = str(row["custom_monthly_target"]) if row["custom_monthly_target"] is not None else "N/A"
                    f.write(f"| {row['site_id']} | {row['risk_adjustment_factor']} | {target_str} |\n")

    return site_supplement


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Set all seeds
    np.random.seed(42)
    random.seed(42)
    Faker.seed(42)
    fake = Faker()
    rng = np.random.RandomState(42)

    n_sites = SCALE["rows_per_table"]
    n_screening = SCALE["rows_per_table"] * 5
    n_eligibility = SCALE["rows_per_table"] * 4
    n_investigators = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # Generate data
    sites_df = generate_sites(rng, fake, n_sites)
    screening_df, _ = generate_screening_logs(rng, fake, sites_df, n_screening)
    eligibility_df, _ = generate_eligibility_results(rng, sites_df, screening_df, n_eligibility)
    investigators_df, _ = generate_investigators(rng, fake, sites_df, n_investigators)
    enrollment_df = generate_enrollment_history(rng, sites_df)

    # Write to database
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    sites_df.to_sql("sites", conn, if_exists="append", index=False)
    screening_df.to_sql("screening_logs", conn, if_exists="append", index=False)
    eligibility_df.to_sql("eligibility_results", conn, if_exists="append", index=False)
    investigators_df.to_sql("investigators", conn, if_exists="append", index=False)
    enrollment_df.to_sql("enrollment_history", conn, if_exists="append", index=False)

    conn.commit()
    conn.close()

    # Create workspace
    os.makedirs(args.workspace, exist_ok=True)
    create_fixed_workspace_files(args.workspace)
    create_scalable_workspace_files(args.workspace, sites_df, rng, n_files)

    print(f"Database created at {args.db_path}")
    print(f"  sites: {len(sites_df)} rows")
    print(f"  screening_logs: {len(screening_df)} rows")
    print(f"  eligibility_results: {len(eligibility_df)} rows")
    print(f"  investigators: {len(investigators_df)} rows")
    print(f"  enrollment_history: {len(enrollment_df)} rows")
    print(f"Workspace created at {args.workspace}")


if __name__ == "__main__":
    main()
