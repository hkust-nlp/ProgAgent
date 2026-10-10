"""
Insider Trading Detection — data generation script.
Generates database tables and workspace files for the compliance investigation task.
"""

import argparse
import sqlite3
import os
import json
import csv
import random
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta
import yaml

# ──────────────────────────────────────────────
# SCALE — only this block differs across v0‒v3
# ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 320,      # v2 = 4x base
    "num_workspace_files": 24,  # v2 = base + 2N
}

# ── Fixed constants ──────────────────────────
TICKERS = [
    "ACME", "BOLT", "CRUX", "DYNX", "ECHO",
    "FLUX", "GRAV", "HEXA", "IONX", "JADE",
    "KRYP", "LUMA", "MNDO", "NOVA", "OMGX",
    "PIXL", "QBIT", "REVO", "SOLR", "TERA",
]

DEPARTMENTS = [
    "Legal", "Finance", "Engineering", "Marketing", "Research",
    "Operations", "Executive", "Compliance", "HR", "Sales",
]

SENSITIVE_DEPTS = {"Legal", "Finance", "Research", "Executive", "Compliance"}

EVENT_TYPES = [
    "earnings_release", "merger_announcement", "fda_approval",
    "product_launch", "restructuring", "dividend_change",
    "stock_split", "sec_filing",
]

DATA_CATEGORIES = [
    "financial_reports", "merger_documents", "clinical_trials",
    "product_specs", "board_minutes", "audit_reports",
    "legal_filings", "market_research",
]

TRADE_TYPES = ["buy", "sell"]
PRECLEARANCE_STATUSES = ["approved", "denied", "pending", "expired"]
ALERT_SEVERITIES = ["low", "medium", "high", "critical"]
BROKER_NAMES = [
    "Morgan Stanley", "Goldman Sachs", "JP Morgan", "Merrill Lynch",
    "Charles Schwab", "Fidelity", "TD Ameritrade", "Interactive Brokers",
]


def _date_range():
    """Canonical date range for the simulation."""
    return datetime(2025, 1, 1), datetime(2025, 12, 31)


def main(db_path: str, workspace: str):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    n = SCALE["rows_per_table"]
    nf = SCALE["num_workspace_files"]
    start_date, end_date = _date_range()
    total_days = (end_date - start_date).days

    # ────────────────────────────────────────
    # 1. Employees table
    # ────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            employee_id TEXT PRIMARY KEY,
            name TEXT,
            department TEXT,
            title TEXT,
            hire_date TEXT,
            is_officer INTEGER
        )
    """)

    employees = []
    for i in range(n):
        emp = {
            "employee_id": f"EMP-{i + 1:04d}",
            "name": fake.name(),
            "department": random.choice(DEPARTMENTS),
            "title": fake.job(),
            "hire_date": fake.date_between(
                start_date=datetime(2015, 1, 1),
                end_date=datetime(2024, 12, 31),
            ).isoformat(),
            "is_officer": 1 if random.random() < 0.15 else 0,
        }
        employees.append(emp)
    cur.executemany(
        "INSERT INTO employees VALUES (:employee_id,:name,:department,:title,:hire_date,:is_officer)",
        employees,
    )

    # ────────────────────────────────────────
    # 2. Corporate events table
    # ────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS corporate_events (
            event_id TEXT PRIMARY KEY,
            ticker TEXT,
            event_type TEXT,
            event_date TEXT,
            public_announcement_date TEXT,
            sensitivity_level INTEGER,
            description TEXT
        )
    """)

    events = []
    for i in range(n):
        ticker = random.choice(TICKERS)
        ev_date = start_date + timedelta(days=random.randint(0, total_days))
        ann_days = random.randint(0, 5)
        sens = random.choices([1, 2, 3, 4, 5], weights=[10, 20, 30, 25, 15])[0]
        ev = {
            "event_id": f"EVT-{i + 1:04d}",
            "ticker": ticker,
            "event_type": random.choice(EVENT_TYPES),
            "event_date": ev_date.strftime("%Y-%m-%d"),
            "public_announcement_date": (ev_date - timedelta(days=ann_days)).strftime(
                "%Y-%m-%d"
            ),
            "sensitivity_level": sens,
            "description": f"{random.choice(EVENT_TYPES).replace('_', ' ').title()} for {ticker}",
        }
        events.append(ev)
    cur.executemany(
        "INSERT INTO corporate_events VALUES "
        "(:event_id,:ticker,:event_type,:event_date,:public_announcement_date,"
        ":sensitivity_level,:description)",
        events,
    )

    # ────────────────────────────────────────
    # 3. Trade pre-clearance logs
    # ────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_preclearance (
            log_id TEXT PRIMARY KEY,
            employee_id TEXT,
            ticker TEXT,
            trade_type TEXT,
            shares INTEGER,
            requested_date TEXT,
            preclearance_status TEXT,
            decision_date TEXT,
            execution_date TEXT,
            FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
        )
    """)

    trades = []
    n_random = int(n * 0.6)
    for i in range(n_random):
        emp = random.choice(employees)
        req_date = start_date + timedelta(days=random.randint(0, total_days))
        status = random.choice(PRECLEARANCE_STATUSES)
        dec_date = req_date + timedelta(days=random.randint(1, 5))
        exec_date = (
            dec_date + timedelta(days=random.randint(0, 3))
            if status == "approved"
            else None
        )
        trades.append(
            {
                "log_id": f"TRD-{i + 1:04d}",
                "employee_id": emp["employee_id"],
                "ticker": random.choice(TICKERS),
                "trade_type": random.choice(TRADE_TYPES),
                "shares": random.randint(50, 5000),
                "requested_date": req_date.strftime("%Y-%m-%d"),
                "preclearance_status": status,
                "decision_date": dec_date.strftime("%Y-%m-%d"),
                "execution_date": exec_date.strftime("%Y-%m-%d") if exec_date else None,
            }
        )

    # ~40% trades deliberately near corporate events (suspicious)
    n_suspicious = n - n_random
    for j in range(n_suspicious):
        i = n_random + j
        ev = random.choice(events)
        emp = random.choice(employees)
        ev_dt = datetime.strptime(ev["event_date"], "%Y-%m-%d")
        offset = random.randint(-10, 3)
        req_date = ev_dt + timedelta(days=offset)
        req_date = max(start_date, min(end_date, req_date))
        status = random.choices(
            PRECLEARANCE_STATUSES, weights=[50, 15, 20, 15]
        )[0]
        dec_date = req_date + timedelta(days=random.randint(1, 3))
        exec_date = (
            dec_date + timedelta(days=random.randint(0, 2))
            if status == "approved"
            else None
        )
        trades.append(
            {
                "log_id": f"TRD-{i + 1:04d}",
                "employee_id": emp["employee_id"],
                "ticker": ev["ticker"],
                "trade_type": random.choice(TRADE_TYPES),
                "shares": random.randint(100, 8000),
                "requested_date": req_date.strftime("%Y-%m-%d"),
                "preclearance_status": status,
                "decision_date": dec_date.strftime("%Y-%m-%d"),
                "execution_date": exec_date.strftime("%Y-%m-%d") if exec_date else None,
            }
        )
    cur.executemany(
        "INSERT INTO trade_preclearance VALUES "
        "(:log_id,:employee_id,:ticker,:trade_type,:shares,:requested_date,"
        ":preclearance_status,:decision_date,:execution_date)",
        trades,
    )

    # ────────────────────────────────────────
    # 4. Sensitive data access logs
    # ────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS data_access_logs (
            access_id TEXT PRIMARY KEY,
            employee_id TEXT,
            system_name TEXT,
            data_category TEXT,
            access_timestamp TEXT,
            duration_minutes INTEGER,
            FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
        )
    """)

    systems = ["DocVault", "SecureShare", "BoardPortal", "FinanceHub", "ResearchDB"]
    access_logs = []
    for i in range(n):
        emp = random.choice(employees)
        acc_date = start_date + timedelta(
            days=random.randint(0, total_days),
            hours=random.randint(6, 22),
            minutes=random.randint(0, 59),
        )
        access_logs.append(
            {
                "access_id": f"ACC-{i + 1:04d}",
                "employee_id": emp["employee_id"],
                "system_name": random.choice(systems),
                "data_category": random.choice(DATA_CATEGORIES),
                "access_timestamp": acc_date.strftime("%Y-%m-%d %H:%M:%S"),
                "duration_minutes": random.randint(1, 120),
            }
        )
    cur.executemany(
        "INSERT INTO data_access_logs VALUES "
        "(:access_id,:employee_id,:system_name,:data_category,:access_timestamp,:duration_minutes)",
        access_logs,
    )

    # ────────────────────────────────────────
    # 5. Options volume alerts
    # ────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS options_alerts (
            alert_id TEXT PRIMARY KEY,
            ticker TEXT,
            alert_date TEXT,
            call_put TEXT,
            volume_ratio REAL,
            avg_historical_volume INTEGER,
            alert_severity TEXT
        )
    """)

    options = []
    for i in range(n):
        ticker = random.choice(TICKERS)
        a_date = start_date + timedelta(days=random.randint(0, total_days))
        vol_ratio = round(random.uniform(1.5, 15.0), 2)
        sev = (
            "critical"
            if vol_ratio >= 10
            else "high"
            if vol_ratio >= 6
            else "medium"
            if vol_ratio >= 3
            else "low"
        )
        options.append(
            {
                "alert_id": f"OPT-{i + 1:04d}",
                "ticker": ticker,
                "alert_date": a_date.strftime("%Y-%m-%d"),
                "call_put": random.choice(["call", "put"]),
                "volume_ratio": vol_ratio,
                "avg_historical_volume": random.randint(500, 50000),
                "alert_severity": sev,
            }
        )
    cur.executemany(
        "INSERT INTO options_alerts VALUES "
        "(:alert_id,:ticker,:alert_date,:call_put,:volume_ratio,:avg_historical_volume,:alert_severity)",
        options,
    )

    conn.commit()

    # ════════════════════════════════════════
    # WORKSPACE FILES
    # ════════════════════════════════════════

    # ── Fixed policy / config files (not counted in SCALE) ──

    policy = {
        "blackout_window_days": 14,
        "quiet_period_days": 2,
        "mnpi_access_lookback_days": 30,
        "options_correlation_window_days": 7,
        "risk_tiers": {
            "CRITICAL": {"min_score": 80, "recommended_action": "immediate_escalation"},
            "HIGH": {"min_score": 50, "recommended_action": "detailed_investigation"},
            "MEDIUM": {"min_score": 30, "recommended_action": "enhanced_monitoring"},
        },
        "case_inclusion_min_score": 30,
        "repeat_offender_multiplier": 1.5,
        "sensitive_departments": sorted(list(SENSITIVE_DEPTS)),
    }
    with open(os.path.join(workspace, "investigation_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    scoring = {
        "flags": {
            "blackout_trade": {
                "description": "Trade requested within the blackout window preceding a corporate event on the same ticker",
                "points": 25,
            },
            "mnpi_access": {
                "description": "Employee accessed sensitive data within the lookback window before a corporate event on a ticker they traded",
                "points": 30,
            },
            "options_correlation": {
                "description": "Unusual options volume alert on the same ticker within the correlation window of the trade request date",
                "points": 20,
            },
            "unreported_trade": {
                "description": "Trade found in broker confirmations but absent from the pre-clearance system",
                "points": 35,
            },
            "officer_trade": {
                "description": "The trading employee is a designated officer or insider",
                "points": 10,
            },
            "high_sensitivity_event": {
                "description": "The related corporate event has sensitivity_level >= 4",
                "points": 15,
            },
            "repeat_offender": {
                "description": "Employee appears as a prior subject in compliance memos",
                "points": 20,
            },
        },
        "score_calculation": "Sum all triggered flag points for a given (employee, ticker) pair. If repeat_offender is triggered, multiply the final total by the repeat_offender_multiplier from the investigation policy. Round the result to the nearest integer.",
        "output_format": {
            "file": "investigation_cases.csv",
            "columns": [
                "case_id",
                "employee_id",
                "employee_name",
                "ticker",
                "risk_score",
                "risk_tier",
                "flags",
                "recommended_action",
            ],
            "flags_delimiter": "|",
            "flags_sort": "alphabetical",
            "case_id_format": "CASE-NNNN (sequential starting at 0001, assigned after sorting)",
            "sort_order": "risk_score descending, then employee_name ascending as tie-breaker",
            "risk_score_format": "integer",
        },
    }
    with open(os.path.join(workspace, "risk_scoring_rules.json"), "w") as f:
        json.dump(scoring, f, indent=2)

    # ── Scalable data files ──
    files_per_type = max(1, nf // 4)
    remainder = nf - files_per_type * 4
    type_counts = [files_per_type] * 4
    for r in range(remainder):
        type_counts[r % 4] += 1
    n_broker, n_memo, n_holdings, n_market = type_counts

    # --- Broker confirmations (CSV) ---
    all_precleared_keys = set()
    for t in trades:
        if t["execution_date"]:
            all_precleared_keys.add(
                (t["employee_id"], t["ticker"], t["execution_date"])
            )

    broker_rows = []
    executed_trades = [t for t in trades if t["execution_date"]]
    for t in executed_trades:
        broker_rows.append(
            {
                "confirmation_id": f"BC-{len(broker_rows) + 1:05d}",
                "employee_id": t["employee_id"],
                "ticker": t["ticker"],
                "trade_type": t["trade_type"],
                "shares": t["shares"],
                "execution_date": t["execution_date"],
                "broker": random.choice(BROKER_NAMES),
            }
        )

    n_unreported = max(5, n // 10)
    for u in range(n_unreported):
        emp = random.choice(employees)
        ticker = random.choice(TICKERS)
        exec_date = (
            start_date + timedelta(days=random.randint(0, total_days))
        ).strftime("%Y-%m-%d")
        key = (emp["employee_id"], ticker, exec_date)
        attempts = 0
        while key in all_precleared_keys and attempts < 100:
            exec_date = (
                start_date + timedelta(days=random.randint(0, total_days))
            ).strftime("%Y-%m-%d")
            key = (emp["employee_id"], ticker, exec_date)
            attempts += 1
        broker_rows.append(
            {
                "confirmation_id": f"BC-{len(broker_rows) + 1:05d}",
                "employee_id": emp["employee_id"],
                "ticker": ticker,
                "trade_type": random.choice(TRADE_TYPES),
                "shares": random.randint(100, 3000),
                "execution_date": exec_date,
                "broker": random.choice(BROKER_NAMES),
            }
        )

    random.shuffle(broker_rows)
    chunk_size = max(1, len(broker_rows) // n_broker)
    for idx in range(n_broker):
        start_i = idx * chunk_size
        end_i = len(broker_rows) if idx == n_broker - 1 else (idx + 1) * chunk_size
        chunk = broker_rows[start_i:end_i]
        fname = os.path.join(workspace, f"broker_confirmation_{idx + 1:03d}.csv")
        with open(fname, "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "confirmation_id",
                    "employee_id",
                    "ticker",
                    "trade_type",
                    "shares",
                    "execution_date",
                    "broker",
                ],
            )
            w.writeheader()
            w.writerows(chunk)

    # --- Compliance memos (TXT) ---
    n_prior = max(3, n // 15)
    prior_subjects = random.sample(employees, n_prior)
    prior_employee_ids = {e["employee_id"] for e in prior_subjects}

    memo_entries = []
    for ps in prior_subjects:
        memo_date = fake.date_between(
            start_date=datetime(2023, 1, 1), end_date=datetime(2024, 12, 31)
        ).isoformat()
        issues = random.choice(
            [
                "Late reporting of personal securities transactions",
                "Potential conflict of interest in client trading",
                "Failure to obtain pre-clearance for restricted security",
                "Suspected front-running of block trades",
                "Unauthorized disclosure of material non-public information",
            ]
        )
        memo_entries.append(
            {
                "employee_id": ps["employee_id"],
                "employee_name": ps["name"],
                "date": memo_date,
                "issue": issues,
                "resolution": random.choice(
                    ["warning_issued", "training_required", "under_review"]
                ),
            }
        )

    chunk_size_m = max(1, len(memo_entries) // n_memo)
    for idx in range(n_memo):
        start_i = idx * chunk_size_m
        end_i = (
            len(memo_entries) if idx == n_memo - 1 else (idx + 1) * chunk_size_m
        )
        chunk = memo_entries[start_i:end_i]
        fname = os.path.join(workspace, f"compliance_memo_{idx + 1:03d}.txt")
        with open(fname, "w") as f:
            f.write("COMPLIANCE INVESTIGATION MEMOS\n")
            f.write("=" * 50 + "\n\n")
            for entry in chunk:
                f.write(f"Subject: {entry['employee_id']} ({entry['employee_name']})\n")
                f.write(f"Date: {entry['date']}\n")
                f.write(f"Issue: {entry['issue']}\n")
                f.write(f"Resolution: {entry['resolution']}\n")
                f.write("-" * 40 + "\n\n")

    # --- Employee holdings (JSON) ---
    holdings_data = []
    for emp in employees:
        n_positions = random.randint(1, 6)
        positions = {}
        for _ in range(n_positions):
            t = random.choice(TICKERS)
            positions[t] = {
                "shares": random.randint(100, 20000),
                "avg_cost_basis": round(random.uniform(10, 500), 2),
            }
        holdings_data.append(
            {
                "employee_id": emp["employee_id"],
                "snapshot_date": "2025-01-01",
                "positions": positions,
            }
        )

    chunk_size_h = max(1, len(holdings_data) // n_holdings)
    for idx in range(n_holdings):
        start_i = idx * chunk_size_h
        end_i = (
            len(holdings_data) if idx == n_holdings - 1 else (idx + 1) * chunk_size_h
        )
        chunk = holdings_data[start_i:end_i]
        fname = os.path.join(workspace, f"employee_holdings_{idx + 1:03d}.json")
        with open(fname, "w") as f:
            json.dump(chunk, f, indent=2)

    # --- Market snapshots (YAML) ---
    market_data = []
    for ticker in TICKERS:
        for _ in range(max(1, n // 20)):
            snap_date = (
                start_date + timedelta(days=random.randint(0, total_days))
            ).strftime("%Y-%m-%d")
            market_data.append(
                {
                    "ticker": ticker,
                    "date": snap_date,
                    "close_price": round(random.uniform(15, 800), 2),
                    "daily_volume": random.randint(100000, 50000000),
                    "sector_avg_volume": random.randint(500000, 20000000),
                    "market_wide_unusual_flag": random.random() < 0.1,
                }
            )

    chunk_size_k = max(1, len(market_data) // n_market)
    for idx in range(n_market):
        start_i = idx * chunk_size_k
        end_i = (
            len(market_data) if idx == n_market - 1 else (idx + 1) * chunk_size_k
        )
        chunk = market_data[start_i:end_i]
        fname = os.path.join(workspace, f"market_snapshot_{idx + 1:03d}.yaml")
        with open(fname, "w") as f:
            yaml.dump(chunk, f, default_flow_style=False)

    conn.close()
    print(f"Database created at {db_path}")
    print(
        f"Workspace populated at {workspace}/ with {nf} scalable data files + 2 fixed config files"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
