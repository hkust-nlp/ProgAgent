"""
Data generation for billing discrepancy reconciliation task.
Generates a SQLite database and workspace files representing customer
subscription plans, promotional discounts, network usage records,
third-party content provider invoices, and billing statements with
injected discrepancies.
"""

import argparse
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
import yaml
from faker import Faker

# ---------------------------------------------------------------------------
# Scale parameters – only this block differs across v0 … v3
# ---------------------------------------------------------------------------
SCALE = {
    "rows_per_table": 50,       # v0 base; v1=2×, v2=4×, v3=8×
    "num_workspace_files": 10,  # v0 base; v1=+N, v2=+2N, v3=+3N
}

# ---------------------------------------------------------------------------
# Fixed constants (do NOT change across versions)
# ---------------------------------------------------------------------------
BILLING_PERIODS = ["2025-01", "2025-02", "2025-03"]
PROVIDERS = ["StreamFlix", "MusicWave", "CloudGaming", "NewsDigital"]
PLAN_TIERS = ["basic", "standard", "premium", "enterprise"]
BUNDLE_TYPES = ["internet_only", "internet_tv", "internet_tv_phone", "full_bundle"]
PROMO_CODES = ["NEW_CUSTOMER_20", "LOYALTY_10", "SEASONAL_15", "REFERRAL_25"]

TIER_PRICING = {
    "basic":      {"monthly_rate": 29.99, "included_gb": 50,  "overage_per_gb": 10.0},
    "standard":   {"monthly_rate": 49.99, "included_gb": 100, "overage_per_gb": 8.0},
    "premium":    {"monthly_rate": 79.99, "included_gb": 200, "overage_per_gb": 5.0},
    "enterprise": {"monthly_rate": 129.99, "included_gb": 500, "overage_per_gb": 3.0},
}

BUNDLE_DISCOUNTS = {
    "internet_only": 0.0,
    "internet_tv": 0.10,
    "internet_tv_phone": 0.15,
    "full_bundle": 0.20,
}

PROMO_DETAILS = {
    "NEW_CUSTOMER_20": {"discount_pct": 0.20, "duration_months": 3, "applies_to": "base_charge"},
    "LOYALTY_10":      {"discount_pct": 0.10, "duration_months": 6, "applies_to": "base_charge"},
    "SEASONAL_15":     {"discount_pct": 0.15, "duration_months": 2, "applies_to": "total"},
    "REFERRAL_25":     {"discount_pct": 0.25, "duration_months": 1, "applies_to": "base_charge"},
}

ROOT_CAUSES = [
    "EXPIRED_PROMO",
    "MISSING_BUNDLE_DISCOUNT",
    "USAGE_OVERCHARGE",
    "PROVIDER_MISMATCH",
    "PLAN_RATE_ERROR",
]

SEED = 42


def seed_all():
    random.seed(SEED)
    np.random.seed(SEED)


def create_tables(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            full_name TEXT,
            email TEXT,
            phone TEXT,
            account_status TEXT,
            signup_date TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscription_plans (
            plan_id TEXT PRIMARY KEY,
            customer_id TEXT,
            plan_name TEXT,
            tier TEXT,
            bundle_type TEXT,
            start_date TEXT,
            end_date TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS discount_eligibility (
            log_id TEXT PRIMARY KEY,
            customer_id TEXT,
            promo_code TEXT,
            eligible_from TEXT,
            eligible_to TEXT,
            status TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS usage_records (
            record_id TEXT PRIMARY KEY,
            customer_id TEXT,
            service_type TEXT,
            usage_gb REAL,
            billing_period TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS provider_invoices (
            invoice_id TEXT PRIMARY KEY,
            provider_name TEXT,
            customer_id TEXT,
            service_description TEXT,
            invoice_amount REAL,
            billing_period TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        )
    """)
    conn.commit()


def generate_customers(fake, n):
    customers = []
    for i in range(n):
        cid = f"CUST-{i+1:05d}"
        customers.append({
            "customer_id": cid,
            "full_name": fake.name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "account_status": random.choice(["active", "active", "active", "suspended"]),
            "signup_date": fake.date_between(start_date="-3y", end_date="-6m").isoformat(),
        })
    return customers


def generate_subscriptions(customers):
    plans = []
    for c in customers:
        tier = random.choice(PLAN_TIERS)
        bundle = random.choice(BUNDLE_TYPES)
        plan_name = f"{tier.capitalize()} {bundle.replace('_', ' ').title()}"
        plans.append({
            "plan_id": f"PLN-{c['customer_id'].split('-')[1]}",
            "customer_id": c["customer_id"],
            "plan_name": plan_name,
            "tier": tier,
            "bundle_type": bundle,
            "start_date": c["signup_date"],
            "end_date": "2026-12-31",
        })
    return plans


def generate_discount_eligibility(customers, fake):
    logs = []
    log_idx = 0
    for c in customers:
        # ~60% of customers have at least one promo
        if random.random() < 0.6:
            num_promos = random.randint(1, 2)
            chosen = random.sample(PROMO_CODES, min(num_promos, len(PROMO_CODES)))
            for promo in chosen:
                log_idx += 1
                detail = PROMO_DETAILS[promo]
                elig_start = fake.date_between(start_date="-12m", end_date="-1m")
                from datetime import timedelta
                elig_end = elig_start + timedelta(days=30 * detail["duration_months"])
                # Some promos are expired, some active
                status = "active" if elig_end.isoformat() >= "2025-03-01" else "expired"
                logs.append({
                    "log_id": f"DISC-{log_idx:06d}",
                    "customer_id": c["customer_id"],
                    "promo_code": promo,
                    "eligible_from": elig_start.isoformat(),
                    "eligible_to": elig_end.isoformat(),
                    "status": status,
                })
    return logs


def generate_usage_records(customers):
    records = []
    rec_idx = 0
    for c in customers:
        for period in BILLING_PERIODS:
            # Each customer has 1-3 service types of usage per period
            services = random.sample(["internet", "streaming", "voip", "cloud"],
                                     k=random.randint(1, 3))
            for svc in services:
                rec_idx += 1
                usage = round(random.uniform(5, 350), 2)
                records.append({
                    "record_id": f"USG-{rec_idx:07d}",
                    "customer_id": c["customer_id"],
                    "service_type": svc,
                    "usage_gb": usage,
                    "billing_period": period,
                })
    return records


def generate_provider_invoices(customers):
    invoices = []
    inv_idx = 0
    for c in customers:
        # Each customer subscribes to 1-3 content providers
        num_providers = random.randint(1, 3)
        chosen_providers = random.sample(PROVIDERS, num_providers)
        for provider in chosen_providers:
            for period in BILLING_PERIODS:
                inv_idx += 1
                amount = round(random.uniform(5.0, 35.0), 2)
                invoices.append({
                    "invoice_id": f"INV-{inv_idx:07d}",
                    "provider_name": provider,
                    "customer_id": c["customer_id"],
                    "service_description": f"{provider} subscription service",
                    "invoice_amount": amount,
                    "billing_period": period,
                })
    return invoices


def compute_correct_billing(customer, plan, discounts, usage_recs, provider_invs, period):
    """Compute the correct billing for a customer in a given period."""
    tier = plan["tier"]
    bundle = plan["bundle_type"]
    pricing = TIER_PRICING[tier]

    # Base charge
    base_charge = pricing["monthly_rate"]

    # Bundle discount (applied to base charge)
    bundle_disc_pct = BUNDLE_DISCOUNTS[bundle]
    bundle_discount = round(base_charge * bundle_disc_pct, 2)

    # Promo discount
    promo_discount = 0.0
    active_promo = None
    for d in discounts:
        if d["eligible_from"] <= f"{period}-28" and d["eligible_to"] >= f"{period}-01" and d["status"] == "active":
            promo = PROMO_DETAILS[d["promo_code"]]
            if promo["applies_to"] == "base_charge":
                disc = round(base_charge * promo["discount_pct"], 2)
            else:
                disc = 0.0  # computed later on total
            if disc > promo_discount:
                promo_discount = disc
                active_promo = d

    # Usage charge: sum of overage across all service types
    total_usage_gb = sum(u["usage_gb"] for u in usage_recs if u["billing_period"] == period)
    overage = max(0, total_usage_gb - pricing["included_gb"])
    usage_charge = round(overage * pricing["overage_per_gb"], 2)

    # Content charge: sum of provider invoices for this period
    content_charge = round(sum(inv["invoice_amount"] for inv in provider_invs
                               if inv["billing_period"] == period), 2)

    # Subtotal before total-level promo
    subtotal = round(base_charge - bundle_discount - promo_discount + usage_charge + content_charge, 2)

    # If active promo applies to total
    total_promo_discount = 0.0
    if active_promo:
        promo = PROMO_DETAILS[active_promo["promo_code"]]
        if promo["applies_to"] == "total":
            total_promo_discount = round(subtotal * promo["discount_pct"], 2)
            promo_discount = total_promo_discount

    total_billed = round(base_charge - bundle_discount - promo_discount + usage_charge + content_charge, 2)

    return {
        "base_charge": base_charge,
        "bundle_discount": bundle_discount,
        "promo_discount": promo_discount,
        "usage_charge": usage_charge,
        "content_charge": content_charge,
        "total_billed": total_billed,
        "active_promo_code": active_promo["promo_code"] if active_promo else None,
    }


def inject_discrepancies(billing_records, customers, plans, discounts_by_cust, rng):
    """Inject billing discrepancies into a fraction of records.
    Returns list of (record, discrepancy_info | None)."""
    results = []
    num_records = len(billing_records)
    # ~25% of records get a discrepancy
    num_discrepant = max(5, int(num_records * 0.25))
    discrepant_indices = set(rng.choice(num_records, size=num_discrepant, replace=False))

    for idx, rec in enumerate(billing_records):
        if idx not in discrepant_indices:
            results.append((rec, None))
            continue

        cid = rec["customer_id"]
        plan = next(p for p in plans if p["customer_id"] == cid)
        tier = plan["tier"]
        bundle = plan["bundle_type"]

        # Pick a root cause
        root_cause = rng.choice(ROOT_CAUSES)

        original = rec.copy()
        disc_info = {"root_cause": root_cause, "original": original.copy()}

        if root_cause == "EXPIRED_PROMO":
            # Apply a fake promo discount even when none should be active
            fake_disc = round(rec["base_charge"] * 0.15, 2)
            rec["promo_discount"] = round(rec["promo_discount"] + fake_disc, 2)
            rec["total_billed"] = round(rec["total_billed"] - fake_disc, 2)
            disc_info["description"] = "Expired promotional discount still applied"

        elif root_cause == "MISSING_BUNDLE_DISCOUNT":
            # Remove the bundle discount
            if rec["bundle_discount"] > 0:
                lost = rec["bundle_discount"]
                rec["bundle_discount"] = 0.0
                rec["total_billed"] = round(rec["total_billed"] + lost, 2)
                disc_info["description"] = "Bundle discount not applied"
            else:
                # If no bundle discount to remove, apply a phantom one
                phantom = round(rec["base_charge"] * 0.10, 2)
                rec["bundle_discount"] = phantom
                rec["total_billed"] = round(rec["total_billed"] - phantom, 2)
                disc_info["description"] = "Incorrect bundle discount applied"

        elif root_cause == "USAGE_OVERCHARGE":
            # Inflate usage charge by using a higher rate
            if rec["usage_charge"] > 0:
                rec["usage_charge"] = round(rec["usage_charge"] * 1.5, 2)
                delta = round(rec["usage_charge"] - original["usage_charge"], 2)
                rec["total_billed"] = round(original["total_billed"] + delta, 2)
            else:
                # Add a spurious usage charge
                rec["usage_charge"] = round(rng.uniform(10, 50), 2)
                rec["total_billed"] = round(rec["total_billed"] + rec["usage_charge"], 2)
            disc_info["description"] = "Usage rated at incorrect tier rate"

        elif root_cause == "PROVIDER_MISMATCH":
            # Alter content charge
            if rec["content_charge"] > 0:
                inflation = round(rng.uniform(5, 20), 2)
                rec["content_charge"] = round(rec["content_charge"] + inflation, 2)
                rec["total_billed"] = round(original["total_billed"] + inflation, 2)
            else:
                spurious = round(rng.uniform(8, 25), 2)
                rec["content_charge"] = spurious
                rec["total_billed"] = round(rec["total_billed"] + spurious, 2)
            disc_info["description"] = "Third-party content charge does not match provider invoice"

        elif root_cause == "PLAN_RATE_ERROR":
            # Use wrong base rate
            wrong_tiers = [t for t in PLAN_TIERS if t != tier]
            wrong_tier = rng.choice(wrong_tiers)
            wrong_rate = TIER_PRICING[wrong_tier]["monthly_rate"]
            delta = round(wrong_rate - rec["base_charge"], 2)
            rec["base_charge"] = wrong_rate
            rec["total_billed"] = round(original["total_billed"] + delta, 2)
            disc_info["description"] = "Base charge does not match plan tier rate"

        results.append((rec, disc_info))

    return results


def build_billing_records(customers, plans, discounts, usage_records, provider_invoices):
    """Build billing records for all customers across all periods."""
    discounts_by_cust = {}
    for d in discounts:
        discounts_by_cust.setdefault(d["customer_id"], []).append(d)

    usage_by_cust = {}
    for u in usage_records:
        usage_by_cust.setdefault(u["customer_id"], []).append(u)

    invs_by_cust = {}
    for inv in provider_invoices:
        invs_by_cust.setdefault(inv["customer_id"], []).append(inv)

    records = []
    for c in customers:
        cid = c["customer_id"]
        plan = next(p for p in plans if p["customer_id"] == cid)
        cust_discounts = discounts_by_cust.get(cid, [])
        cust_usage = usage_by_cust.get(cid, [])
        cust_invs = invs_by_cust.get(cid, [])

        for period in BILLING_PERIODS:
            billing = compute_correct_billing(c, plan, cust_discounts, cust_usage, cust_invs, period)
            billing["customer_id"] = cid
            billing["billing_period"] = period
            records.append(billing)

    return records, discounts_by_cust


def write_workspace_files(workspace, billing_with_disc, customers, plans, discounts,
                          usage_records, provider_invoices, num_scalable_files):
    """Write all workspace files."""
    os.makedirs(workspace, exist_ok=True)

    # ---- Fixed policy/config files ----

    # 1. Pricing tiers config
    pricing_config = {}
    for tier, info in TIER_PRICING.items():
        pricing_config[tier] = {
            "monthly_rate": info["monthly_rate"],
            "included_data_gb": info["included_gb"],
            "overage_rate_per_gb": info["overage_per_gb"],
        }
    with open(os.path.join(workspace, "pricing_tiers.yaml"), "w") as f:
        yaml.dump({"pricing_tiers": pricing_config}, f, default_flow_style=False, sort_keys=False)

    # 2. Bundle discount rules
    bundle_rules = {}
    for bt, disc in BUNDLE_DISCOUNTS.items():
        bundle_rules[bt] = {
            "discount_percentage": disc * 100,
            "applies_to": "base_charge",
            "description": f"{int(disc*100)}% discount on base charge for {bt.replace('_', ' ')} bundle",
        }
    with open(os.path.join(workspace, "bundle_discount_rules.json"), "w") as f:
        json.dump({"bundle_discount_rules": bundle_rules}, f, indent=2)

    # 3. Promo catalog
    promo_lines = ["# Promotional Offer Catalog\n"]
    promo_lines.append("This document describes all active and historical promotional offers.\n")
    for code, detail in PROMO_DETAILS.items():
        promo_lines.append(f"## {code}\n")
        promo_lines.append(f"Discount: {int(detail['discount_pct']*100)}% off {detail['applies_to']}")
        promo_lines.append(f"Duration: {detail['duration_months']} months from enrollment date")
        promo_lines.append(f"Applies to: {detail['applies_to']}\n")
    with open(os.path.join(workspace, "promo_catalog.md"), "w") as f:
        f.write("\n".join(promo_lines))

    # 4. Root cause category definitions
    rc_lines = [
        "ROOT CAUSE CATEGORY DEFINITIONS",
        "================================\n",
        "EXPIRED_PROMO: A promotional discount was applied to a billing period",
        "  after the promotion's eligibility window had ended. The discount",
        "  amount should be reversed.\n",
        "MISSING_BUNDLE_DISCOUNT: The customer's bundle discount was either",
        "  not applied when it should have been, or an incorrect bundle",
        "  discount was applied. Adjustment corrects the bundle discount.\n",
        "USAGE_OVERCHARGE: Network usage was rated at an incorrect per-GB",
        "  rate that does not match the customer's subscription tier.",
        "  The usage charge should be recalculated at the correct rate.\n",
        "PROVIDER_MISMATCH: The amount billed to the customer for third-party",
        "  content services does not match the invoice amount from the",
        "  content provider. The difference must be reconciled.\n",
        "PLAN_RATE_ERROR: The base monthly charge does not match the rate",
        "  defined for the customer's subscription tier. The base charge",
        "  should be corrected to the tier-appropriate rate.\n",
    ]
    with open(os.path.join(workspace, "root_cause_definitions.txt"), "w") as f:
        f.write("\n".join(rc_lines))

    # ---- Scalable data files ----
    # Distribute billing records across files with mixed formats
    all_records = []
    discrepancy_map = {}
    for rec, disc_info in billing_with_disc:
        all_records.append(rec)
        if disc_info is not None:
            key = (rec["customer_id"], rec["billing_period"])
            discrepancy_map[key] = disc_info

    # Determine format distribution: 40% CSV, 30% JSON, 20% TXT, 10% YAML (min 1 each)
    n = num_scalable_files
    n_csv = max(1, int(n * 0.4))
    n_json = max(1, int(n * 0.3))
    n_txt = max(1, int(n * 0.2))
    n_yaml = max(1, n - n_csv - n_json - n_txt)

    # Shuffle records deterministically and split into batches
    rng = np.random.RandomState(SEED)
    indices = list(range(len(all_records)))
    rng.shuffle(indices)

    batch_size = max(1, len(indices) // n)
    batches = []
    for i in range(n):
        start = i * batch_size
        if i == n - 1:
            batch = [all_records[indices[j]] for j in range(start, len(indices))]
        else:
            batch = [all_records[indices[j]] for j in range(start, start + batch_size)]
        batches.append(batch)

    file_idx = 0

    # CSV files
    for i in range(n_csv):
        fname = f"billing_batch_{file_idx+1:03d}.csv"
        df = pd.DataFrame(batches[file_idx])
        cols = ["customer_id", "billing_period", "base_charge", "bundle_discount",
                "promo_discount", "usage_charge", "content_charge", "total_billed"]
        for col in cols:
            if col not in df.columns:
                df[col] = 0.0
        df = df[cols]
        df.to_csv(os.path.join(workspace, fname), index=False)
        file_idx += 1

    # JSON files
    for i in range(n_json):
        fname = f"billing_batch_{file_idx+1:03d}.json"
        batch = batches[file_idx]
        output = []
        for r in batch:
            output.append({
                "customer_id": r["customer_id"],
                "billing_period": r["billing_period"],
                "base_charge": r["base_charge"],
                "bundle_discount": r["bundle_discount"],
                "promo_discount": r["promo_discount"],
                "usage_charge": r["usage_charge"],
                "content_charge": r["content_charge"],
                "total_billed": r["total_billed"],
            })
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump({"billing_records": output}, f, indent=2)
        file_idx += 1

    # TXT files (tab-separated)
    for i in range(n_txt):
        fname = f"billing_batch_{file_idx+1:03d}.txt"
        batch = batches[file_idx]
        lines = ["customer_id\tbilling_period\tbase_charge\tbundle_discount\tpromo_discount\tusage_charge\tcontent_charge\ttotal_billed"]
        for r in batch:
            lines.append(f"{r['customer_id']}\t{r['billing_period']}\t{r['base_charge']:.2f}\t{r['bundle_discount']:.2f}\t{r['promo_discount']:.2f}\t{r['usage_charge']:.2f}\t{r['content_charge']:.2f}\t{r['total_billed']:.2f}")
        with open(os.path.join(workspace, fname), "w") as f:
            f.write("\n".join(lines) + "\n")
        file_idx += 1

    # YAML files
    for i in range(n_yaml):
        fname = f"billing_batch_{file_idx+1:03d}.yaml"
        batch = batches[file_idx]
        output = []
        for r in batch:
            output.append({
                "customer_id": r["customer_id"],
                "billing_period": r["billing_period"],
                "base_charge": float(r["base_charge"]),
                "bundle_discount": float(r["bundle_discount"]),
                "promo_discount": float(r["promo_discount"]),
                "usage_charge": float(r["usage_charge"]),
                "content_charge": float(r["content_charge"]),
                "total_billed": float(r["total_billed"]),
            })
        with open(os.path.join(workspace, fname), "w") as f:
            yaml.dump({"billing_records": output}, f, default_flow_style=False, sort_keys=False)
        file_idx += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    seed_all()
    fake = Faker()
    Faker.seed(SEED)

    n_customers = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # Generate data
    customers = generate_customers(fake, n_customers)
    plans = generate_subscriptions(customers)
    discounts = generate_discount_eligibility(customers, fake)
    usage_records = generate_usage_records(customers)
    provider_invoices = generate_provider_invoices(customers)

    # Build billing records (correct values first)
    billing_records, discounts_by_cust = build_billing_records(
        customers, plans, discounts, usage_records, provider_invoices
    )

    # Inject discrepancies
    rng = np.random.RandomState(SEED + 1)
    billing_with_disc = inject_discrepancies(billing_records, customers, plans, discounts_by_cust, rng)

    # Create database
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    pd.DataFrame(customers).to_sql("customers", conn, if_exists="replace", index=False)
    pd.DataFrame(plans).to_sql("subscription_plans", conn, if_exists="replace", index=False)
    pd.DataFrame(discounts).to_sql("discount_eligibility", conn, if_exists="replace", index=False)
    pd.DataFrame(usage_records).to_sql("usage_records", conn, if_exists="replace", index=False)
    pd.DataFrame(provider_invoices).to_sql("provider_invoices", conn, if_exists="replace", index=False)

    conn.commit()
    conn.close()

    # Write workspace files
    write_workspace_files(
        args.workspace, billing_with_disc, customers, plans,
        discounts, usage_records, provider_invoices, n_files
    )

    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace} with {n_files} scalable data files + 4 policy files")
    print(f"Total customers: {n_customers}")
    print(f"Total billing records: {len(billing_records)}")
    discrepancy_count = sum(1 for _, d in billing_with_disc if d is not None)
    print(f"Discrepancies injected: {discrepancy_count}")


if __name__ == "__main__":
    main()
