"""
VoIP Call Drop Triage - Data Generation Script
Generates database and workspace files for fault localization task.
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
    "rows_per_table": 160,
    "num_workspace_files": 24,
}

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

# ---------- constants ----------

FIRMWARE_VERSIONS = [
    "4.1.0", "4.1.2", "4.2.0", "4.2.1", "4.3.0",
    "5.0.0", "5.0.1", "5.1.0", "5.2.0", "5.3.0",
]
ENDPOINT_MODELS = [
    "Polycom VVX-450", "Cisco 8845", "Yealink T58A",
    "Grandstream GRP2616", "Avaya J179",
]
SIP_ERROR_CODES = [
    ("408", "Request Timeout"),
    ("480", "Temporarily Unavailable"),
    ("486", "Busy Here"),
    ("500", "Server Internal Error"),
    ("502", "Bad Gateway"),
    ("503", "Service Unavailable"),
    ("504", "Server Timeout"),
]
LOCATIONS = [
    "Building-A Floor-1", "Building-A Floor-2", "Building-A Floor-3",
    "Building-B Floor-1", "Building-B Floor-2", "Building-B Floor-3",
    "Building-C Floor-1", "Building-C Floor-2",
    "Data-Center-East", "Data-Center-West",
]
FREQUENCY_BANDS = ["2.4GHz", "5GHz", "6GHz"]
AP_VENDORS = ["Cisco Meraki", "Aruba", "Ubiquiti", "Ruckus"]
PROBE_TYPES = ["ICMP", "RTP-SIM", "TWAMP"]

BASE_TIME = datetime(2025, 6, 15, 8, 0, 0)


def create_tables(conn):
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS sip_servers (
        server_id TEXT PRIMARY KEY,
        server_name TEXT,
        ip_address TEXT,
        region TEXT,
        status TEXT,
        max_concurrent_calls INTEGER,
        current_load_pct REAL
    );
    CREATE TABLE IF NOT EXISTS network_probes (
        probe_id TEXT PRIMARY KEY,
        probe_name TEXT,
        location TEXT,
        subnet TEXT,
        probe_type TEXT,
        status TEXT,
        deployed_date TEXT
    );
    CREATE TABLE IF NOT EXISTS endpoints (
        endpoint_id TEXT PRIMARY KEY,
        mac_address TEXT,
        model TEXT,
        firmware_version TEXT,
        location TEXT,
        ap_id TEXT,
        sip_server_id TEXT,
        registered INTEGER,
        last_reboot TEXT
    );
    CREATE TABLE IF NOT EXISTS wireless_aps (
        ap_id TEXT PRIMARY KEY,
        ap_name TEXT,
        vendor TEXT,
        location TEXT,
        frequency_band TEXT,
        channel INTEGER,
        client_health_score REAL,
        connected_clients INTEGER,
        max_clients INTEGER,
        uptime_hours REAL
    );
    CREATE TABLE IF NOT EXISTS packet_loss_metrics (
        metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
        probe_id TEXT,
        endpoint_id TEXT,
        timestamp TEXT,
        packet_loss_pct REAL,
        jitter_ms REAL,
        latency_ms REAL,
        mos_score REAL,
        FOREIGN KEY (probe_id) REFERENCES network_probes(probe_id),
        FOREIGN KEY (endpoint_id) REFERENCES endpoints(endpoint_id)
    );
    CREATE TABLE IF NOT EXISTS sip_error_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sip_server_id TEXT,
        endpoint_id TEXT,
        call_id TEXT,
        timestamp TEXT,
        error_code TEXT,
        error_message TEXT,
        retry_count INTEGER,
        FOREIGN KEY (sip_server_id) REFERENCES sip_servers(server_id),
        FOREIGN KEY (endpoint_id) REFERENCES endpoints(endpoint_id)
    );
    CREATE TABLE IF NOT EXISTS call_records (
        call_id TEXT PRIMARY KEY,
        caller_endpoint_id TEXT,
        callee_endpoint_id TEXT,
        sip_server_id TEXT,
        start_time TEXT,
        duration_seconds REAL,
        status TEXT,
        drop_reason TEXT,
        FOREIGN KEY (caller_endpoint_id) REFERENCES endpoints(endpoint_id),
        FOREIGN KEY (callee_endpoint_id) REFERENCES endpoints(endpoint_id),
        FOREIGN KEY (sip_server_id) REFERENCES sip_servers(server_id)
    );
    """)
    conn.commit()


def gen_sip_servers(conn, n_rows):
    servers = []
    n_servers = max(6, n_rows // 12)
    for i in range(n_servers):
        sid = f"SIP-{i+1:03d}"
        servers.append({
            "server_id": sid,
            "server_name": f"sip-gw-{fake.lexify('???')}-{i+1}",
            "ip_address": fake.ipv4_private(),
            "region": random.choice(["US-East", "US-West", "EU-Central", "APAC"]),
            "status": random.choices(["active", "degraded", "maintenance"], weights=[0.7, 0.2, 0.1])[0],
            "max_concurrent_calls": random.choice([500, 1000, 2000]),
            "current_load_pct": round(random.uniform(10, 95), 1),
        })
    df = pd.DataFrame(servers)
    df.to_sql("sip_servers", conn, if_exists="replace", index=False)
    return df


def gen_network_probes(conn, n_rows):
    probes = []
    n_probes = max(8, n_rows // 8)
    for i in range(n_probes):
        pid = f"PRB-{i+1:04d}"
        loc = random.choice(LOCATIONS)
        probes.append({
            "probe_id": pid,
            "probe_name": f"probe-{loc.lower().replace(' ', '-')}-{i+1}",
            "location": loc,
            "subnet": f"10.{random.randint(1,254)}.{random.randint(0,254)}.0/24",
            "probe_type": random.choice(PROBE_TYPES),
            "status": random.choices(["active", "inactive"], weights=[0.85, 0.15])[0],
            "deployed_date": (BASE_TIME - timedelta(days=random.randint(30, 730))).strftime("%Y-%m-%d"),
        })
    df = pd.DataFrame(probes)
    df.to_sql("network_probes", conn, if_exists="replace", index=False)
    return df


def gen_wireless_aps(conn, n_rows):
    aps = []
    n_aps = max(10, n_rows // 6)
    for i in range(n_aps):
        aid = f"AP-{i+1:04d}"
        loc = random.choice(LOCATIONS)
        health = round(random.uniform(20, 100), 1)
        aps.append({
            "ap_id": aid,
            "ap_name": f"ap-{loc.lower().replace(' ', '-')}-{i+1}",
            "vendor": random.choice(AP_VENDORS),
            "location": loc,
            "frequency_band": random.choice(FREQUENCY_BANDS),
            "channel": random.choice([1, 6, 11, 36, 40, 44, 48, 149, 153, 157]),
            "client_health_score": health,
            "connected_clients": random.randint(5, 80),
            "max_clients": random.choice([50, 100, 128]),
            "uptime_hours": round(random.uniform(1, 8760), 1),
        })
    df = pd.DataFrame(aps)
    df.to_sql("wireless_aps", conn, if_exists="replace", index=False)
    return df


def gen_endpoints(conn, n_rows, ap_df, sip_df):
    endpoints = []
    ap_ids = ap_df["ap_id"].tolist()
    sip_ids = sip_df["server_id"].tolist()
    for i in range(n_rows):
        eid = f"EP-{i+1:05d}"
        endpoints.append({
            "endpoint_id": eid,
            "mac_address": fake.mac_address(),
            "model": random.choice(ENDPOINT_MODELS),
            "firmware_version": random.choice(FIRMWARE_VERSIONS),
            "location": random.choice(LOCATIONS),
            "ap_id": random.choice(ap_ids),
            "sip_server_id": random.choice(sip_ids),
            "registered": random.choices([1, 0], weights=[0.9, 0.1])[0],
            "last_reboot": (BASE_TIME - timedelta(days=random.randint(0, 90))).strftime("%Y-%m-%d %H:%M:%S"),
        })
    df = pd.DataFrame(endpoints)
    df.to_sql("endpoints", conn, if_exists="replace", index=False)
    return df


def gen_packet_loss_metrics(conn, n_rows, probe_df, endpoint_df):
    rows = []
    probe_ids = probe_df["probe_id"].tolist()
    ep_ids = endpoint_df["endpoint_id"].tolist()
    for i in range(n_rows * 3):
        ts = BASE_TIME + timedelta(minutes=random.randint(0, 720))
        loss = max(0, np.random.exponential(2.5))
        jitter = max(0, np.random.exponential(8))
        latency = max(5, np.random.normal(40, 20))
        mos = max(1.0, min(5.0, 5.0 - loss * 0.3 - jitter * 0.02))
        rows.append({
            "probe_id": random.choice(probe_ids),
            "endpoint_id": random.choice(ep_ids),
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "packet_loss_pct": round(loss, 2),
            "jitter_ms": round(jitter, 2),
            "latency_ms": round(latency, 2),
            "mos_score": round(mos, 2),
        })
    df = pd.DataFrame(rows)
    df.to_sql("packet_loss_metrics", conn, if_exists="replace", index=False)
    return df


def gen_sip_error_logs(conn, n_rows, sip_df, endpoint_df):
    rows = []
    sip_ids = sip_df["server_id"].tolist()
    ep_ids = endpoint_df["endpoint_id"].tolist()
    for i in range(n_rows * 2):
        code, msg = random.choice(SIP_ERROR_CODES)
        ts = BASE_TIME + timedelta(minutes=random.randint(0, 720))
        rows.append({
            "sip_server_id": random.choice(sip_ids),
            "endpoint_id": random.choice(ep_ids),
            "call_id": f"CALL-{fake.uuid4()[:8].upper()}",
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "error_code": code,
            "error_message": msg,
            "retry_count": random.randint(0, 5),
        })
    df = pd.DataFrame(rows)
    df.to_sql("sip_error_logs", conn, if_exists="replace", index=False)
    return df


def gen_call_records(conn, n_rows, endpoint_df, sip_df):
    rows = []
    ep_ids = endpoint_df["endpoint_id"].tolist()
    sip_ids = sip_df["server_id"].tolist()
    statuses = ["completed", "dropped", "failed", "busy"]
    drop_reasons = ["packet_loss", "server_timeout", "firmware_crash", "ap_roaming", "codec_mismatch", None]
    for i in range(n_rows * 2):
        st = random.choices(statuses, weights=[0.55, 0.25, 0.12, 0.08])[0]
        caller = random.choice(ep_ids)
        callee = random.choice([e for e in ep_ids if e != caller] or ep_ids)
        ts = BASE_TIME + timedelta(minutes=random.randint(0, 720))
        rows.append({
            "call_id": f"CALL-{i+1:06d}",
            "caller_endpoint_id": caller,
            "callee_endpoint_id": callee,
            "sip_server_id": random.choice(sip_ids),
            "start_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": round(random.uniform(0, 3600), 1) if st == "completed" else round(random.uniform(0, 120), 1),
            "status": st,
            "drop_reason": random.choice(drop_reasons) if st == "dropped" else None,
        })
    df = pd.DataFrame(rows)
    df.to_sql("call_records", conn, if_exists="replace", index=False)
    return df


# ---------- workspace generation ----------

def gen_workspace(workspace, conn, endpoint_df, ap_df, probe_df, sip_df):
    os.makedirs(workspace, exist_ok=True)

    n_scalable = SCALE["num_workspace_files"]
    n_probe_files = n_scalable // 2
    n_ap_files = n_scalable - n_probe_files

    # --- Scalable file set 1: Probe snapshot CSVs ---
    probe_ids = probe_df["probe_id"].tolist()
    c = conn.cursor()
    for i in range(n_probe_files):
        pid = probe_ids[i % len(probe_ids)]
        c.execute(
            "SELECT endpoint_id, timestamp, packet_loss_pct, jitter_ms, latency_ms, mos_score "
            "FROM packet_loss_metrics WHERE probe_id = ? ORDER BY timestamp LIMIT 50",
            (pid,),
        )
        rows = c.fetchall()
        df = pd.DataFrame(rows, columns=["endpoint_id", "timestamp", "packet_loss_pct", "jitter_ms", "latency_ms", "mos_score"])
        notes = []
        for _, r in df.iterrows():
            if r["packet_loss_pct"] > 5:
                notes.append(random.choice(["flagged", "under_review", "escalated"]))
            else:
                notes.append("normal")
        df["tech_note"] = notes
        fname = f"probe_snapshot_{pid.lower().replace('-', '_')}_batch{i+1}.csv"
        df.to_csv(os.path.join(workspace, fname), index=False)

    # --- Scalable file set 2: AP health report JSONs ---
    ap_ids = ap_df["ap_id"].tolist()
    for i in range(n_ap_files):
        aid = ap_ids[i % len(ap_ids)]
        ap_row = ap_df[ap_df["ap_id"] == aid].iloc[0]
        c.execute(
            "SELECT endpoint_id, firmware_version, model FROM endpoints WHERE ap_id = ?",
            (aid,),
        )
        ep_rows = c.fetchall()
        report = {
            "ap_id": aid,
            "ap_name": ap_row["ap_name"],
            "location": ap_row["location"],
            "vendor": ap_row["vendor"],
            "snapshot_time": (BASE_TIME + timedelta(hours=random.randint(0, 12))).isoformat(),
            "client_health_score": float(ap_row["client_health_score"]),
            "channel_utilization_pct": round(random.uniform(10, 95), 1),
            "noise_floor_dBm": round(random.uniform(-95, -60), 1),
            "co_channel_interference": random.choice(["low", "medium", "high"]),
            "connected_endpoints": [
                {"endpoint_id": r[0], "firmware": r[1], "model": r[2],
                 "rssi_dBm": round(random.uniform(-80, -30), 1)}
                for r in ep_rows[:15]
            ],
        }
        fname = f"ap_health_{aid.lower().replace('-', '_')}_report{i+1}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(report, f, indent=2)

    # --- Fixed config files (not counted in SCALE) ---

    # 1. Thresholds config
    thresholds = {
        "packet_loss_critical_pct": 5.0,
        "packet_loss_warning_pct": 2.0,
        "jitter_critical_ms": 30.0,
        "jitter_warning_ms": 15.0,
        "latency_critical_ms": 150.0,
        "latency_warning_ms": 80.0,
        "mos_critical": 3.0,
        "mos_warning": 3.5,
        "ap_health_critical": 50.0,
        "ap_health_warning": 70.0,
        "server_load_critical_pct": 85.0,
        "sip_error_rate_critical_per_hour": 10,
    }
    with open(os.path.join(workspace, "thresholds.yaml"), "w") as f:
        yaml.dump(thresholds, f, default_flow_style=False)

    # 2. Firmware compatibility matrix
    fw_compat = {
        "known_buggy_versions": ["4.1.0", "4.2.0", "5.0.0"],
        "recommended_versions": ["4.2.1", "4.3.0", "5.2.0", "5.3.0"],
        "eol_versions": ["4.1.0", "4.1.2"],
        "codec_issue_versions": ["5.0.0", "5.0.1"],
        "known_bugs": {
            "4.1.0": "Memory leak causes call drops after 2h continuous use",
            "4.2.0": "SIP re-INVITE handling failure under packet loss >3%",
            "5.0.0": "G.722 codec negotiation failure with Ogg fallback",
        },
    }
    with open(os.path.join(workspace, "firmware_compatibility.json"), "w") as f:
        json.dump(fw_compat, f, indent=2)

    # 3. Severity classification rules
    severity_rules = """# Severity Classification Rules

## Fault Severity Levels

A fault is classified as CRITICAL if any of the following hold:
- Average packet loss for the source exceeds the critical packet loss threshold AND at least one associated SIP error code is 503 or 500.
- The access point health score is below the critical AP health threshold AND packet loss is above the warning threshold.
- The endpoint firmware is on the known buggy list AND the endpoint has more than 3 SIP errors in the observation window.

A fault is classified as HIGH if any of the following hold:
- Average packet loss exceeds the warning threshold but is below critical AND jitter exceeds the critical jitter threshold.
- The SIP server current load exceeds the server load critical threshold AND the endpoint has at least 2 SIP errors.
- The firmware version is end-of-life.

A fault is classified as MEDIUM if any of the following hold:
- Average packet loss exceeds the warning threshold with no other compounding factor.
- MOS score is below the MOS warning threshold.
- AP health score is below the AP warning threshold but above critical.

All other faults are classified as LOW.

## Fault Source Attribution

Each fault must be attributed to exactly one primary source:
- "network" if packet loss or jitter is the dominant degradation factor.
- "sip_server" if SIP errors are the primary issue and network metrics are within warning thresholds.
- "firmware" if the endpoint runs a known buggy or EOL firmware and no network/server issue dominates.
- "wireless" if the AP health score is below critical and the endpoint connects to that AP.

When multiple sources apply, choose the one with the highest severity. If tied, prefer in this order: network > sip_server > wireless > firmware.
"""
    with open(os.path.join(workspace, "severity_rules.md"), "w") as f:
        f.write(severity_rules)

    # 4. Location-subnet mapping
    location_map = {}
    for _, row in probe_df.iterrows():
        loc = row["location"]
        if loc not in location_map:
            location_map[loc] = []
        location_map[loc].append({
            "probe_id": row["probe_id"],
            "subnet": row["subnet"],
            "probe_type": row["probe_type"],
        })
    with open(os.path.join(workspace, "location_subnet_map.json"), "w") as f:
        json.dump(location_map, f, indent=2)

    # 5. Incident response template (txt)
    template = """INCIDENT RESPONSE TEMPLATE
==========================

Incident ID: [AUTO-GENERATED]
Date: [REPORT DATE]
Priority: [CRITICAL/HIGH/MEDIUM/LOW]

Affected Location(s): [LOCATION LIST]
Affected Endpoint Count: [COUNT]
Primary Fault Source: [network/sip_server/firmware/wireless]

Summary:
[BRIEF DESCRIPTION]

Metrics:
- Average Packet Loss: [X]%
- Average Jitter: [X] ms
- Average Latency: [X] ms
- Average MOS: [X]
- SIP Error Count: [X]
- AP Health Score: [X]

Recommended Actions:
[ACTION LIST]
"""
    with open(os.path.join(workspace, "incident_template.txt"), "w") as f:
        f.write(template)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]

    sip_df = gen_sip_servers(conn, n)
    probe_df = gen_network_probes(conn, n)
    ap_df = gen_wireless_aps(conn, n)
    endpoint_df = gen_endpoints(conn, n, ap_df, sip_df)
    gen_packet_loss_metrics(conn, n, probe_df, endpoint_df)
    gen_sip_error_logs(conn, n, sip_df, endpoint_df)
    gen_call_records(conn, n, endpoint_df, sip_df)

    gen_workspace(args.workspace, conn, endpoint_df, ap_df, probe_df, sip_df)

    conn.close()
    print(f"Data generated: db={args.db_path}, workspace={args.workspace}")
    print(f"  SCALE: rows_per_table={n}, num_workspace_files={SCALE['num_workspace_files']}")


if __name__ == "__main__":
    main()
