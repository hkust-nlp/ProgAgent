"""
Manufacturing Defect Analysis Task - Data Generator

Generates a database of assembly line sensor logs, component supplier batches,
inspection results, and operator shift schedules, plus workspace files with
calibration specs, defect severity rules, audit reports, and photo analysis data.
"""
import argparse
import os
import sqlite3
import json
import csv
import random
import numpy as np
from faker import Faker
from datetime import datetime, timedelta
from collections import defaultdict

try:
    import yaml
except ImportError:
    raise ImportError("PyYAML is required. Install with: pip install pyyaml")

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 20,
}

# =========================================================================
# Fixed constants
# =========================================================================
NUM_LINES = 6
NUM_SUPPLIERS = 8
NUM_OPERATORS = 15

LINE_IDS = [f"LINE-{i+1:03d}" for i in range(NUM_LINES)]
SUPPLIER_IDS = [f"SUP-{i+1:03d}" for i in range(NUM_SUPPLIERS)]

MACHINE_TYPE_MAP = {
    "LINE-001": "SMT_Placer",
    "LINE-002": "Reflow_Oven",
    "LINE-003": "Wave_Solder",
    "LINE-004": "AOI_Inspector",
    "LINE-005": "Press_Fit",
    "LINE-006": "CNC_Router",
}

SENSOR_TYPES = ["temperature", "vibration", "pressure", "humidity", "speed"]
COMPONENT_TYPES = [
    "capacitor", "resistor", "connector", "IC_chip",
    "inductor", "diode", "transistor", "relay",
]
DEFECT_TYPES = [
    "solder_bridge", "cold_joint", "missing_component",
    "misalignment", "crack", "contamination",
]
SHIFT_TYPES = ["morning", "afternoon", "night"]
CERT_LEVELS = ["junior", "standard", "senior", "expert"]

SUPPLIER_ROOT_CAUSES = ["material_flaw", "material_contamination"]
MACHINE_ROOT_CAUSES = ["thermal_damage", "mechanical_stress", "alignment_drift"]
OPERATOR_ROOT_CAUSES = ["handling_damage", "electrostatic_discharge"]

# Calibration specs: (machine_type, sensor_type) -> (nominal, min_val, max_val, unit)
CAL_SPECS = {
    ("SMT_Placer", "temperature"): (245.0, 230.0, 260.0, "celsius"),
    ("SMT_Placer", "vibration"): (1.2, 0.2, 2.2, "mm_s"),
    ("SMT_Placer", "pressure"): (101.3, 95.0, 108.0, "kPa"),
    ("SMT_Placer", "humidity"): (45.0, 30.0, 60.0, "pct"),
    ("SMT_Placer", "speed"): (4.0, 2.0, 6.0, "m_min"),
    ("Reflow_Oven", "temperature"): (260.0, 245.0, 275.0, "celsius"),
    ("Reflow_Oven", "vibration"): (0.8, 0.1, 1.5, "mm_s"),
    ("Reflow_Oven", "pressure"): (103.0, 97.0, 109.0, "kPa"),
    ("Reflow_Oven", "humidity"): (40.0, 25.0, 55.0, "pct"),
    ("Reflow_Oven", "speed"): (2.5, 1.0, 4.0, "m_min"),
    ("Wave_Solder", "temperature"): (255.0, 240.0, 270.0, "celsius"),
    ("Wave_Solder", "vibration"): (1.0, 0.2, 1.8, "mm_s"),
    ("Wave_Solder", "pressure"): (106.0, 100.0, 112.0, "kPa"),
    ("Wave_Solder", "humidity"): (42.0, 28.0, 56.0, "pct"),
    ("Wave_Solder", "speed"): (3.5, 1.5, 5.5, "m_min"),
    ("AOI_Inspector", "temperature"): (250.0, 235.0, 265.0, "celsius"),
    ("AOI_Inspector", "vibration"): (0.5, 0.05, 0.95, "mm_s"),
    ("AOI_Inspector", "pressure"): (101.3, 95.0, 108.0, "kPa"),
    ("AOI_Inspector", "humidity"): (50.0, 35.0, 65.0, "pct"),
    ("AOI_Inspector", "speed"): (2.0, 0.5, 3.5, "m_min"),
    ("Press_Fit", "temperature"): (248.0, 233.0, 263.0, "celsius"),
    ("Press_Fit", "vibration"): (2.0, 0.7, 3.3, "mm_s"),
    ("Press_Fit", "pressure"): (111.0, 105.0, 117.0, "kPa"),
    ("Press_Fit", "humidity"): (43.0, 28.0, 58.0, "pct"),
    ("Press_Fit", "speed"): (2.0, 0.5, 3.5, "m_min"),
    ("CNC_Router", "temperature"): (252.0, 237.0, 267.0, "celsius"),
    ("CNC_Router", "vibration"): (1.8, 0.5, 3.1, "mm_s"),
    ("CNC_Router", "pressure"): (101.3, 95.0, 108.0, "kPa"),
    ("CNC_Router", "humidity"): (45.0, 30.0, 60.0, "pct"),
    ("CNC_Router", "speed"): (5.0, 3.0, 7.0, "m_min"),
}

# Anomaly patterns (embedded in generation, not exposed to agent)
ANOMALOUS_LINES = {
    "LINE-002": "temperature",
    "LINE-005": "vibration",
}
ANOMALOUS_SUPPLIERS = {
    "SUP-003": "capacitor",
    "SUP-006": "connector",
}


# =========================================================================
# Database creation
# =========================================================================
def create_tables(conn):
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS assembly_lines (
            line_id TEXT PRIMARY KEY,
            line_name TEXT,
            machine_type TEXT,
            install_date TEXT,
            location TEXT
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id TEXT PRIMARY KEY,
            supplier_name TEXT,
            country TEXT,
            certification TEXT,
            contact_email TEXT
        );
        CREATE TABLE IF NOT EXISTS operators (
            operator_id TEXT PRIMARY KEY,
            operator_name TEXT,
            hire_date TEXT,
            certification_level TEXT,
            department TEXT
        );
        CREATE TABLE IF NOT EXISTS sensor_logs (
            log_id TEXT PRIMARY KEY,
            line_id TEXT,
            sensor_type TEXT,
            reading_value REAL,
            reading_unit TEXT,
            timestamp TEXT,
            FOREIGN KEY (line_id) REFERENCES assembly_lines(line_id)
        );
        CREATE TABLE IF NOT EXISTS component_batches (
            batch_id TEXT PRIMARY KEY,
            supplier_id TEXT,
            component_type TEXT,
            line_id TEXT,
            delivery_date TEXT,
            qty_delivered INTEGER,
            qty_rejected_incoming INTEGER,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
            FOREIGN KEY (line_id) REFERENCES assembly_lines(line_id)
        );
        CREATE TABLE IF NOT EXISTS inspection_results (
            inspection_id TEXT PRIMARY KEY,
            product_id TEXT,
            line_id TEXT,
            batch_id TEXT,
            inspection_date TEXT,
            result TEXT,
            defect_type TEXT,
            FOREIGN KEY (line_id) REFERENCES assembly_lines(line_id),
            FOREIGN KEY (batch_id) REFERENCES component_batches(batch_id)
        );
        CREATE TABLE IF NOT EXISTS operator_shifts (
            shift_id TEXT PRIMARY KEY,
            operator_id TEXT,
            operator_name TEXT,
            line_id TEXT,
            shift_date TEXT,
            shift_type TEXT,
            hours_worked REAL,
            FOREIGN KEY (operator_id) REFERENCES operators(operator_id),
            FOREIGN KEY (line_id) REFERENCES assembly_lines(line_id)
        );
    """)


# =========================================================================
# Fixed entity generators
# =========================================================================
def generate_assembly_lines(conn, fake):
    locations = [
        "Building A - Floor 1", "Building A - Floor 2",
        "Building B - Floor 1", "Building B - Floor 2",
        "Building C - Floor 1", "Building C - Floor 2",
    ]
    rows = []
    for i, lid in enumerate(LINE_IDS):
        mt = MACHINE_TYPE_MAP[lid]
        install = fake.date_between(start_date="-5y", end_date="-1y").isoformat()
        name = f"{mt.replace('_', ' ')} Line {i + 1}"
        rows.append((lid, name, mt, install, locations[i]))
    conn.executemany("INSERT INTO assembly_lines VALUES (?,?,?,?,?)", rows)
    return rows


def generate_suppliers(conn, fake):
    countries = [
        "Germany", "Japan", "China", "South Korea",
        "Taiwan", "USA", "Mexico", "Vietnam",
    ]
    certs = [
        "ISO_9001", "ISO_14001", "IATF_16949", "AS9100",
        "ISO_9001", "ISO_13485", "ISO_9001", "IATF_16949",
    ]
    rows = []
    for i, sid in enumerate(SUPPLIER_IDS):
        name = fake.company()
        rows.append((sid, name, countries[i], certs[i], fake.company_email()))
    conn.executemany("INSERT INTO suppliers VALUES (?,?,?,?,?)", rows)
    return rows


def generate_operators(conn, fake):
    depts = ["Assembly", "Quality", "Maintenance"]
    rows = []
    for i in range(NUM_OPERATORS):
        oid = f"OP-{i + 1:03d}"
        name = fake.name()
        hire = fake.date_between(start_date="-10y", end_date="-6m").isoformat()
        cert = random.choice(CERT_LEVELS)
        dept = random.choice(depts)
        rows.append((oid, name, hire, cert, dept))
    conn.executemany("INSERT INTO operators VALUES (?,?,?,?,?)", rows)
    return rows


# =========================================================================
# Scaled data generators
# =========================================================================
def generate_sensor_logs(conn, fake, n_base):
    """Generate 8 * n_base sensor log entries with planted anomalies."""
    n_logs = 8 * n_base
    rows = []
    base_date = datetime(2024, 1, 1)

    for i in range(n_logs):
        log_id = f"SL-{i + 1:06d}"
        line_id = random.choice(LINE_IDS)
        sensor_type = random.choice(SENSOR_TYPES)
        mt = MACHINE_TYPE_MAP[line_id]
        nom, mn, mx, unit = CAL_SPECS[(mt, sensor_type)]

        half_range = (mx - mn) / 2.0
        normal_std = half_range / 3.0

        if line_id in ANOMALOUS_LINES and sensor_type == ANOMALOUS_LINES[line_id]:
            shifted_mean = nom + half_range * 0.9
            reading = np.random.normal(shifted_mean, normal_std * 1.2)
        else:
            reading = np.random.normal(nom, normal_std)

        reading = round(float(reading), 2)
        ts = (base_date + timedelta(
            hours=random.randint(0, 24 * 90),
            minutes=random.randint(0, 59),
        )).isoformat()
        rows.append((log_id, line_id, sensor_type, reading, unit, ts))

    conn.executemany("INSERT INTO sensor_logs VALUES (?,?,?,?,?,?)", rows)
    return rows


def generate_component_batches(conn, fake, n_base):
    """Generate n_base component batch records with planted supplier defects."""
    rows = []
    base_date = datetime(2024, 1, 1)

    for i in range(n_base):
        batch_id = f"BATCH-{i + 1:06d}"
        supplier_id = random.choice(SUPPLIER_IDS)

        # Anomalous suppliers predominantly produce their problematic component
        if supplier_id in ANOMALOUS_SUPPLIERS and random.random() < 0.60:
            comp_type = ANOMALOUS_SUPPLIERS[supplier_id]
        else:
            comp_type = random.choice(COMPONENT_TYPES)

        line_id = random.choice(LINE_IDS)
        delivery = (base_date + timedelta(days=random.randint(0, 90))).date().isoformat()
        qty = random.randint(100, 1000)

        # Higher rejection rate for anomalous supplier + component combos
        if (supplier_id in ANOMALOUS_SUPPLIERS
                and comp_type == ANOMALOUS_SUPPLIERS[supplier_id]):
            reject_rate = random.uniform(0.07, 0.16)
        else:
            reject_rate = random.uniform(0.005, 0.03)

        qty_rejected = max(0, int(qty * reject_rate))
        rows.append((batch_id, supplier_id, comp_type, line_id, delivery, qty, qty_rejected))

    conn.executemany("INSERT INTO component_batches VALUES (?,?,?,?,?,?,?)", rows)
    return rows


def generate_inspection_results(conn, fake, n_base, batches):
    """Generate 2 * n_base inspection results correlated with anomaly patterns."""
    n_inspections = 2 * n_base
    rows = []
    base_date = datetime(2024, 1, 1)

    anomalous_lines_set = set(ANOMALOUS_LINES.keys())
    anomalous_sup_set = set(ANOMALOUS_SUPPLIERS.keys())

    # Build batch lookup by line
    batch_by_line = defaultdict(list)
    for b in batches:
        batch_by_line[b[3]].append(b)  # b[3] = line_id

    for i in range(n_inspections):
        insp_id = f"INS-{i + 1:06d}"
        prod_id = f"PROD-{i + 1:06d}"
        line_id = random.choice(LINE_IDS)

        # Pick a batch delivered to this line (fallback to any batch)
        line_batches = batch_by_line.get(line_id, [])
        if line_batches:
            batch = random.choice(line_batches)
        else:
            batch = random.choice(batches)

        batch_id = batch[0]
        supplier_id = batch[1]

        insp_date = (base_date + timedelta(
            days=random.randint(0, 90),
            hours=random.randint(0, 23),
        )).isoformat()

        is_anom_line = line_id in anomalous_lines_set
        is_anom_sup = supplier_id in anomalous_sup_set

        if is_anom_line and is_anom_sup:
            fail_prob = 0.35
        elif is_anom_line:
            fail_prob = 0.22
        elif is_anom_sup:
            fail_prob = 0.18
        else:
            fail_prob = 0.05

        if random.random() < fail_prob:
            result = "FAIL"
            defect = random.choice(DEFECT_TYPES)
        else:
            result = "PASS"
            defect = None

        rows.append((insp_id, prod_id, line_id, batch_id, insp_date, result, defect))

    conn.executemany("INSERT INTO inspection_results VALUES (?,?,?,?,?,?,?)", rows)
    return rows


def generate_operator_shifts(conn, fake, n_base, operators):
    """Generate n_base operator shift records."""
    hours_map = {"morning": 8.0, "afternoon": 8.0, "night": 10.0}
    rows = []
    base_date = datetime(2024, 1, 1)

    for i in range(n_base):
        shift_id = f"SH-{i + 1:06d}"
        op = random.choice(operators)
        op_id, op_name = op[0], op[1]
        line_id = random.choice(LINE_IDS)
        shift_date = (base_date + timedelta(days=random.randint(0, 90))).date().isoformat()
        shift_type = random.choice(SHIFT_TYPES)
        hours = round(hours_map[shift_type] + random.uniform(-0.5, 1.5), 1)
        rows.append((shift_id, op_id, op_name, line_id, shift_date, shift_type, hours))

    conn.executemany("INSERT INTO operator_shifts VALUES (?,?,?,?,?,?,?)", rows)
    return rows


# =========================================================================
# Workspace generators
# =========================================================================
def generate_calibration_specs_csv(workspace):
    """Write calibration_specs.csv -- expected sensor ranges per machine type."""
    path = os.path.join(workspace, "calibration_specs.csv")
    fieldnames = ["machine_type", "sensor_type", "nominal_value", "min_value", "max_value", "unit"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for (mt, st) in sorted(CAL_SPECS.keys()):
            nom, mn, mx, unit = CAL_SPECS[(mt, st)]
            w.writerow({
                "machine_type": mt,
                "sensor_type": st,
                "nominal_value": nom,
                "min_value": mn,
                "max_value": mx,
                "unit": unit,
            })


def generate_defect_severity_rules(workspace):
    """Write defect_severity_rules.yaml -- root cause classification."""
    rules = {
        "root_cause_categories": {
            "supplier": {
                "indicators": ["material_flaw", "material_contamination"],
                "description": "Defects originating from supplier component quality issues",
            },
            "machine": {
                "indicators": ["thermal_damage", "mechanical_stress", "alignment_drift"],
                "description": "Defects caused by machine calibration drift or mechanical wear",
            },
            "operator": {
                "indicators": ["handling_damage", "electrostatic_discharge"],
                "description": "Defects from operator handling or procedural errors",
            },
        },
        "actionable_categories": ["supplier", "machine"],
        "note": "Only supplier and machine categories generate corrective actions. Operator issues are logged but do not produce supplier_rework or machine_recalibration entries.",
    }
    path = os.path.join(workspace, "defect_severity_rules.yaml")
    with open(path, "w") as f:
        yaml.dump(rules, f, default_flow_style=False, sort_keys=False)


def generate_action_priority_config(workspace):
    """Write action_priority_config.json -- formulas, thresholds, output spec."""
    config = {
        "supplier_rework": {
            "trigger": "A supplier requires a rework action when its overall incoming defect rate exceeds the threshold.",
            "defect_rate_threshold_pct": 5.0,
            "severity_formula": "severity_score = defect_rate_pct * defect_rate_weight + audit_penalty",
            "audit_penalty_rule": "audit_penalty = max(0, audit_penalty_threshold - avg_audit_score) * audit_penalty_weight",
        },
        "machine_recalibration": {
            "trigger": "An assembly line requires recalibration when the anomaly rate of any of its sensor types exceeds the threshold.",
            "anomaly_rate_threshold_pct": 15.0,
            "severity_formula": "severity_score = max_anomaly_rate_pct * anomaly_rate_weight + drift_penalty",
            "drift_penalty_rule": "drift_penalty = max_drift_ratio * drift_penalty_weight, where max_drift_ratio is the highest drift_ratio recorded for the primary sensor type of that line across all calibration check files.",
        },
        "severity_weights": {
            "defect_rate_weight": 2.0,
            "audit_penalty_weight": 0.5,
            "anomaly_rate_weight": 1.5,
            "drift_penalty_weight": 3.0,
        },
        "audit_penalty_threshold": 70,
        "anomaly_definition": "A sensor reading is anomalous if it falls strictly below min_value or strictly above max_value from calibration_specs.csv for the corresponding machine_type and sensor_type.",
        "ranking_rule": "Sort all corrective actions by severity_score descending. Break ties by entity_id ascending.",
        "score_precision": 2,
        "output_file": "corrective_actions.csv",
        "output_columns": [
            "rank", "action_type", "entity_id", "root_cause",
            "severity_score", "affected_products", "recommended_action",
        ],
        "root_cause_format": {
            "supplier_rework": "Incoming defect rate: {defect_rate_pct:.1f}%; Primary component: {component}; Avg audit score: {avg_audit:.1f}",
            "machine_recalibration": "Sensor anomaly rate: {anomaly_rate_pct:.1f}%; Primary sensor: {sensor}; Max drift ratio: {drift:.2f}",
        },
        "recommended_action_format": {
            "supplier_rework": "Initiate rework program with {entity_id} targeting {primary_component} batches",
            "machine_recalibration": "Schedule recalibration for {primary_sensor} on {entity_id}",
        },
    }
    path = os.path.join(workspace, "action_priority_config.json")
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def generate_photo_analysis_files(workspace, n_files, inspections, batches, fake):
    """Generate photo analysis JSON files for failed inspections.

    Each file contains root_cause_indicator for a subset of failures.
    This information is NOT in the database -- workspace-only.
    """
    failures = [ins for ins in inspections if ins[5] == "FAIL"]
    batch_supplier = {b[0]: b[1] for b in batches}

    anomalous_sup_set = set(ANOMALOUS_SUPPLIERS.keys())
    anomalous_lines_set = set(ANOMALOUS_LINES.keys())

    entries = []
    for ins in failures:
        insp_id, _, line_id, batch_id, _, _, _ = ins
        supplier_id = batch_supplier.get(batch_id, "UNKNOWN")
        is_anom_line = line_id in anomalous_lines_set
        is_anom_sup = supplier_id in anomalous_sup_set

        r = random.random()
        if is_anom_line and is_anom_sup:
            if r < 0.45:
                indicator = random.choice(MACHINE_ROOT_CAUSES)
            elif r < 0.85:
                indicator = random.choice(SUPPLIER_ROOT_CAUSES)
            else:
                indicator = random.choice(OPERATOR_ROOT_CAUSES)
        elif is_anom_line:
            if r < 0.70:
                indicator = random.choice(MACHINE_ROOT_CAUSES)
            elif r < 0.85:
                indicator = random.choice(SUPPLIER_ROOT_CAUSES)
            else:
                indicator = random.choice(OPERATOR_ROOT_CAUSES)
        elif is_anom_sup:
            if r < 0.70:
                indicator = random.choice(SUPPLIER_ROOT_CAUSES)
            elif r < 0.85:
                indicator = random.choice(MACHINE_ROOT_CAUSES)
            else:
                indicator = random.choice(OPERATOR_ROOT_CAUSES)
        else:
            if r < 0.30:
                indicator = random.choice(SUPPLIER_ROOT_CAUSES)
            elif r < 0.60:
                indicator = random.choice(MACHINE_ROOT_CAUSES)
            else:
                indicator = random.choice(OPERATOR_ROOT_CAUSES)

        entries.append({
            "inspection_id": insp_id,
            "root_cause_indicator": indicator,
            "confidence": round(random.uniform(0.75, 0.99), 2),
            "visual_notes": fake.sentence(nb_words=8),
        })

    # Distribute entries across files
    random.shuffle(entries)
    chunks = [[] for _ in range(n_files)]
    for i, entry in enumerate(entries):
        chunks[i % n_files].append(entry)

    for idx, chunk in enumerate(chunks):
        path = os.path.join(workspace, f"photo_analysis_{idx + 1:03d}.json")
        with open(path, "w") as f:
            json.dump(chunk, f, indent=2)


def generate_delivery_reports(workspace, n_files, fake):
    """Generate delivery report CSVs with supplier audit scores.

    Audit scores are workspace-only -- not in the database.
    Anomalous suppliers consistently score below the penalty threshold.
    """
    anomalous_ranges = {"SUP-003": (52, 64), "SUP-006": (55, 67)}
    normal_range = (72, 95)
    base_date = datetime(2024, 1, 1)

    for idx in range(n_files):
        period_start = base_date + timedelta(days=idx * max(1, 90 // max(1, n_files)))
        rows = []
        for sid in SUPPLIER_IDS:
            lo, hi = anomalous_ranges.get(sid, normal_range)
            audit_score = round(random.uniform(lo, hi), 1)
            comp_type = random.choice(COMPONENT_TYPES)
            qty = random.randint(200, 2000)
            condition = random.choice(["A", "B", "C"])
            rows.append({
                "supplier_id": sid,
                "report_period": period_start.date().isoformat(),
                "component_type": comp_type,
                "qty_delivered": qty,
                "audit_score": audit_score,
                "condition_grade": condition,
            })

        path = os.path.join(workspace, f"delivery_report_{idx + 1:03d}.csv")
        fieldnames = ["supplier_id", "report_period", "component_type",
                       "qty_delivered", "audit_score", "condition_grade"]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)


def generate_calibration_checks(workspace, n_files, fake):
    """Generate calibration check YAML files with drift ratio measurements.

    Drift ratios are workspace-only. Anomalous lines show high drift on their
    problematic sensor type.
    """
    anomalous_drift = {
        "LINE-002": ("temperature", (1.8, 3.5)),
        "LINE-005": ("vibration", (1.5, 3.0)),
    }
    normal_drift_range = (0.02, 0.30)
    base_date = datetime(2024, 1, 1)

    for idx in range(n_files):
        check_date = (base_date + timedelta(
            days=idx * max(1, 90 // max(1, n_files))
        )).date().isoformat()

        measurements = []
        for lid in LINE_IDS:
            for st in SENSOR_TYPES:
                if lid in anomalous_drift and st == anomalous_drift[lid][0]:
                    lo, hi = anomalous_drift[lid][1]
                    drift = round(random.uniform(lo, hi), 2)
                else:
                    drift = round(random.uniform(*normal_drift_range), 2)
                measurements.append({
                    "line_id": lid,
                    "sensor_type": st,
                    "drift_ratio": drift,
                })

        data = {
            "check_date": check_date,
            "inspector_id": f"CAL-{random.randint(1, 5):03d}",
            "measurements": measurements,
        }
        path = os.path.join(workspace, f"calibration_check_{idx + 1:03d}.yaml")
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def generate_workspace(workspace, n_files, inspections, batches, fake):
    """Generate all workspace files: fixed configs + scalable data files."""
    # ---- Fixed configuration files (do not count toward SCALE) ----
    generate_calibration_specs_csv(workspace)
    generate_defect_severity_rules(workspace)
    generate_action_priority_config(workspace)

    # ---- Scalable data files ----
    n_photo = max(3, round(n_files * 0.4))
    n_delivery = max(2, round(n_files * 0.3))
    n_calibration = n_files - n_photo - n_delivery
    if n_calibration < 2:
        n_calibration = 2
        n_photo = n_files - n_delivery - n_calibration

    generate_photo_analysis_files(workspace, n_photo, inspections, batches, fake)
    generate_delivery_reports(workspace, n_delivery, fake)
    generate_calibration_checks(workspace, n_calibration, fake)


# =========================================================================
# Main
# =========================================================================
def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    create_tables(conn)

    # Fixed entities
    generate_assembly_lines(conn, fake)
    suppliers = generate_suppliers(conn, fake)
    operators = generate_operators(conn, fake)

    # Scaled data
    generate_sensor_logs(conn, fake, n_rows)
    batches = generate_component_batches(conn, fake, n_rows)
    inspections = generate_inspection_results(conn, fake, n_rows, batches)
    generate_operator_shifts(conn, fake, n_rows, operators)

    conn.commit()

    # Workspace
    generate_workspace(workspace, n_files, inspections, batches, fake)

    conn.close()
    print(f"Database created at {db_path}")
    print(f"Workspace created at {workspace} with {len(os.listdir(workspace))} files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
