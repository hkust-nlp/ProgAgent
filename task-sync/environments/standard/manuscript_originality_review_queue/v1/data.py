"""
Data generation script for manuscript originality verification task.
Generates database and workspace files for plagiarism detection evaluation.
"""
import os
import json
import csv
import sqlite3
import argparse
import random
import numpy as np
from faker import Faker

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 20,
}

SEED = 42

DISCIPLINES = [
    "Biology", "Computer Science", "Chemistry", "Physics",
    "Medicine", "Psychology", "Economics",
]

REPOSITORIES = [
    "PubMed Central", "arXiv Open Access", "DOAJ",
    "Europe PMC", "Semantic Scholar",
]

PREPRINT_SERVERS = [
    "bioRxiv", "medRxiv", "arXiv", "SSRN", "Preprints.org",
]

RETRACTION_REASONS = [
    "Data fabrication", "Plagiarism", "Image manipulation",
    "Duplicate publication", "Authorship dispute", "Ethical violation",
    "Statistical errors", "Unreliable results",
]

TITLE_PREFIXES = {
    "Biology": ["Molecular", "Genomic", "Cellular", "Evolutionary", "Ecological", "Proteomic", "Transcriptomic"],
    "Computer Science": ["Scalable", "Distributed", "Neural", "Adaptive", "Robust", "Efficient", "Hierarchical"],
    "Chemistry": ["Catalytic", "Synthetic", "Electrochemical", "Polymeric", "Photochemical", "Stereoselective", "Biomimetic"],
    "Physics": ["Quantum", "Relativistic", "Topological", "Nonlinear", "Thermodynamic", "Mesoscopic", "Optomechanical"],
    "Medicine": ["Clinical", "Therapeutic", "Diagnostic", "Epidemiological", "Pharmacological", "Translational", "Interventional"],
    "Psychology": ["Cognitive", "Behavioral", "Developmental", "Social", "Neuropsychological", "Motivational", "Perceptual"],
    "Economics": ["Macroeconomic", "Econometric", "Fiscal", "Monetary", "Microeconomic", "Stochastic", "Structural"],
}

TITLE_TOPICS = {
    "Biology": ["Gene Expression Patterns", "Protein Folding Dynamics", "Cell Signaling Cascades",
                 "Metabolic Pathway Regulation", "Immune Response Modulation", "DNA Repair Mechanisms",
                 "Stem Cell Differentiation", "Enzyme Kinetics", "Epigenetic Modifications",
                 "Membrane Transport Systems", "Apoptotic Pathways", "Chromosomal Rearrangement"],
    "Computer Science": ["Deep Learning Architectures", "Graph Neural Networks", "Natural Language Understanding",
                          "Reinforcement Learning Policies", "Computer Vision Pipelines", "Federated Learning Protocols",
                          "Knowledge Graph Embeddings", "Anomaly Detection Frameworks", "Attention Mechanisms",
                          "Generative Adversarial Models", "Transfer Learning Strategies", "Contrastive Representations"],
    "Chemistry": ["Reaction Mechanisms", "Molecular Synthesis Routes", "Catalyst Design Principles",
                   "Polymer Network Formation", "Spectroscopic Analysis Methods", "Nanoparticle Self-Assembly",
                   "Metal-Organic Frameworks", "Redox Flow Systems", "Supramolecular Architectures",
                   "Enantioselective Processes", "Photovoltaic Materials", "Coordination Compounds"],
    "Physics": ["Phase Transition Dynamics", "Wave Propagation Effects", "Spin-Orbit Coupling",
                 "Optical Lattice Configurations", "Superconducting Gap Symmetry", "Dark Matter Candidates",
                 "Gravitational Wave Signatures", "Plasma Confinement Strategies", "Bose-Einstein Condensation",
                 "Topological Insulator States", "Quasiparticle Interactions", "Magnetic Skyrmion Lattices"],
    "Medicine": ["Drug Resistance Mechanisms", "Tumor Biomarker Panels", "Vaccine Efficacy Trials",
                  "Autoimmune Disorder Pathways", "Surgical Outcome Predictors", "Patient Stratification Models",
                  "Biomarker Validation Studies", "Treatment Protocol Optimization", "Immunotherapy Response Rates",
                  "Dosage Escalation Frameworks", "Comorbidity Risk Profiles", "Microbiome Interventions"],
    "Psychology": ["Memory Consolidation Processes", "Attentional Control Networks", "Emotional Regulation Strategies",
                    "Decision-Making Under Uncertainty", "Language Acquisition Trajectories", "Chronic Stress Responses",
                    "Social Cognition Mechanisms", "Perceptual Bias Effects", "Executive Function Development",
                    "Reward Processing Circuits", "Implicit Learning Paradigms", "Cognitive Flexibility Measures"],
    "Economics": ["Market Volatility Dynamics", "Trade Policy Implications", "Income Inequality Trajectories",
                   "Inflation Expectation Models", "Labor Market Frictions", "Financial Regulation Effects",
                   "Endogenous Growth Theories", "Consumer Behavior Anomalies", "Credit Risk Assessment",
                   "Fiscal Multiplier Estimates", "Exchange Rate Determinants", "Wealth Distribution Patterns"],
}

TITLE_METHODS = [
    "Analysis", "Characterization", "Investigation", "Modeling",
    "Framework", "Assessment", "Evaluation", "Study",
    "Simulation", "Optimization",
]

TITLE_CONTEXTS = [
    "in Complex Systems", "Under Variable Conditions", "Across Multiple Domains",
    "with Novel Approaches", "Using Advanced Methods", "Through Comparative Analysis",
    "via Integrated Techniques", "for Improved Outcomes", "Under Realistic Constraints",
    "with Heterogeneous Data",
]


def generate_title(fake, discipline, rng):
    prefix = rng.choice(TITLE_PREFIXES[discipline])
    topic = rng.choice(TITLE_TOPICS[discipline])
    method = rng.choice(TITLE_METHODS)
    context = rng.choice(TITLE_CONTEXTS)
    template_idx = rng.randint(0, 3)
    if template_idx == 0:
        return f"{prefix} {method} of {topic} {context}"
    elif template_idx == 1:
        return f"A {prefix} Approach to {topic}: {method} {context}"
    elif template_idx == 2:
        return f"{topic}: {prefix} {method} {context}"
    else:
        return f"Towards {prefix} Understanding of {topic} {context}"


def generate_abstract(fake, title, n_sentences=6):
    base_topic = title.split(":")[0].strip().lower()
    opening = f"This paper presents a comprehensive study on {base_topic}."
    body = fake.paragraph(nb_sentences=max(2, n_sentences - 2))
    closing = "Our results demonstrate significant improvements over existing baselines and open new avenues for future research."
    return f"{opening} {body} {closing}"


def generate_full_text(fake, title, abstract, rng, word_target=600):
    sections = ["Introduction", "Related Work", "Methodology", "Experiments", "Results", "Discussion", "Conclusion"]
    parts = [f"Abstract: {abstract}\n"]
    words_per_section = max(40, word_target // len(sections))
    for section in sections:
        parts.append(f"\n{section}\n")
        n_para = max(1, words_per_section // 60)
        for _ in range(n_para):
            parts.append(fake.paragraph(nb_sentences=rng.randint(3, 6)))
    parts.append("\nReferences\n")
    n_refs = rng.randint(8, 25)
    for i in range(n_refs):
        year = rng.randint(2010, 2025)
        parts.append(f"[{i+1}] {fake.name()}, {fake.sentence(nb_words=6)} ({year}).")
    return "\n\n".join(parts)


def main(db_path, workspace):
    np.random.seed(SEED)
    random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)
    fake.seed_instance(SEED)
    rng = random.Random(SEED)

    os.makedirs(workspace, exist_ok=True)

    num_rows = SCALE["rows_per_table"]
    num_pending = SCALE["num_workspace_files"]

    # ----------------------------------------------------------------
    # Generate manuscripts
    # ----------------------------------------------------------------
    manuscripts = []
    for i in range(num_rows):
        mid = f"MS-{i+1:04d}"
        disc = DISCIPLINES[i % len(DISCIPLINES)]
        title = generate_title(fake, disc, rng)
        abstract = generate_abstract(fake, title)
        n_authors = rng.randint(1, 4)
        authors = ", ".join([fake.name() for _ in range(n_authors)])
        sub_date = str(fake.date_between(start_date="-2y", end_date="today"))
        status = "pending_review" if i < num_pending else rng.choice(["reviewed", "accepted", "rejected"])
        manuscripts.append({
            "manuscript_id": mid,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "discipline": disc,
            "submission_date": sub_date,
            "status": status,
        })

    # ----------------------------------------------------------------
    # Generate repository articles
    # ----------------------------------------------------------------
    repo_articles = []
    for i in range(num_rows):
        aid = f"OA-{i+1:04d}"
        disc = DISCIPLINES[i % len(DISCIPLINES)]
        title = generate_title(fake, disc, rng)
        n_authors = rng.randint(1, 4)
        authors = ", ".join([fake.name() for _ in range(n_authors)])
        abstract = generate_abstract(fake, title)
        pub_date = str(fake.date_between(start_date="-5y", end_date="-6m"))
        repo = rng.choice(REPOSITORIES)
        doi = f"10.{rng.randint(1000, 9999)}/{fake.lexify('??????')}.{rng.randint(2018, 2025)}"
        repo_articles.append({
            "article_id": aid, "title": title, "authors": authors,
            "abstract": abstract, "publication_date": pub_date,
            "repository": repo, "doi": doi, "discipline": disc,
        })

    # ----------------------------------------------------------------
    # Generate preprint articles
    # ----------------------------------------------------------------
    preprint_articles = []
    for i in range(num_rows):
        aid = f"PP-{i+1:04d}"
        disc = DISCIPLINES[i % len(DISCIPLINES)]
        title = generate_title(fake, disc, rng)
        n_authors = rng.randint(1, 4)
        authors = ", ".join([fake.name() for _ in range(n_authors)])
        abstract = generate_abstract(fake, title)
        post_date = str(fake.date_between(start_date="-3y", end_date="-1m"))
        server = rng.choice(PREPRINT_SERVERS)
        doi = f"10.{rng.randint(1000, 9999)}/preprint.{fake.lexify('??????')}"
        preprint_articles.append({
            "article_id": aid, "title": title, "authors": authors,
            "abstract": abstract, "post_date": post_date,
            "server": server, "doi": doi, "discipline": disc,
        })

    # ----------------------------------------------------------------
    # Generate similarity results
    # ----------------------------------------------------------------
    similarity_results = []
    used_pairs = set()

    for i in range(num_pending):
        mid = manuscripts[i]["manuscript_id"]

        # Determine similarity tier for this manuscript
        if i < num_pending // 3:
            base_lo, base_hi = 0.50, 0.92   # high similarity
        elif i < 2 * num_pending // 3:
            base_lo, base_hi = 0.28, 0.62   # medium similarity
        else:
            base_lo, base_hi = 0.05, 0.38   # low similarity

        # Repository matches (2-4)
        n_repo = rng.randint(2, 4)
        repo_indices = rng.sample(range(num_rows), n_repo)
        for ri in repo_indices:
            aid = f"OA-{ri+1:04d}"
            pair_key = (mid, aid, "repository")
            if pair_key in used_pairs:
                continue
            used_pairs.add(pair_key)
            base = rng.uniform(base_lo, base_hi)
            text_sim = round(max(0.0, min(1.0, base + rng.uniform(-0.08, 0.08))), 4)
            cit_over = round(max(0.0, min(1.0, base + rng.uniform(-0.12, 0.12))), 4)
            str_sim = round(max(0.0, min(1.0, base + rng.uniform(-0.10, 0.10))), 4)
            similarity_results.append({
                "manuscript_id": mid, "article_id": aid, "source": "repository",
                "text_similarity": text_sim, "citation_overlap": cit_over,
                "structural_similarity": str_sim,
            })

        # Preprint matches (1-3)
        n_pre = rng.randint(1, 3)
        pre_indices = rng.sample(range(num_rows), n_pre)
        for pi in pre_indices:
            aid = f"PP-{pi+1:04d}"
            pair_key = (mid, aid, "preprint")
            if pair_key in used_pairs:
                continue
            used_pairs.add(pair_key)
            base = rng.uniform(max(0.0, base_lo - 0.05), base_hi)
            text_sim = round(max(0.0, min(1.0, base + rng.uniform(-0.08, 0.08))), 4)
            cit_over = round(max(0.0, min(1.0, base + rng.uniform(-0.12, 0.12))), 4)
            str_sim = round(max(0.0, min(1.0, base + rng.uniform(-0.10, 0.10))), 4)
            similarity_results.append({
                "manuscript_id": mid, "article_id": aid, "source": "preprint",
                "text_similarity": text_sim, "citation_overlap": cit_over,
                "structural_similarity": str_sim,
            })

    # Pad similarity_results with non-pending manuscript matches
    for i in range(num_pending, num_rows):
        mid = manuscripts[i]["manuscript_id"]
        n_matches = rng.randint(1, 3)
        for _ in range(n_matches):
            source = rng.choice(["repository", "preprint"])
            prefix = "OA" if source == "repository" else "PP"
            idx = rng.randint(0, num_rows - 1)
            aid = f"{prefix}-{idx+1:04d}"
            pair_key = (mid, aid, source)
            if pair_key in used_pairs:
                continue
            used_pairs.add(pair_key)
            similarity_results.append({
                "manuscript_id": mid, "article_id": aid, "source": source,
                "text_similarity": round(rng.uniform(0.0, 0.45), 4),
                "citation_overlap": round(rng.uniform(0.0, 0.40), 4),
                "structural_similarity": round(rng.uniform(0.0, 0.42), 4),
            })

    # ----------------------------------------------------------------
    # Generate retraction watchlist
    # ----------------------------------------------------------------
    retraction_entries = []
    severities = ["high", "medium", "low"]

    # Ensure ~30% of pending manuscripts have an author on watchlist
    n_overlap = max(2, num_pending * 3 // 10)
    overlap_indices = rng.sample(range(num_pending), n_overlap)
    watchlist_authors_pending = {}
    for idx in overlap_indices:
        author_list = [a.strip() for a in manuscripts[idx]["authors"].split(",")]
        chosen = rng.choice(author_list)
        watchlist_authors_pending[chosen] = rng.choice(severities)

    entry_id = 1
    for author, severity in watchlist_authors_pending.items():
        retraction_entries.append({
            "entry_id": entry_id,
            "author_name": author,
            "original_paper_title": fake.sentence(nb_words=8),
            "retraction_date": str(fake.date_between(start_date="-3y", end_date="-1m")),
            "reason": rng.choice(RETRACTION_REASONS),
            "severity": severity,
        })
        entry_id += 1

    while len(retraction_entries) < num_rows:
        retraction_entries.append({
            "entry_id": entry_id,
            "author_name": fake.name(),
            "original_paper_title": fake.sentence(nb_words=8),
            "retraction_date": str(fake.date_between(start_date="-5y", end_date="-1m")),
            "reason": rng.choice(RETRACTION_REASONS),
            "severity": rng.choice(severities),
        })
        entry_id += 1

    # ----------------------------------------------------------------
    # Create database
    # ----------------------------------------------------------------
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE manuscripts (
            manuscript_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT NOT NULL,
            abstract TEXT,
            discipline TEXT NOT NULL,
            submission_date TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE repository_articles (
            article_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT NOT NULL,
            abstract TEXT,
            publication_date TEXT,
            repository TEXT,
            doi TEXT,
            discipline TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE preprint_articles (
            article_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT NOT NULL,
            abstract TEXT,
            post_date TEXT,
            server TEXT,
            doi TEXT,
            discipline TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE similarity_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manuscript_id TEXT NOT NULL,
            article_id TEXT NOT NULL,
            source TEXT NOT NULL,
            text_similarity REAL NOT NULL,
            citation_overlap REAL NOT NULL,
            structural_similarity REAL NOT NULL,
            FOREIGN KEY (manuscript_id) REFERENCES manuscripts(manuscript_id)
        )
    """)

    cur.execute("""
        CREATE TABLE retraction_watchlist (
            entry_id INTEGER PRIMARY KEY,
            author_name TEXT NOT NULL,
            original_paper_title TEXT,
            retraction_date TEXT,
            reason TEXT,
            severity TEXT NOT NULL
        )
    """)

    for m in manuscripts:
        cur.execute(
            "INSERT INTO manuscripts VALUES (?,?,?,?,?,?,?)",
            (m["manuscript_id"], m["title"], m["authors"], m["abstract"],
             m["discipline"], m["submission_date"], m["status"]),
        )
    for a in repo_articles:
        cur.execute(
            "INSERT INTO repository_articles VALUES (?,?,?,?,?,?,?,?)",
            (a["article_id"], a["title"], a["authors"], a["abstract"],
             a["publication_date"], a["repository"], a["doi"], a["discipline"]),
        )
    for a in preprint_articles:
        cur.execute(
            "INSERT INTO preprint_articles VALUES (?,?,?,?,?,?,?,?)",
            (a["article_id"], a["title"], a["authors"], a["abstract"],
             a["post_date"], a["server"], a["doi"], a["discipline"]),
        )
    for s in similarity_results:
        cur.execute(
            "INSERT INTO similarity_results (manuscript_id, article_id, source, "
            "text_similarity, citation_overlap, structural_similarity) VALUES (?,?,?,?,?,?)",
            (s["manuscript_id"], s["article_id"], s["source"],
             s["text_similarity"], s["citation_overlap"], s["structural_similarity"]),
        )
    for r in retraction_entries:
        cur.execute(
            "INSERT INTO retraction_watchlist VALUES (?,?,?,?,?,?)",
            (r["entry_id"], r["author_name"], r["original_paper_title"],
             r["retraction_date"], r["reason"], r["severity"]),
        )

    conn.commit()

    # ----------------------------------------------------------------
    # Generate workspace: config files (fixed, do not scale)
    # ----------------------------------------------------------------

    # scoring_config.yaml
    scoring_yaml = """\
weights:
  text_similarity: 0.45
  citation_overlap: 0.30
  structural_similarity: 0.25

flagging_threshold: 0.65

retraction_penalties:
  high: 0.20
  medium: 0.12
  low: 0.05

max_articles_considered: 3

declared_source_discount: 0.5
"""
    with open(os.path.join(workspace, "scoring_config.yaml"), "w") as f:
        f.write(scoring_yaml)

    # discipline_adjustments.json
    disc_adj = {
        "Biology": 1.05,
        "Computer Science": 0.90,
        "Chemistry": 1.10,
        "Physics": 0.95,
        "Medicine": 1.15,
        "Psychology": 1.00,
        "Economics": 0.92,
    }
    with open(os.path.join(workspace, "discipline_adjustments.json"), "w") as f:
        json.dump(disc_adj, f, indent=2)

    # editorial_policy.md
    policy_md = """\
# Editorial Originality Review Policy

## Risk Score Computation

For each pending manuscript, compute an individual article match score for every
similar article found in both open-access repositories and preprint servers.
The match score uses the weighted formula: multiply each similarity component
(text similarity, citation overlap, and structural similarity) by its
corresponding weight from the scoring configuration, then sum the products.

If a matched article appears in the manuscript submission's declared sources
list, apply the declared source discount factor to that article's match score
(multiply the computed match score by the discount factor).

From all match scores for a given manuscript, select the top N highest-scoring
articles (where N equals the max_articles_considered value in the scoring
configuration). Compute the arithmetic mean of these top scores to obtain the
composite base score. If there are fewer matches than N, average all available
scores. If there are zero matches, the composite base score is 0.

Adjust the composite base score by multiplying with the discipline-specific
adjustment factor from the discipline adjustments configuration.

For retraction watchlist checks: if any of the manuscript's authors appear on
the retraction watchlist, add the corresponding severity penalty for each
matched author. When an author has multiple watchlist entries, use only the
entry with the highest severity penalty for that author (do not double-count
the same author). Severity ranking from highest to lowest: high, medium, low.

The final risk score equals the discipline-adjusted composite plus all
retraction penalties, capped at 1.0.

## Flagging Criteria

A manuscript is flagged for editorial review when its final risk score is
greater than or equal to the flagging threshold specified in the scoring
configuration.

## Severity Categories

Flagged manuscripts receive a severity category based on their final risk score:

- Critical: final risk score >= 0.85
- High: final risk score >= 0.75 and < 0.85
- Moderate: final risk score >= threshold and < 0.75

## Report Ordering

All manuscripts in the originality report must be listed in ascending order of
manuscript ID.

Flagged cases in the detailed JSON report must be sorted by final risk score in
descending order. When two flagged manuscripts share the same final risk score
after rounding to two decimal places, sort by submission date ascending (earlier
first). If submission dates also match, sort by manuscript ID ascending.
"""
    with open(os.path.join(workspace, "editorial_policy.md"), "w") as f:
        f.write(policy_md)

    # review_categories.csv  (fixed reference file)
    with open(os.path.join(workspace, "review_categories.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["severity_category", "min_score", "max_score", "review_urgency", "escalation_required"])
        writer.writerow(["Critical", "0.85", "1.00", "immediate", "yes"])
        writer.writerow(["High", "0.75", "0.85", "within_48h", "yes"])
        writer.writerow(["Moderate", "0.65", "0.75", "within_1week", "no"])

    # ----------------------------------------------------------------
    # Generate workspace: submission text files (scale with num_workspace_files)
    # ----------------------------------------------------------------
    for i in range(num_pending):
        m = manuscripts[i]
        mid = m["manuscript_id"]

        # Pick declared sources from this manuscript's similarity matches
        ms_matches = [s for s in similarity_results if s["manuscript_id"] == mid]
        n_declared = rng.randint(0, min(2, len(ms_matches)))
        if n_declared > 0:
            declared_indices = rng.sample(range(len(ms_matches)), n_declared)
            declared_sources = [ms_matches[di]["article_id"] for di in declared_indices]
        else:
            declared_sources = []

        full_text = generate_full_text(fake, m["title"], m["abstract"], rng)
        declared_str = ", ".join(declared_sources) if declared_sources else "NONE"

        keywords = fake.words(nb=rng.randint(3, 7))

        content = (
            f"MANUSCRIPT_ID: {mid}\n"
            f"TITLE: {m['title']}\n"
            f"AUTHORS: {m['authors']}\n"
            f"DISCIPLINE: {m['discipline']}\n"
            f"SUBMISSION_DATE: {m['submission_date']}\n"
            f"DECLARED_SOURCES: {declared_str}\n"
            f"KEYWORDS: {', '.join(keywords)}\n"
            f"\n---\n\n"
            f"{full_text}\n"
        )

        with open(os.path.join(workspace, f"submission_{mid}.txt"), "w") as f:
            f.write(content)

    conn.close()
    print(f"Database created at {db_path}")
    print(f"Workspace populated at {workspace}/ with {num_pending} submission files + 4 config files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", type=str, required=True)
    parser.add_argument("--workspace", type=str, required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
