import argparse
import os
import sqlite3
import json
import yaml
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 400,       # v2: 4x base
    "num_workspace_files": 30,   # v2: base + 2N (N=10)
}

BILLING_PERIOD = "2026-03"
HOME_CARRIER_ID = 0
CALL_TYPES = ["local", "long_distance", "international", "mobile"]


def main(db_path, workspace):
    rng = np.random.RandomState(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    rpt = SCALE["rows_per_table"]
    nwf = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ================================================================
    # TABLE 1: carriers
    # ================================================================
    num_carriers = rpt
    num_active_partners = max(8, rpt // 8)

    carriers = []
    carriers.append((HOME_CARRIER_ID, "HomeNet Telecom", "US", "home", "active"))

    used_names = {"HomeNet Telecom"}
    for i in range(1, num_active_partners + 1):
        while True:
            name = fake.company() + " Telecom"
            if name not in used_names:
                used_names.add(name)
                break
        country = fake.country_code()
        carriers.append((i, name, country, "partner", "active"))

    for i in range(num_active_partners + 1, num_carriers):
        while True:
            name = fake.company() + " Communications"
            if name not in used_names:
                used_names.add(name)
                break
        country = fake.country_code()
        ctype = str(rng.choice(["wholesale", "transit", "partner"]))
        status = str(rng.choice(["inactive", "suspended"]))
        carriers.append((i, name, country, ctype, status))

    cur.execute("""CREATE TABLE carriers (
        carrier_id INTEGER PRIMARY KEY,
        carrier_name TEXT NOT NULL,
        country_code TEXT NOT NULL,
        carrier_type TEXT NOT NULL,
        status TEXT NOT NULL
    )""")
    cur.executemany("INSERT INTO carriers VALUES (?,?,?,?,?)", carriers)

    active_partner_ids = [c[0] for c in carriers if c[3] == "partner" and c[4] == "active"]

    # ================================================================
    # TABLE 2: switches
    # ================================================================
    num_switches = rpt
    switches = []
    sid = 0

    regions = ["Northeast", "Southeast", "Midwest", "West", "Central",
               "Pacific", "Mountain", "Atlantic"]
    switch_types = ["local", "transit", "international", "mobile"]

    # Home carrier switches (~15%)
    num_home_sw = max(5, num_switches // 7)
    for _ in range(num_home_sw):
        switches.append((sid, HOME_CARRIER_ID, f"HOME-SW-{sid:04d}",
                         str(rng.choice(regions)), str(rng.choice(switch_types))))
        sid += 1

    # Partner switches (at least 2 each)
    partner_switch_map = {}
    for pid in active_partner_ids:
        n_sw = int(rng.randint(2, 5))
        partner_switch_map[pid] = []
        for _ in range(n_sw):
            if sid >= num_switches:
                break
            switches.append((sid, pid, f"P{pid}-SW-{sid:04d}",
                             str(rng.choice(regions)), str(rng.choice(switch_types))))
            partner_switch_map[pid].append(sid)
            sid += 1

    all_carrier_ids = [c[0] for c in carriers]
    while sid < num_switches:
        cid = int(rng.choice(all_carrier_ids))
        switches.append((sid, cid, f"SW-{sid:04d}",
                         str(rng.choice(regions)), str(rng.choice(switch_types))))
        if cid in partner_switch_map:
            partner_switch_map[cid].append(sid)
        elif cid in active_partner_ids:
            partner_switch_map[cid] = [sid]
        sid += 1

    cur.execute("""CREATE TABLE switches (
        switch_id INTEGER PRIMARY KEY,
        carrier_id INTEGER NOT NULL,
        switch_name TEXT NOT NULL,
        region TEXT NOT NULL,
        switch_type TEXT NOT NULL,
        FOREIGN KEY (carrier_id) REFERENCES carriers(carrier_id)
    )""")
    cur.executemany("INSERT INTO switches VALUES (?,?,?,?,?)", switches)

    home_switch_ids = [s[0] for s in switches if s[1] == HOME_CARRIER_ID]
    # Ensure every active partner has at least one switch entry in map
    for pid in active_partner_ids:
        if pid not in partner_switch_map or len(partner_switch_map[pid]) == 0:
            partner_switch_map[pid] = [switches[-1][0]]  # fallback

    # ================================================================
    # TABLE 3: routing_rules
    # ================================================================
    num_routes = rpt
    routes = []
    all_switch_ids = [s[0] for s in switches]

    for rid in range(num_routes):
        src = int(rng.choice(all_switch_ids))
        dst = int(rng.choice(all_switch_ids))
        while dst == src:
            dst = int(rng.choice(all_switch_ids))
        transit_cid = int(rng.choice(all_carrier_ids)) if rng.random() < 0.3 else None
        cost_factor = round(float(rng.choice([1.0, 1.0, 1.0, 1.0, 1.05, 1.10, 1.15, 1.20, 1.25, 1.50])), 2)
        priority = int(rng.randint(1, 10))
        active = 1 if rng.random() < 0.85 else 0
        routes.append((rid, src, dst, transit_cid, cost_factor, priority, active))

    cur.execute("""CREATE TABLE routing_rules (
        route_id INTEGER PRIMARY KEY,
        source_switch_id INTEGER NOT NULL,
        dest_switch_id INTEGER NOT NULL,
        transit_carrier_id INTEGER,
        cost_factor REAL NOT NULL,
        priority INTEGER NOT NULL,
        active INTEGER NOT NULL,
        FOREIGN KEY (source_switch_id) REFERENCES switches(switch_id),
        FOREIGN KEY (dest_switch_id) REFERENCES switches(switch_id)
    )""")
    cur.executemany("INSERT INTO routing_rules VALUES (?,?,?,?,?,?,?)", routes)

    route_ids = [r[0] for r in routes]

    # ================================================================
    # TABLE 4: bilateral_agreements
    # ================================================================
    agreements = []
    aid = 0

    # Active agreements: one per partner per call_type
    for pid in active_partner_ids:
        for ct in CALL_TYPES:
            if ct == "local":
                rate = round(float(rng.uniform(0.005, 0.02)), 4)
            elif ct == "long_distance":
                rate = round(float(rng.uniform(0.02, 0.06)), 4)
            elif ct == "international":
                rate = round(float(rng.uniform(0.08, 0.25)), 4)
            else:  # mobile
                rate = round(float(rng.uniform(0.03, 0.08)), 4)
            agreements.append((aid, HOME_CARRIER_ID, pid, ct, rate,
                               "2025-01-01", "2027-12-31", "active"))
            aid += 1

    # Pad with expired/other agreements to reach rpt
    while aid < rpt:
        ca = int(rng.choice(all_carrier_ids))
        cb = int(rng.choice(all_carrier_ids))
        while cb == ca:
            cb = int(rng.choice(all_carrier_ids))
        ct = str(rng.choice(CALL_TYPES))
        rate = round(float(rng.uniform(0.005, 0.25)), 4)
        agreements.append((aid, ca, cb, ct, rate,
                           "2022-01-01", "2024-12-31", "expired"))
        aid += 1

    cur.execute("""CREATE TABLE bilateral_agreements (
        agreement_id INTEGER PRIMARY KEY,
        carrier_a_id INTEGER NOT NULL,
        carrier_b_id INTEGER NOT NULL,
        call_type TEXT NOT NULL,
        rate_per_minute REAL NOT NULL,
        effective_date TEXT NOT NULL,
        expiry_date TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (carrier_a_id) REFERENCES carriers(carrier_id),
        FOREIGN KEY (carrier_b_id) REFERENCES carriers(carrier_id)
    )""")
    cur.executemany("INSERT INTO bilateral_agreements VALUES (?,?,?,?,?,?,?,?)", agreements)

    # ================================================================
    # TABLE 5: cdrs  (3 * rpt rows for meaningful volume)
    # ================================================================
    num_cdrs = rpt * 3
    cdrs = []

    # Generate timestamps in March 2026
    start_ts = pd.Timestamp("2026-03-01")
    end_ts = pd.Timestamp("2026-03-31 23:59:59")
    ts_range = (end_ts - start_ts).total_seconds()

    completion_statuses = ["completed", "completed", "completed", "completed",
                           "completed", "completed", "completed", "completed",
                           "failed", "dropped"]  # 80% completed

    for cid_idx in range(num_cdrs):
        # ~85% involve home carrier on one side
        if rng.random() < 0.85:
            partner_id = int(rng.choice(active_partner_ids))
            p_switches = partner_switch_map.get(partner_id, [])
            if len(p_switches) == 0:
                continue
            if rng.random() < 0.5:
                # outgoing: HOME -> Partner
                orig = int(rng.choice(home_switch_ids))
                term = int(rng.choice(p_switches))
            else:
                # incoming: Partner -> HOME
                orig = int(rng.choice(p_switches))
                term = int(rng.choice(home_switch_ids))
        else:
            # Non-home CDR (noise)
            orig = int(rng.choice(all_switch_ids))
            term = int(rng.choice(all_switch_ids))
            while term == orig:
                term = int(rng.choice(all_switch_ids))

        ct = str(rng.choice(CALL_TYPES))
        dur = int(rng.randint(1, 3600))
        offset_sec = rng.uniform(0, ts_range)
        ts_val = start_ts + pd.Timedelta(seconds=float(offset_sec))
        ts_str = ts_val.strftime("%Y-%m-%d %H:%M:%S")
        comp = str(rng.choice(completion_statuses))
        rid = int(rng.choice(route_ids))
        cdrs.append((cid_idx, orig, term, ct, dur, ts_str, comp, rid))

    cur.execute("""CREATE TABLE cdrs (
        cdr_id INTEGER PRIMARY KEY,
        originating_switch_id INTEGER NOT NULL,
        terminating_switch_id INTEGER NOT NULL,
        call_type TEXT NOT NULL,
        duration_seconds INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        completion_status TEXT NOT NULL,
        route_id INTEGER NOT NULL,
        FOREIGN KEY (originating_switch_id) REFERENCES switches(switch_id),
        FOREIGN KEY (terminating_switch_id) REFERENCES switches(switch_id),
        FOREIGN KEY (route_id) REFERENCES routing_rules(route_id)
    )""")
    cur.executemany("INSERT INTO cdrs VALUES (?,?,?,?,?,?,?,?)", cdrs)

    # ================================================================
    # TABLE 6: disputes
    # ================================================================
    num_disputes = rpt
    disputes = []
    dispute_categories = ["rate_mismatch", "duration_discrepancy",
                          "routing_error", "quality_issue"]
    dispute_statuses = ["open", "resolved", "rejected"]
    billing_periods = ["2025-10", "2025-11", "2025-12",
                       "2026-01", "2026-02", BILLING_PERIOD]

    for did in range(num_disputes):
        # ~60% involve home carrier
        if rng.random() < 0.6:
            filing = int(rng.choice(active_partner_ids))
            counter = HOME_CARRIER_ID
        else:
            filing = HOME_CARRIER_ID
            counter = int(rng.choice(active_partner_ids))

        # ~35% in current billing period
        if rng.random() < 0.35:
            bp = BILLING_PERIOD
        else:
            bp = str(rng.choice(billing_periods[:-1]))

        cat = str(rng.choice(dispute_categories))
        # Resolved ~40%, rejected ~25%, open ~35%
        r = rng.random()
        if r < 0.40:
            status = "resolved"
        elif r < 0.65:
            status = "rejected"
        else:
            status = "open"

        amount = round(float(rng.uniform(50, 5000)), 2)
        filed_date = f"{bp}-{int(rng.randint(1, 28)):02d}"

        disputes.append((did, filing, counter, bp, amount, cat, status, filed_date))

    cur.execute("""CREATE TABLE disputes (
        dispute_id INTEGER PRIMARY KEY,
        filing_carrier_id INTEGER NOT NULL,
        counter_carrier_id INTEGER NOT NULL,
        billing_period TEXT NOT NULL,
        disputed_amount REAL NOT NULL,
        category TEXT NOT NULL,
        status TEXT NOT NULL,
        filed_date TEXT NOT NULL,
        FOREIGN KEY (filing_carrier_id) REFERENCES carriers(carrier_id),
        FOREIGN KEY (counter_carrier_id) REFERENCES carriers(carrier_id)
    )""")
    cur.executemany("INSERT INTO disputes VALUES (?,?,?,?,?,?,?,?)", disputes)

    conn.commit()

    # ================================================================
    # WORKSPACE FILES — Scalable: CDR quality batches + dispute memos
    # ================================================================
    num_quality_files = max(1, int(nwf * 0.7))
    num_dispute_files = nwf - num_quality_files

    # --- CDR quality data (for ALL cdrs, only available in workspace) ---
    quality_data = []
    for c in cdrs:
        cdr_id = c[0]
        quality_score = int(rng.randint(10, 100))
        jitter_ms = round(float(rng.uniform(0.5, 80.0)), 2)
        packet_loss = round(float(rng.uniform(0.0, 12.0)), 3)
        quality_data.append({
            "cdr_id": cdr_id,
            "quality_score": quality_score,
            "jitter_ms": jitter_ms,
            "packet_loss_pct": packet_loss,
        })

    # Split into batch files
    batch_size = math.ceil(len(quality_data) / num_quality_files)
    for bidx in range(num_quality_files):
        batch = quality_data[bidx * batch_size: (bidx + 1) * batch_size]
        fpath = os.path.join(workspace, f"cdr_quality_batch_{bidx + 1:03d}.csv")
        with open(fpath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["cdr_id", "quality_score",
                                                    "jitter_ms", "packet_loss_pct"])
            writer.writeheader()
            writer.writerows(batch)

    # --- Dispute resolution memos (only for resolved disputes) ---
    resolved_disputes = [d for d in disputes if d[6] == "resolved"]
    dispute_memos = []
    for d in resolved_disputes:
        did, filing, counter, bp, amount, cat, status, fdate = d
        # Approved credit: 30%-100% of disputed amount
        credit_pct = rng.uniform(0.3, 1.0)
        approved_credit = round(float(amount * credit_pct), 2)
        reviewer = fake.name()
        res_date = f"{bp}-{int(rng.randint(15, 28)):02d}"
        dispute_memos.append({
            "dispute_id": int(did),
            "approved_credit_amount": approved_credit,
            "reviewer": reviewer,
            "resolution_date": res_date,
            "notes": fake.sentence(nb_words=12),
        })

    memo_batch_size = max(1, math.ceil(len(dispute_memos) / max(1, num_dispute_files)))
    for bidx in range(num_dispute_files):
        batch = dispute_memos[bidx * memo_batch_size: (bidx + 1) * memo_batch_size]
        fpath = os.path.join(workspace, f"dispute_memo_batch_{bidx + 1:03d}.txt")
        with open(fpath, "w") as f:
            for entry in batch:
                f.write(f"DISPUTE_ID: {entry['dispute_id']}\n")
                f.write(f"APPROVED_CREDIT: {entry['approved_credit_amount']}\n")
                f.write(f"REVIEWER: {entry['reviewer']}\n")
                f.write(f"RESOLUTION_DATE: {entry['resolution_date']}\n")
                f.write(f"NOTES: {entry['notes']}\n")
                f.write("---\n")

    # ================================================================
    # WORKSPACE FILES — Fixed config / policy files
    # ================================================================

    # settlement_rules.json
    settlement_rules = {
        "billing_period": BILLING_PERIOD,
        "minimum_billable_duration_seconds": 6,
        "quality_score_threshold": 40,
        "quality_penalty_multiplier": 0.50,
        "rounding_precision": 2,
        "currency": "USD",
    }
    with open(os.path.join(workspace, "settlement_rules.json"), "w") as f:
        json.dump(settlement_rules, f, indent=2)

    # rate_adjustments.yaml — temporary rate overrides for some carrier pairs
    # Pick a few active partners deterministically
    adj_partners = active_partner_ids[:min(4, len(active_partner_ids))]
    adjustments = []
    adj_call_types = ["international", "mobile", "long_distance", "local"]
    adj_pcts = [15.0, -10.0, 8.5, -5.0]
    adj_reasons = [
        "Peak season surcharge",
        "Volume commitment discount",
        "Regulatory surcharge",
        "Promotional rate reduction",
    ]
    for idx, pid in enumerate(adj_partners):
        adjustments.append({
            "carrier_a_id": HOME_CARRIER_ID,
            "carrier_b_id": int(pid),
            "call_type": adj_call_types[idx % len(adj_call_types)],
            "adjustment_pct": adj_pcts[idx % len(adj_pcts)],
            "reason": adj_reasons[idx % len(adj_reasons)],
        })
    with open(os.path.join(workspace, "rate_adjustments.yaml"), "w") as f:
        yaml.dump({"adjustments": adjustments}, f, default_flow_style=False)

    # tier_discounts.json
    tier_discounts = {
        "tiers": [
            {"min_minutes": 0, "max_minutes": 1000, "discount_pct": 0.0},
            {"min_minutes": 1000, "max_minutes": 5000, "discount_pct": 2.0},
            {"min_minutes": 5000, "max_minutes": 20000, "discount_pct": 5.0},
            {"min_minutes": 20000, "max_minutes": None, "discount_pct": 8.0},
        ]
    }
    with open(os.path.join(workspace, "tier_discounts.json"), "w") as f:
        json.dump(tier_discounts, f, indent=2)

    # routing_penalties.csv — route_ids that carry a surcharge in current period
    penalty_route_ids = rng.choice(route_ids, size=max(5, len(route_ids) // 10), replace=False)
    with open(os.path.join(workspace, "routing_penalties.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["route_id", "surcharge_pct", "reason",
                                                "effective_period"])
        writer.writeheader()
        for prid in sorted(penalty_route_ids):
            surcharge = round(float(rng.uniform(2.0, 15.0)), 1)
            writer.writerow({
                "route_id": int(prid),
                "surcharge_pct": surcharge,
                "reason": str(rng.choice(["congestion", "premium_transit",
                                           "regulatory", "capacity_constraint"])),
                "effective_period": BILLING_PERIOD,
            })

    # billing_notes.md — period-specific notes
    with open(os.path.join(workspace, "billing_notes.md"), "w") as f:
        f.write(f"# Billing Period: {BILLING_PERIOD}\n\n")
        f.write("## General Notes\n\n")
        f.write("- All settlements are denominated in USD.\n")
        f.write("- Calls with duration below the minimum billable threshold "
                "defined in settlement rules must be excluded from charges.\n")
        f.write("- Quality penalties apply to the per-call effective rate, not as a "
                "separate line item.\n")
        f.write("- Tier volume discounts are computed on total billable minutes "
                "(incoming + outgoing combined) per partner.\n")
        f.write("- Dispute credits are subtracted after tier discounts are applied.\n")
        f.write("- Only disputes with status 'resolved' and matching the current "
                "billing period are eligible for credit.\n")
        f.write("- For each resolved dispute, use the approved credit amount from "
                "the dispute memo files, not the original disputed amount.\n\n")
        f.write("## Rate Adjustment Policy\n\n")
        f.write("Rate adjustments listed in the YAML configuration modify the "
                "bilateral base rate by the stated percentage. A positive value is a "
                "surcharge; a negative value is a discount. The adjustment applies "
                "uniformly to both traffic directions for that carrier pair and "
                "call type.\n\n")
        f.write("## Routing Surcharge Policy\n\n")
        f.write("Certain routes incur a surcharge as listed in the routing penalties "
                "file. The surcharge percentage is applied on top of the "
                "(base rate + rate adjustment). If a CDR's route is listed, "
                "the surcharge applies; otherwise no routing surcharge.\n")

    conn.close()
    print(f"Database created at {db_path}")
    print(f"Workspace files generated in {workspace}/")
    print(f"  Carriers: {len(carriers)} ({len(active_partner_ids)} active partners)")
    print(f"  Switches: {len(switches)} ({len(home_switch_ids)} home)")
    print(f"  CDRs: {len(cdrs)}")
    print(f"  Agreements: {len(agreements)}")
    print(f"  Routes: {len(routes)}")
    print(f"  Disputes: {len(disputes)} ({len(resolved_disputes)} resolved)")
    print(f"  Quality files: {num_quality_files}")
    print(f"  Dispute memo files: {num_dispute_files}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
