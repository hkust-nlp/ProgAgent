"""
Data generation script for post-breach remediation prioritization task.
Generates a SQLite database and workspace files for vulnerability management.
"""

import argparse
import sqlite3
import os
import json
import yaml
import csv
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 8,
}

# ── Seed everything ──────────────────────────────────────────────────────────
SEED = 42
fake = Faker()
Faker.seed(SEED)
np.random.seed(SEED)

# ── Constants ────────────────────────────────────────────────────────────────
VULN_TYPES = [
    "Remote Code Execution", "SQL Injection", "Cross-Site Scripting",
    "Privilege Escalation", "Buffer Overflow", "Authentication Bypass",
    "Directory Traversal", "Denial of Service", "Information Disclosure",
    "Command Injection",
]

SOFTWARE_LIST = [
    "Apache HTTP Server 2.4", "nginx 1.22", "OpenSSL 3.0", "MySQL 8.0",
    "PostgreSQL 15", "Redis 7.0", "MongoDB 6.0", "Elasticsearch 8.6",
    "Kubernetes 1.27", "Docker 24.0", "Windows Server 2019", "Ubuntu 22.04",
    "CentOS Stream 9", "Node.js 18", "Python Flask 2.3", "Java Spring 6.0",
    "PHP 8.2", "Apache Tomcat 10", "Jenkins 2.400", "GitLab 16.0",
]

DEPARTMENTS = ["Engineering", "Finance", "HR", "Marketing", "Operations",
               "Security", "Executive", "Legal", "Research", "IT"]

NETWORK_ZONES = ["DMZ", "Restricted", "Internal", "Cloud", "Development"]

OS_LIST = ["Ubuntu 20.04", "Ubuntu 22.04", "CentOS 8", "Windows Server 2019",
           "Windows Server 2022", "RHEL 8", "Debian 11", "Amazon Linux 2"]

THREAT_ACTORS = ["APT28", "APT29", "Lazarus Group", "FIN7", "Sandworm",
                 "Turla", "Cobalt Group", "MuddyWater", "APT41", "DarkSide",
                 "REvil", "Conti Group"]

EXPLOIT_MATURITIES = ["weaponized", "poc_available", "functional", "unproven"]

CAMPAIGN_NAMES = ["Operation Sunrise", "Project Blackout", "Shadow Strike",
                  "Digital Tempest", "Crimson Tide", "Silent Thunder",
                  "Iron Harvest", "Ghost Protocol", "Dark Nexus"]

PATCH_STATUSES = ["deployed", "pending", "failed", "scheduled", "not_available"]

BUSINESS_UNITS = ["Core Platform", "Customer Facing", "Data Analytics",
                  "Infrastructure", "Internal Tools", "Compliance Systems",
                  "Payment Processing", "Cloud Services"]

DATA_CLASSIFICATIONS = ["public", "internal", "confidential", "restricted"]

COMPLIANCE_TAGS_POOL = ["PCI-DSS", "HIPAA", "SOX", "GDPR", "SOC2", "ISO27001",
                        "NIST", "FedRAMP"]


def create_database(db_path):
    """Create and populate the SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    n = SCALE["rows_per_table"]

    # ── Table 1: vulnerabilities ─────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vulnerabilities (
            cve_id TEXT PRIMARY KEY,
            description TEXT,
            cvss_score REAL,
            affected_software TEXT,
            vulnerability_type TEXT,
            published_date TEXT,
            cvss_vector TEXT
        )
    """)

    vulns = []
    for i in range(n):
        year = int(np.random.choice([2023, 2024, 2025]))
        cve_id = f"CVE-{year}-{10000 + i}"
        cvss = round(float(np.random.uniform(2.0, 10.0)), 1)
        ac = "L" if cvss > 7 else ("M" if cvss > 4 else "H")
        vulns.append((
            cve_id,
            fake.sentence(nb_words=12),
            cvss,
            str(np.random.choice(SOFTWARE_LIST)),
            str(np.random.choice(VULN_TYPES)),
            fake.date_between(start_date="-2y", end_date="today").isoformat(),
            f"CVSS:3.1/AV:N/AC:{ac}/PR:N/UI:N/S:U/C:H/I:H/A:H",
        ))
    cursor.executemany("INSERT INTO vulnerabilities VALUES (?,?,?,?,?,?,?)", vulns)

    # ── Table 2: assets ──────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            asset_id TEXT PRIMARY KEY,
            hostname TEXT,
            ip_address TEXT,
            os TEXT,
            department TEXT,
            network_zone TEXT
        )
    """)

    assets = []
    for i in range(n):
        asset_id = f"ASSET-{1000 + i}"
        assets.append((
            asset_id,
            f"srv-{fake.lexify('????')}-{i:03d}",
            f"10.{np.random.randint(0, 255)}.{np.random.randint(0, 255)}.{np.random.randint(1, 254)}",
            str(np.random.choice(OS_LIST)),
            str(np.random.choice(DEPARTMENTS)),
            str(np.random.choice(NETWORK_ZONES)),
        ))
    cursor.executemany("INSERT INTO assets VALUES (?,?,?,?,?,?)", assets)

    # ── Table 3: scan_results ────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_results (
            scan_id TEXT PRIMARY KEY,
            asset_id TEXT,
            cve_id TEXT,
            scan_date TEXT,
            detection_status TEXT,
            port INTEGER,
            FOREIGN KEY (asset_id) REFERENCES assets(asset_id),
            FOREIGN KEY (cve_id) REFERENCES vulnerabilities(cve_id)
        )
    """)

    num_scanned_assets = max(15, n * 2 // 3)
    num_detected_vulns = max(12, n // 2)
    scanned_asset_indices = np.random.choice(n, size=min(num_scanned_assets, n), replace=False)
    detected_vuln_indices = np.random.choice(n, size=min(num_detected_vulns, n), replace=False)
    scanned_asset_ids = [assets[int(idx)][0] for idx in scanned_asset_indices]
    detected_cve_ids = [vulns[int(idx)][0] for idx in detected_vuln_indices]

    # Generate unique (asset_id, cve_id) pairs for scan results
    all_pairs = []
    for aid in scanned_asset_ids:
        for cid in detected_cve_ids:
            all_pairs.append((aid, cid))
    perm = np.random.permutation(len(all_pairs))
    selected_pairs = [all_pairs[int(p)] for p in perm[:n]]

    ports = [22, 80, 443, 3306, 5432, 8080, 8443, 6379, 27017, 9200, 3389, 445]
    scan_records = []
    for i, (aid, cid) in enumerate(selected_pairs):
        scan_records.append((
            f"SCAN-{5000 + i}",
            aid, cid,
            fake.date_between(start_date="-30d", end_date="today").isoformat(),
            "detected",
            int(np.random.choice(ports)),
        ))
    cursor.executemany("INSERT INTO scan_results VALUES (?,?,?,?,?,?)", scan_records)

    # ── Table 4: patch_deployments ───────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patch_deployments (
            deployment_id TEXT PRIMARY KEY,
            asset_id TEXT,
            cve_id TEXT,
            patch_id TEXT,
            status TEXT,
            deploy_date TEXT,
            FOREIGN KEY (asset_id) REFERENCES assets(asset_id),
            FOREIGN KEY (cve_id) REFERENCES vulnerabilities(cve_id)
        )
    """)

    patch_records = []
    patch_idx = 0
    for scan_id, aid, cid, *_ in scan_records:
        if np.random.random() < 0.65:
            status = str(np.random.choice(
                PATCH_STATUSES, p=[0.25, 0.30, 0.15, 0.15, 0.15]
            ))
            deploy_date = (
                fake.date_between(start_date="-15d", end_date="today").isoformat()
                if status == "deployed" else None
            )
            patch_records.append((
                f"PATCH-{7000 + patch_idx}",
                aid, cid,
                f"KB{np.random.randint(100000, 999999)}",
                status,
                deploy_date,
            ))
            patch_idx += 1

    # Pad to rows_per_table if needed
    while len(patch_records) < n:
        aid = str(np.random.choice(scanned_asset_ids))
        cid = str(np.random.choice(detected_cve_ids))
        status = str(np.random.choice(PATCH_STATUSES))
        deploy_date = (
            fake.date_between(start_date="-15d", end_date="today").isoformat()
            if status == "deployed" else None
        )
        patch_records.append((
            f"PATCH-{7000 + len(patch_records)}",
            aid, cid,
            f"KB{np.random.randint(100000, 999999)}",
            status,
            deploy_date,
        ))
    cursor.executemany("INSERT INTO patch_deployments VALUES (?,?,?,?,?,?)", patch_records)

    # ── Table 5: threat_intel ────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS threat_intel (
            intel_id TEXT PRIMARY KEY,
            cve_id TEXT,
            threat_actor TEXT,
            exploit_maturity TEXT,
            last_seen TEXT,
            actively_exploited INTEGER,
            campaign_name TEXT,
            FOREIGN KEY (cve_id) REFERENCES vulnerabilities(cve_id)
        )
    """)

    threat_records = []
    intel_idx = 0
    for cve_id in detected_cve_ids:
        if np.random.random() < 0.6:
            actively = int(np.random.random() < 0.4)
            threat_records.append((
                f"INTEL-{9000 + intel_idx}",
                cve_id,
                str(np.random.choice(THREAT_ACTORS)),
                str(np.random.choice(EXPLOIT_MATURITIES,
                                     p=[0.25, 0.30, 0.25, 0.20])),
                fake.date_between(start_date="-7d", end_date="today").isoformat(),
                actively,
                str(np.random.choice(CAMPAIGN_NAMES)) if actively else None,
            ))
            intel_idx += 1

    remaining_vulns = [v[0] for v in vulns if v[0] not in set(detected_cve_ids)]
    while len(threat_records) < n:
        cve_id = (str(np.random.choice(remaining_vulns))
                  if remaining_vulns
                  else str(np.random.choice(detected_cve_ids)))
        actively = int(np.random.random() < 0.3)
        threat_records.append((
            f"INTEL-{9000 + len(threat_records)}",
            cve_id,
            str(np.random.choice(THREAT_ACTORS)),
            str(np.random.choice(EXPLOIT_MATURITIES)),
            fake.date_between(start_date="-14d", end_date="today").isoformat(),
            actively,
            str(np.random.choice(CAMPAIGN_NAMES)) if actively else None,
        ))
    cursor.executemany("INSERT INTO threat_intel VALUES (?,?,?,?,?,?,?)", threat_records)

    conn.commit()
    conn.close()

    return {
        "vulns": vulns,
        "assets": assets,
        "scan_records": scan_records,
        "patch_records": patch_records,
        "threat_records": threat_records,
        "scanned_asset_ids": scanned_asset_ids,
        "detected_cve_ids": detected_cve_ids,
    }


def create_workspace(workspace, data):
    """Create workspace files from generated data."""
    os.makedirs(workspace, exist_ok=True)

    assets = data["assets"]
    n_files = SCALE["num_workspace_files"]
    n_assets = len(assets)

    # ── Scalable files: asset_criticality_batch_*.csv ────────────────────
    chunk_size = max(1, n_assets // n_files)
    for file_idx in range(n_files):
        start = file_idx * chunk_size
        if file_idx == n_files - 1:
            end = n_assets
        else:
            end = start + chunk_size

        batch_assets = assets[start:end]
        filepath = os.path.join(workspace, f"asset_criticality_batch_{file_idx + 1:03d}.csv")
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["asset_id", "criticality_score", "business_unit",
                             "data_classification", "compliance_tags"])
            for asset_row in batch_assets:
                asset_id = asset_row[0]
                crit_score = int(np.random.choice([1, 2, 3, 4, 5],
                                                  p=[0.10, 0.20, 0.30, 0.25, 0.15]))
                bu = str(np.random.choice(BUSINESS_UNITS))
                dc = str(np.random.choice(DATA_CLASSIFICATIONS,
                                          p=[0.10, 0.30, 0.35, 0.25]))
                n_tags = int(np.random.randint(1, 4))
                tags = ";".join(sorted(np.random.choice(
                    COMPLIANCE_TAGS_POOL, size=n_tags, replace=False).tolist()))
                writer.writerow([asset_id, crit_score, bu, dc, tags])

    # ── Fixed file: remediation_policy.yaml ──────────────────────────────
    policy = {
        "priority_calculation": {
            "formula": "cvss_score * criticality_multiplier * threat_multiplier * zone_multiplier",
            "rounding": 2,
        },
        "criticality_multipliers": {
            5: 3.0,
            4: 2.5,
            3: 2.0,
            2: 1.5,
            1: 1.0,
        },
        "threat_multipliers": {
            "actively_exploited_weaponized": 3.0,
            "actively_exploited_functional": 2.5,
            "actively_exploited_poc_available": 2.5,
            "actively_exploited_unproven": 2.0,
            "not_exploited_weaponized": 1.8,
            "not_exploited_functional": 1.5,
            "not_exploited_poc_available": 1.3,
            "not_exploited_unproven": 1.0,
            "no_intel": 1.0,
        },
        "priority_tiers": {
            "P1": {"min_score": 40.0, "sla_hours": 4, "action": "immediate_patch"},
            "P2": {"min_score": 25.0, "sla_hours": 24, "action": "urgent_patch"},
            "P3": {"min_score": 12.0, "sla_hours": 72, "action": "scheduled_patch"},
            "P4": {"min_score": 0.0, "sla_hours": 168, "action": "monitor_and_plan"},
        },
        "exclusion_rules": {
            "exclude_patch_status": ["deployed"],
            "minimum_cvss_threshold": 0.0,
        },
        "sorting": {
            "primary": "priority_score_desc",
            "secondary": "cvss_score_desc",
            "tertiary": "asset_id_asc",
        },
    }
    with open(os.path.join(workspace, "remediation_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # ── Fixed file: network_zone_config.json ─────────────────────────────
    zone_config = {
        "zone_multipliers": {
            "DMZ": 2.0,
            "Restricted": 1.8,
            "Internal": 1.5,
            "Cloud": 1.3,
            "Development": 1.0,
        },
        "zone_descriptions": {
            "DMZ": "Internet-facing perimeter zone",
            "Restricted": "Sensitive data and payment systems",
            "Internal": "Corporate internal network",
            "Cloud": "Cloud-hosted infrastructure",
            "Development": "Non-production development environment",
        },
    }
    with open(os.path.join(workspace, "network_zone_config.json"), "w") as f:
        json.dump(zone_config, f, indent=2)

    # ── Fixed file: incident_briefing.md ─────────────────────────────────
    briefing = """# Incident Briefing — Confidential

On the morning of the assessed date, the Security Operations Center detected
anomalous outbound traffic from several servers in the DMZ and Internal zones.
Initial forensic analysis confirmed that an advanced persistent threat actor
exploited multiple known vulnerabilities to establish footholds across the
environment. The attacker leveraged unpatched systems to move laterally,
targeting assets with elevated access to sensitive data stores.

The CISO has authorized an emergency remediation sprint. All teams must
cross-reference the latest vulnerability scan data with asset criticality
ratings, active threat intelligence, and current patch deployment records to
produce a unified, priority-ranked remediation plan. Resources are limited;
therefore the plan must sequence actions so the highest-risk exposure is
addressed first, following the organization's remediation policy framework.

Key observations from the IR team:
- The initial compromise vector involved CVEs with publicly available exploits.
- Lateral movement targeted assets in Restricted and Internal zones.
- Several patch deployments were attempted but failed or remain pending.
- Assets hosting confidential and restricted data must receive priority attention.

All remediation actions must comply with the documented SLA tiers and the
priority scoring methodology defined in organizational policy.
"""
    with open(os.path.join(workspace, "incident_briefing.md"), "w") as f:
        f.write(briefing)

    # ── Fixed file: output_schema.txt ────────────────────────────────────
    schema_doc = """Remediation Plan Output Schema
==============================

The remediation plan CSV must contain the following columns in this exact order:

  priority_rank, asset_id, hostname, cve_id, cvss_score, criticality_score,
  criticality_multiplier, threat_multiplier, zone_multiplier, priority_score,
  priority_tier, recommended_action, sla_hours

Rules:
- priority_rank is a 1-based integer reflecting the sorted position.
- priority_score must be rounded to exactly 2 decimal places.
- cvss_score retains its original precision (1 decimal place).
- All multiplier columns use the values from the policy and config files.
- Sort order: priority_score descending, then cvss_score descending,
  then asset_id ascending (lexicographic).
- Only items whose patch status is NOT 'deployed' are included.
  Items with no patch record at all are treated as unpatched and included.
- The file must be named: remediation_plan.csv
"""
    with open(os.path.join(workspace, "output_schema.txt"), "w") as f:
        f.write(schema_doc)


def main():
    parser = argparse.ArgumentParser(description="Generate task data")
    parser.add_argument("--db_path", required=True, help="Path to SQLite database")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    args = parser.parse_args()

    data = create_database(args.db_path)
    create_workspace(args.workspace, data)
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    print(f"  - {SCALE['num_workspace_files']} asset criticality CSV files")
    print(f"  - 4 fixed policy/config/schema files")
    print(f"  - {SCALE['rows_per_table']} rows per table")


if __name__ == "__main__":
    main()
