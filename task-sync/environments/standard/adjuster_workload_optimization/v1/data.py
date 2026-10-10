import argparse
import os
import sqlite3
import json
import csv
import math
import yaml
import numpy as np
import pandas as pd
from faker import Faker
from datetime import date, timedelta

SCALE = {
    "rows_per_table": 60,
    "num_workspace_files": 16,
}

# ── Constants ──────────────────────────────────────────────────────────────
CLAIM_TYPES = ["auto", "property", "liability", "health"]
CERT_LEVELS = ["junior", "standard", "senior", "expert"]
CERT_RANK = {"junior": 1, "standard": 2, "senior": 3, "expert": 4}
REGIONS = ["Northeast", "Southeast", "Midwest", "West", "Southwest"]
BASE_DATE = date(2026, 4, 19)


def _travel_hours(lat1, lon1, lat2, lon2, rng):
    """Rough travel-hours from coordinate distance plus noise."""
    dlat = lat1 - lat2
    dlon = lon1 - lon2
    dist_deg = math.sqrt(dlat ** 2 + dlon ** 2)
    miles = dist_deg * 69.0
    hours = miles / 55.0 + rng.uniform(0.3, 1.5)
    return round(hours, 2)


def main(db_path: str, workspace: str):
    np.random.seed(42)
    rng = np.random.RandomState(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    N = SCALE["rows_per_table"]
    NF = SCALE["num_workspace_files"]

    # ══════════════════════════════════════════════════════════════════════
    #  DATA GENERATION
    # ══════════════════════════════════════════════════════════════════════

    # ── 1. Territories ────────────────────────────────────────────────────
    lats = rng.uniform(25.0, 48.0, N).tolist()
    lons = rng.uniform(-125.0, -70.0, N).tolist()
    territories = []
    used_names = set()
    for i in range(N):
        name = fake.city()
        while name in used_names:
            name = fake.city()
        used_names.add(name)
        territories.append({
            "territory_id": f"T{i+1:04d}",
            "territory_name": name,
            "region": REGIONS[i % len(REGIONS)],
            "latitude": round(lats[i], 4),
            "longitude": round(lons[i], 4),
        })

    # ── 2. Adjusters ─────────────────────────────────────────────────────
    n_active = max(int(N * 0.73), 5)
    cert_pool = []
    for i in range(N):
        r = i / max(N - 1, 1)
        if r < 0.10:
            cert_pool.append("expert")
        elif r < 0.30:
            cert_pool.append("senior")
        elif r < 0.60:
            cert_pool.append("standard")
        else:
            cert_pool.append("junior")
    rng.shuffle(cert_pool)

    adjusters = []
    for i in range(N):
        adjusters.append({
            "adjuster_id": f"A{i+1:04d}",
            "name": fake.name(),
            "certification_level": str(cert_pool[i]),
            "base_territory_id": territories[i % len(territories)]["territory_id"],
            "max_caseload": int(rng.randint(6, 16)),
            "active": 1 if i < n_active else 0,
        })

    active_ids = [a["adjuster_id"] for a in adjusters if a["active"] == 1]

    # ── 3. Claims ─────────────────────────────────────────────────────────
    n_pending = max(int(N * 0.65), 4)
    n_assigned = max(int(N * 0.25), 2)
    n_closed = N - n_pending - n_assigned
    status_list = (["pending"] * n_pending
                   + ["assigned"] * n_assigned
                   + ["closed"] * max(n_closed, 0))
    while len(status_list) < N:
        status_list.append("closed")

    claims = []
    for i in range(N):
        days_ago = int(rng.randint(1, 31))
        filed = BASE_DATE - timedelta(days=days_ago)
        claims.append({
            "claim_id": f"C{i+1:04d}",
            "severity_score": int(rng.randint(1, 101)),
            "claim_type": CLAIM_TYPES[i % len(CLAIM_TYPES)],
            "territory_id": territories[int(rng.randint(0, len(territories)))]["territory_id"],
            "status": status_list[i],
            "date_filed": filed.isoformat(),
            "estimated_value": round(float(rng.uniform(1000, 500000)), 2),
        })

    # Map assigned claims to active adjusters (round-robin) for caseload
    assigned_claims = [c for c in claims if c["status"] == "assigned"]
    claim_to_adjuster = {}
    for j, c in enumerate(assigned_claims):
        claim_to_adjuster[c["claim_id"]] = active_ids[j % len(active_ids)]

    caseload_map: dict = {}
    for aid in active_ids:
        caseload_map[aid] = 0
    for cid, aid in claim_to_adjuster.items():
        caseload_map[aid] = caseload_map.get(aid, 0) + 1

    # ── 4. Adjuster specialties ──────────────────────────────────────────
    specialties = []
    spec_set = set()
    for adj in adjusters:
        n_spec = int(rng.randint(1, 4))
        chosen = list(rng.choice(CLAIM_TYPES, size=min(n_spec, len(CLAIM_TYPES)), replace=False))
        for ct in chosen:
            key = (adj["adjuster_id"], ct)
            if key not in spec_set:
                spec_set.add(key)
                specialties.append({
                    "adjuster_id": adj["adjuster_id"],
                    "claim_type": ct,
                    "proficiency_score": int(rng.randint(25, 101)),
                })
    # ensure >= N rows
    idx = 0
    while len(specialties) < N:
        adj = adjusters[idx % len(adjusters)]
        ct = CLAIM_TYPES[idx % len(CLAIM_TYPES)]
        key = (adj["adjuster_id"], ct)
        if key not in spec_set:
            spec_set.add(key)
            specialties.append({
                "adjuster_id": adj["adjuster_id"],
                "claim_type": ct,
                "proficiency_score": int(rng.randint(25, 101)),
            })
        idx += 1

    # ── 5. Travel times (all ordered pairs) ──────────────────────────────
    travel_times = []
    for i in range(len(territories)):
        for j in range(len(territories)):
            if i == j:
                continue
            ti, tj = territories[i], territories[j]
            hours = _travel_hours(
                ti["latitude"], ti["longitude"],
                tj["latitude"], tj["longitude"], rng,
            )
            travel_times.append({
                "from_territory_id": ti["territory_id"],
                "to_territory_id": tj["territory_id"],
                "travel_hours": hours,
            })

    # ── 6. Settlement history ────────────────────────────────────────────
    settlement_history = []
    hist_set = set()
    for adj in adjusters:
        if adj["active"] == 0:
            if rng.random() < 0.3:
                ct = CLAIM_TYPES[int(rng.randint(0, len(CLAIM_TYPES)))]
                key = (adj["adjuster_id"], ct)
                if key not in hist_set:
                    hist_set.add(key)
                    settlement_history.append({
                        "adjuster_id": adj["adjuster_id"],
                        "claim_type": ct,
                        "avg_settlement_days": round(float(rng.uniform(15, 85)), 1),
                        "total_cases_handled": int(rng.randint(1, 30)),
                    })
            continue
        n_types = int(rng.randint(1, 4))
        chosen = list(rng.choice(CLAIM_TYPES, size=min(n_types, len(CLAIM_TYPES)), replace=False))
        for ct in chosen:
            key = (adj["adjuster_id"], ct)
            if key not in hist_set:
                hist_set.add(key)
                settlement_history.append({
                    "adjuster_id": adj["adjuster_id"],
                    "claim_type": ct,
                    "avg_settlement_days": round(float(rng.uniform(10, 80)), 1),
                    "total_cases_handled": int(rng.randint(5, 100)),
                })
    idx = 0
    while len(settlement_history) < N:
        adj = adjusters[idx % len(adjusters)]
        ct = CLAIM_TYPES[idx % len(CLAIM_TYPES)]
        key = (adj["adjuster_id"], ct)
        if key not in hist_set:
            hist_set.add(key)
            settlement_history.append({
                "adjuster_id": adj["adjuster_id"],
                "claim_type": ct,
                "avg_settlement_days": round(float(rng.uniform(10, 80)), 1),
                "total_cases_handled": int(rng.randint(5, 100)),
            })
        idx += 1

    # ══════════════════════════════════════════════════════════════════════
    #  DATABASE
    # ══════════════════════════════════════════════════════════════════════
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # territories – NOTE: region is NOT stored in DB; only in workspace YAML
    cur.execute("""CREATE TABLE territories (
        territory_id   TEXT PRIMARY KEY,
        territory_name TEXT NOT NULL,
        latitude       REAL NOT NULL,
        longitude      REAL NOT NULL
    )""")
    for t in territories:
        cur.execute("INSERT INTO territories VALUES (?,?,?,?)",
                    (t["territory_id"], t["territory_name"],
                     t["latitude"], t["longitude"]))

    cur.execute("""CREATE TABLE adjusters (
        adjuster_id        TEXT PRIMARY KEY,
        name               TEXT NOT NULL,
        certification_level TEXT NOT NULL,
        base_territory_id  TEXT NOT NULL,
        max_caseload       INTEGER NOT NULL,
        active             INTEGER NOT NULL,
        FOREIGN KEY (base_territory_id) REFERENCES territories(territory_id)
    )""")
    for a in adjusters:
        cur.execute("INSERT INTO adjusters VALUES (?,?,?,?,?,?)",
                    (a["adjuster_id"], a["name"], a["certification_level"],
                     a["base_territory_id"], a["max_caseload"], a["active"]))

    cur.execute("""CREATE TABLE claims (
        claim_id            TEXT PRIMARY KEY,
        severity_score      INTEGER NOT NULL,
        claim_type          TEXT NOT NULL,
        territory_id        TEXT NOT NULL,
        status              TEXT NOT NULL,
        date_filed          TEXT NOT NULL,
        estimated_value     REAL NOT NULL,
        assigned_adjuster_id TEXT,
        FOREIGN KEY (territory_id)        REFERENCES territories(territory_id),
        FOREIGN KEY (assigned_adjuster_id) REFERENCES adjusters(adjuster_id)
    )""")
    for c in claims:
        assigned = claim_to_adjuster.get(c["claim_id"])
        cur.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?)",
                    (c["claim_id"], c["severity_score"], c["claim_type"],
                     c["territory_id"], c["status"], c["date_filed"],
                     c["estimated_value"], assigned))

    cur.execute("""CREATE TABLE adjuster_specialties (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        adjuster_id      TEXT NOT NULL,
        claim_type       TEXT NOT NULL,
        proficiency_score INTEGER NOT NULL,
        FOREIGN KEY (adjuster_id) REFERENCES adjusters(adjuster_id)
    )""")
    for s in specialties:
        cur.execute(
            "INSERT INTO adjuster_specialties (adjuster_id,claim_type,proficiency_score) VALUES (?,?,?)",
            (s["adjuster_id"], s["claim_type"], s["proficiency_score"]))

    cur.execute("""CREATE TABLE travel_times (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        from_territory_id TEXT NOT NULL,
        to_territory_id   TEXT NOT NULL,
        travel_hours      REAL NOT NULL,
        FOREIGN KEY (from_territory_id) REFERENCES territories(territory_id),
        FOREIGN KEY (to_territory_id)   REFERENCES territories(territory_id)
    )""")
    cur.execute("CREATE INDEX idx_travel_from ON travel_times(from_territory_id)")
    for tt in travel_times:
        cur.execute(
            "INSERT INTO travel_times (from_territory_id,to_territory_id,travel_hours) VALUES (?,?,?)",
            (tt["from_territory_id"], tt["to_territory_id"], tt["travel_hours"]))

    cur.execute("""CREATE TABLE settlement_history (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        adjuster_id         TEXT NOT NULL,
        claim_type          TEXT NOT NULL,
        avg_settlement_days REAL NOT NULL,
        total_cases_handled INTEGER NOT NULL,
        FOREIGN KEY (adjuster_id) REFERENCES adjusters(adjuster_id)
    )""")
    for sh in settlement_history:
        cur.execute(
            "INSERT INTO settlement_history (adjuster_id,claim_type,avg_settlement_days,total_cases_handled) VALUES (?,?,?,?)",
            (sh["adjuster_id"], sh["claim_type"],
             sh["avg_settlement_days"], sh["total_cases_handled"]))

    conn.commit()
    conn.close()

    # ══════════════════════════════════════════════════════════════════════
    #  WORKSPACE – fixed config files (not counted in SCALE)
    # ══════════════════════════════════════════════════════════════════════

    # severity_tiers.json
    with open(os.path.join(workspace, "severity_tiers.json"), "w") as f:
        json.dump({
            "tiers": [
                {"name": "low",      "min_score": 1,  "max_score": 25},
                {"name": "medium",   "min_score": 26, "max_score": 50},
                {"name": "high",     "min_score": 51, "max_score": 75},
                {"name": "critical", "min_score": 76, "max_score": 100},
            ]
        }, f, indent=2)

    # certification_requirements.csv
    with open(os.path.join(workspace, "certification_requirements.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["severity_tier", "min_certification"])
        w.writerow(["low",      "junior"])
        w.writerow(["medium",   "standard"])
        w.writerow(["high",     "senior"])
        w.writerow(["critical", "expert"])

    # assignment_policy.yaml
    policy = {
        "scoring_weights": {
            "proficiency": 0.35,
            "proximity":   0.25,
            "capacity":    0.20,
            "history":     0.20,
        },
        "parameters": {
            "max_travel_hours":       12.0,
            "max_settlement_days":    90.0,
            "min_proficiency":        40,
            "default_settlement_days": 45.0,
        },
        "bonuses": {
            "same_region_bonus":  0.05,
            "urgency_multiplier": 1.30,
            "platinum_bonus":     0.15,
        },
    }
    with open(os.path.join(workspace, "assignment_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # assignment_rules.txt
    rules_text = """\
Processing Order
Claims must be processed in descending order of severity score. When two claims \
share the same severity score, the claim with the earlier filing date takes priority. \
If both the severity score and filing date match, use the claim ID in ascending \
alphanumeric order as the final tiebreaker.

Eligibility Criteria
An adjuster is eligible for a claim only when every one of the following conditions \
holds: the adjuster is currently active; their certification level meets or exceeds \
the minimum required for the claim's severity tier (as defined in the certification \
requirements file); they possess a specialty matching the claim type with a proficiency \
score at or above the minimum proficiency threshold from the assignment policy; the \
travel time from their base territory to the claim territory does not exceed the \
maximum travel hours parameter; and their remaining capacity, which equals their \
maximum caseload minus their current active cases minus any claims already assigned \
to them earlier in this same daily batch, is greater than zero.

Score Computation
The base assignment score is a weighted sum of four normalized components. The \
proficiency component equals the adjuster's proficiency score for the matching claim \
type divided by one hundred, multiplied by the proficiency weight. The proximity \
component equals the greater of zero and one minus the travel hours divided by the \
maximum travel hours parameter, multiplied by the proximity weight. The capacity \
component equals the remaining capacity divided by the adjuster's maximum caseload, \
multiplied by the capacity weight. The history component equals one minus the lesser \
of the adjuster's average settlement days for that claim type and the maximum \
settlement days parameter, divided by the maximum settlement days parameter, \
multiplied by the history weight. When no settlement history record exists for the \
adjuster and claim type combination, use the default settlement days value in place \
of the average.

After computing the base score, add the same-region bonus if the adjuster's base \
territory and the claim's territory belong to the same geographic region. Next, if \
the claim carries an urgent priority flag and the adjuster's base territory is \
exactly the same territory as the claim, multiply the cumulative score so far by the \
urgency multiplier. Finally, if the customer tier is platinum and the adjuster holds \
a senior or expert certification level, add the platinum bonus to the score.

Round the final assignment score to four decimal places.

Assignment Tiebreaker
When multiple eligible adjusters achieve identical final scores for a given claim, \
assign the claim to the adjuster whose adjuster ID is alphanumerically lowest.
"""
    with open(os.path.join(workspace, "assignment_rules.txt"), "w") as f:
        f.write(rules_text)

    # ══════════════════════════════════════════════════════════════════════
    #  WORKSPACE – scalable data files
    # ══════════════════════════════════════════════════════════════════════
    n_claims_files    = max(1, round(NF * 3 / 8))
    n_caseload_files  = max(1, round(NF * 3 / 8))
    n_territory_files = max(1, NF - n_claims_files - n_caseload_files)

    # -- Claims supplementary CSVs --
    priority_pool = (["urgent"] * 15 + ["normal"] * 70 + ["low"] * 15)
    tier_pool     = (["platinum"] * 10 + ["gold"] * 30
                     + ["silver"] * 40 + ["bronze"] * 20)
    supp_data = []
    for c in claims:
        supp_data.append({
            "claim_id":      c["claim_id"],
            "priority_flag": str(rng.choice(priority_pool)),
            "customer_tier": str(rng.choice(tier_pool)),
        })

    chunk = max(1, math.ceil(len(supp_data) / n_claims_files))
    for fi in range(n_claims_files):
        rows = supp_data[fi * chunk : (fi + 1) * chunk]
        if not rows:
            continue
        fname = f"claims_supplementary_{fi+1:02d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["claim_id", "priority_flag", "customer_tier"])
            w.writeheader()
            w.writerows(rows)

    # -- Caseload snapshot JSONs --
    caseload_entries = []
    for aid in active_ids:
        caseload_entries.append({
            "adjuster_id":        aid,
            "current_active_cases": caseload_map.get(aid, 0),
        })

    chunk = max(1, math.ceil(len(caseload_entries) / n_caseload_files))
    for fi in range(n_caseload_files):
        rows = caseload_entries[fi * chunk : (fi + 1) * chunk]
        if not rows:
            continue
        fname = f"caseload_snapshot_{fi+1:02d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump({"snapshot_date": BASE_DATE.isoformat(), "adjusters": rows}, f, indent=2)

    # -- Territory zone YAMLs --
    terr_entries = []
    for t in territories:
        terr_entries.append({
            "territory_id":   t["territory_id"],
            "territory_name": t["territory_name"],
            "region":         t["region"],
        })

    chunk = max(1, math.ceil(len(terr_entries) / n_territory_files))
    for fi in range(n_territory_files):
        rows = terr_entries[fi * chunk : (fi + 1) * chunk]
        if not rows:
            continue
        fname = f"territory_zones_{fi+1:02d}.yaml"
        with open(os.path.join(workspace, fname), "w") as f:
            yaml.dump({"territories": rows}, f, default_flow_style=False, sort_keys=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
