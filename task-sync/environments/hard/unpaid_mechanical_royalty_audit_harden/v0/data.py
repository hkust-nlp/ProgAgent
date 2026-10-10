"""
Data generation script for the Mechanical Royalty Discrepancy task.
Generates a SQLite database and workspace files for cross-referencing
ISRC codes, publisher/songwriter splits, and payment ledgers.
"""
import argparse
import sqlite3
import os
import json
import csv
import numpy as np
import pandas as pd
from faker import Faker
from collections import defaultdict

SCALE = {
    "rows_per_table": 80,
    "num_workspace_files": 8,
}

SEED = 42

# --- Constants used for both data generation and workspace config files ---
PLATFORM_RATES = {
    "Spotify": 0.0040,
    "Apple_Music": 0.0070,
    "Amazon_Music": 0.0045,
    "Tidal": 0.0090,
    "YouTube_Music": 0.0020,
    "Deezer": 0.0035,
    "Pandora": 0.0030,
    "SoundCloud": 0.0025,
}

PLATFORMS = list(PLATFORM_RATES.keys())

PERIOD_DEFS = [
    {"start": "2024-01-01", "end": "2024-03-31", "label": "2024_Q1"},
    {"start": "2024-04-01", "end": "2024-06-30", "label": "2024_Q2"},
    {"start": "2024-07-01", "end": "2024-09-30", "label": "2024_Q3"},
    {"start": "2024-10-01", "end": "2024-12-31", "label": "2024_Q4"},
    {"start": "2025-01-01", "end": "2025-03-31", "label": "2025_Q1"},
    {"start": "2025-04-01", "end": "2025-06-30", "label": "2025_Q2"},
]

TERRITORIES = ["US", "GB", "DE", "FR", "JP", "AU", "CA", "BR", "KR", "SE"]

TERRITORY_SOCIETIES = {
    "US": {"society": "HFA/MLC", "commission_rate": 0.060},
    "GB": {"society": "MCPS", "commission_rate": 0.100},
    "DE": {"society": "GEMA", "commission_rate": 0.120},
    "FR": {"society": "SACEM", "commission_rate": 0.110},
    "JP": {"society": "JASRAC", "commission_rate": 0.090},
    "AU": {"society": "AMCOS", "commission_rate": 0.080},
    "CA": {"society": "CMRRA", "commission_rate": 0.070},
    "BR": {"society": "UBC", "commission_rate": 0.130},
    "KR": {"society": "KOMCA", "commission_rate": 0.100},
    "SE": {"society": "STIM", "commission_rate": 0.080},
}

GENRES = [
    "Pop", "Rock", "Hip-Hop", "R&B", "Electronic",
    "Country", "Jazz", "Classical", "Latin", "Indie",
]

LABELS = [
    "Universal Music", "Sony Music", "Warner Music", "BMG", "Concord",
    "Kobalt", "Downtown", "AWAL", "Empire", "Believe Digital",
    "Republic Records", "Interscope", "Atlantic Records", "Def Jam",
    "Columbia Records",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    np.random.seed(SEED)
    rng = np.random.RandomState(SEED)
    fake = Faker()
    Faker.seed(SEED)

    db_path = args.db_path
    workspace = args.workspace
    os.makedirs(workspace, exist_ok=True)

    n_tracks = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # ================================================================
    # 1. Generate entity pools
    # ================================================================
    publisher_pool = []
    seen_pub = set()
    while len(publisher_pool) < max(40, n_tracks // 2):
        name = fake.company() + " Publishing"
        if name not in seen_pub:
            publisher_pool.append(name)
            seen_pub.add(name)

    songwriter_pool = []
    seen_sw = set()
    while len(songwriter_pool) < max(80, n_tracks):
        name = fake.name()
        if name not in seen_sw:
            songwriter_pool.append(name)
            seen_sw.add(name)

    # ================================================================
    # 2. Generate ISRCs
    # ================================================================
    n_extra = max(5, int(n_tracks * 0.12))
    n_total = n_tracks + n_extra
    cc_choices = ["US", "GB", "DE", "FR", "JP"]

    all_isrcs = []
    for i in range(n_total):
        cc = cc_choices[i % len(cc_choices)]
        all_isrcs.append(f"{cc}-S3K-24-{i:05d}")

    registered_track_isrcs = all_isrcs[:n_tracks]
    extra_isrcs = all_isrcs[n_tracks:]

    # ================================================================
    # 3. Assign discrepancy categories (no-reg & split-error)
    # ================================================================
    indices = list(range(n_tracks))
    rng.shuffle(indices)

    n_no_reg = max(4, int(n_tracks * 0.12))
    n_split_err = max(3, int(n_tracks * 0.10))

    ptr = 0
    no_reg_set = set(indices[ptr:ptr + n_no_reg]); ptr += n_no_reg
    split_err_set = set(indices[ptr:ptr + n_split_err]); ptr += n_split_err

    # ================================================================
    # 4. Generate tracks table rows
    # ================================================================
    tracks_rows = []
    for i, isrc in enumerate(registered_track_isrcs):
        title = fake.catch_phrase()
        artist = fake.name()
        album = fake.bs().title()
        label = str(rng.choice(LABELS))
        year = int(rng.choice([2020, 2021, 2022, 2023, 2024]))
        month = int(rng.randint(1, 13))
        release_date = f"{year}-{month:02d}-01"
        genre = str(rng.choice(GENRES))
        duration = int(rng.randint(120, 361))
        tracks_rows.append((
            i + 1, isrc, title, artist, album,
            label, release_date, genre, duration,
        ))

    # ================================================================
    # 5. Generate registrations
    # ================================================================
    reg_rows = []
    reg_id = 1
    isrc_registrations = {}

    for i, isrc in enumerate(registered_track_isrcs):
        if i in no_reg_set:
            continue

        territory = str(rng.choice(TERRITORIES))
        effective_date = tracks_rows[i][6]
        n_songwriters = int(rng.choice([1, 2]))

        publisher = str(rng.choice(publisher_pool))
        songwriters = [str(rng.choice(songwriter_pool)) for _ in range(n_songwriters)]

        if i in split_err_set:
            if rng.random() < 0.5:
                pub_split = round(float(rng.uniform(45, 65)), 2)
                sw_splits = [round(float(rng.uniform(28, 48)), 2) for _ in songwriters]
                while pub_split + sum(sw_splits) <= 102:
                    pub_split = round(pub_split + 3.0, 2)
            else:
                pub_split = round(float(rng.uniform(15, 28)), 2)
                sw_splits = [round(float(rng.uniform(8, 18)), 2) for _ in songwriters]
                while pub_split + sum(sw_splits) >= 98:
                    sw_splits[-1] = round(sw_splits[-1] - 5.0, 2)
        else:
            pub_split = round(float(rng.uniform(30, 60)), 2)
            remaining = round(100.0 - pub_split, 2)
            if n_songwriters == 1:
                sw_splits = [remaining]
            else:
                first = round(float(rng.uniform(remaining * 0.3, remaining * 0.7)), 2)
                sw_splits = [first, round(remaining - first, 2)]

        regs_for_isrc = []

        reg_rows.append((
            reg_id, isrc, publisher, "publisher", "publisher",
            pub_split, territory, effective_date, "active",
        ))
        regs_for_isrc.append({
            "entity": publisher, "type": "publisher",
            "split": pub_split, "territory": territory,
        })
        reg_id += 1

        for j, sw in enumerate(songwriters):
            role = "composer" if j == 0 else "lyricist"
            reg_rows.append((
                reg_id, isrc, sw, "songwriter", role,
                sw_splits[j], territory, effective_date, "active",
            ))
            regs_for_isrc.append({
                "entity": sw, "type": "songwriter",
                "split": sw_splits[j], "territory": territory,
            })
            reg_id += 1

        isrc_registrations[isrc] = regs_for_isrc

    # ================================================================
    # 6. Generate streaming report workspace files
    # ================================================================
    all_combos = [(p, d) for p in PLATFORMS for d in PERIOD_DEFS]
    combo_indices = list(range(len(all_combos)))
    rng.shuffle(combo_indices)
    selected_combos = [all_combos[ci] for ci in sorted(combo_indices[:n_files])]

    streaming_universe = list(registered_track_isrcs) + list(extra_isrcs)
    all_streaming_entries = []

    for platform, period_def in selected_combos:
        period_label = period_def["label"]
        fname = f"streaming_{platform}_{period_label}.csv"

        n_entries = max(20, int(len(streaming_universe) * float(rng.uniform(0.45, 0.65))))
        n_entries = min(n_entries, len(streaming_universe))
        selected = list(rng.choice(streaming_universe, size=n_entries, replace=False))

        rows = []
        for isrc in selected:
            stream_count = int(rng.randint(500, 80001))
            territory = str(rng.choice(TERRITORIES))
            rows.append({
                "isrc": isrc,
                "stream_count": stream_count,
                "territory": territory,
            })
            all_streaming_entries.append((
                isrc, platform, period_label, stream_count, territory,
            ))

        df = pd.DataFrame(rows)
        df.to_csv(os.path.join(workspace, fname), index=False)

    # ================================================================
    # 7. Determine unpaid / underpaid sets
    # ================================================================
    streamed_isrc_set = set(e[0] for e in all_streaming_entries)
    registered_and_streamed = [
        isrc for isrc in registered_track_isrcs
        if isrc in streamed_isrc_set and isrc in isrc_registrations
    ]

    ras_indices = list(range(len(registered_and_streamed)))
    rng.shuffle(ras_indices)

    n_unpaid = max(3, int(len(registered_and_streamed) * 0.15))
    n_underpaid = max(3, int(len(registered_and_streamed) * 0.12))

    ptr2 = 0
    unpaid_isrcs = set(
        registered_and_streamed[idx]
        for idx in ras_indices[ptr2:ptr2 + n_unpaid]
    )
    ptr2 += n_unpaid
    underpaid_isrcs = set(
        registered_and_streamed[idx]
        for idx in ras_indices[ptr2:ptr2 + n_underpaid]
    )
    ptr2 += n_underpaid

    # ================================================================
    # 8. Generate payments
    # ================================================================
    streaming_by_isrc_period = defaultdict(lambda: defaultdict(list))
    for isrc, platform, period_label, stream_count, territory in all_streaming_entries:
        streaming_by_isrc_period[isrc][period_label].append({
            "platform": platform,
            "stream_count": stream_count,
        })

    payment_rows = []
    payment_id = 1

    for isrc in registered_and_streamed:
        if isrc in unpaid_isrcs:
            continue

        regs = isrc_registrations[isrc]
        territory = regs[0]["territory"]
        commission_rate = TERRITORY_SOCIETIES.get(
            territory, {"commission_rate": 0.10}
        )["commission_rate"]

        for period_label, entries in streaming_by_isrc_period[isrc].items():
            period_gross = sum(
                e["stream_count"] * PLATFORM_RATES[e["platform"]]
                for e in entries
            )

            for reg in regs:
                payee_gross = period_gross * reg["split"] / 100.0
                payee_net = payee_gross * (1 - commission_rate)

                if isrc in underpaid_isrcs:
                    fraction = float(rng.uniform(0.30, 0.70))
                    amount = round(payee_net * fraction, 2)
                else:
                    amount = round(payee_net, 2)

                year = int(period_label.split("_")[0])
                quarter = int(period_label.split("_Q")[1])
                pay_month = quarter * 3 + 1
                pay_year = year
                if pay_month > 12:
                    pay_month -= 12
                    pay_year += 1
                payment_date = f"{pay_year}-{pay_month:02d}-15"

                payment_rows.append((
                    payment_id, isrc, reg["entity"], reg["type"],
                    amount, "USD", period_label, payment_date, "completed",
                ))
                payment_id += 1

    # ================================================================
    # 9. Generate royalty_accounts table
    # ================================================================
    entities_seen = {}
    for reg in reg_rows:
        entity_name = reg[2]
        entity_type = reg[3]
        territory = reg[6]
        if entity_name not in entities_seen:
            society = TERRITORY_SOCIETIES.get(
                territory, {"society": "Unknown"}
            )["society"]
            email = fake.email()
            bank_status = str(rng.choice(["verified", "pending", "unverified"]))
            entities_seen[entity_name] = (
                entity_name, entity_type, society, territory, bank_status, email,
            )

    account_rows = [
        (i, *vals) for i, vals in enumerate(entities_seen.values(), 1)
    ]

    while len(account_rows) < n_tracks:
        extra_name = fake.name() + " (inactive)"
        territory = str(rng.choice(TERRITORIES))
        society = TERRITORY_SOCIETIES.get(
            territory, {"society": "Unknown"}
        )["society"]
        account_rows.append((
            len(account_rows) + 1, extra_name, "songwriter",
            society, territory, "inactive", fake.email(),
        ))

    # ================================================================
    # 10. Write database
    # ================================================================
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE tracks (
        track_id INTEGER PRIMARY KEY,
        isrc TEXT UNIQUE NOT NULL,
        title TEXT,
        artist TEXT,
        album TEXT,
        label TEXT,
        release_date TEXT,
        genre TEXT,
        duration_seconds INTEGER
    )""")

    c.execute("""CREATE TABLE registrations (
        reg_id INTEGER PRIMARY KEY,
        isrc TEXT NOT NULL,
        entity_name TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        role TEXT,
        split_pct REAL NOT NULL,
        territory TEXT,
        effective_date TEXT,
        status TEXT DEFAULT 'active',
        FOREIGN KEY (isrc) REFERENCES tracks(isrc)
    )""")

    c.execute("""CREATE TABLE payments (
        payment_id INTEGER PRIMARY KEY,
        isrc TEXT NOT NULL,
        payee_name TEXT NOT NULL,
        payee_type TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT DEFAULT 'USD',
        period_label TEXT,
        payment_date TEXT,
        status TEXT DEFAULT 'completed',
        FOREIGN KEY (isrc) REFERENCES tracks(isrc)
    )""")

    c.execute("""CREATE TABLE royalty_accounts (
        account_id INTEGER PRIMARY KEY,
        entity_name TEXT NOT NULL,
        entity_type TEXT,
        collection_society TEXT,
        territory TEXT,
        bank_status TEXT,
        contact_email TEXT
    )""")

    c.executemany("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?,?)", tracks_rows)
    c.executemany("INSERT INTO registrations VALUES (?,?,?,?,?,?,?,?,?)", reg_rows)
    c.executemany("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?)", payment_rows)
    c.executemany("INSERT INTO royalty_accounts VALUES (?,?,?,?,?,?,?)", account_rows)

    conn.commit()

    for table in ["tracks", "registrations", "payments", "royalty_accounts"]:
        count = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")
        assert count >= n_tracks, (
            f"Table {table} has {count} rows, need >= {n_tracks}"
        )

    conn.close()

    # ================================================================
    # 11. Generate workspace configuration files (fixed, not scaled)
    # ================================================================

    # --- royalty_rates.yaml ---
    yaml_lines = [
        "# Mechanical royalty rates per streaming platform (USD per stream)",
        "platform_rates:",
    ]
    for plat, rate in PLATFORM_RATES.items():
        yaml_lines.append(f"  {plat}: {rate:.4f}")
    with open(os.path.join(workspace, "royalty_rates.yaml"), "w") as f:
        f.write("\n".join(yaml_lines) + "\n")

    # --- reconciliation_policy.json ---
    policy = {
        "shortfall_threshold_usd": 0.50,
        "split_tolerance_pct": 2.0,
        "currency": "USD",
        "amount_precision": 2,
    }
    with open(os.path.join(workspace, "reconciliation_policy.json"), "w") as f:
        json.dump(policy, f, indent=2)

    # --- territory_commissions.csv ---
    with open(
        os.path.join(workspace, "territory_commissions.csv"), "w", newline=""
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["territory_code", "society_name", "commission_rate"])
        for tc, info in TERRITORY_SOCIETIES.items():
            writer.writerow([tc, info["society"], info["commission_rate"]])

    # --- processing_notes.md ---
    notes = """\
# Royalty Reconciliation Processing Notes

Each streaming report file covers exactly one platform and one quarterly
reporting period. The file's name is the platform name followed by the period
label, and every entry in that file inherits its platform and reporting period
from the file name. Every distinct ISRC appearing in any streaming report must
be assessed for discrepancies.

When reconciling mechanical royalties, the expected net payment for each rights
holder is calculated as follows. First, determine the gross royalty for the ISRC
within a single reporting period by summing, across every streaming report entry
for that ISRC in that period, the product of the stream count and the per-stream
rate for the entry's platform. Then, for each rights holder registered under
that ISRC, multiply the period gross by the holder's split percentage divided
by one hundred and reduce the result by the collection society commission rate
associated with the registration territory.

    expected_net = period_gross * (split_pct / 100) * (1 - commission_rate)

When an ISRC appears across multiple reporting periods, each period's
contribution is computed independently. The total expected net for an ISRC is
the sum of per-period per-payee expected net amounts, with each individual
payee-period amount rounded to two decimal places before summing.

A track is considered to have a split anomaly when the sum of all registered
split percentages for that ISRC deviates from 100.00 by more than the tolerance
defined in the reconciliation policy.

Discrepancies fall into four categories:

UNREGISTERED -- ISRC found in streaming reports with no matching registration
record. The expected amount reported is the total gross royalty across all
streaming entries for that ISRC.

UNPAID -- ISRC is registered and has streaming activity but no corresponding
payment records at all. The expected amount is the total expected net across
all payees and periods.

UNDERPAID -- ISRC has payment records whose total falls below the total expected
net by more than the shortfall threshold.

SPLIT_ANOMALY -- The registered split percentages for the ISRC do not sum to
100 within the tolerance specified in the reconciliation policy.

A single ISRC may qualify under multiple discrepancy categories and must be
reported once for each category that applies.
"""
    with open(os.path.join(workspace, "processing_notes.md"), "w") as f:
        f.write(notes)

    print(f"\nDatabase created at {db_path}")
    print(f"Workspace generated in {workspace}/")
    print(f"  Streaming report files: {n_files}")
    print(f"  Fixed config files: 4")
    print(f"  Total tracks in DB: {n_tracks}")
    print(f"  Extra ISRCs (unregistered): {n_extra}")


if __name__ == "__main__":
    main()
