"""
Data generation script for manuscript-reviewer assignment task.
Generates a SQLite database and workspace files at the configured scale.
"""

import argparse
import csv
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
import yaml
from faker import Faker

# ── Scale configuration (only this block differs across v0-v3) ──────────────
SCALE = {
    "rows_per_table": 160,      # v3 = 8× base
    "num_workspace_files": 40,  # v3 = base + 3N  (N=10)
}
# ────────────────────────────────────────────────────────────────────────────

FIELDS = [
    "Computer Science", "Biology", "Physics",
    "Mathematics", "Medicine", "Economics",
]

FIELD_KEYWORDS = {
    "Computer Science": [
        "machine learning", "deep learning", "natural language processing",
        "computer vision", "algorithms", "data mining", "cybersecurity",
        "distributed systems", "cloud computing", "software engineering",
        "artificial intelligence", "reinforcement learning",
        "graph neural networks", "optimization", "information retrieval",
        "database systems", "robotics", "parallel computing",
        "edge computing", "federated learning",
    ],
    "Biology": [
        "genomics", "proteomics", "ecology", "evolution", "cell biology",
        "neuroscience", "microbiology", "immunology", "genetics",
        "bioinformatics", "molecular biology", "developmental biology",
        "systems biology", "synthetic biology", "epigenetics",
        "virology", "marine biology", "conservation biology",
        "structural biology", "phylogenetics",
    ],
    "Physics": [
        "quantum mechanics", "particle physics", "astrophysics",
        "condensed matter", "thermodynamics", "optics", "plasma physics",
        "nuclear physics", "string theory", "cosmology",
        "fluid dynamics", "electromagnetism", "statistical mechanics",
        "quantum computing", "gravitational waves", "dark matter",
        "superconductivity", "photonics", "acoustics", "biophysics",
    ],
    "Mathematics": [
        "number theory", "algebra", "topology", "combinatorics",
        "analysis", "probability", "statistics", "graph theory",
        "differential equations", "numerical methods", "cryptography",
        "game theory", "optimization theory", "category theory",
        "dynamical systems", "stochastic processes", "linear algebra",
        "functional analysis", "discrete mathematics", "geometry",
    ],
    "Medicine": [
        "oncology", "cardiology", "neurology", "immunotherapy",
        "epidemiology", "pharmacology", "pathology", "radiology",
        "surgery", "pediatrics", "clinical trials", "drug discovery",
        "personalized medicine", "public health", "infectious disease",
        "regenerative medicine", "telemedicine", "biomarkers",
        "medical imaging", "gene therapy",
    ],
    "Economics": [
        "macroeconomics", "microeconomics", "econometrics",
        "behavioral economics", "development economics",
        "financial economics", "labor economics", "international trade",
        "monetary policy", "fiscal policy", "game theory",
        "industrial organization", "public economics", "health economics",
        "environmental economics", "urban economics", "political economy",
        "economic growth", "inequality", "market design",
    ],
}

INSTITUTIONS = [
    "MIT", "Stanford University", "Harvard University", "UC Berkeley",
    "Oxford University", "Cambridge University", "ETH Zurich",
    "Caltech", "Princeton University", "Columbia University",
    "Yale University", "University of Chicago", "Imperial College London",
    "Tsinghua University", "University of Tokyo", "NUS Singapore",
    "Max Planck Institute", "EPFL", "University of Toronto",
    "Seoul National University",
]

CONFLICT_TYPES = [
    "co-author", "same_institution", "former_advisor", "personal_relationship",
]


def create_database(db_path, rng, fake, n_rows):
    """Create and populate the SQLite database."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ── DDL ──────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS manuscripts (
            manuscript_id   TEXT PRIMARY KEY,
            title           TEXT NOT NULL,
            field           TEXT NOT NULL,
            submission_date TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            num_pages       INTEGER NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS reviewers (
            reviewer_id           TEXT PRIMARY KEY,
            name                  TEXT NOT NULL,
            institution           TEXT NOT NULL,
            email                 TEXT NOT NULL,
            max_reviews_per_round INTEGER NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS conflicts_of_interest (
            conflict_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            reviewer_id   TEXT NOT NULL,
            manuscript_id TEXT NOT NULL,
            conflict_type TEXT NOT NULL,
            reason        TEXT,
            FOREIGN KEY (reviewer_id)   REFERENCES reviewers(reviewer_id),
            FOREIGN KEY (manuscript_id) REFERENCES manuscripts(manuscript_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS review_history (
            history_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            reviewer_id      TEXT NOT NULL,
            quality_score    REAL NOT NULL,
            timeliness_score REAL NOT NULL,
            review_year      INTEGER NOT NULL,
            FOREIGN KEY (reviewer_id) REFERENCES reviewers(reviewer_id)
        )
    """)

    # ── Manuscripts ──────────────────────────────────────────────────────
    manuscripts = []
    for i in range(n_rows):
        mid = f"M{i + 1:04d}"
        field = str(rng.choice(FIELDS))
        title = fake.sentence(nb_words=int(rng.integers(6, 13)))[:-1]
        day = int(rng.integers(1, 29))
        submission_date = f"2026-03-{day:02d}"
        num_pages = int(rng.integers(8, 35))
        manuscripts.append(
            (mid, title, field, submission_date, "pending", num_pages)
        )
    cur.executemany("INSERT INTO manuscripts VALUES (?,?,?,?,?,?)", manuscripts)

    # ── Reviewers ────────────────────────────────────────────────────────
    reviewers = []
    reviewer_inst = {}
    for i in range(n_rows):
        rid = f"R{i + 1:04d}"
        name = fake.name()
        institution = str(rng.choice(INSTITUTIONS))
        reviewer_inst[rid] = institution
        email = fake.email()
        max_rev = int(rng.integers(3, 7))  # 3-6
        reviewers.append((rid, name, institution, email, max_rev))
    cur.executemany("INSERT INTO reviewers VALUES (?,?,?,?,?)", reviewers)

    # ── Conflicts of interest ────────────────────────────────────────────
    m_ids = [m[0] for m in manuscripts]
    r_ids = [r[0] for r in reviewers]

    n_conflicts = int(n_rows * 1.5)
    seen = set()
    conflict_rows = []
    attempts = 0
    while len(conflict_rows) < n_conflicts and attempts < n_conflicts * 20:
        rid = str(rng.choice(r_ids))
        mid = str(rng.choice(m_ids))
        attempts += 1
        if (rid, mid) in seen:
            continue
        seen.add((rid, mid))
        ctype = str(rng.choice(CONFLICT_TYPES))
        if ctype == "same_institution":
            reason = f"Both affiliated with {reviewer_inst[rid]}"
        elif ctype == "co-author":
            reason = f"Co-authored paper in {int(rng.integers(2020, 2026))}"
        elif ctype == "former_advisor":
            reason = (
                f"Advisor-advisee relationship ended "
                f"{int(rng.integers(2018, 2025))}"
            )
        else:
            reason = "Declared personal relationship"
        conflict_rows.append((rid, mid, ctype, reason))

    cur.executemany(
        "INSERT INTO conflicts_of_interest "
        "(reviewer_id, manuscript_id, conflict_type, reason) VALUES (?,?,?,?)",
        conflict_rows,
    )

    # ── Review history ───────────────────────────────────────────────────
    history_rows = []
    for rid in r_ids:
        n_rev = int(rng.integers(2, 6))
        for _ in range(n_rev):
            qs = round(float(rng.uniform(3.0, 10.0)), 1)
            ts = round(float(rng.uniform(3.0, 10.0)), 1)
            yr = int(rng.integers(2022, 2027))
            history_rows.append((rid, qs, ts, yr))
    cur.executemany(
        "INSERT INTO review_history "
        "(reviewer_id, quality_score, timeliness_score, review_year) "
        "VALUES (?,?,?,?)",
        history_rows,
    )

    conn.commit()
    conn.close()
    return manuscripts, reviewers, conflict_rows, history_rows


def create_workspace(workspace, rng, n_rows, n_files, manuscripts, reviewers):
    """Generate workspace data files and fixed policy/config documents."""
    os.makedirs(workspace, exist_ok=True)

    # ── Generate keyword / expertise data (kept only in workspace) ───────
    manuscript_keywords = {}
    for mid, title, field, *_ in manuscripts:
        pool = FIELD_KEYWORDS[field]
        n_kw = int(rng.integers(4, 8))
        kws = list(rng.choice(pool, size=min(n_kw, len(pool)), replace=False))
        manuscript_keywords[mid] = [str(k) for k in kws]

    reviewer_expertise = {}
    for rid, name, institution, *_ in reviewers:
        n_f = int(rng.integers(1, 3))
        expert_fields = list(rng.choice(FIELDS, size=n_f, replace=False))
        kws = []
        for f in expert_fields:
            n_kw = int(rng.integers(3, 7))
            kws.extend(
                list(
                    rng.choice(
                        FIELD_KEYWORDS[f],
                        size=min(n_kw, len(FIELD_KEYWORDS[f])),
                        replace=False,
                    )
                )
            )
        kws = sorted(set(str(k) for k in kws))
        reviewer_expertise[rid] = {
            "name": name,
            "expertise_fields": [str(f) for f in expert_fields],
            "expertise_keywords": kws,
        }

    # ── Scalable files: half manuscript CSV, half reviewer JSON ──────────
    n_m_files = n_files // 2
    n_r_files = n_files - n_m_files

    m_ids = list(manuscript_keywords.keys())
    chunk_m = max(1, len(m_ids) // n_m_files)
    for i in range(n_m_files):
        start = i * chunk_m
        end = len(m_ids) if i == n_m_files - 1 else start + chunk_m
        batch = m_ids[start:end] if start < len(m_ids) else [m_ids[-1]]
        fp = os.path.join(workspace, f"manuscript_keywords_batch_{i + 1}.csv")
        with open(fp, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["manuscript_id", "keyword"])
            for mid in batch:
                for kw in manuscript_keywords[mid]:
                    w.writerow([mid, kw])

    r_ids = list(reviewer_expertise.keys())
    chunk_r = max(1, len(r_ids) // n_r_files)
    for i in range(n_r_files):
        start = i * chunk_r
        end = len(r_ids) if i == n_r_files - 1 else start + chunk_r
        batch = r_ids[start:end] if start < len(r_ids) else [r_ids[-1]]
        data = {rid: reviewer_expertise[rid] for rid in batch}
        fp = os.path.join(workspace, f"reviewer_expertise_{i + 1}.json")
        with open(fp, "w") as fh:
            json.dump(data, fh, indent=2)

    # ── Fixed policy / config files (not counted in SCALE) ──────────────

    # 1. Assignment policy (JSON)
    policy = {
        "reviewers_per_manuscript": 3,
        "min_quality_threshold": 5.0,
        "assignment_method": "greedy",
        "sort_manuscripts_by": "submission_date",
        "tiebreak_manuscripts_by": "manuscript_id",
        "tiebreak_reviewers_by": "reviewer_id",
    }
    with open(os.path.join(workspace, "assignment_policy.json"), "w") as fh:
        json.dump(policy, fh, indent=2)

    # 2. Scoring rubric (YAML)
    rubric = {
        "scoring_formula": {
            "keyword_match": {
                "weight": 0.6,
                "method": "jaccard_similarity",
                "description": (
                    "Jaccard similarity between manuscript keywords "
                    "and reviewer expertise keywords"
                ),
                "scale_factor": 100,
            },
            "quality": {
                "weight": 0.3,
                "source": (
                    "average of historical quality_score values "
                    "for the reviewer"
                ),
                "scale_factor": 10,
            },
            "timeliness": {
                "weight": 0.1,
                "source": (
                    "average of historical timeliness_score values "
                    "for the reviewer"
                ),
                "scale_factor": 10,
            },
        },
        "pair_score_formula": (
            "keyword_match_weight * jaccard_similarity * 100 "
            "+ quality_weight * avg_quality * 10 "
            "+ timeliness_weight * avg_timeliness * 10"
        ),
        "assignment_score": (
            "sum of pair_scores for all reviewers assigned "
            "to the manuscript"
        ),
    }
    with open(os.path.join(workspace, "scoring_rubric.yaml"), "w") as fh:
        yaml.dump(rubric, fh, default_flow_style=False, sort_keys=False)

    # 3. Load-balancing guidelines (TXT)
    lb = (
        "Reviewer Load-Balancing Guidelines\n"
        "===================================\n\n"
        "When multiple reviewers have equal pair scores for a manuscript,\n"
        "preference is given to the reviewer who currently has fewer\n"
        "assignments in this round. If current assignment counts are also\n"
        "equal, the reviewer whose identifier comes first alphabetically\n"
        "(i.e. ascending reviewer_id) is selected.\n\n"
        "Reviewers who have already reached their maximum review capacity\n"
        "for the round must not receive additional assignments under any\n"
        "circumstances.\n"
    )
    with open(
        os.path.join(workspace, "load_balancing_guidelines.txt"), "w"
    ) as fh:
        fh.write(lb)

    # 4. Quality-tier definitions (Markdown)
    qt = (
        "# Reviewer Quality Tiers\n\n"
        "Reviewers are classified into quality tiers based on their "
        "average\nhistorical quality score.\n\n"
        "| Tier | Avg Quality Score Range | Notes |\n"
        "|------|------------------------|-------|\n"
        "| Gold | 8.0 and above | Priority for complex manuscripts |\n"
        "| Silver | 6.0 to 7.99 | Standard assignment pool |\n"
        "| Bronze | 5.0 to 5.99 | Eligible but lower priority |\n"
        "| Ineligible | Below 5.0 | Must not be assigned |\n\n"
        "The minimum quality threshold specified in the assignment policy\n"
        "defines the hard cutoff below which a reviewer is excluded from\n"
        "the eligible pool entirely.\n"
    )
    with open(os.path.join(workspace, "quality_tiers.md"), "w") as fh:
        fh.write(qt)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Seed everything
    rng = np.random.default_rng(42)
    random.seed(42)
    fake = Faker()
    Faker.seed(42)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    manuscripts, reviewers, conflicts, history = create_database(
        args.db_path, rng, fake, n_rows
    )
    create_workspace(
        args.workspace, rng, n_rows, n_files, manuscripts, reviewers
    )
    print(f"Database created at {args.db_path}")
    print(
        f"Workspace created at {args.workspace} "
        f"with {n_files} scalable data files + 4 fixed files"
    )


if __name__ == "__main__":
    main()
