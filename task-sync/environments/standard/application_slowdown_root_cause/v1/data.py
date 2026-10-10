#!/usr/bin/env python3
"""Data generation for application slowdown root cause analysis task."""

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
    "num_workspace_files": 20,
}

# ---------------------------------------------------------------------------
# Deterministic seeding
# ---------------------------------------------------------------------------
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ---------------------------------------------------------------------------
# Reference constants
# ---------------------------------------------------------------------------
SEGMENT_DEFS = [
    {"segment_id": "SEG-01", "segment_name": "Core-Backbone", "vlan_id": 100, "subnet": "10.1.0.0/16", "criticality": "critical"},
    {"segment_id": "SEG-02", "segment_name": "DMZ-Public", "vlan_id": 200, "subnet": "10.2.0.0/16", "criticality": "critical"},
    {"segment_id": "SEG-03", "segment_name": "App-Tier-East", "vlan_id": 301, "subnet": "10.3.0.0/16", "criticality": "high"},
    {"segment_id": "SEG-04", "segment_name": "App-Tier-West", "vlan_id": 302, "subnet": "10.4.0.0/16", "criticality": "high"},
    {"segment_id": "SEG-05", "segment_name": "DB-Primary", "vlan_id": 400, "subnet": "10.5.0.0/16", "criticality": "critical"},
    {"segment_id": "SEG-06", "segment_name": "DB-Replica", "vlan_id": 401, "subnet": "10.6.0.0/16", "criticality": "high"},
    {"segment_id": "SEG-07", "segment_name": "Storage-SAN", "vlan_id": 500, "subnet": "10.7.0.0/16", "criticality": "high"},
    {"segment_id": "SEG-08", "segment_name": "Management", "vlan_id": 600, "subnet": "10.8.0.0/16", "criticality": "medium"},
    {"segment_id": "SEG-09", "segment_name": "VoIP-Services", "vlan_id": 700, "subnet": "10.9.0.0/16", "criticality": "medium"},
    {"segment_id": "SEG-10", "segment_name": "Guest-WiFi", "vlan_id": 800, "subnet": "10.10.0.0/16", "criticality": "low"},
    {"segment_id": "SEG-11", "segment_name": "Dev-Lab", "vlan_id": 900, "subnet": "10.11.0.0/16", "criticality": "low"},
    {"segment_id": "SEG-12", "segment_name": "CI-CD-Pipeline", "vlan_id": 910, "subnet": "10.12.0.0/16", "criticality": "medium"},
    {"segment_id": "SEG-13", "segment_name": "Monitoring-Infra", "vlan_id": 920, "subnet": "10.13.0.0/16", "criticality": "medium"},
    {"segment_id": "SEG-14", "segment_name": "Backup-Network", "vlan_id": 950, "subnet": "10.14.0.0/16", "criticality": "low"},
    {"segment_id": "SEG-15", "segment_name": "IoT-Sensors", "vlan_id": 960, "subnet": "10.15.0.0/16", "criticality": "low"},
]

DEVICE_TYPES = ["router", "switch", "firewall", "load_balancer"]
LOCATIONS = [
    "DC-East-Rack-A", "DC-East-Rack-B", "DC-East-Rack-C",
    "DC-West-Rack-A", "DC-West-Rack-B", "DC-West-Rack-C",
    "DC-Central-Rack-A", "DC-Central-Rack-B",
    "Remote-Office-1", "Remote-Office-2",
]

TRAP_TYPES = ["linkDown", "highCPU", "highMemory", "packetLoss", "latencySpike", "interfaceError", "bgpPeerDown", "ospfNeighborLoss"]
TRAP_SEVERITIES = ["critical", "major", "minor", "informational"]

INTERFACE_NAMES = ["eth0", "eth1", "eth2", "eth3", "ge-0/0/0", "ge-0/0/1", "ge-0/0/2", "ge-0/0/3",
                   "xe-0/0/0", "xe-0/0/1", "te-1/0/0", "te-1/0/1"]

APP_NAMES = ["PaymentGateway", "UserAuthService", "InventoryAPI", "OrderProcessor",
             "NotificationHub", "ReportEngine", "SearchService", "CacheProxy",
             "FileStorage", "AnalyticsPipeline", "CustomerPortal", "AdminDashboard"]

APP_ENDPOINTS = {
    "PaymentGateway": ["/api/v1/charge", "/api/v1/refund", "/api/v1/status", "/healthz"],
    "UserAuthService": ["/auth/login", "/auth/token/refresh", "/auth/validate", "/healthz"],
    "InventoryAPI": ["/inventory/check", "/inventory/reserve", "/inventory/release", "/healthz"],
    "OrderProcessor": ["/orders/create", "/orders/update", "/orders/cancel", "/healthz"],
    "NotificationHub": ["/notify/email", "/notify/sms", "/notify/push", "/healthz"],
    "ReportEngine": ["/reports/generate", "/reports/status", "/reports/download", "/healthz"],
    "SearchService": ["/search/query", "/search/suggest", "/search/index", "/healthz"],
    "CacheProxy": ["/cache/get", "/cache/set", "/cache/invalidate", "/healthz"],
    "FileStorage": ["/files/upload", "/files/download", "/files/delete", "/healthz"],
    "AnalyticsPipeline": ["/analytics/ingest", "/analytics/query", "/analytics/export", "/healthz"],
    "CustomerPortal": ["/portal/dashboard", "/portal/profile", "/portal/orders", "/healthz"],
    "AdminDashboard": ["/admin/metrics", "/admin/users", "/admin/config", "/healthz"],
}

CHANGE_TYPES = ["firmware_update", "config_change", "hardware_replacement", "capacity_upgrade",
                "security_patch", "routing_update"]
CHANGE_STATUSES = ["completed", "in_progress", "rolled_back", "failed"]

PROTOCOLS = ["TCP", "UDP", "ICMP"]

APP_TIERS = {
    "PaymentGateway": "platinum",
    "UserAuthService": "platinum",
    "OrderProcessor": "gold",
    "InventoryAPI": "gold",
    "CustomerPortal": "gold",
    "NotificationHub": "silver",
    "ReportEngine": "silver",
    "SearchService": "silver",
    "CacheProxy": "bronze",
    "FileStorage": "bronze",
    "AnalyticsPipeline": "bronze",
    "AdminDashboard": "bronze",
}

# Time anchor (fixed)
BASE_TIME = datetime(2025, 3, 15, 8, 0, 0)


def _ip_in_subnet(segment_id: str) -> str:
    """Generate a random IP within a segment's subnet."""
    seg_idx = int(segment_id.split("-")[1])
    return f"10.{seg_idx}.{random.randint(1, 254)}.{random.randint(1, 254)}"


def _generate_devices(n: int):
    """Generate network device records."""
    rows = []
    segment_ids = [s["segment_id"] for s in SEGMENT_DEFS]
    for i in range(n):
        seg = segment_ids[i % len(segment_ids)]
        dev_type = DEVICE_TYPES[i % len(DEVICE_TYPES)]
        loc = LOCATIONS[i % len(LOCATIONS)]
        hostname = f"{dev_type[:2]}-{seg.lower()}-{i:03d}"
        rows.append({
            "device_id": f"DEV-{i+1:04d}",
            "hostname": hostname,
            "device_type": dev_type,
            "location": loc,
            "segment_id": seg,
            "ip_address": _ip_in_subnet(seg),
            "status": random.choices(["active", "degraded", "maintenance"], weights=[0.8, 0.15, 0.05])[0],
        })
    return pd.DataFrame(rows)


def _generate_snmp_traps(n: int, device_ids: list):
    """Generate SNMP trap records."""
    rows = []
    for i in range(n):
        severity = random.choices(
            TRAP_SEVERITIES,
            weights=[0.10, 0.20, 0.40, 0.30]
        )[0]
        trap_type = random.choice(TRAP_TYPES)
        dev_id = random.choice(device_ids)
        iface = random.choice(INTERFACE_NAMES)
        ts = BASE_TIME - timedelta(hours=random.uniform(0, 48))
        oid_base = {"linkDown": "1.3.6.1.6.3.1.1.5.3",
                     "highCPU": "1.3.6.1.4.1.9.9.109.1.1.1",
                     "highMemory": "1.3.6.1.4.1.9.9.48.1.1.1",
                     "packetLoss": "1.3.6.1.2.1.2.2.1.13",
                     "latencySpike": "1.3.6.1.2.1.2.2.1.20",
                     "interfaceError": "1.3.6.1.2.1.2.2.1.14",
                     "bgpPeerDown": "1.3.6.1.2.1.15.3.1.14",
                     "ospfNeighborLoss": "1.3.6.1.2.1.14.10.1.6"}
        val = round(random.uniform(50, 100), 1) if severity in ("critical", "major") else round(random.uniform(5, 50), 1)
        msg = f"{trap_type} on {iface}: value={val}"
        rows.append({
            "trap_id": f"TRAP-{i+1:05d}",
            "device_id": dev_id,
            "interface_name": iface,
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "severity": severity,
            "trap_type": trap_type,
            "oid": oid_base.get(trap_type, "1.3.6.1.2.1.1.3.0"),
            "value": val,
            "message": msg,
        })
    return pd.DataFrame(rows)


def _generate_netflow_sessions(n: int, device_ids: list, devices_df: pd.DataFrame):
    """Generate NetFlow session records."""
    rows = []
    dev_seg_map = dict(zip(devices_df["device_id"], devices_df["segment_id"]))
    for i in range(n):
        dev_id = random.choice(device_ids)
        seg = dev_seg_map[dev_id]
        iface = random.choice(INTERFACE_NAMES)
        src_ip = _ip_in_subnet(seg)
        dst_seg = random.choice([s["segment_id"] for s in SEGMENT_DEFS])
        dst_ip = _ip_in_subnet(dst_seg)
        proto = random.choice(PROTOCOLS)
        start = BASE_TIME - timedelta(hours=random.uniform(0, 48))
        dur = random.uniform(0.1, 300)
        app = random.choice(APP_NAMES)
        rows.append({
            "session_id": f"NF-{i+1:06d}",
            "device_id": dev_id,
            "interface_name": iface,
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "src_port": random.randint(1024, 65535),
            "dst_port": random.choice([80, 443, 8080, 8443, 3306, 5432, 6379, 9200]),
            "protocol": proto,
            "bytes_transferred": random.randint(100, 10_000_000),
            "packets": random.randint(1, 50000),
            "start_time": start.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_sec": round(dur, 2),
            "app_tag": app,
        })
    return pd.DataFrame(rows)


def _generate_apm_traces(n: int, devices_df: pd.DataFrame):
    """Generate APM trace records."""
    rows = []
    # Build a pool of server IPs tied to segments
    server_ips = {}
    for _, dev in devices_df.iterrows():
        seg = dev["segment_id"]
        if seg not in server_ips:
            server_ips[seg] = []
        server_ips[seg].append(dev["ip_address"])

    for i in range(n):
        app = random.choice(APP_NAMES)
        endpoint = random.choice(APP_ENDPOINTS[app])
        # ~20% of traces are slow
        if random.random() < 0.20:
            resp_time = round(random.uniform(2000, 15000), 1)
            error_flag = random.choice([0, 1])
        else:
            resp_time = round(random.uniform(10, 500), 1)
            error_flag = 0
        status = random.choice([200, 200, 200, 200, 201, 400, 500, 502, 503, 504]) if error_flag else random.choice([200, 200, 200, 201])
        ts = BASE_TIME - timedelta(hours=random.uniform(0, 48))
        client_ip = f"192.168.{random.randint(1,254)}.{random.randint(1,254)}"
        seg_key = random.choice(list(server_ips.keys()))
        srv_ip = random.choice(server_ips[seg_key])
        error_types = ["TimeoutError", "ConnectionReset", "ServiceUnavailable", "BadGateway", "InternalError", ""]
        err_type = random.choice(error_types[:5]) if error_flag else ""
        rows.append({
            "trace_id": f"APM-{i+1:06d}",
            "app_name": app,
            "endpoint": endpoint,
            "response_time_ms": resp_time,
            "status_code": status,
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "client_ip": client_ip,
            "server_ip": srv_ip,
            "error_flag": error_flag,
            "error_type": err_type,
        })
    return pd.DataFrame(rows)


def _generate_change_tickets(n: int, device_ids: list):
    """Generate change management ticket records."""
    rows = []
    engineers = [fake.name() for _ in range(10)]
    for i in range(n):
        dev_id = random.choice(device_ids)
        ct = random.choice(CHANGE_TYPES)
        status = random.choices(CHANGE_STATUSES, weights=[0.55, 0.15, 0.20, 0.10])[0]
        sched = BASE_TIME - timedelta(hours=random.uniform(0, 72))
        comp = sched + timedelta(hours=random.uniform(0.5, 4)) if status != "in_progress" else None
        risk = random.choice(["low", "medium", "high", "critical"])
        title = f"{ct.replace('_', ' ').title()} on {dev_id}"
        desc = fake.sentence(nb_words=12)
        rows.append({
            "ticket_id": f"CHG-{i+1:05d}",
            "device_id": dev_id,
            "title": title,
            "change_type": ct,
            "scheduled_time": sched.strftime("%Y-%m-%d %H:%M:%S"),
            "completed_time": comp.strftime("%Y-%m-%d %H:%M:%S") if comp else None,
            "status": status,
            "engineer": random.choice(engineers),
            "risk_level": risk,
            "description": desc,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Database construction
# ---------------------------------------------------------------------------
def build_database(db_path: str, devices_df, traps_df, netflow_df, apm_df, tickets_df):
    conn = sqlite3.connect(db_path)
    devices_df.to_sql("network_devices", conn, if_exists="replace", index=False)
    traps_df.to_sql("snmp_traps", conn, if_exists="replace", index=False)
    netflow_df.to_sql("netflow_sessions", conn, if_exists="replace", index=False)
    apm_df.to_sql("apm_traces", conn, if_exists="replace", index=False)
    tickets_df.to_sql("change_tickets", conn, if_exists="replace", index=False)
    conn.close()


# ---------------------------------------------------------------------------
# Workspace file generation
# ---------------------------------------------------------------------------
def build_workspace(workspace: str, devices_df, traps_df, netflow_df, apm_df, tickets_df):
    os.makedirs(workspace, exist_ok=True)

    num_files = SCALE["num_workspace_files"]

    # ------------------------------------------------------------------
    # Fixed config files (not scaled)
    # ------------------------------------------------------------------

    # 1. segment_definitions.json
    with open(os.path.join(workspace, "segment_definitions.json"), "w") as f:
        json.dump(SEGMENT_DEFS, f, indent=2)

    # 2. severity_scoring.yaml
    severity_config = {
        "severity_weights": {
            "critical": 10.0,
            "major": 6.0,
            "minor": 2.0,
            "informational": 0.5,
        },
        "aggregation": "sum_per_device",
        "description": "For each device, sum the severity weights of all its traps to get the device_severity_score.",
    }
    with open(os.path.join(workspace, "severity_scoring.yaml"), "w") as f:
        yaml.dump(severity_config, f, default_flow_style=False)

    # 3. sla_thresholds.json
    sla_config = {
        "tiers": {
            "platinum": {
                "max_response_time_ms": 500,
                "max_error_rate_pct": 0.5,
                "sla_impact_factor": 4.0,
            },
            "gold": {
                "max_response_time_ms": 1000,
                "max_error_rate_pct": 2.0,
                "sla_impact_factor": 3.0,
            },
            "silver": {
                "max_response_time_ms": 2000,
                "max_error_rate_pct": 5.0,
                "sla_impact_factor": 2.0,
            },
            "bronze": {
                "max_response_time_ms": 5000,
                "max_error_rate_pct": 10.0,
                "sla_impact_factor": 1.0,
            },
        },
        "app_tier_mapping": APP_TIERS,
    }
    with open(os.path.join(workspace, "sla_thresholds.json"), "w") as f:
        json.dump(sla_config, f, indent=2)

    # 4. priority_formula.yaml
    formula_config = {
        "formula": "device_severity_score * criticality_weight * max_sla_impact_factor * (1 + change_correlation_bonus)",
        "criticality_weights": {
            "critical": 5.0,
            "high": 3.0,
            "medium": 1.5,
            "low": 1.0,
        },
        "change_correlation_bonus": {
            "rolled_back": 0.5,
            "failed": 0.5,
            "in_progress": 0.25,
            "completed": 0.0,
        },
        "description": (
            "For each device identified as problematic (having at least one critical or major trap), "
            "compute priority_score using the formula. "
            "device_severity_score = sum of severity_weights for all traps on that device. "
            "criticality_weight = looked up from the device's segment criticality. "
            "max_sla_impact_factor = the maximum sla_impact_factor among all SLA-breaching applications "
            "whose traffic traverses the device (identified via NetFlow sessions on the device whose "
            "app_tag matches an application with at least one APM trace exceeding the tier's "
            "max_response_time_ms threshold). If no SLA-breaching app traverses the device, use 1.0. "
            "change_correlation_bonus = the maximum bonus among all change tickets on the device "
            "within the 72-hour window before the analysis time. If no tickets exist, bonus is 0.0."
        ),
        "root_cause_classification": {
            "rules": [
                "If the device has a rolled_back or failed change ticket AND critical/major traps, classify as 'Change-Induced Failure'",
                "If the device has highCPU or highMemory traps with value >= 90, classify as 'Resource Exhaustion'",
                "If the device has a linkDown or interfaceError trap AND the packet_loss_rate of the trap's interface (from interface stats files) > 5.0, classify as 'Interface Degradation'",
                "If the device has a packetLoss trap AND the packet_loss_rate of the trap's interface (from interface stats files) > 2.0, classify as 'Packet Loss'",
                "If the device has latencySpike traps, classify as 'Latency Anomaly'",
                "If the device has bgpPeerDown or ospfNeighborLoss traps, classify as 'Routing Protocol Failure'",
                "Otherwise classify as 'General Degradation'",
            ],
            "note": "Apply rules top-to-bottom; first matching rule wins.",
        },
        "recommended_actions": {
            "Change-Induced Failure": "Rollback recent change and verify service restoration",
            "Resource Exhaustion": "Scale up or redistribute load; investigate runaway processes",
            "Interface Degradation": "Replace cable/transceiver; check physical layer",
            "Packet Loss": "Investigate congestion; apply QoS policies",
            "Latency Anomaly": "Check routing tables; investigate upstream congestion",
            "Routing Protocol Failure": "Re-establish peering; check configuration drift",
            "General Degradation": "Perform comprehensive device health check",
        },
    }
    with open(os.path.join(workspace, "priority_formula.yaml"), "w") as f:
        yaml.dump(formula_config, f, default_flow_style=False, sort_keys=False)

    # 5. change_correlation_rules.md
    rules_md = """# Change Correlation Rules

A change ticket is considered correlated with a device's issues when all of the following hold:

1. The ticket's device_id matches the device in question.
2. The ticket's scheduled_time falls within 72 hours before the analysis reference time (2025-03-15 08:00:00).
3. The ticket's status is one of: rolled_back, failed, in_progress, or completed.

When multiple tickets match, use the one with the highest change_correlation_bonus
(as defined in the priority formula configuration). In case of a tie in bonus value,
use the ticket with the most recent scheduled_time. Report that single ticket_id as
the correlated ticket.

If no ticket matches, report "NONE" as the correlated_ticket_id and use a bonus of 0.0.
"""
    with open(os.path.join(workspace, "change_correlation_rules.md"), "w") as f:
        f.write(rules_md)

    # ------------------------------------------------------------------
    # Scalable data files
    # ------------------------------------------------------------------

    # Distribute scalable files across three categories
    n_iface_files = max(4, num_files * 4 // 10)   # ~40%
    n_apm_detail_files = max(3, num_files * 3 // 10)  # ~30%
    n_anomaly_files = num_files - n_iface_files - n_apm_detail_files  # ~30%

    # --- Interface statistics CSV files ---
    device_list = devices_df["device_id"].tolist()
    devices_per_file = max(1, len(device_list) // n_iface_files)
    for fidx in range(n_iface_files):
        start_idx = fidx * devices_per_file
        end_idx = start_idx + devices_per_file if fidx < n_iface_files - 1 else len(device_list)
        subset_devs = device_list[start_idx:end_idx]
        iface_rows = []
        for dev_id in subset_devs:
            for iface in random.sample(INTERFACE_NAMES, min(4, len(INTERFACE_NAMES))):
                # Devices with critical/major traps get higher error rates
                dev_traps = traps_df[traps_df["device_id"] == dev_id]
                has_serious = len(dev_traps[dev_traps["severity"].isin(["critical", "major"])]) > 0
                if has_serious and random.random() < 0.6:
                    pkt_loss = round(random.uniform(2.5, 15.0), 2)
                    crc_err = random.randint(50, 500)
                    input_err = random.randint(100, 2000)
                    output_drops = random.randint(50, 1000)
                    utilization = round(random.uniform(70, 99), 1)
                else:
                    pkt_loss = round(random.uniform(0.0, 1.5), 2)
                    crc_err = random.randint(0, 10)
                    input_err = random.randint(0, 50)
                    output_drops = random.randint(0, 20)
                    utilization = round(random.uniform(10, 65), 1)
                ts = (BASE_TIME - timedelta(hours=random.uniform(0, 2))).strftime("%Y-%m-%d %H:%M:%S")
                iface_rows.append({
                    "device_id": dev_id,
                    "interface_name": iface,
                    "avg_utilization_pct": utilization,
                    "packet_loss_rate": pkt_loss,
                    "crc_errors": crc_err,
                    "input_errors": input_err,
                    "output_drops": output_drops,
                    "measurement_time": ts,
                })
        iface_df = pd.DataFrame(iface_rows)
        iface_df.to_csv(os.path.join(workspace, f"interface_stats_{fidx+1:03d}.csv"), index=False)

    # --- APM trace detail JSON files ---
    trace_list = apm_df["trace_id"].tolist()
    traces_per_file = max(1, len(trace_list) // n_apm_detail_files)
    for fidx in range(n_apm_detail_files):
        start_idx = fidx * traces_per_file
        end_idx = start_idx + traces_per_file if fidx < n_apm_detail_files - 1 else len(trace_list)
        subset_traces = trace_list[start_idx:end_idx]
        details = []
        for tid in subset_traces:
            trace_row = apm_df[apm_df["trace_id"] == tid].iloc[0]
            n_spans = random.randint(2, 8)
            spans = []
            for s in range(n_spans):
                srv = random.choice(APP_NAMES)
                dur = round(random.uniform(5, trace_row["response_time_ms"] * 0.6), 1)
                host = trace_row["server_ip"] if s == 0 else f"10.{random.randint(1,15)}.{random.randint(1,254)}.{random.randint(1,254)}"
                spans.append({
                    "span_index": s,
                    "service": srv,
                    "duration_ms": dur,
                    "host_ip": host,
                })
            details.append({
                "trace_id": tid,
                "app_name": trace_row["app_name"],
                "total_spans": n_spans,
                "spans": spans,
            })
        with open(os.path.join(workspace, f"apm_trace_details_{fidx+1:03d}.json"), "w") as f:
            json.dump(details, f, indent=2)

    # --- NetFlow anomaly report TXT files ---
    session_list = netflow_df["session_id"].tolist()
    sessions_per_file = max(1, len(session_list) // n_anomaly_files)
    for fidx in range(n_anomaly_files):
        start_idx = fidx * sessions_per_file
        end_idx = start_idx + sessions_per_file if fidx < n_anomaly_files - 1 else len(session_list)
        subset_sessions = session_list[start_idx:end_idx]
        lines = [f"=== NetFlow Anomaly Report (Batch {fidx+1}) ===", ""]
        for sid in subset_sessions:
            sess = netflow_df[netflow_df["session_id"] == sid].iloc[0]
            # ~25% flagged as anomalous
            if random.random() < 0.25:
                reasons = random.sample([
                    "excessive_bytes: bytes_transferred exceeds baseline by >3 sigma",
                    "unusual_port: destination port not in expected set for app",
                    "duration_outlier: session duration exceeds 95th percentile",
                    "high_packet_rate: packets/sec exceeds normal threshold",
                    "protocol_mismatch: unexpected protocol for application tag",
                ], k=random.randint(1, 3))
                lines.append(f"[ANOMALY] Session {sid} on {sess['device_id']} ({sess['interface_name']})")
                lines.append(f"  Flow: {sess['src_ip']}:{sess['src_port']} -> {sess['dst_ip']}:{sess['dst_port']} ({sess['protocol']})")
                lines.append(f"  App: {sess['app_tag']}  Bytes: {sess['bytes_transferred']}  Duration: {sess['duration_sec']}s")
                for r in reasons:
                    lines.append(f"  * {r}")
                lines.append("")
            else:
                lines.append(f"[NORMAL] Session {sid} on {sess['device_id']} - no anomalies detected")
                lines.append("")
        with open(os.path.join(workspace, f"netflow_anomalies_{fidx+1:03d}.txt"), "w") as f:
            f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n = SCALE["rows_per_table"]

    devices_df = _generate_devices(n)
    device_ids = devices_df["device_id"].tolist()
    traps_df = _generate_snmp_traps(n, device_ids)
    netflow_df = _generate_netflow_sessions(n, device_ids, devices_df)
    apm_df = _generate_apm_traces(n, devices_df)
    tickets_df = _generate_change_tickets(n, device_ids)

    build_database(args.db_path, devices_df, traps_df, netflow_df, apm_df, tickets_df)
    build_workspace(args.workspace, devices_df, traps_df, netflow_df, apm_df, tickets_df)
    print(f"Database written to {args.db_path}")
    print(f"Workspace written to {args.workspace}")
    print(f"  Devices: {len(devices_df)}, Traps: {len(traps_df)}, "
          f"NetFlow: {len(netflow_df)}, APM: {len(apm_df)}, Tickets: {len(tickets_df)}")


if __name__ == "__main__":
    main()
