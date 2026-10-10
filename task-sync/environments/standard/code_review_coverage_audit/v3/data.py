#!/usr/bin/env python3
"""Generate database and workspace for code-review audit task."""

import argparse
import json
import os
import sqlite3

import numpy as np
import pandas as pd
from faker import Faker

try:
    import yaml
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "-q"])
    import yaml

SCALE = {
    "rows_per_table": 400,       # v3 = 8x base
    "num_workspace_files": 32,   # v3 = base + 3N  (N=8)
}

FORMATS = [".csv", ".json", ".yaml", ".txt", ".md"]


def _write_profiles(path: str, profiles: list, fmt: str):
    """Write a batch of repo-profile records in *fmt*."""
    if not profiles:
        return
    if fmt == ".csv":
        pd.DataFrame(profiles).to_csv(path, index=False)
    elif fmt == ".json":
        with open(path, "w") as f:
            json.dump(profiles, f, indent=2)
    elif fmt == ".yaml":
        with open(path, "w") as f:
            yaml.dump(profiles, f, default_flow_style=False, sort_keys=False)
    elif fmt == ".txt":
        keys = list(profiles[0].keys())
        with open(path, "w") as f:
            f.write(" | ".join(keys) + "\n")
            f.write(" | ".join("---" for _ in keys) + "\n")
            for p in profiles:
                f.write(" | ".join(str(p[k]) for k in keys) + "\n")
    elif fmt == ".md":
        keys = list(profiles[0].keys())
        with open(path, "w") as f:
            f.write("| " + " | ".join(keys) + " |\n")
            f.write("| " + " | ".join("---" for _ in keys) + " |\n")
            for p in profiles:
                f.write("| " + " | ".join(str(p[k]) for k in keys) + " |\n")


def main(db_path: str, workspace: str):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    rpt = SCALE["rows_per_table"]
    nwf = SCALE["num_workspace_files"]

    # ------------------------------------------------------------------ #
    #  Table 1: repositories                                              #
    # ------------------------------------------------------------------ #
    num_repos = rpt
    languages = ["Python", "Java", "JavaScript", "Go", "Rust",
                 "TypeScript", "C++", "Ruby", "Kotlin", "Swift"]
    teams = ["Platform", "Backend", "Frontend", "Data", "Infra",
             "Mobile", "Security", "ML", "DevOps", "QA"]

    repo_names = [f"{fake.word()}-svc-{i + 1}" for i in range(num_repos)]

    repos = pd.DataFrame({
        "repo_id": range(1, num_repos + 1),
        "name": repo_names,
        "language": [str(x) for x in np.random.choice(languages, num_repos)],
        "team": [str(x) for x in np.random.choice(teams, num_repos)],
        "created_at": [fake.date_between("-3y", "-6m").isoformat()
                       for _ in range(num_repos)],
    })

    # ------------------------------------------------------------------ #
    #  Table 2: releases                                                   #
    # ------------------------------------------------------------------ #
    num_releases = rpt
    num_pending = max(int(num_releases * 0.2), 5)
    statuses = (["pending_review"] * num_pending
                + ["released"] * (num_releases - num_pending))

    releases = pd.DataFrame({
        "release_id": range(1, num_releases + 1),
        "repo_id": np.random.randint(1, num_repos + 1, num_releases).tolist(),
        "version": [f"v{np.random.randint(1,10)}.{np.random.randint(0,20)}"
                     f".{np.random.randint(0,50)}"
                     for _ in range(num_releases)],
        "planned_date": [fake.date_between("-6m", "+3m").isoformat()
                         for _ in range(num_releases)],
        "status": statuses,
    })

    # ------------------------------------------------------------------ #
    #  Table 3: pull_requests                                              #
    # ------------------------------------------------------------------ #
    author_pool = [fake.name() for _ in range(30)]
    prs_rows = []
    pr_id = 1
    for _, rel in releases.iterrows():
        n = (int(np.random.randint(3, 8))
             if rel["status"] == "pending_review"
             else int(np.random.randint(1, 5)))
        for _ in range(n):
            prs_rows.append({
                "pr_id": pr_id,
                "repo_id": int(rel["repo_id"]),
                "release_id": int(rel["release_id"]),
                "title": fake.sentence(nb_words=6),
                "author": str(np.random.choice(author_pool)),
                "lines_added": int(np.random.randint(10, 500)),
                "lines_deleted": int(np.random.randint(1, 200)),
                "files_changed": int(np.random.randint(1, 25)),
                "merged_at": fake.date_time_between("-6m", "now").isoformat(),
            })
            pr_id += 1
    prs = pd.DataFrame(prs_rows)
    assert len(prs) >= rpt, f"pull_requests has {len(prs)} rows, need >= {rpt}"

    # ------------------------------------------------------------------ #
    #  Table 4: review_comments                                            #
    # ------------------------------------------------------------------ #
    reviewer_pool = [fake.name() for _ in range(40)]
    comment_types = ["inline", "general", "suggestion", "approval",
                     "request_changes"]
    pr_author_map = dict(zip(prs["pr_id"].tolist(), prs["author"].tolist()))
    all_pr_ids = prs["pr_id"].tolist()

    num_comments = max(rpt, len(prs) * 2)
    comments_rows = []
    for i in range(num_comments):
        pid = int(np.random.choice(all_pr_ids))
        author = pr_author_map[pid]
        avail = [r for r in reviewer_pool if r != author]
        if not avail:
            avail = reviewer_pool
        comments_rows.append({
            "comment_id": i + 1,
            "pr_id": pid,
            "reviewer": str(np.random.choice(avail)),
            "comment_type": str(np.random.choice(comment_types)),
            "body_length": int(np.random.randint(10, 500)),
            "created_at": fake.date_time_between("-6m", "now").isoformat(),
        })
    comments = pd.DataFrame(comments_rows)
    assert len(comments) >= rpt

    # ------------------------------------------------------------------ #
    #  Table 5: static_analysis_violations                                 #
    # ------------------------------------------------------------------ #
    severities = ["critical", "high", "medium", "low"]
    sev_probs = [0.08, 0.17, 0.40, 0.35]
    rule_ids = [f"R{str(i).zfill(3)}" for i in range(1, 41)]

    num_violations = max(rpt, len(prs))
    viol_rows = []
    for i in range(num_violations):
        pid = int(np.random.choice(all_pr_ids))
        viol_rows.append({
            "violation_id": i + 1,
            "pr_id": pid,
            "rule_id": str(np.random.choice(rule_ids)),
            "severity": str(np.random.choice(severities, p=sev_probs)),
            "file_path": f"src/{fake.word()}/{fake.word()}.py",
            "resolved": int(np.random.choice([1, 0], p=[0.55, 0.45])),
        })
    violations = pd.DataFrame(viol_rows)
    assert len(violations) >= rpt

    # ------------------------------------------------------------------ #
    #  Table 6: defect_escapes                                             #
    # ------------------------------------------------------------------ #
    released_ids = releases[releases["status"] == "released"]["release_id"].tolist()
    components = ["auth", "api", "database", "ui", "network",
                  "storage", "cache", "logging", "config", "scheduler"]

    num_defects = max(rpt, len(released_ids))
    defect_rows = []
    for i in range(num_defects):
        rid = int(np.random.choice(released_ids))
        defect_rows.append({
            "defect_id": i + 1,
            "release_id": rid,
            "severity": str(np.random.choice(severities, p=[0.05, 0.15, 0.35, 0.45])),
            "component": str(np.random.choice(components)),
            "discovered_at": fake.date_between("-6m", "now").isoformat(),
            "description": fake.sentence(nb_words=8),
        })
    defects = pd.DataFrame(defect_rows)
    assert len(defects) >= rpt

    # ------------------------------------------------------------------ #
    #  Write database                                                      #
    # ------------------------------------------------------------------ #
    conn = sqlite3.connect(db_path)
    repos.to_sql("repositories", conn, if_exists="replace", index=False)
    releases.to_sql("releases", conn, if_exists="replace", index=False)
    prs.to_sql("pull_requests", conn, if_exists="replace", index=False)
    comments.to_sql("review_comments", conn, if_exists="replace", index=False)
    violations.to_sql("static_analysis_violations", conn, if_exists="replace", index=False)
    defects.to_sql("defect_escapes", conn, if_exists="replace", index=False)
    conn.close()

    # ================================================================== #
    #  Workspace – fixed config files                                      #
    # ================================================================== #
    policy = {
        "tiers": {
            1: {"label": "Critical",
                "min_review_coverage": 0.95,
                "min_comment_density": 0.05,
                "max_weighted_violations": 10,
                "max_defect_escape_rate": 0.02},
            2: {"label": "High",
                "min_review_coverage": 0.90,
                "min_comment_density": 0.03,
                "max_weighted_violations": 25,
                "max_defect_escape_rate": 0.05},
            3: {"label": "Standard",
                "min_review_coverage": 0.80,
                "min_comment_density": 0.02,
                "max_weighted_violations": 50,
                "max_defect_escape_rate": 0.10},
            4: {"label": "Low",
                "min_review_coverage": 0.60,
                "min_comment_density": 0.01,
                "max_weighted_violations": 100,
                "max_defect_escape_rate": 0.20},
        }
    }
    with open(os.path.join(workspace, "review_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    sev_weights = {"critical": 10, "high": 5, "medium": 2, "low": 1}
    with open(os.path.join(workspace, "severity_weights.json"), "w") as f:
        json.dump(sev_weights, f, indent=2)

    # ================================================================== #
    #  Workspace – scaling repo-profile files                              #
    # ================================================================== #
    tier_choices = [1, 2, 3, 4]
    tier_probs = [0.15, 0.30, 0.35, 0.20]
    reviewer_map = {1: 3, 2: 2, 3: 2, 4: 1}
    deploy_targets = ["production", "staging", "internal", "edge"]

    # Distribute repos across files evenly: first `remainder` files get one
    # extra repo so that every file has at least one repo.
    base_batch = max(1, num_repos // nwf)
    remainder = num_repos - base_batch * nwf

    cursor = 0
    for fi in range(nwf):
        size = base_batch + (1 if fi < remainder else 0)
        start = cursor
        end = min(start + size, num_repos)
        cursor = end
        if start >= num_repos:
            # More files requested than repos – write an empty-ish placeholder
            # that still has at least one record (wrap around).
            start = fi % num_repos
            end = start + 1
        batch = repos.iloc[start:end]

        profiles = []
        for _, repo in batch.iterrows():
            tier = int(np.random.choice(tier_choices, p=tier_probs))
            profiles.append({
                "repo_name": repo["name"],
                "criticality_tier": tier,
                "required_min_reviewers": reviewer_map[tier],
                "code_owner_team": repo["team"],
                "deployment_target": str(np.random.choice(deploy_targets)),
            })

        fmt = FORMATS[fi % len(FORMATS)]
        fname = f"repo_profiles_batch_{fi + 1}{fmt}"
        _write_profiles(os.path.join(workspace, fname), profiles, fmt)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db_path", required=True)
    p.add_argument("--workspace", required=True)
    args = p.parse_args()
    main(args.db_path, args.workspace)
