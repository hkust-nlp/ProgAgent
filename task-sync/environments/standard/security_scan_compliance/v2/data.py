import argparse
import csv
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
    "num_workspace_files": 30,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

fake = Faker()


def _rand_datetime(start: datetime, end: datetime) -> datetime:
    delta = (end - start).total_seconds()
    return start + timedelta(seconds=random.uniform(0, delta))


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Constants used during generation
# ---------------------------------------------------------------------------

DEVELOPERS = None  # populated in main()
SCAN_TYPES = ["sast", "dast", "dependency_check", "unit_tests", "lint"]
SECURITY_SCANS = ["sast", "dast", "dependency_check"]
SEVERITIES = ["critical", "high", "medium", "low"]
FINDING_STATUSES = ["open", "reviewed", "dismissed"]
TARGET_BRANCHES = ["main", "release/v2.0", "release/v3.0", "develop"]
VULN_PREFIXES = ["CVE-2025-", "CVE-2024-", "CVE-2026-"]
FILE_PATHS = [
    "src/auth/login.py", "src/api/endpoints.py", "src/core/database.py",
    "src/utils/crypto.py", "lib/http_client.js", "lib/session.js",
    "src/payments/processor.py", "src/config/settings.py",
    "src/middleware/cors.py", "src/models/user.py",
    "frontend/src/App.tsx", "frontend/src/api.ts",
    "services/worker.py", "services/queue.py",
    "infra/terraform/main.tf", "infra/docker/Dockerfile",
]


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def create_tables(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS pull_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pr_number INTEGER UNIQUE NOT NULL,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        source_branch TEXT NOT NULL,
        target_branch TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        merged_at TEXT
    );
    CREATE TABLE IF NOT EXISTS commits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pr_id INTEGER NOT NULL,
        commit_sha TEXT UNIQUE NOT NULL,
        author TEXT NOT NULL,
        message TEXT NOT NULL,
        committed_at TEXT NOT NULL,
        FOREIGN KEY (pr_id) REFERENCES pull_requests(id)
    );
    CREATE TABLE IF NOT EXISTS ci_pipelines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        commit_sha TEXT NOT NULL,
        pipeline_name TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        FOREIGN KEY (commit_sha) REFERENCES commits(commit_sha)
    );
    CREATE TABLE IF NOT EXISTS security_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pipeline_id INTEGER NOT NULL,
        tool_name TEXT NOT NULL,
        vulnerability_id TEXT NOT NULL,
        severity TEXT NOT NULL,
        file_path TEXT NOT NULL,
        line_number INTEGER NOT NULL,
        description TEXT NOT NULL,
        status TEXT NOT NULL,
        reviewed_by TEXT,
        reviewed_at TEXT,
        FOREIGN KEY (pipeline_id) REFERENCES ci_pipelines(id)
    );
    CREATE TABLE IF NOT EXISTS merge_approvals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pr_id INTEGER NOT NULL,
        approver TEXT NOT NULL,
        approved_at TEXT NOT NULL,
        FOREIGN KEY (pr_id) REFERENCES pull_requests(id)
    );
    """)


# ---------------------------------------------------------------------------
# Data generators
# ---------------------------------------------------------------------------

def generate_pull_requests(conn: sqlite3.Connection, n: int):
    """Generate n pull requests.  ~60 % merged, ~20 % open, ~20 % closed."""
    rows = []
    base_date = datetime(2026, 1, 15)
    verbs = ["Add", "Fix", "Update", "Refactor", "Implement", "Remove",
             "Improve", "Migrate", "Patch", "Integrate"]
    nouns = ["authentication flow", "payment gateway", "user dashboard",
             "rate limiter", "session manager", "logging pipeline",
             "database schema", "API endpoint", "caching layer",
             "notification service", "search indexer", "config loader",
             "error handler", "file uploader", "webhook handler"]

    for i in range(n):
        pr_number = 1001 + i
        author = random.choice(DEVELOPERS)
        verb = random.choice(verbs)
        noun = random.choice(nouns)
        title = f"{verb} {noun}"
        source_branch = random.choice(["feature/", "bugfix/", "hotfix/"]) + fake.slug()
        target_branch = random.choice(TARGET_BRANCHES)

        r = random.random()
        if r < 0.60:
            status = "merged"
        elif r < 0.80:
            status = "open"
        else:
            status = "closed"

        created_at = _rand_datetime(base_date, base_date + timedelta(days=75))
        merged_at = None
        if status == "merged":
            merged_at = created_at + timedelta(hours=random.randint(6, 336))

        rows.append((pr_number, title, author, source_branch, target_branch,
                      status, _fmt(created_at),
                      _fmt(merged_at) if merged_at else None))

    conn.executemany(
        "INSERT INTO pull_requests (pr_number,title,author,source_branch,"
        "target_branch,status,created_at,merged_at) VALUES (?,?,?,?,?,?,?,?)",
        rows)
    conn.commit()


def generate_commits(conn: sqlite3.Connection, min_rows: int):
    """Generate commits for every PR.  Ensures >= min_rows total."""
    prs = conn.execute(
        "SELECT id, pr_number, author, created_at, merged_at, status "
        "FROM pull_requests").fetchall()

    rows = []
    prefixes = ["feat:", "fix:", "refactor:", "chore:", "test:", "docs:"]
    actions = ["update validation logic", "add error handling",
               "remove deprecated call", "optimize query",
               "add unit tests", "fix null check", "bump dependency",
               "add logging", "refactor helper", "clean up imports"]

    for pr_id, pr_number, author, created_str, merged_str, status in prs:
        created = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%SZ")
        end = (datetime.strptime(merged_str, "%Y-%m-%dT%H:%M:%SZ")
               if merged_str else created + timedelta(days=7))
        n_commits = random.randint(1, 4)
        for _ in range(n_commits):
            sha = fake.sha1()[:12]
            msg = f"{random.choice(prefixes)} {random.choice(actions)}"
            committed = _rand_datetime(created, end)
            rows.append((pr_id, sha, author, msg, _fmt(committed)))

    # pad if needed
    while len(rows) < min_rows:
        pr = random.choice(prs)
        pr_id, pr_number, author, created_str, merged_str, status = pr
        created = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%SZ")
        end = (datetime.strptime(merged_str, "%Y-%m-%dT%H:%M:%SZ")
               if merged_str else created + timedelta(days=7))
        sha = fake.sha1()[:12]
        msg = f"{random.choice(prefixes)} {random.choice(actions)}"
        committed = _rand_datetime(created, end)
        rows.append((pr_id, sha, author, msg, _fmt(committed)))

    conn.executemany(
        "INSERT INTO commits (pr_id,commit_sha,author,message,committed_at) "
        "VALUES (?,?,?,?,?)", rows)
    conn.commit()


def generate_ci_pipelines(conn: sqlite3.Connection, min_rows: int):
    """Generate CI pipeline runs for commits.  Not every commit gets all scans."""
    commits = conn.execute("SELECT commit_sha FROM commits").fetchall()
    rows = []

    for (sha,) in commits:
        # pick a random subset of scan types for this commit
        n_scans = random.randint(1, 5)
        chosen = random.sample(SCAN_TYPES, min(n_scans, len(SCAN_TYPES)))
        for scan in chosen:
            status = random.choices(
                ["success", "failed", "skipped"],
                weights=[0.75, 0.15, 0.10])[0]
            start = _rand_datetime(datetime(2026, 1, 15), datetime(2026, 4, 1))
            finish = start + timedelta(minutes=random.randint(2, 45))
            rows.append((sha, scan, status, _fmt(start), _fmt(finish)))

    # pad if needed
    while len(rows) < min_rows:
        sha = random.choice(commits)[0]
        scan = random.choice(SCAN_TYPES)
        status = random.choice(["success", "failed"])
        start = _rand_datetime(datetime(2026, 1, 15), datetime(2026, 4, 1))
        finish = start + timedelta(minutes=random.randint(2, 45))
        rows.append((sha, scan, status, _fmt(start), _fmt(finish)))

    conn.executemany(
        "INSERT INTO ci_pipelines (commit_sha,pipeline_name,status,"
        "started_at,finished_at) VALUES (?,?,?,?,?)", rows)
    conn.commit()


def generate_security_findings(conn: sqlite3.Connection, min_rows: int):
    """Generate findings for security-scan pipelines."""
    pipelines = conn.execute(
        "SELECT id, pipeline_name FROM ci_pipelines "
        "WHERE pipeline_name IN ('sast','dast','dependency_check')"
    ).fetchall()

    descs = {
        "sast": [
            "SQL injection via unsanitized input",
            "Hard-coded credentials detected",
            "Insecure deserialization of user data",
            "Path traversal in file upload handler",
            "Use of weak cryptographic algorithm",
            "Cross-site scripting in template rendering",
            "Command injection through shell exec",
            "Unvalidated redirect URL",
        ],
        "dast": [
            "Missing Content-Security-Policy header",
            "Server exposes version information",
            "Cookie without Secure flag",
            "HTTP response splitting vulnerability",
            "Open redirect detected",
            "Clickjacking: missing X-Frame-Options",
        ],
        "dependency_check": [
            "Known vulnerable dependency: requests<2.31",
            "Outdated library with RCE vulnerability",
            "Transitive dependency with SSRF flaw",
            "Prototype pollution in npm package",
            "Denial-of-service in XML parser",
        ],
    }

    rows = []
    vuln_counter = 1000
    for pid, pname in pipelines:
        n_findings = random.randint(0, 4)
        for _ in range(n_findings):
            vuln_counter += 1
            vuln_id = random.choice(VULN_PREFIXES) + str(vuln_counter)
            severity = random.choices(
                SEVERITIES, weights=[0.10, 0.25, 0.35, 0.30])[0]
            fpath = random.choice(FILE_PATHS)
            line = random.randint(10, 500)
            desc = random.choice(descs.get(pname, descs["sast"]))

            # Decide review status
            stat = random.choices(
                FINDING_STATUSES, weights=[0.35, 0.45, 0.20])[0]
            reviewed_by = None
            reviewed_at = None
            if stat in ("reviewed", "dismissed"):
                reviewed_by = random.choice(DEVELOPERS)
                # sometimes reviewed AFTER the merge (premature merge case)
                if random.random() < 0.20:
                    # late review: set far in the future
                    reviewed_at = _fmt(
                        datetime(2026, 4, 10) + timedelta(days=random.randint(1, 30)))
                else:
                    reviewed_at = _fmt(
                        _rand_datetime(datetime(2026, 1, 20), datetime(2026, 4, 1)))

            rows.append((pid, pname, vuln_id, severity, fpath, line, desc,
                          stat, reviewed_by, reviewed_at))

    # pad if needed
    while len(rows) < min_rows:
        pid, pname = random.choice(pipelines)
        vuln_counter += 1
        vuln_id = random.choice(VULN_PREFIXES) + str(vuln_counter)
        severity = random.choice(SEVERITIES)
        fpath = random.choice(FILE_PATHS)
        line = random.randint(10, 500)
        desc = random.choice(descs.get(pname, descs["sast"]))
        stat = random.choice(FINDING_STATUSES)
        reviewed_by = None
        reviewed_at = None
        if stat in ("reviewed", "dismissed"):
            reviewed_by = random.choice(DEVELOPERS)
            reviewed_at = _fmt(
                _rand_datetime(datetime(2026, 1, 20), datetime(2026, 4, 5)))
        rows.append((pid, pname, vuln_id, severity, fpath, line, desc,
                      stat, reviewed_by, reviewed_at))

    conn.executemany(
        "INSERT INTO security_findings (pipeline_id,tool_name,vulnerability_id,"
        "severity,file_path,line_number,description,status,reviewed_by,"
        "reviewed_at) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()


def generate_merge_approvals(conn: sqlite3.Connection, min_rows: int):
    """Generate approval records for merged PRs."""
    merged = conn.execute(
        "SELECT id, merged_at FROM pull_requests WHERE status='merged'"
    ).fetchall()

    rows = []
    for pr_id, merged_at_str in merged:
        merged_at = datetime.strptime(merged_at_str, "%Y-%m-%dT%H:%M:%SZ")
        # 1-2 approvals per PR
        n_approvals = random.choices([1, 2], weights=[0.4, 0.6])[0]
        for _ in range(n_approvals):
            approver = random.choice(DEVELOPERS)
            approved = merged_at - timedelta(hours=random.randint(1, 48))
            rows.append((pr_id, approver, _fmt(approved)))

    # pad if needed
    while len(rows) < min_rows:
        pr_id, merged_at_str = random.choice(merged)
        merged_at = datetime.strptime(merged_at_str, "%Y-%m-%dT%H:%M:%SZ")
        approver = random.choice(DEVELOPERS)
        approved = merged_at - timedelta(hours=random.randint(1, 72))
        rows.append((pr_id, approver, _fmt(approved)))

    conn.executemany(
        "INSERT INTO merge_approvals (pr_id,approver,approved_at) "
        "VALUES (?,?,?)", rows)
    conn.commit()


# ---------------------------------------------------------------------------
# Workspace generation
# ---------------------------------------------------------------------------

def generate_workspace(conn: sqlite3.Connection, workspace: str,
                       num_data_files: int):
    """Create workspace: scalable PR metadata files + fixed policy files."""

    # ---- Fixed policy files (not counted in SCALE) ----

    # 1. scan_policy.yaml
    scan_policy = {
        "compliance_tiers": {
            "tier1": {
                "description": "Production-critical deployments",
                "required_scans": ["sast", "dast", "dependency_check"],
                "pre_merge_review_required_severities": ["critical", "high"],
            },
            "tier2": {
                "description": "Staging and pre-release deployments",
                "required_scans": ["sast", "dependency_check"],
                "pre_merge_review_required_severities": ["critical"],
            },
            "tier3": {
                "description": "Development and experimental branches",
                "required_scans": ["sast"],
                "pre_merge_review_required_severities": [],
            },
        },
        "violation_priority_matrix": {
            "unreviewed_finding": {
                "critical": "P1",
                "high": "P2",
                "medium": "P3",
                "low": "P4",
            },
            "unauthorized_review": {
                "critical": "P1",
                "high": "P2",
                "medium": "P3",
                "low": "P4",
            },
            "missing_required_scan": {
                "tier1": "P2",
                "tier2": "P3",
                "tier3": "P4",
            },
            "premature_merge": {
                "critical": "P1",
                "high": "P2",
                "medium": "P3",
                "low": "P4",
            },
        },
    }
    with open(os.path.join(workspace, "scan_policy.yaml"), "w") as f:
        yaml.dump(scan_policy, f, default_flow_style=False, sort_keys=False)

    # 2. authorized_reviewers.csv
    # First 5 developers can review critical, next 3 high, rest medium/low only
    reviewer_rows = []
    for i, dev in enumerate(DEVELOPERS):
        if i < 5:
            max_sev = "critical"
            dept = random.choice(["Security", "Platform"])
        elif i < 8:
            max_sev = "high"
            dept = random.choice(["Backend", "Frontend"])
        else:
            max_sev = "medium"
            dept = random.choice(["Backend", "Frontend", "QA", "DevOps"])
        expiry = _fmt(datetime(2026, 12, 31) - timedelta(days=random.randint(0, 200)))
        reviewer_rows.append({
            "reviewer_name": dev,
            "max_authorized_severity": max_sev,
            "certification_expiry": expiry,
            "department": dept,
        })

    with open(os.path.join(workspace, "authorized_reviewers.csv"), "w",
              newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["reviewer_name", "max_authorized_severity",
                           "certification_expiry", "department"])
        writer.writeheader()
        writer.writerows(reviewer_rows)

    # 3. sla_config.json
    sla_config = {
        "remediation_sla_hours": {
            "critical": 24,
            "high": 72,
            "medium": 168,
            "low": 720,
        },
        "sla_baseline_date": "2026-04-22T00:00:00Z",
        "escalation_policy": {
            "P1": "Immediate escalation to security lead",
            "P2": "Escalation within 24 hours",
            "P3": "Tracked in weekly review",
            "P4": "Logged for next sprint planning",
        },
    }
    with open(os.path.join(workspace, "sla_config.json"), "w") as f:
        json.dump(sla_config, f, indent=2)

    # ---- Scalable PR metadata files ----

    prs = conn.execute(
        "SELECT id, pr_number, target_branch, status FROM pull_requests"
        " ORDER BY pr_number"
    ).fetchall()

    # Assign compliance tier based on target branch + some randomness
    tier_map = {
        "main": "tier1",
        "release/v2.0": "tier1",
        "release/v3.0": "tier2",
        "develop": "tier3",
    }

    pr_metadata_all = []
    deploy_targets = {
        "tier1": "production",
        "tier2": "staging",
        "tier3": "development",
    }
    label_pool = ["security", "backend", "frontend", "urgent", "tech-debt",
                  "feature", "bugfix", "hotfix", "infrastructure", "docs"]

    for pr_id, pr_number, target_branch, status in prs:
        tier = tier_map.get(target_branch, "tier3")
        deploy = deploy_targets[tier]
        labels = random.sample(label_pool, random.randint(1, 4))
        n_tickets = random.randint(0, 3)
        tickets = [f"JIRA-{random.randint(1000, 9999)}" for _ in range(n_tickets)]
        bp_enabled = random.random() < 0.85

        pr_metadata_all.append({
            "pr_number": pr_number,
            "compliance_tier": tier,
            "deployment_target": deploy,
            "branch_protection_enabled": bp_enabled,
            "labels": labels,
            "linked_tickets": tickets,
        })

    # Split into files
    chunk_size = max(1, len(pr_metadata_all) // num_data_files)
    for file_idx in range(num_data_files):
        start = file_idx * chunk_size
        if file_idx == num_data_files - 1:
            chunk = pr_metadata_all[start:]
        else:
            chunk = pr_metadata_all[start:start + chunk_size]
        if not chunk:
            # generate a small placeholder
            chunk = [pr_metadata_all[-1]]
        fname = f"pr_metadata_{file_idx + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(chunk, f, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)

    global DEVELOPERS
    DEVELOPERS = []
    seen = set()
    while len(DEVELOPERS) < 15:
        name = fake.user_name()
        if name not in seen:
            seen.add(name)
            DEVELOPERS.append(name)

    os.makedirs(args.workspace, exist_ok=True)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]

    generate_pull_requests(conn, n)
    generate_commits(conn, n)
    generate_ci_pipelines(conn, n)
    generate_security_findings(conn, n)
    generate_merge_approvals(conn, n)

    generate_workspace(conn, args.workspace, SCALE["num_workspace_files"])

    conn.close()


if __name__ == "__main__":
    main()
