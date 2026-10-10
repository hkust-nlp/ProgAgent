"""
Upcoding Pattern Detection - Task Environment (hardened tool surface)

Provides tools for querying providers, claims, procedures, and patients,
and evaluates the agent's prioritized provider audit list.

Hardened surface (M2 + M3): tools return a mix of shapes — deeply nested
Notion-style record objects with cursor pagination, JSON-encoded strings,
MCP-style envelopes, plain key:value text, and Python-repr strings. Error
responses use a different object shape than success responses. Task
semantics, ground truth, and scoring are unchanged from the base
environment.
"""

import ast
import csv
import hashlib
import json
import math
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


# ── Decorator ──────────────────────────────────────────────────────────────────

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── Hardened tool-surface helpers ──────────────────────────────────────────────

def _request_id(message: str) -> str:
    return "req_" + hashlib.md5(message.encode("utf-8")).hexdigest()[:12]


def _error(status: int, code: str, message: str) -> dict:
    """Error responses share NO keys with success responses."""
    return {
        "status": status,
        "object": "error",
        "code": code,
        "message": message,
        "request_id": _request_id(f"{status}:{code}:{message}"),
    }


def _envelope(payload) -> dict:
    """MCP-style envelope: payload is JSON-encoded into a text content block."""
    return {
        "meta": None,
        "content": [
            {"type": "text",
             "text": json.dumps(payload, ensure_ascii=False, default=str)}
        ],
        "isError": False,
    }


def _shape(value) -> str:
    """Short rendering of a wrong-typed value for error text."""
    if value is None:
        return "'undefined'"
    r = repr(value)
    if len(r) > 60:
        r = r[:57] + "..."
    return f"'{r}'"


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _number(value):
    return {"type": "number", "number": value}


def _title(text):
    return {"type": "title", "title": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _relation(*ids):
    return {"type": "relation", "relation": [{"id": i} for i in ids]}


def _rich_text(text):
    return {"type": "rich_text", "rich_text": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _date(start):
    return {"type": "date", "date": {"start": start, "end": None}}


# ── Task Environment ───────────────────────────────────────────────────────────

class Task_Env:
    def __init__(self, db_path: str, workspace: str):
        """
        Init env.
        Args:
            db_path: Path to the database file.
            workspace: Path to workspace directory for file isolation.
        """
        self.db_path = db_path
        self.workspace = workspace

        # Auto-collect all @tool decorated methods
        self.tools = {}
        for name in dir(self):
            method = getattr(self, name, None)
            if callable(method) and hasattr(method, "_tool_info"):
                self.tools[name] = method

    # --- keep this implementation unchanged ---
    def get_assistant_tools(self) -> List[Dict[str, Any]]:
        """
        Get tool definitions in OpenAI function calling format.

        Returns:
            List of tool definitions compatible with OpenAI API
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": method._tool_info["description"],
                    "parameters": method._tool_info["parameters"],
                },
            }
            for name, method in self.tools.items()
        ]

    # ── Helper ─────────────────────────────────────────────────────────────

    def _query(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def _provider_exists(self, provider_id) -> bool:
        rows = self._query(
            "SELECT 1 FROM providers WHERE provider_id = ?", (provider_id,)
        )
        return bool(rows)

    # ── Tools ──────────────────────────────────────────────────────────────

    @tool(
        description="List providers in the network registry. Returns each provider's ID, name, specialty, and region. Paginated.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20).",
                },
            },
            "required": ["page"],
        },
    )
    def list_providers(self, page: Any = None, page_size: Any = 20):
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _error(400, "validation_error",
                          f"body.page should be a positive integer, instead was {_shape(page)}.")
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            return _error(400, "validation_error",
                          f"body.page_size should be a positive integer, instead was {_shape(page_size)}.")
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        total = self._query("SELECT COUNT(*) AS cnt FROM providers")[0]["cnt"]
        rows = self._query(
            "SELECT provider_id, name, specialty, region FROM providers ORDER BY provider_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        results = [
            {
                "object": "provider",
                "id": r["provider_id"],
                "properties": {
                    "Name": _title(r["name"]),
                    "Specialty": _select(r["specialty"]),
                    "Region": _select(r["region"]),
                },
            }
            for r in rows
        ]
        has_more = offset + len(rows) < total
        return {
            "object": "list",
            "results": results,
            "has_more": has_more,
            "next_cursor": page + 1 if has_more else None,
        }

    @tool(
        description="Get the full registry record for a specific provider, including NPI number, specialty, and region.",
        parameters={
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "string",
                    "description": "The provider ID, e.g. 'PRV0001'.",
                },
            },
            "required": ["provider_id"],
        },
    )
    def get_provider_profile(self, provider_id: Any = None):
        if not isinstance(provider_id, str) or not provider_id:
            return _error(400, "validation_error",
                          f"body.provider_id should be a non-empty string, instead was {_shape(provider_id)}.")
        rows = self._query(
            "SELECT * FROM providers WHERE provider_id = ?", (provider_id,)
        )
        if not rows:
            return _error(404, "object_not_found",
                          f"Could not find provider with ID: {provider_id}.")
        r = rows[0]
        fields = {
            "provider_id": r["provider_id"],
            "name": r["name"],
            "specialty": r["specialty"],
            "region": r["region"],
            "npi_number": r["npi_number"],
        }
        return "\n".join(f"{k}: {v}" for k, v in fields.items())

    @tool(
        description="Get the claims recorded for a specific provider. Each claim includes the patient, the patient's age, the billed procedure code, billed amount, claim date, approval status, and any denial reason. Paginated.",
        parameters={
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "string",
                    "description": "The provider ID, e.g. 'PRV0001'.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 50).",
                },
            },
            "required": ["provider_id"],
        },
    )
    def get_provider_claims(self, provider_id: Any = None, page: Any = 1, page_size: Any = 50):
        if not isinstance(provider_id, str) or not provider_id:
            return _error(400, "validation_error",
                          f"body.provider_id should be a non-empty string, instead was {_shape(provider_id)}.")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _error(400, "validation_error",
                          f"body.page should be a positive integer, instead was {_shape(page)}.")
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            return _error(400, "validation_error",
                          f"body.page_size should be a positive integer, instead was {_shape(page_size)}.")
        if not self._provider_exists(provider_id):
            return _error(404, "object_not_found",
                          f"Could not find provider with ID: {provider_id}.")
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        total = self._query(
            "SELECT COUNT(*) AS cnt FROM claims WHERE provider_id = ?", (provider_id,)
        )[0]["cnt"]
        rows = self._query(
            """SELECT c.claim_id, c.patient_id, p.age AS patient_age,
                      c.procedure_code, c.billed_amount, c.claim_date,
                      c.status, c.denial_reason
               FROM claims c JOIN patients p ON c.patient_id = p.patient_id
               WHERE c.provider_id = ?
               ORDER BY c.claim_id LIMIT ? OFFSET ?""",
            (provider_id, page_size, offset),
        )
        results = [
            {
                "object": "claim",
                "id": r["claim_id"],
                "properties": {
                    "Provider": _relation(provider_id),
                    "Patient": _relation(r["patient_id"]),
                    "Patient Age": _number(r["patient_age"]),
                    "Procedure": _relation(r["procedure_code"]),
                    "Billed Amount": _number(r["billed_amount"]),
                    "Claim Date": _date(r["claim_date"]),
                    "Status": _select(r["status"]),
                    "Denial Reason": _rich_text(r["denial_reason"]),
                },
            }
            for r in rows
        ]
        has_more = offset + len(rows) < total
        return {
            "object": "list",
            "results": results,
            "has_more": has_more,
            "next_cursor": page + 1 if has_more else None,
        }

    @tool(
        description="Get detailed information about a specific procedure code, including its description, category, base cost, and complexity level.",
        parameters={
            "type": "object",
            "properties": {
                "procedure_code": {
                    "type": "string",
                    "description": "The procedure code, e.g. 'CPT10000'.",
                },
            },
            "required": ["procedure_code"],
        },
    )
    def get_procedure_info(self, procedure_code: Any = None):
        if not isinstance(procedure_code, str) or not procedure_code:
            return json.dumps(_error(
                400, "validation_error",
                f"body.procedure_code should be a non-empty string, instead was {_shape(procedure_code)}."))
        rows = self._query(
            "SELECT * FROM procedures WHERE procedure_code = ?", (procedure_code,)
        )
        if not rows:
            return json.dumps(_error(
                404, "object_not_found",
                f"Could not find procedure with ID: {procedure_code}."))
        r = rows[0]
        payload = {
            "object": "procedure",
            "id": r["procedure_code"],
            "properties": {
                "Description": _title(r["description"]),
                "Category": _select(r["category"]),
                "Base Cost": _number(r["base_cost"]),
                "Complexity Level": _select(r["complexity_level"]),
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    @tool(
        description="Get denial statistics for a specific provider: total claims, denied claims, denial rate, and the list of denial reasons with counts.",
        parameters={
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "string",
                    "description": "The provider ID, e.g. 'PRV0001'.",
                },
            },
            "required": ["provider_id"],
        },
    )
    def get_provider_denial_stats(self, provider_id: Any = None):
        if not isinstance(provider_id, str) or not provider_id:
            return _error(400, "validation_error",
                          f"body.provider_id should be a non-empty string, instead was {_shape(provider_id)}.")
        if not self._provider_exists(provider_id):
            return _error(404, "object_not_found",
                          f"Could not find provider with ID: {provider_id}.")
        total = self._query(
            "SELECT COUNT(*) AS cnt FROM claims WHERE provider_id = ?", (provider_id,)
        )[0]["cnt"]
        denied = self._query(
            "SELECT COUNT(*) AS cnt FROM claims WHERE provider_id = ? AND status = 'Denied'",
            (provider_id,),
        )[0]["cnt"]
        reasons = self._query(
            """SELECT denial_reason, COUNT(*) AS cnt
               FROM claims WHERE provider_id = ? AND status = 'Denied' AND denial_reason != ''
               GROUP BY denial_reason ORDER BY cnt DESC""",
            (provider_id,),
        )
        payload = {
            "provider_id": provider_id,
            "total_claims": total,
            "denied_claims": denied,
            "denial_rate": round(denied / total, 4) if total > 0 else 0.0,
            "denial_reasons": reasons,
        }
        return repr(payload)

    @tool(
        description="Get demographic information for a specific patient: patient ID, name, age, gender, and insurance type.",
        parameters={
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The patient ID, e.g. 'PAT00001'.",
                },
            },
            "required": ["patient_id"],
        },
    )
    def get_patient_demographics(self, patient_id: Any = None):
        if not isinstance(patient_id, str) or not patient_id:
            return _error(400, "validation_error",
                          f"body.patient_id should be a non-empty string, instead was {_shape(patient_id)}.")
        rows = self._query(
            "SELECT * FROM patients WHERE patient_id = ?", (patient_id,)
        )
        if not rows:
            return _error(404, "object_not_found",
                          f"Could not find patient with ID: {patient_id}.")
        return _envelope(rows[0])

    # ── Evaluation ─────────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the full ground-truth audit list from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load all tables
        providers = [dict(r) for r in conn.execute("SELECT * FROM providers ORDER BY provider_id").fetchall()]
        claims = [dict(r) for r in conn.execute(
            """SELECT c.*, p.age AS patient_age
               FROM claims c JOIN patients p ON c.patient_id = p.patient_id"""
        ).fetchall()]
        procedures = {r["procedure_code"]: dict(r)
                      for r in conn.execute("SELECT * FROM procedures").fetchall()}
        conn.close()

        # Load workspace config
        with open(os.path.join(self.workspace, "audit_config.yaml")) as f:
            config = yaml.safe_load(f)
        weights = config["scoring_weights"]
        thresholds = config["thresholds"]
        demo_ranges = config["demographic_ranges"]
        decimal_places = config["output"]["decimal_places"]

        with open(os.path.join(self.workspace, "specialty_scope.json")) as f:
            scope = json.load(f)

        # Load benchmarks from all benchmark_data_*.csv files
        benchmarks = {}  # (region, specialty, category) -> expected_pct
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("benchmark_data_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        key = (row["region"], row["specialty"], row["procedure_category"])
                        benchmarks[key] = float(row["expected_pct"])

        # Load peer groups from provider_supplement files
        peer_groups = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("provider_supplement_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        peer_groups[row["provider_id"]] = row["peer_group"]

        # Load historical adjustments
        adj_counts = {}  # provider_id -> count
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("historical_adjustments_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        pid = row["provider_id"]
                        adj_counts[pid] = adj_counts.get(pid, 0) + 1

        # Group claims by provider
        prov_claims = {}
        for c in claims:
            prov_claims.setdefault(c["provider_id"], []).append(c)

        # Compute denial rates per provider and peer-group averages
        denial_rates = {}
        for p in providers:
            pid = p["provider_id"]
            pc = prov_claims.get(pid, [])
            total = len(pc)
            denied = sum(1 for c in pc if c["status"] == "Denied")
            denial_rates[pid] = denied / total if total > 0 else 0.0

        # Peer group average denial rates
        pg_denial = {}
        pg_count = {}
        for p in providers:
            pid = p["provider_id"]
            pg = peer_groups.get(pid, "UNKNOWN")
            pg_denial[pg] = pg_denial.get(pg, 0.0) + denial_rates[pid]
            pg_count[pg] = pg_count.get(pg, 0) + 1
        pg_avg = {pg: pg_denial[pg] / pg_count[pg] for pg in pg_denial}

        # Compute scores for each provider
        results = []
        for p in providers:
            pid = p["provider_id"]
            spec = p["specialty"]
            region = p["region"]
            pc = prov_claims.get(pid, [])
            total = len(pc)
            if total == 0:
                continue

            # 1. Frequency deviation (only authorized categories)
            auth_cats = scope.get(spec, [])
            cat_counts = {}
            for c in pc:
                proc = procedures.get(c["procedure_code"])
                if proc:
                    cat = proc["category"]
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1

            auth_total = sum(cat_counts.get(cat, 0) for cat in auth_cats)
            freq_dev = 0.0
            if auth_total > 0:
                for cat in auth_cats:
                    actual_pct = (cat_counts.get(cat, 0) / auth_total) * 100
                    expected_pct = benchmarks.get((region, spec, cat), 0.0)
                    freq_dev += max(0.0, actual_pct - expected_pct)
            freq_dev = freq_dev / 100.0

            # 2. Out-of-scope rate
            oos_count = 0
            for c in pc:
                proc = procedures.get(c["procedure_code"])
                if proc and proc["category"] not in auth_cats:
                    oos_count += 1
            oos_rate = oos_count / total

            # 3. Denial rate deviation
            pg = peer_groups.get(pid, "UNKNOWN")
            denial_dev = max(0.0, denial_rates[pid] - pg_avg.get(pg, 0.0))

            # 4. Adjustment rate
            adj_rate = adj_counts.get(pid, 0) / total

            # 5. Demographic anomaly rate
            demo_anomaly = 0
            for c in pc:
                proc = procedures.get(c["procedure_code"])
                if proc:
                    complexity = proc["complexity_level"]
                    rng = demo_ranges.get(complexity, {"min_age": 0, "max_age": 100})
                    age = c["patient_age"]
                    if age < rng["min_age"] or age > rng["max_age"]:
                        demo_anomaly += 1
            demo_anomaly_rate = demo_anomaly / total

            # Composite score
            composite = (
                weights["frequency_deviation"] * freq_dev
                + weights["out_of_scope_rate"] * oos_rate
                + weights["denial_rate_deviation"] * denial_dev
                + weights["adjustment_rate"] * adj_rate
                + weights["demographic_anomaly_rate"] * demo_anomaly_rate
            )
            composite = round(composite, decimal_places)

            # Priority
            if composite >= thresholds["high_priority"]:
                priority = "High"
            elif composite >= thresholds["medium_priority"]:
                priority = "Medium"
            elif composite >= thresholds["flag_threshold"]:
                priority = "Low"
            else:
                priority = None  # Not flagged

            results.append({
                "provider_id": pid,
                "provider_name": p["name"],
                "specialty": spec,
                "composite_risk_score": composite,
                "frequency_deviation": round(freq_dev, decimal_places),
                "out_of_scope_rate": round(oos_rate, decimal_places),
                "denial_rate_deviation": round(denial_dev, decimal_places),
                "adjustment_rate": round(adj_rate, decimal_places),
                "demographic_anomaly_rate": round(demo_anomaly_rate, decimal_places),
                "priority": priority,
            })

        # Filter to flagged only and sort descending by composite
        flagged = [r for r in results if r["priority"] is not None]
        flagged.sort(key=lambda x: (-x["composite_risk_score"], x["provider_id"]))

        return flagged, config

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        ground_truth, config = self._compute_ground_truth()
        decimal_places = config["output"]["decimal_places"]
        expected_columns = config["output"]["columns"]

        eval_criteria = {}

        # ── Criterion 1: audit_list.csv exists with correct columns (10 pts) ──
        csv_path = os.path.join(self.workspace, "audit_list.csv")
        c1_passed = False
        c1_reason = ""
        agent_rows = []
        if os.path.exists(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    agent_rows = list(reader)
                cols = list(agent_rows[0].keys()) if agent_rows else []
                missing = [c for c in expected_columns if c not in cols]
                if not missing and len(agent_rows) > 0:
                    c1_passed = True
                else:
                    c1_reason = f"Missing columns: {missing}" if missing else "File is empty"
            except Exception as e:
                c1_reason = f"Parse error: {e}"
        else:
            c1_reason = "audit_list.csv not found"
        eval_criteria["file_structure"] = {
            "passed": c1_passed,
            "score": 10 if c1_passed else 0,
            "max_score": 10,
            "reason": c1_reason if not c1_passed else "",
        }

        # ── Criterion 2: Correct set of flagged providers (20 pts) ──
        gt_ids = {r["provider_id"] for r in ground_truth}
        agent_ids = set()
        for row in agent_rows:
            pid = row.get("provider_id", "").strip()
            if pid:
                agent_ids.add(pid)
        if gt_ids and agent_ids:
            intersection = gt_ids & agent_ids
            precision = len(intersection) / len(agent_ids) if agent_ids else 0
            recall = len(intersection) / len(gt_ids) if gt_ids else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            c2_score = round(f1 * 20)
        else:
            c2_score = 0
            f1 = 0
        c2_passed = c2_score == 20
        eval_criteria["flagged_providers"] = {
            "passed": c2_passed,
            "score": c2_score,
            "max_score": 20,
            "reason": "" if c2_passed else f"F1={f1:.3f}, expected {len(gt_ids)} providers, got {len(agent_ids)}",
        }

        # ── Criterion 3: Correct composite risk scores (20 pts) ──
        gt_scores = {r["provider_id"]: r["composite_risk_score"] for r in ground_truth}
        score_matches = 0
        score_total = 0
        tolerance = 10 ** (-decimal_places)
        for row in agent_rows:
            pid = row.get("provider_id", "").strip()
            if pid in gt_scores:
                score_total += 1
                try:
                    agent_score = round(float(row.get("composite_risk_score", -1)), decimal_places)
                    if abs(agent_score - gt_scores[pid]) <= tolerance:
                        score_matches += 1
                except (ValueError, TypeError):
                    pass
        c3_pct = score_matches / score_total if score_total > 0 else 0
        c3_score = round(c3_pct * 20)
        c3_passed = c3_score == 20
        eval_criteria["composite_scores"] = {
            "passed": c3_passed,
            "score": c3_score,
            "max_score": 20,
            "reason": "" if c3_passed else f"{score_matches}/{score_total} scores matched within tolerance",
        }

        # ── Criterion 4: Correct priority assignments (15 pts) ──
        gt_priorities = {r["provider_id"]: r["priority"] for r in ground_truth}
        pri_matches = 0
        pri_total = 0
        for row in agent_rows:
            pid = row.get("provider_id", "").strip()
            if pid in gt_priorities:
                pri_total += 1
                if row.get("priority", "").strip() == gt_priorities[pid]:
                    pri_matches += 1
        c4_pct = pri_matches / pri_total if pri_total > 0 else 0
        c4_score = round(c4_pct * 15)
        c4_passed = c4_score == 15
        eval_criteria["priority_assignments"] = {
            "passed": c4_passed,
            "score": c4_score,
            "max_score": 15,
            "reason": "" if c4_passed else f"{pri_matches}/{pri_total} priorities correct",
        }

        # ── Criterion 5: Correct sorting (10 pts) ──
        # Primary: descending composite_risk_score; tie-break: ascending provider_id
        c5_passed = False
        c5_reason = ""
        if len(agent_rows) >= 2:
            try:
                is_sorted = True
                for i in range(len(agent_rows) - 1):
                    s1 = float(agent_rows[i].get("composite_risk_score", 0))
                    s2 = float(agent_rows[i + 1].get("composite_risk_score", 0))
                    pid1 = agent_rows[i].get("provider_id", "").strip()
                    pid2 = agent_rows[i + 1].get("provider_id", "").strip()
                    if s1 < s2:
                        is_sorted = False
                        c5_reason = (f"Row {i} composite {s1} < row {i + 1} composite {s2}: "
                                     "not in descending order")
                        break
                    if s1 == s2 and pid1 > pid2:
                        is_sorted = False
                        c5_reason = (f"Tie at composite {s1}: {pid1} comes before {pid2} "
                                     "but tie-break requires ascending provider_id")
                        break
                c5_passed = is_sorted
            except (ValueError, TypeError):
                c5_reason = "Non-numeric composite_risk_score values"
        elif len(agent_rows) == 1:
            c5_passed = True
        else:
            c5_reason = "No rows to check sorting"
        eval_criteria["sorting_order"] = {
            "passed": c5_passed,
            "score": 10 if c5_passed else 0,
            "max_score": 10,
            "reason": c5_reason if not c5_passed else "",
        }

        # ── Criterion 6: Correct individual score components (15 pts) ──
        gt_components = {}
        component_keys = ["frequency_deviation", "out_of_scope_rate",
                          "denial_rate_deviation", "adjustment_rate",
                          "demographic_anomaly_rate"]
        for r in ground_truth:
            gt_components[r["provider_id"]] = {k: r[k] for k in component_keys}
        comp_matches = 0
        comp_total = 0
        for row in agent_rows:
            pid = row.get("provider_id", "").strip()
            if pid in gt_components:
                for k in component_keys:
                    comp_total += 1
                    try:
                        agent_val = round(float(row.get(k, -999)), decimal_places)
                        if abs(agent_val - gt_components[pid][k]) <= tolerance:
                            comp_matches += 1
                    except (ValueError, TypeError):
                        pass
        c6_pct = comp_matches / comp_total if comp_total > 0 else 0
        c6_score = round(c6_pct * 15)
        c6_passed = c6_score == 15
        eval_criteria["score_components"] = {
            "passed": c6_passed,
            "score": c6_score,
            "max_score": 15,
            "reason": "" if c6_passed else f"{comp_matches}/{comp_total} component values correct",
        }

        # ── Criterion 7: Response summary (10 pts) ──
        # Check that the action contains top-5 provider IDs
        top5 = ground_truth[:5]
        top5_found = 0
        for r in top5:
            if r["provider_id"] in action:
                top5_found += 1
        c7_score = round((top5_found / max(len(top5), 1)) * 10)
        c7_passed = c7_score == 10
        eval_criteria["response_summary"] = {
            "passed": c7_passed,
            "score": c7_score,
            "max_score": 10,
            "reason": "" if c7_passed else f"Found {top5_found}/{len(top5)} top provider IDs in response",
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        This method proves end-to-end solvability. It must:
          - Use self.tools[name](**params) to gather data (no direct DB queries).
          - Read files from self.workspace as needed.
          - Write all required deliverables to self.workspace.
          - Construct the final action string.
          - Return self.step(action).

        Note: the hardened tool surface returns mixed shapes, so this solver
        unwraps MCP envelopes, parses JSON strings / repr strings / key:value
        text, extracts values from nested property objects, and follows
        has_more/next_cursor pagination.
        """
        import csv as _csv

        tool_calls = 0

        def call_tool(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        def unwrap_envelope(resp):
            return json.loads(resp["content"][0]["text"])

        def parse_kv_text(text):
            out = {}
            for line in text.splitlines():
                k, _, v = line.partition(": ")
                out[k] = v
            return out

        # ── 1. Read workspace config files ─────────────────────────────────
        with open(os.path.join(self.workspace, "audit_config.yaml")) as f:
            config = yaml.safe_load(f)
        weights = config["scoring_weights"]
        thresholds = config["thresholds"]
        demo_ranges = config["demographic_ranges"]
        decimal_places = config["output"]["decimal_places"]

        with open(os.path.join(self.workspace, "specialty_scope.json")) as f:
            scope = json.load(f)

        # Read the methodology document (the authoritative rule source)
        with open(os.path.join(self.workspace, "audit_methodology.md")) as f:
            _methodology = f.read()

        # ── 2. Read all benchmark files ────────────────────────────────────
        benchmarks = {}  # (region, specialty, category) -> expected_pct
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("benchmark_data_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = _csv.DictReader(f)
                    for row in reader:
                        benchmarks[(row["region"], row["specialty"],
                                    row["procedure_category"])] = float(row["expected_pct"])

        # ── 3. Read all provider supplement files ──────────────────────────
        peer_groups = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("provider_supplement_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = _csv.DictReader(f)
                    for row in reader:
                        peer_groups[row["provider_id"]] = row["peer_group"]

        # ── 4. Read all historical adjustment files ────────────────────────
        adj_counts = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("historical_adjustments_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = _csv.DictReader(f)
                    for row in reader:
                        pid = row["provider_id"]
                        adj_counts[pid] = adj_counts.get(pid, 0) + 1

        # ── 5. Get all providers via tool (nested records, cursor pages) ───
        all_providers = []
        page = 1
        while True:
            result = call_tool("list_providers", page=page, page_size=20)
            for rec in result["results"]:
                props = rec["properties"]
                all_providers.append({
                    "provider_id": rec["id"],
                    "name": props["Name"]["title"][0]["plain_text"],
                    "specialty": props["Specialty"]["select"]["name"],
                    "region": props["Region"]["select"]["name"],
                })
            if not result["has_more"]:
                break
            page = result["next_cursor"]

        # Exercise the profile lookup (plain key:value text) on one provider
        profile_text = call_tool("get_provider_profile",
                                 provider_id=all_providers[0]["provider_id"])
        _profile = parse_kv_text(profile_text)
        assert _profile["provider_id"] == all_providers[0]["provider_id"]

        # ── 6. Cache procedure info (JSON-encoded nested records) ──────────
        proc_cache = {}

        def _get_proc(code):
            if code not in proc_cache:
                raw = call_tool("get_procedure_info", procedure_code=code)
                obj = json.loads(raw)
                props = obj["properties"]
                proc_cache[code] = {
                    "category": props["Category"]["select"]["name"],
                    "complexity_level": props["Complexity Level"]["select"]["name"],
                }
            return proc_cache[code]

        # ── 7. For each provider gather claims and denial stats ────────────
        provider_data = {}  # pid -> {claims, denial_rate}
        for p in all_providers:
            pid = p["provider_id"]
            # Get all claims (nested records, cursor pagination)
            all_claims = []
            cp = 1
            while True:
                res = call_tool("get_provider_claims", provider_id=pid,
                                page=cp, page_size=50)
                for rec in res["results"]:
                    props = rec["properties"]
                    all_claims.append({
                        "claim_id": rec["id"],
                        "patient_id": props["Patient"]["relation"][0]["id"],
                        "patient_age": props["Patient Age"]["number"],
                        "procedure_code": props["Procedure"]["relation"][0]["id"],
                        "status": props["Status"]["select"]["name"],
                    })
                if not res["has_more"]:
                    break
                cp = res["next_cursor"]

            # Get denial stats (Python-repr string; json.loads would fail)
            denial_raw = call_tool("get_provider_denial_stats", provider_id=pid)
            denial = ast.literal_eval(denial_raw)

            provider_data[pid] = {
                "claims": all_claims,
                "denial_rate": denial["denial_rate"],
            }

        # Exercise the patient lookup (MCP envelope) on one patient
        sample_pid = provider_data[all_providers[0]["provider_id"]]["claims"][0]["patient_id"]
        patient = unwrap_envelope(call_tool("get_patient_demographics",
                                            patient_id=sample_pid))
        assert patient["patient_id"] == sample_pid

        # ── 8. Compute denial rate by peer group ───────────────────────────
        pg_sum = {}
        pg_cnt = {}
        for p in all_providers:
            pid = p["provider_id"]
            pg = peer_groups.get(pid, "UNKNOWN")
            pg_sum[pg] = pg_sum.get(pg, 0.0) + provider_data[pid]["denial_rate"]
            pg_cnt[pg] = pg_cnt.get(pg, 0) + 1
        pg_avg = {pg: pg_sum[pg] / pg_cnt[pg] for pg in pg_sum}

        # ── 9. Score each provider ─────────────────────────────────────────
        results = []
        for p in all_providers:
            pid = p["provider_id"]
            spec = p["specialty"]
            region = p["region"]
            pc = provider_data[pid]["claims"]
            total = len(pc)
            if total == 0:
                continue

            auth_cats = scope.get(spec, [])

            # Map claims to categories
            cat_counts = {}
            oos_count = 0
            demo_anomaly = 0
            for c in pc:
                proc = _get_proc(c["procedure_code"])
                cat = proc.get("category", "Unknown")
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
                if cat not in auth_cats:
                    oos_count += 1
                # Demographic anomaly
                complexity = proc.get("complexity_level", "Low")
                rng = demo_ranges.get(complexity, {"min_age": 0, "max_age": 100})
                age = c["patient_age"]
                if age < rng["min_age"] or age > rng["max_age"]:
                    demo_anomaly += 1

            # Frequency deviation (authorised categories only)
            auth_total = sum(cat_counts.get(cat, 0) for cat in auth_cats)
            freq_dev = 0.0
            if auth_total > 0:
                for cat in auth_cats:
                    actual_pct = (cat_counts.get(cat, 0) / auth_total) * 100
                    expected_pct = benchmarks.get((region, spec, cat), 0.0)
                    freq_dev += max(0.0, actual_pct - expected_pct)
            freq_dev /= 100.0

            oos_rate = oos_count / total

            pg = peer_groups.get(pid, "UNKNOWN")
            denial_dev = max(0.0, provider_data[pid]["denial_rate"] - pg_avg.get(pg, 0.0))

            adj_rate = adj_counts.get(pid, 0) / total

            demo_anomaly_rate = demo_anomaly / total

            composite = (
                weights["frequency_deviation"] * freq_dev
                + weights["out_of_scope_rate"] * oos_rate
                + weights["denial_rate_deviation"] * denial_dev
                + weights["adjustment_rate"] * adj_rate
                + weights["demographic_anomaly_rate"] * demo_anomaly_rate
            )
            composite = round(composite, decimal_places)

            if composite >= thresholds["high_priority"]:
                priority = "High"
            elif composite >= thresholds["medium_priority"]:
                priority = "Medium"
            elif composite >= thresholds["flag_threshold"]:
                priority = "Low"
            else:
                priority = None

            if priority is not None:
                results.append({
                    "provider_id": pid,
                    "provider_name": p["name"],
                    "specialty": spec,
                    "composite_risk_score": round(composite, decimal_places),
                    "frequency_deviation": round(freq_dev, decimal_places),
                    "out_of_scope_rate": round(oos_rate, decimal_places),
                    "denial_rate_deviation": round(denial_dev, decimal_places),
                    "adjustment_rate": round(adj_rate, decimal_places),
                    "demographic_anomaly_rate": round(demo_anomaly_rate, decimal_places),
                    "priority": priority,
                })

        results.sort(key=lambda x: (-x["composite_risk_score"], x["provider_id"]))

        # ── 10. Write audit_list.csv ───────────────────────────────────────
        out_path = os.path.join(self.workspace, "audit_list.csv")
        fieldnames = config["output"]["columns"]
        with open(out_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow(r)

        # ── 11. Build action string ────────────────────────────────────────
        top5 = results[:5]
        lines = [f"Upcoding Audit Complete. {len(results)} providers flagged for audit.\n"]
        lines.append("Top 5 highest-risk providers:\n")
        for r in top5:
            lines.append(
                f"  {r['provider_id']} ({r['provider_name']}, {r['specialty']}): "
                f"composite_risk_score={r['composite_risk_score']}, priority={r['priority']}, "
                f"freq_dev={r['frequency_deviation']}, oos_rate={r['out_of_scope_rate']}, "
                f"denial_dev={r['denial_rate_deviation']}, adj_rate={r['adjustment_rate']}, "
                f"demo_anomaly={r['demographic_anomaly_rate']}"
            )
        action = "\n".join(lines)

        print(f"[verify] total tool calls: {tool_calls}")
        return self.step(action)
