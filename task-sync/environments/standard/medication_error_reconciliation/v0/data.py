#!/usr/bin/env python3
"""Generate medication reconciliation task data."""

import argparse
import sqlite3
import os
import json
import csv
import numpy as np
import pandas as pd
from faker import Faker
import yaml
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 80,
    "num_workspace_files": 8,
}

RECONCILIATION_DATE = "2026-04-21"

DRUG_CLASSES = [
    "Penicillins", "Cephalosporins", "Sulfonamides", "Fluoroquinolones",
    "Opioids", "NSAIDs", "ACE_Inhibitors", "Statins",
    "Beta_Blockers", "Benzodiazepines",
]

WARDS = ["A", "B", "C", "D"]
ROUTES = ["oral", "intravenous", "intramuscular", "subcutaneous"]
SHIFT_TEMPLATES = [("06:00:00", "14:00:00"), ("14:00:00", "22:00:00")]
SEVERITY_OPTIONS = ["mild", "moderate", "severe"]
REACTION_OPTIONS = ["rash", "anaphylaxis", "nausea", "swelling",
                    "breathing_difficulty", "hives"]
STANDARD_DOSES = [25, 50, 100, 150, 200, 250, 500, 750, 1000]

MED_NAMES = {
    "Penicillins": [
        ("Amoxicillin", "Amoxil"), ("Ampicillin", "Principen"),
        ("Penicillin_V", "Veetids"), ("Piperacillin", "Pipracil"),
        ("Nafcillin", "Unipen"), ("Oxacillin", "Bactocill"),
        ("Dicloxacillin", "Dynapen"), ("Ticarcillin", "Ticar"),
    ],
    "Cephalosporins": [
        ("Cephalexin", "Keflex"), ("Cefazolin", "Ancef"),
        ("Ceftriaxone", "Rocephin"), ("Cefuroxime", "Zinacef"),
        ("Cefepime", "Maxipime"), ("Cefdinir", "Omnicef"),
        ("Cefpodoxime", "Vantin"), ("Cefixime", "Suprax"),
    ],
    "Sulfonamides": [
        ("Sulfamethoxazole", "Gantanol"), ("Sulfasalazine", "Azulfidine"),
        ("Sulfadiazine", "Microsulfon"), ("Sulfacetamide", "Bleph"),
        ("Sulfapyridine", "Dagenan"), ("Sulfisoxazole", "Gantrisin"),
        ("TMP_SMX", "Bactrim"), ("Mafenide", "Sulfamylon"),
    ],
    "Fluoroquinolones": [
        ("Ciprofloxacin", "Cipro"), ("Levofloxacin", "Levaquin"),
        ("Moxifloxacin", "Avelox"), ("Ofloxacin", "Floxin"),
        ("Norfloxacin", "Noroxin"), ("Gemifloxacin", "Factive"),
        ("Delafloxacin", "Baxdela"), ("Prulifloxacin", "Quisnon"),
    ],
    "Opioids": [
        ("Morphine", "MS_Contin"), ("Oxycodone", "OxyContin"),
        ("Hydrocodone", "Vicodin"), ("Fentanyl", "Duragesic"),
        ("Codeine", "Tylenol_3"), ("Tramadol", "Ultram"),
        ("Hydromorphone", "Dilaudid"), ("Methadone", "Dolophine"),
    ],
    "NSAIDs": [
        ("Ibuprofen", "Advil"), ("Naproxen", "Aleve"),
        ("Diclofenac", "Voltaren"), ("Ketorolac", "Toradol"),
        ("Meloxicam", "Mobic"), ("Celecoxib", "Celebrex"),
        ("Indomethacin", "Indocin"), ("Piroxicam", "Feldene"),
    ],
    "ACE_Inhibitors": [
        ("Lisinopril", "Zestril"), ("Enalapril", "Vasotec"),
        ("Ramipril", "Altace"), ("Captopril", "Capoten"),
        ("Benazepril", "Lotensin"), ("Fosinopril", "Monopril"),
        ("Quinapril", "Accupril"), ("Perindopril", "Aceon"),
    ],
    "Statins": [
        ("Atorvastatin", "Lipitor"), ("Rosuvastatin", "Crestor"),
        ("Simvastatin", "Zocor"), ("Pravastatin", "Pravachol"),
        ("Lovastatin", "Mevacor"), ("Fluvastatin", "Lescol"),
        ("Pitavastatin", "Livalo"), ("Cerivastatin", "Baycol"),
    ],
    "Beta_Blockers": [
        ("Metoprolol", "Lopressor"), ("Atenolol", "Tenormin"),
        ("Propranolol", "Inderal"), ("Carvedilol", "Coreg"),
        ("Bisoprolol", "Zebeta"), ("Nebivolol", "Bystolic"),
        ("Labetalol", "Normodyne"), ("Sotalol", "Betapace"),
    ],
    "Benzodiazepines": [
        ("Diazepam", "Valium"), ("Lorazepam", "Ativan"),
        ("Alprazolam", "Xanax"), ("Clonazepam", "Klonopin"),
        ("Midazolam", "Versed"), ("Temazepam", "Restoril"),
        ("Oxazepam", "Serax"), ("Chlordiazepoxide", "Librium"),
    ],
}

DOSAGE_TOLERANCES = {
    "Penicillins": 10.0,
    "Cephalosporins": 10.0,
    "Sulfonamides": 15.0,
    "Fluoroquinolones": 10.0,
    "Opioids": 5.0,
    "NSAIDs": 15.0,
    "ACE_Inhibitors": 10.0,
    "Statins": 15.0,
    "Beta_Blockers": 10.0,
    "Benzodiazepines": 5.0,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)
    rng = np.random.RandomState(42)

    db_path = args.db_path
    workspace = args.workspace
    os.makedirs(workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # ==================================================================
    # 1. Generate Patients
    # ==================================================================
    patients = []
    for i in range(n_rows):
        ward = WARDS[i % len(WARDS)]
        patients.append({
            "patient_id": f"P{i + 1:04d}",
            "name": fake.name(),
            "dob": fake.date_of_birth(minimum_age=18, maximum_age=90).isoformat(),
            "ward": ward,
            "bed_number": f"{ward}-{(i // len(WARDS)) + 1:03d}",
        })
    patient_map = {p["patient_id"]: p for p in patients}

    # ==================================================================
    # 2. Generate Medications
    # ==================================================================
    medications = []
    med_id = 1
    per_class = n_rows // len(DRUG_CLASSES)
    extra_meds = n_rows % len(DRUG_CLASSES)
    for ci, dc in enumerate(DRUG_CLASSES):
        count = per_class + (1 if ci < extra_meds else 0)
        names = MED_NAMES[dc]
        for j in range(count):
            gname, bname = names[j % len(names)]
            variant = j // len(names) + 1
            if variant > 1:
                gname = f"{gname}_v{variant}"
                bname = f"{bname}_v{variant}"
            medications.append({
                "medication_id": f"M{med_id:04d}",
                "generic_name": gname,
                "brand_name": bname,
                "drug_class": dc,
                "standard_dose_mg": float(STANDARD_DOSES[j % len(STANDARD_DOSES)]),
                "route": ROUTES[j % len(ROUTES)],
            })
            med_id += 1
    med_map = {m["medication_id"]: m for m in medications}

    # ==================================================================
    # 3. Generate Nurses
    # ==================================================================
    n_nurses = max(20, n_rows // 4)
    nurses = []
    cert_levels = ["RN", "LPN", "NP", "BSN"]
    for i in range(n_nurses):
        nurses.append({
            "nurse_id": f"N{i + 1:04d}",
            "name": fake.name(),
            "certification_level": cert_levels[i % len(cert_levels)],
        })

    # ==================================================================
    # 4. Generate Nurse Shifts
    # ==================================================================
    recon_dt = datetime.strptime(RECONCILIATION_DATE, "%Y-%m-%d")
    date_range = [(recon_dt + timedelta(days=d)).strftime("%Y-%m-%d")
                  for d in range(-3, 4)]
    nurse_shifts = []
    shift_id = 1
    today_nurse_shifts = {}  # nurse_id -> [shift_dicts for recon date]

    for date_str in date_range:
        for ni, nurse in enumerate(nurses):
            # ~60 % chance of working any given day; force first half on recon date
            if rng.random() < 0.6 or (
                date_str == RECONCILIATION_DATE and ni < n_nurses
            ):
                st_idx = int(rng.randint(0, len(SHIFT_TEMPLATES)))
                start_t, end_t = SHIFT_TEMPLATES[st_idx]
                ward = WARDS[ni % len(WARDS)]
                shift = {
                    "shift_id": f"S{shift_id:04d}",
                    "nurse_id": nurse["nurse_id"],
                    "shift_date": date_str,
                    "start_time": start_t,
                    "end_time": end_t,
                    "assigned_ward": ward,
                }
                nurse_shifts.append(shift)
                if date_str == RECONCILIATION_DATE:
                    today_nurse_shifts.setdefault(nurse["nurse_id"], []).append(shift)
                shift_id += 1

    # Pad to n_rows if needed
    while len(nurse_shifts) < n_rows:
        ni = len(nurse_shifts) % n_nurses
        nurse = nurses[ni]
        date_str = date_range[len(nurse_shifts) % len(date_range)]
        st_idx = len(nurse_shifts) % len(SHIFT_TEMPLATES)
        start_t, end_t = SHIFT_TEMPLATES[st_idx]
        ward = WARDS[ni % len(WARDS)]
        shift = {
            "shift_id": f"S{shift_id:04d}",
            "nurse_id": nurse["nurse_id"],
            "shift_date": date_str,
            "start_time": start_t,
            "end_time": end_t,
            "assigned_ward": ward,
        }
        nurse_shifts.append(shift)
        if date_str == RECONCILIATION_DATE:
            today_nurse_shifts.setdefault(nurse["nurse_id"], []).append(shift)
        shift_id += 1

    # ==================================================================
    # 5. Generate Patient Allergies
    # ==================================================================
    patient_allergies = []
    allergy_id = 1
    patient_allergy_map = {}  # patient_id -> set(drug_class)

    for p in patients:
        n_allerg = int(rng.choice([0, 0, 1, 1, 1, 2]))
        if n_allerg > 0:
            classes = rng.choice(
                DRUG_CLASSES,
                size=min(n_allerg, len(DRUG_CLASSES)),
                replace=False,
            ).tolist()
            for dc in classes:
                patient_allergies.append({
                    "allergy_id": f"A{allergy_id:04d}",
                    "patient_id": p["patient_id"],
                    "allergen_class": dc,
                    "severity": str(rng.choice(SEVERITY_OPTIONS)),
                    "reaction_type": str(rng.choice(REACTION_OPTIONS)),
                })
                patient_allergy_map.setdefault(p["patient_id"], set()).add(dc)
                allergy_id += 1

    # Pad allergies
    pad_idx = 0
    while len(patient_allergies) < n_rows:
        p = patients[pad_idx % len(patients)]
        existing = patient_allergy_map.get(p["patient_id"], set())
        available = [dc for dc in DRUG_CLASSES if dc not in existing]
        if available:
            dc = available[pad_idx % len(available)]
            patient_allergies.append({
                "allergy_id": f"A{allergy_id:04d}",
                "patient_id": p["patient_id"],
                "allergen_class": dc,
                "severity": str(rng.choice(SEVERITY_OPTIONS)),
                "reaction_type": str(rng.choice(REACTION_OPTIONS)),
            })
            patient_allergy_map.setdefault(p["patient_id"], set()).add(dc)
            allergy_id += 1
        pad_idx += 1

    # ==================================================================
    # 6. Plan error indices for eMAR records
    # ==================================================================
    n_allergy_err = max(3, int(n_rows * 0.07))
    n_dosage_mm_err = max(3, int(n_rows * 0.07))
    n_unauth_err = max(3, int(n_rows * 0.06))
    n_missing_err = max(3, int(n_rows * 0.06))
    n_dosedev_err = max(3, int(n_rows * 0.07))
    total_err = (n_allergy_err + n_dosage_mm_err + n_unauth_err
                 + n_missing_err + n_dosedev_err)

    err_indices = rng.choice(n_rows, size=min(total_err, n_rows),
                             replace=False).tolist()
    ptr = 0
    allergy_err_idx = set(err_indices[ptr:ptr + n_allergy_err]); ptr += n_allergy_err
    dosage_mm_err_idx = set(err_indices[ptr:ptr + n_dosage_mm_err]); ptr += n_dosage_mm_err
    unauth_err_idx = set(err_indices[ptr:ptr + n_unauth_err]); ptr += n_unauth_err
    missing_err_idx = set(err_indices[ptr:ptr + n_missing_err]); ptr += n_missing_err
    dosedev_err_idx = set(err_indices[ptr:ptr + n_dosedev_err])

    deviation_factors = [0.5, 0.6, 1.5, 1.8, 2.0]

    # ==================================================================
    # 7. Generate eMAR, medication orders, and pharmacy dispensations
    # ==================================================================
    emar_records = []
    medication_orders = []
    pharmacy_dispensations = []
    used_pairs = set()  # (patient_id, medication_id)

    for i in range(n_rows):
        patient = patients[i % len(patients)]
        pid = patient["patient_id"]
        pward = patient["ward"]

        # --- Pick medication ---
        if i in allergy_err_idx:
            p_allergies = patient_allergy_map.get(pid, set())
            if not p_allergies:
                dc = medications[i % len(medications)]["drug_class"]
                patient_allergies.append({
                    "allergy_id": f"A{allergy_id:04d}",
                    "patient_id": pid,
                    "allergen_class": dc,
                    "severity": str(rng.choice(SEVERITY_OPTIONS)),
                    "reaction_type": str(rng.choice(REACTION_OPTIONS)),
                })
                patient_allergy_map.setdefault(pid, set()).add(dc)
                allergy_id += 1
                p_allergies = {dc}
            target_class = sorted(p_allergies)[int(rng.randint(0, len(p_allergies)))]
            matching = [m for m in medications if m["drug_class"] == target_class]
            med = matching[i % len(matching)]
        else:
            p_allergies = patient_allergy_map.get(pid, set())
            safe = [m for m in medications if m["drug_class"] not in p_allergies]
            if not safe:
                safe = medications
            med = safe[i % len(safe)]

        mid = med["medication_id"]
        pair = (pid, mid)
        attempts = 0
        while pair in used_pairs and attempts < len(medications):
            attempts += 1
            if i in allergy_err_idx:
                target_class = sorted(patient_allergy_map.get(pid, set()))[0]
                matching = [m for m in medications if m["drug_class"] == target_class]
                med = matching[(i + attempts) % len(matching)]
            else:
                p_allergies = patient_allergy_map.get(pid, set())
                safe = [m for m in medications if m["drug_class"] not in p_allergies]
                if not safe:
                    safe = medications
                med = safe[(i + attempts) % len(safe)]
            mid = med["medication_id"]
            pair = (pid, mid)

        if pair in used_pairs:
            for pi in range(len(patients)):
                alt_p = patients[(i + pi + 1) % len(patients)]
                pair = (alt_p["patient_id"], mid)
                if pair not in used_pairs:
                    patient = alt_p
                    pid = alt_p["patient_id"]
                    pward = alt_p["ward"]
                    break
        used_pairs.add((pid, mid))

        # --- Admin time ---
        hour = 7 + (i % 15)  # 07 .. 21
        minute = (i * 7 + 3) % 60
        admin_time_str = f"{hour:02d}:{minute:02d}:00"

        # --- Pick nurse ---
        if i in unauth_err_idx:
            off_duty = [n for n in nurses
                        if n["nurse_id"] not in today_nurse_shifts]
            if off_duty:
                nurse = off_duty[i % len(off_duty)]
            else:
                wrong = [
                    nid for nid, shifts in today_nurse_shifts.items()
                    if all(s["assigned_ward"] != pward for s in shifts)
                    or not any(
                        s["assigned_ward"] == pward
                        and s["start_time"] <= admin_time_str < s["end_time"]
                        for s in shifts
                    )
                ]
                if wrong:
                    nid_pick = wrong[i % len(wrong)]
                    nurse = next(n for n in nurses if n["nurse_id"] == nid_pick)
                else:
                    nurse = nurses[i % len(nurses)]
        else:
            valid = [
                nid for nid, shifts in today_nurse_shifts.items()
                if any(
                    s["assigned_ward"] == pward
                    and s["start_time"] <= admin_time_str < s["end_time"]
                    for s in shifts
                )
            ]
            if valid:
                nid_pick = valid[i % len(valid)]
                nurse = next(n for n in nurses if n["nurse_id"] == nid_pick)
            else:
                nurse = nurses[i % len(nurses)]
                if hour < 14:
                    s_st, s_en = "06:00:00", "14:00:00"
                else:
                    s_st, s_en = "14:00:00", "22:00:00"
                new_shift = {
                    "shift_id": f"S{shift_id:04d}",
                    "nurse_id": nurse["nurse_id"],
                    "shift_date": RECONCILIATION_DATE,
                    "start_time": s_st,
                    "end_time": s_en,
                    "assigned_ward": pward,
                }
                nurse_shifts.append(new_shift)
                today_nurse_shifts.setdefault(
                    nurse["nurse_id"], []).append(new_shift)
                shift_id += 1

        nid = nurse["nurse_id"]

        # --- Doses ---
        standard_dose = med["standard_dose_mg"]
        prescribed_dose = standard_dose

        if i in dosedev_err_idx:
            factor = deviation_factors[i % len(deviation_factors)]
            administered_dose = round(prescribed_dose * factor, 1)
        else:
            administered_dose = prescribed_dose

        scheduled_time = f"{RECONCILIATION_DATE} {hour:02d}:{minute:02d}:00"
        admin_offset = int(rng.randint(0, 10))
        administered_time = (
            f"{RECONCILIATION_DATE} "
            f"{hour:02d}:{(minute + admin_offset) % 60:02d}:00"
        )

        emar_records.append({
            "emar_id": f"E{i + 1:04d}",
            "patient_id": pid,
            "medication_id": mid,
            "nurse_id": nid,
            "scheduled_time": scheduled_time,
            "administered_time": administered_time,
            "dose_mg": float(administered_dose),
            "status": "administered",
        })

        medication_orders.append({
            "order_id": f"O{i + 1:04d}",
            "patient_id": pid,
            "medication_id": mid,
            "prescribed_dose_mg": float(prescribed_dose),
            "frequency": str(rng.choice([
                "once_daily", "twice_daily", "three_times_daily",
                "every_6h", "every_8h",
            ])),
            "route": med["route"],
            "prescriber": f"Dr. {fake.last_name()}",
            "order_datetime": f"{RECONCILIATION_DATE} 06:00:00",
        })

        # --- Pharmacy dispensation ---
        if i not in missing_err_idx:
            if i in dosage_mm_err_idx:
                mm_factor = deviation_factors[i % len(deviation_factors)]
                dispensed_dose = round(administered_dose * mm_factor, 1)
            else:
                dispensed_dose = administered_dose
            disp_hour = max(6, hour - int(rng.randint(0, 3)))
            pharmacy_dispensations.append({
                "dispensation_id": f"D{i + 1:04d}",
                "patient_id": pid,
                "medication_id": mid,
                "dispensed_dose_mg": float(dispensed_dose),
                "dispensed_time": (
                    f"{RECONCILIATION_DATE} "
                    f"{disp_hour:02d}:{int(rng.randint(0, 59)):02d}:00"
                ),
                "pharmacist_id": f"PH{int(rng.randint(1, 6)):04d}",
            })

    # Pad pharmacy_dispensations to n_rows
    disp_counter = n_rows + 1
    used_disp_pairs = {(d["patient_id"], d["medication_id"])
                       for d in pharmacy_dispensations}
    while len(pharmacy_dispensations) < n_rows:
        p = patients[disp_counter % len(patients)]
        m = medications[(disp_counter * 3 + 7) % len(medications)]
        dp = (p["patient_id"], m["medication_id"])
        if dp not in used_disp_pairs and dp not in used_pairs:
            pharmacy_dispensations.append({
                "dispensation_id": f"D{disp_counter:04d}",
                "patient_id": p["patient_id"],
                "medication_id": m["medication_id"],
                "dispensed_dose_mg": float(m["standard_dose_mg"]),
                "dispensed_time": (
                    f"{RECONCILIATION_DATE} "
                    f"{int(rng.randint(6, 20)):02d}:"
                    f"{int(rng.randint(0, 59)):02d}:00"
                ),
                "pharmacist_id": f"PH{int(rng.randint(1, 6)):04d}",
            })
            used_disp_pairs.add(dp)
        disp_counter += 1

    # ==================================================================
    # 8. Write Database
    # ==================================================================
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE patients (
        patient_id TEXT PRIMARY KEY, name TEXT, dob TEXT,
        ward TEXT, bed_number TEXT)""")
    c.execute("""CREATE TABLE medications (
        medication_id TEXT PRIMARY KEY, generic_name TEXT, brand_name TEXT,
        drug_class TEXT, standard_dose_mg REAL, route TEXT)""")
    c.execute("""CREATE TABLE emar_records (
        emar_id TEXT PRIMARY KEY, patient_id TEXT, medication_id TEXT,
        nurse_id TEXT, scheduled_time TEXT, administered_time TEXT,
        dose_mg REAL, status TEXT,
        FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
        FOREIGN KEY (medication_id) REFERENCES medications(medication_id))""")
    c.execute("""CREATE TABLE pharmacy_dispensations (
        dispensation_id TEXT PRIMARY KEY, patient_id TEXT,
        medication_id TEXT, dispensed_dose_mg REAL, dispensed_time TEXT,
        pharmacist_id TEXT,
        FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
        FOREIGN KEY (medication_id) REFERENCES medications(medication_id))""")
    c.execute("""CREATE TABLE patient_allergies (
        allergy_id TEXT PRIMARY KEY, patient_id TEXT, allergen_class TEXT,
        severity TEXT, reaction_type TEXT,
        FOREIGN KEY (patient_id) REFERENCES patients(patient_id))""")
    c.execute("""CREATE TABLE nurse_shifts (
        shift_id TEXT PRIMARY KEY, nurse_id TEXT, shift_date TEXT,
        start_time TEXT, end_time TEXT, assigned_ward TEXT)""")

    for p in patients:
        c.execute("INSERT INTO patients VALUES (?,?,?,?,?)",
                  (p["patient_id"], p["name"], p["dob"],
                   p["ward"], p["bed_number"]))
    for m in medications:
        c.execute("INSERT INTO medications VALUES (?,?,?,?,?,?)",
                  (m["medication_id"], m["generic_name"], m["brand_name"],
                   m["drug_class"], m["standard_dose_mg"], m["route"]))
    for e in emar_records:
        c.execute("INSERT INTO emar_records VALUES (?,?,?,?,?,?,?,?)",
                  (e["emar_id"], e["patient_id"], e["medication_id"],
                   e["nurse_id"], e["scheduled_time"], e["administered_time"],
                   e["dose_mg"], e["status"]))
    for d in pharmacy_dispensations:
        c.execute("INSERT INTO pharmacy_dispensations VALUES (?,?,?,?,?,?)",
                  (d["dispensation_id"], d["patient_id"], d["medication_id"],
                   d["dispensed_dose_mg"], d["dispensed_time"],
                   d["pharmacist_id"]))
    for a in patient_allergies:
        c.execute("INSERT INTO patient_allergies VALUES (?,?,?,?,?)",
                  (a["allergy_id"], a["patient_id"], a["allergen_class"],
                   a["severity"], a["reaction_type"]))
    for s in nurse_shifts:
        c.execute("INSERT INTO nurse_shifts VALUES (?,?,?,?,?,?)",
                  (s["shift_id"], s["nurse_id"], s["shift_date"],
                   s["start_time"], s["end_time"], s["assigned_ward"]))

    conn.commit()
    conn.close()

    # ==================================================================
    # 9. Write Workspace Files
    # ==================================================================

    # --- Scalable: medication order batch CSV files ---
    orders_per_file = max(1, len(medication_orders) // n_files)
    for fi in range(n_files):
        start = fi * orders_per_file
        end = (start + orders_per_file) if fi < n_files - 1 else len(medication_orders)
        batch = medication_orders[start:end]
        fp = os.path.join(workspace, f"medication_orders_batch_{fi + 1:02d}.csv")
        with open(fp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "order_id", "patient_id", "medication_id",
                "prescribed_dose_mg", "frequency", "route",
                "prescriber", "order_datetime",
            ])
            w.writeheader()
            w.writerows(batch)

    # --- Fixed: formulary.json ---
    formulary = {}
    for m in medications:
        formulary[m["medication_id"]] = {
            "generic_name": m["generic_name"],
            "brand_name": m["brand_name"],
            "drug_class": m["drug_class"],
            "standard_dose_mg": m["standard_dose_mg"],
            "route": m["route"],
            "contraindicated_allergy_classes": [m["drug_class"]],
        }
    with open(os.path.join(workspace, "formulary.json"), "w") as f:
        json.dump(formulary, f, indent=2)

    # --- Fixed: dosage_tolerance.yaml ---
    tol_config = {
        "default_tolerance_percent": 10.0,
        "drug_class_tolerances": dict(DOSAGE_TOLERANCES),
    }
    with open(os.path.join(workspace, "dosage_tolerance.yaml"), "w") as f:
        yaml.dump(tol_config, f, default_flow_style=False)

    # --- Fixed: reconciliation_policy.txt ---
    policy = f"""Medication Reconciliation Policy

Error Type Definitions
---------------------

ALLERGY_CONFLICT: The administered medication belongs to a drug class matching
a documented patient allergy. Severity maps from allergy record severity:
severe -> CRITICAL, moderate -> HIGH, mild -> MEDIUM.

DOSAGE_MISMATCH: The pharmacy-dispensed dose differs from the eMAR-administered
dose beyond the drug-class tolerance threshold. Percentage deviation formula:
abs(administered_dose - dispensed_dose) / prescribed_dose * 100.
Deviation > 50% -> CRITICAL, 30-50% -> HIGH, threshold to 30% -> MEDIUM.

UNAUTHORIZED_ADMIN: The administering nurse either had no shift on the
reconciliation date, was assigned to a different ward than the patient, or the
administration time fell outside the nurse shift window. Always HIGH severity.
Coverage rule: start_time <= admin_time < end_time (string comparison on
HH:MM:SS values).

MISSING_DISPENSATION: An administered eMAR record has no matching pharmacy
dispensation (matched by patient_id AND medication_id on the reconciliation
date). Always HIGH severity.

DOSE_DEVIATION: The administered dose differs from the prescribed dose beyond
the drug-class tolerance. Formula:
abs(administered_dose - prescribed_dose) / prescribed_dose * 100.
Deviation > 50% -> CRITICAL, 30-50% -> HIGH, threshold to 30% -> MEDIUM.

Reconciliation Date: {RECONCILIATION_DATE}
"""
    with open(os.path.join(workspace, "reconciliation_policy.txt"), "w") as f:
        f.write(policy)

    # --- Fixed: nurse_certifications.json ---
    nurse_certs = {}
    for n in nurses:
        nurse_certs[n["nurse_id"]] = {
            "name": n["name"],
            "certification_level": n["certification_level"],
        }
    with open(os.path.join(workspace, "nurse_certifications.json"), "w") as f:
        json.dump(nurse_certs, f, indent=2)

    # ==================================================================
    # Summary
    # ==================================================================
    print(f"Database created at {db_path}")
    print(f"Workspace created at {workspace}")
    print(f"  {len(patients)} patients, {len(medications)} medications, "
          f"{len(nurses)} nurses")
    print(f"  {len(emar_records)} eMAR records, "
          f"{len(pharmacy_dispensations)} dispensations")
    print(f"  {len(patient_allergies)} allergy records, "
          f"{len(nurse_shifts)} nurse shift records")
    print(f"  {n_files} order batch files + 4 config files")
    print(f"  Errors: allergy={len(allergy_err_idx)}, "
          f"dosage_mm={len(dosage_mm_err_idx)}, "
          f"unauth={len(unauth_err_idx)}, "
          f"missing={len(missing_err_idx)}, "
          f"dose_dev={len(dosedev_err_idx)}")


if __name__ == "__main__":
    main()
