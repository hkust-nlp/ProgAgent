#!/usr/bin/env python3
"""Data generation for sanctions screening task."""

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
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 40,
    "num_workspace_files": 8,
}

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ---------------------------------------------------------------------------
# Pre-defined sanctioned names for deterministic matching
# ---------------------------------------------------------------------------
SANCTIONED_INDIVIDUALS = [
    {"name": "Viktor Sergeyevich Petrov", "nationality": "Russian", "dob": "1975-03-15",
     "list": "OFAC", "program": "UKRAINE-EO13661", "remarks": "Senior military official"},
    {"name": "Hassan Ali Mahmoud", "nationality": "Syrian", "dob": "1968-07-22",
     "list": "EU", "program": "EU-SYRIA", "remarks": "Government procurement official"},
    {"name": "Kim Sung-Ho", "nationality": "North Korean", "dob": "1980-11-03",
     "list": "UN", "program": "UN-1718", "remarks": "Weapons procurement network"},
    {"name": "Ahmad Reza Khalili", "nationality": "Iranian", "dob": "1972-09-18",
     "list": "OFAC", "program": "IRAN-TRA", "remarks": "Petrochemical sector"},
    {"name": "Omar Sheikh Abdullah", "nationality": "Yemeni", "dob": "1965-05-30",
     "list": "UN", "program": "UN-1267", "remarks": "Financial facilitator"},
    {"name": "Dmitri Andreyevich Volkov", "nationality": "Russian", "dob": "1970-01-12",
     "list": "EU", "program": "EU-RUSSIA", "remarks": "Defense sector executive"},
    {"name": "Faisal bin Mohammed Al-Rashid", "nationality": "Saudi", "dob": "1978-06-25",
     "list": "OFAC", "program": "SDGT", "remarks": "Terrorism financing network"},
    {"name": "Chen Wei Dong", "nationality": "Chinese", "dob": "1982-04-09",
     "list": "OFAC", "program": "DPRK-EO13810", "remarks": "Proliferation network"},
    {"name": "Abdul Karim Bashar", "nationality": "Syrian", "dob": "1960-12-01",
     "list": "EU", "program": "EU-SYRIA", "remarks": "Regime official"},
    {"name": "Yevgeny Nikolaevich Sorokin", "nationality": "Russian", "dob": "1969-08-14",
     "list": "OFAC", "program": "UKRAINE-EO13662", "remarks": "Energy sector"},
    {"name": "Mohammad Javad Tehrani", "nationality": "Iranian", "dob": "1974-02-28",
     "list": "UN", "program": "UN-2231", "remarks": "Nuclear program involvement"},
    {"name": "Li Xiang Ping", "nationality": "Chinese", "dob": "1985-10-17",
     "list": "UN", "program": "UN-1718", "remarks": "Export controls violation"},
    {"name": "Sergei Ivanovich Kozlov", "nationality": "Russian", "dob": "1966-07-03",
     "list": "EU", "program": "EU-RUSSIA", "remarks": "Financial sector"},
    {"name": "Mustafa Kemal Ozturk", "nationality": "Turkish", "dob": "1977-11-20",
     "list": "OFAC", "program": "SDGT", "remarks": "Facilitation network"},
    {"name": "Park Chul-Soo", "nationality": "North Korean", "dob": "1979-03-08",
     "list": "UN", "program": "UN-1718", "remarks": "Diplomatic front operations"},
    {"name": "Rashid Hamad Al-Thani", "nationality": "Qatari", "dob": "1971-09-12",
     "list": "OFAC", "program": "SDGT", "remarks": "Hawala network operator"},
    {"name": "Alexei Mikhailovich Popov", "nationality": "Russian", "dob": "1973-05-22",
     "list": "EU", "program": "EU-RUSSIA", "remarks": "Arms trading"},
    {"name": "Tariq Aziz Siddiqui", "nationality": "Pakistani", "dob": "1967-01-30",
     "list": "UN", "program": "UN-1267", "remarks": "Extremist financing"},
    {"name": "Boris Andreyevich Kuznetsov", "nationality": "Russian", "dob": "1964-04-18",
     "list": "OFAC", "program": "UKRAINE-EO13661", "remarks": "State enterprise director"},
    {"name": "Ibrahim Yusuf Osman", "nationality": "Somali", "dob": "1976-08-05",
     "list": "UN", "program": "UN-751", "remarks": "Charcoal trade facilitator"},
]

SANCTIONED_ENTITIES = [
    {"name": "Petrochem Holdings International", "country": "Iran",
     "list": "OFAC", "program": "IRAN-TRA", "remarks": "Petroleum sector front company"},
    {"name": "Golden Dragon Trading Corp", "country": "North Korea",
     "list": "UN", "program": "UN-1718", "remarks": "Procurement front"},
    {"name": "Crescent Star Shipping LLC", "country": "Syria",
     "list": "EU", "program": "EU-SYRIA", "remarks": "Oil transport sanctions evasion"},
    {"name": "Volkov Industrial Group", "country": "Russia",
     "list": "OFAC", "program": "UKRAINE-EO13661", "remarks": "Defense conglomerate"},
    {"name": "Phoenix Rising Investments Ltd", "country": "Myanmar",
     "list": "EU", "program": "EU-MYANMAR", "remarks": "Military-linked investments"},
    {"name": "East Wind Technology Co", "country": "China",
     "list": "OFAC", "program": "DPRK-EO13810", "remarks": "Dual-use technology exports"},
    {"name": "Al-Rashid Financial Services", "country": "UAE",
     "list": "OFAC", "program": "SDGT", "remarks": "Terrorism financing conduit"},
    {"name": "Crimson Meridian Logistics", "country": "Russia",
     "list": "EU", "program": "EU-RUSSIA", "remarks": "Sanctions evasion shipping"},
    {"name": "Sovereign Capital Partners", "country": "Cayman Islands",
     "list": "OFAC", "program": "SDN", "remarks": "Shell company network"},
    {"name": "Black Sea Maritime Transport", "country": "Russia",
     "list": "EU", "program": "EU-RUSSIA", "remarks": "Oil tanker fleet"},
    {"name": "Jade Mountain Resources Ltd", "country": "Myanmar",
     "list": "UN", "program": "UN-MYANMAR", "remarks": "Mining sector military link"},
    {"name": "Falcon Bridge Commodities", "country": "Libya",
     "list": "OFAC", "program": "LIBYA-EO13726", "remarks": "Commodity smuggling"},
    {"name": "Northland Energy Consortium", "country": "Iran",
     "list": "OFAC", "program": "IRAN-TRA", "remarks": "Energy sector front"},
    {"name": "Silk Road Trading House", "country": "Afghanistan",
     "list": "UN", "program": "UN-1267", "remarks": "Narcotics trade front"},
    {"name": "Iron Gate Defense Systems", "country": "North Korea",
     "list": "UN", "program": "UN-1718", "remarks": "WMD procurement"},
]

SANCTIONS_ALIASES = {
    "Viktor Sergeyevich Petrov": ["V. Petrov", "Viktor Petrov"],
    "Hassan Ali Mahmoud": ["Hassan Mahmoud", "Abu Ali"],
    "Ahmad Reza Khalili": ["A.R. Khalili", "Ahmad Khalili"],
    "Dmitri Andreyevich Volkov": ["Dmitri Volkov", "D. Volkov"],
    "Faisal bin Mohammed Al-Rashid": ["Faisal Al-Rashid", "Faisal bin Mohammed"],
    "Chen Wei Dong": ["Chen Weidong", "Wei Dong Chen"],
    "Petrochem Holdings International": ["Petrochem Holdings", "PHI Group"],
    "Golden Dragon Trading Corp": ["Golden Dragon Trading", "GDTC"],
    "Crescent Star Shipping LLC": ["Crescent Star Shipping", "CSS LLC"],
    "Volkov Industrial Group": ["Volkov Industries", "VIG"],
    "Al-Rashid Financial Services": ["Al-Rashid Finance", "ARFS"],
}

HIGH_RISK_COUNTRIES = {
    "Iran": 5, "North Korea": 5, "Syria": 5, "Cuba": 5,
    "Myanmar": 4, "Russia": 4, "Libya": 4, "Somalia": 4,
    "Yemen": 4, "Sudan": 4, "Afghanistan": 4, "Iraq": 4,
    "South Sudan": 4, "Venezuela": 3, "Belarus": 3,
    "Democratic Republic of Congo": 3, "Lebanon": 3,
    "Nicaragua": 3, "Zimbabwe": 3, "Central African Republic": 3,
}

SAFE_COUNTRIES = [
    "United States", "United Kingdom", "Germany", "France", "Japan",
    "Canada", "Australia", "Switzerland", "Netherlands", "Sweden",
    "Norway", "Denmark", "Singapore", "New Zealand", "Ireland",
    "Belgium", "Austria", "Finland", "Luxembourg", "Portugal",
    "Spain", "Italy", "South Korea", "Taiwan", "Czech Republic",
]

ALL_COUNTRIES = SAFE_COUNTRIES + list(HIGH_RISK_COUNTRIES.keys())


def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS customers (
        customer_id TEXT PRIMARY KEY,
        full_name TEXT NOT NULL,
        date_of_birth TEXT,
        nationality TEXT,
        country_of_residence TEXT,
        customer_type TEXT NOT NULL,
        registration_date TEXT NOT NULL,
        screening_status TEXT NOT NULL DEFAULT 'pending'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS sanctions_entries (
        entry_id TEXT PRIMARY KEY,
        list_source TEXT NOT NULL,
        entity_name TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        date_of_birth TEXT,
        nationalities TEXT,
        country TEXT,
        listed_date TEXT,
        program TEXT,
        remarks TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS sanctions_aliases (
        alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id TEXT NOT NULL,
        alias_name TEXT NOT NULL,
        FOREIGN KEY (entry_id) REFERENCES sanctions_entries(entry_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS payment_intermediaries (
        intermediary_id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL,
        intermediary_name TEXT NOT NULL,
        intermediary_country TEXT NOT NULL,
        intermediary_type TEXT NOT NULL,
        transaction_amount REAL NOT NULL,
        transaction_currency TEXT NOT NULL,
        transaction_date TEXT NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS ubo_structures (
        ubo_record_id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL,
        entity_name TEXT,
        ownership_percentage REAL NOT NULL,
        beneficial_owner_name TEXT NOT NULL,
        beneficial_owner_nationality TEXT,
        beneficial_owner_dob TEXT,
        control_type TEXT NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
    )""")
    conn.commit()


def _generate_faker_individual():
    name = fake.name()
    dob = fake.date_of_birth(minimum_age=30, maximum_age=75).strftime("%Y-%m-%d")
    nationality = random.choice(ALL_COUNTRIES)
    return name, dob, nationality


def _generate_faker_entity():
    name = fake.company()
    country = random.choice(ALL_COUNTRIES)
    return name, country


def generate_sanctions_entries(conn, n):
    c = conn.cursor()
    entries = []
    entry_idx = 0

    for ind in SANCTIONED_INDIVIDUALS:
        if entry_idx >= n:
            break
        entry_id = f"SAN-{entry_idx:04d}"
        entries.append({
            "entry_id": entry_id, "list_source": ind["list"],
            "entity_name": ind["name"], "entity_type": "individual",
            "date_of_birth": ind["dob"], "nationalities": ind["nationality"],
            "country": ind["nationality"],
            "listed_date": fake.date_between("-10y", "-1y").strftime("%Y-%m-%d"),
            "program": ind["program"], "remarks": ind["remarks"],
        })
        if ind["name"] in SANCTIONS_ALIASES:
            for alias in SANCTIONS_ALIASES[ind["name"]]:
                c.execute("INSERT INTO sanctions_aliases (entry_id, alias_name) VALUES (?, ?)",
                          (entry_id, alias))
        entry_idx += 1

    for ent in SANCTIONED_ENTITIES:
        if entry_idx >= n:
            break
        entry_id = f"SAN-{entry_idx:04d}"
        entries.append({
            "entry_id": entry_id, "list_source": ent["list"],
            "entity_name": ent["name"], "entity_type": "entity",
            "date_of_birth": None, "nationalities": None,
            "country": ent["country"],
            "listed_date": fake.date_between("-10y", "-1y").strftime("%Y-%m-%d"),
            "program": ent["program"], "remarks": ent["remarks"],
        })
        if ent["name"] in SANCTIONS_ALIASES:
            for alias in SANCTIONS_ALIASES[ent["name"]]:
                c.execute("INSERT INTO sanctions_aliases (entry_id, alias_name) VALUES (?, ?)",
                          (entry_id, alias))
        entry_idx += 1

    lists = ["OFAC", "EU", "UN"]
    programs = {
        "OFAC": ["SDN", "SDGT", "IRAN-TRA", "UKRAINE-EO13661", "CUBA"],
        "EU": ["EU-TERROR", "EU-RUSSIA", "EU-SYRIA", "EU-IRAN", "EU-MYANMAR"],
        "UN": ["UN-1267", "UN-1718", "UN-1737", "UN-2231", "UN-751"],
    }
    while entry_idx < n:
        entry_id = f"SAN-{entry_idx:04d}"
        is_individual = random.random() < 0.6
        if is_individual:
            name, dob, nationality = _generate_faker_individual()
            lst = random.choice(lists)
            entries.append({
                "entry_id": entry_id, "list_source": lst,
                "entity_name": name, "entity_type": "individual",
                "date_of_birth": dob, "nationalities": nationality,
                "country": nationality,
                "listed_date": fake.date_between("-10y", "-1y").strftime("%Y-%m-%d"),
                "program": random.choice(programs[lst]),
                "remarks": fake.sentence(nb_words=6),
            })
        else:
            name, country = _generate_faker_entity()
            lst = random.choice(lists)
            entries.append({
                "entry_id": entry_id, "list_source": lst,
                "entity_name": name, "entity_type": "entity",
                "date_of_birth": None, "nationalities": None,
                "country": country,
                "listed_date": fake.date_between("-10y", "-1y").strftime("%Y-%m-%d"),
                "program": random.choice(programs[lst]),
                "remarks": fake.sentence(nb_words=6),
            })
        entry_idx += 1

    for e in entries:
        c.execute("""INSERT INTO sanctions_entries
                     (entry_id, list_source, entity_name, entity_type, date_of_birth,
                      nationalities, country, listed_date, program, remarks)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (e["entry_id"], e["list_source"], e["entity_name"], e["entity_type"],
                   e["date_of_birth"], e["nationalities"], e["country"],
                   e["listed_date"], e["program"], e["remarks"]))
    conn.commit()
    return pd.DataFrame(entries)


def _compute_match_plan(n, rng):
    indices = list(range(n))
    rng.shuffle(indices)
    n_direct = max(3, n // 8)
    n_alias = max(2, n // 10)
    n_ubo = max(2, n // 10)
    n_intermediary_entity = max(2, n // 12)
    n_intermediary_country = max(2, n // 10)
    n_pep = max(2, n // 12)
    ptr = 0
    direct = indices[ptr:ptr + n_direct]; ptr += n_direct
    alias = indices[ptr:ptr + n_alias]; ptr += n_alias
    ubo = indices[ptr:ptr + n_ubo]; ptr += n_ubo
    intm_entity = indices[ptr:ptr + n_intermediary_entity]; ptr += n_intermediary_entity
    intm_country = indices[ptr:ptr + n_intermediary_country]; ptr += n_intermediary_country
    pep = indices[ptr:ptr + n_pep]; ptr += n_pep
    return {
        "direct_name_match": sorted(direct),
        "alias_match": sorted(alias),
        "ubo_sanctions_match": sorted(ubo),
        "intermediary_entity_match": sorted(intm_entity),
        "intermediary_high_risk_country": sorted(intm_country),
        "pep_high_risk": sorted(pep),
    }


def generate_customers(conn, n, sanctions_df):
    c = conn.cursor()
    rng = random.Random(SEED + 1)
    plan = _compute_match_plan(n, random.Random(SEED + 100))
    individual_sanctions = sanctions_df[sanctions_df["entity_type"] == "individual"]

    customers = []
    for i in range(n):
        cid = f"CUST-{i:04d}"
        reg_date = fake.date_between("-1y", "today").strftime("%Y-%m-%d")

        if i in plan["direct_name_match"]:
            san_idx = i % len(individual_sanctions)
            san_name = individual_sanctions.iloc[san_idx]["entity_name"]
            parts = san_name.split()
            if len(parts) >= 3:
                name = f"{parts[0]} {parts[-1]}"
            else:
                name = san_name
            dob = fake.date_of_birth(minimum_age=25, maximum_age=70).strftime("%Y-%m-%d")
            nationality = rng.choice(ALL_COUNTRIES)
            ctype = "individual"
        else:
            is_corp = rng.random() < 0.3
            if is_corp:
                name = fake.company()
                dob = None
                nationality = rng.choice(ALL_COUNTRIES)
                ctype = "corporate"
            else:
                name = fake.name()
                dob = fake.date_of_birth(minimum_age=20, maximum_age=70).strftime("%Y-%m-%d")
                nationality = rng.choice(ALL_COUNTRIES)
                ctype = "individual"

        country_of_res = rng.choice(ALL_COUNTRIES)
        customers.append({
            "customer_id": cid, "full_name": name, "date_of_birth": dob,
            "nationality": nationality, "country_of_residence": country_of_res,
            "customer_type": ctype, "registration_date": reg_date,
            "screening_status": "pending",
        })

    for cu in customers:
        c.execute("""INSERT INTO customers
                     (customer_id, full_name, date_of_birth, nationality,
                      country_of_residence, customer_type, registration_date, screening_status)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                  (cu["customer_id"], cu["full_name"], cu["date_of_birth"],
                   cu["nationality"], cu["country_of_residence"], cu["customer_type"],
                   cu["registration_date"], cu["screening_status"]))
    conn.commit()
    return customers, plan


def generate_payment_intermediaries(conn, customers, plan, sanctions_df):
    c = conn.cursor()
    entity_sanctions = sanctions_df[sanctions_df["entity_type"] == "entity"]
    rng = random.Random(SEED + 2)
    intermediary_types = ["bank", "broker", "money_service", "correspondent_bank", "exchange_house"]
    currencies = ["USD", "EUR", "GBP", "CHF", "AED", "CNY", "JPY", "RUB", "IRR", "KRW"]
    bank_names = [
        "Deutsche International Bank", "Meridian Trust Corp", "Pacific Coast Banking Group",
        "Nordic Capital Partners", "Alpine Wealth Management", "Oceanic Finance Ltd",
        "Continental Credit Union", "Summit Banking Corp", "Horizon Financial Services",
        "Atlas Commercial Bank", "Sterling Reserve Bank", "Pinnacle Trading Finance",
        "Vanguard Settlement Services", "Gateway Exchange Corp", "Liberty Clearing House",
    ]
    records = []
    idx = 0
    for i, cust in enumerate(customers):
        n_intermediaries = rng.randint(1, 4)
        for j in range(n_intermediaries):
            iid = f"INTM-{idx:04d}"
            if i in plan["intermediary_entity_match"] and j == 0:
                san_idx = i % len(entity_sanctions)
                san_name = entity_sanctions.iloc[san_idx]["entity_name"]
                parts = san_name.split()
                if len(parts) > 2:
                    intm_name = " ".join(parts[:len(parts) - 1])
                else:
                    intm_name = san_name
                intm_country = rng.choice(SAFE_COUNTRIES)
            elif i in plan["intermediary_high_risk_country"] and j == 0:
                intm_name = rng.choice(bank_names)
                hr_countries = [ct for ct, t in HIGH_RISK_COUNTRIES.items() if t >= 4]
                intm_country = rng.choice(hr_countries)
            else:
                intm_name = rng.choice(bank_names)
                intm_country = rng.choice(SAFE_COUNTRIES)

            records.append({
                "intermediary_id": iid, "customer_id": cust["customer_id"],
                "intermediary_name": intm_name, "intermediary_country": intm_country,
                "intermediary_type": rng.choice(intermediary_types),
                "transaction_amount": round(rng.uniform(1000, 5000000), 2),
                "transaction_currency": rng.choice(currencies),
                "transaction_date": fake.date_between("-6m", "today").strftime("%Y-%m-%d"),
            })
            idx += 1

    for r in records:
        c.execute("""INSERT INTO payment_intermediaries
                     (intermediary_id, customer_id, intermediary_name, intermediary_country,
                      intermediary_type, transaction_amount, transaction_currency, transaction_date)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                  (r["intermediary_id"], r["customer_id"], r["intermediary_name"],
                   r["intermediary_country"], r["intermediary_type"],
                   r["transaction_amount"], r["transaction_currency"],
                   r["transaction_date"]))
    conn.commit()
    return records


def generate_ubo_structures(conn, customers, plan, sanctions_df):
    c = conn.cursor()
    individual_sanctions = sanctions_df[sanctions_df["entity_type"] == "individual"]
    rng = random.Random(SEED + 3)
    control_types = ["direct", "indirect"]
    records = []
    idx = 0

    for i, cust in enumerate(customers):
        if cust["customer_type"] == "corporate":
            n_ubos = rng.randint(1, 4)
        else:
            n_ubos = rng.randint(0, 2)

        for j in range(n_ubos):
            uid = f"UBO-{idx:04d}"
            if i in plan["ubo_sanctions_match"] and j == 0:
                san_idx = i % len(individual_sanctions)
                san_row = individual_sanctions.iloc[san_idx]
                bo_name = san_row["entity_name"]
                bo_nat = san_row["nationalities"]
                bo_dob = san_row["date_of_birth"]
            else:
                bo_name = fake.name()
                bo_nat = rng.choice(ALL_COUNTRIES)
                bo_dob = fake.date_of_birth(minimum_age=25, maximum_age=80).strftime("%Y-%m-%d")

            entity_name = fake.company() if cust["customer_type"] == "corporate" else cust["full_name"]
            pct = round(rng.uniform(5, 100 / max(1, n_ubos)), 2)

            records.append({
                "ubo_record_id": uid, "customer_id": cust["customer_id"],
                "entity_name": entity_name, "ownership_percentage": pct,
                "beneficial_owner_name": bo_name,
                "beneficial_owner_nationality": bo_nat,
                "beneficial_owner_dob": bo_dob,
                "control_type": rng.choice(control_types),
            })
            idx += 1

    for r in records:
        c.execute("""INSERT INTO ubo_structures
                     (ubo_record_id, customer_id, entity_name, ownership_percentage,
                      beneficial_owner_name, beneficial_owner_nationality,
                      beneficial_owner_dob, control_type)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                  (r["ubo_record_id"], r["customer_id"], r["entity_name"],
                   r["ownership_percentage"], r["beneficial_owner_name"],
                   r["beneficial_owner_nationality"], r["beneficial_owner_dob"],
                   r["control_type"]))
    conn.commit()
    return records


def _write_yaml_manually(data, filepath):
    """Write data as YAML without pyyaml dependency."""
    def _to_yaml(obj, indent=0):
        prefix = "  " * indent
        lines = []
        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    first = True
                    for k, v in item.items():
                        if first:
                            if isinstance(v, (dict, list)):
                                lines.append(f"{prefix}- {k}:")
                                lines.extend(_to_yaml(v, indent + 2))
                            else:
                                lines.append(f"{prefix}- {k}: {_scalar(v)}")
                            first = False
                        else:
                            if isinstance(v, (dict, list)):
                                lines.append(f"{prefix}  {k}:")
                                lines.extend(_to_yaml(v, indent + 2))
                            else:
                                lines.append(f"{prefix}  {k}: {_scalar(v)}")
                else:
                    lines.append(f"{prefix}- {_scalar(item)}")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    lines.append(f"{prefix}{k}:")
                    lines.extend(_to_yaml(v, indent + 1))
                else:
                    lines.append(f"{prefix}{k}: {_scalar(v)}")
        return lines

    def _scalar(v):
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        s = str(v)
        if any(ch in s for ch in ":{}[]&*?|>!%@`#,") or s.startswith("- ") or s == "":
            return f'"{s}"'
        return s

    with open(filepath, "w") as f:
        f.write("\n".join(_to_yaml(data)) + "\n")


def generate_workspace_files(workspace, conn, num_files, customers, plan,
                             intermediary_records, ubo_records, sanctions_df):
    os.makedirs(workspace, exist_ok=True)
    rng = random.Random(SEED + 10)
    individual_sanctions = sanctions_df[sanctions_df["entity_type"] == "individual"]

    # Fixed configuration files
    _write_screening_config(workspace)
    _write_compliance_policy(workspace)
    _write_country_risk_matrix(workspace)

    # Scalable data files
    n_json = max(1, num_files // 4)
    n_yaml = max(1, num_files // 4)
    n_txt = max(1, num_files // 8)
    n_csv = num_files - n_json - n_yaml - n_txt

    _generate_customer_json_files(workspace, customers, plan, individual_sanctions,
                                  n_json, rng)
    _generate_payment_csv_files(workspace, intermediary_records, n_csv, rng)
    _generate_ubo_yaml_files(workspace, ubo_records, customers, plan, n_yaml, rng)
    _generate_dd_notes_files(workspace, customers, n_txt, rng)


def _write_screening_config(workspace):
    config = {
        "name_match_threshold": 0.5,
        "ubo_ownership_screening_threshold": 10.0,
        "country_risk_tier_flag_threshold": 4,
        "risk_score_weights": {
            "direct_name_match": 40,
            "alias_match": 35,
            "ubo_sanctions_match": 30,
            "intermediary_sanctions_match": 25,
            "high_risk_country_intermediary": 15,
            "pep_high_risk_country": 20,
        },
        "priority_thresholds": {
            "critical": 70,
            "high": 45,
            "medium": 20,
        },
    }
    _write_yaml_manually(config, os.path.join(workspace, "screening_config.yaml"))


def _write_compliance_policy(workspace):
    policy = """COMPLIANCE SCREENING POLICY DOCUMENT
Effective Date: 2024-01-01
Version: 3.2

SECTION 1 - SCOPE AND APPLICABILITY

This policy governs the screening of all new customer registrations against applicable sanctions lists prior to account activation. Every customer in pending screening status must be processed through the full screening pipeline before a determination can be made.

SECTION 2 - NAME SCREENING PROCEDURES

Each customer's full registered name must be checked against OFAC, EU, and UN consolidated sanctions lists. In addition, all known aliases recorded in the customer registration documentation must also be searched individually against the same lists. A match is considered positive when the similarity score returned by the screening system meets or exceeds the threshold specified in the screening configuration. When a positive name match is found, the associated sanctions entry identifier must be recorded.

SECTION 3 - PAYMENT INTERMEDIARY REVIEW

All payment intermediaries associated with a customer must be examined. The intermediary name must be searched against sanctions lists using the same matching threshold. Additionally, the country in which each intermediary operates must be checked against the country risk matrix. If the intermediary's operating country has a risk tier at or above the tier threshold in the screening configuration, this constitutes a high-risk-country flag for the customer.

SECTION 4 - ULTIMATE BENEFICIAL OWNERSHIP SCREENING

Every beneficial owner listed in the UBO structure for a customer must be screened against sanctions lists, provided their ownership percentage meets or exceeds the ownership screening threshold from the configuration. Beneficial owners whose names produce a positive match must be recorded. Furthermore, if any beneficial owner is identified as a Politically Exposed Person operating in a country whose risk tier meets or exceeds the tier threshold, a separate PEP-related flag must be raised. PEP status information is recorded exclusively in the UBO declaration documentation files.

SECTION 5 - RISK SCORING

The total risk score for each customer is the sum of the weights corresponding to each applicable flag type, as defined in the screening configuration. A customer may trigger multiple flag types simultaneously and each applicable weight is added once regardless of how many individual matches of that type exist. The possible flag types are: direct_name_match, alias_match, ubo_sanctions_match, intermediary_sanctions_match, high_risk_country_intermediary, and pep_high_risk_country.

SECTION 6 - REVIEW PRIORITY CLASSIFICATION

Based on the computed risk score, each customer is assigned a review priority. If the risk score meets or exceeds the critical threshold, the priority is CRITICAL. If it meets or exceeds the high threshold but is below critical, the priority is HIGH. If it meets or exceeds the medium threshold but is below high, the priority is MEDIUM. If the score is above zero but below the medium threshold, the priority is LOW. Customers with a risk score of zero receive a priority of CLEAR.

SECTION 7 - DELIVERABLES

The screening officer must produce a single CSV report containing one row per screened customer. The report must include all customers regardless of outcome. Each row records the customer identifier, customer name, computed risk score, whether the customer is flagged, a semicolon-separated list of applicable flag-reason codes in alphabetical order, a semicolon-separated list of all matched sanctions entry identifiers in ascending order, and the assigned review priority. Customers in the report must be sorted by risk score in descending order, with ties broken by customer identifier in ascending order.
"""
    with open(os.path.join(workspace, "compliance_policy.txt"), "w") as f:
        f.write(policy)


def _write_country_risk_matrix(workspace):
    filepath = os.path.join(workspace, "country_risk_matrix.csv")
    all_risk = {}
    for c in SAFE_COUNTRIES:
        all_risk[c] = 1
    for c, tier in HIGH_RISK_COUNTRIES.items():
        all_risk[c] = tier
    tier2 = ["Brazil", "India", "Mexico", "Turkey", "South Africa",
             "Thailand", "Indonesia", "Philippines", "Colombia", "Egypt"]
    for c in tier2:
        all_risk[c] = 2

    with open(filepath, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country", "risk_tier", "sanctions_regime"])
        for country in sorted(all_risk.keys()):
            tier = all_risk[country]
            regime = "yes" if tier >= 4 else "no"
            w.writerow([country, tier, regime])


def _generate_customer_json_files(workspace, customers, plan, ind_sanctions,
                                  n_files, rng):
    chunk_size = math.ceil(len(customers) / n_files)
    for file_idx in range(n_files):
        start = file_idx * chunk_size
        end = min(start + chunk_size, len(customers))

        records = []
        for i_global in range(start, end):
            cust = customers[i_global]
            aliases = []
            if cust["customer_type"] == "individual":
                parts = cust["full_name"].split()
                if len(parts) >= 2:
                    aliases.append(f"{parts[0][0]}. {parts[-1]}")
            if cust["customer_type"] == "corporate":
                words = cust["full_name"].split()
                if len(words) >= 2:
                    aliases.append("".join(w[0] for w in words if w[0].isupper()))

            if i_global in plan["alias_match"]:
                san_idx = i_global % len(ind_sanctions)
                san_name = ind_sanctions.iloc[san_idx]["entity_name"]
                parts = san_name.split()
                if len(parts) >= 3:
                    alias = f"{parts[0]} {parts[-1]}"
                else:
                    alias = san_name
                aliases.append(alias)

            passport = None
            if cust["customer_type"] == "individual":
                passport = fake.bothify("??#######").upper()

            records.append({
                "customer_id": cust["customer_id"],
                "aliases": aliases,
                "passport_number": passport,
                "registered_address": fake.address().replace("\n", ", "),
                "business_description": fake.bs() if cust["customer_type"] == "corporate" else None,
                "source_of_funds": rng.choice([
                    "Employment income", "Business revenue", "Investment returns",
                    "Family wealth", "Real estate sales", "Trading profits",
                    "Government grants", "Consulting fees", "Inheritance",
                ]),
                "contact_email": fake.email(),
                "phone": fake.phone_number(),
            })

        filepath = os.path.join(workspace, f"customer_batch_{file_idx + 1:03d}.json")
        with open(filepath, "w") as f:
            json.dump(records, f, indent=2)


def _generate_payment_csv_files(workspace, intermediary_records, n_files, rng):
    chunk_size = math.ceil(len(intermediary_records) / n_files)
    purposes = [
        "Trade settlement", "Supplier payment", "Loan disbursement",
        "Investment transfer", "Service fees", "Equipment purchase",
        "Raw materials procurement", "Insurance premium", "Consulting payment",
        "Dividend distribution", "Freight charges", "License fees",
        "Capital contribution", "Lease payment", "Commission payment",
    ]
    for file_idx in range(n_files):
        start = file_idx * chunk_size
        end = min(start + chunk_size, len(intermediary_records))
        batch = intermediary_records[start:end]

        filepath = os.path.join(workspace, f"transactions_{file_idx + 1:03d}.csv")
        with open(filepath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["transaction_ref", "customer_id", "intermediary_id",
                         "purpose_of_payment", "originating_country",
                         "destination_country", "beneficiary_name",
                         "beneficiary_account", "value_date"])
            for rec in batch:
                w.writerow([
                    f"TXN-{fake.bothify('########')}",
                    rec["customer_id"], rec["intermediary_id"],
                    rng.choice(purposes), rng.choice(ALL_COUNTRIES),
                    rng.choice(ALL_COUNTRIES), fake.name(),
                    fake.iban(), rec["transaction_date"],
                ])


def _generate_ubo_yaml_files(workspace, ubo_records, customers, plan, n_files, rng):
    cust_ubos = {}
    for rec in ubo_records:
        cid = rec["customer_id"]
        if cid not in cust_ubos:
            cust_ubos[cid] = []
        cust_ubos[cid].append(rec)

    cust_idx_map = {c["customer_id"]: i for i, c in enumerate(customers)}
    cust_ids_with_ubo = sorted(cust_ubos.keys())
    chunk_size = max(1, math.ceil(len(cust_ids_with_ubo) / n_files))
    hr_countries_list = [c for c, t in HIGH_RISK_COUNTRIES.items() if t >= 4]

    for file_idx in range(n_files):
        start = file_idx * chunk_size
        end = min(start + chunk_size, len(cust_ids_with_ubo))
        batch_cids = cust_ids_with_ubo[start:end]

        declarations = []
        for cid in batch_cids:
            ubos = cust_ubos[cid]
            global_idx = cust_idx_map.get(cid, -1)

            ubo_details = []
            for u_idx, u_rec in enumerate(ubos):
                is_pep = False
                pep_country = None
                if global_idx in plan["pep_high_risk"] and u_idx == 0:
                    is_pep = True
                    pep_country = rng.choice(hr_countries_list)
                else:
                    is_pep = rng.random() < 0.05
                    if is_pep:
                        pep_country = u_rec["beneficial_owner_nationality"]

                chain = []
                n_layers = rng.randint(1, 3)
                for layer in range(n_layers):
                    chain.append({
                        "level": layer + 1,
                        "entity": fake.company() if layer < n_layers - 1 else u_rec["entity_name"],
                        "ownership_pct": round(rng.uniform(20, 100), 1),
                    })

                ubo_details.append({
                    "beneficial_owner": u_rec["beneficial_owner_name"],
                    "nationality": u_rec["beneficial_owner_nationality"],
                    "ownership_percentage": u_rec["ownership_percentage"],
                    "pep_status": is_pep,
                    "pep_country": pep_country if is_pep else None,
                    "source_of_wealth": rng.choice([
                        "Real estate investments", "Business ownership",
                        "Inherited wealth", "Technology ventures",
                        "Financial services", "Mining operations",
                        "Agricultural holdings", "Manufacturing",
                    ]),
                    "ownership_chain": chain,
                })

            declarations.append({
                "customer_id": cid,
                "declaration_date": fake.date_between("-1y", "today").strftime("%Y-%m-%d"),
                "beneficial_owners": ubo_details,
            })

        filepath = os.path.join(workspace, f"ubo_batch_{file_idx + 1:03d}.yaml")
        _write_yaml_manually(declarations, filepath)


def _generate_dd_notes_files(workspace, customers, n_files, rng):
    chunk_size = max(1, math.ceil(len(customers) / n_files))
    note_templates = [
        "Applicant submitted documentation on {date}. Initial review of corporate structure completed. "
        "No immediate red flags in submitted documents. Standard enhanced due diligence procedures apply.",
        "Cross-referenced applicant details with public records. Business registration confirmed in {country}. "
        "Ongoing monitoring recommended based on sector exposure.",
        "Reviewed source of funds declaration. Applicant claims primary revenue from {activity}. "
        "Documentation appears consistent with declared business activities.",
        "Checked adverse media databases. No significant negative coverage found as of {date}. "
        "Continue standard monitoring cycle.",
        "Applicant has connections to multiple jurisdictions. Enhanced geographic risk assessment "
        "may be warranted. Review payment patterns for unusual cross-border activity.",
    ]
    activities = [
        "import/export trading", "financial consulting", "real estate development",
        "technology services", "commodity trading", "manufacturing", "logistics",
    ]
    for file_idx in range(n_files):
        start = file_idx * chunk_size
        end = min(start + chunk_size, len(customers))
        batch = customers[start:end]

        ext = "txt" if file_idx % 2 == 0 else "md"
        filepath = os.path.join(workspace, f"dd_notes_{file_idx + 1:03d}.{ext}")
        with open(filepath, "w") as f:
            if ext == "md":
                f.write("# Due Diligence Notes\n\n")
            for cust in batch:
                if ext == "md":
                    f.write(f"## {cust['customer_id']} - {cust['full_name']}\n\n")
                else:
                    f.write(f"=== {cust['customer_id']} - {cust['full_name']} ===\n")
                note = rng.choice(note_templates).format(
                    date=fake.date_between("-3m", "today").strftime("%Y-%m-%d"),
                    country=rng.choice(ALL_COUNTRIES),
                    activity=rng.choice(activities),
                )
                f.write(note + "\n\n")


def main():
    parser = argparse.ArgumentParser(description="Generate sanctions screening task data")
    parser.add_argument("--db_path", required=True, help="Path to SQLite database file")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.db_path) if os.path.dirname(args.db_path) else ".", exist_ok=True)
    os.makedirs(args.workspace, exist_ok=True)

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]
    sanctions_df = generate_sanctions_entries(conn, n)
    customers, plan = generate_customers(conn, n, sanctions_df)
    intermediary_records = generate_payment_intermediaries(conn, customers, plan, sanctions_df)
    ubo_records = generate_ubo_structures(conn, customers, plan, sanctions_df)
    generate_workspace_files(args.workspace, conn, SCALE["num_workspace_files"],
                             customers, plan, intermediary_records, ubo_records, sanctions_df)

    conn.close()
    print(f"Data generation complete: {args.db_path}, {args.workspace}/")
    print(f"  Customers: {len(customers)}")
    print(f"  Sanctions entries: {len(sanctions_df)}")
    print(f"  Payment intermediaries: {len(intermediary_records)}")
    print(f"  UBO records: {len(ubo_records)}")
    print(f"  Workspace files: {SCALE['num_workspace_files']} scalable + 3 config")


if __name__ == "__main__":
    main()
