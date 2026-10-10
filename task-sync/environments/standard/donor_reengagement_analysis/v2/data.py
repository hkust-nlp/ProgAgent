import argparse
import os
import sqlite3
import json
import csv
import random

import numpy as np
import pandas as pd
import yaml
from faker import Faker


SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 30,
}

SEGMENTS = ["Major Donor", "Mid-Level", "Grassroots", "Corporate", "Young Professional"]
INCOME_BRACKETS = ["Under $30K", "$30K-$60K", "$60K-$100K", "$100K-$150K", "Over $150K"]
CAMPAIGN_TYPES = [
    "Annual Appeal", "Emergency Relief", "Capital Campaign", "Monthly Newsletter",
    "Event Promotion", "Year-End Giving", "Spring Drive", "Matching Gift",
]
EVENT_TYPES = [
    "Gala", "Fundraiser Dinner", "Charity Run", "Volunteer Day",
    "Auction", "Workshop", "Donor Appreciation", "Community Outreach",
]
REFERENCE_DATE = pd.Timestamp("2025-10-01")


def seed_all():
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)


# ---------------------------------------------------------------------------
# Data generators
# ---------------------------------------------------------------------------

def generate_donors(fake, n):
    donors = []
    for i in range(1, n + 1):
        seg = random.choices(SEGMENTS, weights=[10, 25, 40, 10, 15])[0]
        inc = random.choices(INCOME_BRACKETS, weights=[10, 20, 30, 25, 15])[0]
        reg = fake.date_between(start_date="-8y", end_date="-1y")
        donors.append({
            "id": i,
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "age": random.randint(22, 78),
            "income_bracket": inc,
            "zip_code": fake.zipcode(),
            "segment": seg,
            "registration_date": str(reg),
        })
    return donors


def generate_donations(donors, n_min):
    """~40 % active (recent), ~35 % lapsed (old only), rest mixed."""
    n = len(donors)
    indices = list(range(n))
    random.shuffle(indices)
    active_n = int(n * 0.40)
    lapsed_n = int(n * 0.35)
    active_set = set(indices[:active_n])
    lapsed_set = set(indices[active_n: active_n + lapsed_n])

    base_amounts = {
        "Major Donor": 500, "Mid-Level": 150, "Grassroots": 30,
        "Corporate": 300, "Young Professional": 75,
    }

    donations = []
    don_id = 1
    for donor in donors:
        idx = donor["id"] - 1
        nd = random.choices([1, 2, 3, 4, 5, 7, 10],
                            weights=[10, 15, 25, 20, 15, 10, 5])[0]
        is_rec = random.random() < 0.30
        freq = random.choice(["monthly", "quarterly", "annually"]) if is_rec else "one-time"
        base = base_amounts[donor["segment"]]

        for _ in range(nd):
            amt = round(base * random.uniform(0.5, 3.0), 2)
            if idx in active_set:
                days_ago = random.randint(1, 350)
            elif idx in lapsed_set:
                days_ago = random.randint(400, 2000)
            else:
                days_ago = random.randint(1, 2000)
            don_date = REFERENCE_DATE - pd.Timedelta(days=days_ago)
            donations.append({
                "id": don_id,
                "donor_id": donor["id"],
                "amount": amt,
                "donation_date": str(don_date.date()),
                "is_recurring": 1 if is_rec else 0,
                "frequency": freq,
            })
            don_id += 1

    while len(donations) < n_min:
        donor = random.choice(donors)
        base = base_amounts[donor["segment"]]
        amt = round(base * random.uniform(0.5, 3.0), 2)
        days_ago = random.randint(1, 2000)
        don_date = REFERENCE_DATE - pd.Timedelta(days=days_ago)
        donations.append({
            "id": don_id,
            "donor_id": donor["id"],
            "amount": amt,
            "donation_date": str(don_date.date()),
            "is_recurring": random.choice([0, 1]),
            "frequency": random.choice(["one-time", "monthly", "quarterly"]),
        })
        don_id += 1
    return donations


def generate_campaigns(fake, n):
    campaigns = []
    for i in range(1, n + 1):
        sd = fake.date_between(start_date="-3y", end_date="-30d")
        ct = random.choice(CAMPAIGN_TYPES)
        campaigns.append({
            "id": i,
            "campaign_name": f"{ct} - {fake.word().capitalize()} {sd.year}",
            "send_date": str(sd),
            "subject": fake.sentence(nb_words=6),
            "campaign_type": ct,
        })
    return campaigns


def generate_campaign_interactions(donors, campaigns, n_min):
    interactions = []
    int_id = 1
    seen = set()
    for donor in donors:
        nc = min(random.randint(3, 15), len(campaigns))
        chosen = random.sample(campaigns, nc)
        for c in chosen:
            key = (donor["id"], c["id"])
            if key in seen:
                continue
            seen.add(key)
            opened = 1 if random.random() < 0.40 else 0
            clicked = 1 if opened and random.random() < 0.30 else 0
            interactions.append({
                "id": int_id,
                "campaign_id": c["id"],
                "donor_id": donor["id"],
                "sent": 1,
                "opened": opened,
                "clicked": clicked,
            })
            int_id += 1

    while len(interactions) < n_min:
        d = random.choice(donors)
        c = random.choice(campaigns)
        key = (d["id"], c["id"])
        if key in seen:
            continue
        seen.add(key)
        opened = 1 if random.random() < 0.40 else 0
        clicked = 1 if opened and random.random() < 0.30 else 0
        interactions.append({
            "id": int_id,
            "campaign_id": c["id"],
            "donor_id": d["id"],
            "sent": 1,
            "opened": opened,
            "clicked": clicked,
        })
        int_id += 1
    return interactions


def generate_events(fake, n):
    events = []
    locations = [fake.city() for _ in range(10)]
    for i in range(1, n + 1):
        ed = fake.date_between(start_date="-3y", end_date="-14d")
        et = random.choice(EVENT_TYPES)
        events.append({
            "id": i,
            "event_name": f"{et} - {fake.word().capitalize()} {ed.year}",
            "event_date": str(ed),
            "event_type": et,
            "location": random.choice(locations),
        })
    return events


def generate_event_attendance(donors, events, n_min):
    attendance = []
    att_id = 1
    rsvp_opts = ["confirmed", "declined", "tentative", "no_response"]
    seen = set()
    for donor in donors:
        ne = min(random.randint(1, 8), len(events))
        chosen = random.sample(events, ne)
        for ev in chosen:
            key = (donor["id"], ev["id"])
            if key in seen:
                continue
            seen.add(key)
            rsvp = random.choices(rsvp_opts, weights=[40, 20, 20, 20])[0]
            attended = 1 if rsvp in ("confirmed", "tentative") and random.random() < 0.70 else 0
            attendance.append({
                "id": att_id,
                "event_id": ev["id"],
                "donor_id": donor["id"],
                "rsvp_status": rsvp,
                "attended": attended,
            })
            att_id += 1

    while len(attendance) < n_min:
        d = random.choice(donors)
        ev = random.choice(events)
        key = (d["id"], ev["id"])
        if key in seen:
            continue
        seen.add(key)
        rsvp = random.choice(rsvp_opts)
        attended = 1 if rsvp in ("confirmed", "tentative") and random.random() < 0.70 else 0
        attendance.append({
            "id": att_id,
            "event_id": ev["id"],
            "donor_id": d["id"],
            "rsvp_status": rsvp,
            "attended": attended,
        })
        att_id += 1
    return attendance


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS donors (
        id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT,
        email TEXT, phone TEXT, age INTEGER, income_bracket TEXT,
        zip_code TEXT, segment TEXT, registration_date TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS donations (
        id INTEGER PRIMARY KEY, donor_id INTEGER, amount REAL,
        donation_date TEXT, is_recurring INTEGER, frequency TEXT,
        FOREIGN KEY (donor_id) REFERENCES donors(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS campaigns (
        id INTEGER PRIMARY KEY, campaign_name TEXT, send_date TEXT,
        subject TEXT, campaign_type TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS campaign_interactions (
        id INTEGER PRIMARY KEY, campaign_id INTEGER, donor_id INTEGER,
        sent INTEGER DEFAULT 1, opened INTEGER, clicked INTEGER,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
        FOREIGN KEY (donor_id) REFERENCES donors(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, event_name TEXT, event_date TEXT,
        event_type TEXT, location TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS event_attendance (
        id INTEGER PRIMARY KEY, event_id INTEGER, donor_id INTEGER,
        rsvp_status TEXT, attended INTEGER,
        FOREIGN KEY (event_id) REFERENCES events(id),
        FOREIGN KEY (donor_id) REFERENCES donors(id)
    )""")
    conn.commit()


def insert_data(conn, table, rows):
    if not rows:
        return
    cols = list(rows[0].keys())
    ph = ", ".join(["?"] * len(cols))
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph})",
        [tuple(r[c] for c in cols) for r in rows],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Workspace generation
# ---------------------------------------------------------------------------

def generate_workspace(workspace, donors, donations, campaigns,
                       campaign_interactions, events, event_attendance_data):
    os.makedirs(workspace, exist_ok=True)

    nf = SCALE["num_workspace_files"]
    n_donor_notes = max(2, round(nf * 0.3))
    n_camp_reports = max(2, round(nf * 0.3))
    n_event_summaries = max(1, round(nf * 0.2))
    n_comm_logs = nf - n_donor_notes - n_camp_reports - n_event_summaries
    if n_comm_logs < 1:
        n_comm_logs = 1
        n_event_summaries = nf - n_donor_notes - n_camp_reports - n_comm_logs

    # ---- Donor Notes (JSON) ------------------------------------------------
    dnc_count = max(3, len(donors) // 15)
    dnc_ids = set(random.sample([d["id"] for d in donors], dnc_count))
    contact_methods = ["email", "phone", "mail"]
    note_phrases = [
        "Very engaged in past.", "Needs personal touch.",
        "Prefers low-key communication.", "Responded well to events.",
        "Has potential for major gift.", "Recently moved.",
        "Long-time supporter.", "Interested in volunteering.",
        "Attends galas regularly.", "Corporate liaison.",
    ]

    donor_chunks = np.array_split(donors, n_donor_notes)
    for i, chunk in enumerate(donor_chunks):
        notes = {}
        for d in chunk:
            notes[str(d["id"])] = {
                "donor_id": d["id"],
                "preferred_contact_method": random.choice(contact_methods),
                "do_not_contact": d["id"] in dnc_ids,
                "notes": random.choice(note_phrases),
            }
        with open(os.path.join(workspace, f"donor_notes_{i + 1}.json"), "w") as f:
            json.dump(notes, f, indent=2)

    # ---- Campaign Reports (CSV) --------------------------------------------
    ci_by_camp = {}
    for ci in campaign_interactions:
        ci_by_camp.setdefault(ci["campaign_id"], []).append(ci)

    camp_chunks = np.array_split(campaigns, n_camp_reports)
    for i, chunk in enumerate(camp_chunks):
        rows = []
        for c in chunk:
            cis = ci_by_camp.get(c["id"], [])
            total_sent = len(cis)
            total_opened = sum(x["opened"] for x in cis)
            total_clicked = sum(x["clicked"] for x in cis)
            rows.append({
                "campaign_id": c["id"],
                "campaign_name": c["campaign_name"],
                "campaign_type": c["campaign_type"],
                "send_date": c["send_date"],
                "total_recipients": total_sent,
                "total_opens": total_opened,
                "total_clicks": total_clicked,
                "open_rate": round(total_opened / max(1, total_sent), 4),
                "click_rate": round(total_clicked / max(1, total_sent), 4),
            })
        with open(os.path.join(workspace, f"campaign_report_{i + 1}.csv"), "w",
                  newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    # ---- Event Summaries (Markdown) ----------------------------------------
    ea_by_ev = {}
    for ea in event_attendance_data:
        ea_by_ev.setdefault(ea["event_id"], []).append(ea)

    ev_chunks = np.array_split(events, n_event_summaries)
    for i, chunk in enumerate(ev_chunks):
        lines = []
        for e in chunk:
            eas = ea_by_ev.get(e["id"], [])
            goal = random.choice([5000, 10000, 15000, 20000, 25000, 50000])
            lines.append(f"## {e['event_name']}")
            lines.append(f"- Date: {e['event_date']}")
            lines.append(f"- Type: {e['event_type']}")
            lines.append(f"- Location: {e['location']}")
            lines.append(f"- RSVPs: {len(eas)}")
            lines.append(f"- Attended: {sum(x['attended'] for x in eas)}")
            lines.append(f"- Fundraising Goal: ${goal:,}")
            lines.append("")
        with open(os.path.join(workspace, f"event_summary_{i + 1}.md"), "w") as f:
            f.write("\n".join(lines))

    # ---- Communication Logs (TXT) ------------------------------------------
    donor_chunks_comm = np.array_split(donors, n_comm_logs)
    for i, chunk in enumerate(donor_chunks_comm):
        lines = []
        for d in chunk:
            nl = random.randint(1, 4)
            for _ in range(nl):
                ago = random.randint(1, 1000)
                log_date = REFERENCE_DATE - pd.Timedelta(days=ago)
                ch = random.choice(["email", "phone", "in-person", "mail"])
                outcome = random.choice(["positive", "neutral", "no response", "negative"])
                lines.append(
                    f"[{log_date.date()}] Donor #{d['id']} "
                    f"({d['first_name']} {d['last_name']}) - "
                    f"Channel: {ch} - Outcome: {outcome}"
                )
        with open(os.path.join(workspace, f"comm_log_{i + 1}.txt"), "w") as f:
            f.write("\n".join(lines))

    # ---- Fixed config files (outside SCALE count) --------------------------
    policy = {
        "reference_date": "2025-10-01",
        "lapsed_threshold_months": 12,
        "engagement_scoring": {
            "email_open_weight": 0.35,
            "event_attendance_weight": 0.35,
            "giving_history_weight": 0.30,
        },
        "giving_benchmark": 5000,
        "high_potential_threshold": 0.40,
        "ask_amount": {
            "base_method": "average_past_donation",
            "recency_tiers": [
                {"max_months_since_last": 18, "factor": 1.0},
                {"max_months_since_last": 24, "factor": 0.85},
                {"max_months_since_last": 9999, "factor": 0.7},
            ],
            "rounding": 5,
        },
    }
    with open(os.path.join(workspace, "reengagement_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    segment_tiers = {
        "Major Donor": {"priority": 1, "multiplier": 1.5, "min_ask": 500, "max_ask": 10000},
        "Mid-Level": {"priority": 2, "multiplier": 1.2, "min_ask": 100, "max_ask": 2000},
        "Grassroots": {"priority": 3, "multiplier": 1.0, "min_ask": 25, "max_ask": 500},
        "Corporate": {"priority": 4, "multiplier": 1.3, "min_ask": 250, "max_ask": 5000},
        "Young Professional": {"priority": 5, "multiplier": 1.1, "min_ask": 50, "max_ask": 1000},
    }
    with open(os.path.join(workspace, "segment_tiers.json"), "w") as f:
        json.dump(segment_tiers, f, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    seed_all()
    fake = Faker()

    n = SCALE["rows_per_table"]

    donors = generate_donors(fake, n)
    donations = generate_donations(donors, n)
    campaigns = generate_campaigns(fake, n)
    campaign_interactions = generate_campaign_interactions(donors, campaigns, n)
    events = generate_events(fake, n)
    event_attendance_data = generate_event_attendance(donors, events, n)

    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    insert_data(conn, "donors", donors)
    insert_data(conn, "donations", donations)
    insert_data(conn, "campaigns", campaigns)
    insert_data(conn, "campaign_interactions", campaign_interactions)
    insert_data(conn, "events", events)
    insert_data(conn, "event_attendance", event_attendance_data)
    conn.close()

    generate_workspace(args.workspace, donors, donations, campaigns,
                       campaign_interactions, events, event_attendance_data)

    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    print(f"  Donors: {len(donors)}")
    print(f"  Donations: {len(donations)}")
    print(f"  Campaigns: {len(campaigns)}")
    print(f"  Campaign Interactions: {len(campaign_interactions)}")
    print(f"  Events: {len(events)}")
    print(f"  Event Attendance: {len(event_attendance_data)}")


if __name__ == "__main__":
    main()
