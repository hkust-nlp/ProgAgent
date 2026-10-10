"""
Energy Consumption Anomaly Detection - Data Generation Script

Generates a SQLite database and workspace files for a residential energy
anomaly detection task. Anomalies include faulty meters, unauthorized usage,
and billing discrepancies.
"""
import argparse
import os
import json
import sqlite3
import random
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta
import yaml


def _split_df(df, n):
    L = len(df)
    base, rem = divmod(L, n)
    out, start = [], 0
    for i in range(n):
        size = base + (1 if i < rem else 0)
        out.append(df.iloc[start:start + size])
        start += size
    return out


SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 16,
}


def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    num_households = SCALE["rows_per_table"]
    num_days = 30  # fixed observation window
    num_workspace_files = SCALE["num_workspace_files"]

    zones = ["North", "South", "East", "West"]
    heating_types = ["electric", "gas", "heat_pump"]
    meter_models = ["SM-100A", "SM-200B", "SM-300C", "SM-400D"]

    appliance_catalog = [
        ("refrigerator", 150, 24.0),
        ("washing_machine", 500, 1.0),
        ("dryer", 3000, 0.5),
        ("dishwasher", 1800, 1.0),
        ("air_conditioner", 2500, 4.0),
        ("electric_heater", 1500, 6.0),
        ("water_heater", 4500, 3.0),
        ("oven", 2000, 1.0),
        ("microwave", 1000, 0.5),
        ("television", 100, 5.0),
        ("computer", 300, 8.0),
        ("lighting", 200, 8.0),
        ("ceiling_fan", 75, 10.0),
        ("dehumidifier", 300, 6.0),
        ("freezer", 200, 24.0),
    ]

    # ------------------------------------------------------------------ #
    #  Anomaly assignment (deterministic via separate RNG)
    # ------------------------------------------------------------------ #
    rng_a = random.Random(42)
    indices = list(range(num_households))
    rng_a.shuffle(indices)

    num_faulty = max(2, int(num_households * 0.14))
    num_unauthorized = max(2, int(num_households * 0.10))
    num_billing = max(2, int(num_households * 0.08))

    anomaly_map = {}  # household_index -> type
    ptr = 0
    for _ in range(num_faulty):
        anomaly_map[indices[ptr]] = "faulty_meter"
        ptr += 1
    for _ in range(num_unauthorized):
        anomaly_map[indices[ptr]] = "unauthorized_usage"
        ptr += 1
    for _ in range(num_billing):
        anomaly_map[indices[ptr]] = "billing_discrepancy"
        ptr += 1

    # ------------------------------------------------------------------ #
    #  Households
    # ------------------------------------------------------------------ #
    start_date = datetime(2025, 1, 1)
    households = []
    for i in range(num_households):
        hid = f"H{i+1:04d}"
        households.append({
            "household_id": hid,
            "zone": zones[i % len(zones)],
            "address": fake.street_address(),
            "account_number": f"ACC{fake.unique.random_int(100000, 999999)}",
            "num_occupants": random.randint(1, 6),
            "sq_footage": random.randint(800, 3500),
            "heating_type": random.choice(heating_types),
        })
    hh_df = pd.DataFrame(households)

    # ------------------------------------------------------------------ #
    #  Meters
    # ------------------------------------------------------------------ #
    meters = []
    for i, h in enumerate(households):
        mid = f"M{i+1:04d}"
        install = start_date - timedelta(days=random.randint(365, 3650))
        calib = install + timedelta(days=random.randint(180, 1095))
        if calib > start_date:
            calib = start_date - timedelta(days=random.randint(10, 90))
        meters.append({
            "meter_id": mid,
            "household_id": h["household_id"],
            "install_date": install.strftime("%Y-%m-%d"),
            "last_calibration_date": calib.strftime("%Y-%m-%d"),
            "meter_model": random.choice(meter_models),
            "status": "active",
        })
    meter_df = pd.DataFrame(meters)

    # ------------------------------------------------------------------ #
    #  Appliances  (>= rows_per_table rows)
    # ------------------------------------------------------------------ #
    appliances = []
    aid = 1
    # Ensure at least 3 per household so total >= rows_per_table when
    # num_households >= rows_per_table (which it always is here).
    min_per_hh = max(3, math.ceil(SCALE["rows_per_table"] / num_households))
    for i, h in enumerate(households):
        n_app = random.randint(min_per_hh, min(min_per_hh + 4, len(appliance_catalog)))
        chosen = random.sample(appliance_catalog, n_app)
        for atype, watt_base, hrs_base in chosen:
            watt = int(watt_base * random.uniform(0.8, 1.2))
            hrs = round(hrs_base * random.uniform(0.7, 1.3), 1)
            appliances.append({
                "appliance_id": f"A{aid:05d}",
                "household_id": h["household_id"],
                "appliance_type": atype,
                "brand": fake.company().split()[0],
                "rated_wattage": watt,
                "avg_daily_hours": hrs,
                "registration_date": (start_date - timedelta(days=random.randint(30, 730))).strftime("%Y-%m-%d"),
            })
            aid += 1
    app_df = pd.DataFrame(appliances)

    # ------------------------------------------------------------------ #
    #  Weather observations (daily, >= rows_per_table rows)
    # ------------------------------------------------------------------ #
    num_weather_days = max(num_days, SCALE["rows_per_table"])
    weather_start = start_date - timedelta(days=num_weather_days - num_days)
    conditions = ["sunny", "cloudy", "rainy", "partly_cloudy", "overcast", "windy"]
    weather_rows = []
    for d in range(num_weather_days):
        dt = weather_start + timedelta(days=d)
        # Seasonal pattern (winter in Jan)
        day_of_year = dt.timetuple().tm_yday
        base_temp = 5 + 15 * math.sin((day_of_year - 80) * 2 * math.pi / 365)
        temp = round(base_temp + np.random.normal(0, 4), 1)
        weather_rows.append({
            "obs_id": d + 1,
            "date": dt.strftime("%Y-%m-%d"),
            "temperature_c": temp,
            "humidity_pct": round(np.random.uniform(30, 95), 1),
            "wind_speed_kmh": round(np.random.uniform(0, 40), 1),
            "condition": random.choice(conditions),
        })
    weather_df = pd.DataFrame(weather_rows)

    # Pre-compute daily weather factors for meter reading generation
    # Thresholds must match the config file we write below
    HEATING_THRESHOLD = 10.0
    COOLING_THRESHOLD = 28.0
    HEATING_COEFF = 0.15
    COOLING_COEFF = 0.12

    # Build date->weather lookup for the observation window
    obs_dates = [(start_date + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(num_days)]
    weather_lookup = {r["date"]: r for r in weather_rows}

    # ------------------------------------------------------------------ #
    #  Compute base expected daily consumption per household
    # ------------------------------------------------------------------ #
    hh_expected = {}  # household_id -> base daily kWh
    for h in households:
        hid = h["household_id"]
        apps = [a for a in appliances if a["household_id"] == hid]
        daily_kwh = sum(a["rated_wattage"] * a["avg_daily_hours"] / 1000.0 for a in apps)
        hh_expected[hid] = daily_kwh

    def weather_factor(date_str, heating_type):
        w = weather_lookup.get(date_str)
        if w is None:
            return 1.0
        factor = 1.0
        temp = w["temperature_c"]
        if heating_type in ("electric", "heat_pump"):
            if temp < HEATING_THRESHOLD:
                factor += HEATING_COEFF * (HEATING_THRESHOLD - temp) / 10.0
            if temp > COOLING_THRESHOLD:
                factor += COOLING_COEFF * (temp - COOLING_THRESHOLD) / 10.0
        else:
            # Gas heating – only cooling adds electric load
            if temp > COOLING_THRESHOLD:
                factor += COOLING_COEFF * (temp - COOLING_THRESHOLD) / 10.0
        return factor

    # ------------------------------------------------------------------ #
    #  Meter readings  (num_households * num_days rows)
    # ------------------------------------------------------------------ #
    readings = []
    rid = 1
    rng_read = np.random.RandomState(42)
    for i, h in enumerate(households):
        hid = h["household_id"]
        mid = meters[i]["meter_id"]
        atype = anomaly_map.get(i, "normal")
        base_kwh = hh_expected[hid]

        # Anomaly factors
        if atype == "faulty_meter":
            faulty_factor = rng_read.uniform(1.5, 2.5)
        elif atype == "unauthorized_usage":
            extra_fraction = rng_read.uniform(0.4, 0.8)
        else:
            faulty_factor = 1.0
            extra_fraction = 0.0

        for d in range(num_days):
            dt = start_date + timedelta(days=d)
            date_str = dt.strftime("%Y-%m-%d")
            wf = weather_factor(date_str, h["heating_type"])
            expected = base_kwh * wf

            noise = 1.0 + rng_read.normal(0, 0.05)
            if atype == "faulty_meter":
                daily_kwh = expected * faulty_factor * noise
            elif atype == "unauthorized_usage":
                daily_kwh = (expected + base_kwh * extra_fraction) * noise
            else:
                daily_kwh = expected * noise

            daily_kwh = round(max(0.5, daily_kwh), 2)
            peak_ratio = rng_read.uniform(0.35, 0.55)
            peak_kwh = round(daily_kwh * peak_ratio, 2)
            off_peak_kwh = round(daily_kwh - peak_kwh, 2)

            # Voltage: normal ~230 V, faulty meters drift
            if atype == "faulty_meter":
                voltage = round(230 + rng_read.normal(0, 8), 1)
            else:
                voltage = round(230 + rng_read.normal(0, 2), 1)

            readings.append({
                "reading_id": rid,
                "meter_id": mid,
                "date": date_str,
                "daily_kwh": daily_kwh,
                "peak_kwh": peak_kwh,
                "off_peak_kwh": off_peak_kwh,
                "avg_voltage": voltage,
            })
            rid += 1
    reading_df = pd.DataFrame(readings)

    # ------------------------------------------------------------------ #
    #  Tariff log  (>= rows_per_table)
    # ------------------------------------------------------------------ #
    tiers = [1, 2, 3]
    base_rates = {1: 0.08, 2: 0.12, 3: 0.18}
    peak_mults = {1: 1.3, 2: 1.5, 3: 1.8}
    # Generate enough tariff entries
    tariff_rows = []
    tid = 1
    entries_needed = SCALE["rows_per_table"]
    changes_per_zone = max(1, math.ceil(entries_needed / (len(zones) * len(tiers))))
    for z in zones:
        for ch in range(changes_per_zone):
            eff_date = (start_date - timedelta(days=(changes_per_zone - ch) * 60)).strftime("%Y-%m-%d")
            for t in tiers:
                rate = round(base_rates[t] * (1 + 0.02 * ch) + random.uniform(-0.005, 0.005), 4)
                pm = round(peak_mults[t] + 0.05 * ch + random.uniform(-0.02, 0.02), 3)
                tariff_rows.append({
                    "log_id": tid,
                    "zone": z,
                    "effective_date": eff_date,
                    "tier": t,
                    "rate_per_kwh": rate,
                    "peak_multiplier": pm,
                })
                tid += 1
    tariff_df = pd.DataFrame(tariff_rows)

    # ------------------------------------------------------------------ #
    #  Write database
    # ------------------------------------------------------------------ #
    conn = sqlite3.connect(db_path)
    hh_df.to_sql("households", conn, if_exists="replace", index=False)
    meter_df.to_sql("meters", conn, if_exists="replace", index=False)
    app_df.to_sql("appliances", conn, if_exists="replace", index=False)
    weather_df.to_sql("weather_observations", conn, if_exists="replace", index=False)
    reading_df.to_sql("meter_readings", conn, if_exists="replace", index=False)
    tariff_df.to_sql("tariff_log", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()

    # ------------------------------------------------------------------ #
    #  Workspace: fixed config/policy files
    # ------------------------------------------------------------------ #
    thresholds = {
        "consumption_anomaly_threshold": 0.35,
        "billing_discrepancy_threshold": 0.20,
        "voltage_lower_bound": 218.0,
        "voltage_upper_bound": 242.0,
        "heating_threshold_c": 10.0,
        "cooling_threshold_c": 28.0,
        "heating_coefficient": 0.15,
        "cooling_coefficient": 0.12,
    }
    with open(os.path.join(workspace, "anomaly_thresholds.yaml"), "w") as f:
        yaml.dump(thresholds, f, default_flow_style=False)

    priority_rules = """Inspection Priority Scoring Rules
==================================

Each anomalous household receives a priority score that determines its
position on the field inspection list.

Base scores by anomaly type:
  faulty_meter           -> 70
  unauthorized_usage     -> 90
  billing_discrepancy    -> 50

Deviation bonus:
  bonus = min(abs(deviation_ratio) * 20, 30)

Final priority score = base_score + bonus, rounded to one decimal place.

Sorting:
  Primary key  : priority_score descending
  Tie-breaker  : household_id ascending (lexicographic)

Recommended actions:
  faulty_meter           -> "Replace or recalibrate meter"
  unauthorized_usage     -> "On-site inspection for unauthorized connections"
  billing_discrepancy    -> "Audit billing records and verify meter accuracy"
"""
    with open(os.path.join(workspace, "inspection_priority_rules.md"), "w") as f:
        f.write(priority_rules)

    tariff_mapping_lines = [
        "Tariff Tier Mapping",
        "====================",
        "",
        "Tier 1 : Basic residential usage up to 200 kWh/month",
        "Tier 2 : Moderate usage 201-500 kWh/month",
        "Tier 3 : High usage above 500 kWh/month",
        "",
        "Peak hours   : 07:00 - 21:00",
        "Off-peak hours: 21:00 - 07:00",
        "",
        "The peak multiplier is applied to all peak-hour consumption.",
        "Billing uses the tariff rate effective on the first day of the billing period.",
    ]
    with open(os.path.join(workspace, "tariff_tier_mapping.txt"), "w") as f:
        f.write("\n".join(tariff_mapping_lines) + "\n")

    # ------------------------------------------------------------------ #
    #  Workspace: scalable billing batch CSVs
    # ------------------------------------------------------------------ #
    # Reopen DB to read actual totals
    conn = sqlite3.connect(db_path)

    num_billing_files = num_workspace_files // 2
    num_maint_files = num_workspace_files - num_billing_files

    # Compute actual metered totals per household (from readings)
    actual_totals = reading_df.groupby("meter_id").agg(
        total_kwh=("daily_kwh", "sum"),
        total_peak=("peak_kwh", "sum"),
        total_off_peak=("off_peak_kwh", "sum"),
    ).reset_index()
    # Map meter -> household
    meter_hh = {m["meter_id"]: m["household_id"] for m in meters}
    actual_totals["household_id"] = actual_totals["meter_id"].map(meter_hh)

    # Get latest tariff per zone (for billing computation)
    latest_tariffs = {}
    for z in zones:
        zt = tariff_df[tariff_df["zone"] == z].sort_values("effective_date", ascending=False)
        for t in tiers:
            row = zt[zt["tier"] == t].iloc[0]
            latest_tariffs[(z, t)] = (row["rate_per_kwh"], row["peak_multiplier"])

    # Build billing records
    billing_records = []
    hh_zone = {h["household_id"]: h["zone"] for h in households}
    period_start = start_date.strftime("%Y-%m-%d")
    period_end = (start_date + timedelta(days=num_days - 1)).strftime("%Y-%m-%d")

    rng_bill = random.Random(4242)
    for _, row in actual_totals.iterrows():
        hid = row["household_id"]
        zone = hh_zone[hid]
        total_kwh = row["total_kwh"]
        total_peak = row["total_peak"]
        total_off_peak = row["total_off_peak"]

        # Determine tier by monthly extrapolation
        monthly_est = total_kwh * 30.0 / num_days
        if monthly_est <= 200:
            tier = 1
        elif monthly_est <= 500:
            tier = 2
        else:
            tier = 3

        rate, pm = latest_tariffs[(zone, tier)]

        # Normal billed kwh = actual kwh
        idx_in_list = int(hid[1:]) - 1
        atype = anomaly_map.get(idx_in_list, "normal")

        if atype == "billing_discrepancy":
            # Billed kwh is wrong
            factor = rng_bill.choice([0.55, 0.60, 0.65, 1.35, 1.45, 1.55])
            billed_kwh = round(total_kwh * factor, 2)
        else:
            billed_kwh = round(total_kwh + rng_bill.uniform(-2, 2), 2)

        billed_peak = round(billed_kwh * total_peak / max(total_kwh, 0.01), 2)
        billed_off_peak = round(billed_kwh - billed_peak, 2)

        amount = round(billed_off_peak * rate + billed_peak * rate * pm, 2)
        billing_records.append({
            "household_id": hid,
            "billing_period_start": period_start,
            "billing_period_end": period_end,
            "billed_kwh": billed_kwh,
            "billed_peak_kwh": billed_peak,
            "billed_off_peak_kwh": billed_off_peak,
            "tier_applied": tier,
            "rate_per_kwh": rate,
            "peak_multiplier": pm,
            "total_amount": amount,
            "payment_status": rng_bill.choice(["paid", "pending", "overdue"]),
        })

    billing_df = pd.DataFrame(billing_records)
    # Split across files
    chunks = _split_df(billing_df, num_billing_files)
    for ci, chunk in enumerate(chunks):
        fname = f"billing_batch_{ci+1:02d}.csv"
        chunk.to_csv(os.path.join(workspace, fname), index=False)

    # ------------------------------------------------------------------ #
    #  Workspace: scalable maintenance log JSONs
    # ------------------------------------------------------------------ #
    maintenance_entries = []
    rng_maint = random.Random(4343)
    service_types = ["routine_inspection", "emergency_repair", "calibration_check", "firmware_update"]
    normal_findings = [
        "All systems nominal",
        "Minor wear on connector",
        "Firmware up to date",
        "Meter operating within specifications",
    ]
    faulty_findings = [
        "calibration_drift detected",
        "sensor_malfunction observed",
        "faulty_component in voltage regulator",
        "intermittent read errors logged",
    ]
    tech_ids = [f"TECH{k:03d}" for k in range(1, 11)]

    for i, m in enumerate(meters):
        mid = m["meter_id"]
        hid = m["household_id"]
        atype = anomaly_map.get(i, "normal")

        # Each meter has 1-3 maintenance entries
        n_entries = rng_maint.randint(1, 3)
        for _ in range(n_entries):
            sdate = (start_date - timedelta(days=rng_maint.randint(10, 365))).strftime("%Y-%m-%d")
            stype = rng_maint.choice(service_types)
            if atype == "faulty_meter":
                findings = rng_maint.choice(faulty_findings)
                issues = findings.split(" ")[0]  # e.g. "calibration_drift"
            else:
                findings = rng_maint.choice(normal_findings)
                issues = "none"
            maintenance_entries.append({
                "meter_id": mid,
                "household_id": hid,
                "service_date": sdate,
                "service_type": stype,
                "technician_id": rng_maint.choice(tech_ids),
                "findings": findings,
                "issues_found": issues,
            })

    # Split across JSON files
    maint_chunks = np.array_split(range(len(maintenance_entries)), num_maint_files)
    for ci, idxs in enumerate(maint_chunks):
        subset = [maintenance_entries[j] for j in idxs]
        fname = f"maintenance_log_{ci+1:02d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(subset, f, indent=2)

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
