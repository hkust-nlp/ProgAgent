import argparse
import hashlib
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
from faker import Faker
import yaml

# ──────────────────────────────────────────────
# SCALE — only this block differs across v0‑v3
# ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 320,      # v2 = 4× base
    "num_workspace_files": 30,  # v2 = base + 2N
}

# ──────────────────────────────────────────────
# Seeds
# ──────────────────────────────────────────────
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────
TIERS = ["free", "basic", "premium", "enterprise"]
TIER_LEVEL = {"free": 0, "basic": 1, "premium": 2, "enterprise": 3}
CATEGORIES = [
    "Computer Science", "Mathematics", "Physics", "Business",
    "Art", "Music", "Engineering", "Biology", "Chemistry", "Economics",
    "Philosophy", "History", "Psychology", "Linguistics",
]
PIRATE_PLATFORMS = [
    "PirateEdu", "LeakTube", "CourseRip", "FreeLearn.to",
    "TorrentClass", "EduLeaks", "OpenPiracy", "ShadowCourse",
]
SCANNER_NAMES = [
    "ContentGuard Pro", "PiracyHawk", "FingerPrintAI",
    "MediaShield", "CopyScan360",
]

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _content_hash(lecture_id: int) -> str:
    """Deterministic 16-hex-char fingerprint for a lecture."""
    return hashlib.sha256(f"lec_fp_{lecture_id}".encode()).hexdigest()[:16]


def _noise_hash(idx: int) -> str:
    """Hash that does NOT match any lecture (for scan-report noise)."""
    return hashlib.sha256(f"noise_{idx}".encode()).hexdigest()[:16]


# ──────────────────────────────────────────────
# Table generators
# ──────────────────────────────────────────────

def generate_students(n: int) -> list[dict]:
    weights = [0.35, 0.30, 0.25, 0.10]
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "student_id": i,
            "name": fake.name(),
            "email": fake.email(),
            "subscription_tier": random.choices(TIERS, weights=weights, k=1)[0],
            "joined_date": fake.date_between(start_date="-3y", end_date="today").isoformat(),
            "is_active": random.choices([1, 0], weights=[0.85, 0.15], k=1)[0],
        })
    return rows


def generate_courses(n: int) -> list[dict]:
    adjectives = [
        "Advanced", "Introduction to", "Fundamentals of", "Applied",
        "Modern", "Classical", "Practical", "Theoretical", "Intermediate",
        "Survey of", "Topics in", "Principles of",
    ]
    subjects = [
        "Machine Learning", "Data Structures", "Linear Algebra", "Calculus",
        "Organic Chemistry", "Microeconomics", "Digital Art", "Music Theory",
        "Thermodynamics", "Genetics", "Statistics", "Algorithms",
        "Database Systems", "Computer Networks", "Operating Systems",
        "Quantum Mechanics", "Financial Accounting", "Marketing Strategy",
        "Signal Processing", "Robotics", "Web Development", "Cryptography",
        "Game Theory", "Compiler Design", "Embedded Systems",
        "Natural Language Processing", "Computer Vision", "Distributed Systems",
        "Cloud Computing", "Cybersecurity", "Bioinformatics", "Econometrics",
        "Operations Research", "Control Systems", "Information Theory",
        "Numerical Methods", "Graph Theory", "Topology", "Abstract Algebra",
        "Real Analysis", "Complex Analysis", "Differential Equations",
        "Probability Theory", "Discrete Mathematics", "Combinatorics",
        "Number Theory", "Set Theory", "Logic and Computation",
        "Category Theory", "Stochastic Processes", "Fluid Dynamics",
        "Astrophysics", "Geophysics", "Materials Science", "Photonics",
        "Biomedical Engineering", "Renewable Energy", "Data Mining",
        "Human-Computer Interaction", "Software Engineering", "Parallel Computing",
        "Deep Learning", "Reinforcement Learning", "Computer Graphics",
        "Digital Signal Processing", "VLSI Design", "Power Systems",
        "Structural Engineering", "Environmental Science", "Neuroscience",
        "Cognitive Science", "Behavioral Economics", "Public Policy",
        "International Relations", "Comparative Literature",
        "Ethics in Technology", "Philosophy of Mind",
    ]
    tier_weights = [0.25, 0.30, 0.30, 0.15]
    used = set()
    rows = []
    for i in range(1, n + 1):
        while True:
            title = f"{random.choice(adjectives)} {random.choice(subjects)}"
            if title not in used:
                used.add(title)
                break
        rows.append({
            "course_id": i,
            "title": title,
            "instructor": fake.name(),
            "category": random.choice(CATEGORIES),
            "min_tier": random.choices(TIERS, weights=tier_weights, k=1)[0],
        })
    return rows


def generate_lectures(n: int, courses: list[dict]) -> list[dict]:
    cids = [c["course_id"] for c in courses]
    course_map = {c["course_id"]: c for c in courses}
    rows = []
    for i in range(1, n + 1):
        cid = random.choice(cids)
        min_lvl = TIER_LEVEL[course_map[cid]["min_tier"]]
        possible = [t for t in TIERS if TIER_LEVEL[t] >= min_lvl]
        rows.append({
            "lecture_id": i,
            "course_id": cid,
            "title": f"Lecture {i}: {fake.bs().title()}",
            "content_hash": _content_hash(i),
            "duration_minutes": random.randint(15, 120),
            "access_tier": random.choice(possible),
        })
    return rows


def _pick_pirated(lectures: list[dict], fraction: float = 0.18) -> list[dict]:
    """Select a subset of lectures to be 'pirated'."""
    n = max(12, int(len(lectures) * fraction))
    n = min(n, len(lectures))
    chosen = random.sample(range(len(lectures)), n)
    return [lectures[i] for i in sorted(chosen)]


def _make_suspicious_ips(count: int = 20) -> list[str]:
    return [fake.ipv4() for _ in range(count)]


def generate_access_logs(
    n: int,
    students: list[dict],
    lectures: list[dict],
    pirated_ids: set[int],
    suspicious_ips: list[str],
) -> list[dict]:
    student_ids = [s["student_id"] for s in students]
    lecture_ids = [l["lecture_id"] for l in lectures]
    stu_map = {s["student_id"]: s for s in students}
    lec_map = {l["lecture_id"]: l for l in lectures}

    rows = []
    log_id = 1

    # ── deliberate tier-violation + suspicious-IP entries for pirated lectures ──
    pirated_list = [lid for lid in pirated_ids]
    deliberate_count = max(n // 5, len(pirated_list) * 2)
    for _ in range(deliberate_count):
        lid = random.choice(pirated_list)
        lec = lec_map[lid]
        lec_tier_lvl = TIER_LEVEL[lec["access_tier"]]
        # pick a student whose tier is too low
        candidates = [s for s in students if TIER_LEVEL[s["subscription_tier"]] < lec_tier_lvl]
        if not candidates:
            sid = random.choice(student_ids)
        else:
            sid = random.choice(candidates)["student_id"]
        ip = random.choice(suspicious_ips) if random.random() < 0.5 else fake.ipv4()
        rows.append({
            "log_id": log_id,
            "student_id": sid,
            "lecture_id": lid,
            "access_time": fake.date_time_between(start_date="-1y", end_date="now").isoformat(),
            "ip_address": ip,
            "watch_duration_seconds": random.randint(60, 7200),
        })
        log_id += 1

    # ── fill remaining with random entries ──
    remaining = n - len(rows)
    for _ in range(max(0, remaining)):
        lid = random.choice(lecture_ids)
        sid = random.choice(student_ids)
        ip = (
            random.choice(suspicious_ips)
            if lid in pirated_ids and random.random() < 0.15
            else fake.ipv4()
        )
        rows.append({
            "log_id": log_id,
            "student_id": sid,
            "lecture_id": lid,
            "access_time": fake.date_time_between(start_date="-1y", end_date="now").isoformat(),
            "ip_address": ip,
            "watch_duration_seconds": random.randint(30, 7200),
        })
        log_id += 1

    return rows


def generate_download_records(
    n: int,
    students: list[dict],
    lectures: list[dict],
    pirated_ids: set[int],
    suspicious_ips: list[str],
) -> list[dict]:
    student_ids = [s["student_id"] for s in students]
    lecture_ids = [l["lecture_id"] for l in lectures]
    pirated_list = list(pirated_ids)
    rows = []
    dl_id = 1

    # ── deliberate suspicious downloads for pirated lectures ──
    deliberate = max(n // 5, len(pirated_list) * 2)
    for _ in range(deliberate):
        lid = random.choice(pirated_list)
        sid = random.choice(student_ids)
        ip = random.choice(suspicious_ips) if random.random() < 0.45 else fake.ipv4()
        rows.append({
            "download_id": dl_id,
            "student_id": sid,
            "lecture_id": lid,
            "download_time": fake.date_time_between(start_date="-1y", end_date="now").isoformat(),
            "ip_address": ip,
        })
        dl_id += 1

    remaining = n - len(rows)
    for _ in range(max(0, remaining)):
        lid = random.choice(lecture_ids)
        sid = random.choice(student_ids)
        ip = (
            random.choice(suspicious_ips)
            if lid in pirated_ids and random.random() < 0.1
            else fake.ipv4()
        )
        rows.append({
            "download_id": dl_id,
            "student_id": sid,
            "lecture_id": lid,
            "download_time": fake.date_time_between(start_date="-1y", end_date="now").isoformat(),
            "ip_address": ip,
        })
        dl_id += 1

    return rows


# ──────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────

def create_tables(conn: sqlite3.Connection):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id   INTEGER PRIMARY KEY,
            name         TEXT NOT NULL,
            email        TEXT NOT NULL,
            subscription_tier TEXT NOT NULL,
            joined_date  TEXT NOT NULL,
            is_active    INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            course_id  INTEGER PRIMARY KEY,
            title      TEXT NOT NULL,
            instructor TEXT NOT NULL,
            category   TEXT NOT NULL,
            min_tier   TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS lectures (
            lecture_id      INTEGER PRIMARY KEY,
            course_id       INTEGER NOT NULL,
            title           TEXT NOT NULL,
            content_hash    TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            access_tier     TEXT NOT NULL,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS access_logs (
            log_id                INTEGER PRIMARY KEY,
            student_id            INTEGER NOT NULL,
            lecture_id            INTEGER NOT NULL,
            access_time           TEXT NOT NULL,
            ip_address            TEXT NOT NULL,
            watch_duration_seconds INTEGER NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            FOREIGN KEY (lecture_id) REFERENCES lectures(lecture_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS download_records (
            download_id  INTEGER PRIMARY KEY,
            student_id   INTEGER NOT NULL,
            lecture_id   INTEGER NOT NULL,
            download_time TEXT NOT NULL,
            ip_address   TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            FOREIGN KEY (lecture_id) REFERENCES lectures(lecture_id)
        )
    """)
    conn.commit()


def insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict]):
    if not rows:
        return
    cols = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_str = ", ".join(cols)
    conn.executemany(
        f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})",
        [tuple(r[c] for c in cols) for r in rows],
    )
    conn.commit()


# ──────────────────────────────────────────────
# Workspace generators
# ──────────────────────────────────────────────

def _distribute_items(items: list, num_buckets: int) -> list[list]:
    """Spread items roughly evenly across buckets, every item in at least 1 bucket."""
    buckets: list[list] = [[] for _ in range(num_buckets)]
    for idx, item in enumerate(items):
        buckets[idx % num_buckets].append(item)
    return buckets


def generate_scan_reports(
    workspace: str,
    pirated_lectures: list[dict],
    num_reports: int,
):
    """Create scan_report_NNN.json files."""
    entries: list[dict] = []
    for lec in pirated_lectures:
        n_urls = random.randint(1, 3)
        for _ in range(n_urls):
            platform = random.choice(PIRATE_PLATFORMS)
            entries.append({
                "external_url": f"https://{platform.lower().replace(' ', '').replace('.', '')}.com/{fake.lexify('????????')}",
                "content_fingerprint": lec["content_hash"],
                "match_confidence": round(random.uniform(0.90, 0.99), 2),
                "estimated_views": random.randint(100, 20000),
                "first_detected": fake.date_between(start_date="-6m", end_date="today").isoformat(),
            })
    # add noise (non-matching fingerprints)
    noise_count = max(3, len(entries) // 5)
    for i in range(noise_count):
        platform = random.choice(PIRATE_PLATFORMS)
        entries.append({
            "external_url": f"https://{platform.lower().replace(' ', '').replace('.', '')}.com/{fake.lexify('????????')}",
            "content_fingerprint": _noise_hash(i),
            "match_confidence": round(random.uniform(0.85, 0.95), 2),
            "estimated_views": random.randint(50, 5000),
            "first_detected": fake.date_between(start_date="-6m", end_date="today").isoformat(),
        })
    random.shuffle(entries)
    buckets = _distribute_items(entries, num_reports)

    for idx, findings in enumerate(buckets, start=1):
        report = {
            "scan_id": f"SCAN-2025-{idx:03d}",
            "scan_date": fake.date_between(start_date="-3m", end_date="today").isoformat(),
            "scanner": random.choice(SCANNER_NAMES),
            "platform_scanned": random.choice(PIRATE_PLATFORMS),
            "findings": findings,
        }
        path = os.path.join(workspace, f"scan_report_{idx:03d}.json")
        with open(path, "w") as f:
            json.dump(report, f, indent=2)


def generate_ip_watchlists(
    workspace: str,
    suspicious_ips: list[str],
    num_files: int,
):
    """Create ip_watchlist_NNN.csv files."""
    extra_ips = [fake.ipv4() for _ in range(len(suspicious_ips) // 2)]
    all_ips = suspicious_ips + extra_ips
    random.shuffle(all_ips)
    buckets = _distribute_items(all_ips, num_files)
    threat_levels = ["critical", "high", "medium"]
    sources = ["abuse_report", "honeypot", "isp_feed", "community_flag", "automated_scan"]

    for idx, ips in enumerate(buckets, start=1):
        rows_data = []
        for ip in ips:
            rows_data.append({
                "ip_address": ip,
                "threat_level": random.choice(threat_levels),
                "source": random.choice(sources),
                "date_flagged": fake.date_between(start_date="-1y", end_date="today").isoformat(),
                "notes": fake.sentence(nb_words=6),
            })
        df = pd.DataFrame(rows_data)
        path = os.path.join(workspace, f"ip_watchlist_{idx:03d}.csv")
        df.to_csv(path, index=False)


def generate_dmca_complaints(
    workspace: str,
    pirated_lectures: list[dict],
    num_files: int,
):
    """Create dmca_complaint_NNN.txt files with semi-structured notices."""
    notices: list[dict] = []
    subset = random.sample(
        pirated_lectures,
        k=min(len(pirated_lectures), max(6, len(pirated_lectures) // 2)),
    )
    for lec in subset:
        platform = random.choice(PIRATE_PLATFORMS)
        notices.append({
            "content_hash": lec["content_hash"],
            "lecture_title": lec["title"],
            "platform": platform,
            "url": f"https://{platform.lower().replace(' ', '').replace('.', '')}.com/{fake.lexify('????????')}",
            "complainant": fake.name(),
            "date_filed": fake.date_between(start_date="-4m", end_date="today").isoformat(),
        })
    random.shuffle(notices)
    buckets = _distribute_items(notices, num_files)

    for idx, batch in enumerate(buckets, start=1):
        lines = []
        for ni, n in enumerate(batch, start=1):
            lines.append(f"=== DMCA Notice DCM-{idx:03d}-{ni:03d} ===")
            lines.append(f"Date Filed: {n['date_filed']}")
            lines.append(f"Complainant: {n['complainant']}")
            lines.append(f"Content Hash: {n['content_hash']}")
            lines.append(f"Lecture Title: {n['lecture_title']}")
            lines.append(f"Infringing Platform: {n['platform']}")
            lines.append(f"Infringing URL: {n['url']}")
            lines.append("Status: pending_review")
            lines.append("")
        path = os.path.join(workspace, f"dmca_complaint_{idx:03d}.txt")
        with open(path, "w") as f:
            f.write("\n".join(lines))


def generate_config_files(workspace: str):
    """Create fixed policy / config files (not scaled)."""

    # ── piracy_policy.yaml ──
    policy = {
        "scoring": {
            "weights": {
                "external_source": 15,
                "unauthorized_access": 5,
                "watchlist_ip_hit": 20,
            },
            "tier_multipliers": {
                "free": 1.0,
                "basic": 1.5,
                "premium": 2.5,
                "enterprise": 3.5,
            },
            "priority_thresholds": {
                "critical": 200,
                "high": 100,
                "medium": 40,
            },
            "priority_actions": {
                "critical": "immediate_takedown",
                "high": "expedited_review",
                "medium": "standard_review",
            },
            "min_piracy_score": 40,
        },
    }
    with open(os.path.join(workspace, "piracy_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # ── tier_access_rules.json ──
    rules = {
        "free": ["free"],
        "basic": ["free", "basic"],
        "premium": ["free", "basic", "premium"],
        "enterprise": ["free", "basic", "premium", "enterprise"],
    }
    with open(os.path.join(workspace, "tier_access_rules.json"), "w") as f:
        json.dump(rules, f, indent=2)

    # ── severity_guide.md ──
    md = """# Content Piracy Severity Assessment Guide

When assessing pirated content, the raw score for a lecture is computed by
summing weighted signals and then applying a tier-based multiplier that
reflects the commercial value of the content.

## Signal Weights

Each unique external URL where the content appears contributes to the
external-source signal. Each access-log entry by a student whose
subscription tier does not permit the lecture's access tier counts as
an unauthorized access. Each access-log or download-record entry whose
IP address appears on any IP watchlist counts as a watchlist IP hit.

## Tier Multiplier

The multiplier is applied to the sum of weighted signals. Higher-tier
content is more commercially sensitive and therefore receives a larger
multiplier.

## Priority Classification

After computing the final piracy score, each lecture is classified into
a priority level based on configured thresholds. Lectures that fall
below the minimum score threshold are excluded from the takedown list.
"""
    with open(os.path.join(workspace, "severity_guide.md"), "w") as f:
        f.write(md)

    # ── detection_methodology.md ──
    methodology = """# Piracy Detection Methodology

This document is the authoritative specification for how pirated lectures
are identified and scored. Read it together with the scoring policy
(`piracy_policy.yaml`), the tier-access rules (`tier_access_rules.json`),
and the severity guide.

## Evidence Sources

Piracy evidence arrives in two kinds of workspace files. External scan
reports (JSON, `scan_report_*.json`) each contain an array of findings;
every finding records a content fingerprint and the external URL where the
material was discovered. DMCA complaint files (plain text,
`dmca_complaint_*.txt`) contain one or more structured notices; each notice
records a content hash and the infringing URL. Collect every fingerprint
and every associated URL from BOTH kinds of files. The external-URL set for
a fingerprint is the union of all URLs reported for it across every scan
report and every DMCA notice.

## Fingerprint Matching

Match each collected fingerprint against the lecture catalogue by content
hash. Some fingerprints in the scan reports are false positives that match
no lecture in the catalogue; discard them once the lookup finds no match.
A lecture is confirmed as pirated when at least one collected fingerprint
matches its content hash.

## IP Watchlist

The workspace contains CSV watchlist files (`ip_watchlist_*.csv`) listing
IP addresses flagged by the security team. Every IP address appearing in
any watchlist file is considered suspicious, regardless of the threat level
or source recorded alongside it.

## Signal Definitions

For each confirmed pirated lecture, compute exactly three raw signal counts:

1. Number of external sources — the count of unique external URLs
   referencing the lecture's fingerprint across all evidence sources.
2. Unauthorized access count — the total number of access-log events for
   the lecture in which the accessing student's subscription tier does not
   list the lecture's access tier among the tiers it is permitted to view,
   per the tier-access rules configuration. Every such event counts, even
   repeated events by the same student.
3. Watchlist IP hits — the number of UNIQUE watchlist IP addresses observed
   across the lecture's access-log events and download records combined.
   Each distinct IP address counts once, no matter how many events it
   appears in or whether it appears in both logs and downloads.

## Scoring Formula

Multiply each signal count by its respective weight from the scoring
policy, sum the three products, then multiply that sum by the tier
multiplier corresponding to the lecture's access tier. Round the result to
two decimal places. A lecture whose final piracy score falls below the
configured minimum piracy score is excluded from the takedown list
entirely.

## Priority Classification

A score at or above the critical threshold is classified as critical; a
score at or above the high threshold but below critical is high; a score at
or above the medium threshold but below high is medium. Each priority level
maps to the recommended enforcement action named in the scoring policy.
"""
    with open(os.path.join(workspace, "detection_methodology.md"), "w") as f:
        f.write(methodology)


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    R = SCALE["rows_per_table"]
    N = SCALE["num_workspace_files"]

    # ── Generate core data ──
    students = generate_students(R)
    courses = generate_courses(R)
    lectures = generate_lectures(R * 2, courses)

    pirated = _pick_pirated(lectures)
    pirated_ids = {l["lecture_id"] for l in pirated}
    suspicious_ips = _make_suspicious_ips(count=max(20, R // 4))

    access_logs = generate_access_logs(R * 5, students, lectures, pirated_ids, suspicious_ips)
    download_records = generate_download_records(R * 3, students, lectures, pirated_ids, suspicious_ips)

    # ── Populate database ──
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    insert_rows(conn, "students", students)
    insert_rows(conn, "courses", courses)
    insert_rows(conn, "lectures", lectures)
    insert_rows(conn, "access_logs", access_logs)
    insert_rows(conn, "download_records", download_records)
    conn.close()

    # ── Create workspace ──
    num_scans = N // 2
    num_ips = max(1, int(N * 0.3))
    num_dmca = N - num_scans - num_ips

    generate_scan_reports(args.workspace, pirated, num_scans)
    generate_ip_watchlists(args.workspace, suspicious_ips, num_ips)
    generate_dmca_complaints(args.workspace, pirated, num_dmca)
    generate_config_files(args.workspace)

    # ── Summary ──
    print(f"Database written to {args.db_path}")
    print(f"  students:         {len(students)}")
    print(f"  courses:          {len(courses)}")
    print(f"  lectures:         {len(lectures)}")
    print(f"  access_logs:      {len(access_logs)}")
    print(f"  download_records: {len(download_records)}")
    print(f"Workspace files in {args.workspace}:")
    for fn in sorted(os.listdir(args.workspace)):
        print(f"  {fn}")


if __name__ == "__main__":
    main()
