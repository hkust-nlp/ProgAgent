import argparse
import os
import sqlite3
import json
import csv
import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 18,
}


def main(db_path, workspace):
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()

    os.makedirs(workspace, exist_ok=True)

    n = SCALE["rows_per_table"]
    nf = SCALE["num_workspace_files"]

    # ── High-risk state lists (used in regional_risk_map) ──
    high_risk_states = ["FL", "NV", "CA", "TX", "NY"]
    medium_risk_states = ["IL", "GA", "AZ", "NJ", "OH"]

    suspicious_email_domains = [
        "tempmail.com", "throwaway.net", "fakeinbox.org", "mailnator.com",
    ]
    suspicious_referral_prefixes = ["FRD", "XXX", "TST"]

    # ── 1. Generate applications ──
    apps = []
    for i in range(n):
        state = fake.state_abbr()
        income = max(18000, int(np.random.lognormal(mean=10.8, sigma=0.6)))
        limit_choices = [3000, 5000, 7500, 10000, 15000, 20000, 25000, 30000]
        requested_limit = int(np.random.choice(limit_choices))
        emp = np.random.choice(
            ["employed", "self-employed", "unemployed", "retired"],
            p=[0.60, 0.20, 0.10, 0.10],
        )
        apps.append({
            "app_id": f"APP-{i+1:04d}",
            "applicant_name": fake.name(),
            "ssn_last4": fake.numerify("####"),
            "email": fake.email(),
            "phone": fake.numerify("###-###-####"),
            "verified_annual_income": income,
            "employment_status": emp,
            "employer_name": fake.company() if emp in ("employed", "self-employed") else "N/A",
            "address": fake.street_address(),
            "city": fake.city(),
            "state": state,
            "zip_code": fake.zipcode(),
            "requested_credit_limit": requested_limit,
            "applied_date": fake.date_between("-60d", "today").isoformat(),
        })

    # ── 2. Assign workspace-only metadata ──
    # Income discrepancy
    discrepancy_mask = np.random.random(n) < 0.18
    self_reported = []
    for i in range(n):
        if discrepancy_mask[i]:
            factor = 1.0 + np.random.uniform(0.35, 0.80)
        else:
            factor = 1.0 + np.random.uniform(-0.05, 0.10)
        self_reported.append(int(apps[i]["verified_annual_income"] * factor))

    doc_statuses = list(np.random.choice(
        ["verified", "pending", "failed"], size=n, p=[0.70, 0.15, 0.15],
    ))
    channels = list(np.random.choice(
        ["online", "mobile", "in-branch", "phone"], size=n, p=[0.40, 0.30, 0.20, 0.10],
    ))
    referral_codes = []
    for i in range(n):
        r = np.random.random()
        if r < 0.10:
            prefix = np.random.choice(suspicious_referral_prefixes)
            referral_codes.append(f"{prefix}-{fake.numerify('####')}")
        elif r < 0.55:
            referral_codes.append(f"REF-{fake.numerify('####')}")
        else:
            referral_codes.append("")

    # ── 3. Credit bureau data ──
    credit_data = []
    for i in range(n):
        if np.random.random() < 0.16:
            score = int(np.random.uniform(320, 575))
        else:
            score = int(np.clip(np.random.normal(690, 70), 300, 850))
        bankruptcy = int(np.random.random() < 0.09)
        delinq = max(0, int(np.random.exponential(0.5)))
        credit_data.append({
            "app_id": apps[i]["app_id"],
            "credit_score": score,
            "open_trade_lines": max(1, int(np.random.normal(8, 4))),
            "delinquent_trade_lines": delinq,
            "total_delinquency_amount": delinq * int(np.random.uniform(500, 5000)) if delinq else 0,
            "credit_history_years": max(0, int(np.random.normal(10, 5))),
            "total_outstanding_debt": max(0, int(np.random.lognormal(9, 1.5))),
            "bankruptcy_flag": bankruptcy,
            "hard_inquiries_6mo": max(0, int(np.random.exponential(2))),
        })

    # ── 4. Device fingerprints (with shared hashes for velocity) ──
    velocity_count = max(6, int(n * 0.14))
    velocity_indices = sorted(np.random.choice(n, size=velocity_count, replace=False).tolist())
    device_hash_map = {}
    shared_ip_map = {}
    idx = 0
    while idx < len(velocity_indices):
        grp_size = min(np.random.choice([2, 3]), len(velocity_indices) - idx)
        if grp_size < 2:
            break
        dh = fake.sha256()[:16]
        ip = fake.ipv4()
        for j in range(grp_size):
            device_hash_map[velocity_indices[idx + j]] = dh
            shared_ip_map[velocity_indices[idx + j]] = ip
        idx += grp_size

    device_data = []
    for i in range(n):
        vpn = int(np.random.random() < 0.13)
        proxy = int(np.random.random() < 0.09)
        ip_country = "US" if np.random.random() < 0.85 else str(np.random.choice(["RU", "NG", "CN", "BR", "IN"]))
        device_data.append({
            "app_id": apps[i]["app_id"],
            "device_hash": device_hash_map.get(i, fake.sha256()[:16]),
            "ip_address": shared_ip_map.get(i, fake.ipv4()),
            "ip_country": ip_country,
            "vpn_detected": vpn,
            "proxy_detected": proxy,
            "browser": str(np.random.choice(["Chrome", "Firefox", "Safari", "Edge"])),
            "os_name": str(np.random.choice(["Windows", "macOS", "Linux", "iOS", "Android"])),
            "session_duration_sec": max(10, int(np.random.normal(300, 150))),
        })

    # ── 5. Inject suspicious email domains into some apps ──
    sus_email_count = max(4, int(n * 0.10))
    sus_email_indices = sorted(np.random.choice(n, size=sus_email_count, replace=False).tolist())
    for idx in sus_email_indices:
        domain = str(np.random.choice(suspicious_email_domains))
        local = apps[idx]["email"].split("@")[0]
        apps[idx]["email"] = f"{local}@{domain}"

    # ── 6. Known fraudsters (some match app data) ──
    n_fraudsters = max(20, n // 2)
    fraudsters = []
    match_count = max(4, int(n * 0.10))
    match_indices = sorted(np.random.choice(n, size=match_count, replace=False).tolist())
    for mi in match_indices:
        mtype = str(np.random.choice(["ssn_last4", "email_domain", "phone_prefix"]))
        if mtype == "ssn_last4":
            mval = apps[mi]["ssn_last4"]
        elif mtype == "email_domain":
            mval = apps[mi]["email"].split("@")[1]
        else:
            mval = apps[mi]["phone"][:3]
        fraudsters.append({
            "fraudster_id": f"FRD-{len(fraudsters)+1:04d}",
            "match_field": mtype,
            "match_value": mval,
            "fraud_type": str(np.random.choice([
                "identity_theft", "synthetic_identity", "application_fraud", "account_takeover",
            ])),
            "severity": str(np.random.choice(["high", "medium", "low"], p=[0.3, 0.4, 0.3])),
        })
    while len(fraudsters) < n_fraudsters:
        mtype = str(np.random.choice(["ssn_last4", "email_domain", "phone_prefix"]))
        if mtype == "ssn_last4":
            mval = fake.numerify("####")
        elif mtype == "email_domain":
            mval = fake.domain_name()
        else:
            mval = fake.numerify("###")
        fraudsters.append({
            "fraudster_id": f"FRD-{len(fraudsters)+1:04d}",
            "match_field": mtype,
            "match_value": mval,
            "fraud_type": str(np.random.choice([
                "identity_theft", "synthetic_identity", "application_fraud", "account_takeover",
            ])),
            "severity": str(np.random.choice(["high", "medium", "low"], p=[0.3, 0.4, 0.3])),
        })

    # ══════════════════════════════════════════════════════════
    #  Write database
    # ══════════════════════════════════════════════════════════
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE applications (
        app_id TEXT PRIMARY KEY,
        applicant_name TEXT,
        ssn_last4 TEXT,
        email TEXT,
        phone TEXT,
        verified_annual_income INTEGER,
        employment_status TEXT,
        employer_name TEXT,
        address TEXT,
        city TEXT,
        state TEXT,
        zip_code TEXT,
        requested_credit_limit INTEGER,
        applied_date TEXT
    )""")
    for a in apps:
        c.execute(
            "INSERT INTO applications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (a["app_id"], a["applicant_name"], a["ssn_last4"], a["email"],
             a["phone"], a["verified_annual_income"], a["employment_status"],
             a["employer_name"], a["address"], a["city"], a["state"],
             a["zip_code"], a["requested_credit_limit"], a["applied_date"]),
        )

    c.execute("""CREATE TABLE credit_bureau (
        app_id TEXT PRIMARY KEY,
        credit_score INTEGER,
        open_trade_lines INTEGER,
        delinquent_trade_lines INTEGER,
        total_delinquency_amount INTEGER,
        credit_history_years INTEGER,
        total_outstanding_debt INTEGER,
        bankruptcy_flag INTEGER,
        hard_inquiries_6mo INTEGER,
        FOREIGN KEY (app_id) REFERENCES applications(app_id)
    )""")
    for cd in credit_data:
        c.execute(
            "INSERT INTO credit_bureau VALUES (?,?,?,?,?,?,?,?,?)",
            tuple(cd.values()),
        )

    c.execute("""CREATE TABLE device_fingerprints (
        app_id TEXT PRIMARY KEY,
        device_hash TEXT,
        ip_address TEXT,
        ip_country TEXT,
        vpn_detected INTEGER,
        proxy_detected INTEGER,
        browser TEXT,
        os_name TEXT,
        session_duration_sec INTEGER,
        FOREIGN KEY (app_id) REFERENCES applications(app_id)
    )""")
    for dd in device_data:
        c.execute(
            "INSERT INTO device_fingerprints VALUES (?,?,?,?,?,?,?,?,?)",
            tuple(dd.values()),
        )

    c.execute("""CREATE TABLE known_fraudsters (
        fraudster_id TEXT PRIMARY KEY,
        match_field TEXT,
        match_value TEXT,
        fraud_type TEXT,
        severity TEXT
    )""")
    for f in fraudsters:
        c.execute(
            "INSERT INTO known_fraudsters VALUES (?,?,?,?,?)",
            tuple(f.values()),
        )

    conn.commit()
    conn.close()

    # ══════════════════════════════════════════════════════════
    #  Write workspace files
    # ══════════════════════════════════════════════════════════

    # ── Scaling files: application batch CSVs ──
    batch_size = n // nf
    remainder = n % nf
    start = 0
    for bi in range(nf):
        end = start + batch_size + (1 if bi < remainder else 0)
        path = os.path.join(workspace, f"application_batch_{bi+1:03d}.csv")
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([
                "app_id", "submission_channel", "referral_code",
                "self_reported_annual_income", "document_status", "applied_timestamp",
            ])
            for i in range(start, end):
                w.writerow([
                    apps[i]["app_id"],
                    channels[i],
                    referral_codes[i],
                    self_reported[i],
                    doc_statuses[i],
                    apps[i]["applied_date"] + "T" + fake.time(),
                ])
        start = end

    # ── Fixed file 1: scoring_policy.yaml ──
    scoring_policy = {
        "risk_threshold": 50,
        "risk_factors": {
            "R01": {
                "name": "low_credit_score",
                "description": "Credit score below minimum acceptable threshold",
                "credit_score_threshold": 580,
                "points": 25,
            },
            "R02": {
                "name": "income_discrepancy",
                "description": "Self-reported income exceeds verified income beyond tolerance",
                "discrepancy_threshold": 0.30,
                "points": 20,
            },
            "R03": {
                "name": "vpn_proxy_high_limit",
                "description": "VPN or proxy detected with high credit limit request",
                "limit_threshold": 15000,
                "points": 30,
            },
            "R04": {
                "name": "fraudster_match",
                "description": "Applicant data matches known fraudster database entry",
                "points_by_severity": {"high": 40, "medium": 25, "low": 15},
            },
            "R05": {
                "name": "high_velocity",
                "description": "Multiple applications from same device or IP address",
                "velocity_threshold": 2,
                "points": 35,
            },
            "R06": {
                "name": "failed_documents",
                "description": "Document verification status is failed",
                "points": 20,
            },
            "R07": {
                "name": "bankruptcy_high_limit",
                "description": "Bankruptcy on record with high credit limit request",
                "limit_threshold": 10000,
                "points": 30,
            },
            "R08": {
                "name": "regional_high_risk",
                "description": "Applicant in high-risk region with below-average credit score",
                "credit_score_threshold": 650,
                "points": 15,
            },
            "R09": {
                "name": "suspicious_referral",
                "description": "Referral code matches known suspicious pattern",
                "points": 15,
            },
            "R10": {
                "name": "suspicious_email_domain",
                "description": "Email domain matches known disposable or suspicious provider",
                "points": 20,
            },
        },
    }
    with open(os.path.join(workspace, "scoring_policy.yaml"), "w") as fh:
        yaml.dump(scoring_policy, fh, default_flow_style=False, sort_keys=False)

    # ── Fixed file 2: fraud_rules.json ──
    fraud_rules = {
        "suspicious_referral_prefixes": suspicious_referral_prefixes,
        "suspicious_email_domains": suspicious_email_domains,
        "foreign_high_risk_countries": ["RU", "NG", "CN"],
        "notes": "Applications matching these patterns should be evaluated for the corresponding risk factor.",
    }
    with open(os.path.join(workspace, "fraud_rules.json"), "w") as fh:
        json.dump(fraud_rules, fh, indent=2)

    # ── Fixed file 3: reason_code_reference.csv ──
    rc_rows = [
        ["code", "name", "description", "category"],
        ["R01", "LOW_CREDIT", "Credit score below minimum threshold", "credit"],
        ["R02", "INCOME_MISMATCH", "Self-reported income exceeds verified income", "income"],
        ["R03", "VPN_HIGH_LIMIT", "VPN/proxy detected with high limit request", "device"],
        ["R04", "FRAUDSTER_MATCH", "Matches known fraudster database", "identity"],
        ["R05", "HIGH_VELOCITY", "Multiple applications from same device/IP", "velocity"],
        ["R06", "DOC_FAILED", "Document verification failed", "documentation"],
        ["R07", "BANKRUPT_HIGH_LIMIT", "Bankruptcy with high limit request", "credit"],
        ["R08", "REGIONAL_RISK", "High-risk region with low credit", "regional"],
        ["R09", "SUSPICIOUS_REFERRAL", "Suspicious referral code pattern", "referral"],
        ["R10", "SUSPICIOUS_EMAIL", "Suspicious email domain", "identity"],
    ]
    with open(os.path.join(workspace, "reason_code_reference.csv"), "w", newline="") as fh:
        csv.writer(fh).writerows(rc_rows)

    # ── Fixed file 4: regional_risk_map.json ──
    all_states = [
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
    ]
    regional_risk = {}
    for s in all_states:
        if s in high_risk_states:
            regional_risk[s] = "high"
        elif s in medium_risk_states:
            regional_risk[s] = "medium"
        else:
            regional_risk[s] = "low"
    with open(os.path.join(workspace, "regional_risk_map.json"), "w") as fh:
        json.dump(regional_risk, fh, indent=2)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db_path", required=True)
    p.add_argument("--workspace", required=True)
    main(p.parse_args().db_path, p.parse_args().workspace)
