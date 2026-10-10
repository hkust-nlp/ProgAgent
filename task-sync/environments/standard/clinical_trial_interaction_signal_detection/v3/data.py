"""
Data generation for Clinical Trial DDI Signal Detection task.
Produces a SQLite database and workspace files for the evaluation environment.
"""

import os
import json
import csv
import sqlite3
import argparse
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 480,      # v3 = 8x base
    "num_workspace_files": 32,  # v3 = base + 3N
}

SEED = 42
NUM_COHORTS = 6
NUM_WEEKS = 4

DRUG_CATALOG = {
    "Warfarin":      {"typical_dose": 5,   "route": "oral"},
    "Metformin":     {"typical_dose": 500, "route": "oral"},
    "Lisinopril":    {"typical_dose": 10,  "route": "oral"},
    "Atorvastatin":  {"typical_dose": 20,  "route": "oral"},
    "Omeprazole":    {"typical_dose": 20,  "route": "oral"},
    "Amlodipine":    {"typical_dose": 5,   "route": "oral"},
    "Metoprolol":    {"typical_dose": 50,  "route": "oral"},
    "Sertraline":    {"typical_dose": 50,  "route": "oral"},
    "Gabapentin":    {"typical_dose": 300, "route": "oral"},
    "Ibuprofen":     {"typical_dose": 400, "route": "oral"},
    "Aspirin":       {"typical_dose": 81,  "route": "oral"},
    "Clopidogrel":   {"typical_dose": 75,  "route": "oral"},
    "Fluconazole":   {"typical_dose": 150, "route": "oral"},
    "Rifampin":      {"typical_dose": 600, "route": "oral"},
    "Carbamazepine": {"typical_dose": 200, "route": "oral"},
    "Phenytoin":     {"typical_dose": 100, "route": "oral"},
    "Erythromycin":  {"typical_dose": 250, "route": "oral"},
    "Ketoconazole":  {"typical_dose": 200, "route": "oral"},
    "Verapamil":     {"typical_dose": 120, "route": "oral"},
    "Simvastatin":   {"typical_dose": 20,  "route": "oral"},
}

# (drug_a, drug_b, interaction_type, risk_level, min_dose_a, min_dose_b)
DDI_PAIRS_DATA = [
    ("Warfarin",     "Aspirin",       "pharmacodynamic", "high",     2,   40),
    ("Warfarin",     "Ibuprofen",     "pharmacodynamic", "high",     2,   200),
    ("Warfarin",     "Fluconazole",   "pharmacokinetic", "high",     2,   100),
    ("Metformin",    "Ketoconazole",  "pharmacokinetic", "moderate", 250, 100),
    ("Atorvastatin", "Erythromycin",  "pharmacokinetic", "high",     10,  125),
    ("Atorvastatin", "Fluconazole",   "pharmacokinetic", "moderate", 10,  100),
    ("Sertraline",   "Ibuprofen",     "pharmacodynamic", "moderate", 25,  200),
    ("Clopidogrel",  "Omeprazole",    "pharmacokinetic", "moderate", 37,  10),
    ("Metoprolol",   "Verapamil",     "pharmacodynamic", "high",     25,  60),
    ("Amlodipine",   "Carbamazepine", "pharmacokinetic", "moderate", 2,   100),
    ("Phenytoin",    "Fluconazole",   "pharmacokinetic", "high",     50,  100),
    ("Rifampin",     "Warfarin",      "pharmacokinetic", "high",     300, 2),
    ("Simvastatin",  "Erythromycin",  "pharmacokinetic", "high",     10,  125),
    ("Warfarin",     "Erythromycin",  "pharmacokinetic", "moderate", 2,   125),
    ("Gabapentin",   "Ibuprofen",     "pharmacodynamic", "low",      150, 200),
]

AE_TYPES = [
    "headache", "nausea", "dizziness", "fatigue", "rash",
    "diarrhea", "insomnia", "elevated_liver_enzymes", "hypotension",
    "tachycardia", "bleeding", "muscle_pain", "joint_pain", "fever", "edema",
]

COHORT_DEFS = [
    (1, "Alpha Low-Dose",  "Examplezol", "Hypertension"),
    (2, "Beta Standard",   "Examplezol", "Type 2 Diabetes"),
    (3, "Gamma High-Dose", "Examplezol", "Chronic Pain"),
    (4, "Delta Extended",  "Trialopin",  "Cardiovascular Risk"),
    (5, "Epsilon Combo",   "Trialopin",  "Metabolic Syndrome"),
    (6, "Zeta Control",    "Trialopin",  "General Wellness"),
]

PK_NORMAL_RANGES = {
    "Examplezol": {"min_ng_ml": 50,  "max_ng_ml": 200},
    "Trialopin":  {"min_ng_ml": 30,  "max_ng_ml": 150},
}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _create_tables(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS cohorts (
        cohort_id INTEGER PRIMARY KEY,
        cohort_name TEXT NOT NULL,
        study_drug TEXT NOT NULL,
        target_indication TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS participants (
        participant_id TEXT PRIMARY KEY,
        cohort_id INTEGER NOT NULL,
        age INTEGER NOT NULL,
        sex TEXT NOT NULL,
        weight_kg REAL NOT NULL,
        enrollment_date TEXT NOT NULL,
        current_phase INTEGER NOT NULL,
        FOREIGN KEY (cohort_id) REFERENCES cohorts(cohort_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS concomitant_medications (
        med_id INTEGER PRIMARY KEY AUTOINCREMENT,
        participant_id TEXT NOT NULL,
        drug_name TEXT NOT NULL,
        dose_mg REAL NOT NULL,
        route TEXT NOT NULL,
        start_week INTEGER NOT NULL,
        end_week INTEGER,
        FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS adverse_events (
        ae_id INTEGER PRIMARY KEY AUTOINCREMENT,
        participant_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        severity_grade INTEGER NOT NULL,
        onset_week INTEGER NOT NULL,
        resolved INTEGER NOT NULL,
        description TEXT NOT NULL,
        FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS pk_samples (
        sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
        participant_id TEXT NOT NULL,
        week INTEGER NOT NULL,
        analyte TEXT NOT NULL,
        concentration_ng_ml REAL NOT NULL,
        time_post_dose_hr REAL NOT NULL,
        FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
    )""")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(db_path, workspace):
    rng = np.random.RandomState(SEED)
    fake = Faker()
    Faker.seed(SEED)
    np.random.seed(SEED)

    os.makedirs(workspace, exist_ok=True)

    n_participants = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # ---- Database --------------------------------------------------------
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    _create_tables(cur)

    # Cohorts (fixed size)
    for c in COHORT_DEFS:
        cur.execute("INSERT INTO cohorts VALUES (?,?,?,?)", c)

    # Participants
    participants = []
    for i in range(n_participants):
        pid = f"PT{i+1:04d}"
        cid = int(rng.choice(range(1, NUM_COHORTS + 1)))
        age = int(rng.randint(22, 76))
        sex = str(rng.choice(["M", "F"]))
        weight = round(float(rng.uniform(50, 120)), 1)
        edate = fake.date_between_dates(
            date_start=pd.Timestamp("2024-01-01"),
            date_end=pd.Timestamp("2024-03-01"),
        ).isoformat()
        phase = int(rng.choice([1, 2, 3], p=[0.3, 0.4, 0.3]))
        cur.execute("INSERT INTO participants VALUES (?,?,?,?,?,?,?)",
                    (pid, cid, age, sex, weight, edate, phase))
        participants.append({
            "participant_id": pid,
            "cohort_id": cid,
            "current_phase": phase,
        })

    # Concomitant medications  ── force DDI pairs for ~30 % of participants
    drug_names = list(DRUG_CATALOG.keys())
    pids_list = [p["participant_id"] for p in participants]
    pids_shuffled = pids_list.copy()
    rng.shuffle(pids_shuffled)
    n_ddi_forced = max(int(n_participants * 0.3), 6)
    ddi_pids = set(pids_shuffled[:n_ddi_forced])

    medications = []  # collector for site-report generation later

    for p in participants:
        pid = p["participant_id"]
        if pid in ddi_pids:
            pair_idx = int(rng.randint(0, len(DDI_PAIRS_DATA)))
            pair = DDI_PAIRS_DATA[pair_idx]
            drugs_to_assign = [pair[0], pair[1]]
            if rng.random() < 0.3:
                extras = [d for d in drug_names if d not in drugs_to_assign]
                drugs_to_assign.append(str(rng.choice(extras)))
        else:
            nd = int(rng.choice([1, 2, 3], p=[0.4, 0.4, 0.2]))
            drugs_to_assign = list(rng.choice(drug_names, size=nd, replace=False))

        for drug in drugs_to_assign:
            dose_mult = float(rng.choice([0.5, 1.0, 1.5, 2.0]))
            dose = round(DRUG_CATALOG[drug]["typical_dose"] * dose_mult, 1)
            route = DRUG_CATALOG[drug]["route"]
            start_week = int(rng.choice([1, 2]))
            ew_roll = float(rng.random())
            end_week = None if ew_roll < 0.6 else int(rng.choice([3, 4]))
            cur.execute(
                "INSERT INTO concomitant_medications "
                "(participant_id, drug_name, dose_mg, route, start_week, end_week) "
                "VALUES (?,?,?,?,?,?)",
                (pid, drug, dose, route, start_week, end_week),
            )
            medications.append({
                "participant_id": pid,
                "drug_name": drug,
                "dose_mg": dose,
                "start_week": start_week,
                "end_week": end_week,
            })

    # Adverse events  (at least rows_per_table rows, ~2x participants)
    n_aes = max(n_participants * 2, SCALE["rows_per_table"])
    for _ in range(n_aes):
        idx = int(rng.randint(0, len(participants)))
        pid = participants[idx]["participant_id"]
        ae_type = str(rng.choice(AE_TYPES))
        severity = int(rng.choice([1, 2, 3, 4, 5], p=[0.25, 0.30, 0.25, 0.15, 0.05]))
        week = int(rng.randint(1, NUM_WEEKS + 1))
        resolved = int(rng.choice([0, 1], p=[0.3, 0.7]))
        desc = f"{ae_type} reported in week {week}, grade {severity}"
        cur.execute(
            "INSERT INTO adverse_events "
            "(participant_id, event_type, severity_grade, onset_week, resolved, description) "
            "VALUES (?,?,?,?,?,?)",
            (pid, ae_type, severity, week, resolved, desc),
        )

    # PK samples (at least rows_per_table rows, ~2x participants)
    cohort_drug_map = {c[0]: c[2] for c in COHORT_DEFS}
    n_pk = max(n_participants * 2, SCALE["rows_per_table"])
    for _ in range(n_pk):
        idx = int(rng.randint(0, len(participants)))
        p = participants[idx]
        pid = p["participant_id"]
        analyte = cohort_drug_map[p["cohort_id"]]
        week = int(rng.randint(1, NUM_WEEKS + 1))
        pk_range = PK_NORMAL_RANGES[analyte]
        if rng.random() < 0.25:
            if rng.random() < 0.5:
                conc = round(float(rng.uniform(
                    pk_range["max_ng_ml"] * 1.3,
                    pk_range["max_ng_ml"] * 2.5)), 2)
            else:
                conc = round(float(rng.uniform(
                    pk_range["min_ng_ml"] * 0.1,
                    pk_range["min_ng_ml"] * 0.7)), 2)
        else:
            conc = round(float(rng.uniform(
                pk_range["min_ng_ml"], pk_range["max_ng_ml"])), 2)
        tph = float(rng.choice([0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]))
        cur.execute(
            "INSERT INTO pk_samples "
            "(participant_id, week, analyte, concentration_ng_ml, time_post_dose_hr) "
            "VALUES (?,?,?,?,?)",
            (pid, week, analyte, conc, tph),
        )

    conn.commit()
    conn.close()

    # ---- Workspace files -------------------------------------------------

    # 1. DDI reference  (fixed, CSV)
    with open(os.path.join(workspace, "ddi_reference.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["drug_a", "drug_b", "interaction_type", "risk_level",
                     "min_dose_a", "min_dose_b"])
        for row in DDI_PAIRS_DATA:
            w.writerow(row)

    # 2. Phase rules  (fixed, YAML ── written as a formatted string)
    phase_rules_yaml = """\
phases:
  1:
    name: "Phase I - Safety"
    ae_severity_threshold: 2
    pk_deviation_multiplier: 1.3
  2:
    name: "Phase II - Efficacy"
    ae_severity_threshold: 3
    pk_deviation_multiplier: 1.5
  3:
    name: "Phase III - Confirmatory"
    ae_severity_threshold: 3
    pk_deviation_multiplier: 1.8
"""
    with open(os.path.join(workspace, "phase_rules.yaml"), "w") as f:
        f.write(phase_rules_yaml)

    # 3. PK normal ranges  (fixed, JSON)
    with open(os.path.join(workspace, "pk_normal_ranges.json"), "w") as f:
        json.dump(PK_NORMAL_RANGES, f, indent=2)

    # 4. Flagging config  (fixed, JSON)
    flagging_config = {
        "cohort_flag_threshold": 2,
        "risk_level_weights": {"high": 3, "moderate": 2, "low": 1},
        "dose_adjustment_risk_elevation": True,
        "report_sort_order": ["week", "cohort_id", "participant_id"],
        "report_columns": [
            "week", "participant_id", "cohort_id", "drug_a", "drug_b",
            "risk_level", "max_ae_severity", "pk_deviation_pct", "flag_reason",
        ],
    }
    with open(os.path.join(workspace, "flagging_config.json"), "w") as f:
        json.dump(flagging_config, f, indent=2)

    # 5. Assessment guidelines  (fixed, TXT)
    guidelines = """\
Adverse Event Severity Grading Scale
=====================================
Grade 1: Mild - Awareness of symptoms, easily tolerated
Grade 2: Moderate - Discomfort, interference with usual activity
Grade 3: Severe - Significant interference, may require intervention
Grade 4: Life-threatening - Urgent intervention indicated
Grade 5: Fatal

PK Deviation Assessment
========================
A PK concentration is considered anomalous when it falls outside
the acceptable range defined by:
  Lower bound: min_ng_ml / pk_deviation_multiplier
  Upper bound: max_ng_ml * pk_deviation_multiplier

where min_ng_ml and max_ng_ml are the reference ranges for the analyte
and pk_deviation_multiplier is the phase-specific multiplier.

The pk_deviation_pct for the report is calculated as:
  If concentration > upper_bound: ((concentration - upper_bound) / upper_bound) * 100
  If concentration < lower_bound: ((lower_bound - concentration) / lower_bound) * 100
  Otherwise: 0.0

When multiple PK samples exist for a participant in a given week,
use the maximum pk_deviation_pct across all samples.

All pk_deviation_pct values should be rounded to 1 decimal place.
"""
    with open(os.path.join(workspace, "assessment_guidelines.txt"), "w") as f:
        f.write(guidelines)

    # 6. Site-report files  (scaling, CSV)
    meds_df = pd.DataFrame(medications)
    pids_with_meds = sorted(meds_df["participant_id"].unique())
    chunk = max(1, len(pids_with_meds) // n_files)

    for fi in range(n_files):
        start = fi * chunk
        end = (start + chunk) if fi < n_files - 1 else len(pids_with_meds)
        file_pids = pids_with_meds[start:end]
        if len(file_pids) == 0:
            file_pids = [pids_with_meds[fi % len(pids_with_meds)]]

        n_adj = int(rng.randint(3, 7))
        rows = []
        for _ in range(n_adj):
            pid = str(rng.choice(file_pids))
            pid_meds = meds_df[meds_df["participant_id"] == pid]
            if len(pid_meds) == 0:
                continue
            med_row = pid_meds.iloc[int(rng.randint(0, len(pid_meds)))]
            adj_week = int(rng.randint(1, NUM_WEEKS + 1))
            factor = float(rng.choice([0.25, 0.5, 0.75, 1.5, 2.0, 2.5]))
            adj_dose = round(float(med_row["dose_mg"]) * factor, 1)
            reason = str(rng.choice([
                "tolerability", "efficacy", "safety_concern", "protocol_amendment"
            ]))
            rows.append({
                "participant_id": pid,
                "drug_name": med_row["drug_name"],
                "adjusted_dose_mg": adj_dose,
                "adjustment_week": adj_week,
                "reason": reason,
            })

        pd.DataFrame(rows).to_csv(
            os.path.join(workspace, f"site_report_{fi+1:02d}.csv"), index=False
        )

    print(f"Database created at {db_path}")
    print(f"Workspace created at {workspace} with {n_files + 5} files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
