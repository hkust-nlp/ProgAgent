"""
Data generation for transitive dependency patch schedule task.
Generates a database of software components, vulnerabilities, releases, and deployments,
plus workspace files (SBOMs, vulnerability feeds, deployment manifests, release notes,
and policy/config files).
"""

import argparse
import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker


def _split_df(df, n):
    L = len(df)
    base, rem = divmod(L, n)
    out, start = [], 0
    for i in range(n):
        size = base + (1 if i < rem else 0)
        out.append(df.iloc[start:start + size])
        start += size
    return out


SCALE = {
    "rows_per_table": 800,
    "num_workspace_files": 40,
}

# ---------------------------------------------------------------------------
# Deterministic seeds
# ---------------------------------------------------------------------------
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ---------------------------------------------------------------------------
# Constants (do NOT vary with scale)
# ---------------------------------------------------------------------------
SERVICES = [
    "payment-gateway",
    "user-auth",
    "api-gateway",
    "web-frontend",
    "analytics-engine",
    "notification-service",
    "logging-pipeline",
    "internal-tools",
]

SERVICE_CRITICALITY = {
    "payment-gateway": "critical",
    "user-auth": "critical",
    "api-gateway": "high",
    "web-frontend": "high",
    "analytics-engine": "standard",
    "notification-service": "standard",
    "logging-pipeline": "low",
    "internal-tools": "low",
}

ECOSYSTEMS = ["npm", "pypi", "maven", "cargo", "go"]

SEVERITY_LEVELS = ["Critical", "High", "Medium", "Low"]
SEVERITY_CVSS_RANGES = {
    "Critical": (9.0, 10.0),
    "High": (7.0, 8.9),
    "Medium": (4.0, 6.9),
    "Low": (0.1, 3.9),
}

TECH_WORDS = [
    "net", "data", "http", "json", "xml", "log", "auth", "crypto",
    "cache", "queue", "mail", "stream", "metric", "trace", "session",
    "token", "schema", "codec", "buffer", "pool", "retry", "circuit",
    "rate", "batch", "async", "sync", "hash", "compress", "encode",
    "parse", "route", "proxy", "gate", "link", "bind", "plug",
    "hook", "pipe", "wire", "mesh", "node", "edge", "graph", "tree",
    "heap", "stack", "ring", "slab", "cell", "bolt", "flux", "core",
    "base", "fuse", "glow", "hive", "iris", "jade", "keen", "loom",
    "meld", "nova", "onyx", "plex", "quil", "reef", "sage", "tide",
    "umbr", "vane", "weld", "xeno", "yoke", "zeta", "apex", "byte",
    "cron", "dock", "emit", "fork", "grip", "halo", "icon", "jolt",
    "knot", "lens", "mist", "neon", "orb", "prism", "quad", "rune",
    "sift", "tact", "unit", "volt", "warp", "xray", "yarn", "zinc",
]

TECH_SUFFIXES = [
    "utils", "core", "lib", "client", "parser", "handler",
    "manager", "adapter", "connector", "provider", "module",
    "engine", "runtime", "toolkit", "sdk", "bridge", "proxy",
    "wrapper", "helper", "factory", "service", "driver",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_version():
    major = np.random.randint(0, 8)
    minor = np.random.randint(0, 30)
    patch = np.random.randint(0, 20)
    return f"{major}.{minor}.{patch}"


def _bump_version(ver, kind="patch"):
    parts = ver.split(".")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    if kind == "patch":
        patch += np.random.randint(1, 5)
    elif kind == "minor":
        minor += 1
        patch = 0
    else:
        major += 1
        minor = 0
        patch = 0
    return f"{major}.{minor}.{patch}"


def _random_date(start_year=2024, end_year=2026):
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 4, 1)
    delta = (end - start).days
    return (start + timedelta(days=int(np.random.randint(0, delta)))).strftime("%Y-%m-%d")


def _generate_component_name(idx, ecosystem):
    w1 = TECH_WORDS[idx % len(TECH_WORDS)]
    w2 = TECH_SUFFIXES[idx % len(TECH_SUFFIXES)]
    # Add a distinguisher so names are unique
    tag = idx // max(len(TECH_WORDS), len(TECH_SUFFIXES))
    suffix = f"{tag}" if tag > 0 else ""
    if ecosystem == "npm":
        return f"@org/{w1}-{w2}{suffix}"
    elif ecosystem == "pypi":
        return f"{w1}_{w2}{suffix}"
    elif ecosystem == "maven":
        return f"com.{w1}.{w2}{suffix}"
    elif ecosystem == "cargo":
        return f"{w1}-{w2}{suffix}"
    else:  # go
        return f"github.com/lib/{w1}{w2}{suffix}"


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def generate_components(n_rows):
    """Generate components: ~30 % direct, ~70 % transitive."""
    n_direct = max(10, int(n_rows * 0.30))
    n_transitive = n_rows - n_direct

    components = []
    used_names = set()

    # Direct components
    for i in range(n_direct):
        eco = ECOSYSTEMS[i % len(ECOSYSTEMS)]
        name = _generate_component_name(i, eco)
        while name in used_names:
            name = _generate_component_name(i + len(TECH_WORDS), eco)
        used_names.add(name)
        components.append({
            "id": i + 1,
            "name": name,
            "version": _generate_version(),
            "ecosystem": eco,
            "is_direct": 1,
            "parent_id": None,
            "description": fake.sentence(nb_words=8),
        })

    # Transitive components
    direct_ids = [c["id"] for c in components]
    for j in range(n_transitive):
        idx = n_direct + j
        eco = ECOSYSTEMS[idx % len(ECOSYSTEMS)]
        name = _generate_component_name(idx + 100, eco)
        while name in used_names:
            name = _generate_component_name(idx + 200 + j, eco)
        used_names.add(name)
        # 85% parent is a direct dep, 15% parent is another transitive dep
        if j > 5 and np.random.random() < 0.15:
            parent_id = components[n_direct + np.random.randint(0, j)]["id"]
        else:
            parent_id = direct_ids[np.random.randint(0, len(direct_ids))]
        components.append({
            "id": idx + 1,
            "name": name,
            "version": _generate_version(),
            "ecosystem": eco,
            "is_direct": 0,
            "parent_id": parent_id,
            "description": fake.sentence(nb_words=8),
        })

    return pd.DataFrame(components)


def generate_vulnerabilities(n_rows, components_df):
    """Generate vulnerabilities affecting various components."""
    transitive_names = components_df[components_df["is_direct"] == 0]["name"].tolist()
    direct_names = components_df[components_df["is_direct"] == 1]["name"].tolist()
    all_names = components_df["name"].tolist()

    vulns = []
    used_cves = set()
    year_pool = [2024, 2025, 2026]

    for i in range(n_rows):
        # ~55 % target transitive deps, ~25 % direct, ~20 % random
        r = np.random.random()
        if r < 0.55 and transitive_names:
            comp_name = transitive_names[np.random.randint(0, len(transitive_names))]
        elif r < 0.80 and direct_names:
            comp_name = direct_names[np.random.randint(0, len(direct_names))]
        else:
            comp_name = all_names[np.random.randint(0, len(all_names))]

        comp_row = components_df[components_df["name"] == comp_name].iloc[0]

        # Severity distribution: ~20 % Critical, ~30 % High, ~30 % Medium, ~20 % Low
        sev_r = np.random.random()
        if sev_r < 0.20:
            severity = "Critical"
        elif sev_r < 0.50:
            severity = "High"
        elif sev_r < 0.80:
            severity = "Medium"
        else:
            severity = "Low"

        lo, hi = SEVERITY_CVSS_RANGES[severity]
        cvss = round(float(np.random.uniform(lo, hi)), 1)

        year = year_pool[np.random.randint(0, len(year_pool))]
        seq = 1000 + i
        cve_id = f"CVE-{year}-{seq:05d}"
        while cve_id in used_cves:
            seq += n_rows
            cve_id = f"CVE-{year}-{seq:05d}"
        used_cves.add(cve_id)

        # ~75 % of High/Critical vulns have a fix; ~50 % of Med/Low
        has_fix = (
            (severity in ("Critical", "High") and np.random.random() < 0.75)
            or (severity in ("Medium", "Low") and np.random.random() < 0.50)
        )
        fixed_version = _bump_version(comp_row["version"]) if has_fix else None

        vulns.append({
            "id": i + 1,
            "cve_id": cve_id,
            "component_name": comp_name,
            "affected_version": comp_row["version"],
            "fixed_version": fixed_version,
            "severity": severity,
            "cvss_score": cvss,
            "published_date": _random_date(),
            "description": fake.sentence(nb_words=12),
        })

    return pd.DataFrame(vulns)


def generate_releases(n_rows, components_df):
    """Generate release records for components."""
    all_names = components_df["name"].tolist()
    releases = []
    for i in range(n_rows):
        comp_name = all_names[i % len(all_names)]
        comp_row = components_df[components_df["name"] == comp_name].iloc[0]
        ver = _bump_version(comp_row["version"], kind=np.random.choice(["patch", "minor"]))
        is_sec = int(np.random.random() < 0.35)
        releases.append({
            "id": i + 1,
            "component_name": comp_name,
            "version": ver,
            "release_date": _random_date(2025, 2026),
            "is_security_fix": is_sec,
            "changelog": fake.paragraph(nb_sentences=3),
        })
    return pd.DataFrame(releases)


def generate_deployments(n_rows, components_df):
    """Generate deployment records linking services to direct components."""
    direct_comps = components_df[components_df["is_direct"] == 1]
    direct_ids = direct_comps["id"].tolist()
    envs = ["production", "staging", "development"]

    deployments = []
    # First, ensure every service has some components in production
    base_assignments = []
    for svc in SERVICES:
        n_comps = np.random.randint(3, min(8, len(direct_ids) + 1))
        chosen = np.random.choice(direct_ids, size=n_comps, replace=False).tolist()
        for cid in chosen:
            base_assignments.append((svc, cid, "production"))

    # Fill remaining rows with random service-component-environment combos
    while len(base_assignments) < n_rows:
        svc = SERVICES[np.random.randint(0, len(SERVICES))]
        cid = direct_ids[np.random.randint(0, len(direct_ids))]
        env = envs[np.random.randint(0, len(envs))]
        base_assignments.append((svc, cid, env))

    # Truncate to exactly n_rows
    base_assignments = base_assignments[:n_rows]

    for i, (svc, cid, env) in enumerate(base_assignments):
        deployments.append({
            "id": i + 1,
            "service_name": svc,
            "component_id": cid,
            "environment": env,
            "deploy_date": _random_date(2025, 2026),
            "is_active": int(np.random.random() < 0.90),
        })
    return pd.DataFrame(deployments)


# ---------------------------------------------------------------------------
# Database creation
# ---------------------------------------------------------------------------

def create_database(db_path, components, vulns, releases, deployments):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("DROP TABLE IF EXISTS components")
    c.execute("DROP TABLE IF EXISTS vulnerabilities")
    c.execute("DROP TABLE IF EXISTS releases")
    c.execute("DROP TABLE IF EXISTS deployments")

    c.execute("""
        CREATE TABLE components (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            ecosystem TEXT,
            is_direct INTEGER,
            parent_id INTEGER,
            description TEXT,
            FOREIGN KEY (parent_id) REFERENCES components(id)
        )
    """)

    c.execute("""
        CREATE TABLE vulnerabilities (
            id INTEGER PRIMARY KEY,
            cve_id TEXT UNIQUE NOT NULL,
            component_name TEXT NOT NULL,
            affected_version TEXT,
            fixed_version TEXT,
            severity TEXT,
            cvss_score REAL,
            published_date TEXT,
            description TEXT
        )
    """)

    c.execute("""
        CREATE TABLE releases (
            id INTEGER PRIMARY KEY,
            component_name TEXT NOT NULL,
            version TEXT NOT NULL,
            release_date TEXT,
            is_security_fix INTEGER,
            changelog TEXT
        )
    """)

    c.execute("""
        CREATE TABLE deployments (
            id INTEGER PRIMARY KEY,
            service_name TEXT NOT NULL,
            component_id INTEGER NOT NULL,
            environment TEXT,
            deploy_date TEXT,
            is_active INTEGER,
            FOREIGN KEY (component_id) REFERENCES components(id)
        )
    """)

    components.to_sql("components", conn, if_exists="append", index=False)
    vulns.to_sql("vulnerabilities", conn, if_exists="append", index=False)
    releases.to_sql("releases", conn, if_exists="append", index=False)
    deployments.to_sql("deployments", conn, if_exists="append", index=False)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Workspace file generation
# ---------------------------------------------------------------------------

def generate_workspace(workspace, components_df, vulns_df, releases_df, deployments_df):
    os.makedirs(workspace, exist_ok=True)

    n_files = SCALE["num_workspace_files"]

    # Distribution across file types (ratios)
    n_sbom = max(2, int(n_files * 0.30))
    n_vuln = max(2, int(n_files * 0.30))
    n_deploy = max(1, int(n_files * 0.20))
    n_release = max(1, n_files - n_sbom - n_vuln - n_deploy)

    _write_sbom_files(workspace, components_df, deployments_df, n_sbom)
    _write_vuln_feeds(workspace, vulns_df, n_vuln)
    _write_deploy_manifests(workspace, deployments_df, components_df, n_deploy)
    _write_release_notes(workspace, releases_df, components_df, n_release)

    # Fixed config files (not counted toward SCALE["num_workspace_files"])
    _write_prioritization_policy(workspace)
    _write_service_criticality(workspace)


def _write_sbom_files(workspace, components_df, deployments_df, n_files):
    """Write SBOM JSON files. Each covers a subset of services and their components."""
    # Determine which direct components each service uses
    svc_to_direct_ids = {}
    for svc in SERVICES:
        svc_deps = deployments_df[
            (deployments_df["service_name"] == svc)
        ]["component_id"].unique().tolist()
        svc_to_direct_ids[svc] = svc_deps

    # Split services across SBOM files
    svc_chunks = np.array_split(SERVICES, n_files)

    for i, svc_group in enumerate(svc_chunks):
        sbom_components = []
        seen_names = set()

        for svc in svc_group:
            direct_ids = svc_to_direct_ids.get(svc, [])
            for did in direct_ids:
                row = components_df[components_df["id"] == did]
                if row.empty:
                    continue
                row = row.iloc[0]
                if row["name"] not in seen_names:
                    seen_names.add(row["name"])
                    sbom_components.append({
                        "name": row["name"],
                        "version": row["version"],
                        "ecosystem": row["ecosystem"],
                        "dependency_type": "direct",
                        "parent_component": None,
                    })
                # Find ALL transitive deps recursively
                stack = [did]
                while stack:
                    parent_cid = stack.pop()
                    parent_row = components_df[components_df["id"] == parent_cid].iloc[0]
                    children = components_df[components_df["parent_id"] == parent_cid]
                    for _, child in children.iterrows():
                        if child["name"] not in seen_names:
                            seen_names.add(child["name"])
                            sbom_components.append({
                                "name": child["name"],
                                "version": child["version"],
                                "ecosystem": child["ecosystem"],
                                "dependency_type": "transitive",
                                "parent_component": parent_row["name"],
                            })
                            stack.append(child["id"])

        sbom_doc = {
            "sbom_id": f"SBOM-{i + 1:03d}",
            "generated_date": "2026-04-01",
            "services": list(svc_group),
            "component_count": len(sbom_components),
            "components": sbom_components,
        }

        path = os.path.join(workspace, f"sbom_{i + 1:03d}.json")
        with open(path, "w") as f:
            json.dump(sbom_doc, f, indent=2)


def _write_vuln_feeds(workspace, vulns_df, n_files):
    """Write vulnerability feed CSV files. Each covers a subset of CVEs."""
    chunks = _split_df(vulns_df, n_files)
    for i, chunk in enumerate(chunks):
        path = os.path.join(workspace, f"vuln_feed_{i + 1:03d}.csv")
        subset = chunk[["cve_id", "component_name", "severity", "published_date"]].copy()
        subset.to_csv(path, index=False, quoting=csv.QUOTE_ALL)


def _write_deploy_manifests(workspace, deployments_df, components_df, n_files):
    """Write deployment manifest YAML files."""
    svc_chunks = np.array_split(SERVICES, n_files)

    for i, svc_group in enumerate(svc_chunks):
        manifests = []
        for svc in svc_group:
            svc_deps = deployments_df[deployments_df["service_name"] == svc]
            deployed_comps = []
            for _, dep_row in svc_deps.iterrows():
                comp = components_df[components_df["id"] == dep_row["component_id"]]
                if comp.empty:
                    continue
                comp = comp.iloc[0]
                deployed_comps.append({
                    "name": comp["name"],
                    "version": comp["version"],
                    "environment": dep_row["environment"],
                    "deploy_date": dep_row["deploy_date"],
                    "active": bool(dep_row["is_active"]),
                })
            manifests.append({
                "service": svc,
                "components": deployed_comps,
            })

        path = os.path.join(workspace, f"deploy_manifest_{i + 1:03d}.yaml")
        with open(path, "w") as f:
            # Manual YAML writing to avoid dependency issues
            for m in manifests:
                f.write(f"---\nservice: {m['service']}\ncomponents:\n")
                for c in m["components"]:
                    f.write(f"  - name: \"{c['name']}\"\n")
                    f.write(f"    version: \"{c['version']}\"\n")
                    f.write(f"    environment: {c['environment']}\n")
                    f.write(f"    deploy_date: \"{c['deploy_date']}\"\n")
                    f.write(f"    active: {str(c['active']).lower()}\n")


def _write_release_notes(workspace, releases_df, components_df, n_files):
    """Write release notes markdown files."""
    chunks = _split_df(releases_df, n_files)
    for i, chunk in enumerate(chunks):
        path = os.path.join(workspace, f"release_notes_{i + 1:03d}.md")
        with open(path, "w") as f:
            for _, rel in chunk.iterrows():
                comp = components_df[components_df["name"] == rel["component_name"]]
                eco = comp.iloc[0]["ecosystem"] if not comp.empty else "unknown"
                sec_tag = " [SECURITY]" if rel["is_security_fix"] else ""
                f.write(f"# {rel['component_name']} v{rel['version']}{sec_tag}\n\n")
                f.write(f"**Ecosystem:** {eco}  \n")
                f.write(f"**Release Date:** {rel['release_date']}  \n\n")
                f.write(f"{rel['changelog']}\n\n")
                f.write("---\n\n")


def _write_prioritization_policy(workspace):
    """Write the prioritization policy config (fixed, not scaled)."""
    policy = {
        "minimum_severity_threshold": "High",
        "included_severities": ["Critical", "High"],
        "severity_weights": {
            "Critical": 4,
            "High": 3,
            "Medium": 2,
            "Low": 1,
        },
        "priority_score_formula": "cvss_score * severity_weight * max_service_criticality_multiplier",
        "service_criticality_multipliers": {
            "critical": 3.0,
            "high": 2.0,
            "standard": 1.0,
            "low": 0.5,
        },
        "patch_deadlines_days": {
            "Critical": 7,
            "High": 30,
        },
        "reference_date": "2026-04-20",
        "sort_order": [
            {"field": "priority_score", "direction": "descending"},
            {"field": "cvss_score", "direction": "descending"},
            {"field": "cve_id", "direction": "ascending"},
        ],
    }
    path = os.path.join(workspace, "prioritization_policy.json")
    with open(path, "w") as f:
        json.dump(policy, f, indent=2)


def _write_service_criticality(workspace):
    """Write the service criticality tiers config (fixed, not scaled)."""
    path = os.path.join(workspace, "service_criticality.yaml")
    with open(path, "w") as f:
        f.write("# Service criticality tiers\n")
        f.write("# Used for patch prioritization scoring\n\n")
        f.write("service_tiers:\n")
        for svc, tier in SERVICE_CRITICALITY.items():
            f.write(f"  {svc}: {tier}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_rows = SCALE["rows_per_table"]

    # Generate data
    components = generate_components(n_rows)
    vulns = generate_vulnerabilities(n_rows, components)
    releases = generate_releases(n_rows, components)
    deployments = generate_deployments(n_rows, components)

    # Create database
    create_database(args.db_path, components, vulns, releases, deployments)

    # Generate workspace files
    generate_workspace(args.workspace, components, vulns, releases, deployments)

    print(f"Database created at {args.db_path}")
    print(f"Workspace files generated in {args.workspace}")
    print(f"  Components: {len(components)} ({components['is_direct'].sum()} direct, "
          f"{(~components['is_direct'].astype(bool)).sum()} transitive)")
    print(f"  Vulnerabilities: {len(vulns)}")
    print(f"  Releases: {len(releases)}")
    print(f"  Deployments: {len(deployments)}")


if __name__ == "__main__":
    main()
