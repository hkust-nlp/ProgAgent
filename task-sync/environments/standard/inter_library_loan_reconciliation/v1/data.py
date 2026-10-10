"""
Data generation for Inter-Library Loan Overdue Reconciliation task.
Generates database tables and workspace files for the ILL reconciliation environment.
"""

import argparse
import json
import os
import sqlite3
import random
import yaml
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

# ── Scale parameters (v0 base) ──────────────────────────────────────────
SCALE = {
    "rows_per_table": 100,       # v1 = 2x base
    "num_workspace_files": 16,   # v1 = base + N (N=8)
}

# ── Seeds ────────────────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

REFERENCE_DATE = datetime(2026, 4, 15)

CATEGORIES = [
    "Science", "Engineering", "History", "Literature", "Philosophy",
    "Mathematics", "Medicine", "Law", "Art", "Music", "Economics",
    "Computer Science", "Psychology", "Sociology", "Biology",
]

CARRIERS = ["FedEx", "UPS", "USPS", "DHL", "Library Courier Network"]
DEPARTMENTS = [
    "Physics", "Chemistry", "Biology", "Mathematics", "Computer Science",
    "English", "History", "Philosophy", "Economics", "Psychology",
    "Sociology", "Art", "Music", "Engineering", "Law", "Medicine",
    "Library Science", "Education", "Political Science", "Linguistics",
]
PATRON_TYPES = ["faculty", "graduate_student", "undergraduate", "staff", "visiting_researcher"]
CONTACT_METHODS = ["email", "phone", "letter", "in_person", "text_message"]
OUTCOMES = ["no_response", "acknowledged", "promised_return", "disputed", "payment_arranged", "unreachable"]
CONDITION_GRADES = ["A", "B", "C", "D", "F"]
STATES = [
    "CA", "NY", "TX", "IL", "PA", "OH", "FL", "MA", "MI", "WA",
    "VA", "NC", "GA", "MN", "CO", "OR", "AZ", "MD", "WI", "MO",
]


def create_tables(conn):
    """Create all database tables."""
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS partner_institutions (
            institution_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            contact_email TEXT NOT NULL,
            default_loan_period_days INTEGER NOT NULL,
            default_fine_per_day REAL NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS books (
            book_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            isbn TEXT NOT NULL,
            category TEXT NOT NULL,
            base_replacement_cost REAL NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS patrons (
            patron_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            department TEXT NOT NULL,
            patron_type TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            loan_id TEXT PRIMARY KEY,
            book_id TEXT NOT NULL,
            patron_id TEXT NOT NULL,
            partner_institution_id TEXT NOT NULL,
            loan_date TEXT NOT NULL,
            due_date TEXT NOT NULL,
            return_date TEXT,
            status TEXT NOT NULL,
            FOREIGN KEY (book_id) REFERENCES books(book_id),
            FOREIGN KEY (patron_id) REFERENCES patrons(patron_id),
            FOREIGN KEY (partner_institution_id) REFERENCES partner_institutions(institution_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS shipment_tracking (
            shipment_id TEXT PRIMARY KEY,
            loan_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            carrier TEXT NOT NULL,
            tracking_number TEXT NOT NULL,
            ship_date TEXT NOT NULL,
            estimated_delivery TEXT NOT NULL,
            actual_delivery TEXT,
            status TEXT NOT NULL,
            FOREIGN KEY (loan_id) REFERENCES loans(loan_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS patron_contacts (
            contact_id TEXT PRIMARY KEY,
            patron_id TEXT NOT NULL,
            loan_id TEXT NOT NULL,
            contact_date TEXT NOT NULL,
            contact_method TEXT NOT NULL,
            outcome TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (patron_id) REFERENCES patrons(patron_id),
            FOREIGN KEY (loan_id) REFERENCES loans(loan_id)
        )
    """)
    conn.commit()


def generate_institutions(conn, n):
    """Generate partner institution records."""
    rows = []
    used_names = set()
    for i in range(n):
        while True:
            name = f"{fake.last_name()} {random.choice(['University', 'College', 'Institute of Technology', 'State University', 'Community College'])} Library"
            if name not in used_names:
                used_names.add(name)
                break
        inst_id = f"INST-{i+1:04d}"
        city = fake.city()
        state = random.choice(STATES)
        email = f"ill@{name.lower().replace(' ', '').replace('.', '')}_{i}.edu"
        loan_period = random.choice([21, 28, 30, 42, 60, 90])
        fine_per_day = round(random.choice([0.10, 0.15, 0.20, 0.25, 0.30, 0.50]), 2)
        rows.append((inst_id, name, city, state, email, loan_period, fine_per_day))
    conn.executemany(
        "INSERT INTO partner_institutions VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_books(conn, n):
    """Generate book records."""
    rows = []
    for i in range(n):
        book_id = f"BK-{i+1:04d}"
        title = fake.sentence(nb_words=random.randint(3, 8)).rstrip(".")
        author = fake.name()
        isbn = fake.isbn13()
        category = random.choice(CATEGORIES)
        cost = round(random.uniform(15.0, 250.0), 2)
        rows.append((book_id, title, author, isbn, category, cost))
    conn.executemany("INSERT INTO books VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_patrons(conn, n):
    """Generate patron records."""
    rows = []
    for i in range(n):
        patron_id = f"PAT-{i+1:04d}"
        name = fake.name()
        email = fake.email()
        phone = fake.phone_number()
        dept = random.choice(DEPARTMENTS)
        ptype = random.choice(PATRON_TYPES)
        rows.append((patron_id, name, email, phone, dept, ptype))
    conn.executemany("INSERT INTO patrons VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_loans(conn, n, institutions, books, patrons):
    """Generate loan records with a mix of statuses."""
    rows = []
    n_inst = len(institutions)
    n_books = len(books)
    n_patrons = len(patrons)

    for i in range(n):
        loan_id = f"ILL-{i+1:04d}"
        book_id = books[i % n_books][0]
        patron_id = patrons[i % n_patrons][0]
        inst_id = institutions[i % n_inst][0]

        # Generate loan dates spread over the past year
        days_ago = random.randint(10, 365)
        loan_date = REFERENCE_DATE - timedelta(days=days_ago)
        inst_loan_period = institutions[i % n_inst][5]
        due_date = loan_date + timedelta(days=inst_loan_period)

        # Determine status
        rand_val = random.random()
        if rand_val < 0.35:
            # Returned on time or late
            return_days_after_due = random.randint(-10, 20)
            return_date = due_date + timedelta(days=return_days_after_due)
            if return_date > REFERENCE_DATE:
                return_date = REFERENCE_DATE - timedelta(days=random.randint(1, 5))
            status = "returned"
            return_date_str = return_date.strftime("%Y-%m-%d")
        elif rand_val < 0.65 and due_date < REFERENCE_DATE:
            # Overdue - not returned
            status = "overdue"
            return_date_str = None
        elif rand_val < 0.78 and due_date < REFERENCE_DATE - timedelta(days=60):
            # Lost
            status = "lost"
            return_date_str = None
        elif due_date >= REFERENCE_DATE:
            # Active - not yet due
            status = "active"
            return_date_str = None
        else:
            # Additional overdue to ensure enough
            if due_date < REFERENCE_DATE:
                status = "overdue"
                return_date_str = None
            else:
                status = "active"
                return_date_str = None

        rows.append((
            loan_id, book_id, patron_id, inst_id,
            loan_date.strftime("%Y-%m-%d"),
            due_date.strftime("%Y-%m-%d"),
            return_date_str,
            status,
        ))

    conn.executemany("INSERT INTO loans VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_shipments(conn, loans, n_min):
    """Generate shipment tracking records."""
    rows = []
    shipment_idx = 0

    for loan in loans:
        loan_id = loan[0]
        loan_date_str = loan[4]
        status = loan[7]
        return_date_str = loan[6]
        loan_date = datetime.strptime(loan_date_str, "%Y-%m-%d")

        # Outbound shipment (always exists)
        shipment_idx += 1
        sid = f"SHP-{shipment_idx:05d}"
        carrier = random.choice(CARRIERS)
        tracking = fake.bothify(text="??########")
        ship_date = loan_date - timedelta(days=random.randint(1, 5))
        est_delivery = ship_date + timedelta(days=random.randint(2, 7))
        actual_delivery = est_delivery + timedelta(days=random.randint(-1, 3))
        rows.append((
            sid, loan_id, "outbound", carrier, tracking,
            ship_date.strftime("%Y-%m-%d"),
            est_delivery.strftime("%Y-%m-%d"),
            actual_delivery.strftime("%Y-%m-%d"),
            "delivered",
        ))

        # Return shipment (only for returned loans)
        if status == "returned" and return_date_str:
            shipment_idx += 1
            sid = f"SHP-{shipment_idx:05d}"
            carrier = random.choice(CARRIERS)
            tracking = fake.bothify(text="??########")
            ret_date = datetime.strptime(return_date_str, "%Y-%m-%d")
            ship_date_ret = ret_date - timedelta(days=random.randint(2, 5))
            est_del_ret = ship_date_ret + timedelta(days=random.randint(2, 7))
            rows.append((
                sid, loan_id, "return", carrier, tracking,
                ship_date_ret.strftime("%Y-%m-%d"),
                est_del_ret.strftime("%Y-%m-%d"),
                ret_date.strftime("%Y-%m-%d"),
                "delivered",
            ))
        elif status == "overdue":
            # Some overdue loans may have a pending return shipment
            if random.random() < 0.2:
                shipment_idx += 1
                sid = f"SHP-{shipment_idx:05d}"
                carrier = random.choice(CARRIERS)
                tracking = fake.bothify(text="??########")
                ship_date_ret = REFERENCE_DATE - timedelta(days=random.randint(1, 10))
                est_del_ret = ship_date_ret + timedelta(days=random.randint(3, 7))
                rows.append((
                    sid, loan_id, "return", carrier, tracking,
                    ship_date_ret.strftime("%Y-%m-%d"),
                    est_del_ret.strftime("%Y-%m-%d"),
                    None,
                    "in_transit",
                ))

    # Pad to minimum if needed
    while len(rows) < n_min:
        shipment_idx += 1
        sid = f"SHP-{shipment_idx:05d}"
        loan = random.choice(loans)
        carrier = random.choice(CARRIERS)
        tracking = fake.bothify(text="??########")
        base_date = datetime.strptime(loan[4], "%Y-%m-%d")
        ship_date = base_date - timedelta(days=random.randint(1, 5))
        est_delivery = ship_date + timedelta(days=random.randint(2, 7))
        rows.append((
            sid, loan[0], "outbound", carrier, tracking,
            ship_date.strftime("%Y-%m-%d"),
            est_delivery.strftime("%Y-%m-%d"),
            est_delivery.strftime("%Y-%m-%d"),
            "delivered",
        ))

    conn.executemany("INSERT INTO shipment_tracking VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_contacts(conn, loans, patrons, n_min):
    """Generate patron contact log entries."""
    rows = []
    contact_idx = 0

    # Generate contacts for overdue and lost loans
    overdue_loans = [l for l in loans if l[7] in ("overdue", "lost")]
    for loan in overdue_loans:
        loan_id = loan[0]
        patron_id = loan[2]
        due_date = datetime.strptime(loan[5], "%Y-%m-%d")

        # 1-3 contact attempts per overdue loan
        n_contacts = random.randint(1, 3)
        for j in range(n_contacts):
            contact_idx += 1
            cid = f"CON-{contact_idx:05d}"
            contact_date = due_date + timedelta(days=random.randint(7 * j + 1, 7 * (j + 1) + 14))
            if contact_date > REFERENCE_DATE:
                contact_date = REFERENCE_DATE - timedelta(days=random.randint(0, 5))
            method = random.choice(CONTACT_METHODS)
            outcome = random.choice(OUTCOMES)
            notes = fake.sentence(nb_words=random.randint(5, 15))
            rows.append((
                cid, patron_id, loan_id,
                contact_date.strftime("%Y-%m-%d"),
                method, outcome, notes,
            ))

    # Pad to minimum
    while len(rows) < n_min:
        contact_idx += 1
        cid = f"CON-{contact_idx:05d}"
        loan = random.choice(loans)
        patron_id = loan[2]
        due_date = datetime.strptime(loan[5], "%Y-%m-%d")
        contact_date = due_date + timedelta(days=random.randint(1, 30))
        if contact_date > REFERENCE_DATE:
            contact_date = REFERENCE_DATE - timedelta(days=random.randint(0, 10))
        method = random.choice(CONTACT_METHODS)
        outcome = random.choice(OUTCOMES)
        notes = fake.sentence(nb_words=random.randint(5, 15))
        rows.append((
            cid, patron_id, loan[0],
            contact_date.strftime("%Y-%m-%d"),
            method, outcome, notes,
        ))

    conn.executemany("INSERT INTO patron_contacts VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


# ── Workspace file generation ────────────────────────────────────────────

def generate_condition_reports(workspace, books, num_files):
    """Generate condition report CSV batches splitting all books across files."""
    books_per_file = max(1, len(books) // num_files)
    for i in range(num_files):
        start = i * books_per_file
        end = start + books_per_file if i < num_files - 1 else len(books)
        batch_books = books[start:end]
        rows = []
        for b in batch_books:
            grade = random.choice(CONDITION_GRADES)
            damage = ""
            if grade in ("C", "D", "F"):
                damage = random.choice([
                    "Water damage on cover",
                    "Spine cracked",
                    "Pages torn",
                    "Heavy highlighting throughout",
                    "Missing dust jacket",
                    "Binding loose",
                    "Mold spotted on edges",
                    "Cover detached",
                ])
            assessment_date = (REFERENCE_DATE - timedelta(days=random.randint(30, 180))).strftime("%Y-%m-%d")
            rows.append({
                "book_id": b[0],
                "condition_grade": grade,
                "damage_description": damage,
                "assessment_date": assessment_date,
            })
        df = pd.DataFrame(rows)
        df.to_csv(os.path.join(workspace, f"condition_report_batch_{i+1}.csv"), index=False)


def generate_insurance_records(workspace, loans, num_files):
    """Generate insurance record JSON files for loans."""
    # Only overdue/lost/active loans get insurance records
    eligible = [l for l in loans if l[7] in ("overdue", "lost", "active")]
    # Also add some returned ones for realism
    returned = [l for l in loans if l[7] == "returned"]
    eligible.extend(random.sample(returned, min(len(returned), len(eligible) // 2)))
    random.shuffle(eligible)

    per_file = max(1, len(eligible) // num_files)
    for i in range(num_files):
        start = i * per_file
        end = start + per_file if i < num_files - 1 else len(eligible)
        batch = eligible[start:end]
        records = []
        for loan in batch:
            coverage = round(random.uniform(0, 150.0), 2) if random.random() < 0.6 else 0.0
            deductible = round(random.uniform(5.0, 25.0), 2) if coverage > 0 else 0.0
            policy_status = random.choice(["active", "expired"]) if coverage > 0 else "none"
            records.append({
                "loan_id": loan[0],
                "insurance_provider": random.choice(["LibGuard Insurance", "BookShield Corp", "AcademicCover Ltd", "InterLib Mutual"]),
                "coverage_amount": coverage,
                "deductible": deductible,
                "policy_status": policy_status,
            })
        filepath = os.path.join(workspace, f"insurance_record_{i+1}.json")
        with open(filepath, "w") as f:
            json.dump(records, f, indent=2)


def generate_patron_comm_files(workspace, patrons, num_files):
    """Generate patron communication preference text files."""
    per_file = max(1, len(patrons) // num_files)
    for i in range(num_files):
        start = i * per_file
        end = start + per_file if i < num_files - 1 else len(patrons)
        batch = patrons[start:end]
        lines = []
        lines.append("PATRON COMMUNICATION PREFERENCES")
        lines.append("=" * 50)
        lines.append(f"Generated: {REFERENCE_DATE.strftime('%Y-%m-%d')}")
        lines.append("")
        for p in batch:
            patron_id = p[0]
            pref_method = random.choice(CONTACT_METHODS)
            do_not_contact = "yes" if random.random() < 0.05 else "no"
            max_contacts_per_month = random.randint(1, 5)
            notes = random.choice([
                "Prefers morning contact.",
                "Available only during business hours.",
                "On sabbatical until June 2026.",
                "Responsive to follow-ups.",
                "Has payment plan in place.",
                "Frequently travels internationally.",
                "Department head, handle with discretion.",
                "",
            ])
            lines.append(f"Patron ID: {patron_id}")
            lines.append(f"  Preferred Method: {pref_method}")
            lines.append(f"  Do Not Contact: {do_not_contact}")
            lines.append(f"  Max Contacts/Month: {max_contacts_per_month}")
            if notes:
                lines.append(f"  Notes: {notes}")
            lines.append("")

        filepath = os.path.join(workspace, f"patron_comm_prefs_{i+1}.txt")
        with open(filepath, "w") as f:
            f.write("\n".join(lines))


def generate_fine_policy(workspace):
    """Generate the fine calculation policy YAML file (fixed, not scaled)."""
    policy = {
        "report_as_of_date": "2026-04-15",
        "default_grace_period_days": 7,
        "fine_tiers": [
            {"min_days": 1, "max_days": 14, "rate_per_day": 0.25},
            {"min_days": 15, "max_days": 30, "rate_per_day": 0.50},
            {"min_days": 31, "max_days": 60, "rate_per_day": 1.00},
            {"min_days": 61, "max_days": 90, "rate_per_day": 1.50},
            {"min_days": 91, "max_days": 9999, "rate_per_day": 2.00},
        ],
        "default_max_fine_cap": 75.00,
        "replacement_threshold_days": 90,
        "condition_multipliers": {
            "A": 1.0,
            "B": 1.1,
            "C": 1.25,
            "D": 1.5,
            "F": 2.0,
        },
        "insurance_deduction_policy": "If the loan has an active insurance policy, deduct coverage_amount minus deductible from gross replacement cost. Net replacement cost cannot be negative.",
    }
    filepath = os.path.join(workspace, "fine_policy.yaml")
    with open(filepath, "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)


def generate_institution_agreements(workspace, institutions):
    """Generate institution-specific agreement overrides (fixed file)."""
    agreements = {}
    # About 40% of institutions get custom overrides
    override_indices = random.sample(range(len(institutions)), max(1, len(institutions) * 2 // 5))
    for idx in override_indices:
        inst = institutions[idx]
        inst_id = inst[0]
        overrides = {}
        if random.random() < 0.7:
            overrides["grace_period_days"] = random.choice([0, 3, 5, 10, 14])
        if random.random() < 0.5:
            overrides["max_fine_cap"] = round(random.choice([30.0, 50.0, 100.0, 150.0]), 2)
        if random.random() < 0.4:
            overrides["fine_rate_multiplier"] = round(random.choice([0.5, 0.75, 1.25, 1.5]), 2)
        if overrides:
            agreements[inst_id] = overrides

    filepath = os.path.join(workspace, "institution_agreements.json")
    with open(filepath, "w") as f:
        json.dump(agreements, f, indent=2)


def generate_recovery_procedures(workspace):
    """Generate recovery procedures markdown file (fixed file)."""
    content = """# Recovery Action Procedures for Overdue Inter-Library Loans

## Action Categories

The following recovery action categories apply based on the number of days
a loan is overdue (after grace period):

### courtesy_reminder
Applies when the adjusted overdue period is between 1 and 14 days inclusive.
Send a polite reminder via the patron's preferred contact method. Include
the loan ID, title, and amount of fine accrued so far.

### formal_notice
Applies when the adjusted overdue period is between 15 and 30 days inclusive.
Send an official library notice. Copy the patron's department head if the
patron is a student. Include cumulative fine and a return deadline of 14 days.

### final_warning
Applies when the adjusted overdue period is between 31 and 60 days inclusive.
Issue a final warning letter. Inform the patron that failure to return within
30 days will result in the account being referred to collections. Include
the total fine and estimated replacement cost.

### collection_referral
Applies when the adjusted overdue period is between 61 and 90 days inclusive.
Refer the account to the university collections department. Freeze the
patron's borrowing privileges. Include total fine and replacement cost estimate.

### replacement_invoice
Applies when the adjusted overdue period exceeds 90 days, or the loan status
is marked as lost. Generate a replacement invoice for the net replacement cost
plus accumulated fines. If insurance coverage applies (active policy), the
invoice reflects the net amount after insurance deduction.

## Priority Handling

Items with a net total liability (fine plus net replacement cost, if applicable)
exceeding $100.00 should be flagged as high_priority in the recovery action.
All others are normal_priority.

## Do Not Contact

If a patron's communication preferences indicate do_not_contact is "yes",
the recovery action should still be generated but marked with
contact_hold = true. Otherwise contact_hold = false.
"""
    filepath = os.path.join(workspace, "recovery_procedures.md")
    with open(filepath, "w") as f:
        f.write(content)


def main(db_path, workspace):
    """Main entry point: build database and workspace."""
    os.makedirs(workspace, exist_ok=True)
    n = SCALE["rows_per_table"]
    nf = SCALE["num_workspace_files"]

    # ── Database ─────────────────────────────────────────────────────────
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)

    create_tables(conn)
    institutions = generate_institutions(conn, n)
    books = generate_books(conn, n)
    patrons = generate_patrons(conn, n)
    loans = generate_loans(conn, n, institutions, books, patrons)
    generate_shipments(conn, loans, n)
    generate_contacts(conn, loans, patrons, n)
    conn.close()

    # ── Workspace files (scalable) ───────────────────────────────────────
    # Distribute scalable files: ~3/8 condition, ~3/8 insurance, ~2/8 patron comm
    n_condition = nf * 3 // 8
    if n_condition < 1:
        n_condition = 1
    n_insurance = nf * 3 // 8
    if n_insurance < 1:
        n_insurance = 1
    n_patron_comm = nf - n_condition - n_insurance
    if n_patron_comm < 1:
        n_patron_comm = 1
        n_insurance = nf - n_condition - n_patron_comm

    generate_condition_reports(workspace, books, n_condition)
    generate_insurance_records(workspace, loans, n_insurance)
    generate_patron_comm_files(workspace, patrons, n_patron_comm)

    # ── Workspace files (fixed, policy/config) ───────────────────────────
    generate_fine_policy(workspace)
    generate_institution_agreements(workspace, institutions)
    generate_recovery_procedures(workspace)

    print(f"Database written to {db_path}")
    print(f"Workspace populated in {workspace}/")
    print(f"  Scalable files: {n_condition} condition CSVs, {n_insurance} insurance JSONs, {n_patron_comm} patron comm TXTs")
    print(f"  Fixed files: fine_policy.yaml, institution_agreements.json, recovery_procedures.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
