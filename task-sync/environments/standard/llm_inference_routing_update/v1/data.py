#!/usr/bin/env python3
"""Data generation script for LLM inference routing task environment."""

import argparse
import os
import sqlite3
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 20,
}

# Fix all random seeds
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ---------- Constants ----------
PROVIDERS = [
    "OpenAI", "Anthropic", "Google", "Meta", "Mistral",
    "Cohere", "AI21", "Amazon", "DeepSeek", "Zhipu",
]

TIERS = ["economy", "standard", "premium", "enterprise"]
TIER_DISTRIBUTION = [0.30, 0.30, 0.24, 0.16]

MODEL_STATUSES = ["active", "inactive", "degraded"]
STATUS_WEIGHTS = [0.70, 0.15, 0.15]

REGIONS = ["us-east", "us-west", "eu-west", "ap-southeast", "ap-northeast"]
REQUEST_TYPES = ["chat", "completion", "embedding"]
ENDPOINTS = ["/v1/chat/completions", "/v1/completions", "/v1/embeddings"]

INCIDENT_TYPES = [
    "latency_breach", "error_spike", "downtime", "throttle", "timeout_surge",
]
SEVERITIES = ["low", "medium", "high", "critical"]
INCIDENT_STATUSES = ["open", "resolved", "investigating"]

TIER_PRICING = {
    "economy":    {"input": (0.10, 0.60),  "output": (0.20, 1.00)},
    "standard":   {"input": (0.50, 3.00),  "output": (1.00, 5.00)},
    "premium":    {"input": (2.00, 15.00), "output": (5.00, 30.00)},
    "enterprise": {"input": (10.00, 60.00), "output": (20.00, 100.00)},
}

TIER_LATENCY = {
    "economy":    {"mean": 800,  "std": 300},
    "standard":   {"mean": 400,  "std": 150},
    "premium":    {"mean": 150,  "std": 60},
    "enterprise": {"mean": 80,   "std": 30},
}

TIER_CONTEXT = {
    "economy":    (4096, 16384),
    "standard":   (8192, 32768),
    "premium":    (16384, 131072),
    "enterprise": (32768, 200000),
}

MODEL_VARIANTS = {
    "OpenAI":    ["GPT4o", "GPT4o-mini", "GPT4-turbo", "GPT3.5-turbo", "o1-mini", "o1", "o3-mini"],
    "Anthropic": ["Claude3-Haiku", "Claude3-Sonnet", "Claude3-Opus", "Claude3.5-Sonnet", "Claude3.5-Haiku"],
    "Google":    ["Gemini-Flash", "Gemini-Pro", "Gemini-Ultra", "PaLM2", "Gemma-7B"],
    "Meta":      ["Llama3-8B", "Llama3-70B", "Llama3-405B", "Llama3.1-8B", "Llama3.1-70B"],
    "Mistral":   ["Mistral-7B", "Mistral-Small", "Mistral-Medium", "Mistral-Large", "Mixtral-8x7B"],
    "Cohere":    ["Command-Light", "Command", "Command-R", "Command-R-Plus"],
    "AI21":      ["Jamba-Mini", "Jamba-Large", "J2-Ultra", "J2-Mid"],
    "Amazon":    ["Titan-Lite", "Titan-Express", "Titan-Premier", "Nova-Micro", "Nova-Lite"],
    "DeepSeek":  ["DS-V2", "DS-V2.5", "DS-V3", "DS-Coder-V2", "DS-R1"],
    "Zhipu":     ["GLM4-Flash", "GLM4-Air", "GLM4-Plus", "GLM4-Long"],
}

ROOT_CAUSES = [
    "network_congestion", "gpu_memory_overflow", "rate_limit_misconfiguration",
    "upstream_provider_outage", "load_balancer_failure", "certificate_expiry",
    "dns_resolution_delay", "cold_start_spike", "memory_leak", "config_drift",
]


# ---------- Data generation ----------

def _build_model_name_pool():
    """Build a large pool of unique model names."""
    pool = []
    for provider in PROVIDERS:
        for variant in MODEL_VARIANTS[provider]:
            for ver in ["v1", "v2", "v3"]:
                pool.append((provider, f"{provider}-{variant}-{ver}"))
    return pool


def generate_models(n_models):
    """Generate model entries deterministically."""
    pool = _build_model_name_pool()
    rng = np.random.RandomState(42)
    indices = rng.permutation(len(pool))

    tier_counts = np.round(np.array(TIER_DISTRIBUTION) * n_models).astype(int)
    tier_counts[0] += n_models - tier_counts.sum()

    models = []
    idx = 0
    for tier_idx, tier in enumerate(TIERS):
        for _ in range(tier_counts[tier_idx]):
            pi = indices[idx % len(indices)]
            provider, model_name = pool[pi]
            status = rng.choice(MODEL_STATUSES, p=STATUS_WEIGHTS)

            pr = TIER_PRICING[tier]
            input_price = round(rng.uniform(*pr["input"]), 2)
            output_price = round(rng.uniform(*pr["output"]), 2)

            ctx = TIER_CONTEXT[tier]
            max_ctx = int(rng.choice([ctx[0], (ctx[0] + ctx[1]) // 2, ctx[1]]))

            region = REGIONS[idx % len(REGIONS)]
            model_id = f"M{idx + 1:04d}"

            models.append({
                "model_id": model_id,
                "model_name": model_name,
                "provider": provider,
                "tier": tier,
                "input_price_per_mtok": input_price,
                "output_price_per_mtok": output_price,
                "max_context_tokens": max_ctx,
                "status": status,
                "deployed_region": region,
            })
            idx += 1

    return models


def generate_latency_samples(models, n_samples):
    """Generate latency measurement records."""
    rng = np.random.RandomState(42)
    active_models = [m for m in models if m["status"] != "inactive"]
    if not active_models:
        active_models = models[:5]

    # Prone models: deterministic selection based on index
    prone_ids = set()
    for i, m in enumerate(models):
        if i % 5 == 0:
            prone_ids.add(m["model_id"])

    base_ts = pd.Timestamp("2025-01-01")
    samples = []
    for i in range(n_samples):
        model = active_models[i % len(active_models)]
        tier = model["tier"]
        lp = TIER_LATENCY[tier]
        latency = max(10.0, rng.normal(lp["mean"], lp["std"]))

        if model["model_id"] in prone_ids:
            latency *= rng.uniform(2.0, 4.0)

        ts = base_ts + pd.Timedelta(hours=int(rng.randint(0, 24 * 90)))
        samples.append({
            "sample_id": i + 1,
            "model_id": model["model_id"],
            "timestamp": ts.isoformat(),
            "latency_ms": round(latency, 2),
            "request_type": REQUEST_TYPES[i % len(REQUEST_TYPES)],
            "endpoint": ENDPOINTS[i % len(ENDPOINTS)],
        })
    return samples


def generate_request_log(models, n_requests):
    """Generate API request log entries."""
    rng = np.random.RandomState(43)
    active_models = [m for m in models if m["status"] != "inactive"]
    if not active_models:
        active_models = models[:5]

    n_clients = max(20, n_requests // 4)
    client_ids = [f"CLI-{j + 1:04d}" for j in range(n_clients)]

    base_ts = pd.Timestamp("2025-01-01")
    requests = []
    for i in range(n_requests):
        model = active_models[i % len(active_models)]
        lp = TIER_LATENCY[model["tier"]]
        prompt_tokens = int(max(50, rng.lognormal(7, 1)))
        completion_tokens = int(max(10, rng.lognormal(6, 0.8)))
        total_latency = max(50.0, rng.normal(lp["mean"], lp["std"]))
        roll = rng.random()
        status = "success" if roll < 0.85 else ("error" if roll < 0.93 else "timeout")
        ts = base_ts + pd.Timedelta(hours=int(rng.randint(0, 24 * 90)))
        requests.append({
            "request_id": i + 1,
            "model_id": model["model_id"],
            "client_id": client_ids[i % len(client_ids)],
            "timestamp": ts.isoformat(),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_latency_ms": round(total_latency, 2),
            "status": status,
        })
    return requests, client_ids


def generate_sla_incidents(models, n_incidents):
    """Generate SLA incident records."""
    rng = np.random.RandomState(44)
    active_models = [m for m in models if m["status"] != "inactive"]
    if not active_models:
        active_models = models[:5]

    prone_models = [m for i, m in enumerate(models) if i % 5 == 0 and m["status"] != "inactive"]
    if not prone_models:
        prone_models = active_models[:3]

    base_ts = pd.Timestamp("2025-01-01")
    incidents = []
    desc_templates = [
        "Latency exceeded threshold for {tier} tier on {name}",
        "Error rate spike detected on {name}",
        "Service degradation reported in {region} for {name}",
        "Throttling activated due to capacity limits on {name}",
        "Timeout surge affecting requests to {name}",
    ]

    for i in range(n_incidents):
        if rng.random() < 0.60 and prone_models:
            model = prone_models[i % len(prone_models)]
        else:
            model = active_models[i % len(active_models)]

        severity = rng.choice(SEVERITIES, p=[0.25, 0.30, 0.25, 0.20])
        inc_status = rng.choice(INCIDENT_STATUSES, p=[0.45, 0.30, 0.25])
        ts = base_ts + pd.Timedelta(hours=int(rng.randint(0, 24 * 90)))
        affected = int(max(1, rng.lognormal(4, 1.5)))

        tmpl = desc_templates[i % len(desc_templates)]
        desc = tmpl.format(tier=model["tier"], name=model["model_name"],
                           region=model["deployed_region"])

        incidents.append({
            "incident_id": i + 1,
            "model_id": model["model_id"],
            "timestamp": ts.isoformat(),
            "incident_type": INCIDENT_TYPES[i % len(INCIDENT_TYPES)],
            "severity": severity,
            "status": inc_status,
            "affected_requests": affected,
            "description": desc,
        })
    return incidents


def generate_routing_rules(models):
    """Generate one routing rule per model."""
    rng = np.random.RandomState(45)
    base_priority = {"economy": 30, "standard": 20, "premium": 10, "enterprise": 5}
    prompt_limits = {"economy": 4000, "standard": 8000, "premium": 16000, "enterprise": 32000}
    ceiling_base = {"economy": 2000, "standard": 1000, "premium": 500, "enterprise": 200}

    rules = []
    for i, model in enumerate(models):
        tier = model["tier"]
        priority = base_priority[tier] + int(rng.randint(-3, 4))
        # Deliberately vary max_prompt_length so some differ from tier threshold
        mpl = prompt_limits[tier] + int(rng.choice([-2000, -1000, 0, 0, 1000, 2000]))
        latency_ceiling = ceiling_base[tier] + int(rng.randint(-50, 100))
        active = 0 if model["status"] == "inactive" else 1
        rules.append({
            "rule_id": i + 1,
            "model_id": model["model_id"],
            "tier": tier,
            "priority": priority,
            "max_prompt_length": mpl,
            "latency_ceiling_ms": float(latency_ceiling),
            "cost_weight": round(float(rng.uniform(0.3, 0.8)), 2),
            "active": active,
        })
    return rules


# ---------- Database creation ----------

def create_database(db_path, models, latency_samples, request_log, sla_incidents, routing_rules):
    """Create and populate the SQLite database."""
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE models (
            model_id TEXT PRIMARY KEY,
            model_name TEXT NOT NULL,
            provider TEXT NOT NULL,
            tier TEXT NOT NULL,
            input_price_per_mtok REAL NOT NULL,
            output_price_per_mtok REAL NOT NULL,
            max_context_tokens INTEGER NOT NULL,
            status TEXT NOT NULL,
            deployed_region TEXT NOT NULL
        )
    """)
    for m in models:
        cur.execute("INSERT INTO models VALUES (?,?,?,?,?,?,?,?,?)",
                     (m["model_id"], m["model_name"], m["provider"], m["tier"],
                      m["input_price_per_mtok"], m["output_price_per_mtok"],
                      m["max_context_tokens"], m["status"], m["deployed_region"]))

    cur.execute("""
        CREATE TABLE latency_samples (
            sample_id INTEGER PRIMARY KEY,
            model_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            latency_ms REAL NOT NULL,
            request_type TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            FOREIGN KEY (model_id) REFERENCES models(model_id)
        )
    """)
    for s in latency_samples:
        cur.execute("INSERT INTO latency_samples VALUES (?,?,?,?,?,?)",
                     (s["sample_id"], s["model_id"], s["timestamp"],
                      s["latency_ms"], s["request_type"], s["endpoint"]))

    cur.execute("""
        CREATE TABLE request_log (
            request_id INTEGER PRIMARY KEY,
            model_id TEXT NOT NULL,
            client_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL,
            total_latency_ms REAL NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (model_id) REFERENCES models(model_id)
        )
    """)
    for r in request_log:
        cur.execute("INSERT INTO request_log VALUES (?,?,?,?,?,?,?,?)",
                     (r["request_id"], r["model_id"], r["client_id"], r["timestamp"],
                      r["prompt_tokens"], r["completion_tokens"],
                      r["total_latency_ms"], r["status"]))

    cur.execute("""
        CREATE TABLE sla_incidents (
            incident_id INTEGER PRIMARY KEY,
            model_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            incident_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            affected_requests INTEGER NOT NULL,
            description TEXT NOT NULL,
            FOREIGN KEY (model_id) REFERENCES models(model_id)
        )
    """)
    for inc in sla_incidents:
        cur.execute("INSERT INTO sla_incidents VALUES (?,?,?,?,?,?,?,?)",
                     (inc["incident_id"], inc["model_id"], inc["timestamp"],
                      inc["incident_type"], inc["severity"], inc["status"],
                      inc["affected_requests"], inc["description"]))

    cur.execute("""
        CREATE TABLE routing_rules (
            rule_id INTEGER PRIMARY KEY,
            model_id TEXT NOT NULL UNIQUE,
            tier TEXT NOT NULL,
            priority INTEGER NOT NULL,
            max_prompt_length INTEGER NOT NULL,
            latency_ceiling_ms REAL NOT NULL,
            cost_weight REAL NOT NULL,
            active INTEGER NOT NULL,
            FOREIGN KEY (model_id) REFERENCES models(model_id)
        )
    """)
    for r in routing_rules:
        cur.execute("INSERT INTO routing_rules VALUES (?,?,?,?,?,?,?,?)",
                     (r["rule_id"], r["model_id"], r["tier"], r["priority"],
                      r["max_prompt_length"], r["latency_ceiling_ms"],
                      r["cost_weight"], r["active"]))

    conn.commit()
    conn.close()


# ---------- Workspace files ----------

def generate_workspace_files(workspace, models, latency_samples, sla_incidents,
                             request_log, client_ids):
    """Generate all workspace files (scalable data files + fixed configs)."""
    os.makedirs(workspace, exist_ok=True)
    rng = np.random.RandomState(46)

    n_files = SCALE["num_workspace_files"]
    n_latency_files = max(1, int(0.4 * n_files))
    n_request_files = max(1, int(0.3 * n_files))
    n_incident_files = max(1, int(0.2 * n_files))
    n_benchmark_files = max(1, n_files - n_latency_files - n_request_files - n_incident_files)

    active_models = [m for m in models if m["status"] != "inactive"]
    prone_ids = set(m["model_id"] for i, m in enumerate(models) if i % 5 == 0)

    # --- Latency window CSVs ---
    for f_idx in range(n_latency_files):
        window_label = f"2025-Q1-W{f_idx + 1}"
        rows = []
        for m in active_models:
            lp = TIER_LATENCY[m["tier"]]
            avg_lat = max(10.0, rng.normal(lp["mean"], lp["std"] * 0.5))
            retry_rate = round(float(rng.beta(2, 20)), 4)
            satisfaction = round(float(np.clip(rng.normal(0.80, 0.12), 0.10, 1.0)), 2)
            if m["model_id"] in prone_ids:
                satisfaction = round(max(0.10, satisfaction - 0.20), 2)
                retry_rate = round(min(0.50, retry_rate * 3), 4)
            rows.append({
                "model_id": m["model_id"],
                "window_label": window_label,
                "avg_latency_ms": round(avg_lat, 2),
                "retry_rate": retry_rate,
                "client_satisfaction_score": satisfaction,
            })
        pd.DataFrame(rows).to_csv(
            os.path.join(workspace, f"latency_window_{f_idx + 1:03d}.csv"), index=False)

    # --- Request pattern JSONs ---
    clients_per_file = max(1, len(client_ids) // n_request_files)
    for f_idx in range(n_request_files):
        start = f_idx * clients_per_file
        end = start + clients_per_file if f_idx < n_request_files - 1 else len(client_ids)
        batch = client_ids[start:end]
        patterns = []
        for cid in batch:
            n_prefs = int(rng.randint(1, 4))
            pref_start = int(rng.randint(0, len(active_models)))
            prefs = [active_models[(pref_start + j) % len(active_models)]["model_id"]
                     for j in range(n_prefs)]
            patterns.append({
                "client_id": cid,
                "preferred_models": prefs,
                "avg_prompt_length": int(max(100, rng.lognormal(7, 0.8))),
                "cost_sensitivity": round(float(rng.uniform(0.1, 1.0)), 2),
            })
        with open(os.path.join(workspace, f"request_pattern_{f_idx + 1:03d}.json"), "w") as f:
            json.dump(patterns, f, indent=2)

    # --- Incident detail MDs ---
    incs_per_file = max(1, len(sla_incidents) // n_incident_files)
    for f_idx in range(n_incident_files):
        start = f_idx * incs_per_file
        end = start + incs_per_file if f_idx < n_incident_files - 1 else len(sla_incidents)
        batch = sla_incidents[start:end]
        lines = []
        for inc in batch:
            impact = round(float(rng.lognormal(6, 1.5)), 2)
            root_cause = ROOT_CAUSES[inc["incident_id"] % len(ROOT_CAUSES)]
            lines.append(f"## Incident INC-{inc['incident_id']:04d}")
            lines.append(f"- Model: {inc['model_id']}")
            lines.append(f"- Severity: {inc['severity']}")
            lines.append(f"- Status: {inc['status']}")
            lines.append(f"- Root Cause: {root_cause}")
            lines.append(f"- Estimated Impact: ${impact:,.2f}")
            lines.append(f"- Affected Requests: {inc['affected_requests']}")
            lines.append(f"- Description: {inc['description']}")
            lines.append("")
        with open(os.path.join(workspace, f"incident_detail_{f_idx + 1:03d}.md"), "w") as f:
            f.write("\n".join(lines))

    # --- Model benchmark YAMLs ---
    import yaml as yaml_lib
    models_per_file = max(1, len(models) // n_benchmark_files)
    for f_idx in range(n_benchmark_files):
        start = f_idx * models_per_file
        end = start + models_per_file if f_idx < n_benchmark_files - 1 else len(models)
        batch = models[start:end]
        data = {}
        base_quality = {"economy": 0.55, "standard": 0.70, "premium": 0.82, "enterprise": 0.90}
        for m in batch:
            quality = round(float(np.clip(rng.normal(base_quality[m["tier"]], 0.08), 0.10, 1.0)), 2)
            throughput = int(max(10, rng.lognormal(5, 0.5)))
            data[m["model_id"]] = {
                "quality_score": quality,
                "throughput_tokens_per_sec": throughput,
            }
        with open(os.path.join(workspace, f"model_benchmark_{f_idx + 1:03d}.yaml"), "w") as f:
            yaml_lib.dump(data, f, default_flow_style=False, sort_keys=True)

    # --- Fixed config files ---
    _generate_config_files(workspace)


def _generate_config_files(workspace):
    """Generate fixed configuration / policy files."""
    import yaml as yaml_lib

    # 1. tier_sla_policy.yaml
    tier_policy = {
        "economy": {
            "max_p95_latency_ms": 2000,
            "max_error_rate": 0.10,
            "max_open_incidents": 5,
            "critical_incident_threshold": 2,
            "promote_top_pct": 25,
        },
        "standard": {
            "max_p95_latency_ms": 1000,
            "max_error_rate": 0.05,
            "max_open_incidents": 3,
            "critical_incident_threshold": 1,
            "promote_top_pct": 25,
        },
        "premium": {
            "max_p95_latency_ms": 400,
            "max_error_rate": 0.02,
            "max_open_incidents": 2,
            "critical_incident_threshold": 1,
            "promote_top_pct": 25,
        },
        "enterprise": {
            "max_p95_latency_ms": 200,
            "max_error_rate": 0.01,
            "max_open_incidents": 1,
            "critical_incident_threshold": 1,
            "promote_top_pct": 25,
        },
    }
    with open(os.path.join(workspace, "tier_sla_policy.yaml"), "w") as f:
        yaml_lib.dump(tier_policy, f, default_flow_style=False, sort_keys=True)

    # 2. routing_formula.json
    routing_formula = {
        "cost_effectiveness_formula": {
            "quality_weight": 0.35,
            "satisfaction_weight": 0.30,
            "price_weight": 0.35,
            "description": "cost_effectiveness = (quality_score * quality_weight + avg_satisfaction * satisfaction_weight) / ((input_price + output_price) / 2.0 * adjustment_factor * price_weight)",
        },
        "prompt_length_thresholds": {
            "economy": 4000,
            "standard": 8000,
            "premium": 16000,
            "enterprise": 32000,
        },
        "action_priority_adjustments": {
            "demote_priority_increase": 10,
            "promote_priority_decrease": 5,
            "deactivate_priority": 999,
        },
    }
    with open(os.path.join(workspace, "routing_formula.json"), "w") as f:
        json.dump(routing_formula, f, indent=2)

    # 3. cost_adjustment.csv
    rows = [
        ("OpenAI",    1.00, "2025-01-01", "baseline"),
        ("Anthropic", 1.05, "2025-01-01", "premium_support_surcharge"),
        ("Google",    0.95, "2025-01-01", "volume_discount"),
        ("Meta",      0.80, "2025-01-01", "open_source_savings"),
        ("Mistral",   0.85, "2025-01-01", "partnership_discount"),
        ("Cohere",    0.90, "2025-01-01", "enterprise_agreement"),
        ("AI21",      0.92, "2025-01-01", "early_adopter_rate"),
        ("Amazon",    0.88, "2025-01-01", "cloud_bundle_discount"),
        ("DeepSeek",  0.75, "2025-01-01", "competitive_pricing"),
        ("Zhipu",     0.78, "2025-01-01", "regional_pricing"),
    ]
    with open(os.path.join(workspace, "cost_adjustment.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["provider", "adjustment_factor", "effective_date", "reason"])
        writer.writerows(rows)


# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_models = SCALE["rows_per_table"]
    n_latency = 5 * SCALE["rows_per_table"]
    n_requests = 4 * SCALE["rows_per_table"]
    n_incidents = SCALE["rows_per_table"]

    models = generate_models(n_models)
    latency_samples = generate_latency_samples(models, n_latency)
    request_log, client_ids = generate_request_log(models, n_requests)
    sla_incidents = generate_sla_incidents(models, n_incidents)
    routing_rules = generate_routing_rules(models)

    create_database(args.db_path, models, latency_samples, request_log,
                    sla_incidents, routing_rules)
    generate_workspace_files(args.workspace, models, latency_samples,
                             sla_incidents, request_log, client_ids)

    print(f"Database created at {args.db_path}")
    print(f"Workspace generated in {args.workspace}")
    print(f"  Models: {len(models)}")
    print(f"  Latency samples: {len(latency_samples)}")
    print(f"  Requests: {len(request_log)}")
    print(f"  Incidents: {len(sla_incidents)}")
    print(f"  Routing rules: {len(routing_rules)}")


if __name__ == "__main__":
    main()
