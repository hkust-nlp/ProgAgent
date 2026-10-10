import argparse
import os
import sqlite3
import json
import random
import numpy as np
import pandas as pd
import yaml
from datetime import date, timedelta
from faker import Faker

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 10,
}

# ── Constants ──────────────────────────────────────────────────────────────────

TERRITORIES = [
    "APAC-N", "APAC-S", "APAC-O",
    "EMEA-W", "EMEA-E", "EMEA-A",
    "NA", "LATAM",
]

TERRITORY_MODIFIERS = {
    "APAC-N": 1.15, "APAC-S": 0.90, "APAC-O": 1.05,
    "EMEA-W": 1.20, "EMEA-E": 0.85, "EMEA-A": 0.75,
    "NA": 1.25, "LATAM": 0.80,
}

PRODUCT_CATEGORIES = ["Software", "Hardware", "Services", "Subscription"]
PARTNER_TIERS = ["Platinum", "Gold", "Silver", "Bronze"]
EXCEPTION_TYPES = [
    "under_reporting", "volume_mismatch",
    "unauthorized_territory", "late_payment", "documentation_gap",
]
SEVERITIES = ["critical", "high", "medium", "low"]


def quarter_for_date(d):
    q = (d.month - 1) // 3 + 1
    return f"Q{q}-{d.year}"


# ── Table creation ─────────────────────────────────────────────────────────────

def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS distributors (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            country TEXT NOT NULL,
            territory_code TEXT NOT NULL,
            partner_tier TEXT NOT NULL,
            registration_date TEXT NOT NULL,
            active INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_skus (
            id INTEGER PRIMARY KEY,
            sku_code TEXT NOT NULL UNIQUE,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL,
            unit_price REAL NOT NULL,
            base_royalty_pct REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS license_agreements (
            id INTEGER PRIMARY KEY,
            agreement_code TEXT NOT NULL UNIQUE,
            distributor_id INTEGER NOT NULL,
            territory_code TEXT NOT NULL,
            product_category TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            min_annual_volume INTEGER NOT NULL,
            royalty_discount_pct REAL NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (distributor_id) REFERENCES distributors(id)
        );
        CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY,
            distributor_id INTEGER NOT NULL,
            sku_id INTEGER NOT NULL,
            territory_code TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            ship_date TEXT NOT NULL,
            reported_royalty REAL NOT NULL,
            invoice_number TEXT NOT NULL UNIQUE,
            FOREIGN KEY (distributor_id) REFERENCES distributors(id),
            FOREIGN KEY (sku_id) REFERENCES product_skus(id)
        );
        CREATE TABLE IF NOT EXISTS audit_exceptions (
            id INTEGER PRIMARY KEY,
            distributor_id INTEGER NOT NULL,
            exception_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            finding_detail TEXT NOT NULL,
            audit_date TEXT NOT NULL,
            resolved INTEGER NOT NULL,
            FOREIGN KEY (distributor_id) REFERENCES distributors(id)
        );
    """)
    conn.commit()


# ── Data generation ────────────────────────────────────────────────────────────

def generate_data(rng, fake):
    rpt = SCALE["rows_per_table"]
    n_dist = rpt
    n_skus = rpt
    n_agreements = rpt * 2
    n_shipments = rpt * 5
    n_exceptions = rpt

    # ── Distributors ──
    distributors = []
    for i in range(n_dist):
        distributors.append({
            "id": i + 1,
            "name": fake.company(),
            "country": fake.country(),
            "territory_code": str(rng.choice(TERRITORIES)),
            "partner_tier": str(rng.choice(PARTNER_TIERS)),
            "registration_date": fake.date_between(
                start_date=date(2018, 1, 1), end_date=date(2022, 12, 31)
            ).isoformat(),
            "active": int(rng.random() > 0.1),
        })

    # ── Product SKUs ──
    skus = []
    for i in range(n_skus):
        skus.append({
            "id": i + 1,
            "sku_code": f"SKU-{1000 + i:04d}",
            "product_name": fake.catch_phrase(),
            "category": PRODUCT_CATEGORIES[i % len(PRODUCT_CATEGORIES)],
            "unit_price": round(float(rng.uniform(20, 500)), 2),
            "base_royalty_pct": round(float(rng.uniform(0.03, 0.15)), 4),
        })

    # ── License Agreements ──
    agreements = []
    for i in range(n_agreements):
        dist = distributors[i % n_dist]
        cat = str(rng.choice(PRODUCT_CATEGORIES))
        start = fake.date_between(start_date=date(2021, 1, 1),
                                  end_date=date(2023, 6, 30))
        duration_days = int(rng.choice([365, 730, 1095]))
        end = start + timedelta(days=duration_days)
        status = "active" if end >= date(2024, 6, 30) else "expired"
        if float(rng.random()) < 0.05:
            status = "suspended"
        agreements.append({
            "id": i + 1,
            "agreement_code": f"AGR-{2000 + i:05d}",
            "distributor_id": dist["id"],
            "territory_code": dist["territory_code"],
            "product_category": cat,
            "effective_date": start.isoformat(),
            "expiry_date": end.isoformat(),
            "min_annual_volume": int(rng.integers(100, 1000)),
            "royalty_discount_pct": round(float(rng.uniform(0, 15)), 2),
            "status": status,
        })

    # ── Determine leaky distributors (~30 % of active) ──
    active_ids = [d["id"] for d in distributors if d["active"]]
    n_leaky = max(3, len(active_ids) * 3 // 10)
    leaky_ids = set(rng.choice(active_ids, size=n_leaky, replace=False).tolist())

    # helpers
    sku_map = {s["id"]: s for s in skus}
    agr_idx = {}
    for a in agreements:
        key = (a["distributor_id"], a["territory_code"], a["product_category"])
        agr_idx.setdefault(key, []).append(a)

    def best_agreement(dist_id, terr, cat, ship_dt):
        for a in agr_idx.get((dist_id, terr, cat), []):
            if (a["status"] == "active"
                    and a["effective_date"] <= ship_dt <= a["expiry_date"]):
                return a
        return None

    # ── Shipments ──
    shipments = []
    for i in range(n_shipments):
        dist = distributors[i % n_dist]
        sku = skus[int(rng.integers(0, n_skus))]
        territory = dist["territory_code"]
        quantity = int(rng.integers(5, 300))
        ship_date = fake.date_between(start_date=date(2023, 1, 1),
                                      end_date=date(2024, 12, 31))
        ship_dt_str = ship_date.isoformat()

        t_mod = TERRITORY_MODIFIERS[territory]
        agr = best_agreement(dist["id"], territory, sku["category"], ship_dt_str)
        discount = agr["royalty_discount_pct"] / 100.0 if agr else 0.0
        expected = quantity * sku["unit_price"] * sku["base_royalty_pct"] * t_mod * (1 - discount)

        if dist["id"] in leaky_ids and float(rng.random()) < 0.4:
            factor = float(rng.uniform(0.50, 0.90))
            reported = round(expected * factor, 2)
        else:
            noise = float(rng.uniform(0.98, 1.02))
            reported = round(expected * noise, 2)

        shipments.append({
            "id": i + 1,
            "distributor_id": dist["id"],
            "sku_id": sku["id"],
            "territory_code": territory,
            "quantity": quantity,
            "ship_date": ship_dt_str,
            "reported_royalty": reported,
            "invoice_number": f"INV-{100000 + i:06d}",
        })

    # ── Audit Exceptions ──
    exceptions = []
    for i in range(n_exceptions):
        if float(rng.random()) < 0.6 and leaky_ids:
            dist_id = int(rng.choice(list(leaky_ids)))
        else:
            dist_id = int(rng.choice(active_ids))
        exceptions.append({
            "id": i + 1,
            "distributor_id": dist_id,
            "exception_type": str(rng.choice(EXCEPTION_TYPES)),
            "severity": str(rng.choice(SEVERITIES)),
            "finding_detail": fake.sentence(nb_words=12),
            "audit_date": fake.date_between(
                start_date=date(2023, 1, 1), end_date=date(2024, 12, 31)
            ).isoformat(),
            "resolved": int(float(rng.random()) > 0.6),
        })

    return distributors, skus, agreements, shipments, exceptions, leaky_ids


# ── DB insertion ───────────────────────────────────────────────────────────────

def insert_data(conn, distributors, skus, agreements, shipments, exceptions):
    c = conn.cursor()
    c.executemany(
        "INSERT INTO distributors VALUES (?,?,?,?,?,?,?)",
        [(d["id"], d["name"], d["country"], d["territory_code"],
          d["partner_tier"], d["registration_date"], d["active"])
         for d in distributors],
    )
    c.executemany(
        "INSERT INTO product_skus VALUES (?,?,?,?,?,?)",
        [(s["id"], s["sku_code"], s["product_name"], s["category"],
          s["unit_price"], s["base_royalty_pct"]) for s in skus],
    )
    c.executemany(
        "INSERT INTO license_agreements VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(a["id"], a["agreement_code"], a["distributor_id"], a["territory_code"],
          a["product_category"], a["effective_date"], a["expiry_date"],
          a["min_annual_volume"], a["royalty_discount_pct"], a["status"])
         for a in agreements],
    )
    c.executemany(
        "INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?)",
        [(s["id"], s["distributor_id"], s["sku_id"], s["territory_code"],
          s["quantity"], s["ship_date"], s["reported_royalty"], s["invoice_number"])
         for s in shipments],
    )
    c.executemany(
        "INSERT INTO audit_exceptions VALUES (?,?,?,?,?,?,?)",
        [(e["id"], e["distributor_id"], e["exception_type"], e["severity"],
          e["finding_detail"], e["audit_date"], e["resolved"])
         for e in exceptions],
    )
    conn.commit()


# ── Workspace generation ───────────────────────────────────────────────────────

def generate_workspace(workspace, distributors, skus, shipments, exceptions,
                       leaky_ids, rng, fake):
    os.makedirs(workspace, exist_ok=True)
    sku_map = {s["id"]: s for s in skus}

    # ── Fixed file 1: territory_modifiers.yaml ──
    with open(os.path.join(workspace, "territory_modifiers.yaml"), "w") as f:
        yaml.dump({"territory_modifiers": TERRITORY_MODIFIERS},
                  f, default_flow_style=False)

    # ── Fixed file 2: risk_scoring_policy.yaml ──
    policy = {
        "scoring_weights": {
            "leakage_amount": 0.25,
            "leakage_percentage": 0.20,
            "audit_severity": 0.20,
            "volume_gap": 0.15,
            "quantity_discrepancy": 0.20,
        },
        "severity_points": {
            "critical": 100,
            "high": 75,
            "medium": 50,
            "low": 25,
        },
        "risk_categories": {
            "critical": 80,
            "high": 60,
            "medium": 40,
            "low": 0,
        },
        "normalization": {
            "max_leakage_amount": 50000.0,
            "max_leakage_pct": 0.30,
            "max_volume_gap_pct": 0.50,
            "max_quantity_discrepancies": 20,
        },
    }
    with open(os.path.join(workspace, "risk_scoring_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False)

    # ── Fixed file 3: compliance_config.json ──
    config = {
        "leakage_threshold_amount": 500.0,
        "leakage_threshold_pct": 0.02,
        "review_priority_cutoff": 60.0,
        "fiscal_year_start": "2023-01-01",
        "fiscal_year_end": "2024-12-31",
    }
    with open(os.path.join(workspace, "compliance_config.json"), "w") as f:
        json.dump(config, f, indent=2)

    # ── Scalable files: third-party verification reports ──
    combo_map = {}
    for s in shipments:
        sd = date.fromisoformat(s["ship_date"])
        q = quarter_for_date(sd)
        key = (s["territory_code"], q)
        combo_map.setdefault(key, []).append(s)

    all_combos_ranked = sorted(
        combo_map.keys(),
        key=lambda c: (-len(combo_map[c]), c[0], c[1]),
    )
    n_files = SCALE["num_workspace_files"]
    selected = all_combos_ranked[:n_files]

    for territory, quarter in selected:
        rows = []
        for s in combo_map[(territory, quarter)]:
            sku = sku_map[s["sku_id"]]
            if s["distributor_id"] in leaky_ids and float(rng.random()) < 0.25:
                factor = float(rng.uniform(1.05, 1.25))
                verified_qty = max(1, int(round(s["quantity"] * factor)))
            else:
                noise = float(rng.uniform(-0.01, 0.01))
                verified_qty = max(1, int(round(s["quantity"] * (1 + noise))))

            disc_flag = "Y" if verified_qty != s["quantity"] else "N"
            note = fake.sentence(nb_words=6) if disc_flag == "Y" else ""
            vdate = (date.fromisoformat(s["ship_date"])
                     + timedelta(days=int(rng.integers(15, 60))))

            rows.append({
                "invoice_number": s["invoice_number"],
                "distributor_id": s["distributor_id"],
                "sku_code": sku["sku_code"],
                "verified_quantity": verified_qty,
                "verification_date": vdate.isoformat(),
                "discrepancy_flag": disc_flag,
                "verifier_notes": note,
            })

        df = pd.DataFrame(rows)
        fname = f"verification_report_{territory}_{quarter}.csv"
        df.to_csv(os.path.join(workspace, fname), index=False)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    np.random.seed(42)
    random.seed(42)
    Faker.seed(42)
    rng = np.random.default_rng(42)
    fake = Faker()

    distributors, skus, agreements, shipments, exceptions, leaky_ids = \
        generate_data(rng, fake)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    insert_data(conn, distributors, skus, agreements, shipments, exceptions)
    conn.close()

    generate_workspace(args.workspace, distributors, skus, shipments, exceptions,
                       leaky_ids, rng, fake)
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")


if __name__ == "__main__":
    main()
