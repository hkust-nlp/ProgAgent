import argparse
import sqlite3
import os
import json
import csv
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 120,
    "num_workspace_files": 30,
}

# ---------------------------------------------------------------------------
# Deterministic seeding
# ---------------------------------------------------------------------------
fake = Faker()
Faker.seed(42)
np.random.seed(42)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
INDUSTRIES = [
    ("RET", "Retail"),
    ("MFG", "Manufacturing"),
    ("TECH", "Technology"),
    ("FOOD", "Food Services"),
    ("HLTH", "Healthcare"),
    ("CONS", "Construction"),
    ("TRANS", "Transportation"),
    ("PROF", "Professional Services"),
]

ASSET_TYPES = ["real_estate", "equipment", "inventory", "vehicle", "accounts_receivable"]

TXN_CATEGORIES_CREDIT = [
    "sales_revenue", "loan_proceeds", "investment_income", "refund", "grant",
]
TXN_CATEGORIES_DEBIT = [
    "payroll", "rent", "utilities", "supplies", "insurance",
    "maintenance", "marketing", "taxes",
]

INDUSTRY_DEFAULT_RATES = {
    "RET": 4.2, "MFG": 3.8, "TECH": 5.1, "FOOD": 7.3,
    "HLTH": 2.9, "CONS": 6.5, "TRANS": 5.8, "PROF": 2.4,
}

REFERENCE_DATE = pd.Timestamp("2026-03-20")


# ===================================================================
# Database schema
# ===================================================================
def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS loan_applications (
        application_id TEXT PRIMARY KEY,
        business_name TEXT,
        industry_code TEXT,
        requested_amount REAL,
        lender_id TEXT,
        status TEXT,
        submission_date TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS bank_transactions (
        transaction_id TEXT PRIMARY KEY,
        application_id TEXT,
        transaction_date TEXT,
        amount REAL,
        type TEXT,
        category TEXT,
        description TEXT,
        FOREIGN KEY (application_id) REFERENCES loan_applications(application_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS collateral_assets (
        asset_id TEXT PRIMARY KEY,
        application_id TEXT,
        asset_type TEXT,
        description TEXT,
        declared_value REAL,
        current_market_value REAL,
        FOREIGN KEY (application_id) REFERENCES loan_applications(application_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS lender_portfolios (
        portfolio_id TEXT PRIMARY KEY,
        lender_id TEXT,
        industry_code TEXT,
        current_exposure REAL,
        max_exposure REAL
    )""")
    conn.commit()


# ===================================================================
# Data generators
# ===================================================================
def generate_applications(n_rows, n_pending):
    """Generate loan applications; first n_pending have status='pending'."""
    applications = []
    statuses_other = ["approved", "denied", "withdrawn"]

    for i in range(n_rows):
        app_id = f"APP_{i + 1:04d}"
        business_name = fake.company()
        industry_code = INDUSTRIES[np.random.randint(0, len(INDUSTRIES))][0]
        requested_amount = round(float(np.random.uniform(25000, 500000)), 2)
        # Scale lenders so the portfolio table can hit row targets
        n_lenders = max(5, n_rows // 6)
        lender_id = f"L{np.random.randint(1, n_lenders + 1):03d}"

        if i < n_pending:
            status = "pending"
            days_ago = int(np.random.randint(1, 31))
        else:
            status = statuses_other[int(np.random.randint(0, len(statuses_other)))]
            days_ago = int(np.random.randint(31, 180))

        submission_date = (REFERENCE_DATE - pd.Timedelta(days=days_ago)).strftime("%Y-%m-%d")

        applications.append({
            "application_id": app_id,
            "business_name": business_name,
            "industry_code": industry_code,
            "requested_amount": requested_amount,
            "lender_id": lender_id,
            "status": status,
            "submission_date": submission_date,
        })

    return applications


def generate_transactions(applications, min_rows):
    """Generate bank transactions; at least min_rows total."""
    transactions = []
    txn_id = 0
    txns_per_app = max(10, min_rows // len(applications) + 1)

    for app in applications:
        n_txns = int(np.random.randint(txns_per_app, txns_per_app + 10))
        for _ in range(n_txns):
            txn_id += 1
            days_ago = int(np.random.randint(1, 180))
            txn_date = (REFERENCE_DATE - pd.Timedelta(days=days_ago)).strftime("%Y-%m-%d")

            if np.random.random() < 0.6:
                txn_type = "credit"
                category = TXN_CATEGORIES_CREDIT[int(np.random.randint(0, len(TXN_CATEGORIES_CREDIT)))]
                amount = round(float(np.random.uniform(500, 50000)), 2)
            else:
                txn_type = "debit"
                category = TXN_CATEGORIES_DEBIT[int(np.random.randint(0, len(TXN_CATEGORIES_DEBIT)))]
                amount = round(float(np.random.uniform(200, 30000)), 2)

            transactions.append({
                "transaction_id": f"TXN_{txn_id:06d}",
                "application_id": app["application_id"],
                "transaction_date": txn_date,
                "amount": amount,
                "type": txn_type,
                "category": category,
                "description": f"{category.replace('_', ' ').title()} - {fake.bs()}",
            })

    return transactions


def generate_collateral(applications, min_rows):
    """Generate collateral assets; at least min_rows total."""
    assets = []
    asset_id = 0
    assets_per_app = max(1, min_rows // len(applications))

    for app in applications:
        n_assets = int(np.random.randint(assets_per_app, assets_per_app + 3))
        for _ in range(n_assets):
            asset_id += 1
            asset_type = ASSET_TYPES[int(np.random.randint(0, len(ASSET_TYPES)))]
            declared_value = round(float(np.random.uniform(10000, 300000)), 2)
            market_factor = float(np.random.uniform(0.6, 1.3))
            current_market_value = round(declared_value * market_factor, 2)

            assets.append({
                "asset_id": f"AST_{asset_id:04d}",
                "application_id": app["application_id"],
                "asset_type": asset_type,
                "description": f"{asset_type.replace('_', ' ').title()} - {fake.catch_phrase()}",
                "declared_value": declared_value,
                "current_market_value": current_market_value,
            })

    return assets


def generate_lender_portfolios(n_rows):
    """One row per (lender, industry) combination; at least n_rows."""
    portfolios = []
    pid = 0
    n_lenders = max(5, n_rows // 6)
    lender_ids = [f"L{i + 1:03d}" for i in range(n_lenders)]

    combos = [(lid, ind[0]) for lid in lender_ids for ind in INDUSTRIES]
    # Shuffle deterministically (seed already set)
    indices = np.random.permutation(len(combos)).tolist()
    combos = [combos[i] for i in indices]

    # If combos < n_rows, pad with extra entries (different sub-portfolio splits)
    while len(combos) < n_rows:
        extra_lid = lender_ids[int(np.random.randint(0, len(lender_ids)))]
        extra_ind = INDUSTRIES[int(np.random.randint(0, len(INDUSTRIES)))][0]
        combos.append((extra_lid, extra_ind))

    # Deduplicate by (lender_id, industry_code) — keep first occurrence
    seen = set()
    unique_combos = []
    for lid, icode in combos:
        key = (lid, icode)
        if key not in seen:
            seen.add(key)
            unique_combos.append(key)
    # If dedup brought us below n_rows, add new lenders
    extra_lender_counter = n_lenders
    while len(unique_combos) < n_rows:
        extra_lender_counter += 1
        extra_lid = f"L{extra_lender_counter:03d}"
        for ind in INDUSTRIES:
            unique_combos.append((extra_lid, ind[0]))
            if len(unique_combos) >= n_rows:
                break

    for lid, icode in unique_combos:
        pid += 1
        max_exposure = round(float(np.random.uniform(500000, 5000000)), 2)
        current_exposure = round(float(np.random.uniform(0, max_exposure * 0.9)), 2)
        portfolios.append({
            "portfolio_id": f"PF_{pid:04d}",
            "lender_id": lid,
            "industry_code": icode,
            "current_exposure": current_exposure,
            "max_exposure": max_exposure,
        })

    return portfolios


# ===================================================================
# Workspace file generation
# ===================================================================
def generate_workspace(workspace, applications, transactions, collateral_assets):
    os.makedirs(workspace, exist_ok=True)

    # ---------------------------------------------------------------
    # Fixed config file 1: risk_config.yaml  (written as JSON-superset
    # YAML via manual formatting for readability)
    # ---------------------------------------------------------------
    risk_config = {
        "risk_scoring": {
            "weights": {
                "credit_score": 0.25,
                "dti_ratio": 0.20,
                "cash_flow_stability": 0.20,
                "collateral_coverage": 0.20,
                "industry_risk": 0.10,
                "business_maturity": 0.05,
            },
            "credit_score_bands": {
                "excellent": {"min": 750, "max": 850, "component_score": 100},
                "good": {"min": 680, "max": 749, "component_score": 75},
                "fair": {"min": 620, "max": 679, "component_score": 50},
                "poor": {"min": 0, "max": 619, "component_score": 25},
            },
            "dti_bands": {
                "low": {"min": 0.0, "max": 0.30, "component_score": 100},
                "moderate": {"min": 0.30, "max": 0.45, "component_score": 70},
                "high": {"min": 0.45, "max": 0.60, "component_score": 40},
                "very_high": {"min": 0.60, "max": 1.0, "component_score": 10},
            },
            "cash_flow_assessment": {
                "positive_trend": {
                    "description": "Later-half average net cash flow exceeds earlier-half average by more than 5 percent",
                    "component_score": 100,
                },
                "stable": {
                    "description": "Later-half and earlier-half averages are within 5 percent of each other",
                    "component_score": 75,
                },
                "declining": {
                    "description": "Later-half average is more than 5 percent below earlier-half average",
                    "component_score": 40,
                },
                "negative": {
                    "description": "Overall average monthly net cash flow is negative",
                    "component_score": 10,
                },
            },
            "collateral_coverage_bands": {
                "full": {"min": 1.0, "max": 999.0, "component_score": 100},
                "substantial": {"min": 0.5, "max": 1.0, "component_score": 60},
                "partial": {"min": 0.2, "max": 0.5, "component_score": 30},
                "insufficient": {"min": 0.0, "max": 0.2, "component_score": 10},
            },
            "industry_risk_formula": "component_score = max(0, 100 - default_rate_pct * 10)",
            "business_maturity_bands": {
                "established": {"min_years": 10, "component_score": 100},
                "mature": {"min_years": 5, "component_score": 75},
                "growing": {"min_years": 2, "component_score": 50},
                "startup": {"min_years": 0, "component_score": 25},
            },
        },
        "risk_tiers": {
            "tier_1": {"label": "Low Risk", "min_score": 75, "credit_limit_pct": 1.00},
            "tier_2": {"label": "Moderate Risk", "min_score": 55, "credit_limit_pct": 0.75},
            "tier_3": {"label": "Elevated Risk", "min_score": 35, "credit_limit_pct": 0.50},
            "tier_4": {"label": "High Risk", "min_score": 0, "credit_limit_pct": 0.25},
        },
        "credit_limit_formula": (
            "credit_limit = min(requested_amount * credit_limit_pct, "
            "total_collateral_market_value, lender_remaining_capacity)"
        ),
    }

    # Write as JSON (universally parseable; the .yaml extension is kept for
    # the task but content is valid YAML because JSON is a YAML subset)
    with open(os.path.join(workspace, "risk_config.yaml"), "w") as f:
        # Pretty-print with manual YAML-style for readability
        import yaml  # noqa: delayed import keeps top-level imports clean
        yaml.dump(risk_config, f, default_flow_style=False, sort_keys=False)

    # ---------------------------------------------------------------
    # Fixed config file 2: lending_policy.md
    # ---------------------------------------------------------------
    policy = """# Lending Policy Document

## Eligibility Requirements

All pending loan applications must satisfy every one of the following minimum criteria to be considered for approval. Any application failing one or more of these criteria must be denied.

- Minimum credit score: 580
- Maximum debt-to-income ratio: 0.65
- Minimum years in business: 1
- Minimum collateral coverage ratio: 0.15 (total collateral market value divided by requested amount)
- Lender industry exposure: the lender's current exposure plus the proposed credit limit must not exceed the lender's maximum exposure for the applicant's industry

## Debt-to-Income Ratio

DTI is calculated as: total_existing_debt / annual_revenue
Both values come from the applicant's financial profile.

## Risk Score Computation

The composite risk score is a weighted average of six component scores. Each component is scored on a 0 to 100 scale. The weights and band definitions are specified in risk_config.yaml.

    composite_risk_score = sum(weight_i * component_score_i) for all six components

The composite score is rounded to two decimal places.

## Cash Flow Assessment

Cash flow is assessed using the applicant's bank transaction history over the most recent six months (relative to 2026-03-20). Monthly net cash flow equals the sum of credit amounts minus the sum of debit amounts for each calendar month.

Only calendar months that contain at least one transaction are considered. Sort those months chronologically and split the list into two halves: the earlier half and the later half. When there is an odd number of months, the middle month belongs to the earlier half.

If either half is empty, classify the cash flow as "stable".

Otherwise compare the average monthly net cash flow of the later half to the average of the earlier half:
- If the overall (all-month) average monthly net cash flow is negative, classify as "negative" regardless of trend.
- If later-half average exceeds earlier-half average by more than 5 percent, classify as "positive_trend".
- If later-half average is more than 5 percent below earlier-half average, classify as "declining".
- Otherwise classify as "stable".

## Credit Limit Determination

The credit limit is the minimum of three values:
1. requested_amount multiplied by the tier's credit_limit_pct
2. total collateral market value (sum of current market values of all collateral assets for the application)
3. lender remaining capacity (max_exposure minus current_exposure for the lender-industry combination)

The credit limit is rounded to two decimal places.

## Priority Queue Ordering

Approved applications are ranked by composite risk score in descending order (highest score = lowest risk = rank 1). Ties in score are broken by submission date ascending (earlier date first). If both score and date match, sort by application_id in ascending lexicographic order.

Denied applications are not ranked but must appear in the output.
"""

    with open(os.path.join(workspace, "lending_policy.md"), "w") as f:
        f.write(policy)

    # ---------------------------------------------------------------
    # Fixed config file 3: industry_default_rates.csv
    # ---------------------------------------------------------------
    default_rates = [
        {"industry_code": "RET", "industry_name": "Retail", "default_rate_pct": 4.2, "risk_premium_bps": 150},
        {"industry_code": "MFG", "industry_name": "Manufacturing", "default_rate_pct": 3.8, "risk_premium_bps": 130},
        {"industry_code": "TECH", "industry_name": "Technology", "default_rate_pct": 5.1, "risk_premium_bps": 180},
        {"industry_code": "FOOD", "industry_name": "Food Services", "default_rate_pct": 7.3, "risk_premium_bps": 250},
        {"industry_code": "HLTH", "industry_name": "Healthcare", "default_rate_pct": 2.9, "risk_premium_bps": 100},
        {"industry_code": "CONS", "industry_name": "Construction", "default_rate_pct": 6.5, "risk_premium_bps": 220},
        {"industry_code": "TRANS", "industry_name": "Transportation", "default_rate_pct": 5.8, "risk_premium_bps": 200},
        {"industry_code": "PROF", "industry_name": "Professional Services", "default_rate_pct": 2.4, "risk_premium_bps": 85},
    ]

    with open(os.path.join(workspace, "industry_default_rates.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["industry_code", "industry_name", "default_rate_pct", "risk_premium_bps"])
        writer.writeheader()
        writer.writerows(default_rates)

    # ---------------------------------------------------------------
    # Scalable files: one financial profile per pending application
    # ---------------------------------------------------------------
    pending_apps = [a for a in applications if a["status"] == "pending"]

    financials_dir = os.path.join(workspace, "financials")
    os.makedirs(financials_dir, exist_ok=True)

    for app in pending_apps:
        credit_score = int(np.random.randint(520, 820))
        annual_revenue = round(float(np.random.uniform(80000, 2000000)), 2)
        # Varied DTI distribution — some above the 0.65 cutoff
        dti_target = float(np.random.choice(
            [0.15, 0.25, 0.35, 0.50, 0.55, 0.70],
            p=[0.15, 0.25, 0.25, 0.15, 0.10, 0.10],
        ))
        total_existing_debt = round(annual_revenue * dti_target, 2)
        years_in_business = int(np.random.choice(
            [0, 1, 2, 3, 5, 8, 12, 15, 20],
            p=[0.05, 0.10, 0.15, 0.15, 0.15, 0.15, 0.10, 0.10, 0.05],
        ))

        profile = {
            "application_id": app["application_id"],
            "business_name": app["business_name"],
            "credit_score": credit_score,
            "annual_revenue": annual_revenue,
            "total_existing_debt": total_existing_debt,
            "years_in_business": years_in_business,
        }

        with open(os.path.join(financials_dir, f"{app['application_id']}.json"), "w") as f:
            json.dump(profile, f, indent=2)


# ===================================================================
# Main
# ===================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_rows = SCALE["rows_per_table"]
    n_pending = SCALE["num_workspace_files"]

    # Generate all data
    applications = generate_applications(n_rows, n_pending)
    transactions = generate_transactions(applications, n_rows)
    collateral = generate_collateral(applications, n_rows)
    portfolios = generate_lender_portfolios(n_rows)

    # Populate database
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    c = conn.cursor()

    for a in applications:
        c.execute(
            "INSERT INTO loan_applications VALUES (?,?,?,?,?,?,?)",
            (a["application_id"], a["business_name"], a["industry_code"],
             a["requested_amount"], a["lender_id"], a["status"], a["submission_date"]),
        )
    for t in transactions:
        c.execute(
            "INSERT INTO bank_transactions VALUES (?,?,?,?,?,?,?)",
            (t["transaction_id"], t["application_id"], t["transaction_date"],
             t["amount"], t["type"], t["category"], t["description"]),
        )
    for ca in collateral:
        c.execute(
            "INSERT INTO collateral_assets VALUES (?,?,?,?,?,?)",
            (ca["asset_id"], ca["application_id"], ca["asset_type"],
             ca["description"], ca["declared_value"], ca["current_market_value"]),
        )
    for p in portfolios:
        c.execute(
            "INSERT INTO lender_portfolios VALUES (?,?,?,?,?)",
            (p["portfolio_id"], p["lender_id"], p["industry_code"],
             p["current_exposure"], p["max_exposure"]),
        )

    conn.commit()
    conn.close()

    # Build workspace
    generate_workspace(args.workspace, applications, transactions, collateral)

    print(f"Database: {args.db_path}  ({n_rows} apps, {len(transactions)} txns, "
          f"{len(collateral)} assets, {len(portfolios)} portfolio rows)")
    print(f"Workspace: {args.workspace}  ({n_pending} pending profiles + 3 config files)")


if __name__ == "__main__":
    main()
