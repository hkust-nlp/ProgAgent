import argparse
import sqlite3
import os
import json
import csv
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 320,
    "num_workspace_files": 24,
}

# ── Deterministic seeds ──
random.seed(42)
np.random.seed(42)
Faker.seed(42)
fake = Faker()

# ── Domain constants ──
SERVICES = [
    "auth-service", "payment-gateway", "user-profile", "notification-engine",
    "analytics-pipeline", "search-service", "billing-system", "inventory-manager",
    "recommendation-engine", "logging-service", "config-service", "api-gateway",
]

ENVIRONMENTS = ["dev", "staging", "production", "production-critical"]
ENV_WEIGHTS = [0.30, 0.30, 0.25, 0.15]

AD_GROUPS = [
    "Engineering", "DevOps", "Security", "ProductManagement", "QA",
    "DataScience", "SRE", "Compliance", "Executives", "PlatformAdmin",
]

DEPARTMENTS = [
    "Engineering", "DevOps", "Security", "Product", "QA",
    "Data Science", "SRE", "Compliance", "Executive",
]

DEPT_BASE_GROUPS = {
    "Engineering": ["Engineering"],
    "DevOps": ["DevOps", "SRE"],
    "Security": ["Security", "Compliance"],
    "Product": ["ProductManagement"],
    "QA": ["QA"],
    "Data Science": ["DataScience"],
    "SRE": ["SRE", "DevOps"],
    "Compliance": ["Compliance"],
    "Executive": ["Executives"],
}

DEPT_ROLES = {
    "Engineering": ["Junior Engineer", "Senior Engineer", "Staff Engineer", "Team Lead"],
    "DevOps": ["DevOps Engineer", "Senior DevOps Engineer"],
    "Security": ["Security Analyst", "Security Engineer"],
    "Product": ["Product Manager", "Senior Product Manager"],
    "QA": ["QA Engineer", "Senior QA Engineer"],
    "Data Science": ["Data Scientist", "Senior Data Scientist"],
    "SRE": ["SRE Engineer", "Senior SRE Engineer"],
    "Compliance": ["Compliance Officer", "Senior Compliance Officer"],
    "Executive": ["Director", "VP"],
}

ROLE_CLEARANCE = {
    "Junior Engineer": (1, 2), "Senior Engineer": (2, 3),
    "Staff Engineer": (3, 4), "Team Lead": (3, 4),
    "DevOps Engineer": (2, 3), "Senior DevOps Engineer": (3, 4),
    "Security Analyst": (3, 4), "Security Engineer": (3, 5),
    "Product Manager": (2, 3), "Senior Product Manager": (3, 4),
    "QA Engineer": (1, 2), "Senior QA Engineer": (2, 3),
    "Data Scientist": (2, 3), "Senior Data Scientist": (3, 4),
    "SRE Engineer": (2, 4), "Senior SRE Engineer": (3, 4),
    "Compliance Officer": (3, 4), "Senior Compliance Officer": (4, 5),
    "Director": (4, 5), "VP": (4, 5),
}

SENSITIVE_SERVICES = ["auth-service", "payment-gateway", "billing-system"]

FLAG_ACTIONS = [
    "enable", "disable", "rollout", "gate", "toggle",
    "switch", "experiment", "beta", "feature", "control",
]
FLAG_DOMAINS = [
    "checkout", "auth", "dashboard", "notifications", "search", "billing",
    "inventory", "analytics", "recommendations", "onboarding", "profile",
    "messaging", "reporting", "admin_panel", "api_v2", "mobile", "sso",
    "mfa", "rate_limit", "cache", "logging", "monitoring", "alerts",
    "encryption", "compression", "batch_jobs",
]
FLAG_FEATURES = [
    "flow", "v2", "redesign", "optimization", "migration", "handler",
    "processor", "service", "module", "component", "endpoint", "pipeline",
    "worker", "scheduler", "integration",
]

AUDIT_ACTIONS = ["created", "modified", "toggled", "deleted", "rollback"]
AUDIT_ACTION_WEIGHTS = [0.15, 0.35, 0.30, 0.10, 0.10]


def generate_flag_names(n):
    """Generate n unique feature-flag names."""
    combos = []
    for a in FLAG_ACTIONS:
        for d in FLAG_DOMAINS:
            for f in FLAG_FEATURES:
                combos.append(f"{a}_{d}_{f}")
    random.shuffle(combos)
    return combos[:n]


def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # ═══════════════════════════════════════════
    # 1. Employees
    # ═══════════════════════════════════════════
    employees = []
    for i in range(1, n_rows + 1):
        dept = random.choice(DEPARTMENTS)
        role = random.choice(DEPT_ROLES[dept])
        cl_min, cl_max = ROLE_CLEARANCE[role]
        clearance = random.randint(cl_min, cl_max)
        employees.append({
            "employee_id": f"EMP{i:04d}",
            "name": fake.name(),
            "email": fake.email(),
            "department": dept,
            "role": role,
            "clearance_level": clearance,
            "is_active": 1 if random.random() > 0.05 else 0,
        })

    # ═══════════════════════════════════════════
    # 2. AD-group memberships
    # ═══════════════════════════════════════════
    employee_ad_groups = []
    ag_id = 0
    emp_group_lookup = {}
    for emp in employees:
        base_groups = list(DEPT_BASE_GROUPS[emp["department"]])
        if random.random() < 0.05:
            base_groups.append("PlatformAdmin")
        other_groups = [g for g in AD_GROUPS if g not in base_groups]
        extras = random.sample(other_groups, k=min(random.randint(0, 2), len(other_groups)))
        all_groups = sorted(set(base_groups + extras))
        emp_group_lookup[emp["employee_id"]] = all_groups
        for g in all_groups:
            ag_id += 1
            employee_ad_groups.append({
                "id": ag_id,
                "employee_id": emp["employee_id"],
                "group_name": g,
            })

    # ═══════════════════════════════════════════
    # 3. Feature flags
    # ═══════════════════════════════════════════
    flag_names = generate_flag_names(n_rows)
    flags = []
    base_date = datetime(2025, 1, 1)
    for i in range(1, n_rows + 1):
        env = str(np.random.choice(ENVIRONMENTS, p=ENV_WEIGHTS))
        service = random.choice(SERVICES)
        owner = random.choice(employees)
        created = base_date + timedelta(days=random.randint(0, 365))
        modified = created + timedelta(
            days=random.randint(0, 180),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )
        flags.append({
            "flag_id": f"FLAG{i:04d}",
            "flag_name": flag_names[i - 1],
            "service": service,
            "environment": env,
            "status": random.choice(["active", "active", "active", "inactive", "archived"]),
            "owner_id": owner["employee_id"],
            "created_at": created.strftime("%Y-%m-%d %H:%M:%S"),
            "last_modified_at": modified.strftime("%Y-%m-%d %H:%M:%S"),
        })

    # ═══════════════════════════════════════════
    # 4. Targeting rules (→ workspace files)
    # ═══════════════════════════════════════════
    targeting_rules = {}
    for flag in flags:
        owner_groups = set(emp_group_lookup.get(flag["owner_id"], []))
        n_targets = random.randint(1, 3)
        if random.random() < 0.70 and owner_groups:
            sampled = random.sample(sorted(owner_groups), min(n_targets, len(owner_groups)))
            remaining = [g for g in AD_GROUPS if g not in sampled]
            if len(sampled) < n_targets and remaining:
                sampled += random.sample(remaining, min(n_targets - len(sampled), len(remaining)))
            target_groups = sampled
        else:
            non_owner = [g for g in AD_GROUPS if g not in owner_groups]
            if non_owner:
                target_groups = random.sample(non_owner, min(n_targets, len(non_owner)))
            else:
                target_groups = random.sample(AD_GROUPS, n_targets)

        targeting_rules[flag["flag_id"]] = {
            "flag_id": flag["flag_id"],
            "flag_name": flag["flag_name"],
            "target_groups": sorted(target_groups),
            "rollout_percentage": random.choice([10, 25, 50, 75, 100]),
            "conditions": {
                "min_app_version": f"{random.randint(1, 5)}.{random.randint(0, 9)}.0",
                "platforms": sorted(random.sample(
                    ["web", "ios", "android", "desktop"],
                    k=random.randint(1, 4),
                )),
            },
        }

    # ═══════════════════════════════════════════
    # 5. Audit logs (1.5× rows for better flag coverage)
    # ═══════════════════════════════════════════
    n_audit = max(n_rows, int(n_rows * 1.5))
    audit_logs = []
    for i in range(1, n_audit + 1):
        flag = random.choice(flags)
        actor = random.choice(employees)
        action = str(np.random.choice(AUDIT_ACTIONS, p=AUDIT_ACTION_WEIGHTS))

        ts_date = base_date + timedelta(days=random.randint(0, 500))
        if random.random() < 0.25:
            hour = random.randint(8, 22)          # outside maintenance window
        else:
            if ts_date.weekday() < 5:
                hour = random.randint(2, 5)       # weekday window
            else:
                hour = random.randint(0, 7)       # weekend window

        ts = ts_date.replace(
            hour=hour,
            minute=random.randint(0, 59),
            second=random.randint(0, 59),
        )
        audit_logs.append({
            "log_id": f"LOG{i:04d}",
            "flag_id": flag["flag_id"],
            "actor_id": actor["employee_id"],
            "action": action,
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "old_value": json.dumps({"status": random.choice(["active", "inactive"])}),
            "new_value": json.dumps({"status": random.choice(["active", "inactive"])}),
            "source_ip": fake.ipv4(),
        })

    # ═══════════════════════════════════════════
    # 6. Change tickets
    # ═══════════════════════════════════════════
    ticketed_envs = {"staging", "production", "production-critical"}
    flags_with_mods = {}
    for log in audit_logs:
        if log["action"] in ("modified", "toggled"):
            fid = log["flag_id"]
            flag_env = next(f["environment"] for f in flags if f["flag_id"] == fid)
            if flag_env in ticketed_envs:
                flags_with_mods[fid] = flag_env

    security_emp_ids = [
        eid for eid, groups in emp_group_lookup.items() if "Security" in groups
    ]

    tickets = []
    ticket_counter = 0
    covered_flags = set()

    mod_flag_list = sorted(flags_with_mods.keys())
    random.shuffle(mod_flag_list)

    # Approved tickets for ~60 % of modified flags in ticketed envs
    n_with_tickets = int(len(mod_flag_list) * 0.60)
    for fid in mod_flag_list[:n_with_tickets]:
        ticket_counter += 1
        flag = next(f for f in flags if f["flag_id"] == fid)
        requester_id = flag["owner_id"]

        if flag["service"] in SENSITIVE_SERVICES:
            if random.random() < 0.55 and security_emp_ids:
                approver_id = random.choice(security_emp_ids)
            else:
                non_sec = [e["employee_id"] for e in employees if e["employee_id"] not in security_emp_ids]
                approver_id = random.choice(non_sec) if non_sec else random.choice(employees)["employee_id"]
        else:
            approver_id = random.choice(employees)["employee_id"]

        req_date = base_date + timedelta(days=random.randint(0, 400))
        tickets.append({
            "ticket_id": f"CHG{ticket_counter:04d}",
            "flag_id": fid,
            "requester_id": requester_id,
            "approver_id": approver_id,
            "change_type": random.choice(["feature_toggle", "rollout_change", "targeting_update", "emergency_change"]),
            "status": "approved",
            "requested_at": req_date.strftime("%Y-%m-%d %H:%M:%S"),
            "resolved_at": (req_date + timedelta(hours=random.randint(1, 72))).strftime("%Y-%m-%d %H:%M:%S"),
            "notes": fake.sentence(),
        })
        covered_flags.add(fid)

    # Pad with rejected / pending tickets to reach n_rows
    while len(tickets) < n_rows:
        ticket_counter += 1
        flag = random.choice(flags)
        req_date = base_date + timedelta(days=random.randint(0, 400))
        status = random.choice(["rejected", "pending"])
        tickets.append({
            "ticket_id": f"CHG{ticket_counter:04d}",
            "flag_id": flag["flag_id"],
            "requester_id": random.choice(employees)["employee_id"],
            "approver_id": random.choice(employees)["employee_id"],
            "change_type": random.choice(["feature_toggle", "rollout_change", "targeting_update", "emergency_change"]),
            "status": status,
            "requested_at": req_date.strftime("%Y-%m-%d %H:%M:%S"),
            "resolved_at": (req_date + timedelta(hours=random.randint(1, 72))).strftime("%Y-%m-%d %H:%M:%S") if status == "rejected" else "",
            "notes": fake.sentence(),
        })

    # ═══════════════════════════════════════════
    # 7. Persist to SQLite
    # ═══════════════════════════════════════════
    cursor.executescript("""
        DROP TABLE IF EXISTS audit_logs;
        DROP TABLE IF EXISTS change_tickets;
        DROP TABLE IF EXISTS feature_flags;
        DROP TABLE IF EXISTS employee_ad_groups;
        DROP TABLE IF EXISTS employees;
    """)

    cursor.execute("""
        CREATE TABLE employees (
            employee_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            department TEXT NOT NULL,
            role TEXT NOT NULL,
            clearance_level INTEGER NOT NULL,
            is_active INTEGER NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE employee_ad_groups (
            id INTEGER PRIMARY KEY,
            employee_id TEXT NOT NULL,
            group_name TEXT NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE feature_flags (
            flag_id TEXT PRIMARY KEY,
            flag_name TEXT NOT NULL,
            service TEXT NOT NULL,
            environment TEXT NOT NULL,
            status TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_modified_at TEXT NOT NULL,
            FOREIGN KEY (owner_id) REFERENCES employees(employee_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE change_tickets (
            ticket_id TEXT PRIMARY KEY,
            flag_id TEXT NOT NULL,
            requester_id TEXT NOT NULL,
            approver_id TEXT NOT NULL,
            change_type TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            resolved_at TEXT,
            notes TEXT,
            FOREIGN KEY (flag_id) REFERENCES feature_flags(flag_id),
            FOREIGN KEY (requester_id) REFERENCES employees(employee_id),
            FOREIGN KEY (approver_id) REFERENCES employees(employee_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE audit_logs (
            log_id TEXT PRIMARY KEY,
            flag_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            source_ip TEXT,
            FOREIGN KEY (flag_id) REFERENCES feature_flags(flag_id),
            FOREIGN KEY (actor_id) REFERENCES employees(employee_id)
        )
    """)

    cursor.executemany(
        "INSERT INTO employees VALUES (?,?,?,?,?,?,?)",
        [tuple(e.values()) for e in employees],
    )
    cursor.executemany(
        "INSERT INTO employee_ad_groups VALUES (?,?,?)",
        [tuple(r.values()) for r in employee_ad_groups],
    )
    cursor.executemany(
        "INSERT INTO feature_flags VALUES (?,?,?,?,?,?,?,?)",
        [tuple(f.values()) for f in flags],
    )
    cursor.executemany(
        "INSERT INTO change_tickets VALUES (?,?,?,?,?,?,?,?,?)",
        [tuple(t.values()) for t in tickets],
    )
    cursor.executemany(
        "INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?,?)",
        [tuple(a.values()) for a in audit_logs],
    )

    conn.commit()
    conn.close()

    # ═══════════════════════════════════════════
    # 8. Workspace — fixed configuration files
    # ═══════════════════════════════════════════

    # compliance_policy.yaml
    yaml_content = (
        "environment_clearance_requirements:\n"
        "  dev: 1\n"
        "  staging: 2\n"
        "  production: 3\n"
        "  production-critical: 4\n"
        "\n"
        "targeting_policy:\n"
        "  owner_must_be_member_of_targeted_group: true\n"
        "  exempt_groups:\n"
        "    - PlatformAdmin\n"
        "\n"
        "change_management:\n"
        "  ticket_required_environments:\n"
        "    - staging\n"
        "    - production\n"
        "    - production-critical\n"
        "  sensitive_service_requires_security_approval: true\n"
        "\n"
        "maintenance_windows:\n"
        "  weekday:\n"
        "    start: \"02:00\"\n"
        "    end: \"06:00\"\n"
        "  weekend:\n"
        "    start: \"00:00\"\n"
        "    end: \"08:00\"\n"
        "  timezone: UTC\n"
        "\n"
        "severity_mapping:\n"
        "  production-critical: critical\n"
        "  production: high\n"
        "  staging: medium\n"
        "  dev: low\n"
    )
    with open(os.path.join(workspace, "compliance_policy.yaml"), "w") as f:
        f.write(yaml_content)

    # sensitive_services.csv
    with open(os.path.join(workspace, "sensitive_services.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["service_name", "sensitivity_level"])
        for svc, lvl in [("auth-service", "critical"),
                         ("payment-gateway", "critical"),
                         ("billing-system", "high")]:
            writer.writerow([svc, lvl])

    # ad_group_permissions.csv
    group_perms = [
        ("Engineering", "dev,staging", "standard"),
        ("DevOps", "dev,staging,production", "elevated"),
        ("Security", "dev,staging,production,production-critical", "elevated"),
        ("PlatformAdmin", "dev,staging,production,production-critical", "admin"),
        ("ProductManagement", "dev,staging", "standard"),
        ("QA", "dev,staging", "standard"),
        ("DataScience", "dev,staging", "standard"),
        ("SRE", "dev,staging,production", "elevated"),
        ("Compliance", "dev,staging,production,production-critical", "elevated"),
        ("Executives", "dev,staging,production,production-critical", "standard"),
    ]
    with open(os.path.join(workspace, "ad_group_permissions.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["group_name", "can_modify_environments", "permission_level"])
        for row in group_perms:
            writer.writerow(row)

    # remediation_procedures.md
    remediation_md = (
        "# Remediation Procedures\n\n"
        "When a compliance violation is identified during the feature-flag audit, "
        "the corresponding remediation action below must be applied.\n\n"
        "## CLEARANCE_VIOLATION\n\n"
        "Reassign flag ownership to employee with adequate clearance level\n\n"
        "## TARGETING_VIOLATION\n\n"
        "Remove unauthorized group targeting or add owner to targeted groups\n\n"
        "## MISSING_TICKET\n\n"
        "Create retroactive change ticket and submit for emergency approval\n\n"
        "## OUT_OF_WINDOW_CHANGE\n\n"
        "Document out-of-window justification and submit incident report\n\n"
        "## SENSITIVE_NO_SECURITY_APPROVAL\n\n"
        "Escalate to security team for immediate review and approval\n"
    )
    with open(os.path.join(workspace, "remediation_procedures.md"), "w") as f:
        f.write(remediation_md)

    # ═══════════════════════════════════════════
    # 9. Workspace — scalable targeting-rule batch files
    # ═══════════════════════════════════════════
    flags_per_file = max(1, len(flags) // n_files)
    for batch_idx in range(n_files):
        start = batch_idx * flags_per_file
        end = len(flags) if batch_idx == n_files - 1 else start + flags_per_file
        batch = [
            targeting_rules[flags[j]["flag_id"]]
            for j in range(start, min(end, len(flags)))
        ]
        fname = f"targeting_rules_batch_{batch_idx + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as fp:
            json.dump(batch, fp, indent=2)

    print(f"Database : {db_path} ({n_rows} rows/table, {n_audit} audit logs)")
    print(f"Workspace: {workspace} ({n_files} batch files + 4 config files)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
