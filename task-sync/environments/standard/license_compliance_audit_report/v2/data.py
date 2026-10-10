#!/usr/bin/env python3
"""License compliance analysis task - data generation."""

import argparse
import sqlite3
import os
import json
import csv
import random
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 30,
}

# ── Seeds ──
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ── Fixed project definitions ──
PROJECTS = [
    {"id": 1, "name": "atlas-platform", "product_line": "Infrastructure", "criticality": "high", "release_date": "2026-06-15"},
    {"id": 2, "name": "mercury-api", "product_line": "Backend Services", "criticality": "critical", "release_date": "2026-05-01"},
    {"id": 3, "name": "nova-frontend", "product_line": "Web Applications", "criticality": "medium", "release_date": "2026-07-20"},
    {"id": 4, "name": "titan-analytics", "product_line": "Data Platform", "criticality": "high", "release_date": "2026-06-01"},
    {"id": 5, "name": "orbit-mobile", "product_line": "Mobile Apps", "criticality": "medium", "release_date": "2026-08-10"},
    {"id": 6, "name": "forge-devtools", "product_line": "Developer Tools", "criticality": "low", "release_date": "2026-09-01"},
    {"id": 7, "name": "shield-security", "product_line": "Security", "criticality": "critical", "release_date": "2026-05-15"},
    {"id": 8, "name": "pulse-monitoring", "product_line": "Operations", "criticality": "high", "release_date": "2026-06-30"},
]

DEPLOYMENT_ENVS = ["production", "staging", "development", "testing", "internal-tools"]
DEP_ENV_WEIGHTS = [0.35, 0.20, 0.20, 0.15, 0.10]

# ── Base license definitions ──
BASE_LICENSES = [
    # Permissive – approved
    {"spdx": "MIT", "name": "MIT License", "category": "permissive", "osi": 1, "risk": "low", "approval": "approved"},
    {"spdx": "Apache-2.0", "name": "Apache License 2.0", "category": "permissive", "osi": 1, "risk": "low", "approval": "approved"},
    {"spdx": "BSD-2-Clause", "name": "BSD 2-Clause Simplified", "category": "permissive", "osi": 1, "risk": "low", "approval": "approved"},
    {"spdx": "BSD-3-Clause", "name": "BSD 3-Clause New", "category": "permissive", "osi": 1, "risk": "low", "approval": "approved"},
    {"spdx": "ISC", "name": "ISC License", "category": "permissive", "osi": 1, "risk": "low", "approval": "approved"},
    {"spdx": "Zlib", "name": "zlib License", "category": "permissive", "osi": 1, "risk": "low", "approval": "approved"},
    {"spdx": "Unlicense", "name": "The Unlicense", "category": "permissive", "osi": 1, "risk": "low", "approval": "approved"},
    {"spdx": "CC0-1.0", "name": "CC0 1.0 Universal", "category": "permissive", "osi": 0, "risk": "low", "approval": "approved"},
    {"spdx": "0BSD", "name": "Zero-Clause BSD", "category": "permissive", "osi": 1, "risk": "low", "approval": "approved"},
    {"spdx": "PSF-2.0", "name": "Python Software Foundation License 2.0", "category": "permissive", "osi": 1, "risk": "low", "approval": "approved"},
    # Weak copyleft – restricted
    {"spdx": "LGPL-2.1-only", "name": "GNU LGPL v2.1 only", "category": "weak_copyleft", "osi": 1, "risk": "medium", "approval": "restricted"},
    {"spdx": "LGPL-3.0-only", "name": "GNU LGPL v3.0 only", "category": "weak_copyleft", "osi": 1, "risk": "medium", "approval": "restricted"},
    {"spdx": "MPL-2.0", "name": "Mozilla Public License 2.0", "category": "weak_copyleft", "osi": 1, "risk": "medium", "approval": "restricted"},
    {"spdx": "EPL-2.0", "name": "Eclipse Public License 2.0", "category": "weak_copyleft", "osi": 1, "risk": "medium", "approval": "restricted"},
    {"spdx": "CDDL-1.0", "name": "Common Development and Distribution License 1.0", "category": "weak_copyleft", "osi": 1, "risk": "medium", "approval": "restricted"},
    {"spdx": "CPL-1.0", "name": "Common Public License 1.0", "category": "weak_copyleft", "osi": 1, "risk": "medium", "approval": "restricted"},
    {"spdx": "EUPL-1.2", "name": "European Union Public License 1.2", "category": "weak_copyleft", "osi": 1, "risk": "medium", "approval": "restricted"},
    # Strong copyleft – denied
    {"spdx": "GPL-2.0-only", "name": "GNU GPL v2.0 only", "category": "strong_copyleft", "osi": 1, "risk": "high", "approval": "denied"},
    {"spdx": "GPL-3.0-only", "name": "GNU GPL v3.0 only", "category": "strong_copyleft", "osi": 1, "risk": "high", "approval": "denied"},
    {"spdx": "AGPL-3.0-only", "name": "GNU AGPL v3.0 only", "category": "strong_copyleft", "osi": 1, "risk": "critical", "approval": "denied"},
    {"spdx": "GPL-2.0-or-later", "name": "GNU GPL v2.0 or later", "category": "strong_copyleft", "osi": 1, "risk": "high", "approval": "denied"},
    {"spdx": "GPL-3.0-or-later", "name": "GNU GPL v3.0 or later", "category": "strong_copyleft", "osi": 1, "risk": "high", "approval": "denied"},
    # Non-standard – denied
    {"spdx": "SSPL-1.0", "name": "Server Side Public License v1", "category": "non_standard", "osi": 0, "risk": "critical", "approval": "denied"},
    {"spdx": "BSL-1.1", "name": "Business Source License 1.1", "category": "non_standard", "osi": 0, "risk": "high", "approval": "denied"},
    {"spdx": "Elastic-2.0", "name": "Elastic License 2.0", "category": "non_standard", "osi": 0, "risk": "high", "approval": "denied"},
]

# ── Name generation pools ──
LIB_PREFIXES = [
    "lib", "py", "go", "node", "net", "core", "open", "fast",
    "super", "mini", "micro", "ultra", "hyper", "meta", "neo", "pro",
]
LIB_WORDS = [
    "redis", "kafka", "rabbit", "elastic", "mongo", "postgres", "arrow",
    "parquet", "protobuf", "grpc", "graphql", "oauth", "jwt", "websocket",
    "stream", "queue", "buffer", "cipher", "digest", "compress", "parse",
    "render", "template", "route", "handler", "filter", "transform",
    "validate", "serialize", "marshal", "cache", "index", "shard",
    "proxy", "gateway", "bridge", "tunnel", "beacon", "pulse", "signal",
    "vector", "tensor", "matrix", "graph", "codec", "encoder", "decoder",
    "scanner", "watcher", "daemon", "runner", "worker", "scheduler",
]
LIB_SUFFIXES = [
    "utils", "helper", "core", "lib", "sdk", "api", "client", "server",
    "tools", "kit", "hub", "io", "db", "log", "auth", "crypto", "http",
    "json", "xml", "config", "fmt", "gen", "sync", "async", "pool",
]
ORG_NAMES = [
    "Acme", "CloudBase", "DataForge", "NetCore", "SecureStack",
    "OpenGrid", "FlexLab", "CodeVault", "ByteWorks", "LogicHub",
    "StreamLine", "PixelForge", "NodeSync", "EdgeServe", "CoreStack",
    "VortexIO", "NimbusLab", "QuarkSys", "PrismDev", "ZenithOps",
]
LICENSE_TYPE_WORDS = [
    "Open", "Community", "Developer", "Enterprise", "Academic",
    "Research", "Collaborative", "Shared", "Public", "Free",
]

# Category rotation for generated licenses
GEN_LICENSE_SPECS = [
    ("permissive", "low", "approved"),
    ("weak_copyleft", "medium", "restricted"),
    ("strong_copyleft", "high", "denied"),
    ("non_standard", "critical", "denied"),
    ("permissive", "low", "approved"),
    ("weak_copyleft", "medium", "restricted"),
    ("permissive", "low", "approved"),
    ("non_standard", "high", "denied"),
]


# ── Helpers ──

def _gen_version(rng):
    return f"{rng.randint(0, 15)}.{rng.randint(0, 30)}.{rng.randint(0, 20)}"


def _gen_date(rng, start="2024-01-01", end="2026-04-01"):
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    delta = (e - s).days
    if delta <= 0:
        return s.strftime("%Y-%m-%d")
    return (s + timedelta(days=rng.randint(0, delta))).strftime("%Y-%m-%d")


def generate_component_names(n, rng):
    names = set()
    patterns = [
        lambda: f"{rng.choice(LIB_PREFIXES)}-{rng.choice(LIB_WORDS)}",
        lambda: f"{rng.choice(LIB_WORDS)}-{rng.choice(LIB_SUFFIXES)}",
        lambda: f"{rng.choice(LIB_PREFIXES)}{rng.choice(LIB_SUFFIXES)}",
        lambda: f"{rng.choice(LIB_WORDS)}-{rng.choice(LIB_WORDS)}",
        lambda: f"{rng.choice(LIB_PREFIXES)}-{rng.choice(LIB_WORDS)}-{rng.choice(LIB_SUFFIXES)}",
    ]
    attempts = 0
    while len(names) < n and attempts < n * 20:
        name = rng.choice(patterns)()
        names.add(name)
        attempts += 1
    while len(names) < n:
        names.add(f"component-{len(names):04d}")
    return sorted(names)[:n]


# ── License registry generation ──

def generate_licenses(n):
    licenses = list(BASE_LICENSES)
    needed = max(0, n - len(licenses))
    for i in range(needed):
        spec = GEN_LICENSE_SPECS[i % len(GEN_LICENSE_SPECS)]
        org = ORG_NAMES[i % len(ORG_NAMES)]
        lt = LICENSE_TYPE_WORDS[i % len(LICENSE_TYPE_WORDS)]
        ver_major = (i // len(ORG_NAMES)) + 1
        ver_minor = i % 3
        spdx = f"LicenseRef-{org.lower()}-{lt.lower()}-v{ver_major}{ver_minor}"
        licenses.append({
            "spdx": spdx,
            "name": f"{org} {lt} License v{ver_major}.{ver_minor}",
            "category": spec[0],
            "osi": 1 if spec[0] == "permissive" else 0,
            "risk": spec[1],
            "approval": spec[2],
        })
    return licenses[:n]


# ── Component generation ──

def generate_components(n, licenses, rng):
    names = generate_component_names(n, rng)

    by_cat = {}
    for lic in licenses:
        by_cat.setdefault(lic["category"], []).append(lic)

    cat_weights = [
        ("permissive", 0.45),
        ("weak_copyleft", 0.18),
        ("strong_copyleft", 0.17),
        ("non_standard", 0.12),
    ]
    pool = []
    for cat, w in cat_weights:
        if cat in by_cat:
            count = max(1, int(n * w))
            for _ in range(count):
                pool.append(rng.choice(by_cat[cat]))
    while len(pool) < n:
        pool.append(rng.choice(licenses))
    rng.shuffle(pool)
    pool = pool[:n]

    components = []
    for i, name in enumerate(names):
        lic = pool[i]
        proj = PROJECTS[i % len(PROJECTS)]
        dep_env = rng.choices(DEPLOYMENT_ENVS, weights=DEP_ENV_WEIGHTS, k=1)[0]
        components.append({
            "id": i + 1,
            "name": name,
            "current_version": _gen_version(rng),
            "license_spdx": lic["spdx"],
            "project_id": proj["id"],
            "deployment_env": dep_env,
            "last_updated": _gen_date(rng, "2025-06-01", "2026-04-01"),
        })
    return components


# ── Version history generation ──

def generate_version_history(n, components, licenses, rng):
    records = []
    comp_ids = [c["id"] for c in components]
    shuffled_ids = list(comp_ids)
    rng.shuffle(shuffled_ids)
    license_changers = set(shuffled_ids[:max(1, len(shuffled_ids) // 5)])

    rec_id = 1
    while len(records) < n:
        comp = rng.choice(components)
        from_ver = _gen_version(rng)
        to_ver = _gen_version(rng)
        change_date = _gen_date(rng, "2024-06-01", "2026-03-15")

        if comp["id"] in license_changers and rec_id <= n // 3:
            old_lic = rng.choice(licenses)["spdx"]
            new_lic = comp["license_spdx"]
            change_type = "license_change"
        else:
            old_lic = comp["license_spdx"]
            new_lic = comp["license_spdx"]
            change_type = rng.choice(["patch", "minor_upgrade", "major_upgrade", "security_fix"])

        records.append({
            "id": rec_id,
            "component_id": comp["id"],
            "from_version": from_ver,
            "to_version": to_ver,
            "from_license": old_lic,
            "to_license": new_lic,
            "change_date": change_date,
            "change_type": change_type,
        })
        rec_id += 1
    return records[:n]


# ── Legal exception generation ──

def _gen_condition(rng, status):
    if status == "approved":
        return rng.choice([
            "Must not link at runtime",
            "Allowed in non-customer-facing services only",
            "Requires attribution in NOTICES file",
            "Limited to internal tooling",
            "Approved for current version only; re-review on upgrade",
            "Must isolate in separate container",
        ])
    elif status == "expired":
        return "Exception expired; re-apply required"
    elif status == "pending":
        return "Under legal review"
    else:
        return rng.choice([
            "Risk too high for production use",
            "No isolation strategy provided",
            "Copyleft obligations incompatible with product license",
        ])


def generate_legal_exceptions(n, components, licenses, rng):
    lic_map = {l["spdx"]: l for l in licenses}
    non_approved = [c for c in components
                    if lic_map.get(c["license_spdx"], {}).get("approval") in ("denied", "restricted")]

    statuses = ["approved", "expired", "pending", "denied"]
    status_weights = [0.35, 0.25, 0.20, 0.20]
    exception_types = ["runtime_isolation", "build_only", "internal_use", "evaluation",
                       "legacy_grandfathered", "dual_license"]
    lawyers = [fake.name() for _ in range(8)]

    records = []
    rec_id = 1

    for comp in non_approved:
        if rec_id > n:
            break
        status = rng.choices(statuses, weights=status_weights, k=1)[0]
        grant_date = _gen_date(rng, "2024-01-01", "2026-01-01")
        grant_dt = datetime.strptime(grant_date, "%Y-%m-%d")

        if status == "approved":
            expiry_date = (grant_dt + timedelta(days=rng.randint(365, 730))).strftime("%Y-%m-%d")
        elif status == "expired":
            expiry_date = _gen_date(rng, "2025-01-01", "2026-03-31")
        elif status == "pending":
            expiry_date = ""
        else:
            expiry_date = ""

        records.append({
            "id": rec_id,
            "component_id": comp["id"],
            "ticket_id": f"LEGAL-{rec_id:04d}",
            "exception_type": rng.choice(exception_types),
            "status": status,
            "granted_by": rng.choice(lawyers) if status in ("approved", "expired") else "",
            "grant_date": grant_date if status in ("approved", "expired") else "",
            "expiry_date": expiry_date,
            "conditions": _gen_condition(rng, status),
            "justification": fake.sentence(nb_words=12),
        })
        rec_id += 1

    while len(records) < n:
        comp = rng.choice(non_approved) if non_approved else rng.choice(components)
        status = rng.choices(statuses, weights=status_weights, k=1)[0]
        grant_date = _gen_date(rng, "2024-01-01", "2026-01-01")
        grant_dt = datetime.strptime(grant_date, "%Y-%m-%d")

        if status == "approved":
            expiry_date = (grant_dt + timedelta(days=rng.randint(365, 730))).strftime("%Y-%m-%d")
        elif status == "expired":
            expiry_date = _gen_date(rng, "2025-01-01", "2026-03-31")
        else:
            expiry_date = ""

        records.append({
            "id": rec_id,
            "component_id": comp["id"],
            "ticket_id": f"LEGAL-{rec_id:04d}",
            "exception_type": rng.choice(exception_types),
            "status": status,
            "granted_by": rng.choice(lawyers) if status in ("approved", "expired") else "",
            "grant_date": grant_date if status in ("approved", "expired") else "",
            "expiry_date": expiry_date,
            "conditions": _gen_condition(rng, status),
            "justification": fake.sentence(nb_words=12),
        })
        rec_id += 1

    return records[:n]


# ── Database creation ──

def create_database(db_path, components, licenses, version_history, exceptions):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("DROP TABLE IF EXISTS legal_exceptions")
    c.execute("DROP TABLE IF EXISTS version_history")
    c.execute("DROP TABLE IF EXISTS components")
    c.execute("DROP TABLE IF EXISTS license_registry")
    c.execute("DROP TABLE IF EXISTS projects")

    c.execute("""CREATE TABLE projects (
        id INTEGER PRIMARY KEY, name TEXT, product_line TEXT,
        criticality TEXT, release_date TEXT
    )""")
    c.execute("""CREATE TABLE license_registry (
        id INTEGER PRIMARY KEY, spdx_id TEXT UNIQUE, full_name TEXT,
        category TEXT, osi_approved INTEGER, risk_level TEXT,
        approval_status TEXT, notes TEXT
    )""")
    c.execute("""CREATE TABLE components (
        id INTEGER PRIMARY KEY, name TEXT, current_version TEXT,
        license_spdx TEXT, project_id INTEGER, deployment_env TEXT,
        last_updated TEXT,
        FOREIGN KEY (project_id) REFERENCES projects(id),
        FOREIGN KEY (license_spdx) REFERENCES license_registry(spdx_id)
    )""")
    c.execute("""CREATE TABLE version_history (
        id INTEGER PRIMARY KEY, component_id INTEGER,
        from_version TEXT, to_version TEXT, from_license TEXT,
        to_license TEXT, change_date TEXT, change_type TEXT,
        FOREIGN KEY (component_id) REFERENCES components(id)
    )""")
    c.execute("""CREATE TABLE legal_exceptions (
        id INTEGER PRIMARY KEY, component_id INTEGER, ticket_id TEXT,
        exception_type TEXT, status TEXT, granted_by TEXT,
        grant_date TEXT, expiry_date TEXT, conditions TEXT,
        justification TEXT,
        FOREIGN KEY (component_id) REFERENCES components(id)
    )""")

    for p in PROJECTS:
        c.execute("INSERT INTO projects VALUES (?,?,?,?,?)",
                  (p["id"], p["name"], p["product_line"], p["criticality"], p["release_date"]))

    for i, lic in enumerate(licenses):
        notes = fake.sentence(nb_words=6) if random.random() < 0.3 else ""
        c.execute("INSERT INTO license_registry VALUES (?,?,?,?,?,?,?,?)",
                  (i + 1, lic["spdx"], lic["name"], lic["category"],
                   lic["osi"], lic["risk"], lic["approval"], notes))

    for comp in components:
        c.execute("INSERT INTO components VALUES (?,?,?,?,?,?,?)",
                  (comp["id"], comp["name"], comp["current_version"],
                   comp["license_spdx"], comp["project_id"],
                   comp["deployment_env"], comp["last_updated"]))

    for vh in version_history:
        c.execute("INSERT INTO version_history VALUES (?,?,?,?,?,?,?,?)",
                  (vh["id"], vh["component_id"], vh["from_version"],
                   vh["to_version"], vh["from_license"], vh["to_license"],
                   vh["change_date"], vh["change_type"]))

    for ex in exceptions:
        c.execute("INSERT INTO legal_exceptions VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (ex["id"], ex["component_id"], ex["ticket_id"],
                   ex["exception_type"], ex["status"], ex["granted_by"],
                   ex["grant_date"], ex["expiry_date"], ex["conditions"],
                   ex["justification"]))

    conn.commit()
    conn.close()


# ── Workspace creation ──

def create_workspace(workspace, db_path, components, licenses, exceptions, version_history):
    os.makedirs(workspace, exist_ok=True)
    lic_map = {l["spdx"]: l for l in licenses}
    comp_map = {c["id"]: c for c in components}
    proj_map = {p["id"]: p for p in PROJECTS}

    # Fixed policy files (not scaled)
    _write_approved_licenses(workspace, licenses)
    _write_compliance_policy(workspace)

    # Scalable data files
    n_files = SCALE["num_workspace_files"]
    n_sca = max(1, round(n_files * 0.4))
    n_manifest = max(1, round(n_files * 0.3))
    n_exception_log = n_files - n_sca - n_manifest

    _write_sca_reports(workspace, components, lic_map, n_sca)
    _write_dependency_manifests(workspace, components, proj_map, n_manifest)
    _write_exception_logs(workspace, exceptions, comp_map, n_exception_log)


def _write_approved_licenses(workspace, licenses):
    data = {"approved": [], "restricted": [], "denied": []}
    for lic in licenses:
        entry = {
            "spdx_id": lic["spdx"],
            "name": lic["name"],
            "category": lic["category"],
            "osi_approved": bool(lic["osi"]),
        }
        if lic["approval"] == "approved":
            data["approved"].append(entry)
        elif lic["approval"] == "restricted":
            entry["conditions"] = "Requires legal review for production and customer-facing deployments"
            data["restricted"].append(entry)
        else:
            data["denied"].append(entry)

    path = os.path.join(workspace, "approved_licenses.yaml")
    with open(path, "w") as f:
        f.write("# Approved OSS License Registry\n")
        f.write("# Last updated: 2026-04-01\n\n")
        for section in ["approved", "restricted", "denied"]:
            f.write(f"{section}:\n")
            for entry in data[section]:
                f.write(f"  - spdx_id: \"{entry['spdx_id']}\"\n")
                f.write(f"    name: \"{entry['name']}\"\n")
                f.write(f"    category: \"{entry['category']}\"\n")
                f.write(f"    osi_approved: {str(entry['osi_approved']).lower()}\n")
                if "conditions" in entry:
                    f.write(f"    conditions: \"{entry['conditions']}\"\n")
            f.write("\n")


def _write_compliance_policy(workspace):
    policy = {
        "risk_scoring": {
            "base_risk_weight": {
                "low": 1,
                "medium": 3,
                "high": 7,
                "critical": 10,
            },
            "criticality_multiplier": {
                "low": 1,
                "medium": 2,
                "high": 3,
                "critical": 4,
            },
            "vulnerability_factor": {
                "formula": "min(1 + vulnerability_count * 0.1, 3.0)",
                "description": "Multiply base score by 1 + 0.1 per vulnerability, capped at 3.0"
            },
            "formula_description": "risk_score = base_risk_weight[license_risk_level] * criticality_multiplier[project_criticality] * vulnerability_factor"
        },
        "action_thresholds": {
            "replace": {
                "min_risk_score": 20.0,
                "description": "Components at or above this score with denied license and no valid exception must be replaced"
            },
            "obtain_exception": {
                "min_risk_score": 10.0,
                "description": "Components at or above this score with denied license should obtain an exception"
            },
            "legal_review": {
                "min_risk_score": 0.0,
                "description": "Restricted-category licenses in production or staging deployments need legal review regardless of score"
            }
        },
        "compliance_rules": {
            "approved_license": "No action needed",
            "restricted_in_production": "Restricted-category licenses deployed to production or staging require legal_review",
            "denied_no_exception": "Denied-category licenses without a valid (approved, non-expired) exception require action based on risk score",
            "expired_exception": "Previously approved exceptions that have expired require renew_exception action",
            "pending_exception": "Components with pending exception requests are flagged as pending_review",
            "denied_exception": "Components whose exception request was denied require replace action",
            "license_change_recent": "Components whose license changed within the last 180 days from reference date require re_evaluate action"
        },
        "reference_date": "2026-04-20",
        "license_change_lookback_days": 180
    }
    path = os.path.join(workspace, "compliance_policy.json")
    with open(path, "w") as f:
        json.dump(policy, f, indent=2)


def _write_sca_reports(workspace, components, lic_map, n_files):
    rng = random.Random(4242)
    scanners = ["Snyk", "BlackDuck", "WhiteSource", "Trivy", "FOSSA"]
    chunks = _partition(components, n_files)
    for i, chunk in enumerate(chunks):
        path = os.path.join(workspace, f"sca_scan_batch_{i+1:03d}.csv")
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "component_name", "detected_license", "vulnerability_count",
                "max_cvss_score", "scanner", "scan_date", "confidence_pct"
            ])
            for comp in chunk:
                vuln_count = rng.randint(0, 25)
                max_cvss = round(rng.uniform(0.0, 10.0), 1) if vuln_count > 0 else 0.0
                scanner = rng.choice(scanners)
                scan_date = _gen_date(rng, "2026-02-01", "2026-04-15")
                confidence = rng.randint(70, 100)
                writer.writerow([
                    comp["name"], comp["license_spdx"], vuln_count,
                    max_cvss, scanner, scan_date, confidence
                ])


def _write_dependency_manifests(workspace, components, proj_map, n_files):
    rng = random.Random(4243)
    dep_types = ["direct", "transitive"]
    dep_type_weights = [0.6, 0.4]
    scopes = ["runtime", "compile", "test", "provided"]
    scope_weights = [0.5, 0.25, 0.15, 0.10]

    chunks = _partition(components, n_files)
    for i, chunk in enumerate(chunks):
        deps = []
        for comp in chunk:
            proj = proj_map[comp["project_id"]]
            deps.append({
                "component_name": comp["name"],
                "version": comp["current_version"],
                "project": proj["name"],
                "dependency_type": rng.choices(dep_types, weights=dep_type_weights, k=1)[0],
                "scope": rng.choices(scopes, weights=scope_weights, k=1)[0],
            })
        manifest = {
            "manifest_id": f"MANIFEST-{i+1:03d}",
            "generated_date": _gen_date(rng, "2026-03-01", "2026-04-10"),
            "dependencies": deps,
        }
        path = os.path.join(workspace, f"dependency_manifest_{i+1:03d}.json")
        with open(path, "w") as f:
            json.dump(manifest, f, indent=2)


def _write_exception_logs(workspace, exceptions, comp_map, n_files):
    rng = random.Random(4244)
    alternatives = [
        "No alternative identified", "Consider MIT-licensed fork",
        "Evaluate Apache-2.0 equivalent", "Internal reimplementation recommended",
        "Vendor commercial license available", "Dual-license option exists",
        "Community fork under BSD-3-Clause", "Check for permissive wrapper library",
    ]
    priorities = ["P1", "P2", "P3", "P4"]
    priority_weights = [0.15, 0.30, 0.35, 0.20]

    chunks = _partition(exceptions, n_files)
    for i, chunk in enumerate(chunks):
        path = os.path.join(workspace, f"exception_review_log_{i+1:03d}.md")
        with open(path, "w") as f:
            f.write(f"# Exception Review Log - Batch {i+1}\n\n")
            for ex in chunk:
                comp = comp_map.get(ex["component_id"], {})
                comp_name = comp.get("name", f"component-{ex['component_id']}")
                priority = rng.choices(priorities, weights=priority_weights, k=1)[0]
                alt = rng.choice(alternatives)
                f.write(f"## {ex['ticket_id']}: {comp_name}\n\n")
                f.write(f"- **License**: {comp.get('license_spdx', 'Unknown')}\n")
                f.write(f"- **Status**: {ex['status']}\n")
                f.write(f"- **Priority**: {priority}\n")
                f.write(f"- **Type**: {ex['exception_type']}\n")
                f.write(f"- **Recommended Alternative**: {alt}\n")
                if ex["conditions"]:
                    f.write(f"- **Conditions**: {ex['conditions']}\n")
                f.write(f"- **Justification**: {ex['justification']}\n")
                f.write("\n---\n\n")


def _partition(items, n):
    k, m = divmod(len(items), n)
    return [items[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]


# ── Main ──

def main():
    parser = argparse.ArgumentParser(description="Generate license compliance data")
    parser.add_argument("--db_path", required=True, help="Path to output database")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    args = parser.parse_args()

    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    rng = random.Random(42)

    n = SCALE["rows_per_table"]
    licenses = generate_licenses(n)
    components = generate_components(n, licenses, rng)
    version_history = generate_version_history(n, components, licenses, rng)
    exceptions = generate_legal_exceptions(n, components, licenses, rng)

    create_database(args.db_path, components, licenses, version_history, exceptions)
    create_workspace(args.workspace, args.db_path, components, licenses, exceptions, version_history)

    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    print(f"  - {len(licenses)} licenses in registry")
    print(f"  - {len(components)} components")
    print(f"  - {len(version_history)} version history entries")
    print(f"  - {len(exceptions)} legal exception records")
    print(f"  - {SCALE['num_workspace_files']} scalable data files + 2 policy files")


if __name__ == "__main__":
    main()
