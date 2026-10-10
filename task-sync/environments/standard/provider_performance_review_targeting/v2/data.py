import argparse
import os
import sqlite3
import json
import csv
import math
import random
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 24,
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SPECIALTIES = [
    "Cardiology", "Orthopedics", "Neurology", "Oncology",
    "Gastroenterology", "Pulmonology", "Endocrinology",
    "Dermatology", "Urology", "Rheumatology",
]
NETWORK_TIERS = ["Tier1", "Tier2", "Tier3"]
TIER_MULTIPLIERS = {"Tier1": 1.00, "Tier2": 1.15, "Tier3": 1.35}
REGIONS = ["Northeast", "Southeast", "Midwest", "West", "Southwest"]
DIAGNOSIS_GROUPS = [
    "cardiac", "musculoskeletal", "neurological", "oncological",
    "gastrointestinal", "respiratory", "metabolic", "dermatological",
    "urological", "immunological",
]
URGENCY_LEVELS = ["high", "medium", "low"]
REFERENCE_DATE = "2025-01-01"


def init_seeds():
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    return Faker()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
def create_tables(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS providers (
            provider_id TEXT PRIMARY KEY,
            name TEXT,
            specialty TEXT,
            network_tier TEXT,
            region TEXT,
            npi TEXT,
            contract_start_date TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT PRIMARY KEY,
            provider_id TEXT,
            member_id TEXT,
            service_code TEXT,
            service_date TEXT,
            billed_amount REAL,
            paid_amount REAL,
            status TEXT,
            FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS satisfaction_surveys (
            survey_id TEXT PRIMARY KEY,
            member_id TEXT,
            provider_id TEXT,
            overall_rating REAL,
            survey_date TEXT,
            FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS fee_schedules (
            fee_id TEXT PRIMARY KEY,
            service_code TEXT UNIQUE,
            base_rate REAL,
            effective_date TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referral_id TEXT PRIMARY KEY,
            referring_provider_id TEXT,
            referred_provider_id TEXT,
            member_id TEXT,
            referral_date TEXT,
            is_in_network INTEGER,
            status TEXT,
            FOREIGN KEY (referring_provider_id) REFERENCES providers(provider_id),
            FOREIGN KEY (referred_provider_id) REFERENCES providers(provider_id)
        )
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Data generators
# ---------------------------------------------------------------------------
def generate_service_codes(n_providers):
    """Return a list of service codes sized to the provider count."""
    n_codes = max(50, n_providers)
    return [f"SVC{i:04d}" for i in range(1, n_codes + 1)]


def generate_providers(fake, conn, n):
    providers = []
    used_npis = set()
    for i in range(n):
        pid = f"PRV{i + 1:05d}"
        name = fake.name()
        specialty = SPECIALTIES[i % len(SPECIALTIES)]
        tier = NETWORK_TIERS[i % len(NETWORK_TIERS)]
        region = REGIONS[i % len(REGIONS)]
        while True:
            npi = fake.numerify("##########")
            if npi not in used_npis:
                used_npis.add(npi)
                break
        # Contract start: between 2022-01-01 and 2024-12-31
        start = fake.date_between_dates(
            date_start=pd.Timestamp("2022-01-01"),
            date_end=pd.Timestamp("2024-12-31"),
        )
        providers.append({
            "provider_id": pid,
            "name": name,
            "specialty": specialty,
            "network_tier": tier,
            "region": region,
            "npi": npi,
            "contract_start_date": str(start),
        })
    rows = [(p["provider_id"], p["name"], p["specialty"], p["network_tier"],
             p["region"], p["npi"], p["contract_start_date"]) for p in providers]
    conn.executemany(
        "INSERT INTO providers VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return providers


def generate_fee_schedules(conn, service_codes):
    """One base rate per service code."""
    fee_rates = {}
    rows = []
    for i, sc in enumerate(service_codes):
        fid = f"FEE{i + 1:05d}"
        base_rate = round(float(np.random.uniform(80, 600)), 2)
        fee_rates[sc] = base_rate
        rows.append((fid, sc, base_rate, "2024-01-01"))
    conn.executemany(
        "INSERT INTO fee_schedules VALUES (?,?,?,?)", rows)
    conn.commit()
    return fee_rates


def generate_claims(fake, conn, providers, n_claims, fee_rates, service_codes):
    """
    Return DB rows + supplemental workspace data.
    Supplemental: list of {claim_id, diagnosis_group, cost_adjustment_factor}
    """
    n_prov = len(providers)
    # Provider profiles
    high_cost_mask = np.random.random(n_prov) < 0.35
    profile_map = {p["provider_id"]: bool(high_cost_mask[i])
                   for i, p in enumerate(providers)}

    # Distribute claims across providers (at least 3 per provider)
    base_per_prov = max(3, n_claims // n_prov)
    remainder = n_claims - base_per_prov * n_prov
    claims_per_prov = [base_per_prov] * n_prov
    for i in range(max(0, remainder)):
        claims_per_prov[i % n_prov] += 1

    db_rows = []
    supp_data = []
    claim_idx = 0
    for pi, prov in enumerate(providers):
        pid = prov["provider_id"]
        tier = prov["network_tier"]
        tier_mult = TIER_MULTIPLIERS[tier]
        is_high_cost = profile_map[pid]
        for _ in range(claims_per_prov[pi]):
            claim_idx += 1
            cid = f"CLM{claim_idx:06d}"
            mid = f"MBR{np.random.randint(1, 10000):05d}"
            sc = random.choice(service_codes)
            sdate = str(fake.date_between_dates(
                date_start=pd.Timestamp("2024-01-01"),
                date_end=pd.Timestamp("2024-12-31"),
            ))
            diag = random.choice(DIAGNOSIS_GROUPS)
            adj_factor = round(float(np.random.uniform(0.75, 1.40)), 4)
            base_rate = fee_rates[sc]
            expected = base_rate * tier_mult * adj_factor
            if is_high_cost:
                premium = float(np.random.uniform(1.25, 1.75))
            else:
                premium = float(np.random.uniform(0.78, 1.08))
            paid = round(expected * premium, 2)
            billed = round(paid * float(np.random.uniform(1.05, 1.45)), 2)
            status = np.random.choice(
                ["approved", "denied", "pending"],
                p=[0.75, 0.15, 0.10],
            )
            db_rows.append((cid, pid, mid, sc, sdate, billed, paid, status))
            supp_data.append({
                "claim_id": cid,
                "diagnosis_group": diag,
                "cost_adjustment_factor": adj_factor,
            })

    conn.executemany("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?)", db_rows)
    conn.commit()
    return supp_data, profile_map


def generate_surveys(fake, conn, providers, n_surveys, cost_profile_map):
    """
    Return DB rows + supplemental dimension scores.
    """
    n_prov = len(providers)
    # Low satisfaction mask (independent of cost)
    low_sat_mask = np.random.random(n_prov) < 0.40
    sat_profile = {p["provider_id"]: bool(low_sat_mask[i])
                   for i, p in enumerate(providers)}

    base_per_prov = max(2, n_surveys // n_prov)
    remainder = n_surveys - base_per_prov * n_prov
    surveys_per_prov = [base_per_prov] * n_prov
    for i in range(max(0, remainder)):
        surveys_per_prov[i % n_prov] += 1

    db_rows = []
    dims_data = []
    survey_idx = 0
    for pi, prov in enumerate(providers):
        pid = prov["provider_id"]
        is_low_sat = sat_profile[pid]
        for _ in range(surveys_per_prov[pi]):
            survey_idx += 1
            sid = f"SRV{survey_idx:06d}"
            mid = f"MBR{np.random.randint(1, 10000):05d}"
            sdate = str(fake.date_between_dates(
                date_start=pd.Timestamp("2024-01-01"),
                date_end=pd.Timestamp("2024-12-31"),
            ))
            if is_low_sat:
                overall = round(float(np.random.uniform(1.3, 3.1)), 2)
                comm = round(float(np.random.uniform(1.2, 3.2)), 2)
                time_ = round(float(np.random.uniform(1.2, 3.3)), 2)
                outc = round(float(np.random.uniform(1.1, 3.0)), 2)
            else:
                overall = round(float(np.random.uniform(3.4, 5.0)), 2)
                comm = round(float(np.random.uniform(3.3, 5.0)), 2)
                time_ = round(float(np.random.uniform(3.3, 5.0)), 2)
                outc = round(float(np.random.uniform(3.4, 5.0)), 2)
            db_rows.append((sid, mid, pid, overall, sdate))
            dims_data.append({
                "survey_id": sid,
                "communication_score": comm,
                "timeliness_score": time_,
                "outcome_score": outc,
            })

    conn.executemany(
        "INSERT INTO satisfaction_surveys VALUES (?,?,?,?,?)", db_rows)
    conn.commit()
    return dims_data, sat_profile


def generate_referrals(fake, conn, providers, n_referrals):
    """
    Return DB rows + urgency annotations.
    """
    n_prov = len(providers)
    pids = [p["provider_id"] for p in providers]
    base_per_prov = max(2, n_referrals // n_prov)
    remainder = n_referrals - base_per_prov * n_prov
    refs_per_prov = [base_per_prov] * n_prov
    for i in range(max(0, remainder)):
        refs_per_prov[i % n_prov] += 1

    db_rows = []
    annot_data = []
    ref_idx = 0
    for pi, prov in enumerate(providers):
        pid = prov["provider_id"]
        for _ in range(refs_per_prov[pi]):
            ref_idx += 1
            rid = f"REF{ref_idx:06d}"
            referred = random.choice(pids)
            while referred == pid and n_prov > 1:
                referred = random.choice(pids)
            mid = f"MBR{np.random.randint(1, 10000):05d}"
            rdate = str(fake.date_between_dates(
                date_start=pd.Timestamp("2024-01-01"),
                date_end=pd.Timestamp("2024-12-31"),
            ))
            is_in = int(np.random.random() < 0.65)
            status = random.choice(["completed", "pending", "cancelled"])
            urgency = np.random.choice(
                URGENCY_LEVELS, p=[0.20, 0.45, 0.35])
            db_rows.append((rid, pid, referred, mid, rdate, is_in, status))
            annot_data.append({
                "referral_id": rid,
                "urgency_level": urgency,
            })

    conn.executemany("INSERT INTO referrals VALUES (?,?,?,?,?,?,?)", db_rows)
    conn.commit()
    return annot_data


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
def _split_into_chunks(data, n_chunks):
    n_chunks = max(1, n_chunks)
    chunk_size = math.ceil(len(data) / n_chunks)
    return [data[i * chunk_size:(i + 1) * chunk_size]
            for i in range(n_chunks)]


def compute_specialty_benchmarks(conn, providers, fee_rates, claims_supp):
    """Compute average cost ratio per specialty from actual DB data,
    using the same formula as the evaluation (with cost_adjustment_factor)."""
    # Build claim_id -> adj_factor map
    adj_map = {rec["claim_id"]: rec["cost_adjustment_factor"]
               for rec in claims_supp}
    cur = conn.cursor()
    specialty_ratios = {}
    for prov in providers:
        pid = prov["provider_id"]
        tier = prov["network_tier"]
        tier_mult = TIER_MULTIPLIERS[tier]
        spec = prov["specialty"]
        cur.execute(
            "SELECT c.claim_id, c.service_code, c.paid_amount "
            "FROM claims c WHERE c.provider_id=? AND c.status='approved'",
            (pid,))
        rows = cur.fetchall()
        if len(rows) < 5:
            continue
        total_paid = 0.0
        total_expected = 0.0
        for cid, sc, paid in rows:
            base = fee_rates.get(sc, 200.0)
            adj = adj_map.get(cid, 1.0)
            total_expected += base * tier_mult * adj
            total_paid += paid
        if total_expected > 0:
            ratio = total_paid / total_expected
            specialty_ratios.setdefault(spec, []).append(ratio)
    benchmarks = {}
    for spec, ratios in specialty_ratios.items():
        benchmarks[spec] = round(float(np.mean(ratios)), 4)
    return benchmarks


def generate_workspace(workspace, providers, claims_supp, survey_dims,
                       referral_annots, fee_rates, conn, n_scalable_files):
    # --- Scalable files ---
    n_csv = max(2, n_scalable_files * 3 // 8)
    n_json = max(2, n_scalable_files * 3 // 8)
    n_txt = max(2, n_scalable_files - n_csv - n_json)

    # Claims detail CSVs
    csv_chunks = _split_into_chunks(claims_supp, n_csv)
    for i, chunk in enumerate(csv_chunks):
        fpath = os.path.join(workspace, f"claims_detail_{i + 1:03d}.csv")
        with open(fpath, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "claim_id", "diagnosis_group", "cost_adjustment_factor"])
            w.writeheader()
            w.writerows(chunk)

    # Survey responses JSONs
    json_chunks = _split_into_chunks(survey_dims, n_json)
    for i, chunk in enumerate(json_chunks):
        fpath = os.path.join(workspace, f"survey_responses_{i + 1:03d}.json")
        with open(fpath, "w") as f:
            json.dump(chunk, f, indent=2)

    # Referral annotations TXTs
    txt_chunks = _split_into_chunks(referral_annots, n_txt)
    for i, chunk in enumerate(txt_chunks):
        fpath = os.path.join(workspace, f"referral_annotations_{i + 1:03d}.txt")
        with open(fpath, "w") as f:
            f.write("referral_id|urgency_level\n")
            for rec in chunk:
                f.write(f"{rec['referral_id']}|{rec['urgency_level']}\n")

    # --- Fixed configuration files ---

    # 1. review_criteria.yaml
    import yaml
    criteria = {
        "cost_ratio_threshold": 1.20,
        "satisfaction_floor": 3.20,
        "min_claims_required": 5,
        "referral_leakage_threshold": 0.30,
        "composite_weights": {
            "cost_excess": 0.40,
            "satisfaction_deficit": 0.35,
            "referral_leakage": 0.25,
        },
    }
    with open(os.path.join(workspace, "review_criteria.yaml"), "w") as f:
        yaml.dump(criteria, f, default_flow_style=False, sort_keys=False)

    # 2. satisfaction_weights.yaml
    sat_weights = {
        "weights": {
            "overall": 0.40,
            "communication": 0.20,
            "timeliness": 0.20,
            "outcome": 0.20,
        }
    }
    with open(os.path.join(workspace, "satisfaction_weights.yaml"), "w") as f:
        yaml.dump(sat_weights, f, default_flow_style=False, sort_keys=False)

    # 3. network_tier_config.json
    tier_cfg = {
        t: {"rate_multiplier": m, "description": desc}
        for t, m, desc in [
            ("Tier1", 1.00, "Preferred in-network"),
            ("Tier2", 1.15, "Standard in-network"),
            ("Tier3", 1.35, "Extended network"),
        ]
    }
    with open(os.path.join(workspace, "network_tier_config.json"), "w") as f:
        json.dump(tier_cfg, f, indent=2)

    # 4. specialty_benchmarks.csv
    benchmarks = compute_specialty_benchmarks(conn, providers, fee_rates, claims_supp)
    with open(os.path.join(workspace, "specialty_benchmarks.csv"), "w",
              newline="") as f:
        w = csv.writer(f)
        w.writerow(["specialty", "benchmark_cost_ratio"])
        for spec in sorted(benchmarks):
            w.writerow([spec, benchmarks[spec]])

    # 5. exclusion_list.md  – providers with contract start within 180 days
    from datetime import datetime, timedelta
    ref = datetime.strptime(REFERENCE_DATE, "%Y-%m-%d")
    cutoff = ref - timedelta(days=180)
    excluded = [p for p in providers
                if datetime.strptime(p["contract_start_date"], "%Y-%m-%d") >= cutoff]
    with open(os.path.join(workspace, "exclusion_list.md"), "w") as f:
        f.write("# Provider Exclusion List\n\n")
        f.write(
            "Providers whose contracts were initiated within 180 days of the "
            f"review reference date ({REFERENCE_DATE}) are excluded from the "
            "renegotiation review.\n\n"
        )
        if excluded:
            for p in excluded:
                f.write(
                    f"{p['provider_id']} - {p['name']} "
                    f"(contract start: {p['contract_start_date']})\n"
                )
        else:
            f.write("No providers currently meet the exclusion criteria.\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    fake = init_seeds()
    os.makedirs(args.workspace, exist_ok=True)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n_prov = SCALE["rows_per_table"]
    n_claims = SCALE["rows_per_table"] * 10
    n_surveys = SCALE["rows_per_table"] * 3
    n_referrals = SCALE["rows_per_table"] * 3

    service_codes = generate_service_codes(n_prov)
    providers = generate_providers(fake, conn, n_prov)
    fee_rates = generate_fee_schedules(conn, service_codes)
    claims_supp, cost_profile = generate_claims(
        fake, conn, providers, n_claims, fee_rates, service_codes)
    survey_dims, sat_profile = generate_surveys(
        fake, conn, providers, n_surveys, cost_profile)
    referral_annots = generate_referrals(fake, conn, providers, n_referrals)

    generate_workspace(
        args.workspace, providers, claims_supp, survey_dims,
        referral_annots, fee_rates, conn, SCALE["num_workspace_files"])

    conn.close()
    print(f"Database written to {args.db_path}")
    print(f"Workspace generated in {args.workspace}")


if __name__ == "__main__":
    main()
