"""
Environment for single-source supplier risk monitoring task.
Defines tools for querying supplier/component/PO/inventory/risk data,
and evaluation logic for the mitigation list output.
"""

import csv
import io
import json
import math
import os
import sqlite3
import yaml
from typing import Tuple, Dict, List, Any


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


def _envelope(payload):
    """MCP-style tool result: payload JSON-encoded in a text content block."""
    return {"content": [{"type": "text",
                          "text": json.dumps(payload, ensure_ascii=False, default=str)}],
            "isError": False}


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

    # ── Tool Methods ─────────────────────────────────────────────────────

    @tool(
        description="List suppliers with pagination. Returns a page of supplier records with basic info.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 50)",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_suppliers(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM suppliers")
        total = c.fetchone()[0]
        c.execute(
            "SELECT supplier_id, name, country FROM suppliers ORDER BY supplier_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return _envelope({
            "suppliers": rows,
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": math.ceil(total / page_size),
        })

    @tool(
        description="Get detailed information for a specific supplier by ID.",
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "string",
                    "description": "The supplier ID (e.g. SUP-0001)",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_supplier_details(self, supplier_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM suppliers WHERE supplier_id = ?", (supplier_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return _envelope({"error": f"Supplier {supplier_id} not found"})
        return _envelope(dict(row))

    @tool(
        description="List components with pagination. Returns a page of component records.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 50)",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_components(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM components")
        total = c.fetchone()[0]
        c.execute(
            "SELECT component_id, name, category, criticality_level FROM components ORDER BY component_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps({
            "components": rows,
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": math.ceil(total / page_size),
        }, ensure_ascii=False, default=str)

    @tool(
        description="Get detailed information for a specific component by ID.",
        parameters={
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "The component ID (e.g. CMP-0001)",
                },
            },
            "required": ["component_id"],
        },
    )
    def get_component_details(self, component_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM components WHERE component_id = ?", (component_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return _envelope({"error": f"Component {component_id} not found"})
        return _envelope(dict(row))

    @tool(
        description="Query purchase orders with optional filters. Returns paginated results. At least one filter (supplier_id or component_id) should be provided.",
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "string",
                    "description": "Filter by supplier ID (optional)",
                },
                "component_id": {
                    "type": "string",
                    "description": "Filter by component ID (optional)",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by PO status: delivered, pending, or cancelled (optional)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based, default 1)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 50, default 20)",
                },
            },
            "required": [],
        },
    )
    def query_purchase_orders(
        self,
        supplier_id: str = None,
        component_id: str = None,
        status: str = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size

        conditions = []
        params = []
        if supplier_id:
            conditions.append("supplier_id = ?")
            params.append(supplier_id)
        if component_id:
            conditions.append("component_id = ?")
            params.append(component_id)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(f"SELECT COUNT(*) FROM purchase_orders{where}", params)
        total = c.fetchone()[0]
        c.execute(
            f"SELECT * FROM purchase_orders{where} ORDER BY po_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps({
            "purchase_orders": rows,
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": math.ceil(total / page_size) if total > 0 else 0,
        }, ensure_ascii=False, default=str)

    @tool(
        description="Check current inventory level for a specific component.",
        parameters={
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "The component ID to check inventory for",
                },
            },
            "required": ["component_id"],
        },
    )
    def check_inventory(self, component_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM inventory WHERE component_id = ?", (component_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"No inventory record for {component_id}"}, ensure_ascii=False, default=str)
        d = dict(row)
        if d["daily_usage_rate"] > 0:
            d["coverage_days"] = round(d["quantity_on_hand"] / d["daily_usage_rate"], 1)
        else:
            d["coverage_days"] = 999.0
        return json.dumps(d, ensure_ascii=False, default=str)

    @tool(
        description="Get geopolitical risk data for a specific country.",
        parameters={
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "Country name (e.g. 'China', 'Germany')",
                },
            },
            "required": ["country"],
        },
    )
    def get_country_risk(self, country: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM country_risks WHERE country = ?", (country,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"No risk data for country: {country}"}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    # ── Ground-truth computation (used by step and verify) ───────────────

    def _compute_ground_truth(self) -> list:
        """
        Compute the full ground-truth mitigation list using DB + workspace files.
        Returns a list of dicts sorted by composite_risk_score desc, component_id asc.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load config
        config_path = os.path.join(self.workspace, "risk_config.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)
        weights = config["risk_weights"]
        buffer_days = config["thresholds"]["inventory_buffer_days"]
        tiers = config["risk_tiers"]

        # Load financial health scores from workspace CSV files
        financial_scores = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("supplier_financials_part_") and fname.endswith(".csv"):
                df_path = os.path.join(self.workspace, fname)
                import pandas as pd
                df = pd.read_csv(df_path)
                for _, row in df.iterrows():
                    financial_scores[row["supplier_id"]] = float(row["financial_health_score"])

        # Load quality audit scores from workspace TXT files
        quality_scores = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("quality_audits_part_") and fname.endswith(".txt"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("Supplier:"):
                            parts = line.split("|")
                            sid = parts[0].replace("Supplier:", "").strip()
                            qs = float(parts[1].replace("Quality Score:", "").strip())
                            quality_scores[sid] = qs

        # Load alternate supplier info from workspace JSON files
        alternates = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("component_alternates_part_") and fname.endswith(".json"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as f:
                    records = json.load(f)
                for rec in records:
                    alternates[rec["component_id"]] = {
                        "num_known_alternates": rec["num_known_alternates"],
                        "qualification_status": rec["qualification_status"],
                    }

        # Load lead times from workspace YAML files
        lead_times = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("lead_times_part_") and fname.endswith(".yaml"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as f:
                    records = yaml.safe_load(f)
                for rec in records:
                    lead_times[rec["component_id"]] = rec["lead_time_days"]

        # Get all components
        c = conn.cursor()
        c.execute("SELECT * FROM components ORDER BY component_id")
        components = [dict(r) for r in c.fetchall()]

        # Find single-source components via PO history
        single_source = []
        for comp in components:
            cid = comp["component_id"]
            c.execute(
                "SELECT DISTINCT supplier_id FROM purchase_orders WHERE component_id = ?",
                (cid,),
            )
            suppliers = [r[0] for r in c.fetchall()]
            if len(suppliers) == 1:
                single_source.append((comp, suppliers[0]))

        # Build mitigation list
        mitigation = []
        for comp, supplier_id in single_source:
            cid = comp["component_id"]

            # Supplier details
            c.execute("SELECT * FROM suppliers WHERE supplier_id = ?", (supplier_id,))
            sup = dict(c.fetchone())

            # Country risk
            c.execute("SELECT risk_index FROM country_risks WHERE country = ?", (sup["country"],))
            cr_row = c.fetchone()
            geo_risk = float(cr_row[0]) if cr_row else 50.0

            # Inventory
            c.execute("SELECT * FROM inventory WHERE component_id = ?", (cid,))
            inv = dict(c.fetchone())
            daily_rate = float(inv["daily_usage_rate"])
            coverage_days = round(inv["quantity_on_hand"] / daily_rate, 1) if daily_rate > 0 else 999.0

            # Financial health (from workspace)
            fhs = financial_scores.get(supplier_id, 50.0)

            # Quality score (from workspace)
            qs = quality_scores.get(supplier_id, 50.0)

            # Compute normalized risk factors
            financial_risk = 100.0 - fhs
            inventory_risk = max(0.0, min(100.0, (1.0 - coverage_days / buffer_days) * 100.0))
            quality_risk = 100.0 - qs

            composite = (
                weights["financial_health"] * financial_risk
                + weights["geopolitical_risk"] * geo_risk
                + weights["inventory_risk"] * inventory_risk
                + weights["quality_score"] * quality_risk
            )
            composite = round(composite, 2)

            # Risk tier
            if composite >= tiers["Critical"]:
                tier = "Critical"
            elif composite >= tiers["High"]:
                tier = "High"
            elif composite >= tiers["Medium"]:
                tier = "Medium"
            else:
                tier = "Low"

            # Alternate info
            alt_info = alternates.get(cid, {"num_known_alternates": 0, "qualification_status": "none_identified"})
            qual_status = alt_info["qualification_status"]

            # Recommended action
            action_map = {
                ("Critical", "none_identified"): "Immediate: identify and qualify new alternate suppliers",
                ("Critical", "under_evaluation"): "Immediate: fast-track alternate supplier qualification",
                ("Critical", "qualified"): "Immediate: activate qualified alternate supply",
                ("High", "none_identified"): "Within 30 days: source potential alternate suppliers",
                ("High", "under_evaluation"): "Within 30 days: accelerate qualification process",
                ("High", "qualified"): "Within 30 days: onboard qualified alternate supplier",
            }
            if tier == "Medium":
                rec_action = "Quarterly review: monitor risk indicators"
            elif tier == "Low":
                rec_action = "Annual review: standard monitoring"
            else:
                rec_action = action_map.get((tier, qual_status), "Review supplier risk")

            mitigation.append({
                "component_id": cid,
                "component_name": comp["name"],
                "category": comp["category"],
                "supplier_id": supplier_id,
                "supplier_name": sup["name"],
                "supplier_country": sup["country"],
                "financial_health_score": fhs,
                "geopolitical_risk_index": geo_risk,
                "inventory_coverage_days": coverage_days,
                "quality_audit_score": qs,
                "composite_risk_score": composite,
                "risk_tier": tier,
                "recommended_action": rec_action,
            })

        # Sort: composite_risk_score desc, component_id asc
        mitigation.sort(key=lambda x: (-x["composite_risk_score"], x["component_id"]))

        # Add rank
        for i, entry in enumerate(mitigation):
            entry["rank"] = i + 1

        conn.close()
        return mitigation

    # ── Evaluation ───────────────────────────────────────────────────────

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
        ground_truth = self._compute_ground_truth()
        criteria = {}
        max_total = 0
        earned_total = 0

        # ── Criterion 1: CSV file exists with correct structure (10 pts) ──
        csv_path = os.path.join(self.workspace, "mitigation_list.csv")
        c1_max = 10
        c1_score = 0
        agent_rows = []
        expected_columns = [
            "rank", "component_id", "component_name", "category",
            "supplier_id", "supplier_name", "supplier_country",
            "financial_health_score", "geopolitical_risk_index",
            "inventory_coverage_days", "quality_audit_score",
            "composite_risk_score", "risk_tier", "recommended_action",
        ]
        c1_reason = ""
        if os.path.exists(csv_path):
            try:
                with open(csv_path, "r") as f:
                    reader = csv.DictReader(f)
                    headers = reader.fieldnames or []
                    agent_rows = list(reader)
                if set(expected_columns).issubset(set(headers)):
                    c1_score = c1_max
                else:
                    missing = set(expected_columns) - set(headers)
                    c1_score = 5
                    c1_reason = f"Missing columns: {missing}"
            except Exception as e:
                c1_reason = f"Error reading CSV: {e}"
        else:
            c1_reason = "mitigation_list.csv not found in workspace"
        criteria["csv_structure"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": c1_reason if c1_score < c1_max else "",
        }

        # ── Criterion 2: All single-source components correctly identified (20 pts) ──
        c2_max = 20
        c2_score = 0
        gt_cids = set(e["component_id"] for e in ground_truth)
        agent_cids = set(r.get("component_id", "") for r in agent_rows)
        if gt_cids and agent_cids:
            correct = gt_cids & agent_cids
            extra = agent_cids - gt_cids
            missing = gt_cids - agent_cids
            precision = len(correct) / len(agent_cids) if agent_cids else 0
            recall = len(correct) / len(gt_cids) if gt_cids else 0
            f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0
            c2_score = round(c2_max * f1)
            c2_reason = "" if c2_score == c2_max else f"Missing {len(missing)}, extra {len(extra)} components"
        else:
            c2_reason = "No components to compare" if not gt_cids else "No agent components found"
        criteria["single_source_identification"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": c2_reason if c2_score < c2_max else "",
        }

        # ── Criterion 3: Composite risk scores match ground truth (20 pts) ──
        c3_max = 20
        c3_score = 0
        c3_reason = ""
        if agent_rows and gt_cids:
            gt_map = {e["component_id"]: e["composite_risk_score"] for e in ground_truth}
            matches = 0
            checked = 0
            for r in agent_rows:
                cid = r.get("component_id", "")
                if cid in gt_map:
                    checked += 1
                    try:
                        agent_score = round(float(r.get("composite_risk_score", -1)), 2)
                        if abs(agent_score - gt_map[cid]) < 0.5:
                            matches += 1
                    except (ValueError, TypeError):
                        pass
            if checked > 0:
                c3_score = round(c3_max * matches / len(gt_cids))
                c3_reason = "" if c3_score == c3_max else f"{matches}/{len(gt_cids)} scores correct (tolerance 0.5)"
            else:
                c3_reason = "No matching component IDs to check scores"
        else:
            c3_reason = "No rows to evaluate"
        criteria["composite_risk_scores"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": c3_reason if c3_score < c3_max else "",
        }

        # ── Criterion 4: Correct sorting by composite_risk_score desc (10 pts) ──
        c4_max = 10
        c4_score = 0
        c4_reason = ""
        if len(agent_rows) >= 2:
            try:
                scores = [float(r.get("composite_risk_score", 0)) for r in agent_rows]
                correctly_sorted = all(scores[i] >= scores[i + 1] - 0.01 for i in range(len(scores) - 1))
                if correctly_sorted:
                    c4_score = c4_max
                else:
                    c4_reason = "Rows not sorted by composite_risk_score descending"
            except (ValueError, TypeError):
                c4_reason = "Could not parse composite_risk_score values"
        elif len(agent_rows) == 1:
            c4_score = c4_max
        else:
            c4_reason = "No rows to check sorting"
        criteria["correct_sorting"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": c4_reason if c4_score < c4_max else "",
        }

        # ── Criterion 5: Risk tier assignments correct (15 pts) ──
        c5_max = 15
        c5_score = 0
        c5_reason = ""
        if agent_rows and gt_cids:
            gt_tiers = {e["component_id"]: e["risk_tier"] for e in ground_truth}
            tier_matches = 0
            tier_checked = 0
            for r in agent_rows:
                cid = r.get("component_id", "")
                if cid in gt_tiers:
                    tier_checked += 1
                    if r.get("risk_tier", "").strip() == gt_tiers[cid]:
                        tier_matches += 1
            if tier_checked > 0:
                c5_score = round(c5_max * tier_matches / len(gt_cids))
                c5_reason = "" if c5_score == c5_max else f"{tier_matches}/{len(gt_cids)} tiers correct"
            else:
                c5_reason = "No matching component IDs for tier check"
        else:
            c5_reason = "No rows to evaluate tiers"
        criteria["risk_tier_assignment"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": c5_reason if c5_score < c5_max else "",
        }

        # ── Criterion 6: Response contains correct total count (10 pts) ──
        c6_max = 10
        c6_score = 0
        c6_reason = ""
        expected_count = len(ground_truth)
        if str(expected_count) in action:
            c6_score = c6_max
        else:
            c6_reason = f"Expected total single-source count {expected_count} not found in response"
        criteria["response_total_count"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": c6_reason if c6_score < c6_max else "",
        }

        # ── Criterion 7: Response identifies top 5 critical components (15 pts) ──
        c7_max = 15
        c7_score = 0
        c7_reason = ""
        top5_gt = ground_truth[:5]
        top5_ids = [e["component_id"] for e in top5_gt]
        found_count = 0
        for cid in top5_ids:
            if cid in action:
                found_count += 1
        if found_count > 0:
            c7_score = round(c7_max * found_count / 5)
        c7_reason = "" if c7_score == c7_max else f"Found {found_count}/5 top components in response"
        criteria["response_top5"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": c7_reason if c7_score < c7_max else "",
        }

        # ── Aggregate ────────────────────────────────────────────────────
        for v in criteria.values():
            max_total += v["max_score"]
            earned_total += v["score"]

        reward = earned_total / max_total if max_total > 0 else 0.0

        info = {
            "eval_criteria": criteria,
            "total_score": earned_total,
            "max_score": max_total,
        }
        return reward, info

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
        import pandas as pd

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # ── Step 1: Read workspace config files ──────────────────────────
        config_path = os.path.join(self.workspace, "risk_config.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)
        weights = config["risk_weights"]
        buffer_days = config["thresholds"]["inventory_buffer_days"]
        tiers_config = config["risk_tiers"]

        # Read scoring policy
        policy_path = os.path.join(self.workspace, "scoring_policy.md")
        with open(policy_path) as f:
            policy_text = f.read()

        # ── Step 2: Load financial health scores from CSV files ──────────
        financial_scores = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("supplier_financials_part_") and fname.endswith(".csv"):
                fpath = os.path.join(self.workspace, fname)
                df = pd.read_csv(fpath)
                for _, row in df.iterrows():
                    financial_scores[row["supplier_id"]] = float(row["financial_health_score"])

        # ── Step 3: Load quality audit scores from TXT files ─────────────
        quality_scores = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("quality_audits_part_") and fname.endswith(".txt"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("Supplier:"):
                            parts = line.split("|")
                            sid = parts[0].replace("Supplier:", "").strip()
                            qs = float(parts[1].replace("Quality Score:", "").strip())
                            quality_scores[sid] = qs

        # ── Step 4: Load alternate supplier info from JSON files ─────────
        alternates = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("component_alternates_part_") and fname.endswith(".json"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as f:
                    records = json.load(f)
                for rec in records:
                    alternates[rec["component_id"]] = {
                        "num_known_alternates": rec["num_known_alternates"],
                        "qualification_status": rec["qualification_status"],
                    }

        # ── Step 5: Load lead times from YAML files ─────────────────────
        lead_times = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("lead_times_part_") and fname.endswith(".yaml"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as f:
                    records = yaml.safe_load(f)
                for rec in records:
                    lead_times[rec["component_id"]] = rec["lead_time_days"]

        # ── Step 6: List all components via tools ────────────────────────
        all_components = []
        page = 1
        while True:
            result = json.loads(call_tool("list_components", page=page, page_size=50))
            all_components.extend(result["components"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ── Step 7: For each component, find unique suppliers via POs ────
        single_source_components = []
        for comp in all_components:
            cid = comp["component_id"]
            # Get all POs for this component
            suppliers_seen = set()
            po_page = 1
            while True:
                po_result = json.loads(call_tool(
                    "query_purchase_orders",
                    component_id=cid,
                    page=po_page,
                    page_size=50,
                ))
                for po in po_result["purchase_orders"]:
                    suppliers_seen.add(po["supplier_id"])
                if po_page >= po_result["total_pages"] or po_result["total_pages"] == 0:
                    break
                po_page += 1

            if len(suppliers_seen) == 1:
                single_source_components.append((comp, list(suppliers_seen)[0]))

        # ── Step 8: Gather details for single-source components ──────────
        mitigation = []
        country_risk_cache = {}

        for comp, supplier_id in single_source_components:
            cid = comp["component_id"]

            # Get supplier details
            sup = json.loads(call_tool("get_supplier_details", supplier_id=supplier_id)["content"][0]["text"])
            country = sup["country"]

            # Get country risk (with caching)
            if country not in country_risk_cache:
                cr = json.loads(call_tool("get_country_risk", country=country))
                country_risk_cache[country] = float(cr.get("risk_index", 50.0))
            geo_risk = country_risk_cache[country]

            # Check inventory
            inv = json.loads(call_tool("check_inventory", component_id=cid))
            coverage_days = float(inv.get("coverage_days", 999.0))

            # Financial health from workspace
            fhs = financial_scores.get(supplier_id, 50.0)

            # Quality score from workspace
            qs = quality_scores.get(supplier_id, 50.0)

            # Compute risk factors
            financial_risk = 100.0 - fhs
            inventory_risk = max(0.0, min(100.0, (1.0 - coverage_days / buffer_days) * 100.0))
            quality_risk = 100.0 - qs

            composite = (
                weights["financial_health"] * financial_risk
                + weights["geopolitical_risk"] * geo_risk
                + weights["inventory_risk"] * inventory_risk
                + weights["quality_score"] * quality_risk
            )
            composite = round(composite, 2)

            # Risk tier
            if composite >= tiers_config["Critical"]:
                tier = "Critical"
            elif composite >= tiers_config["High"]:
                tier = "High"
            elif composite >= tiers_config["Medium"]:
                tier = "Medium"
            else:
                tier = "Low"

            # Alternate info
            alt_info = alternates.get(cid, {"num_known_alternates": 0, "qualification_status": "none_identified"})
            qual_status = alt_info["qualification_status"]

            # Recommended action
            action_map = {
                ("Critical", "none_identified"): "Immediate: identify and qualify new alternate suppliers",
                ("Critical", "under_evaluation"): "Immediate: fast-track alternate supplier qualification",
                ("Critical", "qualified"): "Immediate: activate qualified alternate supply",
                ("High", "none_identified"): "Within 30 days: source potential alternate suppliers",
                ("High", "under_evaluation"): "Within 30 days: accelerate qualification process",
                ("High", "qualified"): "Within 30 days: onboard qualified alternate supplier",
            }
            if tier == "Medium":
                rec_action = "Quarterly review: monitor risk indicators"
            elif tier == "Low":
                rec_action = "Annual review: standard monitoring"
            else:
                rec_action = action_map.get((tier, qual_status), "Review supplier risk")

            mitigation.append({
                "rank": 0,  # will be set after sorting
                "component_id": cid,
                "component_name": comp["component_name"] if "component_name" in comp else comp.get("name", ""),
                "category": comp["category"],
                "supplier_id": supplier_id,
                "supplier_name": sup["name"],
                "supplier_country": country,
                "financial_health_score": fhs,
                "geopolitical_risk_index": geo_risk,
                "inventory_coverage_days": coverage_days,
                "quality_audit_score": qs,
                "composite_risk_score": composite,
                "risk_tier": tier,
                "recommended_action": rec_action,
            })

        # Sort
        mitigation.sort(key=lambda x: (-x["composite_risk_score"], x["component_id"]))
        for i, entry in enumerate(mitigation):
            entry["rank"] = i + 1

        # ── Step 9: Write mitigation_list.csv ────────────────────────────
        csv_path = os.path.join(self.workspace, "mitigation_list.csv")
        columns = [
            "rank", "component_id", "component_name", "category",
            "supplier_id", "supplier_name", "supplier_country",
            "financial_health_score", "geopolitical_risk_index",
            "inventory_coverage_days", "quality_audit_score",
            "composite_risk_score", "risk_tier", "recommended_action",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for entry in mitigation:
                writer.writerow(entry)

        # ── Step 10: Construct action string ─────────────────────────────
        total_ss = len(mitigation)
        tier_counts = {}
        for entry in mitigation:
            t = entry["risk_tier"]
            tier_counts[t] = tier_counts.get(t, 0) + 1

        top5 = mitigation[:5]
        top5_lines = []
        for e in top5:
            top5_lines.append(
                f"  {e['rank']}. {e['component_id']} ({e['component_name']}) - "
                f"Supplier: {e['supplier_name']} ({e['supplier_country']}) - "
                f"Composite Risk: {e['composite_risk_score']} - Tier: {e['risk_tier']}"
            )

        action = (
            f"Single-source supplier risk analysis complete.\n\n"
            f"Total single-source components identified: {total_ss}\n\n"
            f"Risk tier breakdown:\n"
        )
        for tier_name in ["Critical", "High", "Medium", "Low"]:
            count = tier_counts.get(tier_name, 0)
            action += f"  {tier_name}: {count}\n"

        action += f"\nTop 5 highest-risk components:\n"
        action += "\n".join(top5_lines)
        action += f"\n\nThe full prioritized mitigation list has been saved to mitigation_list.csv."

        print(f"[verify] Tool calls made: {tool_call_count}")
        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls; need at least 15"

        return self.step(action)
