"""
Branch Protection Rule Compliance Audit - Data Generator
Generates a database and workspace files for auditing branch protection compliance.
"""

import argparse
import sqlite3
import os
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker
import yaml
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 80,
    "num_workspace_files": 8,
}

ORGS = ["alpha-corp", "beta-labs", "gamma-tech", "delta-io", "epsilon-dev"]
TEAMS = [
    "Platform", "Backend", "Frontend", "Security",
    "DevOps", "Data Engineering", "Mobile", "QA",
    "Infrastructure", "API Services",
]
BRANCH_PATTERNS = ["main", "develop", "release/*", "staging"]
CHECK_NAMES = ["ci-build", "lint-check", "security-scan", "unit-tests", "integration-tests"]
VISIBILITIES = ["public", "private", "internal"]

PROJECT_WORDS = [
    "auth", "api", "data", "web", "core", "infra", "ml", "ui", "config",
    "gateway", "proxy", "cache", "queue", "scheduler", "monitor", "logger",
    "metrics", "alert", "deploy", "test", "docs", "sdk", "cli", "dashboard",
    "search", "notify", "billing", "inventory", "analytics", "pipeline",
    "service", "worker", "handler", "engine", "bridge", "adapter", "router",
    "store", "vault", "relay", "sync", "batch", "stream", "hook", "plugin",
    "manager", "controller", "resolver", "aggregator", "transformer", "loader",
    "exporter", "importer", "validator", "formatter", "parser", "builder",
    "runner", "executor", "orchestrator", "dispatcher", "collector", "indexer",
    "scraper", "crawler", "fetcher", "poller", "watcher", "listener",
    "publisher", "subscriber", "producer", "consumer", "processor", "filter",
    "sorter", "merger", "splitter", "mapper", "reducer", "joiner", "linker",
    "tracker", "profiler", "debugger", "tracer", "sampler", "inspector",
]

SUFFIXES = [
    "service", "app", "tool", "lib", "module", "pkg", "util", "helper",
    "framework", "platform", "system", "hub", "kit", "box", "forge",
]


def _generate_all_repo_names(rng, count):
    """Generate `count` unique project-like repo names."""
    # Build a pool of all possible names
    pool = []
    for w1 in PROJECT_WORDS:
        for w2 in SUFFIXES:
            pool.append(f"{w1}-{w2}")
    # If pool is too small (unlikely given 80×15=1200), extend with numbered suffixes
    base_pool_size = len(pool)
    extra = 0
    while len(pool) < count:
        w1 = PROJECT_WORDS[extra % len(PROJECT_WORDS)]
        pool.append(f"{w1}-v{extra}")
        extra += 1
    rng.shuffle(np.array(pool))  # deterministic shuffle
    # Use first `count` from shuffled pool
    indices = rng.choice(len(pool), size=count, replace=False)
    return [pool[i] for i in sorted(indices)]


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)
    rng = np.random.default_rng(42)

    os.makedirs(workspace, exist_ok=True)

    num_repos = SCALE["rows_per_table"]
    num_rules_target = SCALE["rows_per_table"]
    num_push_events = SCALE["rows_per_table"]
    num_reviews_target = SCALE["rows_per_table"]
    num_status_checks_target = SCALE["rows_per_table"]
    num_ws_files = SCALE["num_workspace_files"]

    base_date = datetime(2025, 1, 1)

    # ── 1. Generate repositories ──
    repo_names = _generate_all_repo_names(rng, num_repos)
    repos = []
    for i in range(num_repos):
        org = ORGS[i % len(ORGS)]
        name = repo_names[i]
        repos.append({
            "id": i + 1,
            "name": name,
            "org": org,
            "visibility": VISIBILITIES[int(rng.integers(0, len(VISIBILITIES)))],
            "default_branch": "main",
            "created_at": (base_date - timedelta(days=int(rng.integers(30, 730)))).strftime("%Y-%m-%d"),
        })

    # ── 2. Assign teams to repos ──
    repo_teams = {}
    for r in repos:
        repo_teams[r["id"]] = TEAMS[int(rng.integers(0, len(TEAMS)))]

    # ── 3. Generate branch protection rules ──
    num_protected = max(int(num_repos * 0.45), 10)
    protected_repo_ids = sorted(rng.choice(num_repos, num_protected, replace=False) + 1)

    rules = []
    rule_id = 1
    for repo_id in protected_repo_ids:
        # main branch rule (always)
        min_approvals = int(rng.choice([1, 2, 2, 3]))
        req_checks = rng.choice(CHECK_NAMES, size=int(rng.integers(2, 5)), replace=False).tolist()
        enforce = int(rng.integers(0, 2))
        rules.append({
            "id": rule_id,
            "repo_id": int(repo_id),
            "branch_pattern": "main",
            "require_pull_request_reviews": 1,
            "min_approvals": min_approvals,
            "require_status_checks": 1,
            "required_status_checks": ",".join(req_checks),
            "allow_force_push": 0,
            "enforce_admins": enforce,
        })
        rule_id += 1

        # maybe add a develop branch rule
        if rng.random() < 0.4 and rule_id <= num_rules_target:
            rules.append({
                "id": rule_id,
                "repo_id": int(repo_id),
                "branch_pattern": "develop",
                "require_pull_request_reviews": 1,
                "min_approvals": max(1, min_approvals - 1),
                "require_status_checks": int(rng.integers(0, 2)),
                "required_status_checks": ",".join(req_checks[:2]),
                "allow_force_push": 0,
                "enforce_admins": 0,
            })
            rule_id += 1

        # maybe add a release/* rule
        if rng.random() < 0.2 and rule_id <= num_rules_target:
            rules.append({
                "id": rule_id,
                "repo_id": int(repo_id),
                "branch_pattern": "release/*",
                "require_pull_request_reviews": 1,
                "min_approvals": min_approvals,
                "require_status_checks": 1,
                "required_status_checks": ",".join(req_checks),
                "allow_force_push": 0,
                "enforce_admins": 1,
            })
            rule_id += 1

    # Pad rules to meet minimum if needed
    while len(rules) < num_rules_target:
        # Add more rules for protected repos with additional branch patterns
        repo_id = int(rng.choice(protected_repo_ids))
        existing_patterns = {r["branch_pattern"] for r in rules if r["repo_id"] == repo_id}
        available = [p for p in BRANCH_PATTERNS if p not in existing_patterns]
        if not available:
            available = [f"feature/{fake.word()}"]
        pattern = available[0]
        rules.append({
            "id": rule_id,
            "repo_id": repo_id,
            "branch_pattern": pattern,
            "require_pull_request_reviews": 1,
            "min_approvals": int(rng.integers(1, 3)),
            "require_status_checks": int(rng.integers(0, 2)),
            "required_status_checks": ",".join(rng.choice(CHECK_NAMES, size=2, replace=False).tolist()),
            "allow_force_push": 0,
            "enforce_admins": int(rng.integers(0, 2)),
        })
        rule_id += 1

    # ── 4. Generate users ──
    num_users = max(30, num_repos // 2)
    users = [fake.unique.user_name() for _ in range(num_users)]
    admin_users = set(rng.choice(users, size=max(5, num_users // 6), replace=False))

    # ── 5. Plan violations ──
    # We need to create merge records, push events, reviews, status checks
    # with specific violations embedded

    # Build a lookup: repo_id -> list of rules
    repo_rules = {}
    for rule in rules:
        repo_rules.setdefault(rule["repo_id"], []).append(rule)

    # Determine number of merge records: roughly num_repos * 0.6
    num_merges = max(int(num_repos * 0.6), 30)

    # Plan violations
    num_force_push_violations = max(int(num_push_events * 0.12), 6)
    num_review_violations = max(int(num_merges * 0.15), 5)
    num_status_violations = max(int(num_merges * 0.12), 4)
    num_admin_violations = max(int(num_merges * 0.08), 3)

    # ── 6. Generate merge records ──
    merge_records = []
    merge_id = 1

    # Select repos for merges - mix of protected and unprotected
    merge_repo_ids = rng.choice(num_repos, num_merges, replace=True) + 1

    # Decide which merges will be violations
    protected_merge_indices = [
        i for i, rid in enumerate(merge_repo_ids) if int(rid) in repo_rules
    ]
    if len(protected_merge_indices) < (num_review_violations + num_status_violations + num_admin_violations):
        # Replace some unprotected merges with protected ones
        unprotected = [i for i in range(num_merges) if i not in protected_merge_indices]
        needed = (num_review_violations + num_status_violations + num_admin_violations) - len(protected_merge_indices)
        for idx in unprotected[:needed]:
            merge_repo_ids[idx] = int(rng.choice(protected_repo_ids))
        protected_merge_indices = [
            i for i, rid in enumerate(merge_repo_ids) if int(rid) in repo_rules
        ]

    rng.shuffle(np.array(protected_merge_indices))
    review_violation_indices = set(protected_merge_indices[:num_review_violations])
    status_violation_indices = set(protected_merge_indices[num_review_violations:num_review_violations + num_status_violations])
    admin_violation_indices = set(protected_merge_indices[
        num_review_violations + num_status_violations:
        num_review_violations + num_status_violations + num_admin_violations
    ])

    for i in range(num_merges):
        repo_id = int(merge_repo_ids[i])
        repo = repos[repo_id - 1]
        # Pick branch based on repo rules
        if repo_id in repo_rules:
            rule = repo_rules[repo_id][0]  # primary rule (main)
            branch = rule["branch_pattern"].replace("/*", "/v1.0")
        else:
            branch = "main"

        user = users[int(rng.integers(0, len(users)))]
        is_admin = user in admin_users
        is_admin_override = (i in admin_violation_indices) and is_admin
        if i in admin_violation_indices and not is_admin:
            # Force an admin user
            user = list(admin_users)[int(rng.integers(0, len(admin_users)))]
            is_admin_override = True

        merge_time = base_date + timedelta(
            days=int(rng.integers(0, 180)),
            hours=int(rng.integers(8, 20)),
            minutes=int(rng.integers(0, 60)),
        )
        commit_sha = fake.sha1()[:12]
        pr_number = int(rng.integers(100, 9999))

        merge_records.append({
            "merge_id": merge_id,
            "repo_name": repo["name"],
            "repo_id": repo_id,
            "branch": branch,
            "pr_number": pr_number,
            "merge_commit_sha": commit_sha,
            "merged_by": user,
            "merged_at": merge_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "is_admin_override": is_admin_override,
            "is_review_violation": i in review_violation_indices,
            "is_status_violation": i in status_violation_indices,
            "is_admin_violation": i in admin_violation_indices,
        })
        merge_id += 1

    # ── 7. Generate code reviews ──
    reviews = []
    review_id = 1
    for mr in merge_records:
        repo_id = mr["repo_id"]
        if repo_id not in repo_rules:
            # Non-protected: generate 1-2 reviews anyway
            n_reviews = int(rng.integers(0, 3))
            for _ in range(n_reviews):
                reviewer = users[int(rng.integers(0, len(users)))]
                reviews.append({
                    "id": review_id,
                    "repo_id": repo_id,
                    "pr_number": mr["pr_number"],
                    "reviewer": reviewer,
                    "decision": "approved",
                    "submitted_at": mr["merged_at"],
                })
                review_id += 1
            continue

        rule = repo_rules[repo_id][0]
        min_approvals = rule["min_approvals"]

        if mr["is_review_violation"]:
            # Generate fewer approvals than required
            n_approvals = max(0, min_approvals - int(rng.integers(1, min_approvals + 1)))
            n_other = int(rng.integers(0, 3))
        else:
            # Generate enough approvals
            n_approvals = min_approvals + int(rng.integers(0, 3))
            n_other = int(rng.integers(0, 2))

        review_time_base = datetime.strptime(mr["merged_at"], "%Y-%m-%dT%H:%M:%S")
        for j in range(n_approvals):
            reviewer = users[int(rng.integers(0, len(users)))]
            reviews.append({
                "id": review_id,
                "repo_id": repo_id,
                "pr_number": mr["pr_number"],
                "reviewer": reviewer,
                "decision": "approved",
                "submitted_at": (review_time_base - timedelta(hours=int(rng.integers(1, 48)))).strftime("%Y-%m-%dT%H:%M:%S"),
            })
            review_id += 1

        for j in range(n_other):
            reviewer = users[int(rng.integers(0, len(users)))]
            decision = rng.choice(["changes_requested", "commented"])
            reviews.append({
                "id": review_id,
                "repo_id": repo_id,
                "pr_number": mr["pr_number"],
                "reviewer": reviewer,
                "decision": decision,
                "submitted_at": (review_time_base - timedelta(hours=int(rng.integers(1, 72)))).strftime("%Y-%m-%dT%H:%M:%S"),
            })
            review_id += 1

    # Pad reviews to meet minimum
    while len(reviews) < num_reviews_target:
        repo_id = int(rng.integers(1, num_repos + 1))
        reviews.append({
            "id": review_id,
            "repo_id": repo_id,
            "pr_number": int(rng.integers(100, 9999)),
            "reviewer": users[int(rng.integers(0, len(users)))],
            "decision": rng.choice(["approved", "changes_requested", "commented"]),
            "submitted_at": (base_date + timedelta(days=int(rng.integers(0, 180)))).strftime("%Y-%m-%dT%H:%M:%S"),
        })
        review_id += 1

    # ── 8. Generate status checks ──
    status_checks = []
    sc_id = 1
    for mr in merge_records:
        repo_id = mr["repo_id"]
        commit_sha = mr["merge_commit_sha"]

        if repo_id not in repo_rules:
            # Non-protected: generate a couple of passing checks
            for check in rng.choice(CHECK_NAMES, size=int(rng.integers(1, 4)), replace=False):
                status_checks.append({
                    "id": sc_id,
                    "repo_id": repo_id,
                    "commit_sha": commit_sha,
                    "check_name": check,
                    "status": "success",
                    "completed_at": mr["merged_at"],
                })
                sc_id += 1
            continue

        rule = repo_rules[repo_id][0]
        req_checks = rule["required_status_checks"].split(",") if rule["required_status_checks"] else []

        if mr["is_status_violation"] and rule["require_status_checks"]:
            # At least one required check fails
            failed_check = req_checks[int(rng.integers(0, len(req_checks)))]
            for check in req_checks:
                status = "failure" if check == failed_check else "success"
                status_checks.append({
                    "id": sc_id,
                    "repo_id": repo_id,
                    "commit_sha": commit_sha,
                    "check_name": check,
                    "status": status,
                    "completed_at": mr["merged_at"],
                })
                sc_id += 1
        else:
            # All required checks pass
            for check in req_checks:
                status_checks.append({
                    "id": sc_id,
                    "repo_id": repo_id,
                    "commit_sha": commit_sha,
                    "check_name": check,
                    "status": "success",
                    "completed_at": mr["merged_at"],
                })
                sc_id += 1

    # Pad status checks
    while len(status_checks) < num_status_checks_target:
        repo_id = int(rng.integers(1, num_repos + 1))
        status_checks.append({
            "id": sc_id,
            "repo_id": repo_id,
            "commit_sha": fake.sha1()[:12],
            "check_name": rng.choice(CHECK_NAMES),
            "status": rng.choice(["success", "success", "failure"]),
            "completed_at": (base_date + timedelta(days=int(rng.integers(0, 180)))).strftime("%Y-%m-%dT%H:%M:%S"),
        })
        sc_id += 1

    # ── 9. Generate push events ──
    push_events = []
    pe_id = 1

    # Force push violations on protected branches
    force_push_candidates = [
        rid for rid in protected_repo_ids
        if any(r["allow_force_push"] == 0 for r in repo_rules.get(int(rid), []))
    ]
    force_push_violation_repos = rng.choice(
        force_push_candidates,
        size=min(num_force_push_violations, len(force_push_candidates)),
        replace=False,
    )

    for repo_id in force_push_violation_repos:
        repo_id = int(repo_id)
        rule = [r for r in repo_rules[repo_id] if r["allow_force_push"] == 0][0]
        branch = rule["branch_pattern"].replace("/*", "/v1.0")
        user = users[int(rng.integers(0, len(users)))]
        push_time = base_date + timedelta(
            days=int(rng.integers(0, 180)),
            hours=int(rng.integers(0, 24)),
        )
        push_events.append({
            "id": pe_id,
            "repo_id": repo_id,
            "branch": branch,
            "user": user,
            "timestamp": push_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "forced": 1,
            "commit_sha": fake.sha1()[:12],
        })
        pe_id += 1

    # Normal push events to fill up
    while len(push_events) < num_push_events:
        repo_id = int(rng.integers(1, num_repos + 1))
        branch = rng.choice(["main", "develop", "feature/update", "fix/patch"])
        user = users[int(rng.integers(0, len(users)))]
        push_time = base_date + timedelta(
            days=int(rng.integers(0, 180)),
            hours=int(rng.integers(0, 24)),
        )
        forced = 0
        # Occasionally add non-violation forced pushes (on unprotected repos or allowed branches)
        if rng.random() < 0.05 and repo_id not in repo_rules:
            forced = 1
        push_events.append({
            "id": pe_id,
            "repo_id": repo_id,
            "branch": branch,
            "user": user,
            "timestamp": push_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "forced": forced,
            "commit_sha": fake.sha1()[:12],
        })
        pe_id += 1

    # ── 10. Write database ──
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE repositories (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            org TEXT NOT NULL,
            visibility TEXT NOT NULL,
            default_branch TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE branch_protection_rules (
            id INTEGER PRIMARY KEY,
            repo_id INTEGER NOT NULL,
            branch_pattern TEXT NOT NULL,
            require_pull_request_reviews INTEGER NOT NULL,
            min_approvals INTEGER NOT NULL,
            require_status_checks INTEGER NOT NULL,
            required_status_checks TEXT,
            allow_force_push INTEGER NOT NULL,
            enforce_admins INTEGER NOT NULL,
            FOREIGN KEY (repo_id) REFERENCES repositories(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE push_events (
            id INTEGER PRIMARY KEY,
            repo_id INTEGER NOT NULL,
            branch TEXT NOT NULL,
            user TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            forced INTEGER NOT NULL,
            commit_sha TEXT NOT NULL,
            FOREIGN KEY (repo_id) REFERENCES repositories(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE code_reviews (
            id INTEGER PRIMARY KEY,
            repo_id INTEGER NOT NULL,
            pr_number INTEGER NOT NULL,
            reviewer TEXT NOT NULL,
            decision TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            FOREIGN KEY (repo_id) REFERENCES repositories(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE status_checks (
            id INTEGER PRIMARY KEY,
            repo_id INTEGER NOT NULL,
            commit_sha TEXT NOT NULL,
            check_name TEXT NOT NULL,
            status TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            FOREIGN KEY (repo_id) REFERENCES repositories(id)
        )
    """)

    for r in repos:
        cursor.execute(
            "INSERT INTO repositories VALUES (?,?,?,?,?,?)",
            (r["id"], r["name"], r["org"], r["visibility"], r["default_branch"], r["created_at"]),
        )
    for r in rules:
        cursor.execute(
            "INSERT INTO branch_protection_rules VALUES (?,?,?,?,?,?,?,?,?)",
            (r["id"], r["repo_id"], r["branch_pattern"], r["require_pull_request_reviews"],
             r["min_approvals"], r["require_status_checks"], r["required_status_checks"],
             r["allow_force_push"], r["enforce_admins"]),
        )
    for p in push_events:
        cursor.execute(
            "INSERT INTO push_events VALUES (?,?,?,?,?,?,?)",
            (p["id"], p["repo_id"], p["branch"], p["user"], p["timestamp"], p["forced"], p["commit_sha"]),
        )
    for r in reviews:
        cursor.execute(
            "INSERT INTO code_reviews VALUES (?,?,?,?,?,?)",
            (r["id"], r["repo_id"], r["pr_number"], r["reviewer"], r["decision"], r["submitted_at"]),
        )
    for s in status_checks:
        cursor.execute(
            "INSERT INTO status_checks VALUES (?,?,?,?,?,?)",
            (s["id"], s["repo_id"], s["commit_sha"], s["check_name"], s["status"], s["completed_at"]),
        )

    conn.commit()
    conn.close()

    # ── 11. Write workspace files ──

    # === Fixed files (not counted in SCALE) ===

    # compliance_policy.yaml
    policy = {
        "violation_types": {
            "force_push": {
                "description": "Forced push to a branch where force pushing is disallowed by protection rules",
                "severity": "critical",
            },
            "insufficient_reviews": {
                "description": "Pull request merged without meeting the minimum approval count required by branch protection",
                "severity": "high",
            },
            "failed_status_checks": {
                "description": "Pull request merged despite one or more required status checks reporting failure",
                "severity": "high",
            },
            "admin_override": {
                "description": "Administrator bypassed branch protection on a branch with enforce-admins enabled",
                "severity": "medium",
            },
        },
        "severity_weights": {
            "critical": 10,
            "high": 7,
            "medium": 4,
            "low": 1,
        },
        "escalation_threshold": 3,
    }
    with open(os.path.join(workspace, "compliance_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # exemptions.json
    # Pick a few repos and users to exempt
    exempt_repo_names = [repos[int(i) - 1]["name"] for i in rng.choice(protected_repo_ids, size=min(3, len(protected_repo_ids)), replace=False)]
    exempt_user_entries = {}
    exempt_user_list = rng.choice(users, size=min(2, len(users)), replace=False)
    for u in exempt_user_list:
        exempt_user_entries[u] = [rng.choice(["force_push", "admin_override"])]

    exemptions = {
        "exempt_repos": exempt_repo_names,
        "exempt_users": exempt_user_entries,
        "effective_until": "2025-12-31",
    }
    with open(os.path.join(workspace, "exemptions.json"), "w") as f:
        json.dump(exemptions, f, indent=2)

    # team_ownership.csv - maps repos to teams
    with open(os.path.join(workspace, "team_ownership.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["repo_name", "team", "team_lead", "department"])
        writer.writeheader()
        for r in repos:
            team = repo_teams[r["id"]]
            writer.writerow({
                "repo_name": r["name"],
                "team": team,
                "team_lead": fake.name(),
                "department": rng.choice(["Engineering", "Platform", "Product", "Security"]),
            })

    # user_roles.yaml - classifies users as admin or developer
    user_roles = {}
    for u in users:
        user_roles[u] = {
            "role": "admin" if u in admin_users else "developer",
            "active": True,
        }
    with open(os.path.join(workspace, "user_roles.yaml"), "w") as f:
        yaml.dump({"users": user_roles}, f, default_flow_style=False, sort_keys=False)

    # reporting_template.md - describes required output format
    reporting_md = """# Violation Report Formatting Rules

Each violation in the final report must carry a weighted risk score.
The score for a single violation equals the severity weight defined in the
compliance policy for its violation type.

When a repository accumulates violations whose total weighted score meets
or exceeds the escalation threshold specified in the compliance policy,
that repository must be flagged for immediate escalation in the
executive summary.

Repositories listed in the exemptions file are fully exempt: discard
every violation attributed to them regardless of type. Individual user
exemptions are type-scoped: if a user is exempt from a specific violation
type, discard only violations of that type for that user; other violation
types for the same user still count.

The violation report CSV must be sorted first by severity weight descending
(higher weight first), then by event timestamp ascending (earliest first)
among ties of the same weight. Timestamps must appear in ISO 8601 format
without timezone (YYYY-MM-DDTHH:MM:SS).
"""
    with open(os.path.join(workspace, "reporting_template.md"), "w") as f:
        f.write(reporting_md.strip() + "\n")

    # === Scalable files (counted in SCALE) ===
    # Split merge records across num_ws_files batch files
    # Half CSV merge records, half JSON merge records (for format variety)
    num_csv_batches = num_ws_files // 2
    num_json_batches = num_ws_files - num_csv_batches

    # Prepare merge records for workspace (strip internal violation flags)
    ws_merges = []
    for mr in merge_records:
        ws_merges.append({
            "repo_name": mr["repo_name"],
            "branch": mr["branch"],
            "pr_number": mr["pr_number"],
            "merge_commit_sha": mr["merge_commit_sha"],
            "merged_by": mr["merged_by"],
            "merged_at": mr["merged_at"],
            "admin_override": mr["is_admin_override"],
        })

    # Split merge records across all batch files
    total_batches = num_csv_batches + num_json_batches
    batch_size = max(1, len(ws_merges) // total_batches)

    # CSV batches
    for batch_idx in range(num_csv_batches):
        start = batch_idx * batch_size
        end = start + batch_size if batch_idx < total_batches - 1 else len(ws_merges)
        batch = ws_merges[start:end]
        if not batch:
            # Generate a synthetic entry to ensure file is non-empty
            batch = [ws_merges[batch_idx % len(ws_merges)]]

        fname = f"merge_records_batch_{batch_idx + 1}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["repo_name", "branch", "pr_number", "merge_commit_sha", "merged_by", "merged_at", "admin_override"])
            writer.writeheader()
            for row in batch:
                writer.writerow(row)

    # JSON batches
    for batch_idx in range(num_json_batches):
        global_idx = num_csv_batches + batch_idx
        start = global_idx * batch_size
        end = start + batch_size if global_idx < total_batches - 1 else len(ws_merges)
        batch = ws_merges[start:end]
        if not batch:
            batch = [ws_merges[batch_idx % len(ws_merges)]]

        fname = f"merge_records_batch_{num_csv_batches + batch_idx + 1}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(batch, f, indent=2)

    print(f"Database written to {db_path}")
    print(f"Workspace files written to {workspace}")
    print(f"  Repositories: {len(repos)}")
    print(f"  Branch protection rules: {len(rules)}")
    print(f"  Push events: {len(push_events)}")
    print(f"  Code reviews: {len(reviews)}")
    print(f"  Status checks: {len(status_checks)}")
    print(f"  Merge records: {len(merge_records)}")
    print(f"  Workspace files: {len(os.listdir(workspace))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
