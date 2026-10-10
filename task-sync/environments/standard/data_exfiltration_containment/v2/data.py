"""
Data generation for data exfiltration forensic analysis task.
Generates a SQLite database and workspace files simulating a corporate
network security incident with firewall logs, file access audits,
authentication events, and threat intelligence feeds.
"""

import argparse
import sqlite3
import os
import json
import csv
import random
import numpy as np
from datetime import datetime, timedelta

import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 400,        # v2 = 4x base
    "num_workspace_files": 30,    # v2 = base + 2N (N = 10)
}

# ---------- constants ----------
CLASSIFICATION_HIERARCHY = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "TOP_SECRET"]
CLASSIFICATION_ORDER = {c: i for i, c in enumerate(CLASSIFICATION_HIERARCHY)}

DEPARTMENTS = [
    "Engineering", "Finance", "HR", "Marketing", "Legal",
    "IT", "Executive", "Research", "Sales", "Operations",
]

ROLES = [
    "Analyst", "Manager", "Director", "VP",
    "Engineer", "Administrator", "Specialist", "Coordinator",
]

CLEARANCE_MAP = {
    "Analyst": "CONFIDENTIAL",
    "Engineer": "CONFIDENTIAL",
    "Specialist": "INTERNAL",
    "Coordinator": "INTERNAL",
    "Manager": "RESTRICTED",
    "Director": "TOP_SECRET",
    "VP": "TOP_SECRET",
    "Administrator": "RESTRICTED",
}

DEPT_RISK_SCORES = {
    "Engineering": 7,
    "Finance": 9,
    "HR": 5,
    "Marketing": 3,
    "Legal": 8,
    "IT": 6,
    "Executive": 10,
    "Research": 8,
    "Sales": 4,
    "Operations": 5,
}

# Policy parameters (also written to workspace config)
OFF_HOURS_START = 21
OFF_HOURS_END = 6
BYTES_THRESHOLD = 30000
MAX_FAILED_AUTH = 2
SUSPICIOUS_ACTIONS = ["COPY", "DOWNLOAD"]

BASE_DATE = datetime(2026, 4, 18, 0, 0, 0)


# ---------- helpers ----------
def is_off_hours(hour, start=OFF_HOURS_START, end=OFF_HOURS_END):
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


_used_ips: set = set()


def _unique_ip(rng, lo=100, hi=250):
    while True:
        ip = f"{rng.randint(lo, hi)}.{rng.randint(1, 254)}.{rng.randint(1, 254)}.{rng.randint(1, 254)}"
        if ip not in _used_ips:
            _used_ips.add(ip)
            return ip


def _business_ts(rng):
    d = rng.randint(0, 6)
    h = rng.randint(7, 19)
    m, s = rng.randint(0, 59), rng.randint(0, 59)
    return (BASE_DATE + timedelta(days=d, hours=h, minutes=m, seconds=s)).strftime("%Y-%m-%d %H:%M:%S")


def _off_hours_ts(rng):
    d = rng.randint(0, 6)
    h = rng.choice([21, 22, 23, 0, 1, 2, 3, 4, 5])
    m, s = rng.randint(0, 59), rng.randint(0, 59)
    return (BASE_DATE + timedelta(days=d, hours=h, minutes=m, seconds=s)).strftime("%Y-%m-%d %H:%M:%S")


# ---------- main ----------
def main(db_path: str, workspace: str):
    global _used_ips
    _used_ips = set()

    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()

    os.makedirs(workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_ws_files = SCALE["num_workspace_files"]

    # ================================================================
    # 1. Reference entities
    # ================================================================

    # --- users ---
    users = []
    used_unames = set()
    for i in range(n_rows):
        while True:
            uname = fake.user_name()
            if uname not in used_unames:
                used_unames.add(uname)
                break
        role = random.choice(ROLES)
        dept = random.choice(DEPARTMENTS)
        users.append({
            "user_id": f"USR-{i+1:04d}",
            "username": uname,
            "department": dept,
            "role": role,
            "clearance_level": CLEARANCE_MAP[role],
        })

    # --- endpoints ---
    endpoints = []
    os_types = ["Windows 10", "Windows 11", "macOS 13", "macOS 14", "Ubuntu 22.04", "RHEL 8"]
    for i in range(n_rows):
        endpoints.append({
            "endpoint_id": f"EP-{i+1:04d}",
            "hostname": f"ws-{fake.lexify('????')}-{i+1:03d}",
            "ip_address": f"10.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}",
            "os_type": random.choice(os_types),
            "department": random.choice(DEPARTMENTS),
        })

    # --- files (data assets) ---
    file_types = [".docx", ".xlsx", ".pdf", ".csv", ".pptx", ".txt", ".json", ".zip"]
    files = []
    for i in range(n_rows):
        dept = random.choice(DEPARTMENTS)
        ftype = random.choice(file_types)
        classification = random.choice(CLASSIFICATION_HIERARCHY)
        files.append({
            "file_id": f"FILE-{i+1:04d}",
            "filename": f"{dept.lower()}_{fake.word()}_{i+1}{ftype}",
            "classification": classification,
            "size_kb": random.randint(10, 50000),
            "department": dept,
            "owner_user_id": random.choice(users)["user_id"],
        })

    sensitive_files = [f for f in files if f["classification"] in ("CONFIDENTIAL", "RESTRICTED", "TOP_SECRET")]

    # ================================================================
    # 2. Compromised / decoy user selection
    # ================================================================
    n_compromised = max(4, n_rows // 20)
    n_decoy = max(2, n_compromised // 3)

    idx_pool = list(range(n_rows))
    random.shuffle(idx_pool)
    compromised_indices = sorted(idx_pool[:n_compromised])
    decoy_indices = sorted(idx_pool[n_compromised:n_compromised + n_decoy])

    compromised_user_ids = {users[i]["user_id"] for i in compromised_indices}
    decoy_user_ids = {users[i]["user_id"] for i in decoy_indices}

    # ================================================================
    # 3. IP pools
    # ================================================================
    real_malicious_ips = [_unique_ip(random, 100, 150) for _ in range(n_compromised * 2 + 5)]
    decoy_ips = [_unique_ip(random, 160, 180) for _ in range(n_decoy * 2 + 3)]
    extra_malicious_ips = [_unique_ip(random, 181, 199) for _ in range(n_ws_files * 2)]
    normal_dst_ips = [_unique_ip(random, 50, 90) for _ in range(30)]
    extra_safe_ips = [_unique_ip(random, 200, 220) for _ in range(5)]

    all_threat_ips = real_malicious_ips + decoy_ips + extra_malicious_ips
    safe_list_ips = decoy_ips + extra_safe_ips

    real_malicious_set = set(real_malicious_ips)
    decoy_ip_set = set(decoy_ips)

    # ================================================================
    # 4. Activity logs
    # ================================================================

    # --- firewall logs ---
    firewall_logs = []
    fw_id = 0

    # Suspicious (compromised users -> real malicious IPs)
    for idx in compromised_indices:
        uid = users[idx]["user_id"]
        for _ in range(3):
            fw_id += 1
            firewall_logs.append({
                "log_id": f"FW-{fw_id:06d}",
                "timestamp": _off_hours_ts(random),
                "src_ip": random.choice(endpoints)["ip_address"],
                "dst_ip": random.choice(real_malicious_ips),
                "dst_port": random.choice([443, 8443, 8080]),
                "bytes_transferred": random.randint(50000, 500000),
                "protocol": "TCP",
                "action": "ALLOW",
                "user_id": uid,
            })

    # Decoy (decoy users -> decoy IPs which are also in safe list)
    for idx in decoy_indices:
        uid = users[idx]["user_id"]
        for _ in range(2):
            fw_id += 1
            firewall_logs.append({
                "log_id": f"FW-{fw_id:06d}",
                "timestamp": _off_hours_ts(random),
                "src_ip": random.choice(endpoints)["ip_address"],
                "dst_ip": random.choice(decoy_ips),
                "dst_port": random.choice([443, 8443]),
                "bytes_transferred": random.randint(50000, 500000),
                "protocol": "TCP",
                "action": "ALLOW",
                "user_id": uid,
            })

    # Normal traffic (fill to n_rows)
    n_suspicious_fw = len(firewall_logs)
    for _ in range(max(10, n_rows - n_suspicious_fw)):
        fw_id += 1
        bts = random.randint(30000, 80000) if random.random() < 0.10 else random.randint(100, 15000)
        firewall_logs.append({
            "log_id": f"FW-{fw_id:06d}",
            "timestamp": _business_ts(random),
            "src_ip": random.choice(endpoints)["ip_address"],
            "dst_ip": random.choice(normal_dst_ips),
            "dst_port": random.choice([80, 443, 8080, 22, 3389, 53, 25]),
            "bytes_transferred": bts,
            "protocol": random.choice(["TCP", "UDP"]),
            "action": random.choice(["ALLOW", "ALLOW", "ALLOW", "DENY"]),
            "user_id": random.choice(users)["user_id"],
        })

    random.shuffle(firewall_logs)

    # --- auth events ---
    auth_events = []
    auth_id = 0

    for idx in compromised_indices:
        uid = users[idx]["user_id"]
        for _ in range(MAX_FAILED_AUTH + 1):
            auth_id += 1
            auth_events.append({
                "event_id": f"AUTH-{auth_id:06d}",
                "timestamp": _off_hours_ts(random),
                "user_id": uid,
                "auth_type": random.choice(["PASSWORD", "MFA"]),
                "status": "FAILURE",
                "src_ip": random.choice(endpoints)["ip_address"],
                "session_id": f"SESS-{random.randint(10000,99999)}",
            })
        auth_id += 1
        auth_events.append({
            "event_id": f"AUTH-{auth_id:06d}",
            "timestamp": _off_hours_ts(random),
            "user_id": uid,
            "auth_type": "PASSWORD",
            "status": "SUCCESS",
            "src_ip": random.choice(endpoints)["ip_address"],
            "session_id": f"SESS-{random.randint(10000,99999)}",
        })

    # Decoy users also get failures >= threshold (look suspicious)
    for idx in decoy_indices:
        uid = users[idx]["user_id"]
        for _ in range(MAX_FAILED_AUTH + 1):
            auth_id += 1
            auth_events.append({
                "event_id": f"AUTH-{auth_id:06d}",
                "timestamp": _off_hours_ts(random),
                "user_id": uid,
                "auth_type": "PASSWORD",
                "status": "FAILURE",
                "src_ip": random.choice(endpoints)["ip_address"],
                "session_id": f"SESS-{random.randint(10000,99999)}",
            })

    n_suspicious_auth = len(auth_events)
    for _ in range(max(10, n_rows - n_suspicious_auth)):
        auth_id += 1
        auth_events.append({
            "event_id": f"AUTH-{auth_id:06d}",
            "timestamp": _business_ts(random),
            "user_id": random.choice(users)["user_id"],
            "auth_type": random.choice(["PASSWORD", "MFA", "SSO", "CERTIFICATE"]),
            "status": random.choice(["SUCCESS", "SUCCESS", "SUCCESS", "SUCCESS", "FAILURE"]),
            "src_ip": random.choice(endpoints)["ip_address"],
            "session_id": f"SESS-{random.randint(10000,99999)}",
        })

    random.shuffle(auth_events)

    # --- file access logs ---
    file_access_logs = []
    fa_id = 0

    for idx in compromised_indices:
        uid = users[idx]["user_id"]
        for j in range(3):
            fa_id += 1
            # 2/3 sensitive, 1/3 any (may include PUBLIC which gets filtered later)
            target = random.choice(sensitive_files) if j < 2 else random.choice(files)
            file_access_logs.append({
                "access_id": f"FA-{fa_id:06d}",
                "timestamp": _off_hours_ts(random),
                "user_id": uid,
                "file_id": target["file_id"],
                "action": random.choice(SUSPICIOUS_ACTIONS),
                "endpoint_id": random.choice(endpoints)["endpoint_id"],
            })

    n_suspicious_fa = len(file_access_logs)
    for _ in range(max(10, n_rows - n_suspicious_fa)):
        fa_id += 1
        file_access_logs.append({
            "access_id": f"FA-{fa_id:06d}",
            "timestamp": _business_ts(random),
            "user_id": random.choice(users)["user_id"],
            "file_id": random.choice(files)["file_id"],
            "action": random.choice(["READ", "READ", "WRITE", "READ", "COPY"]),
            "endpoint_id": random.choice(endpoints)["endpoint_id"],
        })

    random.shuffle(file_access_logs)

    # ================================================================
    # 5. Write database
    # ================================================================
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE users (
        user_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        department TEXT NOT NULL,
        role TEXT NOT NULL,
        clearance_level TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE endpoints (
        endpoint_id TEXT PRIMARY KEY,
        hostname TEXT NOT NULL,
        ip_address TEXT NOT NULL,
        os_type TEXT NOT NULL,
        department TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE files (
        file_id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        classification TEXT NOT NULL,
        size_kb INTEGER NOT NULL,
        department TEXT NOT NULL,
        owner_user_id TEXT NOT NULL,
        FOREIGN KEY (owner_user_id) REFERENCES users(user_id)
    )""")

    c.execute("""CREATE TABLE firewall_logs (
        log_id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        src_ip TEXT NOT NULL,
        dst_ip TEXT NOT NULL,
        dst_port INTEGER NOT NULL,
        bytes_transferred INTEGER NOT NULL,
        protocol TEXT NOT NULL,
        action TEXT NOT NULL,
        user_id TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )""")

    c.execute("""CREATE TABLE auth_events (
        event_id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        user_id TEXT NOT NULL,
        auth_type TEXT NOT NULL,
        status TEXT NOT NULL,
        src_ip TEXT NOT NULL,
        session_id TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )""")

    c.execute("""CREATE TABLE file_access_logs (
        access_id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        user_id TEXT NOT NULL,
        file_id TEXT NOT NULL,
        action TEXT NOT NULL,
        endpoint_id TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id),
        FOREIGN KEY (file_id) REFERENCES files(file_id),
        FOREIGN KEY (endpoint_id) REFERENCES endpoints(endpoint_id)
    )""")

    for u in users:
        c.execute("INSERT INTO users VALUES (?,?,?,?,?)",
                  (u["user_id"], u["username"], u["department"], u["role"], u["clearance_level"]))

    for e in endpoints:
        c.execute("INSERT INTO endpoints VALUES (?,?,?,?,?)",
                  (e["endpoint_id"], e["hostname"], e["ip_address"], e["os_type"], e["department"]))

    for f in files:
        c.execute("INSERT INTO files VALUES (?,?,?,?,?,?)",
                  (f["file_id"], f["filename"], f["classification"], f["size_kb"],
                   f["department"], f["owner_user_id"]))

    for fw in firewall_logs:
        c.execute("INSERT INTO firewall_logs VALUES (?,?,?,?,?,?,?,?,?)",
                  (fw["log_id"], fw["timestamp"], fw["src_ip"], fw["dst_ip"],
                   fw["dst_port"], fw["bytes_transferred"], fw["protocol"],
                   fw["action"], fw["user_id"]))

    for ae in auth_events:
        c.execute("INSERT INTO auth_events VALUES (?,?,?,?,?,?,?)",
                  (ae["event_id"], ae["timestamp"], ae["user_id"], ae["auth_type"],
                   ae["status"], ae["src_ip"], ae["session_id"]))

    for fa in file_access_logs:
        c.execute("INSERT INTO file_access_logs VALUES (?,?,?,?,?,?)",
                  (fa["access_id"], fa["timestamp"], fa["user_id"], fa["file_id"],
                   fa["action"], fa["endpoint_id"]))

    conn.commit()
    conn.close()

    # ================================================================
    # 6. Workspace files
    # ================================================================

    # ----- Fixed files -----

    # (a) incident_response_policy.yaml
    policy = {
        "incident_response": {
            "off_hours": {"start": OFF_HOURS_START, "end": OFF_HOURS_END},
            "bytes_threshold": BYTES_THRESHOLD,
            "max_failed_auth_before_flag": MAX_FAILED_AUTH,
            "lookback_window_days": 7,
            "suspicious_actions": list(SUSPICIOUS_ACTIONS),
            "severity_levels": {
                "CRITICAL": {"min_classification": "TOP_SECRET", "requires_immediate_containment": True},
                "HIGH": {"min_classification": "RESTRICTED", "requires_immediate_containment": True},
                "MEDIUM": {"min_classification": "CONFIDENTIAL", "requires_immediate_containment": False},
                "LOW": {"min_classification": "INTERNAL", "requires_immediate_containment": False},
            },
        }
    }
    with open(os.path.join(workspace, "incident_response_policy.yaml"), "w") as fh:
        yaml.dump(policy, fh, default_flow_style=False, sort_keys=False)

    # (b) clearance_matrix.json
    with open(os.path.join(workspace, "clearance_matrix.json"), "w") as fh:
        json.dump(CLEARANCE_MAP, fh, indent=2)

    # (c) data_classification_guide.md
    guide_md = """# Data Classification Guide

The organization uses a five-tier data classification hierarchy, listed from least to most sensitive:

1. **PUBLIC** -- Information approved for unrestricted distribution.
2. **INTERNAL** -- For internal use only; not to be shared externally without authorization.
3. **CONFIDENTIAL** -- Business-sensitive information on a need-to-know basis.
4. **RESTRICTED** -- Highly sensitive data subject to regulatory compliance requirements.
5. **TOP_SECRET** -- The most sensitive category, limited to executive and board-level access.

For clearance comparison purposes, each level is strictly ordered: PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED < TOP_SECRET. A user whose role-based clearance is set to a given level may access data at that level and all levels below it. Access to data classified above a user's clearance constitutes an unauthorized access event.
"""
    with open(os.path.join(workspace, "data_classification_guide.md"), "w") as fh:
        fh.write(guide_md)

    # (d) known_safe_destinations.txt
    with open(os.path.join(workspace, "known_safe_destinations.txt"), "w") as fh:
        fh.write("# Known Safe Destination IPs\n")
        fh.write("# Verified by Security Operations -- exclude from malicious indicator analysis\n")
        for ip in safe_list_ips:
            fh.write(ip + "\n")

    # (e) department_risk_scores.csv
    with open(os.path.join(workspace, "department_risk_scores.csv"), "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["department", "risk_score"])
        for dept in sorted(DEPT_RISK_SCORES.keys()):
            writer.writerow([dept, DEPT_RISK_SCORES[dept]])

    # ----- Scalable files: threat intel feeds -----
    random.shuffle(all_threat_ips)
    threat_cats_malicious = ["C2", "exfiltration"]
    threat_cats_noise = ["scanning", "spam", "tor_exit"]
    confidence_relevant = ["high", "medium"]
    sources = ["CERT", "ISAC", "ThreatGrid", "FireEye", "CrowdStrike", "Mandiant"]

    # Spread real-malicious + decoy + extra IPs across feeds
    threat_ip_pool = list(all_threat_ips)
    random.shuffle(threat_ip_pool)
    per_file = max(1, len(threat_ip_pool) // n_ws_files)

    for idx in range(n_ws_files):
        start = idx * per_file
        end = min(start + per_file, len(threat_ip_pool))
        if idx == n_ws_files - 1:
            end = len(threat_ip_pool)
        chunk = threat_ip_pool[start:end]

        report = {
            "report_id": f"TI-{idx+1:04d}",
            "source": random.choice(sources),
            "date": (BASE_DATE - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d"),
            "indicators": [],
        }

        for ip in chunk:
            is_key_ip = ip in real_malicious_set or ip in decoy_ip_set
            if is_key_ip:
                report["indicators"].append({
                    "type": "ipv4",
                    "value": ip,
                    "threat_category": random.choice(threat_cats_malicious),
                    "confidence": random.choice(confidence_relevant),
                    "status": "active",
                })
            else:
                # Extra malicious IPs -- some relevant, some noise
                if random.random() < 0.5:
                    report["indicators"].append({
                        "type": "ipv4",
                        "value": ip,
                        "threat_category": random.choice(threat_cats_malicious),
                        "confidence": random.choice(confidence_relevant),
                        "status": "active",
                    })
                else:
                    report["indicators"].append({
                        "type": "ipv4",
                        "value": ip,
                        "threat_category": random.choice(threat_cats_noise),
                        "confidence": random.choice(["low", "medium"]),
                        "status": random.choice(["active", "inactive", "expired"]),
                    })

        # Add pure noise indicators
        for _ in range(random.randint(2, 6)):
            report["indicators"].append({
                "type": "ipv4",
                "value": f"{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}",
                "threat_category": random.choice(threat_cats_noise),
                "confidence": "low",
                "status": random.choice(["inactive", "expired"]),
            })

        random.shuffle(report["indicators"])

        with open(os.path.join(workspace, f"threat_intel_feed_{idx+1:03d}.json"), "w") as fh:
            json.dump(report, fh, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
