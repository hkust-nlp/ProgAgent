import csv
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

    # ── Tools ──────────────────────────────────────────────────────────────

    @tool(
        description="List providers with pagination. Returns provider_id, name, specialty, and region.",
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
    def list_providers(self, page: int, page_size: int = 20):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        total = self._query("SELECT COUNT(*) AS cnt FROM providers")[0]["cnt"]
        rows = self._query(
            "SELECT provider_id, name, specialty, region FROM providers ORDER BY provider_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        return {
            "providers": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description="Get all claims for a specific provider with pagination. Returns claim_id, patient_id, patient_age, procedure_code, billed_amount, claim_date, status, and denial_reason.",
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
    def get_provider_claims(self, provider_id: str, page: int = 1, page_size: int = 50):
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
        return {
            "claims": rows,
            "provider_id": provider_id,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description="Get detailed information about a specific procedure code, including its category, base cost, and complexity level.",
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
    def get_procedure_info(self, procedure_code: str):
        rows = self._query(
            "SELECT * FROM procedures WHERE procedure_code = ?", (procedure_code,)
        )
        if not rows:
            return {"error": f"Procedure code '{procedure_code}' not found."}
        return rows[0]

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
    def get_provider_denial_stats(self, provider_id: str):
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
        return {
            "provider_id": provider_id,
            "total_claims": total,
            "denied_claims": denied,
            "denial_rate": round(denied / total, 4) if total > 0 else 0.0,
            "denial_reasons": reasons,
        }

    @tool(
        description="Get demographic information for a specific patient: patient_id, name, age, gender, and insurance type.",
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
    def get_patient_demographics(self, patient_id: str):
        rows = self._query(
            "SELECT * FROM patients WHERE patient_id = ?", (patient_id,)
        )
        if not rows:
            return {"error": f"Patient '{patient_id}' not found."}
        return rows[0]

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
        c5_passed = False
        c5_reason = ""
        if len(agent_rows) >= 2:
            try:
                agent_scores_list = [float(r.get("composite_risk_score", 0)) for r in agent_rows]
                is_sorted = all(agent_scores_list[i] >= agent_scores_list[i + 1]
                                for i in range(len(agent_scores_list) - 1))
                c5_passed = is_sorted
                if not is_sorted:
                    c5_reason = "Not sorted in descending order by composite_risk_score"
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
        """
        import csv as _csv

        tool_calls = 0

        # ── 1. Read workspace config files ─────────────────────────────────
        with open(os.path.join(self.workspace, "audit_config.yaml")) as f:
            config = yaml.safe_load(f)
        weights = config["scoring_weights"]
        thresholds = config["thresholds"]
        demo_ranges = config["demographic_ranges"]
        decimal_places = config["output"]["decimal_places"]

        with open(os.path.join(self.workspace, "specialty_scope.json")) as f:
            scope = json.load(f)

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

        # ── 5. Get all providers via tool ──────────────────────────────────
        all_providers = []
        page = 1
        while True:
            result = self.tools["list_providers"](page=page, page_size=20)
            tool_calls += 1
            all_providers.extend(result["providers"])
            if not result["has_more"]:
                break
            page += 1

        # ── 6. Cache procedure info ────────────────────────────────────────
        proc_cache = {}

        def _get_proc(code):
            nonlocal tool_calls
            if code not in proc_cache:
                proc_cache[code] = self.tools["get_procedure_info"](procedure_code=code)
                tool_calls += 1
            return proc_cache[code]

        # ── 7. For each provider gather claims and denial stats ────────────
        provider_data = {}  # pid -> {claims, denial_stats}
        for p in all_providers:
            pid = p["provider_id"]
            # Get all claims (paginated)
            all_claims = []
            cp = 1
            while True:
                res = self.tools["get_provider_claims"](provider_id=pid, page=cp, page_size=50)
                tool_calls += 1
                all_claims.extend(res["claims"])
                if not res["has_more"]:
                    break
                cp += 1

            # Get denial stats
            denial = self.tools["get_provider_denial_stats"](provider_id=pid)
            tool_calls += 1

            provider_data[pid] = {
                "claims": all_claims,
                "denial_rate": denial["denial_rate"],
            }

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
