"""
Data generation script for Fraudulent International Call Traffic Detection task.
Generates SQLite database and workspace files for agent evaluation.
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
    "rows_per_table": 800,       # v3 = 8x base
    "num_workspace_files": 40,   # v3 = base + 3N = 10 + 30
}

# ─── Country pool with calling codes ────────────────────────────────────────
COUNTRY_POOL = [
    ("AF", "Afghanistan", "93"), ("AL", "Albania", "355"), ("DZ", "Algeria", "213"),
    ("AO", "Angola", "244"), ("AR", "Argentina", "54"), ("AM", "Armenia", "374"),
    ("AU", "Australia", "61"), ("AT", "Austria", "43"), ("AZ", "Azerbaijan", "994"),
    ("BH", "Bahrain", "973"), ("BD", "Bangladesh", "880"), ("BY", "Belarus", "375"),
    ("BE", "Belgium", "32"), ("BJ", "Benin", "229"), ("BO", "Bolivia", "591"),
    ("BA", "Bosnia", "387"), ("BW", "Botswana", "267"), ("BR", "Brazil", "55"),
    ("BG", "Bulgaria", "359"), ("BF", "Burkina Faso", "226"), ("KH", "Cambodia", "855"),
    ("CM", "Cameroon", "237"), ("CA", "Canada", "1"), ("CF", "Central African Rep", "236"),
    ("TD", "Chad", "235"), ("CL", "Chile", "56"), ("CN", "China", "86"),
    ("CO", "Colombia", "57"), ("CD", "DR Congo", "243"), ("CG", "Congo", "242"),
    ("CR", "Costa Rica", "506"), ("CI", "Ivory Coast", "225"), ("HR", "Croatia", "385"),
    ("CU", "Cuba", "53"), ("CY", "Cyprus", "357"), ("CZ", "Czech Republic", "420"),
    ("DK", "Denmark", "45"), ("DJ", "Djibouti", "253"), ("DO", "Dominican Rep", "1809"),
    ("EC", "Ecuador", "593"), ("EG", "Egypt", "20"), ("SV", "El Salvador", "503"),
    ("GQ", "Equatorial Guinea", "240"), ("ER", "Eritrea", "291"), ("EE", "Estonia", "372"),
    ("ET", "Ethiopia", "251"), ("FI", "Finland", "358"), ("FR", "France", "33"),
    ("GA", "Gabon", "241"), ("GM", "Gambia", "220"), ("GE", "Georgia", "995"),
    ("DE", "Germany", "49"), ("GH", "Ghana", "233"), ("GR", "Greece", "30"),
    ("GT", "Guatemala", "502"), ("GN", "Guinea", "224"), ("HT", "Haiti", "509"),
    ("HN", "Honduras", "504"), ("HU", "Hungary", "36"), ("IN", "India", "91"),
    ("ID", "Indonesia", "62"), ("IR", "Iran", "98"), ("IQ", "Iraq", "964"),
    ("IE", "Ireland", "353"), ("IL", "Israel", "972"), ("IT", "Italy", "39"),
    ("JM", "Jamaica", "1876"), ("JP", "Japan", "81"), ("JO", "Jordan", "962"),
    ("KZ", "Kazakhstan", "7"), ("KE", "Kenya", "254"), ("KW", "Kuwait", "965"),
    ("KG", "Kyrgyzstan", "996"), ("LA", "Laos", "856"), ("LV", "Latvia", "371"),
    ("LB", "Lebanon", "961"), ("LR", "Liberia", "231"), ("LY", "Libya", "218"),
    ("LT", "Lithuania", "370"), ("LU", "Luxembourg", "352"), ("MG", "Madagascar", "261"),
    ("MW", "Malawi", "265"), ("MY", "Malaysia", "60"), ("ML", "Mali", "223"),
    ("MR", "Mauritania", "222"), ("MX", "Mexico", "52"), ("MD", "Moldova", "373"),
    ("MN", "Mongolia", "976"), ("MA", "Morocco", "212"), ("MZ", "Mozambique", "258"),
    ("MM", "Myanmar", "95"), ("NA", "Namibia", "264"), ("NP", "Nepal", "977"),
    ("NL", "Netherlands", "31"), ("NZ", "New Zealand", "64"), ("NI", "Nicaragua", "505"),
    ("NE", "Niger", "227"), ("NG", "Nigeria", "234"), ("NO", "Norway", "47"),
    ("OM", "Oman", "968"), ("PK", "Pakistan", "92"), ("PA", "Panama", "507"),
    ("PY", "Paraguay", "595"), ("PE", "Peru", "51"), ("PH", "Philippines", "63"),
    ("PL", "Poland", "48"), ("PT", "Portugal", "351"), ("QA", "Qatar", "974"),
    ("RO", "Romania", "40"), ("RU", "Russia", "7"), ("RW", "Rwanda", "250"),
    ("SA", "Saudi Arabia", "966"), ("SN", "Senegal", "221"), ("RS", "Serbia", "381"),
    ("SL", "Sierra Leone", "232"), ("SG", "Singapore", "65"), ("SK", "Slovakia", "421"),
    ("SI", "Slovenia", "386"), ("SO", "Somalia", "252"), ("ZA", "South Africa", "27"),
    ("ES", "Spain", "34"), ("LK", "Sri Lanka", "94"), ("SD", "Sudan", "249"),
    ("SE", "Sweden", "46"), ("CH", "Switzerland", "41"), ("SY", "Syria", "963"),
    ("TW", "Taiwan", "886"), ("TJ", "Tajikistan", "992"), ("TZ", "Tanzania", "255"),
    ("TH", "Thailand", "66"), ("TG", "Togo", "228"), ("TT", "Trinidad Tobago", "1868"),
    ("TN", "Tunisia", "216"), ("TR", "Turkey", "90"), ("TM", "Turkmenistan", "993"),
    ("UG", "Uganda", "256"), ("UA", "Ukraine", "380"), ("AE", "UAE", "971"),
    ("GB", "United Kingdom", "44"), ("US", "United States", "1"), ("UY", "Uruguay", "598"),
    ("UZ", "Uzbekistan", "998"), ("VE", "Venezuela", "58"), ("VN", "Vietnam", "84"),
    ("YE", "Yemen", "967"), ("ZM", "Zambia", "260"), ("ZW", "Zimbabwe", "263"),
    ("MU", "Mauritius", "230"), ("FJ", "Fiji", "679"), ("PG", "Papua New Guinea", "675"),
    ("BT", "Bhutan", "975"), ("MV", "Maldives", "960"), ("MT", "Malta", "356"),
    ("IS", "Iceland", "354"), ("BN", "Brunei", "673"), ("LS", "Lesotho", "266"),
    ("SZ", "Eswatini", "268"), ("GY", "Guyana", "592"), ("SR", "Suriname", "597"),
    ("BB", "Barbados", "1246"), ("BS", "Bahamas", "1242"), ("AG", "Antigua", "1268"),
    ("KN", "St Kitts Nevis", "1869"), ("LC", "St Lucia", "1758"), ("VC", "St Vincent", "1784"),
    ("DM", "Dominica", "1767"), ("GD", "Grenada", "1473"), ("BZ", "Belize", "501"),
    ("TL", "Timor Leste", "670"), ("WS", "Samoa", "685"), ("TO", "Tonga", "676"),
    ("VU", "Vanuatu", "678"), ("SB", "Solomon Islands", "677"), ("KI", "Kiribati", "686"),
    ("MH", "Marshall Islands", "692"), ("PW", "Palau", "680"), ("FM", "Micronesia", "691"),
    ("NR", "Nauru", "674"), ("TV", "Tuvalu", "688"), ("CK", "Cook Islands", "682"),
    ("NU", "Niue", "683"), ("TK", "Tokelau", "690"), ("AW", "Aruba", "297"),
    ("CW", "Curacao", "5999"), ("SX", "Sint Maarten", "1721"), ("BQ", "Bonaire", "5997"),
    ("MF", "Saint Martin", "590"), ("BL", "Saint Barthelemy", "590"),
    ("PM", "Saint Pierre", "508"), ("GL", "Greenland", "299"), ("FO", "Faroe Islands", "298"),
    ("GI", "Gibraltar", "350"), ("AD", "Andorra", "376"), ("MC", "Monaco", "377"),
    ("SM", "San Marino", "378"), ("VA", "Vatican City", "379"), ("LI", "Liechtenstein", "423"),
    ("JE", "Jersey", "44"), ("GG", "Guernsey", "44"), ("IM", "Isle of Man", "44"),
    ("AX", "Aland Islands", "358"), ("NC", "New Caledonia", "687"),
    ("PF", "French Polynesia", "689"), ("WF", "Wallis Futuna", "681"),
    ("RE", "Reunion", "262"), ("YT", "Mayotte", "262"), ("KM", "Comoros", "269"),
    ("MQ", "Martinique", "596"), ("GP", "Guadeloupe", "590"), ("GF", "French Guiana", "594"),
    ("SC", "Seychelles", "248"), ("CV", "Cape Verde", "238"), ("ST", "Sao Tome", "239"),
    ("GW", "Guinea Bissau", "245"), ("MO", "Macau", "853"), ("HK", "Hong Kong", "852"),
]

CARRIER_POOL = [
    "GlobalTelecom", "TransOcean Comm", "MeridianLink", "AsiaPac Routes",
    "EuroConnect", "AfricaGateway", "LatAm Transit", "NordTel",
    "PacificBridge", "MidEast Link", "AtlanticWire", "SilkRoute Telecom",
    "PolarNet", "EquatorComm", "SunriseTelecom", "DeepSea Cable Co",
    "Highland Routes", "CoastalNet", "StarBridge Intl", "NexusGlobal",
    "PrimeTelco", "OmniRoute", "SwiftCarrier", "SkyLink Intl",
    "TerraNova Comm", "BlueWave Telecom", "CrossRoad Networks", "Pinnacle Routes",
    "VanguardTel", "HorizonConnect",
]

FRAUD_TYPES = ["IRSF", "Wangiri", "PBX_Hack", "CLI_Spoofing", "Short_Stopping"]

ORIGIN_COUNTRIES = ["US", "GB", "DE", "FR", "NL", "SG", "JP", "AU", "CA", "CH"]

SNAPSHOT_HOUR = 14
SNAPSHOT_DATE = "2026-04-25"


def _phone_number(calling_code, rng):
    """Generate a synthetic phone number."""
    n_digits = rng.choice([8, 9, 10])
    local = "".join([str(rng.randint(0, 9)) for _ in range(n_digits)])
    return f"+{calling_code}{local}"


def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()
    rng = random.Random(42)
    np_rng = np.random.RandomState(42)

    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    n = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # Pick countries for this scale
    n_countries = min(len(COUNTRY_POOL), max(50, n))
    countries = COUNTRY_POOL[:n_countries]
    cc_map = {c[0]: c[2] for c in countries}

    # Pick carriers
    n_carriers = min(len(CARRIER_POOL), max(10, n // 5))
    carriers = CARRIER_POOL[:n_carriers]

    # ═══════════════════════════════════════════════════════════════════════
    # TABLE 1: routes
    # ═══════════════════════════════════════════════════════════════════════
    cursor.execute("DROP TABLE IF EXISTS routes")
    cursor.execute("""
        CREATE TABLE routes (
            route_id TEXT PRIMARY KEY,
            carrier_name TEXT,
            origin_country TEXT,
            destination_region TEXT,
            capacity_calls_per_hour INTEGER,
            cost_per_minute_usd REAL,
            status TEXT
        )
    """)

    routes = []
    for i in range(n):
        route_id = f"RT-{i+1:04d}"
        status = "active" if rng.random() < 0.32 else rng.choice(["inactive", "maintenance"])
        routes.append({
            "route_id": route_id,
            "carrier_name": rng.choice(carriers),
            "origin_country": rng.choice(ORIGIN_COUNTRIES),
            "destination_region": rng.choice(countries)[1],
            "capacity_calls_per_hour": rng.randint(50, 500),
            "cost_per_minute_usd": round(rng.uniform(0.02, 0.55), 3),
            "status": status,
        })

    # Ensure at least 15 active routes
    active_routes = [r for r in routes if r["status"] == "active"]
    if len(active_routes) < 15:
        for r in routes:
            if r["status"] != "active" and len(active_routes) < 15:
                r["status"] = "active"
                active_routes.append(r)

    routes_df = pd.DataFrame(routes)
    routes_df.to_sql("routes", conn, index=False, if_exists="replace")

    active_routes = [r for r in routes if r["status"] == "active"]

    # Assign destination countries to active routes
    active_combos = []
    for r in active_routes:
        dest = rng.choice(countries)
        active_combos.append({
            "route_id": r["route_id"],
            "dest_country": dest[0],
            "dest_name": dest[1],
            "calling_code": dest[2],
        })

    # Select spike combos (~25% of active, min 5)
    n_spike = max(5, int(len(active_combos) * 0.25))
    spike_indices = sorted(rng.sample(range(len(active_combos)), n_spike))

    # Distribute severity tiers
    n_critical = max(2, int(n_spike * 0.35))
    n_high = max(1, int(n_spike * 0.30))
    n_medium = n_spike - n_critical - n_high
    if n_medium < 1:
        n_medium = 1
        n_high = n_spike - n_critical - n_medium

    severity_assignments = (
        ["CRITICAL"] * n_critical +
        ["HIGH"] * n_high +
        ["MEDIUM"] * n_medium
    )
    rng.shuffle(severity_assignments)

    for idx, sev in zip(spike_indices, severity_assignments):
        active_combos[idx]["is_spike"] = True
        active_combos[idx]["target_severity"] = sev

    for combo in active_combos:
        combo.setdefault("is_spike", False)
        combo.setdefault("target_severity", None)

    # ═══════════════════════════════════════════════════════════════════════
    # TABLE 2: prefix_risk
    # ═══════════════════════════════════════════════════════════════════════
    cursor.execute("DROP TABLE IF EXISTS prefix_risk")
    cursor.execute("""
        CREATE TABLE prefix_risk (
            prefix_id TEXT PRIMARY KEY,
            country_code TEXT,
            number_prefix TEXT,
            risk_score INTEGER,
            risk_tier TEXT,
            fraud_type_flags TEXT,
            last_updated TEXT
        )
    """)

    # Determine risk scores for spike destination countries
    spike_country_risk = {}
    for combo in active_combos:
        if combo["is_spike"]:
            sev = combo["target_severity"]
            cc = combo["dest_country"]
            if sev == "CRITICAL":
                spike_country_risk[cc] = max(spike_country_risk.get(cc, 0), rng.randint(75, 95))
            elif sev == "HIGH":
                spike_country_risk[cc] = max(spike_country_risk.get(cc, 0), rng.randint(52, 68))
            elif sev == "MEDIUM":
                spike_country_risk[cc] = max(spike_country_risk.get(cc, 0), rng.randint(32, 48))

    prefix_rows = []
    prefixes_per_country = max(1, n // len(countries))
    prefix_id_counter = 0
    for c_code, c_name, calling_code in countries:
        n_pfx = rng.randint(max(1, prefixes_per_country - 1), prefixes_per_country + 2)
        for j in range(n_pfx):
            prefix_id_counter += 1
            prefix = f"+{calling_code}{rng.randint(10, 99)}"

            if c_code in spike_country_risk:
                if j == 0:
                    risk_score = spike_country_risk[c_code]
                else:
                    risk_score = rng.randint(5, min(spike_country_risk[c_code] - 5, 35))
            else:
                risk_score = rng.randint(5, 35)

            if risk_score >= 70:
                risk_tier = "critical"
            elif risk_score >= 50:
                risk_tier = "high"
            elif risk_score >= 30:
                risk_tier = "medium"
            else:
                risk_tier = "low"

            fraud_flags = ""
            if risk_score >= 50:
                fraud_flags = ",".join(rng.sample(FRAUD_TYPES, rng.randint(1, 3)))
            elif risk_score >= 30:
                fraud_flags = rng.choice(FRAUD_TYPES)

            prefix_rows.append({
                "prefix_id": f"PFX-{prefix_id_counter:05d}",
                "country_code": c_code,
                "number_prefix": prefix,
                "risk_score": risk_score,
                "risk_tier": risk_tier,
                "fraud_type_flags": fraud_flags,
                "last_updated": (datetime(2026, 4, 1) + timedelta(days=rng.randint(0, 24))).strftime("%Y-%m-%d"),
            })

    # Pad to meet minimum
    while len(prefix_rows) < n:
        prefix_id_counter += 1
        c = rng.choice(countries)
        prefix_rows.append({
            "prefix_id": f"PFX-{prefix_id_counter:05d}",
            "country_code": c[0],
            "number_prefix": f"+{c[2]}{rng.randint(10, 99)}",
            "risk_score": rng.randint(5, 30),
            "risk_tier": "low",
            "fraud_type_flags": "",
            "last_updated": "2026-04-20",
        })

    prefix_df = pd.DataFrame(prefix_rows)
    prefix_df.to_sql("prefix_risk", conn, index=False, if_exists="replace")

    # ═══════════════════════════════════════════════════════════════════════
    # TABLE 3: known_fraud_numbers
    # ═══════════════════════════════════════════════════════════════════════
    cursor.execute("DROP TABLE IF EXISTS known_fraud_numbers")
    cursor.execute("""
        CREATE TABLE known_fraud_numbers (
            fraud_id TEXT PRIMARY KEY,
            phone_number TEXT,
            fraud_type TEXT,
            date_flagged TEXT,
            reporting_source TEXT,
            is_active INTEGER
        )
    """)

    fraud_sources = ["Interpol Telecom Unit", "CFCA Alert", "National Fraud DB",
                     "Carrier Report", "GSMA FraudWatch", "Internal Detection"]

    fraud_numbers = []
    fraud_phone_set = set()
    for i in range(n):
        if i < n // 3 and spike_country_risk:
            fc = rng.choice(list(spike_country_risk.keys()))
        else:
            fc = rng.choice(countries)[0]
        calling_code = cc_map.get(fc, "1")
        phone = _phone_number(calling_code, rng)
        while phone in fraud_phone_set:
            phone = _phone_number(calling_code, rng)
        fraud_phone_set.add(phone)
        fraud_numbers.append({
            "fraud_id": f"FRD-{i+1:05d}",
            "phone_number": phone,
            "fraud_type": rng.choice(FRAUD_TYPES),
            "date_flagged": (datetime(2025, 1, 1) + timedelta(days=rng.randint(0, 480))).strftime("%Y-%m-%d"),
            "reporting_source": rng.choice(fraud_sources),
            "is_active": 1 if rng.random() < 0.85 else 0,
        })

    # Build lookup for active fraud numbers by country
    fraud_by_country = {}
    for fn in fraud_numbers:
        if fn["is_active"]:
            for c_code, _, calling_code in countries:
                if fn["phone_number"].startswith(f"+{calling_code}"):
                    fraud_by_country.setdefault(c_code, []).append(fn["phone_number"])
                    break

    # ═══════════════════════════════════════════════════════════════════════
    # TABLE 4: historical_baselines
    # ═══════════════════════════════════════════════════════════════════════
    cursor.execute("DROP TABLE IF EXISTS historical_baselines")
    cursor.execute("""
        CREATE TABLE historical_baselines (
            baseline_id TEXT PRIMARY KEY,
            route_id TEXT,
            destination_country TEXT,
            hour_of_day INTEGER,
            avg_calls_per_hour REAL,
            std_dev_calls REAL
        )
    """)

    baseline_rows = []
    baseline_id_counter = 0
    combo_baselines = {}

    for combo in active_combos:
        rid = combo["route_id"]
        dc = combo["dest_country"]
        avg_calls = round(rng.uniform(8, 25), 1)
        std_calls = round(avg_calls * rng.uniform(0.15, 0.35), 1)
        combo_baselines[(rid, dc)] = {"avg": avg_calls, "std": std_calls}

        baseline_id_counter += 1
        baseline_rows.append({
            "baseline_id": f"BL-{baseline_id_counter:05d}",
            "route_id": rid,
            "destination_country": dc,
            "hour_of_day": SNAPSHOT_HOUR,
            "avg_calls_per_hour": avg_calls,
            "std_dev_calls": std_calls,
        })

        other_hours = rng.sample([h for h in range(24) if h != SNAPSHOT_HOUR], min(3, 23))
        for h in other_hours:
            baseline_id_counter += 1
            h_avg = round(avg_calls * rng.uniform(0.5, 1.5), 1)
            h_std = round(h_avg * rng.uniform(0.15, 0.35), 1)
            baseline_rows.append({
                "baseline_id": f"BL-{baseline_id_counter:05d}",
                "route_id": rid,
                "destination_country": dc,
                "hour_of_day": h,
                "avg_calls_per_hour": h_avg,
                "std_dev_calls": h_std,
            })

    n_baselines_target = n * 2
    while len(baseline_rows) < n_baselines_target:
        baseline_id_counter += 1
        combo = rng.choice(active_combos)
        h = rng.randint(0, 23)
        baseline_rows.append({
            "baseline_id": f"BL-{baseline_id_counter:05d}",
            "route_id": combo["route_id"],
            "destination_country": combo["dest_country"],
            "hour_of_day": h,
            "avg_calls_per_hour": round(rng.uniform(5, 30), 1),
            "std_dev_calls": round(rng.uniform(1, 8), 1),
        })

    baseline_df = pd.DataFrame(baseline_rows)
    baseline_df.to_sql("historical_baselines", conn, index=False, if_exists="replace")

    # ═══════════════════════════════════════════════════════════════════════
    # TABLE 5: cdr_records
    # ═══════════════════════════════════════════════════════════════════════
    cursor.execute("DROP TABLE IF EXISTS cdr_records")
    cursor.execute("""
        CREATE TABLE cdr_records (
            cdr_id TEXT PRIMARY KEY,
            caller_number TEXT,
            callee_number TEXT,
            route_id TEXT,
            destination_country TEXT,
            duration_seconds INTEGER,
            call_timestamp TEXT,
            cost_usd REAL
        )
    """)

    combo_current_volumes = {}
    for combo in active_combos:
        rid = combo["route_id"]
        dc = combo["dest_country"]
        bl = combo_baselines[(rid, dc)]
        avg = bl["avg"]

        if combo["is_spike"]:
            sev = combo["target_severity"]
            if sev == "CRITICAL":
                spike_ratio = rng.uniform(3.2, 4.5)
            elif sev == "HIGH":
                spike_ratio = rng.uniform(2.6, 3.4)
            else:
                spike_ratio = rng.uniform(2.1, 2.8)
            current_vol = max(6, int(round(avg * spike_ratio)))
        else:
            current_vol = max(3, int(round(avg * rng.uniform(0.7, 1.4))))

        combo_current_volumes[(rid, dc)] = current_vol
        combo["current_volume"] = current_vol

    # Generate CDRs
    cdr_rows = []
    cdr_id_counter = 0
    base_time = datetime(2026, 4, 25, SNAPSHOT_HOUR, 0, 0)

    for combo in active_combos:
        rid = combo["route_id"]
        dc = combo["dest_country"]
        cc = combo["calling_code"]
        vol = combo_current_volumes[(rid, dc)]

        fraud_call_count = 0
        fraud_phones_for_combo = []
        if combo["is_spike"]:
            sev = combo["target_severity"]
            available_fraud = list(fraud_by_country.get(dc, []))
            if sev == "CRITICAL":
                fraud_call_count = rng.randint(3, min(8, vol))
            elif sev == "HIGH":
                fraud_call_count = rng.randint(2, min(5, vol))
            else:
                fraud_call_count = rng.randint(1, min(3, vol))

            # Create additional fraud numbers if needed
            if len(available_fraud) < fraud_call_count:
                for _ in range(fraud_call_count - len(available_fraud)):
                    new_phone = _phone_number(cc, rng)
                    while new_phone in fraud_phone_set:
                        new_phone = _phone_number(cc, rng)
                    fraud_phone_set.add(new_phone)
                    fraud_numbers.append({
                        "fraud_id": f"FRD-{len(fraud_numbers)+1:05d}",
                        "phone_number": new_phone,
                        "fraud_type": rng.choice(FRAUD_TYPES),
                        "date_flagged": "2026-04-20",
                        "reporting_source": "Internal Detection",
                        "is_active": 1,
                    })
                    available_fraud.append(new_phone)
                    fraud_by_country.setdefault(dc, []).append(new_phone)

            if available_fraud:
                fraud_phones_for_combo = rng.sample(
                    available_fraud, min(fraud_call_count, len(available_fraud))
                )
            fraud_call_count = len(fraud_phones_for_combo)
            combo["fraud_call_count"] = fraud_call_count

        origin_cc = cc_map.get(rng.choice(ORIGIN_COUNTRIES), "1")
        for j in range(vol):
            cdr_id_counter += 1
            caller = _phone_number(origin_cc, rng)
            if j < fraud_call_count:
                callee = fraud_phones_for_combo[j % len(fraud_phones_for_combo)]
            else:
                callee = _phone_number(cc, rng)
                while callee in fraud_phone_set:
                    callee = _phone_number(cc, rng)

            ts = base_time + timedelta(seconds=rng.randint(0, 3599))
            cdr_rows.append({
                "cdr_id": f"CDR-{cdr_id_counter:07d}",
                "caller_number": caller,
                "callee_number": callee,
                "route_id": rid,
                "destination_country": dc,
                "duration_seconds": rng.randint(1, 1800),
                "call_timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "cost_usd": round(rng.uniform(0.05, 15.0), 2),
            })

    # Re-save fraud table with any added numbers
    fraud_df = pd.DataFrame(fraud_numbers)
    fraud_df.to_sql("known_fraud_numbers", conn, index=False, if_exists="replace")

    # Pad CDRs to meet minimum
    n_cdrs_target = n * 5
    while len(cdr_rows) < n_cdrs_target:
        cdr_id_counter += 1
        combo = rng.choice([c for c in active_combos if not c["is_spike"]])
        rid = combo["route_id"]
        dc = combo["dest_country"]
        cc = combo["calling_code"]
        origin_cc = cc_map.get(rng.choice(ORIGIN_COUNTRIES), "1")
        ts = base_time + timedelta(seconds=rng.randint(0, 3599))
        callee = _phone_number(cc, rng)
        while callee in fraud_phone_set:
            callee = _phone_number(cc, rng)
        cdr_rows.append({
            "cdr_id": f"CDR-{cdr_id_counter:07d}",
            "caller_number": _phone_number(origin_cc, rng),
            "callee_number": callee,
            "route_id": rid,
            "destination_country": dc,
            "duration_seconds": rng.randint(1, 1800),
            "call_timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "cost_usd": round(rng.uniform(0.05, 15.0), 2),
        })
        combo_current_volumes[(rid, dc)] = combo_current_volumes.get((rid, dc), 0) + 1
        combo["current_volume"] = combo_current_volumes[(rid, dc)]

    cdr_df = pd.DataFrame(cdr_rows)
    cdr_df.to_sql("cdr_records", conn, index=False, if_exists="replace")

    conn.commit()

    # ═══════════════════════════════════════════════════════════════════════
    # WORKSPACE: Traffic snapshot files (scalable data files)
    # ═══════════════════════════════════════════════════════════════════════
    combos_for_snapshots = list(active_combos)
    rng.shuffle(combos_for_snapshots)
    snapshot_groups = [[] for _ in range(n_files)]
    for i, combo in enumerate(combos_for_snapshots):
        snapshot_groups[i % n_files].append(combo)

    for file_idx in range(n_files):
        snapshot = {
            "snapshot_id": f"SNAP-{file_idx+1:03d}",
            "time_window_start": f"{SNAPSHOT_DATE}T{SNAPSHOT_HOUR:02d}:00:00",
            "time_window_end": f"{SNAPSHOT_DATE}T{SNAPSHOT_HOUR+1:02d}:00:00",
            "monitoring_hour": SNAPSHOT_HOUR,
            "traffic_data": [],
        }
        for combo in snapshot_groups[file_idx]:
            rid = combo["route_id"]
            dc = combo["dest_country"]
            combo_cdrs = [c for c in cdr_rows
                          if c["route_id"] == rid and c["destination_country"] == dc]
            total_dur = sum(c["duration_seconds"] for c in combo_cdrs)
            total_cost = sum(c["cost_usd"] for c in combo_cdrs)
            snapshot["traffic_data"].append({
                "route_id": rid,
                "destination_country": dc,
                "call_count": len(combo_cdrs),
                "total_duration_seconds": total_dur,
                "total_cost_usd": round(total_cost, 2),
            })

        filepath = os.path.join(workspace, f"traffic_snapshot_{file_idx+1:03d}.json")
        with open(filepath, "w") as f:
            json.dump(snapshot, f, indent=2)

    # ═══════════════════════════════════════════════════════════════════════
    # WORKSPACE: Fixed configuration / policy files
    # ═══════════════════════════════════════════════════════════════════════

    # --- detection_thresholds.yaml ---
    thresholds = {
        "spike_detection": {
            "multiplier": 2.0,
            "min_calls_threshold": 5,
            "baseline_hour_match": True,
        },
        "monitoring": {
            "snapshot_aggregation": "sum",
            "baseline_metric": "avg_calls_per_hour",
        },
    }
    with open(os.path.join(workspace, "detection_thresholds.yaml"), "w") as f:
        yaml.dump(thresholds, f, default_flow_style=False, sort_keys=False)

    # --- alert_classification.json ---
    classification = {
        "severity_levels": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        "classification_rules": [
            {
                "severity": "CRITICAL",
                "min_spike_ratio": 3.0,
                "min_country_risk_score": 70,
                "min_fraud_call_count": 3,
                "logic": "ALL conditions must be met"
            },
            {
                "severity": "HIGH",
                "min_spike_ratio": 2.5,
                "additional_conditions": [
                    {"field": "country_risk_score", "min_value": 50},
                    {"field": "fraud_call_count", "min_value": 2}
                ],
                "additional_logic": "Spike ratio must be met AND at least ONE additional condition"
            },
            {
                "severity": "MEDIUM",
                "min_spike_ratio": 2.0,
                "additional_conditions": [
                    {"field": "country_risk_score", "min_value": 30},
                    {"field": "fraud_call_count", "min_value": 1}
                ],
                "additional_logic": "Spike ratio must be met AND at least ONE additional condition"
            },
            {
                "severity": "LOW",
                "min_spike_ratio": 2.0,
                "additional_conditions": [],
                "additional_logic": "Only spike ratio threshold required, no additional conditions"
            }
        ],
        "evaluation_order": "Rules are evaluated from CRITICAL to LOW. The first matching rule determines the alert severity."
    }
    with open(os.path.join(workspace, "alert_classification.json"), "w") as f:
        json.dump(classification, f, indent=2)

    # --- route_blocking_policy.md ---
    policy_text = """# Route Blocking Policy

When a traffic anomaly is detected and classified by severity, the following response actions shall apply.

For alerts classified as CRITICAL severity, the recommended action is "immediate_block". All traffic on the affected route to the flagged destination must be halted within fifteen minutes of alert generation. No manual review is required prior to blocking.

For alerts classified as HIGH severity, the recommended action is "block_pending_review". The route should be blocked immediately, but a senior analyst must review the block within four hours. If the review determines the block was a false positive, the route may be reinstated.

For alerts classified as MEDIUM severity, the recommended action is "rate_limit". Traffic on the route to the flagged destination should be throttled to fifty percent of normal capacity. An investigation ticket must be opened and resolved within twenty-four hours.

For alerts classified as LOW severity, the recommended action is "monitor". No immediate traffic restriction is required, but the route must be placed under enhanced monitoring for a period of twenty-four hours with fifteen-minute sampling intervals.

Only alerts of severity CRITICAL or HIGH shall be included in the recommended route blocks report. MEDIUM and LOW severity alerts appear only in the general alert report.

Alert identifiers in the alert report must follow the format ALT-NNN where NNN is a zero-padded three-digit sequential number starting from 001. Alerts shall be ordered by severity priority (CRITICAL first, then HIGH, then MEDIUM, then LOW), and within the same severity level by spike ratio in descending order."""
    with open(os.path.join(workspace, "route_blocking_policy.md"), "w") as f:
        f.write(policy_text.strip())

    # --- carrier_directory.csv ---
    carrier_records = []
    for i, carrier in enumerate(carriers):
        carrier_records.append({
            "carrier_id": f"CAR-{i+1:03d}",
            "carrier_name": carrier,
            "headquarters": fake.city() + ", " + fake.country(),
            "support_email": f"noc@{carrier.lower().replace(' ', '')}.com",
            "sla_tier": rng.choice(["Platinum", "Gold", "Silver", "Bronze"]),
            "contract_expiry": (datetime(2026, 6, 1) + timedelta(days=rng.randint(0, 730))).strftime("%Y-%m-%d"),
        })
    carrier_df = pd.DataFrame(carrier_records)
    carrier_df.to_csv(os.path.join(workspace, "carrier_directory.csv"), index=False)

    # --- fraud_intelligence_bulletin.txt ---
    bulletin_lines = [
        "=== FRAUD INTELLIGENCE BULLETIN ===",
        f"Date: {SNAPSHOT_DATE}",
        f"Monitoring Window: {SNAPSHOT_HOUR:02d}:00 - {SNAPSHOT_HOUR+1:02d}:00 UTC",
        "",
        "CURRENT THREAT LANDSCAPE:",
        "",
        "International Revenue Share Fraud (IRSF) remains the primary threat vector",
        "for interconnect traffic. Premium rate number abuse continues to be observed",
        "across multiple African and Southeast Asian destinations.",
        "",
        "Wangiri (one-ring) fraud campaigns have been detected targeting European",
        "origin networks with callbacks to high-cost destinations.",
        "",
        "PBX hacking incidents have increased by 15% quarter-over-quarter, with",
        "compromised systems generating high-volume traffic to premium destinations.",
        "",
        "MONITORING INSTRUCTIONS:",
        "",
        "All traffic snapshots for the current monitoring window should be aggregated",
        "to determine per-route, per-destination call volumes. These volumes must be",
        "compared against historical baselines for the corresponding hour of day.",
        "",
        "Any route-destination combination whose current call count exceeds the",
        "configured spike multiplier times the historical average for the matching",
        "hour of day should be flagged for further analysis. Combinations where",
        "current traffic is below the minimum calls threshold should be excluded",
        "from spike analysis regardless of ratio.",
        "",
        "For flagged combinations, individual call detail records must be retrieved",
        "and each destination number checked against the known fraudulent number",
        "database. The country-level risk score for each destination must also be",
        "obtained to support severity classification.",
        "",
        "END OF BULLETIN",
    ]
    with open(os.path.join(workspace, "fraud_intelligence_bulletin.txt"), "w") as f:
        f.write("\n".join(bulletin_lines))

    conn.close()
    print(f"Data generation complete: {db_path}, {workspace}/")
    print(f"  Routes: {len(routes)}")
    print(f"  Prefix risk entries: {len(prefix_rows)}")
    print(f"  Fraud numbers: {len(fraud_numbers)}")
    print(f"  Baseline entries: {len(baseline_rows)}")
    print(f"  CDR records: {len(cdr_rows)}")
    print(f"  Traffic snapshot files: {n_files}")
    print(f"  Active route combos: {len(active_combos)}")
    print(f"  Spike combos: {n_spike}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", type=str, required=True)
    parser.add_argument("--workspace", type=str, required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
