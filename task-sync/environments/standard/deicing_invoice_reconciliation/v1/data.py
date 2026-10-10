"""
Aircraft De-Icing Invoice Reconciliation - Data Generation Script

Generates a SQLite database and workspace files for reconciling de-icing
service invoices against actual fluid usage logs, flight schedules, and
contracted rates.
"""

import argparse
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 20,
}

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

# --- Constants ---
FLUID_TYPES = ["Type I", "Type II", "Type IV"]
FLUID_UNIT = "liters"
AIRLINES = ["AA", "UA", "DL", "WN", "NK", "B6", "AS", "F9"]
AIRCRAFT_TYPES = ["B737", "A320", "B777", "A330", "E175", "CRJ900", "B787", "A321"]
GATES = [f"{t}{n}" for t in ["A", "B", "C", "D"] for n in range(1, 16)]

PROVIDERS = [
    {"provider_id": "P001", "provider_name": "ArcticShield Services", "contract_id": "C-2025-001"},
    {"provider_id": "P002", "provider_name": "FrostGuard Aviation", "contract_id": "C-2025-002"},
    {"provider_id": "P003", "provider_name": "IceClear Solutions", "contract_id": "C-2025-003"},
    {"provider_id": "P004", "provider_name": "PolarWing De-Icing", "contract_id": "C-2025-004"},
    {"provider_id": "P005", "provider_name": "NorthStar Ground Ops", "contract_id": "C-2025-005"},
]

# Contracted rates per fluid type per provider (base rates; workspace file will hold the actual ones)
BASE_RATES = {
    "Type I":  {"min": 3.50, "max": 5.50},
    "Type II": {"min": 7.00, "max": 10.00},
    "Type IV": {"min": 12.00, "max": 18.00},
}

# Temperature brackets determine required fluid type
TEMP_BRACKETS = [
    {"min_temp_c": -40, "max_temp_c": -20, "required_fluid": "Type IV", "holdover_minutes": 15},
    {"min_temp_c": -20, "max_temp_c": -5,  "required_fluid": "Type II", "holdover_minutes": 30},
    {"min_temp_c": -5,  "max_temp_c": 5,   "required_fluid": "Type I",  "holdover_minutes": 45},
]

# Validation policy parameters
VALIDATION_POLICY = {
    "quantity_tolerance_pct": 5.0,
    "max_service_duration_minutes": 90,
    "min_fluid_quantity_liters": 10,
    "rate_tolerance_pct": 0.0,
    "pushback_window_minutes": 120,
    "duplicate_detection_window_minutes": 30,
}


def create_tables(conn):
    """Create all database tables."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS providers (
            provider_id TEXT PRIMARY KEY,
            provider_name TEXT NOT NULL,
            contract_id TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS flights (
            flight_id TEXT PRIMARY KEY,
            airline_code TEXT NOT NULL,
            flight_number TEXT NOT NULL,
            aircraft_type TEXT NOT NULL,
            gate TEXT NOT NULL,
            scheduled_departure TEXT NOT NULL,
            actual_pushback TEXT NOT NULL,
            destination TEXT NOT NULL,
            date TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deicing_trucks (
            truck_id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            fluid_type TEXT NOT NULL,
            capacity_liters REAL NOT NULL,
            last_maintenance_date TEXT NOT NULL,
            FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deicing_services (
            service_id TEXT PRIMARY KEY,
            flight_id TEXT NOT NULL,
            truck_id TEXT NOT NULL,
            fluid_type TEXT NOT NULL,
            fluid_quantity_liters REAL NOT NULL,
            service_start TEXT NOT NULL,
            service_end TEXT NOT NULL,
            temperature_c REAL NOT NULL,
            provider_id TEXT NOT NULL,
            date TEXT NOT NULL,
            FOREIGN KEY (flight_id) REFERENCES flights(flight_id),
            FOREIGN KEY (truck_id) REFERENCES deicing_trucks(truck_id),
            FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_id TEXT PRIMARY KEY,
            service_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            fluid_type TEXT NOT NULL,
            charged_quantity REAL NOT NULL,
            charged_rate REAL NOT NULL,
            total_charge REAL NOT NULL,
            invoice_date TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (service_id) REFERENCES deicing_services(service_id),
            FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
        )
    """)

    conn.commit()


def generate_contract_rates():
    """Generate contracted rates per provider per fluid type."""
    rates = {}
    for provider in PROVIDERS:
        pid = provider["provider_id"]
        rates[pid] = {}
        for fluid in FLUID_TYPES:
            rate = round(random.uniform(BASE_RATES[fluid]["min"], BASE_RATES[fluid]["max"]), 2)
            rates[pid][fluid] = rate
    return rates


def generate_data(conn, contract_rates):
    """Generate all data and insert into database."""
    cursor = conn.cursor()
    n_rows = SCALE["rows_per_table"]

    # Insert providers
    for p in PROVIDERS:
        cursor.execute(
            "INSERT INTO providers VALUES (?, ?, ?)",
            (p["provider_id"], p["provider_name"], p["contract_id"])
        )

    # Generate trucks (about n_rows/5, min 20)
    n_trucks = max(20, n_rows // 5)
    trucks = []
    for i in range(n_trucks):
        truck_id = f"T{i+1:04d}"
        provider = random.choice(PROVIDERS)
        fluid_type = random.choice(FLUID_TYPES)
        capacity = round(random.uniform(2000, 8000), 0)
        maint_date = fake.date_between(start_date="-180d", end_date="-10d").isoformat()
        trucks.append({
            "truck_id": truck_id,
            "provider_id": provider["provider_id"],
            "fluid_type": fluid_type,
            "capacity_liters": capacity,
            "last_maintenance_date": maint_date,
        })
        cursor.execute(
            "INSERT INTO deicing_trucks VALUES (?, ?, ?, ?, ?)",
            (truck_id, provider["provider_id"], fluid_type, capacity, maint_date)
        )

    # Generate date range for operations (winter months)
    n_files = SCALE["num_workspace_files"]
    # We'll spread flights across multiple days
    n_days = max(n_files, 5)  # at least as many days as workspace files needed
    base_date = datetime(2026, 1, 5)
    dates = [(base_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n_days)]

    # Generate flights
    flights = []
    flights_per_day = max(1, n_rows // n_days)
    flight_counter = 0
    for date_str in dates:
        for j in range(flights_per_day):
            if flight_counter >= n_rows:
                break
            flight_counter += 1
            fid = f"FL{flight_counter:05d}"
            airline = random.choice(AIRLINES)
            fnum = f"{airline}{random.randint(100, 9999)}"
            atype = random.choice(AIRCRAFT_TYPES)
            gate = random.choice(GATES)
            # Scheduled departure between 05:00 and 22:00
            hour = random.randint(5, 21)
            minute = random.choice([0, 15, 30, 45])
            sched_dep = f"{date_str}T{hour:02d}:{minute:02d}:00"
            # Actual pushback: usually within -10 to +60 minutes of scheduled
            delay_min = random.randint(-10, 60)
            actual_pb = (datetime.fromisoformat(sched_dep) + timedelta(minutes=delay_min)).isoformat()
            dest = fake.city()
            flights.append({
                "flight_id": fid,
                "airline_code": airline,
                "flight_number": fnum,
                "aircraft_type": atype,
                "gate": gate,
                "scheduled_departure": sched_dep,
                "actual_pushback": actual_pb,
                "destination": dest,
                "date": date_str,
            })
            cursor.execute(
                "INSERT INTO flights VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fid, airline, fnum, atype, gate, sched_dep, actual_pb, dest, date_str)
            )
        if flight_counter >= n_rows:
            break

    # Fill remaining flights if n_rows not reached
    while flight_counter < n_rows:
        flight_counter += 1
        date_str = random.choice(dates)
        fid = f"FL{flight_counter:05d}"
        airline = random.choice(AIRLINES)
        fnum = f"{airline}{random.randint(100, 9999)}"
        atype = random.choice(AIRCRAFT_TYPES)
        gate = random.choice(GATES)
        hour = random.randint(5, 21)
        minute = random.choice([0, 15, 30, 45])
        sched_dep = f"{date_str}T{hour:02d}:{minute:02d}:00"
        delay_min = random.randint(-10, 60)
        actual_pb = (datetime.fromisoformat(sched_dep) + timedelta(minutes=delay_min)).isoformat()
        dest = fake.city()
        flights.append({
            "flight_id": fid,
            "airline_code": airline,
            "flight_number": fnum,
            "aircraft_type": atype,
            "gate": gate,
            "scheduled_departure": sched_dep,
            "actual_pushback": actual_pb,
            "destination": dest,
            "date": date_str,
        })
        cursor.execute(
            "INSERT INTO flights VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fid, airline, fnum, atype, gate, sched_dep, actual_pb, dest, date_str)
        )

    # Generate de-icing services (one per flight)
    services = []
    for i, flight in enumerate(flights):
        sid = f"SVC{i+1:05d}"
        # Pick a truck from a random provider
        truck = random.choice(trucks)
        provider_id = truck["provider_id"]
        fluid_type = random.choice(FLUID_TYPES)
        # Temperature for the service
        temp = round(random.uniform(-30, 4), 1)
        # Fluid quantity: 50-500 liters depending on aircraft
        base_qty = {"B737": 150, "A320": 160, "B777": 350, "A330": 320,
                     "E175": 80, "CRJ900": 70, "B787": 380, "A321": 180}
        qty = round(base_qty.get(flight["aircraft_type"], 150) * random.uniform(0.7, 1.5), 1)

        # Service starts 30-90 min before pushback
        pb_time = datetime.fromisoformat(flight["actual_pushback"])
        start_offset = random.randint(30, 90)
        svc_start = (pb_time - timedelta(minutes=start_offset)).isoformat()
        svc_duration = random.randint(10, 45)
        svc_end = (datetime.fromisoformat(svc_start) + timedelta(minutes=svc_duration)).isoformat()

        services.append({
            "service_id": sid,
            "flight_id": flight["flight_id"],
            "truck_id": truck["truck_id"],
            "fluid_type": fluid_type,
            "fluid_quantity_liters": qty,
            "service_start": svc_start,
            "service_end": svc_end,
            "temperature_c": temp,
            "provider_id": provider_id,
            "date": flight["date"],
        })
        cursor.execute(
            "INSERT INTO deicing_services VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, flight["flight_id"], truck["truck_id"], fluid_type, qty,
             svc_start, svc_end, temp, provider_id, flight["date"])
        )

    # Generate invoices with some intentional discrepancies
    invoices = []
    discrepancy_indices = set()

    # ~15% quantity overcharges
    qty_overcharge_count = max(5, int(n_rows * 0.15))
    qty_overcharge_indices = set(random.sample(range(n_rows), qty_overcharge_count))
    discrepancy_indices.update(qty_overcharge_indices)

    # ~10% rate mismatches
    rate_mismatch_count = max(4, int(n_rows * 0.10))
    remaining = [i for i in range(n_rows) if i not in qty_overcharge_indices]
    rate_mismatch_indices = set(random.sample(remaining, min(rate_mismatch_count, len(remaining))))
    discrepancy_indices.update(rate_mismatch_indices)

    # ~8% time anomalies (service end after pushback)
    time_anomaly_count = max(3, int(n_rows * 0.08))
    remaining2 = [i for i in range(n_rows) if i not in discrepancy_indices]
    time_anomaly_indices = set(random.sample(remaining2, min(time_anomaly_count, len(remaining2))))

    # ~5% duplicate invoices (same service_id billed twice)
    duplicate_count = max(2, int(n_rows * 0.05))
    remaining3 = [i for i in range(n_rows) if i not in discrepancy_indices and i not in time_anomaly_indices]
    duplicate_source_indices = set(random.sample(remaining3, min(duplicate_count, len(remaining3))))

    for i, svc in enumerate(services):
        inv_id = f"INV{i+1:05d}"
        correct_rate = contract_rates[svc["provider_id"]][svc["fluid_type"]]
        actual_qty = svc["fluid_quantity_liters"]

        if i in qty_overcharge_indices:
            # Overcharge: add 8-25% to quantity
            overcharge_pct = random.uniform(0.08, 0.25)
            charged_qty = round(actual_qty * (1 + overcharge_pct), 1)
            charged_rate = correct_rate
        elif i in rate_mismatch_indices:
            # Wrong rate: use a different rate (10-40% higher)
            charged_qty = actual_qty
            rate_increase = random.uniform(0.10, 0.40)
            charged_rate = round(correct_rate * (1 + rate_increase), 2)
        else:
            # Correct invoice
            charged_qty = actual_qty
            charged_rate = correct_rate

        total = round(charged_qty * charged_rate, 2)
        inv_date = svc["date"]

        invoices.append({
            "invoice_id": inv_id,
            "service_id": svc["service_id"],
            "provider_id": svc["provider_id"],
            "fluid_type": svc["fluid_type"],
            "charged_quantity": charged_qty,
            "charged_rate": charged_rate,
            "total_charge": total,
            "invoice_date": inv_date,
            "status": "pending",
            "is_qty_overcharge": i in qty_overcharge_indices,
            "is_rate_mismatch": i in rate_mismatch_indices,
        })
        cursor.execute(
            "INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (inv_id, svc["service_id"], svc["provider_id"], svc["fluid_type"],
             charged_qty, charged_rate, total, inv_date, "pending")
        )

    # Insert duplicate invoices
    dup_invoices = []
    dup_counter = n_rows
    for idx in duplicate_source_indices:
        dup_counter += 1
        orig_svc = services[idx]
        orig_inv = invoices[idx]
        dup_id = f"INV{dup_counter:05d}"
        # Duplicate with slightly different charge (rounding difference)
        charged_qty = orig_inv["charged_quantity"]
        charged_rate = orig_inv["charged_rate"]
        total = round(charged_qty * charged_rate, 2)
        dup_invoices.append({
            "invoice_id": dup_id,
            "service_id": orig_svc["service_id"],
            "provider_id": orig_svc["provider_id"],
            "fluid_type": orig_svc["fluid_type"],
            "charged_quantity": charged_qty,
            "charged_rate": charged_rate,
            "total_charge": total,
            "invoice_date": orig_inv["invoice_date"],
            "status": "pending",
        })
        cursor.execute(
            "INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (dup_id, orig_svc["service_id"], orig_svc["provider_id"], orig_svc["fluid_type"],
             charged_qty, charged_rate, total, orig_inv["invoice_date"], "pending")
        )

    # For time anomalies, update the service end time to be AFTER pushback
    for idx in time_anomaly_indices:
        svc = services[idx]
        flight = flights[idx]
        pb_time = datetime.fromisoformat(flight["actual_pushback"])
        # Set service end to 5-30 min after pushback
        new_end = (pb_time + timedelta(minutes=random.randint(5, 30))).isoformat()
        svc["service_end"] = new_end
        cursor.execute(
            "UPDATE deicing_services SET service_end = ? WHERE service_id = ?",
            (new_end, svc["service_id"])
        )

    conn.commit()
    return flights, services, invoices, dup_invoices, trucks, time_anomaly_indices, duplicate_source_indices


def generate_workspace(workspace, flights, services, invoices, dup_invoices,
                       trucks, contract_rates, time_anomaly_indices, duplicate_source_indices):
    """Generate workspace files."""
    os.makedirs(workspace, exist_ok=True)
    n_files = SCALE["num_workspace_files"]

    # --- Fixed policy/config files (not scaled) ---

    # 1. Contract rates JSON
    rates_data = {}
    for pid, fluids in contract_rates.items():
        provider_name = next(p["provider_name"] for p in PROVIDERS if p["provider_id"] == pid)
        rates_data[pid] = {
            "provider_name": provider_name,
            "rates": {ft: {"rate_per_liter": rate, "currency": "USD"} for ft, rate in fluids.items()},
            "effective_date": "2025-10-01",
            "expiry_date": "2026-04-30",
        }
    with open(os.path.join(workspace, "contract_rates.json"), "w") as f:
        json.dump(rates_data, f, indent=2)

    # 2. Validation policy YAML
    policy = {
        "validation_rules": {
            "quantity_tolerance_pct": VALIDATION_POLICY["quantity_tolerance_pct"],
            "rate_tolerance_pct": VALIDATION_POLICY["rate_tolerance_pct"],
            "max_service_duration_minutes": VALIDATION_POLICY["max_service_duration_minutes"],
            "min_fluid_quantity_liters": VALIDATION_POLICY["min_fluid_quantity_liters"],
            "pushback_window_minutes": VALIDATION_POLICY["pushback_window_minutes"],
            "duplicate_detection": {
                "enabled": True,
                "match_fields": ["service_id"],
                "window_minutes": VALIDATION_POLICY["duplicate_detection_window_minutes"],
            },
        },
        "approval_workflow": {
            "auto_approve_threshold_usd": 500.00,
            "manager_review_threshold_usd": 5000.00,
            "discrepancy_categories": [
                "quantity_overcharge",
                "rate_mismatch",
                "time_anomaly",
                "duplicate_billing",
            ],
        },
    }
    with open(os.path.join(workspace, "validation_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 3. Temperature brackets MD
    temp_content = "# Temperature-Based Fluid Requirements\n\n"
    temp_content += "The following table defines which de-icing fluid type is required based on\n"
    temp_content += "the ambient temperature at the time of service.\n\n"
    temp_content += "| Min Temp (C) | Max Temp (C) | Required Fluid | Holdover (min) |\n"
    temp_content += "|-------------|-------------|----------------|----------------|\n"
    for tb in TEMP_BRACKETS:
        temp_content += f"| {tb['min_temp_c']} | {tb['max_temp_c']} | {tb['required_fluid']} | {tb['holdover_minutes']} |\n"
    temp_content += "\nIf the temperature does not fall within any bracket (above 5C),\n"
    temp_content += "de-icing service is not required and any invoice for such conditions\n"
    temp_content += "should be flagged as a time_anomaly.\n"
    with open(os.path.join(workspace, "temperature_brackets.md"), "w") as f:
        f.write(temp_content)

    # --- Scalable data files (n_files count) ---

    # Group services by date for truck log files
    services_by_date = {}
    for svc in services:
        d = svc["date"]
        if d not in services_by_date:
            services_by_date[d] = []
        services_by_date[d].append(svc)

    sorted_dates = sorted(services_by_date.keys())

    # Distribute dates across n_files truck log files
    # Each file covers one or more dates
    files_generated = 0

    # Generate truck fluid usage log CSVs (60% of files)
    n_truck_log_files = max(1, int(n_files * 0.6))
    dates_per_file = max(1, len(sorted_dates) // n_truck_log_files)

    for file_idx in range(n_truck_log_files):
        start_d = file_idx * dates_per_file
        end_d = start_d + dates_per_file if file_idx < n_truck_log_files - 1 else len(sorted_dates)
        file_dates = sorted_dates[start_d:end_d]
        if not file_dates:
            file_dates = [sorted_dates[-1]]

        rows = []
        for d in file_dates:
            for svc in services_by_date.get(d, []):
                # Truck log records the actual fluid dispensed
                rows.append({
                    "log_date": d,
                    "truck_id": svc["truck_id"],
                    "service_id": svc["service_id"],
                    "fluid_type": svc["fluid_type"],
                    "dispensed_liters": svc["fluid_quantity_liters"],
                    "start_time": svc["service_start"],
                    "end_time": svc["service_end"],
                })

        if rows:
            df = pd.DataFrame(rows)
            fname = f"truck_fluid_log_{file_dates[0].replace('-', '')}_to_{file_dates[-1].replace('-', '')}.csv"
            df.to_csv(os.path.join(workspace, fname), index=False)
            files_generated += 1

    # Generate departure schedule TXT files (20% of files)
    n_schedule_files = max(1, int(n_files * 0.2))
    flights_by_date = {}
    for fl in flights:
        d = fl["date"]
        if d not in flights_by_date:
            flights_by_date[d] = []
        flights_by_date[d].append(fl)

    dates_per_sched = max(1, len(sorted_dates) // n_schedule_files)
    for file_idx in range(n_schedule_files):
        start_d = file_idx * dates_per_sched
        end_d = start_d + dates_per_sched if file_idx < n_schedule_files - 1 else len(sorted_dates)
        file_dates = sorted_dates[start_d:end_d]
        if not file_dates:
            file_dates = [sorted_dates[-1]]

        lines = [f"DEPARTURE SCHEDULE: {file_dates[0]} to {file_dates[-1]}", "=" * 60, ""]
        lines.append(f"{'Flight ID':<12} {'Flight#':<10} {'Gate':<6} {'Sched Departure':<22} {'Aircraft':<10} {'Destination'}")
        lines.append("-" * 90)
        for d in file_dates:
            for fl in sorted(flights_by_date.get(d, []), key=lambda x: x["scheduled_departure"]):
                lines.append(
                    f"{fl['flight_id']:<12} {fl['flight_number']:<10} {fl['gate']:<6} "
                    f"{fl['scheduled_departure']:<22} {fl['aircraft_type']:<10} {fl['destination']}"
                )
        lines.append("")

        fname = f"departure_schedule_{file_dates[0].replace('-', '')}_to_{file_dates[-1].replace('-', '')}.txt"
        with open(os.path.join(workspace, fname), "w") as f:
            f.write("\n".join(lines))
        files_generated += 1

    # Generate remaining files as JSON invoice batch summaries (20% of files)
    n_invoice_files = max(1, n_files - files_generated)
    all_invoices = invoices + dup_invoices
    invs_per_file = max(1, len(all_invoices) // n_invoice_files)

    for file_idx in range(n_invoice_files):
        start_i = file_idx * invs_per_file
        end_i = start_i + invs_per_file if file_idx < n_invoice_files - 1 else len(all_invoices)
        batch = all_invoices[start_i:end_i]

        batch_data = {
            "batch_id": f"BATCH-{file_idx + 1:03d}",
            "generated_date": "2026-02-15",
            "invoice_count": len(batch),
            "invoices": [
                {
                    "invoice_id": inv["invoice_id"],
                    "service_id": inv["service_id"],
                    "provider_id": inv["provider_id"],
                    "fluid_type": inv["fluid_type"],
                    "charged_quantity": inv["charged_quantity"],
                    "charged_rate": inv["charged_rate"],
                    "total_charge": inv["total_charge"],
                    "invoice_date": inv["invoice_date"],
                }
                for inv in batch
            ],
        }

        fname = f"invoice_batch_{file_idx + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(batch_data, f, indent=2)
        files_generated += 1

    # Pad with extra files if needed
    while files_generated < n_files:
        files_generated += 1
        # Generate a provider summary YAML
        pid = PROVIDERS[(files_generated - 1) % len(PROVIDERS)]["provider_id"]
        pname = next(p["provider_name"] for p in PROVIDERS if p["provider_id"] == pid)
        provider_svcs = [s for s in services if s["provider_id"] == pid]
        summary = {
            "provider_id": pid,
            "provider_name": pname,
            "total_services": len(provider_svcs),
            "total_fluid_liters": round(sum(s["fluid_quantity_liters"] for s in provider_svcs), 1),
            "fluid_breakdown": {},
        }
        for ft in FLUID_TYPES:
            ft_svcs = [s for s in provider_svcs if s["fluid_type"] == ft]
            summary["fluid_breakdown"][ft] = {
                "count": len(ft_svcs),
                "total_liters": round(sum(s["fluid_quantity_liters"] for s in ft_svcs), 1),
            }
        fname = f"provider_summary_{pid}.yaml"
        with open(os.path.join(workspace, fname), "w") as f:
            yaml.dump(summary, f, default_flow_style=False, sort_keys=False)


def main():
    parser = argparse.ArgumentParser(description="Generate de-icing invoice reconciliation data")
    parser.add_argument("--db_path", required=True, help="Path to SQLite database file")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    args = parser.parse_args()

    # Remove existing DB
    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    contract_rates = generate_contract_rates()
    flights, services, invoices, dup_invoices, trucks, time_anomaly_indices, dup_source_indices = generate_data(conn, contract_rates)
    generate_workspace(args.workspace, flights, services, invoices, dup_invoices,
                       trucks, contract_rates, time_anomaly_indices, dup_source_indices)
    conn.close()
    print(f"Database created at {args.db_path}")
    print(f"Workspace files generated in {args.workspace}")
    print(f"  Flights: {len(flights)}")
    print(f"  Services: {len(services)}")
    print(f"  Invoices: {len(invoices)} + {len(dup_invoices)} duplicates")


if __name__ == "__main__":
    main()
