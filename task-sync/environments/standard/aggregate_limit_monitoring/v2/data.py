import argparse
import sqlite3
import os
import json
import csv
import random
import math
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 30,
}

SEED = 42


def main(db_path, workspace):
    random.seed(SEED)
    np.random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    n_treaties = SCALE["rows_per_table"]
    n_events = SCALE["rows_per_table"]
    n_bulletins = SCALE["num_workspace_files"]

    # ──────────────────────────────────────────────
    # TABLE 1: treaties
    # ──────────────────────────────────────────────
    treaty_types = ["AGG_XL", "ILW", "CAT_XL"]
    currencies = ["USD", "EUR", "GBP"]
    currency_weights = [0.6, 0.25, 0.15]
    lines_of_business = ["Property", "Marine", "Energy", "Aviation"]

    treaties = []
    for i in range(n_treaties):
        tid = f"TR-{i+1:04d}"
        ttype = treaty_types[i % 3]
        curr = random.choices(currencies, weights=currency_weights, k=1)[0]
        cedent = fake.company()
        lob = random.choice(lines_of_business)
        eff_year = random.choice([2023, 2024])
        eff_date = f"{eff_year}-01-01"
        exp_date = f"{eff_year}-12-31"

        # Vary attachment / limit tiers so outcomes mix across statuses
        tier = i % 3
        if tier == 0:
            attachment = round(random.uniform(1_000_000, 6_000_000), 2)
            limit_val = round(random.uniform(5_000_000, 15_000_000), 2)
        elif tier == 1:
            attachment = round(random.uniform(12_000_000, 35_000_000), 2)
            limit_val = round(random.uniform(20_000_000, 60_000_000), 2)
        else:
            attachment = round(random.uniform(45_000_000, 90_000_000), 2)
            limit_val = round(random.uniform(30_000_000, 100_000_000), 2)

        per_occ_ret = None
        if ttype == "CAT_XL":
            per_occ_ret = round(attachment * random.uniform(0.08, 0.25), 2)

        treaties.append({
            "treaty_id": tid,
            "treaty_name": f"{cedent[:20]} {ttype} {lob} {eff_year}",
            "cedent_name": cedent,
            "line_of_business": lob,
            "effective_date": eff_date,
            "expiry_date": exp_date,
            "currency": curr,
            "status": "active",
            # workspace-only fields (NOT stored in DB)
            "_treaty_type": ttype,
            "_attachment_usd": attachment,
            "_limit_usd": limit_val,
            "_per_occ_ret": per_occ_ret,
        })

    cur.execute("""CREATE TABLE treaties (
        treaty_id TEXT PRIMARY KEY,
        treaty_name TEXT,
        cedent_name TEXT,
        line_of_business TEXT,
        effective_date TEXT,
        expiry_date TEXT,
        currency TEXT,
        status TEXT
    )""")
    for t in treaties:
        cur.execute(
            "INSERT INTO treaties VALUES (?,?,?,?,?,?,?,?)",
            (t["treaty_id"], t["treaty_name"], t["cedent_name"],
             t["line_of_business"], t["effective_date"], t["expiry_date"],
             t["currency"], t["status"]),
        )

    # ──────────────────────────────────────────────
    # TABLE 2: catastrophe_events
    # ──────────────────────────────────────────────
    perils = ["Hurricane", "Earthquake", "Flood", "Wildfire", "Tornado", "Hailstorm"]
    regions = [
        "US_Southeast", "US_Northeast", "US_West", "Europe_West",
        "Europe_South", "Japan", "Australia", "Caribbean", "Central_America",
    ]

    events = []
    for i in range(n_events):
        eid = f"EVT-{i+1:04d}"
        peril = random.choice(perils)
        region = random.choice(regions)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        year = random.choice([2023, 2024])
        occ_date = f"{year}-{month:02d}-{day:02d}"
        rep_day = min(day + random.randint(1, 15), 28)
        rep_date = f"{year}-{month:02d}-{rep_day:02d}"
        ili_value = round(random.uniform(0.5, 80.0), 2)

        events.append({
            "event_id": eid,
            "event_name": f"{year} {region} {peril} {fake.word().title()}",
            "peril_type": peril,
            "region": region,
            "occurrence_date": occ_date,
            "reported_date": rep_date,
            "_ili_value": ili_value,
        })

    cur.execute("""CREATE TABLE catastrophe_events (
        event_id TEXT PRIMARY KEY,
        event_name TEXT,
        peril_type TEXT,
        region TEXT,
        occurrence_date TEXT,
        reported_date TEXT
    )""")
    for e in events:
        cur.execute(
            "INSERT INTO catastrophe_events VALUES (?,?,?,?,?,?)",
            (e["event_id"], e["event_name"], e["peril_type"],
             e["region"], e["occurrence_date"], e["reported_date"]),
        )

    # ──────────────────────────────────────────────
    # TABLE 3: industry_loss_indices
    # ──────────────────────────────────────────────
    index_providers = ["PCS", "PERILS", "CRESTA"]

    cur.execute("""CREATE TABLE industry_loss_indices (
        index_id TEXT PRIMARY KEY,
        event_id TEXT,
        index_provider TEXT,
        index_value_usd_bn REAL,
        publication_date TEXT,
        FOREIGN KEY (event_id) REFERENCES catastrophe_events(event_id)
    )""")
    for i, e in enumerate(events):
        idx_id = f"ILI-{i+1:04d}"
        provider = random.choice(index_providers)
        cur.execute(
            "INSERT INTO industry_loss_indices VALUES (?,?,?,?,?)",
            (idx_id, e["event_id"], provider, e["_ili_value"], e["reported_date"]),
        )

    # ──────────────────────────────────────────────
    # TABLE 4: loss_advices
    # ──────────────────────────────────────────────
    development_stages = ["preliminary", "interim", "final"]
    dev_stage_weights = [0.3, 0.4, 0.3]

    loss_advices = []
    advice_counter = 0

    for t in treaties:
        n_affected = random.randint(3, min(6, n_events))
        affected_events = random.sample(events, n_affected)

        for evt in affected_events:
            n_seq = random.choices([1, 2, 3], weights=[0.4, 0.4, 0.2], k=1)[0]
            base_gross = random.uniform(500_000, 30_000_000)

            for seq in range(1, n_seq + 1):
                advice_counter += 1
                aid = f"LA-{advice_counter:05d}"
                gross = round(base_gross * random.uniform(0.85, 1.15), 2)

                if seq == n_seq and n_seq > 1:
                    dev_stage = random.choices(
                        ["interim", "final"], weights=[0.4, 0.6], k=1
                    )[0]
                else:
                    dev_stage = random.choices(
                        development_stages, weights=dev_stage_weights, k=1
                    )[0]

                adv_day = min(int(evt["occurrence_date"][-2:]) + seq * 5, 28)
                advice_date = evt["occurrence_date"][:-2] + f"{adv_day:02d}"

                loss_advices.append({
                    "advice_id": aid,
                    "treaty_id": t["treaty_id"],
                    "event_id": evt["event_id"],
                    "gross_loss_amount": gross,
                    "advice_date": advice_date,
                    "advice_sequence": seq,
                    "_development_stage": dev_stage,
                })

    cur.execute("""CREATE TABLE loss_advices (
        advice_id TEXT PRIMARY KEY,
        treaty_id TEXT,
        event_id TEXT,
        gross_loss_amount REAL,
        advice_date TEXT,
        advice_sequence INTEGER,
        FOREIGN KEY (treaty_id) REFERENCES treaties(treaty_id),
        FOREIGN KEY (event_id) REFERENCES catastrophe_events(event_id)
    )""")
    for la in loss_advices:
        cur.execute(
            "INSERT INTO loss_advices VALUES (?,?,?,?,?,?)",
            (la["advice_id"], la["treaty_id"], la["event_id"],
             la["gross_loss_amount"], la["advice_date"], la["advice_sequence"]),
        )

    # ──────────────────────────────────────────────
    # TABLE 5: inuring_recoveries
    # ──────────────────────────────────────────────
    recovery_types = ["quota_share", "fac_ob", "surplus"]
    event_map = {e["event_id"]: e for e in events}

    te_pairs = sorted({(la["treaty_id"], la["event_id"]) for la in loss_advices})

    inuring_recoveries = []
    recovery_counter = 0

    for tid, eid in te_pairs:
        if random.random() < 0.40:
            recovery_counter += 1
            rid = f"IR-{recovery_counter:05d}"

            relevant = [la for la in loss_advices
                        if la["treaty_id"] == tid and la["event_id"] == eid]
            max_gross = max(la["gross_loss_amount"] for la in relevant)
            recovery_amt = round(max_gross * random.uniform(0.10, 0.50), 2)

            inuring_recoveries.append({
                "recovery_id": rid,
                "treaty_id": tid,
                "event_id": eid,
                "recovery_amount": recovery_amt,
                "recovery_type": random.choice(recovery_types),
                "effective_date": event_map[eid]["occurrence_date"],
            })

    cur.execute("""CREATE TABLE inuring_recoveries (
        recovery_id TEXT PRIMARY KEY,
        treaty_id TEXT,
        event_id TEXT,
        recovery_amount REAL,
        recovery_type TEXT,
        effective_date TEXT,
        FOREIGN KEY (treaty_id) REFERENCES treaties(treaty_id),
        FOREIGN KEY (event_id) REFERENCES catastrophe_events(event_id)
    )""")
    for ir in inuring_recoveries:
        cur.execute(
            "INSERT INTO inuring_recoveries VALUES (?,?,?,?,?,?)",
            (ir["recovery_id"], ir["treaty_id"], ir["event_id"],
             ir["recovery_amount"], ir["recovery_type"], ir["effective_date"]),
        )

    conn.commit()
    conn.close()

    # ══════════════════════════════════════════════
    # WORKSPACE — fixed policy / config files
    # ══════════════════════════════════════════════

    # 1. treaty_terms.yaml (YAML)
    yaml_lines = []
    for t in treaties:
        yaml_lines.append(f"{t['treaty_id']}:")
        yaml_lines.append(f"  treaty_type: {t['_treaty_type']}")
        yaml_lines.append(f"  attachment_usd: {t['_attachment_usd']}")
        yaml_lines.append(f"  limit_usd: {t['_limit_usd']}")
        if t["_per_occ_ret"] is not None:
            yaml_lines.append(
                f"  per_occurrence_retention_usd: {t['_per_occ_ret']}"
            )
    with open(os.path.join(workspace, "treaty_terms.yaml"), "w") as f:
        f.write("\n".join(yaml_lines) + "\n")

    # 2. ili_trigger_thresholds.json (JSON)
    ili_thresholds = {}
    for t in treaties:
        if t["_treaty_type"] == "ILW":
            ili_thresholds[t["treaty_id"]] = round(random.uniform(5.0, 40.0), 2)
    with open(os.path.join(workspace, "ili_trigger_thresholds.json"), "w") as f:
        json.dump(ili_thresholds, f, indent=2)

    # 3. loss_development_factors.csv (CSV)
    with open(
        os.path.join(workspace, "loss_development_factors.csv"), "w", newline=""
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["development_stage", "factor"])
        writer.writerow(["preliminary", "1.35"])
        writer.writerow(["interim", "1.15"])
        writer.writerow(["final", "1.00"])

    # 4. currency_conversion.json (JSON)
    fx_rates = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27}
    with open(os.path.join(workspace, "currency_conversion.json"), "w") as f:
        json.dump(fx_rates, f, indent=2)

    # 5. disputed_events.txt (TXT)
    n_disputed = max(2, n_events // 10)
    disputed_ids = sorted(
        random.sample([e["event_id"] for e in events], n_disputed)
    )
    with open(os.path.join(workspace, "disputed_events.txt"), "w") as f:
        f.write(
            "# Events currently under dispute — exclude from treaty calculations\n"
        )
        for did in disputed_ids:
            f.write(did + "\n")

    # ══════════════════════════════════════════════
    # WORKSPACE — scalable cedent bulletin files
    # ══════════════════════════════════════════════
    advices_per_bulletin = math.ceil(len(loss_advices) / n_bulletins)

    for b in range(n_bulletins):
        start = b * advices_per_bulletin
        end = min(start + advices_per_bulletin, len(loss_advices))
        batch = loss_advices[start:end]

        fname = f"cedent_bulletin_{b+1:03d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["advice_id", "development_stage"])
            for la in batch:
                writer.writerow([la["advice_id"], la["_development_stage"]])

    print(f"Database written to {db_path}")
    print(
        f"Workspace populated in {workspace}/ "
        f"({n_bulletins} bulletins + 5 config files)"
    )
    print(
        f"  Treaties: {n_treaties}, Events: {n_events}, "
        f"Loss advices: {len(loss_advices)}, "
        f"Inuring recoveries: {len(inuring_recoveries)}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
