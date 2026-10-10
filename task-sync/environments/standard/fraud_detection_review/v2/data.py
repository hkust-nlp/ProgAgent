"""
Data generation for fraudulent ticket purchase detection task.
Generates database tables and workspace files for a fraud review queue scenario.
"""

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
from datetime import datetime, timedelta


SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 30,
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REVIEW_DATE = "2025-03-15"
DATE_RANGE_DAYS = 14  # transactions span 14 days ending on REVIEW_DATE
REVIEW_DATE_FRACTION = 0.30  # ~30% of transactions on review date

ACCOUNT_TIERS = ["standard", "premium", "vip"]
PAYMENT_METHODS = ["credit_card", "debit_card", "paypal", "apple_pay", "crypto"]
DEVICE_TYPES = ["desktop", "mobile", "tablet"]
BROWSERS = ["Chrome", "Firefox", "Safari", "Edge", "Opera"]
RESALE_PLATFORMS = ["StubHub", "Viagogo", "SeatGeek", "TicketSwap"]
EVENT_CATEGORIES = ["concert", "sports", "theater", "festival", "comedy"]

COUNTRIES = [
    "US", "UK", "CA", "DE", "FR", "AU", "JP", "BR", "IN", "RU",
    "MX", "AR", "ES", "IT", "NL",
]

CITIES_BY_COUNTRY = {
    "US": ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"],
    "UK": ["London", "Manchester", "Birmingham", "Leeds", "Glasgow"],
    "CA": ["Toronto", "Vancouver", "Montreal", "Calgary", "Ottawa"],
    "DE": ["Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne"],
    "FR": ["Paris", "Marseille", "Lyon", "Toulouse", "Nice"],
    "AU": ["Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide"],
    "JP": ["Tokyo", "Osaka", "Yokohama", "Nagoya", "Sapporo"],
    "BR": ["Sao Paulo", "Rio de Janeiro", "Brasilia", "Salvador", "Fortaleza"],
    "IN": ["Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai"],
    "RU": ["Moscow", "Saint Petersburg", "Novosibirsk", "Yekaterinburg", "Kazan"],
    "MX": ["Mexico City", "Guadalajara", "Monterrey", "Puebla", "Tijuana"],
    "AR": ["Buenos Aires", "Cordoba", "Rosario", "Mendoza", "Tucuman"],
    "ES": ["Madrid", "Barcelona", "Valencia", "Seville", "Bilbao"],
    "IT": ["Rome", "Milan", "Naples", "Turin", "Florence"],
    "NL": ["Amsterdam", "Rotterdam", "The Hague", "Utrecht", "Eindhoven"],
}

VENUE_NAMES = [
    "Grand Arena", "City Stadium", "Royal Theater", "Metro Center",
    "Park Amphitheater", "Civic Hall", "Star Dome", "Riverside Pavilion",
    "Heritage Auditorium", "Skyline Center", "Unity Arena", "Liberty Hall",
    "Ocean View Theater", "Summit Coliseum", "Central Garden Stage",
    "Diamond Ballroom", "Golden Gate Pavilion", "Emerald Hall",
    "Crescent Arena", "Phoenix Stadium",
]

VELOCITY_POLICY = {
    "standard": {"max_purchases_today": 2, "max_purchases_7d": 5},
    "premium":  {"max_purchases_today": 4, "max_purchases_7d": 10},
    "vip":      {"max_purchases_today": 6, "max_purchases_7d": 20},
}

FRAUD_SCORING_RULES = {
    "risk_factors": {
        "geo_mismatch":       {"weight": 20, "description": "Device geolocation country differs from customer verified residential country"},
        "velocity_violation": {"weight": 20, "description": "Purchase count exceeds account tier velocity limits"},
        "resale_detected":    {"weight": 20, "description": "Purchased ticket found listed on a resale platform"},
        "vpn_detected":       {"weight": 10, "description": "VPN or proxy detected on the purchasing device"},
        "price_anomaly":      {"weight": 15, "description": "Transaction amount exceeds the event maximum ticket price by the anomaly threshold"},
        "processor_flag":     {"weight": 15, "description": "Payment processor flagged the transaction as suspicious"},
    },
    "thresholds": {
        "high_risk": 50,
        "medium_risk": 25,
        "price_anomaly_pct": 20,
    },
    "risk_levels": {
        "HIGH":   {"min_score": 50, "action": "block_and_investigate"},
        "MEDIUM": {"min_score": 25, "action": "manual_review"},
        "LOW":    {"min_score": 10, "action": "monitor"},
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_id(prefix, idx, width=5):
    return f"{prefix}-{idx:0{width}d}"


def random_city(country, rng):
    cities = CITIES_BY_COUNTRY.get(country, ["Unknown"])
    return cities[rng.randint(0, len(cities))]


# ---------------------------------------------------------------------------
# Data Generation Functions
# ---------------------------------------------------------------------------

def generate_customers(n, fake, rng):
    """Generate customer records."""
    rows = []
    for i in range(1, n + 1):
        country = COUNTRIES[rng.randint(0, len(COUNTRIES))]
        tier = ACCOUNT_TIERS[rng.randint(0, len(ACCOUNT_TIERS))]
        reg_date = fake.date_between(start_date="-3y", end_date="-30d")
        rows.append({
            "customer_id": make_id("CUST", i),
            "name": fake.name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "registration_date": str(reg_date),
            "account_tier": tier,
            "country": country,
            "city": random_city(country, rng),
        })
    return pd.DataFrame(rows)


def generate_events(n, fake, rng):
    """Generate event records."""
    rows = []
    for i in range(1, n + 1):
        category = EVENT_CATEGORIES[rng.randint(0, len(EVENT_CATEGORIES))]
        country = COUNTRIES[rng.randint(0, len(COUNTRIES))]
        venue = VENUE_NAMES[rng.randint(0, len(VENUE_NAMES))]
        base_price = rng.choice([25, 50, 75, 100, 150, 200, 300])
        min_price = float(base_price)
        max_price = float(base_price * rng.uniform(1.5, 3.0))
        event_date = fake.date_between(start_date="+7d", end_date="+90d")
        max_per_customer = int(rng.choice([2, 4, 6, 8]))
        rows.append({
            "event_id": make_id("EVT", i),
            "event_name": f"{fake.catch_phrase()} {category.title()}",
            "venue": venue,
            "venue_city": random_city(country, rng),
            "venue_country": country,
            "event_date": str(event_date),
            "category": category,
            "min_ticket_price": round(min_price, 2),
            "max_ticket_price": round(max_price, 2),
            "max_tickets_per_customer": max_per_customer,
        })
    return pd.DataFrame(rows)


def generate_transactions(n, customers_df, events_df, rng):
    """
    Generate transaction records.
    ~30% on REVIEW_DATE, rest spread over prior days.
    Some 'burst' customers get clustered transactions for velocity violations.
    """
    review_dt = datetime.strptime(REVIEW_DATE, "%Y-%m-%d")
    start_dt = review_dt - timedelta(days=DATE_RANGE_DAYS - 1)

    n_review = max(15, int(n * REVIEW_DATE_FRACTION))
    n_prior = n - n_review

    customer_ids = customers_df["customer_id"].tolist()
    event_ids = events_df["event_id"].tolist()
    event_prices = dict(zip(events_df["event_id"], events_df["max_ticket_price"]))

    # Create burst customers (for velocity violations)
    n_burst = max(3, n // 20)  # ~5% of customers become burst
    burst_customers = [customer_ids[rng.randint(0, len(customer_ids))] for _ in range(n_burst)]
    burst_customers = list(set(burst_customers))[:n_burst]

    rows = []
    txn_idx = 1

    # Generate prior-period transactions
    for i in range(n_prior):
        cid = customer_ids[rng.randint(0, len(customer_ids))]
        eid = event_ids[rng.randint(0, len(event_ids))]
        day_offset = rng.randint(1, DATE_RANGE_DAYS)
        ts = review_dt - timedelta(days=day_offset,
                                    hours=rng.randint(0, 24),
                                    minutes=rng.randint(0, 60))
        max_p = event_prices[eid]
        amount = round(float(rng.uniform(max_p * 0.5, max_p * 1.0)), 2)
        qty = int(rng.choice([1, 1, 1, 2, 2, 3]))
        rows.append({
            "transaction_id": make_id("TXN", txn_idx),
            "customer_id": cid,
            "event_id": eid,
            "ticket_id": make_id("TKT", txn_idx),
            "purchase_timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "purchase_date": ts.strftime("%Y-%m-%d"),
            "amount": amount,
            "payment_method": PAYMENT_METHODS[rng.randint(0, len(PAYMENT_METHODS))],
            "quantity": qty,
            "status": "completed",
        })
        txn_idx += 1

    # Inject burst-customer transactions in the 7-day window (but before review date)
    for bc in burst_customers:
        n_burst_txns = rng.randint(2, 5)
        for _ in range(n_burst_txns):
            eid = event_ids[rng.randint(0, len(event_ids))]
            day_offset = rng.randint(1, 7)  # within 7d window, before review date
            ts = review_dt - timedelta(days=day_offset,
                                        hours=rng.randint(0, 24),
                                        minutes=rng.randint(0, 60))
            max_p = event_prices[eid]
            amount = round(float(rng.uniform(max_p * 0.5, max_p * 1.0)), 2)
            rows.append({
                "transaction_id": make_id("TXN", txn_idx),
                "customer_id": bc,
                "event_id": eid,
                "ticket_id": make_id("TKT", txn_idx),
                "purchase_timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "purchase_date": ts.strftime("%Y-%m-%d"),
                "amount": amount,
                "payment_method": PAYMENT_METHODS[rng.randint(0, len(PAYMENT_METHODS))],
                "quantity": int(rng.choice([1, 2, 3])),
                "status": "completed",
            })
            txn_idx += 1

    # Generate review-date transactions
    review_txn_start = txn_idx
    for i in range(n_review):
        # Mix burst and regular customers
        if i < len(burst_customers):
            cid = burst_customers[i]
        else:
            cid = customer_ids[rng.randint(0, len(customer_ids))]
        eid = event_ids[rng.randint(0, len(event_ids))]
        ts = review_dt + timedelta(hours=rng.randint(0, 23),
                                   minutes=rng.randint(0, 59),
                                   seconds=rng.randint(0, 59))
        max_p = event_prices[eid]
        # Some will have price anomalies (decided later, but generate normal amounts here)
        amount = round(float(rng.uniform(max_p * 0.5, max_p * 1.0)), 2)
        qty = int(rng.choice([1, 1, 2, 2, 3, 4]))
        rows.append({
            "transaction_id": make_id("TXN", txn_idx),
            "customer_id": cid,
            "event_id": eid,
            "ticket_id": make_id("TKT", txn_idx),
            "purchase_timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "purchase_date": ts.strftime("%Y-%m-%d"),
            "amount": amount,
            "payment_method": PAYMENT_METHODS[rng.randint(0, len(PAYMENT_METHODS))],
            "quantity": qty,
            "status": "completed",
        })
        txn_idx += 1

    df = pd.DataFrame(rows)
    return df, review_txn_start


def compute_velocity(customer_id, review_date_str, all_txns_df):
    """Compute purchase velocity for a customer."""
    review_dt = datetime.strptime(review_date_str, "%Y-%m-%d")
    window_7d_start = (review_dt - timedelta(days=6)).strftime("%Y-%m-%d")

    cust_txns = all_txns_df[all_txns_df["customer_id"] == customer_id]
    today_count = len(cust_txns[cust_txns["purchase_date"] == review_date_str])
    week_count = len(cust_txns[cust_txns["purchase_date"] >= window_7d_start])
    return today_count, week_count


def assign_fraud_flags(all_txns_df, review_txn_start_idx, customers_df, events_df, rng):
    """
    Assign fraud flags for review-date transactions.
    Returns a dict mapping transaction_id -> set of fraud flags.
    Also modifies transactions for price_anomaly (adjusts amount).
    """
    review_txns = all_txns_df[all_txns_df["purchase_date"] == REVIEW_DATE].copy()
    customer_tiers = dict(zip(customers_df["customer_id"], customers_df["account_tier"]))
    event_max_prices = dict(zip(events_df["event_id"], events_df["max_ticket_price"]))
    customer_countries = dict(zip(customers_df["customer_id"], customers_df["country"]))

    fraud_flags = {}
    price_anomaly_txns = {}  # transaction_id -> new_amount

    for _, row in review_txns.iterrows():
        tid = row["transaction_id"]
        cid = row["customer_id"]
        eid = row["event_id"]
        flags = set()

        # Geo mismatch: ~20% chance
        if rng.random() < 0.22:
            flags.add("geo_mismatch")

        # VPN detected: ~20% chance
        if rng.random() < 0.22:
            flags.add("vpn_detected")

        # Resale detected: ~15% chance
        if rng.random() < 0.18:
            flags.add("resale_detected")

        # Price anomaly: ~15% chance
        if rng.random() < 0.18:
            flags.add("price_anomaly")
            max_p = event_max_prices.get(eid, 100.0)
            threshold_pct = FRAUD_SCORING_RULES["thresholds"]["price_anomaly_pct"]
            anomaly_amount = round(max_p * (1 + threshold_pct / 100) * rng.uniform(1.01, 1.5), 2)
            price_anomaly_txns[tid] = anomaly_amount

        # Processor flag: ~15% chance
        if rng.random() < 0.18:
            flags.add("processor_flag")

        # Velocity violation: computed from actual data
        tier = customer_tiers.get(cid, "standard")
        limits = VELOCITY_POLICY[tier]
        today_count, week_count = compute_velocity(cid, REVIEW_DATE, all_txns_df)
        if today_count > limits["max_purchases_today"] or week_count > limits["max_purchases_7d"]:
            flags.add("velocity_violation")

        fraud_flags[tid] = flags

    # Apply price anomaly amounts back to the dataframe
    for tid, new_amount in price_anomaly_txns.items():
        all_txns_df.loc[all_txns_df["transaction_id"] == tid, "amount"] = new_amount

    return fraud_flags


def generate_devices(all_txns_df, customers_df, fraud_flags, rng):
    """Generate device session records. One per transaction."""
    customer_countries = dict(zip(customers_df["customer_id"], customers_df["country"]))
    rows = []

    for i, (_, txn) in enumerate(all_txns_df.iterrows()):
        tid = txn["transaction_id"]
        cid = txn["customer_id"]
        cust_country = customer_countries.get(cid, "US")
        flags = fraud_flags.get(tid, set())

        # Determine device country
        if "geo_mismatch" in flags:
            # Pick a different country
            other_countries = [c for c in COUNTRIES if c != cust_country]
            dev_country = other_countries[rng.randint(0, len(other_countries))]
        else:
            dev_country = cust_country

        dev_city = random_city(dev_country, rng)

        # VPN flag
        vpn = "vpn_detected" in flags

        # For non-review-date transactions, small chance of VPN (background noise)
        if tid not in fraud_flags and rng.random() < 0.05:
            vpn = True

        device_type = DEVICE_TYPES[rng.randint(0, len(DEVICE_TYPES))]
        browser = BROWSERS[rng.randint(0, len(BROWSERS))]

        # Generate plausible lat/lon for the device country/city
        lat = round(rng.uniform(-60, 70), 6)
        lon = round(rng.uniform(-180, 180), 6)

        # Generate IP address
        ip = f"{rng.randint(1, 255)}.{rng.randint(0, 256)}.{rng.randint(0, 256)}.{rng.randint(1, 255)}"

        rows.append({
            "device_id": make_id("DEV", i + 1),
            "transaction_id": tid,
            "ip_address": ip,
            "device_type": device_type,
            "browser": browser,
            "os": rng.choice(["Windows 11", "macOS 14", "iOS 17", "Android 14", "Linux"]),
            "latitude": lat,
            "longitude": lon,
            "city": dev_city,
            "country": dev_country,
            "vpn_detected": int(vpn),
        })

    return pd.DataFrame(rows)


def generate_resale_listings(n_min, all_txns_df, fraud_flags, rng):
    """
    Generate resale platform listings.
    Ensure resale_detected flagged tickets appear, plus background noise.
    """
    rows = []
    listing_idx = 1

    # First, create listings for resale_detected tickets
    resale_txn_ids = [tid for tid, flags in fraud_flags.items() if "resale_detected" in flags]
    for tid in resale_txn_ids:
        txn_row = all_txns_df[all_txns_df["transaction_id"] == tid].iloc[0]
        ticket_id = txn_row["ticket_id"]
        amount = txn_row["amount"]
        purchase_ts = datetime.strptime(txn_row["purchase_timestamp"], "%Y-%m-%d %H:%M:%S")
        listing_date = purchase_ts + timedelta(hours=rng.randint(1, 48))
        asking_price = round(amount * rng.uniform(1.5, 4.0), 2)
        platform = RESALE_PLATFORMS[rng.randint(0, len(RESALE_PLATFORMS))]
        rows.append({
            "listing_id": make_id("LST", listing_idx),
            "ticket_id": ticket_id,
            "original_transaction_id": tid,
            "platform": platform,
            "listing_date": listing_date.strftime("%Y-%m-%d %H:%M:%S"),
            "asking_price": asking_price,
            "seller_handle": f"seller_{rng.randint(1000, 9999)}",
            "status": "active",
        })
        listing_idx += 1

    # Fill remaining with background noise listings (random tickets)
    while len(rows) < n_min:
        # Use ticket IDs from non-flagged transactions or generate synthetic ones
        if rng.random() < 0.3 and len(all_txns_df) > 0:
            # Reference a real but non-flagged ticket
            non_flagged = all_txns_df[~all_txns_df["transaction_id"].isin(resale_txn_ids)]
            if len(non_flagged) > 0:
                idx = rng.randint(0, len(non_flagged))
                ref_txn = non_flagged.iloc[idx]
                ticket_id = ref_txn["ticket_id"]
                orig_tid = ref_txn["transaction_id"]
                base_price = ref_txn["amount"]
            else:
                ticket_id = make_id("TKT", 90000 + listing_idx)
                orig_tid = ""
                base_price = rng.uniform(50, 500)
        else:
            ticket_id = make_id("TKT", 90000 + listing_idx)
            orig_tid = ""
            base_price = rng.uniform(50, 500)

        listing_date = datetime.strptime(REVIEW_DATE, "%Y-%m-%d") - timedelta(days=rng.randint(0, 30))
        asking_price = round(base_price * rng.uniform(1.2, 3.5), 2)
        platform = RESALE_PLATFORMS[rng.randint(0, len(RESALE_PLATFORMS))]

        rows.append({
            "listing_id": make_id("LST", listing_idx),
            "ticket_id": ticket_id,
            "original_transaction_id": orig_tid,
            "platform": platform,
            "listing_date": listing_date.strftime("%Y-%m-%d %H:%M:%S"),
            "asking_price": asking_price,
            "seller_handle": f"seller_{rng.randint(1000, 9999)}",
            "status": rng.choice(["active", "sold", "expired"]),
        })
        listing_idx += 1

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def write_database(db_path, customers_df, events_df, transactions_df, devices_df, resale_df):
    """Write all data to SQLite database."""
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE customers (
            customer_id TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            phone TEXT,
            registration_date TEXT,
            account_tier TEXT,
            country TEXT,
            city TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            event_name TEXT,
            venue TEXT,
            venue_city TEXT,
            venue_country TEXT,
            event_date TEXT,
            category TEXT,
            min_ticket_price REAL,
            max_ticket_price REAL,
            max_tickets_per_customer INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE transactions (
            transaction_id TEXT PRIMARY KEY,
            customer_id TEXT,
            event_id TEXT,
            ticket_id TEXT,
            purchase_timestamp TEXT,
            purchase_date TEXT,
            amount REAL,
            payment_method TEXT,
            quantity INTEGER,
            status TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
            FOREIGN KEY (event_id) REFERENCES events(event_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE devices (
            device_id TEXT PRIMARY KEY,
            transaction_id TEXT,
            ip_address TEXT,
            device_type TEXT,
            browser TEXT,
            os TEXT,
            latitude REAL,
            longitude REAL,
            city TEXT,
            country TEXT,
            vpn_detected INTEGER,
            FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE resale_listings (
            listing_id TEXT PRIMARY KEY,
            ticket_id TEXT,
            original_transaction_id TEXT,
            platform TEXT,
            listing_date TEXT,
            asking_price REAL,
            seller_handle TEXT,
            status TEXT
        )
    """)

    customers_df.to_sql("customers", conn, if_exists="append", index=False)
    events_df.to_sql("events", conn, if_exists="append", index=False)
    transactions_df.to_sql("transactions", conn, if_exists="append", index=False)
    devices_df.to_sql("devices", conn, if_exists="append", index=False)
    resale_df.to_sql("resale_listings", conn, if_exists="append", index=False)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Workspace Files
# ---------------------------------------------------------------------------

def write_workspace_files(workspace, n_files, all_txns_df, events_df, customers_df, fraud_flags):
    """Write scalable workspace data files."""

    # Distribute file counts across types
    n_batch = max(1, n_files * 4 // 10)
    n_event = max(1, n_files * 3 // 10)
    n_customer = n_files - n_batch - n_event
    if n_customer < 1:
        n_customer = 1
        n_batch = n_files - n_event - n_customer

    # ---- Transaction batch CSV files (processor flags) ----
    all_txn_ids = all_txns_df["transaction_id"].tolist()
    processor_flags = {}
    rng_proc = np.random.RandomState(4242)
    for tid in all_txn_ids:
        if tid in fraud_flags and "processor_flag" in fraud_flags[tid]:
            processor_flags[tid] = 1
        else:
            # Small background noise rate for non-review transactions
            processor_flags[tid] = 1 if rng_proc.random() < 0.03 else 0

    # Split transactions across batch files
    chunks = np.array_split(all_txn_ids, n_batch)
    for file_idx, chunk in enumerate(chunks, 1):
        filepath = os.path.join(workspace, f"batch_{file_idx:03d}.csv")
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["transaction_id", "processor_risk_flag", "processor_code", "processing_timestamp"])
            for tid in chunk:
                flag = processor_flags.get(tid, 0)
                txn_row = all_txns_df[all_txns_df["transaction_id"] == tid].iloc[0]
                code = "FLAGGED" if flag else "APPROVED"
                writer.writerow([tid, flag, code, txn_row["purchase_timestamp"]])

    # ---- Event pricing JSON files ----
    event_records = events_df.to_dict("records")
    event_chunks = np.array_split(range(len(event_records)), n_event)
    for file_idx, indices in enumerate(event_chunks, 1):
        filepath = os.path.join(workspace, f"event_pricing_{file_idx:03d}.json")
        chunk_data = []
        for idx in indices:
            rec = event_records[idx]
            chunk_data.append({
                "event_id": rec["event_id"],
                "event_name": rec["event_name"],
                "venue": rec["venue"],
                "category": rec["category"],
                "min_ticket_price": rec["min_ticket_price"],
                "max_ticket_price": rec["max_ticket_price"],
                "max_tickets_per_customer": rec["max_tickets_per_customer"],
            })
        with open(filepath, "w") as f:
            json.dump(chunk_data, f, indent=2)

    # ---- Customer verified address TXT files (tab-separated) ----
    cust_records = customers_df.to_dict("records")
    cust_chunks = np.array_split(range(len(cust_records)), n_customer)
    verification_methods = ["id_document", "utility_bill", "bank_statement", "passport", "drivers_license"]
    rng_ver = np.random.RandomState(4243)
    for file_idx, indices in enumerate(cust_chunks, 1):
        filepath = os.path.join(workspace, f"customer_verified_{file_idx:03d}.txt")
        with open(filepath, "w") as f:
            f.write("customer_id\tverified_country\tverification_date\tverification_method\n")
            for idx in indices:
                rec = cust_records[idx]
                ver_date = (datetime.strptime(rec["registration_date"], "%Y-%m-%d") +
                            timedelta(days=rng_ver.randint(1, 30))).strftime("%Y-%m-%d")
                method = verification_methods[rng_ver.randint(0, len(verification_methods))]
                f.write(f"{rec['customer_id']}\t{rec['country']}\t{ver_date}\t{method}\n")


def write_config_files(workspace):
    """Write fixed configuration files (not scaled)."""

    # Fraud scoring rules (YAML)
    filepath = os.path.join(workspace, "fraud_scoring_rules.yaml")
    with open(filepath, "w") as f:
        yaml.dump(FRAUD_SCORING_RULES, f, default_flow_style=False, sort_keys=False)

    # Velocity policy (CSV)
    filepath = os.path.join(workspace, "velocity_policy.csv")
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["tier", "max_purchases_today", "max_purchases_7d"])
        for tier in ["standard", "premium", "vip"]:
            limits = VELOCITY_POLICY[tier]
            writer.writerow([tier, limits["max_purchases_today"], limits["max_purchases_7d"]])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate fraud detection task data")
    parser.add_argument("--db_path", required=True, help="Path to output SQLite database")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    args = parser.parse_args()

    # Set all seeds
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)
    rng = np.random.RandomState(42)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    os.makedirs(args.workspace, exist_ok=True)

    # Generate base entities
    customers_df = generate_customers(n_rows, fake, rng)
    events_df = generate_events(n_rows, fake, rng)

    # Generate transactions (with burst customers for velocity)
    all_txns_df, review_txn_start = generate_transactions(n_rows, customers_df, events_df, rng)

    # Assign fraud flags for review-date transactions
    fraud_flags = assign_fraud_flags(all_txns_df, review_txn_start, customers_df, events_df, rng)

    # Generate devices consistent with fraud flags
    devices_df = generate_devices(all_txns_df, customers_df, fraud_flags, rng)

    # Generate resale listings
    resale_df = generate_resale_listings(n_rows, all_txns_df, fraud_flags, rng)

    # Write database
    write_database(args.db_path, customers_df, events_df, all_txns_df, devices_df, resale_df)

    # Write workspace files
    write_workspace_files(args.workspace, n_files, all_txns_df, events_df, customers_df, fraud_flags)
    write_config_files(args.workspace)

    # Print summary
    review_txns = all_txns_df[all_txns_df["purchase_date"] == REVIEW_DATE]
    flagged = {tid for tid, flags in fraud_flags.items() if len(flags) > 0}
    print(f"Generated {len(all_txns_df)} transactions ({len(review_txns)} on review date {REVIEW_DATE})")
    print(f"Flagged transactions: {len(flagged)} with at least one risk factor")
    print(f"Database: {args.db_path}")
    print(f"Workspace: {args.workspace} ({n_files} data files + 2 config files)")


if __name__ == "__main__":
    main()
