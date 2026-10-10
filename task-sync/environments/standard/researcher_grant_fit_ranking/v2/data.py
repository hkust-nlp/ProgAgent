"""
data.py – Generates the database and workspace for the researcher-grant matching task.
Usage:
    python data.py --db_path data.db --workspace workspace
"""

import os
import json
import csv
import sqlite3
import argparse
import random
import math
import numpy as np
import pandas as pd
from faker import Faker

# ──────────────────────────────────────────────
# SCALE – only this block differs across v0‥v3
# ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 120,      # v2 = 4x base
    "num_workspace_files": 24,  # v2 = base + 2N
}

# ── Constants ─────────────────────────────────
RESEARCH_FIELDS = [
    "Artificial Intelligence",
    "Machine Learning",
    "Natural Language Processing",
    "Computer Vision",
    "Data Science",
    "Cybersecurity",
    "Networks",
    "Software Engineering",
    "Database Systems",
    "Robotics",
    "Bioinformatics",
    "Human-Computer Interaction",
    "Computer Graphics",
    "Quantum Computing",
    "Theory of Computation",
]

FIELD_CLUSTER = {
    "Artificial Intelligence": 0,
    "Machine Learning": 0,
    "Natural Language Processing": 0,
    "Computer Vision": 0,
    "Data Science": 0,
    "Cybersecurity": 1,
    "Networks": 1,
    "Software Engineering": 1,
    "Database Systems": 1,
    "Robotics": 2,
    "Bioinformatics": 2,
    "Human-Computer Interaction": 2,
    "Computer Graphics": 2,
    "Quantum Computing": 3,
    "Theory of Computation": 3,
}

DEPARTMENTS = [
    "Computer Science",
    "Electrical Engineering",
    "Mathematics",
    "Physics",
    "Biology",
    "Chemistry",
    "Biomedical Engineering",
    "Information Science",
    "Statistics",
    "Mechanical Engineering",
]

AGENCIES = ["NSF", "NIH", "DARPA", "DOE", "ONR", "AFOSR", "ARO", "NASA", "IARPA", "NIST"]

CAREER_STAGES = ["early", "mid", "senior"]

CERTIFICATIONS_POOL = ["IRB", "SecurityClearance", "GLP", "IACUC", "BSL2", "RadiationSafety"]

JOURNALS = [
    "Nature", "Science", "IEEE TPAMI", "NeurIPS", "ICML", "ACL Anthology",
    "CVPR Proceedings", "AAAI", "IJCAI", "KDD", "SIGMOD", "VLDB",
    "ACM Computing Surveys", "JMLR", "Bioinformatics Journal",
    "Physical Review Letters", "Quantum", "ACM TOCHI", "SIGGRAPH",
    "IEEE S&P", "USENIX Security", "IMC", "IEEE TSE", "Artificial Intelligence",
]


def _build_taxonomy(rng: np.random.Generator) -> dict:
    """Build a symmetric field-compatibility matrix."""
    n = len(RESEARCH_FIELDS)
    mat = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            if i == j:
                mat[i][j] = 1.0
            else:
                ci = FIELD_CLUSTER[RESEARCH_FIELDS[i]]
                cj = FIELD_CLUSTER[RESEARCH_FIELDS[j]]
                if ci == cj:
                    base = 0.75
                else:
                    diff = abs(ci - cj)
                    if diff == 1:
                        base = 0.35
                    elif diff == 2:
                        base = 0.20
                    else:
                        base = 0.12
                noise = rng.uniform(-0.08, 0.08)
                val = round(max(0.05, min(0.95, base + noise)), 2)
                mat[i][j] = val
                mat[j][i] = val
    taxonomy = {}
    for i, fi in enumerate(RESEARCH_FIELDS):
        taxonomy[fi] = {}
        for j, fj in enumerate(RESEARCH_FIELDS):
            taxonomy[fi][fj] = float(mat[i][j])
    return taxonomy


def _unique_names(fake: Faker, n: int) -> list:
    names = set()
    while len(names) < n:
        names.add(fake.unique.name())
    return sorted(names)


def _unique_institutions(fake: Faker, n: int) -> list:
    names = set()
    attempts = 0
    while len(names) < n and attempts < n * 20:
        candidate = fake.city() + " University"
        if candidate not in names:
            names.add(candidate)
        attempts += 1
    # fallback for collisions
    idx = 1
    while len(names) < n:
        names.add(f"Institution {idx}")
        idx += 1
    return sorted(names)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Seed everything
    np.random.seed(42)
    rng = np.random.default_rng(42)
    random.seed(42)
    fake = Faker()
    Faker.seed(42)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    os.makedirs(args.workspace, exist_ok=True)

    # ── 1. Field taxonomy ──────────────────────
    taxonomy = _build_taxonomy(rng)

    # ── 2. Institutions ────────────────────────
    n_institutions = min(max(8, n_rows // 4), 30)
    inst_names = _unique_institutions(fake, n_institutions)
    institutions = []
    for idx, name in enumerate(inst_names):
        tier = int(rng.choice([1, 2, 3], p=[0.25, 0.45, 0.30]))
        country = fake.country()
        institutions.append({
            "id": idx + 1,
            "name": name,
            "tier": tier,
            "country": country,
        })

    # Assign departments to institutions
    inst_departments = {}
    for inst in institutions:
        nd = int(rng.integers(3, 7))
        chosen = list(rng.choice(DEPARTMENTS, size=nd, replace=False))
        inst_departments[inst["id"]] = chosen

    # ── 3. Researchers ─────────────────────────
    n_researchers = n_rows
    researcher_names = _unique_names(fake, n_researchers)
    researchers = []
    for i in range(n_researchers):
        inst = institutions[i % n_institutions]
        dept = str(rng.choice(inst_departments[inst["id"]]))
        pf = str(rng.choice(RESEARCH_FIELDS))
        sf_choices = [f for f in RESEARCH_FIELDS if f != pf]
        sf = str(rng.choice(sf_choices))
        stage = str(rng.choice(CAREER_STAGES))
        h = int(rng.integers(3, 60))
        yrs = int(rng.integers(1, 35))
        researchers.append({
            "id": i + 1,
            "name": researcher_names[i],
            "email": fake.email(),
            "institution_id": inst["id"],
            "department": dept,
            "career_stage": stage,
            "primary_field": pf,
            "secondary_field": sf,
            "h_index": h,
            "years_since_phd": yrs,
        })

    # ── 4. Funding calls ──────────────────────
    n_grants = n_rows
    funding_calls = []
    for i in range(n_grants):
        pf = str(rng.choice(RESEARCH_FIELDS))
        sf_choices = [f for f in RESEARCH_FIELDS if f != pf]
        sf = str(rng.choice(sf_choices))
        n_elig = int(rng.integers(1, 4))  # 1..3 stages
        elig = list(rng.choice(CAREER_STAGES, size=n_elig, replace=False))
        req_collab = int(rng.choice([0, 1]))
        min_team = int(rng.integers(2, 6)) if req_collab else 1
        agency = str(rng.choice(AGENCIES))
        title_words = fake.bs().title()
        funding_calls.append({
            "id": i + 1,
            "title": f"{title_words} Research Grant",
            "agency": agency,
            "max_award": int(rng.choice([50000, 100000, 250000, 500000, 1000000])),
            "deadline": fake.date_between(start_date="+30d", end_date="+365d").isoformat(),
            "primary_focus": pf,
            "secondary_focus": sf,
            "min_h_index": int(rng.integers(5, 25)),
            "eligible_stages": ",".join(sorted(elig)),
            "requires_collaboration": req_collab,
            "min_team_size": min_team,
        })

    # ── 5. Publications ───────────────────────
    publications = []
    pub_id = 1
    for r in researchers:
        n_pubs = int(rng.integers(3, 9))
        for _ in range(n_pubs):
            field_pool = [r["primary_field"], r["secondary_field"]] + list(
                rng.choice(RESEARCH_FIELDS, size=1)
            )
            field = str(rng.choice(field_pool))
            publications.append({
                "id": pub_id,
                "researcher_id": r["id"],
                "title": fake.sentence(nb_words=8).rstrip("."),
                "journal": str(rng.choice(JOURNALS)),
                "year": int(rng.integers(2015, 2026)),
                "citations": int(rng.integers(0, 200)),
                "field": field,
            })
            pub_id += 1
    # Ensure at least n_rows
    assert len(publications) >= n_rows

    # ── 6. Expenditures ───────────────────────
    expenditures = []
    exp_id = 1
    for inst in institutions:
        for dept in inst_departments[inst["id"]]:
            for yr in [2021, 2022, 2023]:
                total = round(float(rng.uniform(500_000, 10_000_000)), 2)
                ext = round(total * float(rng.uniform(0.10, 0.70)), 2)
                expenditures.append({
                    "id": exp_id,
                    "institution_id": inst["id"],
                    "department": dept,
                    "fiscal_year": yr,
                    "total_budget": total,
                    "external_funding": ext,
                })
                exp_id += 1
    assert len(expenditures) >= n_rows

    # ── 7. Collaborations ─────────────────────
    collaborations = []
    collab_id = 1
    used_pairs = set()
    researcher_ids = [r["id"] for r in researchers]
    for r in researchers:
        n_c = int(rng.integers(1, 5))
        possible = [rid for rid in researcher_ids if rid != r["id"]]
        if not possible:
            continue
        partner_ids = list(rng.choice(possible, size=min(n_c, len(possible)), replace=False))
        for pid in partner_ids:
            pair = (min(r["id"], int(pid)), max(r["id"], int(pid)))
            if pair not in used_pairs:
                used_pairs.add(pair)
                collaborations.append({
                    "id": collab_id,
                    "researcher_a_id": pair[0],
                    "researcher_b_id": pair[1],
                    "joint_publications": int(rng.integers(1, 15)),
                    "shared_field": str(rng.choice(RESEARCH_FIELDS)),
                    "last_collab_year": int(rng.integers(2018, 2026)),
                })
                collab_id += 1
    # Pad if needed
    while len(collaborations) < n_rows:
        a, b = sorted(rng.choice(researcher_ids, size=2, replace=False))
        pair = (int(a), int(b))
        if pair not in used_pairs:
            used_pairs.add(pair)
            collaborations.append({
                "id": collab_id,
                "researcher_a_id": pair[0],
                "researcher_b_id": pair[1],
                "joint_publications": int(rng.integers(1, 15)),
                "shared_field": str(rng.choice(RESEARCH_FIELDS)),
                "last_collab_year": int(rng.integers(2018, 2026)),
            })
            collab_id += 1
    assert len(collaborations) >= n_rows

    # ── 8. Create SQLite database ─────────────
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE researchers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            institution_id INTEGER,
            department TEXT,
            career_stage TEXT,
            primary_field TEXT,
            secondary_field TEXT,
            h_index INTEGER,
            years_since_phd INTEGER
        )
    """)
    for r in researchers:
        c.execute(
            "INSERT INTO researchers VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r["id"], r["name"], r["email"], r["institution_id"],
             r["department"], r["career_stage"], r["primary_field"],
             r["secondary_field"], r["h_index"], r["years_since_phd"]),
        )

    c.execute("""
        CREATE TABLE funding_calls (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            agency TEXT,
            max_award INTEGER,
            deadline TEXT,
            primary_focus TEXT,
            secondary_focus TEXT,
            min_h_index INTEGER,
            eligible_stages TEXT,
            requires_collaboration INTEGER,
            min_team_size INTEGER
        )
    """)
    for fc in funding_calls:
        c.execute(
            "INSERT INTO funding_calls VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (fc["id"], fc["title"], fc["agency"], fc["max_award"],
             fc["deadline"], fc["primary_focus"], fc["secondary_focus"],
             fc["min_h_index"], fc["eligible_stages"],
             fc["requires_collaboration"], fc["min_team_size"]),
        )

    c.execute("""
        CREATE TABLE publications (
            id INTEGER PRIMARY KEY,
            researcher_id INTEGER,
            title TEXT,
            journal TEXT,
            year INTEGER,
            citations INTEGER,
            field TEXT,
            FOREIGN KEY (researcher_id) REFERENCES researchers(id)
        )
    """)
    for p in publications:
        c.execute(
            "INSERT INTO publications VALUES (?,?,?,?,?,?,?)",
            (p["id"], p["researcher_id"], p["title"], p["journal"],
             p["year"], p["citations"], p["field"]),
        )

    c.execute("""
        CREATE TABLE expenditures (
            id INTEGER PRIMARY KEY,
            institution_id INTEGER,
            department TEXT,
            fiscal_year INTEGER,
            total_budget REAL,
            external_funding REAL,
            FOREIGN KEY (institution_id) REFERENCES researchers(institution_id)
        )
    """)
    for e in expenditures:
        c.execute(
            "INSERT INTO expenditures VALUES (?,?,?,?,?,?)",
            (e["id"], e["institution_id"], e["department"],
             e["fiscal_year"], e["total_budget"], e["external_funding"]),
        )

    c.execute("""
        CREATE TABLE collaborations (
            id INTEGER PRIMARY KEY,
            researcher_a_id INTEGER,
            researcher_b_id INTEGER,
            joint_publications INTEGER,
            shared_field TEXT,
            last_collab_year INTEGER,
            FOREIGN KEY (researcher_a_id) REFERENCES researchers(id),
            FOREIGN KEY (researcher_b_id) REFERENCES researchers(id)
        )
    """)
    for cl in collaborations:
        c.execute(
            "INSERT INTO collaborations VALUES (?,?,?,?,?,?)",
            (cl["id"], cl["researcher_a_id"], cl["researcher_b_id"],
             cl["joint_publications"], cl["shared_field"], cl["last_collab_year"]),
        )

    conn.commit()
    conn.close()

    # ── 9. Workspace – fixed config files ─────
    # 9a. scoring_config.yaml
    scoring_config = {
        "weights": {
            "field_alignment": 0.30,
            "publication_strength": 0.25,
            "expenditure_fit": 0.15,
            "collaboration_score": 0.15,
            "keyword_match": 0.15,
        },
        "thresholds": {
            "min_fit_score": 0.35,
            "top_n_per_researcher": 5,
        },
        "publication_metrics": {
            "recent_year_cutoff": 2021,
            "citation_normalization": 50,
            "max_relevant_pubs": 10,
        },
        "expenditure_metrics": {
            "target_external_ratio": 0.50,
        },
        "collaboration_metrics": {
            "field_relevance_threshold": 0.60,
        },
    }
    import yaml
    with open(os.path.join(args.workspace, "scoring_config.yaml"), "w") as f:
        yaml.dump(scoring_config, f, default_flow_style=False, sort_keys=False)

    # 9b. field_taxonomy.json
    with open(os.path.join(args.workspace, "field_taxonomy.json"), "w") as f:
        json.dump(taxonomy, f, indent=2)

    # 9c. institution_registry.csv
    with open(os.path.join(args.workspace, "institution_registry.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["institution_id", "name", "tier", "country"])
        writer.writeheader()
        for inst in institutions:
            writer.writerow({
                "institution_id": inst["id"],
                "name": inst["name"],
                "tier": inst["tier"],
                "country": inst["country"],
            })

    # 9d. eligibility_rules.json
    eligibility_rules = {
        "agency_tier_requirements": {
            "DARPA": 1,
            "IARPA": 1,
            "ONR": 2,
            "AFOSR": 2,
            "NIH": 2,
            "DOE": 2,
            "ARO": 3,
            "NASA": 2,
            "NSF": 3,
            "NIST": 3,
        },
        "agency_certification_requirements": {
            "NIH": ["IRB"],
            "DOE": ["SecurityClearance"],
            "DARPA": ["SecurityClearance"],
        },
        "min_expenditure_external_ratio": 0.25,
    }
    with open(os.path.join(args.workspace, "eligibility_rules.json"), "w") as f:
        json.dump(eligibility_rules, f, indent=2)

    # 9e. scoring_guide.md
    scoring_guide = """# Scoring Methodology

## Eligibility Filters

A researcher-grant pair is eligible only if **all** of the following hold:

1. The researcher's career stage appears in the grant's eligible career stages.
2. The researcher's h-index is greater than or equal to the grant's minimum h-index.
3. The researcher's institution tier (from institution_registry.csv) is less than or equal to the tier threshold for the grant's agency (from eligibility_rules.json `agency_tier_requirements`). Tier 1 is the most prestigious; a lower number is better.
4. If the grant's agency has certification requirements (from eligibility_rules.json `agency_certification_requirements`), the researcher must hold **every** listed certification (from their dossier file).
5. The researcher's department must have an external funding ratio (external_funding / total_budget for the most recent fiscal year) that meets or exceeds the `min_expenditure_external_ratio` in eligibility_rules.json.

## Scoring Dimensions

All dimension scores are capped at 1.0 (use `min(1.0, value)`).

### 1. Field Alignment (weight from scoring_config.yaml)

Compute all four pairwise compatibility values between {researcher.primary_field, researcher.secondary_field} and {grant.primary_focus, grant.secondary_focus} using the field taxonomy. The field alignment score is the **maximum** of these four values.

### 2. Publication Strength (weight from scoring_config.yaml)

- Identify "recent" publications: those with `year >= recent_year_cutoff`.
- Among recent publications, keep "relevant" ones: those whose `field` has a compatibility score `>= field_relevance_threshold` with the grant's `primary_focus` (using the field taxonomy).
- `count_score = min(1.0, len(relevant_pubs) / max_relevant_pubs)`
- `citation_score = min(1.0, mean(citations of relevant_pubs) / citation_normalization)`. If there are no relevant publications, citation_score = 0.
- `publication_strength = 0.6 * count_score + 0.4 * citation_score`

### 3. Expenditure Fit (weight from scoring_config.yaml)

- Look up the most recent fiscal year's expenditure record for the researcher's institution and department.
- `external_ratio = external_funding / total_budget`
- `score = min(1.0, external_ratio / target_external_ratio)`

### 4. Collaboration Score (weight from scoring_config.yaml)

- Retrieve the researcher's collaborator list.
- If the grant requires collaboration (`requires_collaboration == 1`):
  - Count "relevant" collaborators whose `shared_field` has compatibility `>= field_relevance_threshold` with the grant's `primary_focus`.
  - If `min_team_size - 1 > 0`: `score = min(1.0, relevant_count / (min_team_size - 1))`
  - If `min_team_size - 1 <= 0`: `score = 1.0` if any relevant collaborators exist, else `0.0`
- If the grant does NOT require collaboration:
  - `score = min(1.0, total_collaborators / 5)`

### 5. Keyword Match (weight from scoring_config.yaml)

- Read the researcher's `research_keywords` from their dossier file (a list of field names).
- Count how many keywords have compatibility `>= field_relevance_threshold` with the grant's `primary_focus`.
- `score = matching_count / total_keywords`. If the researcher has no keywords, score = 0.0.

## Final Score

`fit_score = sum(weight_i * score_i)` for all five dimensions, rounded to **2 decimal places**.

## Output

Only include pairs where `fit_score >= min_fit_score`. For each researcher, keep at most `top_n_per_researcher` grants, ranked by descending fit_score. Break ties by ascending grant id.

Rank starts at 1 (best match).
"""
    with open(os.path.join(args.workspace, "scoring_guide.md"), "w") as f:
        f.write(scoring_guide)

    # ── 10. Workspace – scalable dossier files ─
    # Distribute researchers across n_files JSON dossier files
    dossier_entries = []
    for r in researchers:
        n_kw = int(rng.integers(2, 6))
        other_fields = [f for f in RESEARCH_FIELDS if f not in (r["primary_field"], r["secondary_field"])]
        keywords = list(rng.choice(other_fields, size=min(n_kw, len(other_fields)), replace=False))
        # Certifications: some researchers get some
        n_cert = int(rng.choice([0, 0, 0, 1, 1, 2]))
        certs = list(rng.choice(CERTIFICATIONS_POOL, size=min(n_cert, len(CERTIFICATIONS_POOL)), replace=False)) if n_cert > 0 else []
        past_grants = int(rng.integers(0, 12))
        dossier_entries.append({
            "researcher_id": r["id"],
            "research_keywords": [str(k) for k in keywords],
            "certifications": [str(c) for c in certs],
            "past_grant_count": past_grants,
        })

    chunk_size = math.ceil(len(dossier_entries) / n_files)
    for fi in range(n_files):
        chunk = dossier_entries[fi * chunk_size : (fi + 1) * chunk_size]
        fpath = os.path.join(args.workspace, f"researcher_dossier_{fi + 1}.json")
        with open(fpath, "w") as f:
            json.dump(chunk, f, indent=2)

    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace} with {n_files} dossier files + 5 config files")
    print(f"  researchers: {len(researchers)}")
    print(f"  funding_calls: {len(funding_calls)}")
    print(f"  publications: {len(publications)}")
    print(f"  expenditures: {len(expenditures)}")
    print(f"  collaborations: {len(collaborations)}")


if __name__ == "__main__":
    main()
