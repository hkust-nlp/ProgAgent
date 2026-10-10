"""
Data generation for franchisee marketing promotion compliance monitoring task.
Generates database tables and workspace files for cross-referencing POS transactions,
coupon redemptions, advertising spend, and brand guidelines.
"""

import argparse
import json
import os
import sqlite3
import yaml
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 30,
}

NUM_PROMOTIONS = 5
NUM_CHANNELS = 4  # digital, print, social_media, radio

REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest", "West"]
TIERS = ["Gold", "Silver", "Bronze"]
PROMOTION_TYPES = ["percentage_discount", "bogo", "coupon_bundle", "seasonal_sale", "loyalty_reward"]
CHANNELS = ["digital", "print", "social_media", "radio"]
ITEM_CATEGORIES = ["burgers", "beverages", "sides", "desserts", "combos", "breakfast"]

fake = Faker()
Faker.seed(42)
np.random.seed(42)


def generate_franchisees(num_franchisees):
    """Generate franchisee records."""
    records = []
    for i in range(1, num_franchisees + 1):
        records.append({
            "franchisee_id": f"FR-{i:04d}",
            "name": f"{fake.last_name()} {fake.random_element(['Foods', 'Dining', 'Eatery', 'Kitchen', 'Grill'])} #{fake.random_int(100, 999)}",
            "region": REGIONS[i % len(REGIONS)],
            "city": fake.city(),
            "state": fake.state_abbr(),
            "contact_email": fake.company_email(),
            "tier": TIERS[i % len(TIERS)],
            "active_since": fake.date_between(start_date="-10y", end_date="-1y").isoformat(),
            "is_active": 1,
        })
    return pd.DataFrame(records)


def generate_promotions():
    """Generate national promotion records."""
    promo_names = [
        "Summer Sizzle Savings",
        "Back to School Bundle",
        "Holiday Feast Deal",
        "Spring Fresh Start",
        "Weekend Warriors Special",
    ]
    required_discounts = [15.0, 20.0, 25.0, 10.0, 12.0]
    min_ad_spends = [5000.0, 8000.0, 12000.0, 4000.0, 3000.0]
    mandatory_flags = [1, 1, 1, 0, 0]  # first 3 are mandatory

    records = []
    for i in range(NUM_PROMOTIONS):
        records.append({
            "promotion_id": f"PROMO-{i + 1:03d}",
            "name": promo_names[i],
            "type": PROMOTION_TYPES[i],
            "start_date": f"2025-{(i * 2 + 1):02d}-01",
            "end_date": f"2025-{(i * 2 + 2):02d}-28",
            "required_discount_pct": required_discounts[i],
            "min_local_ad_spend": min_ad_spends[i],
            "is_mandatory": mandatory_flags[i],
            "status": "active",
        })
    return pd.DataFrame(records)


def generate_pos_transactions(franchisees_df, promotions_df, num_rows, rng):
    """Generate POS transaction records with some violations embedded."""
    franchisee_ids = franchisees_df["franchisee_id"].tolist()
    promotion_ids = promotions_df["promotion_id"].tolist()
    required_discounts = dict(zip(promotions_df["promotion_id"], promotions_df["required_discount_pct"]))

    # Determine which (franchisee, promotion) pairs have discount violations
    violation_pairs = set()
    for fi, fid in enumerate(franchisee_ids):
        for pi, pid in enumerate(promotion_ids):
            # Use deterministic hash to decide violations
            h = hash((fid, pid, "discount_violation")) % 100
            if h < 18:  # ~18% chance of discount violation
                violation_pairs.add((fid, pid))

    # Determine non-participation pairs (franchisee doesn't run some mandatory promotions)
    non_participation = set()
    mandatory_promos = promotions_df[promotions_df["is_mandatory"] == 1]["promotion_id"].tolist()
    for fi, fid in enumerate(franchisee_ids):
        h = hash((fid, "non_participation")) % 100
        if h < 20:  # ~20% chance a franchisee skips a mandatory promo
            skip_idx = hash((fid, "skip_which")) % len(mandatory_promos)
            non_participation.add((fid, mandatory_promos[skip_idx]))

    # Build participation map: which promos each franchisee participates in
    participation = {}
    for fid in franchisee_ids:
        participating_promos = []
        for pid in promotion_ids:
            if (fid, pid) not in non_participation:
                participating_promos.append(pid)
        participation[fid] = participating_promos

    records = []
    row_id = 0
    # Distribute rows across participating (franchisee, promotion) pairs
    active_pairs = []
    for fid in franchisee_ids:
        for pid in participation[fid]:
            active_pairs.append((fid, pid))

    rows_per_pair = max(2, num_rows // max(len(active_pairs), 1))
    extra_rows = num_rows - rows_per_pair * len(active_pairs)

    for idx, (fid, pid) in enumerate(active_pairs):
        n = rows_per_pair + (1 if idx < extra_rows else 0)
        req_disc = required_discounts[pid]

        for _ in range(n):
            row_id += 1
            original_price = round(rng.uniform(5.0, 50.0), 2)

            if (fid, pid) in violation_pairs:
                # Generate incorrect discount
                deviation = rng.choice([-8, -6, -5, 7, 8, 10, 12])
                applied_discount = max(0.0, min(50.0, req_disc + deviation))
            else:
                # Correct discount with minor noise
                applied_discount = req_disc + rng.uniform(-1.0, 1.0)
                applied_discount = round(max(0.0, applied_discount), 1)

            final_price = round(original_price * (1 - applied_discount / 100), 2)
            txn_date = f"2025-{rng.integers(1, 13):02d}-{rng.integers(1, 29):02d}"

            records.append({
                "transaction_id": f"TXN-{row_id:06d}",
                "franchisee_id": fid,
                "promotion_id": pid,
                "transaction_date": txn_date,
                "item_category": rng.choice(ITEM_CATEGORIES),
                "original_price": original_price,
                "applied_discount_pct": round(applied_discount, 1),
                "final_price": final_price,
                "quantity": int(rng.integers(1, 6)),
            })

    return pd.DataFrame(records), violation_pairs, non_participation


def generate_coupon_redemptions(franchisees_df, promotions_df, num_rows, rng):
    """Generate coupon redemption records with some invalid rate violations."""
    franchisee_ids = franchisees_df["franchisee_id"].tolist()
    promotion_ids = promotions_df["promotion_id"].tolist()

    # Determine which franchisees have coupon violations
    coupon_violation_franchisees = set()
    for fid in franchisee_ids:
        h = hash((fid, "coupon_violation")) % 100
        if h < 22:  # ~22% chance
            coupon_violation_franchisees.add(fid)

    records = []
    rows_per_franchisee = max(3, num_rows // len(franchisee_ids))
    extra = num_rows - rows_per_franchisee * len(franchisee_ids)

    row_id = 0
    for fi, fid in enumerate(franchisee_ids):
        n = rows_per_franchisee + (1 if fi < extra else 0)
        for _ in range(n):
            row_id += 1
            pid = rng.choice(promotion_ids)
            discount_amount = round(rng.uniform(1.0, 15.0), 2)

            if fid in coupon_violation_franchisees:
                # High rate of invalid/expired
                status = rng.choice(["valid", "invalid", "expired", "invalid", "expired"])
            else:
                # Mostly valid
                status = rng.choice(["valid", "valid", "valid", "valid", "invalid", "expired"])

            redemption_date = f"2025-{rng.integers(1, 13):02d}-{rng.integers(1, 29):02d}"
            records.append({
                "redemption_id": f"RDM-{row_id:06d}",
                "franchisee_id": fid,
                "promotion_id": pid,
                "coupon_code": f"CPN-{rng.integers(10000, 99999)}",
                "redemption_date": redemption_date,
                "discount_amount": discount_amount,
                "status": status,
            })

    return pd.DataFrame(records), coupon_violation_franchisees


def generate_ad_spend_data(franchisees_df, promotions_df, rng):
    """Generate advertising spend data for workspace files.
    Returns a dict: franchisee_id -> list of {promotion_id, channel, planned_spend, actual_spend}
    Also returns the set of underfunded (franchisee, promotion) pairs.
    """
    franchisee_ids = franchisees_df["franchisee_id"].tolist()
    min_spends = dict(zip(promotions_df["promotion_id"], promotions_df["min_local_ad_spend"]))
    promotion_ids = promotions_df["promotion_id"].tolist()

    # Determine underfunded pairs
    underfunded_pairs = set()
    for fid in franchisee_ids:
        for pid in promotion_ids:
            h = hash((fid, pid, "underfunded")) % 100
            if h < 15:  # ~15% chance
                underfunded_pairs.add((fid, pid))

    spend_data = {}
    for fid in franchisee_ids:
        rows = []
        for pid in promotion_ids:
            min_spend = min_spends[pid]
            for ch in CHANNELS:
                fair_share = min_spend / len(CHANNELS)
                planned = round(fair_share * rng.uniform(0.9, 1.3), 2)

                if (fid, pid) in underfunded_pairs:
                    # Underfunded: actual is significantly below planned
                    actual = round(planned * rng.uniform(0.15, 0.45), 2)
                else:
                    actual = round(planned * rng.uniform(0.85, 1.15), 2)

                rows.append({
                    "promotion_id": pid,
                    "channel": ch,
                    "planned_spend": planned,
                    "actual_spend": actual,
                })
        spend_data[fid] = rows

    return spend_data, underfunded_pairs


def create_workspace_files(workspace, franchisees_df, promotions_df, spend_data, rng):
    """Create workspace files including scaling ad reports and fixed config files."""
    os.makedirs(workspace, exist_ok=True)
    ad_reports_dir = os.path.join(workspace, "ad_reports")
    os.makedirs(ad_reports_dir, exist_ok=True)

    # --- Fixed config files ---

    # 1. Brand guidelines (markdown)
    brand_guidelines = """# National Brand Marketing Guidelines

## Promotion Compliance Standards

All franchisees are required to adhere to national marketing promotion parameters as defined
by corporate headquarters. Compliance is measured across three dimensions: pricing accuracy,
advertising investment, and coupon processing integrity.

### Pricing Accuracy
Franchisees must apply the exact discount percentage specified for each national promotion.
A tolerance band is defined in the compliance configuration. Any average applied discount
falling outside the required percentage plus or minus the tolerance constitutes a pricing violation.

### Advertising Investment
Each promotion specifies a minimum local advertising spend. Franchisees must meet or exceed
this threshold across all advertising channels combined. Failure to meet the minimum constitutes
an underfunded campaign violation.

### Coupon Processing
Digital coupon redemptions must maintain an invalid/expired rate below the defined threshold.
Franchisees with excessive invalid or expired coupon processing rates are flagged for
coupon processing violations.

### Mandatory Participation
Certain promotions are designated as mandatory. All active franchisees must participate in
mandatory promotions. Absence of any point-of-sale transactions for a mandatory promotion
constitutes a non-participation violation.

### Severity Classification
Violations are classified by severity based on the magnitude of deviation from requirements.
Severity thresholds and corresponding recommended corrective actions are defined in the
compliance configuration file.
"""
    with open(os.path.join(workspace, "brand_guidelines.md"), "w") as f:
        f.write(brand_guidelines)

    # 2. Compliance thresholds (YAML)
    compliance_config = {
        "discount_tolerance_pct": 3.0,
        "max_coupon_invalid_rate_pct": 25.0,
        "severity_rules": {
            "discount_violation": {
                "CRITICAL": {"min_deviation_pct": 10.0},
                "HIGH": {"min_deviation_pct": 6.0},
                "MEDIUM": {"min_deviation_pct": 3.0},
            },
            "underfunded_campaign": {
                "CRITICAL": {"max_funding_ratio_pct": 30.0},
                "HIGH": {"max_funding_ratio_pct": 50.0},
                "MEDIUM": {"max_funding_ratio_pct": 75.0},
            },
            "coupon_violation": {
                "CRITICAL": {"min_invalid_rate_pct": 50.0},
                "HIGH": {"min_invalid_rate_pct": 35.0},
                "MEDIUM": {"min_invalid_rate_pct": 25.0},
            },
            "non_participation": {
                "HIGH": {"description": "Missing mandatory promotion participation"},
            },
        },
        "recommended_actions": {
            "discount_violation": {
                "CRITICAL": "Immediately suspend promotion pricing; conduct full POS audit; retrain all staff",
                "HIGH": "Issue pricing correction directive; schedule POS system review within 7 days",
                "MEDIUM": "Send pricing reminder notice; monitor next 30 days",
            },
            "underfunded_campaign": {
                "CRITICAL": "Require immediate supplemental ad budget submission; escalate to regional manager",
                "HIGH": "Request revised media plan within 14 days; increase digital allocation",
                "MEDIUM": "Send budget compliance reminder; review at next quarterly meeting",
            },
            "coupon_violation": {
                "CRITICAL": "Suspend coupon acceptance; mandatory staff retraining on coupon procedures",
                "HIGH": "Audit coupon processing workflow; retrain front-line staff within 14 days",
                "MEDIUM": "Issue coupon processing guidelines reminder; monitor weekly",
            },
            "non_participation": {
                "HIGH": "Require written explanation within 7 days; implement promotion within 14 days",
            },
        },
    }
    with open(os.path.join(workspace, "compliance_thresholds.yaml"), "w") as f:
        yaml.dump(compliance_config, f, default_flow_style=False, sort_keys=False)

    # 3. Promotion calendar (JSON) - includes mandatory/optional flags
    promo_calendar = []
    for _, row in promotions_df.iterrows():
        promo_calendar.append({
            "promotion_id": row["promotion_id"],
            "name": row["name"],
            "period": f"{row['start_date']} to {row['end_date']}",
            "participation": "mandatory" if row["is_mandatory"] == 1 else "optional",
        })
    with open(os.path.join(workspace, "promotion_calendar.json"), "w") as f:
        json.dump(promo_calendar, f, indent=2)

    # --- Scaling workspace files: per-franchisee ad spend reports ---
    for _, fr_row in franchisees_df.iterrows():
        fid = fr_row["franchisee_id"]
        if fid in spend_data:
            df = pd.DataFrame(spend_data[fid])
            filepath = os.path.join(ad_reports_dir, f"{fid}_ad_spend.csv")
            df.to_csv(filepath, index=False)

    # 4. Regional summary (txt) - fixed
    regional_summary = "Regional Franchisee Distribution\n" + "=" * 40 + "\n\n"
    for region in REGIONS:
        count = len(franchisees_df[franchisees_df["region"] == region])
        regional_summary += f"{region}: {count} franchisee(s)\n"
    regional_summary += f"\nTotal active franchisees: {len(franchisees_df)}\n"
    with open(os.path.join(workspace, "regional_summary.txt"), "w") as f:
        f.write(regional_summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    rng = np.random.default_rng(42)
    num_franchisees = SCALE["num_workspace_files"]
    num_rows = SCALE["rows_per_table"]

    # Generate data
    franchisees_df = generate_franchisees(num_franchisees)
    promotions_df = generate_promotions()
    pos_df, _, _ = generate_pos_transactions(franchisees_df, promotions_df, num_rows, rng)
    coupon_df, _ = generate_coupon_redemptions(franchisees_df, promotions_df, num_rows, rng)
    spend_data, _ = generate_ad_spend_data(franchisees_df, promotions_df, rng)

    # Create database
    conn = sqlite3.connect(args.db_path)

    franchisees_df.to_sql("franchisees", conn, if_exists="replace", index=False)
    promotions_df.to_sql("promotions", conn, if_exists="replace", index=False)
    pos_df.to_sql("pos_transactions", conn, if_exists="replace", index=False)
    coupon_df.to_sql("coupon_redemptions", conn, if_exists="replace", index=False)

    conn.commit()
    conn.close()

    # Create workspace files
    create_workspace_files(args.workspace, franchisees_df, promotions_df, spend_data, rng)

    print(f"Database created at {args.db_path}")
    print(f"Tables: franchisees ({len(franchisees_df)}), promotions ({len(promotions_df)}), "
          f"pos_transactions ({len(pos_df)}), coupon_redemptions ({len(coupon_df)})")
    print(f"Workspace created at {args.workspace}")
    print(f"Ad report files: {num_franchisees}")


if __name__ == "__main__":
    main()
