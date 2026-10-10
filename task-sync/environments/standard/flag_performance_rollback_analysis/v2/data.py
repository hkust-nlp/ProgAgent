import argparse
import json
import math
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 320,
    "num_workspace_files": 30,
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SERVICES = [
    "auth-service",
    "payment-gateway",
    "search-engine",
    "notification-hub",
    "checkout-flow",
    "user-profile",
    "analytics-platform",
    "recommendation-engine",
]

SERVICE_CRITICALITY = {
    "auth-service": "critical",
    "payment-gateway": "critical",
    "search-engine": "high",
    "notification-hub": "medium",
    "checkout-flow": "critical",
    "user-profile": "high",
    "analytics-platform": "low",
    "recommendation-engine": "medium",
}

SERVICE_TEAMS = {
    "auth-service": "platform",
    "payment-gateway": "fintech",
    "search-engine": "discovery",
    "notification-hub": "engagement",
    "checkout-flow": "commerce",
    "user-profile": "platform",
    "analytics-platform": "data-engineering",
    "recommendation-engine": "ml-team",
}

SERVICE_DEPENDENCIES = {
    "auth-service": ["user-profile"],
    "payment-gateway": ["auth-service"],
    "search-engine": [],
    "notification-hub": ["auth-service"],
    "checkout-flow": ["payment-gateway", "auth-service"],
    "user-profile": [],
    "analytics-platform": [],
    "recommendation-engine": ["analytics-platform"],
}

SEVERITY_LEVELS = ["critical", "high", "medium", "low"]
ERROR_TYPES = [
    "NullPointerException", "TimeoutError", "ConnectionRefused",
    "AuthenticationFailed", "RateLimitExceeded", "DataCorruption",
    "MemoryOverflow", "ConfigurationError", "ValidationError",
    "ServiceUnavailable", "DeadlockDetected", "CacheInvalidation",
]
TICKET_PRIORITIES = ["P1", "P2", "P3", "P4"]
TICKET_CATEGORIES = ["bug", "performance", "usability", "feature_request", "crash"]
TICKET_STATUSES = ["open", "in_progress", "resolved", "closed"]

REFERENCE_DATE = datetime(2026, 4, 15)
ANALYSIS_WINDOW_DAYS = 14
CHANGE_LOOKBACK_DAYS = 30
CHANGE_WINDOW_START = REFERENCE_DATE - timedelta(days=CHANGE_LOOKBACK_DAYS)
CHANGE_WINDOW_END = REFERENCE_DATE - timedelta(days=ANALYSIS_WINDOW_DAYS)
DATA_START = REFERENCE_DATE - timedelta(days=60)
FILL_CUTOFF = CHANGE_WINDOW_START - timedelta(days=ANALYSIS_WINDOW_DAYS)

ROLLBACK_THRESHOLDS = {
    "error_increase_pct": 50.0,
    "satisfaction_drop": 0.3,
    "ticket_spike_multiplier": 2.0,
}
MONITOR_THRESHOLDS = {
    "error_increase_pct": 25.0,
    "satisfaction_drop": 0.15,
    "ticket_spike_multiplier": 1.5,
}
COMPLEXITY_CHOICES = ["easy", "medium", "hard"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _rand_ts(start, end, rng):
    """Return a random datetime between start and end."""
    delta = (end - start).total_seconds()
    if delta <= 0:
        return start
    return start + timedelta(seconds=rng.randint(1, max(1, int(delta))))


def _clamp_ts(ts):
    return max(DATA_START, min(ts, REFERENCE_DATE))


# ---------------------------------------------------------------------------
# Data-generation functions
# ---------------------------------------------------------------------------
def generate_flags(n, fake, rng):
    flags = []
    for i in range(1, n + 1):
        service = SERVICES[(i - 1) % len(SERVICES)]
        flags.append({
            "flag_id": i,
            "flag_name": f"flag_{fake.word()}_{fake.word()}_{i}",
            "service": service,
            "description": fake.sentence(nb_words=10),
            "rollout_percentage": rng.choice([10, 25, 50, 75, 100]),
            "is_enabled": int(rng.random() < 0.75),
            "created_date": fake.date_between(
                start_date="-365d", end_date="-60d"
            ).isoformat(),
        })
    return flags


def select_changed_and_problematic(n, rng):
    n_changed = max(10, int(n * 0.30))
    changed = sorted(rng.sample(range(1, n + 1), n_changed))
    n_prob = max(4, int(n_changed * 0.35))
    prob = set(sorted(rng.sample(changed, n_prob)))
    return changed, prob


def assign_change_dates(changed_ids, rng):
    latest = {}
    for fid in changed_ids:
        days_off = rng.uniform(0, (CHANGE_WINDOW_END - CHANGE_WINDOW_START).total_seconds())
        latest[fid] = CHANGE_WINDOW_START + timedelta(seconds=days_off)
    return latest


def generate_changes(flags, changed_ids, latest_changes, target_rows, fake, rng):
    rows = []
    cid = 1
    for fid in changed_ids:
        cd = latest_changes[fid]
        # 1-2 older changes
        n_old = rng.randint(0, 2)
        for _ in range(n_old):
            ts = _rand_ts(DATA_START - timedelta(days=60), CHANGE_WINDOW_START, rng)
            field = rng.choice(["rollout_percentage", "is_enabled"])
            rows.append({
                "change_id": cid, "flag_id": fid,
                "change_date": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "field_changed": field,
                "old_value": str(rng.choice([0, 10, 25])),
                "new_value": str(rng.choice([50, 75, 100])),
                "changed_by": fake.name(),
                "reason": fake.sentence(nb_words=8),
            })
            cid += 1
        # latest change (the one in the analysis window)
        field = rng.choice(["rollout_percentage", "is_enabled", "rollout_percentage"])
        if field == "rollout_percentage":
            old_v, new_v = str(rng.choice([0, 10, 25, 50])), str(rng.choice([50, 75, 100]))
        else:
            old_v, new_v = "false", "true"
        rows.append({
            "change_id": cid, "flag_id": fid,
            "change_date": cd.strftime("%Y-%m-%d %H:%M:%S"),
            "field_changed": field,
            "old_value": old_v, "new_value": new_v,
            "changed_by": fake.name(),
            "reason": fake.sentence(nb_words=8),
        })
        cid += 1

    # fill with old changes for non-changed flags
    non_changed = [f["flag_id"] for f in flags if f["flag_id"] not in set(changed_ids)]
    while len(rows) < target_rows and non_changed:
        fid = rng.choice(non_changed)
        ts = _rand_ts(DATA_START - timedelta(days=90), FILL_CUTOFF, rng)
        rows.append({
            "change_id": cid, "flag_id": fid,
            "change_date": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "field_changed": rng.choice(["rollout_percentage", "is_enabled"]),
            "old_value": str(rng.choice([0, 10, 25])),
            "new_value": str(rng.choice([50, 75])),
            "changed_by": fake.name(),
            "reason": fake.sentence(nb_words=8),
        })
        cid += 1
    return rows


def generate_errors(flags, changed_ids, problematic_ids, latest_changes,
                    target_rows, fake, rng):
    rows = []
    eid = 1
    aw = ANALYSIS_WINDOW_DAYS

    for fid in changed_ids:
        is_prob = fid in problematic_ids
        cd = latest_changes[fid]
        service = flags[fid - 1]["service"]

        n_b = rng.randint(4, 7) if is_prob else rng.randint(2, 4)
        if is_prob:
            n_a = max(n_b + 3, int(n_b * rng.uniform(2.5, 4.0)))
        else:
            n_a = max(1, int(n_b * rng.uniform(0.7, 1.2)))

        sev_w_prob = [30, 35, 25, 10]
        sev_w_norm = [5, 15, 40, 40]

        for _ in range(n_b):
            ts = cd - timedelta(seconds=rng.randint(3600, aw * 86400))
            ts = _clamp_ts(ts)
            rows.append({
                "error_id": eid, "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "service": service,
                "error_type": rng.choice(ERROR_TYPES),
                "severity": rng.choices(SEVERITY_LEVELS,
                                        weights=sev_w_prob if is_prob else sev_w_norm)[0],
                "message": fake.sentence(nb_words=12),
                "associated_flag_id": fid,
            })
            eid += 1
        for _ in range(n_a):
            ts = cd + timedelta(seconds=rng.randint(3600, aw * 86400))
            ts = _clamp_ts(ts)
            rows.append({
                "error_id": eid, "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "service": service,
                "error_type": rng.choice(ERROR_TYPES),
                "severity": rng.choices(SEVERITY_LEVELS,
                                        weights=sev_w_prob if is_prob else sev_w_norm)[0],
                "message": fake.sentence(nb_words=12),
                "associated_flag_id": fid,
            })
            eid += 1

    # fill remaining
    while len(rows) < target_rows:
        fid_r = rng.choice(range(1, len(flags) + 1)) if rng.random() < 0.5 else None
        ts = _rand_ts(DATA_START, FILL_CUTOFF, rng)
        rows.append({
            "error_id": eid, "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "service": flags[(fid_r or rng.randint(1, len(flags))) - 1]["service"],
            "error_type": rng.choice(ERROR_TYPES),
            "severity": rng.choices(SEVERITY_LEVELS, weights=[5, 15, 40, 40])[0],
            "message": fake.sentence(nb_words=12),
            "associated_flag_id": fid_r,
        })
        eid += 1
    return rows


def generate_sessions(flags, changed_ids, problematic_ids, latest_changes,
                      target_rows, fake, rng, np_rng):
    rows = []
    sid = 1
    aw = ANALYSIS_WINDOW_DAYS
    n_flags = len(flags)

    for fid in changed_ids:
        is_prob = fid in problematic_ids
        cd = latest_changes[fid]

        n_b = rng.randint(5, 8) if is_prob else rng.randint(3, 5)
        n_a = rng.randint(6, 10) if is_prob else rng.randint(3, 5)

        for phase, count in [("before", n_b), ("after", n_a)]:
            for _ in range(count):
                if phase == "before":
                    ts = cd - timedelta(seconds=rng.randint(3600, aw * 86400))
                else:
                    ts = cd + timedelta(seconds=rng.randint(3600, aw * 86400))
                ts = _clamp_ts(ts)

                # exposed flags: include target fid + 0-2 others
                extras = rng.sample(
                    [f for f in range(1, n_flags + 1) if f != fid],
                    k=rng.randint(0, min(2, n_flags - 1)),
                )
                exposed = sorted(set([fid] + extras))

                if is_prob and phase == "after":
                    sat = round(max(1.0, min(5.0, np_rng.normal(2.8, 0.5))), 1)
                    rt = max(500, int(np_rng.normal(3500, 600)))
                    errs = rng.choices([0, 1, 2, 3, 4, 5],
                                       weights=[10, 20, 25, 25, 15, 5])[0]
                    conv = int(rng.random() < 0.25)
                elif is_prob and phase == "before":
                    sat = round(max(1.0, min(5.0, np_rng.normal(4.0, 0.3))), 1)
                    rt = max(300, int(np_rng.normal(1800, 300)))
                    errs = rng.choices([0, 1, 2], weights=[55, 30, 15])[0]
                    conv = int(rng.random() < 0.65)
                else:
                    sat = round(max(1.0, min(5.0, np_rng.normal(3.9, 0.3))), 1)
                    rt = max(300, int(np_rng.normal(2000, 350)))
                    errs = rng.choices([0, 1, 2], weights=[60, 30, 10])[0]
                    conv = int(rng.random() < 0.60)

                rows.append({
                    "session_id": sid,
                    "user_id": f"user_{rng.randint(1, max(50, target_rows // 5))}",
                    "start_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "duration_ms": rng.randint(10000, 600000),
                    "pages_viewed": rng.randint(1, 20),
                    "errors_encountered": errs,
                    "satisfaction_score": sat,
                    "exposed_flags": ",".join(str(f) for f in exposed),
                    "response_time_ms": rt,
                    "conversion_completed": conv,
                })
                sid += 1

    # fill
    while len(rows) < target_rows:
        ts = _rand_ts(DATA_START, FILL_CUTOFF, rng)
        n_exp = rng.randint(1, 3)
        exposed = sorted(rng.sample(range(1, n_flags + 1), min(n_exp, n_flags)))
        rows.append({
            "session_id": sid,
            "user_id": f"user_{rng.randint(1, max(50, target_rows // 5))}",
            "start_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_ms": rng.randint(10000, 600000),
            "pages_viewed": rng.randint(1, 20),
            "errors_encountered": rng.choices([0, 1, 2], weights=[60, 30, 10])[0],
            "satisfaction_score": round(max(1.0, min(5.0, np_rng.normal(3.8, 0.5))), 1),
            "exposed_flags": ",".join(str(f) for f in exposed),
            "response_time_ms": max(300, int(np_rng.normal(2000, 400))),
            "conversion_completed": int(rng.random() < 0.55),
        })
        sid += 1
    return rows


def generate_tickets(flags, changed_ids, problematic_ids, latest_changes,
                     target_rows, fake, rng):
    rows = []
    tid = 1
    aw = ANALYSIS_WINDOW_DAYS

    for fid in changed_ids:
        is_prob = fid in problematic_ids
        cd = latest_changes[fid]

        n_b = rng.randint(2, 4) if is_prob else rng.randint(1, 2)
        if is_prob:
            n_a = max(n_b + 2, int(n_b * rng.uniform(2.5, 5.0)))
        else:
            n_a = max(0, int(n_b * rng.uniform(0.5, 1.3)))

        pri_w_prob = [30, 35, 25, 10]
        pri_w_norm = [5, 20, 40, 35]

        for phase, count in [("before", n_b), ("after", n_a)]:
            for _ in range(count):
                if phase == "before":
                    ts = cd - timedelta(seconds=rng.randint(3600, aw * 86400))
                else:
                    ts = cd + timedelta(seconds=rng.randint(3600, aw * 86400))
                ts = _clamp_ts(ts)
                rows.append({
                    "ticket_id": tid,
                    "user_id": f"user_{rng.randint(1, max(30, target_rows // 3))}",
                    "created_date": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "subject": fake.sentence(nb_words=8),
                    "category": rng.choice(TICKET_CATEGORIES),
                    "priority": rng.choices(TICKET_PRIORITIES,
                                            weights=pri_w_prob if is_prob else pri_w_norm)[0],
                    "related_flag_id": fid,
                    "status": rng.choice(TICKET_STATUSES),
                    "resolution_time_hours": round(rng.uniform(0.5, 72), 1)
                    if rng.random() < 0.7 else None,
                })
                tid += 1

    # fill
    non_changed = [f["flag_id"] for f in flags if f["flag_id"] not in set(changed_ids)]
    while len(rows) < target_rows:
        fid_r = rng.choice(non_changed) if non_changed and rng.random() < 0.4 else None
        ts = _rand_ts(DATA_START, FILL_CUTOFF, rng)
        rows.append({
            "ticket_id": tid,
            "user_id": f"user_{rng.randint(1, max(30, target_rows // 3))}",
            "created_date": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "subject": fake.sentence(nb_words=8),
            "category": rng.choice(TICKET_CATEGORIES),
            "priority": rng.choices(TICKET_PRIORITIES, weights=[5, 20, 40, 35])[0],
            "related_flag_id": fid_r,
            "status": rng.choice(TICKET_STATUSES),
            "resolution_time_hours": round(rng.uniform(0.5, 72), 1)
            if rng.random() < 0.7 else None,
        })
        tid += 1
    return rows


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def create_and_insert(db_path, flags, changes, errors, sessions, tickets):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS feature_flags (
        flag_id INTEGER PRIMARY KEY,
        flag_name TEXT NOT NULL,
        service TEXT NOT NULL,
        description TEXT,
        rollout_percentage INTEGER,
        is_enabled INTEGER,
        created_date TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS flag_changes (
        change_id INTEGER PRIMARY KEY,
        flag_id INTEGER NOT NULL,
        change_date TEXT NOT NULL,
        field_changed TEXT,
        old_value TEXT,
        new_value TEXT,
        changed_by TEXT,
        reason TEXT,
        FOREIGN KEY (flag_id) REFERENCES feature_flags(flag_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS error_logs (
        error_id INTEGER PRIMARY KEY,
        timestamp TEXT NOT NULL,
        service TEXT,
        error_type TEXT,
        severity TEXT,
        message TEXT,
        associated_flag_id INTEGER,
        FOREIGN KEY (associated_flag_id) REFERENCES feature_flags(flag_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS user_sessions (
        session_id INTEGER PRIMARY KEY,
        user_id TEXT,
        start_time TEXT NOT NULL,
        duration_ms INTEGER,
        pages_viewed INTEGER,
        errors_encountered INTEGER,
        satisfaction_score REAL,
        exposed_flags TEXT,
        response_time_ms INTEGER,
        conversion_completed INTEGER
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
        ticket_id INTEGER PRIMARY KEY,
        user_id TEXT,
        created_date TEXT NOT NULL,
        subject TEXT,
        category TEXT,
        priority TEXT,
        related_flag_id INTEGER,
        status TEXT,
        resolution_time_hours REAL,
        FOREIGN KEY (related_flag_id) REFERENCES feature_flags(flag_id)
    )""")

    for f in flags:
        c.execute(
            "INSERT INTO feature_flags VALUES (?,?,?,?,?,?,?)",
            (f["flag_id"], f["flag_name"], f["service"], f["description"],
             f["rollout_percentage"], f["is_enabled"], f["created_date"]),
        )
    for ch in changes:
        c.execute(
            "INSERT INTO flag_changes VALUES (?,?,?,?,?,?,?,?)",
            (ch["change_id"], ch["flag_id"], ch["change_date"],
             ch["field_changed"], ch["old_value"], ch["new_value"],
             ch["changed_by"], ch["reason"]),
        )
    for e in errors:
        c.execute(
            "INSERT INTO error_logs VALUES (?,?,?,?,?,?,?)",
            (e["error_id"], e["timestamp"], e["service"], e["error_type"],
             e["severity"], e["message"], e["associated_flag_id"]),
        )
    for s in sessions:
        c.execute(
            "INSERT INTO user_sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
            (s["session_id"], s["user_id"], s["start_time"], s["duration_ms"],
             s["pages_viewed"], s["errors_encountered"], s["satisfaction_score"],
             s["exposed_flags"], s["response_time_ms"], s["conversion_completed"]),
        )
    for t in tickets:
        c.execute(
            "INSERT INTO support_tickets VALUES (?,?,?,?,?,?,?,?,?)",
            (t["ticket_id"], t["user_id"], t["created_date"], t["subject"],
             t["category"], t["priority"], t["related_flag_id"],
             t["status"], t["resolution_time_hours"]),
        )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Workspace generation
# ---------------------------------------------------------------------------
def generate_workspace(workspace, flags, sessions, changed_ids, problematic_ids,
                       latest_changes, nfiles, fake, rng):
    os.makedirs(workspace, exist_ok=True)

    # ---- Fixed files (not counted in SCALE) ----
    # rollback_policy.yaml
    policy = {
        "analysis": {
            "window_days": ANALYSIS_WINDOW_DAYS,
            "recent_change_lookback_days": CHANGE_LOOKBACK_DAYS,
            "reference_date": REFERENCE_DATE.strftime("%Y-%m-%d"),
        },
        "thresholds": {
            "rollback": {
                "error_increase_pct": ROLLBACK_THRESHOLDS["error_increase_pct"],
                "satisfaction_drop": ROLLBACK_THRESHOLDS["satisfaction_drop"],
                "ticket_spike_multiplier": ROLLBACK_THRESHOLDS["ticket_spike_multiplier"],
            },
            "monitor": {
                "error_increase_pct": MONITOR_THRESHOLDS["error_increase_pct"],
                "satisfaction_drop": MONITOR_THRESHOLDS["satisfaction_drop"],
                "ticket_spike_multiplier": MONITOR_THRESHOLDS["ticket_spike_multiplier"],
            },
        },
    }
    with open(os.path.join(workspace, "rollback_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # service_config.json
    svc_cfg = {}
    for svc in SERVICES:
        svc_cfg[svc] = {
            "criticality": SERVICE_CRITICALITY[svc],
            "team": SERVICE_TEAMS[svc],
            "dependencies": SERVICE_DEPENDENCIES[svc],
        }
    with open(os.path.join(workspace, "service_config.json"), "w") as f:
        json.dump(svc_cfg, f, indent=2)

    # ---- Scalable files ----
    n_session_files = max(2, nfiles // 2)
    n_flag_detail_files = max(2, nfiles * 3 // 10)
    n_incident_files = nfiles - n_session_files - n_flag_detail_files
    n_incident_files = max(1, n_incident_files)
    # re-adjust if sum != nfiles
    n_session_files = nfiles - n_flag_detail_files - n_incident_files

    # --- Session logs ---
    os.makedirs(os.path.join(workspace, "session_logs"), exist_ok=True)
    sessions_per_file = max(1, len(sessions) // n_session_files)
    for i in range(n_session_files):
        start = i * sessions_per_file
        end = start + sessions_per_file if i < n_session_files - 1 else len(sessions)
        chunk = sessions[start:end]
        df = pd.DataFrame([{
            "session_id": s["session_id"],
            "exposed_flags": s["exposed_flags"],
            "response_time_ms": s["response_time_ms"],
            "conversion_completed": bool(s["conversion_completed"]),
            "timestamp": s["start_time"],
        } for s in chunk])
        fname = f"batch_{i + 1:03d}.csv"
        df.to_csv(os.path.join(workspace, "session_logs", fname), index=False)

    # --- Flag details ---
    os.makedirs(os.path.join(workspace, "flag_details"), exist_ok=True)
    flags_per_file = max(1, len(flags) // n_flag_detail_files)
    for i in range(n_flag_detail_files):
        start = i * flags_per_file
        end = start + flags_per_file if i < n_flag_detail_files - 1 else len(flags)
        chunk = flags[start:end]
        details = []
        for fl in chunk:
            details.append({
                "flag_id": fl["flag_id"],
                "owner_name": fake.name(),
                "owner_team": SERVICE_TEAMS.get(fl["service"], "unknown"),
                "rollback_complexity": rng.choice(COMPLEXITY_CHOICES),
                "launch_date": fl["created_date"],
                "expected_impact": fake.sentence(nb_words=8),
            })
        fname = f"group_{i + 1}.json"
        with open(os.path.join(workspace, "flag_details", fname), "w") as f:
            json.dump(details, f, indent=2)

    # --- Incident notes ---
    os.makedirs(os.path.join(workspace, "incident_notes"), exist_ok=True)
    # Select flags to mention in incidents
    prob_list = sorted(problematic_ids)
    n_mentioned = max(2, int(len(prob_list) * 0.6))
    mentioned_flags = set(rng.sample(prob_list, min(n_mentioned, len(prob_list))))
    # optionally add 1 non-problematic changed flag
    non_prob_changed = [fid for fid in changed_ids if fid not in problematic_ids]
    if non_prob_changed:
        mentioned_flags.add(rng.choice(non_prob_changed))

    mentioned_list = sorted(mentioned_flags)
    flags_per_incident = max(1, len(mentioned_list) // n_incident_files)

    for i in range(n_incident_files):
        start = i * flags_per_incident
        end = start + flags_per_incident if i < n_incident_files - 1 else len(mentioned_list)
        chunk_fids = mentioned_list[start:end]
        if not chunk_fids:
            chunk_fids = [rng.choice(mentioned_list)]

        lines = [f"Incident Report - {fake.date_between(start_date='-20d', end_date='-5d').isoformat()}\n"]
        for fid in chunk_fids:
            fname = flags[fid - 1]["flag_name"]
            svc = flags[fid - 1]["service"]
            lines.append(
                f"During routine monitoring of {svc}, anomalies were detected "
                f"correlating with the feature flag '{fname}' (ID: {fid}). "
                f"{fake.sentence(nb_words=15)} "
                f"User reports and automated alerts indicate degraded performance "
                f"and increased error rates since the flag was modified. "
                f"{fake.sentence(nb_words=12)}\n"
            )
        lines.append(
            f"Affected users: approximately {rng.randint(50, 500)}. "
            f"Duration: {rng.randint(1, 12)} hours. "
            f"Status: {rng.choice(['investigating', 'mitigated', 'monitoring'])}.\n"
        )
        with open(
            os.path.join(workspace, "incident_notes", f"incident_{i + 1:03d}.txt"), "w"
        ) as f:
            f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    rng = random.Random(42)
    np_rng = np.random.RandomState(42)
    fake = Faker()
    Faker.seed(42)

    nrows = SCALE["rows_per_table"]
    nfiles = SCALE["num_workspace_files"]

    # 1. Flags
    flags = generate_flags(nrows, fake, rng)

    # 2. Select changed / problematic
    changed_ids, problematic_ids = select_changed_and_problematic(nrows, rng)

    # 3. Assign latest change dates
    latest_changes = assign_change_dates(changed_ids, rng)

    # 4. Changes table
    changes = generate_changes(flags, changed_ids, latest_changes,
                               max(nrows, nrows * 2), fake, rng)

    # 5. Errors
    errors = generate_errors(flags, changed_ids, problematic_ids, latest_changes,
                             max(nrows, nrows * 3), fake, rng)

    # 6. Sessions
    sessions = generate_sessions(flags, changed_ids, problematic_ids, latest_changes,
                                 max(nrows, nrows * 3), fake, rng, np_rng)

    # 7. Tickets
    tickets = generate_tickets(flags, changed_ids, problematic_ids, latest_changes,
                               max(nrows, int(nrows * 1.5)), fake, rng)

    # 8. DB
    create_and_insert(db_path, flags, changes, errors, sessions, tickets)

    # 9. Workspace
    generate_workspace(workspace, flags, sessions, changed_ids, problematic_ids,
                       latest_changes, nfiles, fake, rng)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
