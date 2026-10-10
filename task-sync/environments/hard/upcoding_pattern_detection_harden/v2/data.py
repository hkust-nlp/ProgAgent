import argparse
import json
import os
import random
import sqlite3
import yaml

import numpy as np
import pandas as pd
from faker import Faker


SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 24,
}

# ── Constants ──────────────────────────────────────────────────────────────────

SPECIALTIES = [
    "Cardiology", "Orthopedics", "Dermatology", "Gastroenterology",
    "Neurology", "Urology", "Pulmonology", "General Surgery",
    "Internal Medicine", "Family Medicine",
]

REGIONS = ["Northeast", "Southeast", "Midwest", "West", "Southwest"]

PROCEDURE_CATEGORIES = [
    "Diagnostic", "Therapeutic", "Surgical",
    "Preventive", "Consultation", "Rehabilitative",
]

SPECIALTY_SCOPE = {
    "Cardiology":        ["Diagnostic", "Therapeutic", "Surgical", "Consultation"],
    "Orthopedics":       ["Diagnostic", "Therapeutic", "Surgical", "Rehabilitative"],
    "Dermatology":       ["Diagnostic", "Therapeutic", "Preventive", "Consultation"],
    "Gastroenterology":  ["Diagnostic", "Therapeutic", "Surgical", "Consultation"],
    "Neurology":         ["Diagnostic", "Therapeutic", "Consultation", "Rehabilitative"],
    "Urology":           ["Diagnostic", "Therapeutic", "Surgical", "Consultation"],
    "Pulmonology":       ["Diagnostic", "Therapeutic", "Consultation", "Rehabilitative"],
    "General Surgery":   ["Diagnostic", "Surgical", "Therapeutic", "Consultation"],
    "Internal Medicine": ["Diagnostic", "Therapeutic", "Preventive", "Consultation"],
    "Family Medicine":   ["Diagnostic", "Therapeutic", "Preventive", "Consultation"],
}

# Base expected-pct distributions per specialty (over its authorised categories).
# Each specialty's values sum to 100.
BASE_DISTRIBUTIONS = {
    "Cardiology":        {"Diagnostic": 35, "Therapeutic": 28, "Surgical": 22, "Consultation": 15},
    "Orthopedics":       {"Diagnostic": 25, "Therapeutic": 23, "Surgical": 37, "Rehabilitative": 15},
    "Dermatology":       {"Diagnostic": 38, "Therapeutic": 30, "Preventive": 18, "Consultation": 14},
    "Gastroenterology":  {"Diagnostic": 33, "Therapeutic": 27, "Surgical": 25, "Consultation": 15},
    "Neurology":         {"Diagnostic": 36, "Therapeutic": 26, "Consultation": 18, "Rehabilitative": 20},
    "Urology":           {"Diagnostic": 32, "Therapeutic": 28, "Surgical": 26, "Consultation": 14},
    "Pulmonology":       {"Diagnostic": 34, "Therapeutic": 30, "Consultation": 20, "Rehabilitative": 16},
    "General Surgery":   {"Diagnostic": 20, "Surgical": 42, "Therapeutic": 24, "Consultation": 14},
    "Internal Medicine": {"Diagnostic": 34, "Therapeutic": 30, "Preventive": 22, "Consultation": 14},
    "Family Medicine":   {"Diagnostic": 30, "Therapeutic": 28, "Preventive": 26, "Consultation": 16},
}

# Region perturbation seeds (fixed deltas added before re-normalizing)
REGION_DELTAS = {
    "Northeast":  {"Diagnostic": 2, "Therapeutic": -1, "Surgical": 1, "Preventive": -1, "Consultation": 0, "Rehabilitative": -1},
    "Southeast":  {"Diagnostic": -1, "Therapeutic": 2, "Surgical": -1, "Preventive": 1, "Consultation": 0, "Rehabilitative": -1},
    "Midwest":    {"Diagnostic": 0, "Therapeutic": 0, "Surgical": -1, "Preventive": 2, "Consultation": 1, "Rehabilitative": -2},
    "West":       {"Diagnostic": -2, "Therapeutic": 1, "Surgical": 2, "Preventive": -1, "Consultation": 1, "Rehabilitative": -1},
    "Southwest":  {"Diagnostic": 1, "Therapeutic": -2, "Surgical": -1, "Preventive": 0, "Consultation": -1, "Rehabilitative": 3},
}

DEMOGRAPHIC_RANGES = {
    "High":   {"min_age": 30, "max_age": 75},
    "Medium": {"min_age": 20, "max_age": 80},
    "Low":    {"min_age": 5,  "max_age": 90},
}

SCORING_WEIGHTS = {
    "frequency_deviation":     0.25,
    "out_of_scope_rate":       0.20,
    "denial_rate_deviation":   0.20,
    "adjustment_rate":         0.15,
    "demographic_anomaly_rate": 0.20,
}

THRESHOLDS = {
    "flag_threshold":  0.10,
    "high_priority":   0.30,
    "medium_priority": 0.20,
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _regional_benchmark(specialty, region):
    """Return {category: expected_pct} for (specialty, region), summing to 100."""
    base = BASE_DISTRIBUTIONS[specialty].copy()
    deltas = REGION_DELTAS[region]
    for cat in base:
        base[cat] += deltas.get(cat, 0)
        base[cat] = max(base[cat], 1)
    total = sum(base.values())
    return {c: round(v / total * 100, 2) for c, v in base.items()}


def _generate_providers(n, fake):
    providers = []
    for i in range(n):
        providers.append({
            "provider_id": f"PRV{i + 1:04d}",
            "name": fake.name(),
            "specialty": SPECIALTIES[i % len(SPECIALTIES)],
            "region": REGIONS[i % len(REGIONS)],
            "npi_number": f"NPI{1000000 + i}",
        })
    return providers


def _generate_patients(n, fake):
    patients = []
    for i in range(n):
        patients.append({
            "patient_id": f"PAT{i + 1:05d}",
            "name": fake.name(),
            "age": random.randint(2, 95),
            "gender": random.choice(["M", "F"]),
            "insurance_type": random.choice(["Medicare", "Medicaid", "Private", "Self-Pay"]),
        })
    return patients


def _generate_procedures(n):
    """Generate n procedure codes spread evenly across categories."""
    procedures = []
    descs = {
        "Diagnostic":     ["blood panel", "imaging scan", "biopsy analysis", "stress test", "ultrasound exam",
                           "CT scan", "MRI scan", "X-ray study", "endoscopy", "echocardiogram"],
        "Therapeutic":    ["infusion therapy", "radiation treatment", "physical therapy session", "injection therapy",
                           "wound care", "chemotherapy cycle", "dialysis session", "laser therapy", "phototherapy",
                           "occupational therapy"],
        "Surgical":       ["laparoscopic procedure", "arthroscopic repair", "excision", "bypass graft",
                           "implant placement", "debridement", "fusion surgery", "resection", "transplant prep",
                           "stent insertion"],
        "Preventive":     ["vaccination", "screening exam", "wellness checkup", "risk assessment",
                           "genetic counseling", "nutritional consult", "immunization series", "health education",
                           "preventive scan", "lifestyle coaching"],
        "Consultation":   ["initial consult", "follow-up consult", "second opinion", "telehealth visit",
                           "care coordination", "referral evaluation", "discharge planning", "case review",
                           "peer consult", "multidisciplinary review"],
        "Rehabilitative": ["gait training", "range-of-motion therapy", "speech therapy", "cognitive rehab",
                           "cardiac rehab", "pulmonary rehab", "aquatic therapy", "prosthetic fitting",
                           "balance training", "neuromuscular re-education"],
    }
    cat_list = PROCEDURE_CATEGORIES
    for i in range(n):
        cat = cat_list[i % len(cat_list)]
        complexity = ["Low", "Medium", "High"][i % 3]
        base_cost = {"Low": 80 + (i * 7) % 120,
                     "Medium": 250 + (i * 13) % 550,
                     "High": 900 + (i * 17) % 2100}[complexity]
        desc_pool = descs[cat]
        desc = desc_pool[i % len(desc_pool)]
        procedures.append({
            "procedure_code": f"CPT{10000 + i}",
            "description": desc,
            "category": cat,
            "base_cost": round(float(base_cost), 2),
            "complexity_level": complexity,
        })
    return procedures


def _assign_suspicious_flags(providers, rng):
    """Assign upcoding flags to ~35% of providers."""
    flags = {}
    for p in providers:
        pid = p["provider_id"]
        r = rng.random()
        f = []
        if r < 0.08:
            f = ["freq_deviation", "out_of_scope", "high_denial"]
        elif r < 0.16:
            f = ["freq_deviation", "out_of_scope"]
        elif r < 0.22:
            f = ["freq_deviation", "high_denial"]
        elif r < 0.28:
            f = ["out_of_scope", "high_denial"]
        elif r < 0.35:
            f = ["freq_deviation"]
        elif r < 0.40:
            f = ["out_of_scope"]
        elif r < 0.45:
            f = ["high_denial"]
        flags[pid] = f
    return flags


def _generate_claims(providers, patients, procedures, suspicious_flags, rng, n_claims):
    """Generate claims with planted patterns for suspicious providers."""
    proc_by_cat = {}
    for pr in procedures:
        proc_by_cat.setdefault(pr["category"], []).append(pr)

    all_cats = PROCEDURE_CATEGORIES

    # Distribute claims across providers
    n_prov = len(providers)
    base_per = n_claims // n_prov
    remainder = n_claims - base_per * n_prov
    counts = [base_per] * n_prov
    for i in range(remainder):
        counts[i] += 1
    rng.shuffle(counts)

    claims = []
    claim_id = 1
    for idx, prov in enumerate(providers):
        pid = prov["provider_id"]
        spec = prov["specialty"]
        n_c = counts[idx]
        flags = suspicious_flags.get(pid, [])
        auth_cats = SPECIALTY_SCOPE[spec]

        for _ in range(n_c):
            # Choose category
            if "out_of_scope" in flags and rng.random() < 0.25:
                # Pick a non-authorised category
                non_auth = [c for c in all_cats if c not in auth_cats]
                cat = rng.choice(non_auth) if non_auth else rng.choice(auth_cats)
            elif "freq_deviation" in flags and rng.random() < 0.40:
                # Over-represent Surgical or Therapeutic (typically expensive)
                expensive = [c for c in ["Surgical", "Therapeutic"] if c in auth_cats]
                cat = rng.choice(expensive) if expensive else rng.choice(auth_cats)
            else:
                cat = rng.choice(auth_cats)

            # Pick a procedure in that category
            pool = proc_by_cat.get(cat, proc_by_cat["Diagnostic"])
            proc = rng.choice(pool)

            # Pick a patient
            pat = rng.choice(patients)

            # Determine billed amount (suspicious providers may inflate)
            base = proc["base_cost"]
            if "freq_deviation" in flags and rng.random() < 0.3:
                multiplier = rng.uniform(1.3, 2.0)
            else:
                multiplier = rng.uniform(0.85, 1.25)
            billed = round(base * multiplier, 2)

            # Determine approval status
            if "high_denial" in flags:
                denied = rng.random() < 0.35
            else:
                denied = rng.random() < 0.10
            status = "Denied" if denied else "Approved"
            denial_reason = ""
            if denied:
                denial_reason = rng.choice([
                    "Medical necessity not established",
                    "Procedure not covered under plan",
                    "Duplicate claim submission",
                    "Insufficient documentation",
                    "Out-of-network provider",
                    "Pre-authorization not obtained",
                ])

            claim_date = f"2025-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}"

            claims.append({
                "claim_id": f"CLM{claim_id:06d}",
                "provider_id": pid,
                "patient_id": pat["patient_id"],
                "procedure_code": proc["procedure_code"],
                "billed_amount": billed,
                "claim_date": claim_date,
                "status": status,
                "denial_reason": denial_reason,
            })
            claim_id += 1

    return claims


def _assign_peer_groups(providers, claims):
    """Assign peer groups based on specialty + volume tier."""
    claim_counts = {}
    for c in claims:
        claim_counts[c["provider_id"]] = claim_counts.get(c["provider_id"], 0) + 1

    # Group by specialty, split into HIGH/LOW by median claim count
    spec_providers = {}
    for p in providers:
        spec_providers.setdefault(p["specialty"], []).append(p["provider_id"])

    peer_groups = {}
    for spec, pids in spec_providers.items():
        counts = sorted([(claim_counts.get(pid, 0), pid) for pid in pids])
        mid = len(counts) // 2
        abbrev = spec[:4].upper()
        for i, (_, pid) in enumerate(counts):
            tier = "HIGH" if i >= mid else "LOW"
            peer_groups[pid] = f"{abbrev}_{tier}"
    return peer_groups


# ── Workspace file generators ─────────────────────────────────────────────────

def _write_audit_config(workspace):
    config = {
        "scoring_weights": SCORING_WEIGHTS,
        "thresholds": THRESHOLDS,
        "demographic_ranges": DEMOGRAPHIC_RANGES,
        "output": {
            "file_name": "audit_list.csv",
            "columns": [
                "provider_id", "provider_name", "specialty",
                "composite_risk_score", "frequency_deviation",
                "out_of_scope_rate", "denial_rate_deviation",
                "adjustment_rate", "demographic_anomaly_rate", "priority",
            ],
            "sort_by": "composite_risk_score",
            "sort_order": "descending",
            "decimal_places": 4,
        },
    }
    with open(os.path.join(workspace, "audit_config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def _write_specialty_scope(workspace):
    with open(os.path.join(workspace, "specialty_scope.json"), "w") as f:
        json.dump(SPECIALTY_SCOPE, f, indent=2)


def _write_methodology(workspace):
    """Fixed methodology document describing the audit computation rules."""
    text = """# Upcoding Audit Methodology

This document is the authoritative specification for the provider audit.
Every provider in the registry with at least one claim must be scored.

## Data sources

- `audit_config.yaml` — scoring weights, flagging thresholds, demographic
  age ranges per procedure complexity level, and the output specification.
- `specialty_scope.json` — the procedure categories each medical specialty
  is authorized to bill.
- `benchmark_data_*.csv` — regional billing benchmarks: for every
  combination of region, specialty, and procedure category, the expected
  percentage of claims in that category. May be split across multiple
  files; consolidate all of them.
- `provider_supplement_*.csv` — each provider's assigned peer group, years
  in practice, and certification level. May be split across multiple
  files; consolidate all of them.
- `historical_adjustments_*.csv` — past instances where a provider's claim
  was downcoded or otherwise modified. May be split across multiple files;
  consolidate all of them. Each row is one adjustment record.
- Provider, claim, procedure, and patient records come from the network's
  claims database.

## Risk components

Compute the following five components for every provider. A provider's
"total claims" always means the number of claims billed by that provider.

1. **frequency_deviation** — consider only the provider's claims whose
   procedure category is among the categories authorized for the
   provider's specialty. For each authorized category, compute the actual
   percentage: (claims in that category / total authorized-category
   claims) x 100. Compare it against the benchmark expected percentage
   for the provider's region, specialty, and that category. Sum every
   positive difference where actual exceeds expected, then divide the sum
   by one hundred. If the provider has no claims in authorized
   categories, the component is 0.
2. **out_of_scope_rate** — the fraction of the provider's total claims
   whose procedure category is NOT authorized for the provider's
   specialty.
3. **denial_rate_deviation** — the provider's denial rate (denied claims
   / total claims) minus the average denial rate of all providers
   assigned to the same peer group, floored at zero. The peer group
   average is the unweighted mean of the per-provider denial rates across
   every provider in that group.
4. **adjustment_rate** — the number of historical adjustment records for
   the provider divided by the provider's total claims.
5. **demographic_anomaly_rate** — the share of the provider's claims where
   the patient's age falls outside the typical range for the billed
   procedure's complexity level, i.e. age is strictly below `min_age` or
   strictly above `max_age` for that complexity level. Ages equal to a
   boundary are within range.

## Composite score, flagging, and priority

Multiply each component by its weight from `scoring_weights` and sum the
products to obtain the composite risk score. Round the composite and each
individual component to the number of decimal places given by
`output.decimal_places`, and apply the thresholds to the rounded
composite.

A provider is flagged for audit when the composite risk score is greater
than or equal to `flag_threshold`. Among flagged providers, a composite at
or above `high_priority` is assigned priority "High"; otherwise, at or
above `medium_priority`, priority "Medium"; all remaining flagged
providers receive priority "Low". Providers below `flag_threshold` are not
flagged and must not appear in the output.
"""
    with open(os.path.join(workspace, "audit_methodology.md"), "w") as f:
        f.write(text)


def _write_supplement_files(workspace, providers, peer_groups, n_files, rng):
    """Split provider supplementary info across n_files CSV files."""
    rows = []
    for p in providers:
        pid = p["provider_id"]
        rows.append({
            "provider_id": pid,
            "peer_group": peer_groups[pid],
            "years_in_practice": rng.randint(1, 35),
            "certification_level": rng.choice(["Board Certified", "Board Eligible", "Licensed"]),
        })
    rng.shuffle(rows)
    chunks = np.array_split(rows, n_files)
    for i, chunk in enumerate(chunks):
        df = pd.DataFrame(list(chunk))
        df.to_csv(os.path.join(workspace, f"provider_supplement_{i + 1:03d}.csv"), index=False)


def _write_benchmark_files(workspace, n_files):
    """Generate regional benchmark data split across n_files CSV files."""
    rows = []
    for region in REGIONS:
        for spec in SPECIALTIES:
            bench = _regional_benchmark(spec, region)
            for cat, pct in bench.items():
                rows.append({
                    "region": region,
                    "specialty": spec,
                    "procedure_category": cat,
                    "expected_pct": pct,
                })
    # Shuffle and split into n_files
    random.shuffle(rows)
    chunks = np.array_split(rows, n_files)
    for i, chunk in enumerate(chunks):
        df = pd.DataFrame(list(chunk))
        df.to_csv(os.path.join(workspace, f"benchmark_data_{i + 1:03d}.csv"), index=False)


def _write_adjustment_files(workspace, providers, claims, suspicious_flags, n_files, rng, procedures):
    """Generate historical adjustment records, more for suspicious providers."""
    proc_map = {p["procedure_code"]: p for p in procedures}
    adjustments = []
    adj_id = 1
    for c in claims:
        pid = c["provider_id"]
        flags = suspicious_flags.get(pid, [])
        # Suspicious providers have higher adjustment probability
        if flags and rng.random() < 0.20:
            prob = True
        elif not flags and rng.random() < 0.03:
            prob = True
        else:
            prob = False
        if prob:
            orig_code = c["procedure_code"]
            orig_proc = proc_map.get(orig_code)
            # Adjusted to a cheaper code in the same category
            cat = orig_proc["category"] if orig_proc else "Diagnostic"
            same_cat = [p for p in procedures if p["category"] == cat and p["base_cost"] < (orig_proc["base_cost"] if orig_proc else 500)]
            if same_cat:
                adj_proc = rng.choice(same_cat)
                adj_code = adj_proc["procedure_code"]
                cost_diff = round(c["billed_amount"] - adj_proc["base_cost"], 2)
            else:
                adj_code = orig_code
                cost_diff = round(c["billed_amount"] * 0.2, 2)
            adjustments.append({
                "adjustment_id": f"ADJ{adj_id:05d}",
                "provider_id": pid,
                "claim_id": c["claim_id"],
                "original_code": orig_code,
                "adjusted_code": adj_code,
                "cost_difference": max(cost_diff, 0),
                "adjustment_reason": rng.choice([
                    "Downcoded after review",
                    "Modifier mismatch",
                    "Level of service reduced",
                    "Bundled with other procedure",
                ]),
            })
            adj_id += 1
    rng.shuffle(adjustments)
    if not adjustments:
        # ensure at least one per file
        for i in range(n_files):
            adjustments.append({
                "adjustment_id": f"ADJ{adj_id:05d}",
                "provider_id": providers[i % len(providers)]["provider_id"],
                "claim_id": claims[i % len(claims)]["claim_id"],
                "original_code": claims[i % len(claims)]["procedure_code"],
                "adjusted_code": claims[i % len(claims)]["procedure_code"],
                "cost_difference": 0.0,
                "adjustment_reason": "No adjustment needed",
            })
            adj_id += 1
    chunks = np.array_split(adjustments, n_files)
    for i, chunk in enumerate(chunks):
        df = pd.DataFrame(list(chunk))
        df.to_csv(os.path.join(workspace, f"historical_adjustments_{i + 1:03d}.csv"), index=False)


# ── Main ───────────────────────────────────────────────────────────────────────

def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)
    rng = random.Random(42)

    os.makedirs(workspace, exist_ok=True)

    n_providers = SCALE["rows_per_table"]
    n_patients = SCALE["rows_per_table"] * 2
    n_procedures = max(SCALE["rows_per_table"], 60)
    n_claims = SCALE["rows_per_table"] * 8
    n_files = SCALE["num_workspace_files"]

    # ── Generate data ──────────────────────────────────────────────────────
    providers = _generate_providers(n_providers, fake)
    patients = _generate_patients(n_patients, fake)
    procedures = _generate_procedures(n_procedures)
    suspicious_flags = _assign_suspicious_flags(providers, rng)
    claims = _generate_claims(providers, patients, procedures, suspicious_flags, rng, n_claims)
    peer_groups = _assign_peer_groups(providers, claims)

    # ── Persist to SQLite ──────────────────────────────────────────────────
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS providers (
        provider_id TEXT PRIMARY KEY,
        name TEXT,
        specialty TEXT,
        region TEXT,
        npi_number TEXT
    )""")
    cur.executemany("INSERT INTO providers VALUES (?,?,?,?,?)",
                    [(p["provider_id"], p["name"], p["specialty"], p["region"], p["npi_number"])
                     for p in providers])

    cur.execute("""CREATE TABLE IF NOT EXISTS patients (
        patient_id TEXT PRIMARY KEY,
        name TEXT,
        age INTEGER,
        gender TEXT,
        insurance_type TEXT
    )""")
    cur.executemany("INSERT INTO patients VALUES (?,?,?,?,?)",
                    [(p["patient_id"], p["name"], p["age"], p["gender"], p["insurance_type"])
                     for p in patients])

    cur.execute("""CREATE TABLE IF NOT EXISTS procedures (
        procedure_code TEXT PRIMARY KEY,
        description TEXT,
        category TEXT,
        base_cost REAL,
        complexity_level TEXT
    )""")
    cur.executemany("INSERT INTO procedures VALUES (?,?,?,?,?)",
                    [(p["procedure_code"], p["description"], p["category"],
                      p["base_cost"], p["complexity_level"]) for p in procedures])

    cur.execute("""CREATE TABLE IF NOT EXISTS claims (
        claim_id TEXT PRIMARY KEY,
        provider_id TEXT,
        patient_id TEXT,
        procedure_code TEXT,
        billed_amount REAL,
        claim_date TEXT,
        status TEXT,
        denial_reason TEXT,
        FOREIGN KEY (provider_id) REFERENCES providers(provider_id),
        FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
        FOREIGN KEY (procedure_code) REFERENCES procedures(procedure_code)
    )""")
    cur.executemany("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?)",
                    [(c["claim_id"], c["provider_id"], c["patient_id"],
                      c["procedure_code"], c["billed_amount"], c["claim_date"],
                      c["status"], c["denial_reason"]) for c in claims])

    conn.commit()
    conn.close()

    # ── Generate workspace files ───────────────────────────────────────────
    # File distribution: ~3/8 supplement, ~3/8 benchmark, ~2/8 adjustments
    n_supplement = max(2, n_files * 3 // 8)
    n_benchmark = max(2, n_files * 3 // 8)
    n_adjustment = n_files - n_supplement - n_benchmark
    n_adjustment = max(1, n_adjustment)

    _write_supplement_files(workspace, providers, peer_groups, n_supplement, rng)
    _write_benchmark_files(workspace, n_benchmark)
    _write_adjustment_files(workspace, providers, claims, suspicious_flags, n_adjustment, rng, procedures)

    # Fixed config files (not counted in SCALE)
    _write_audit_config(workspace)
    _write_specialty_scope(workspace)
    _write_methodology(workspace)

    print(f"Database written to {db_path}")
    print(f"Workspace populated at {workspace}/ "
          f"({n_supplement} supplement + {n_benchmark} benchmark + {n_adjustment} adjustment "
          f"+ 3 config files)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
