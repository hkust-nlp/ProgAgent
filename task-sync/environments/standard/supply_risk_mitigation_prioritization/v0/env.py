import sqlite3
import os
import json
import csv
import math
from typing import Tuple, Dict, List, Any
from datetime import datetime

try:
    import yaml
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml"])
    import yaml


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


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

    # -----------------------------------------------------------------------
    # Tool methods
    # -----------------------------------------------------------------------

    @tool(
        description="Returns a paginated list of all suppliers. Each entry includes supplier_id, name, region_id, primary_material_id, and status.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page. Maximum 20.",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_suppliers(self, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM suppliers")
        total = c.fetchone()[0]
        c.execute(
            "SELECT supplier_id, name, region_id, primary_material_id, status "
            "FROM suppliers ORDER BY supplier_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "suppliers": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description="Returns full details for a single supplier including contract dates.",
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "integer",
                    "description": "The supplier's unique ID.",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_supplier_details(self, supplier_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM suppliers WHERE supplier_id = ?", (supplier_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Supplier {supplier_id} not found"}
        return dict(row)

    @tool(
        description="Returns paginated delivery records for a specific supplier. Each record includes order_date, promised_date, actual_delivery_date, quantity_ordered, and quantity_delivered.",
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "integer",
                    "description": "The supplier's unique ID.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1.",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_delivery_history(self, supplier_id: int, page: int = 1):
        page_size = 20
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM delivery_records WHERE supplier_id = ?",
            (supplier_id,),
        )
        total = c.fetchone()[0]
        c.execute(
            "SELECT record_id, supplier_id, material_id, order_date, promised_date, "
            "actual_delivery_date, quantity_ordered, quantity_delivered "
            "FROM delivery_records WHERE supplier_id = ? "
            "ORDER BY record_id LIMIT ? OFFSET ?",
            (supplier_id, page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "records": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description="Returns information about a region including its name, country, continent, and base geopolitical risk score (0-100).",
        parameters={
            "type": "object",
            "properties": {
                "region_id": {
                    "type": "integer",
                    "description": "The region's unique ID.",
                },
            },
            "required": ["region_id"],
        },
    )
    def get_region_info(self, region_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM regions WHERE region_id = ?", (region_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Region {region_id} not found"}
        return dict(row)

    @tool(
        description="Returns details for a specific material including name, category, unit, base price, and criticality level (1-5).",
        parameters={
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "integer",
                    "description": "The material's unique ID.",
                },
            },
            "required": ["material_id"],
        },
    )
    def get_material_details(self, material_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM materials WHERE material_id = ?", (material_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Material {material_id} not found"}
        return dict(row)

    @tool(
        description="Returns quarterly consumption forecast data for a specific material. Each entry includes the period (e.g. '2026-Q1'), forecasted quantity, and confidence level.",
        parameters={
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "integer",
                    "description": "The material's unique ID.",
                },
            },
            "required": ["material_id"],
        },
    )
    def get_consumption_forecast(self, material_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT forecast_id, material_id, period, forecasted_qty, confidence_level "
            "FROM consumption_forecasts WHERE material_id = ? ORDER BY period",
            (material_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"forecasts": rows}

    @tool(
        description="Returns alternate supplier entries for a given primary supplier. Each entry includes the alternate supplier's ID, material ID, qualification status ('qualified', 'pending', or 'failed'), qualification date, and maximum capacity percentage.",
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "integer",
                    "description": "The primary supplier's unique ID.",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_alternate_suppliers(self, supplier_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT alt_id, primary_supplier_id, material_id, alt_supplier_id, "
            "qualification_status, qualification_date, max_capacity_pct "
            "FROM alternate_suppliers WHERE primary_supplier_id = ? ORDER BY alt_id",
            (supplier_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"alternates": rows}

    # -----------------------------------------------------------------------
    # Ground-truth computation (shared by step and verify-check)
    # -----------------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute the expected mitigation action list from DB + workspace files."""

        # --- Load config files ---
        with open(os.path.join(self.workspace, "risk_scoring_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "mitigation_playbook.json")) as f:
            playbook = json.load(f)
        crit_matrix = {}
        with open(os.path.join(self.workspace, "criticality_matrix.csv")) as f:
            for row in csv.DictReader(f):
                crit_matrix[int(row["criticality_level"])] = int(row["base_risk_score"])

        weights = config["weights"]
        tiers_cfg = config["risk_tiers"]
        late_thresh = config["late_delivery_threshold_days"]
        short_thresh = config["quantity_shortfall_threshold_pct"]

        # --- Load workspace data files ---
        audit_data: Dict[int, List[dict]] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("audit_report_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        sid = int(row["supplier_id"])
                        audit_data.setdefault(sid, []).append({
                            "quality_score": float(row["quality_score"]),
                            "compliance_flag": int(row["compliance_flag"]),
                        })

        regional_intel: Dict[int, dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("regional_intel_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for entry in json.load(f):
                        regional_intel[entry["region_id"]] = entry

        demand_adj: Dict[int, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("demand_adjustment_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                    for adj in data["adjustments"]:
                        demand_adj[adj["material_id"]] = adj["adjustment_factor"]

        financial: Dict[int, dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("supplier_financials_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                current: dict = {}
                for line in content.splitlines():
                    line = line.strip()
                    if not line:
                        if "Supplier ID" in current:
                            sid = int(current["Supplier ID"])
                            financial[sid] = {
                                "credit_rating": current.get("Credit Rating", "C"),
                                "debt_ratio": float(current.get("Debt Ratio", "0.5")),
                            }
                        current = {}
                        continue
                    if ":" in line:
                        key, val = line.split(":", 1)
                        current[key.strip()] = val.strip()
                # Handle last block without trailing blank line
                if "Supplier ID" in current:
                    sid = int(current["Supplier ID"])
                    financial[sid] = {
                        "credit_rating": current.get("Credit Rating", "C"),
                        "debt_ratio": float(current.get("Debt Ratio", "0.5")),
                    }

        # --- Query DB for ground truth ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT * FROM suppliers ORDER BY supplier_id")
        suppliers = [dict(r) for r in c.fetchall()]

        results = []
        for s in suppliers:
            sid = s["supplier_id"]
            rid = s["region_id"]
            mid = s["primary_material_id"]

            # -- delivery_performance --
            c.execute(
                "SELECT promised_date, actual_delivery_date, quantity_ordered, quantity_delivered "
                "FROM delivery_records WHERE supplier_id = ?",
                (sid,),
            )
            deliveries = c.fetchall()
            if deliveries:
                late = sum(
                    1 for d in deliveries
                    if (datetime.strptime(d[1], "%Y-%m-%d") - datetime.strptime(d[0], "%Y-%m-%d")).days > late_thresh
                )
                shortfall = sum(
                    1 for d in deliveries
                    if d[3] < d[2] * (1 - short_thresh / 100.0)
                )
                total = len(deliveries)
                delivery_risk = min(100.0, (late / total) * 60 + (shortfall / total) * 40)
            else:
                delivery_risk = 0.0

            # -- geopolitical_risk --
            c.execute("SELECT name, base_risk_score FROM regions WHERE region_id = ?", (rid,))
            reg = c.fetchone()
            region_name = reg[0]
            base_risk = reg[1]
            intel = regional_intel.get(rid, {})
            sanctions = intel.get("sanctions_active", False)
            restriction = intel.get("trade_restriction_level", 0)
            trend = intel.get("political_stability_trend", "stable")
            trend_mod = {"improving": -5, "stable": 0, "declining": 10}.get(trend, 0)
            geo_risk = min(100.0, base_risk + (20 if sanctions else 0) + restriction * 5 + trend_mod)

            # -- material_criticality --
            c.execute("SELECT name, criticality_level FROM materials WHERE material_id = ?", (mid,))
            mat = c.fetchone()
            mat_name = mat[0]
            crit_level = mat[1]
            crit_base = crit_matrix.get(crit_level, 45)

            c.execute(
                "SELECT period, forecasted_qty FROM consumption_forecasts "
                "WHERE material_id = ? ORDER BY period",
                (mid,),
            )
            forecasts = c.fetchall()
            if len(forecasts) >= 2:
                first_qty = forecasts[0][1]
                last_qty = forecasts[-1][1]
                demand_growth = (last_qty - first_qty) / first_qty if first_qty > 0 else 0.0
            else:
                demand_growth = 0.0
            adj = demand_adj.get(mid, 1.0)
            material_risk = min(100.0, crit_base + max(0.0, demand_growth) * adj * 50)

            # -- supply_alternative --
            c.execute(
                "SELECT qualification_status FROM alternate_suppliers "
                "WHERE primary_supplier_id = ?",
                (sid,),
            )
            alts = c.fetchall()
            qualified = sum(1 for a in alts if a[0] == "qualified")
            if qualified == 0:
                alt_risk = 100.0
            elif qualified == 1:
                alt_risk = 60.0
            elif qualified == 2:
                alt_risk = 30.0
            else:
                alt_risk = 10.0

            # -- quality_compliance --
            audits = audit_data.get(sid, [])
            if audits:
                avg_q = sum(a["quality_score"] for a in audits) / len(audits)
                has_viol = any(a["compliance_flag"] == 0 for a in audits)
                quality_risk = min(100.0, (100 - avg_q) + (15 if has_viol else 0))
            else:
                quality_risk = 50.0

            # -- financial_health --
            fin = financial.get(sid, None)
            if fin:
                credit_map = {"A": 10, "B": 30, "C": 60, "D": 90}
                fin_base = credit_map.get(fin["credit_rating"], 50)
                fin_risk = min(100.0, fin_base + fin["debt_ratio"] * 20)
            else:
                fin_risk = 50.0

            # -- composite --
            composite = (
                delivery_risk * weights["delivery_performance"]
                + geo_risk * weights["geopolitical_risk"]
                + material_risk * weights["material_criticality"]
                + alt_risk * weights["supply_alternative"]
                + quality_risk * weights["quality_compliance"]
                + fin_risk * weights["financial_health"]
            )
            composite = round(composite, 2)

            # -- risk tier --
            if composite >= tiers_cfg["critical"]["min_score"]:
                tier = "Critical"
                urgency = tiers_cfg["critical"]["urgency_days"]
            elif composite >= tiers_cfg["high"]["min_score"]:
                tier = "High"
                urgency = tiers_cfg["high"]["urgency_days"]
            elif composite >= tiers_cfg["medium"]["min_score"]:
                tier = "Medium"
                urgency = tiers_cfg["medium"]["urgency_days"]
            else:
                tier = "Low"
                urgency = 0

            # -- primary risk factor: highest weighted contribution, ties alphabetical --
            components = {
                "delivery_performance": delivery_risk * weights["delivery_performance"],
                "geopolitical_risk": geo_risk * weights["geopolitical_risk"],
                "material_criticality": material_risk * weights["material_criticality"],
                "supply_alternative": alt_risk * weights["supply_alternative"],
                "quality_compliance": quality_risk * weights["quality_compliance"],
                "financial_health": fin_risk * weights["financial_health"],
            }
            primary = sorted(components.keys(), key=lambda k: (-components[k], k))[0]

            # -- mitigation action --
            if tier != "Low":
                action_text = playbook["actions"][primary][tier.lower()]
            else:
                action_text = ""

            results.append({
                "supplier_id": sid,
                "supplier_name": s["name"],
                "region_name": region_name,
                "primary_material": mat_name,
                "composite_risk_score": composite,
                "risk_tier": tier,
                "primary_risk_factor": primary,
                "mitigation_action": action_text,
                "urgency_days": urgency,
            })

        conn.close()

        # Sort: composite desc, then supplier_id asc for ties
        results.sort(key=lambda x: (-x["composite_risk_score"], x["supplier_id"]))
        actionable = [r for r in results if r["risk_tier"] in ("Critical", "High", "Medium")]

        # Risk distribution
        dist = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
        for r in results:
            dist[r["risk_tier"]] += 1

        # Top risk factors by frequency among actionable, ties alphabetical
        factor_counts: Dict[str, int] = {}
        for r in actionable:
            factor_counts[r["primary_risk_factor"]] = factor_counts.get(r["primary_risk_factor"], 0) + 1
        top_factors = sorted(factor_counts.keys(), key=lambda k: (-factor_counts[k], k))

        return {
            "all_results": results,
            "actionable": actionable,
            "distribution": dist,
            "top_factors": top_factors,
            "total_assessed": len(results),
        }

    # -----------------------------------------------------------------------
    # Step: evaluate task completion
    # -----------------------------------------------------------------------

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        gt = self._compute_ground_truth()
        actionable = gt["actionable"]
        dist = gt["distribution"]
        top_factors = gt["top_factors"]
        total_assessed = gt["total_assessed"]

        eval_criteria: Dict[str, dict] = {}
        EXPECTED_COLS = [
            "rank", "supplier_id", "supplier_name", "region_name",
            "primary_material", "composite_risk_score", "risk_tier",
            "primary_risk_factor", "mitigation_action", "urgency_days",
        ]

        # ---- Criterion 1: File existence & structure (15 pts) ----
        c1 = 0
        c1_reason = ""
        csv_path = os.path.join(self.workspace, "mitigation_actions.csv")
        json_path = os.path.join(self.workspace, "risk_summary.json")
        agent_rows: list = []
        csv_valid = False

        if os.path.exists(csv_path):
            c1 += 5
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    headers = reader.fieldnames or []
                    if all(col in headers for col in EXPECTED_COLS):
                        c1 += 5
                        csv_valid = True
                        agent_rows = list(reader)
                    else:
                        c1_reason += f"CSV missing columns. Expected {EXPECTED_COLS}, got {headers}. "
            except Exception as e:
                c1_reason += f"CSV parse error: {e}. "
        else:
            c1_reason += "mitigation_actions.csv not found. "

        if os.path.exists(json_path):
            c1 += 5
        else:
            c1_reason += "risk_summary.json not found. "

        eval_criteria["file_structure"] = {
            "passed": c1 == 15,
            "score": c1,
            "max_score": 15,
            "reason": c1_reason if c1 < 15 else "",
        }

        # ---- Criterion 2: Supplier coverage (20 pts) ----
        c2 = 0
        c2_reason = ""
        expected_ids = {r["supplier_id"] for r in actionable}
        if csv_valid and agent_rows:
            try:
                agent_ids = {int(r["supplier_id"]) for r in agent_rows}
            except (ValueError, KeyError):
                agent_ids = set()
            missing = expected_ids - agent_ids
            extra = agent_ids - expected_ids
            if not missing and not extra:
                c2 = 20
            else:
                coverage = max(0, len(expected_ids) - len(missing) - len(extra)) / max(len(expected_ids), 1)
                c2 = int(round(coverage * 20))
                if missing:
                    c2_reason += f"Missing supplier IDs: {sorted(missing)[:5]}... "
                if extra:
                    c2_reason += f"Extra supplier IDs: {sorted(extra)[:5]}... "
        else:
            c2_reason = "Cannot evaluate: CSV invalid or empty."

        eval_criteria["supplier_coverage"] = {
            "passed": c2 == 20,
            "score": c2,
            "max_score": 20,
            "reason": c2_reason if c2 < 20 else "",
        }

        # ---- Criterion 3: Risk score accuracy (20 pts) ----
        c3 = 0
        c3_reason = ""
        if csv_valid and agent_rows and actionable:
            expected_map = {r["supplier_id"]: r["composite_risk_score"] for r in actionable}
            correct = 0
            total_check = 0
            for ar in agent_rows:
                try:
                    sid = int(ar["supplier_id"])
                    agent_score = round(float(ar["composite_risk_score"]), 2)
                except (ValueError, KeyError):
                    continue
                if sid in expected_map:
                    total_check += 1
                    if abs(agent_score - expected_map[sid]) <= 2.0:
                        correct += 1
            if total_check > 0:
                c3 = int(round(correct / total_check * 20))
            if c3 < 20:
                c3_reason = f"{correct}/{total_check} scores within tolerance."
        else:
            c3_reason = "Cannot evaluate: CSV invalid."

        eval_criteria["risk_score_accuracy"] = {
            "passed": c3 == 20,
            "score": c3,
            "max_score": 20,
            "reason": c3_reason if c3 < 20 else "",
        }

        # ---- Criterion 4: Risk tier & primary factor (15 pts) ----
        c4 = 0
        c4_reason = ""
        if csv_valid and agent_rows and actionable:
            expected_tier_map = {r["supplier_id"]: r["risk_tier"] for r in actionable}
            expected_factor_map = {r["supplier_id"]: r["primary_risk_factor"] for r in actionable}
            tier_correct = 0
            factor_correct = 0
            total_check = 0
            for ar in agent_rows:
                try:
                    sid = int(ar["supplier_id"])
                except (ValueError, KeyError):
                    continue
                if sid in expected_tier_map:
                    total_check += 1
                    if ar.get("risk_tier", "").strip() == expected_tier_map[sid]:
                        tier_correct += 1
                    if ar.get("primary_risk_factor", "").strip() == expected_factor_map[sid]:
                        factor_correct += 1
            if total_check > 0:
                tier_pct = tier_correct / total_check
                factor_pct = factor_correct / total_check
                c4 = int(round((tier_pct * 8 + factor_pct * 7)))
            if c4 < 15:
                c4_reason = f"Tier: {tier_correct}/{total_check}, Factor: {factor_correct}/{total_check}."
        else:
            c4_reason = "Cannot evaluate: CSV invalid."

        eval_criteria["tier_and_factor"] = {
            "passed": c4 == 15,
            "score": c4,
            "max_score": 15,
            "reason": c4_reason if c4 < 15 else "",
        }

        # ---- Criterion 5: Mitigation actions (10 pts) ----
        c5 = 0
        c5_reason = ""
        if csv_valid and agent_rows and actionable:
            expected_action_map = {r["supplier_id"]: r["mitigation_action"] for r in actionable}
            correct = 0
            total_check = 0
            for ar in agent_rows:
                try:
                    sid = int(ar["supplier_id"])
                except (ValueError, KeyError):
                    continue
                if sid in expected_action_map:
                    total_check += 1
                    if ar.get("mitigation_action", "").strip() == expected_action_map[sid]:
                        correct += 1
            if total_check > 0:
                c5 = int(round(correct / total_check * 10))
            if c5 < 10:
                c5_reason = f"{correct}/{total_check} actions matched."
        else:
            c5_reason = "Cannot evaluate: CSV invalid."

        eval_criteria["mitigation_actions"] = {
            "passed": c5 == 10,
            "score": c5,
            "max_score": 10,
            "reason": c5_reason if c5 < 10 else "",
        }

        # ---- Criterion 6: Sorting & ranking (10 pts) ----
        c6 = 0
        c6_reason = ""
        if csv_valid and agent_rows and actionable:
            # Check sort order
            try:
                agent_scores = [round(float(r["composite_risk_score"]), 2) for r in agent_rows]
                agent_sids = [int(r["supplier_id"]) for r in agent_rows]
                is_sorted = True
                for i in range(len(agent_scores) - 1):
                    if agent_scores[i] < agent_scores[i + 1]:
                        is_sorted = False
                        break
                    if agent_scores[i] == agent_scores[i + 1] and agent_sids[i] > agent_sids[i + 1]:
                        is_sorted = False
                        break
                if is_sorted:
                    c6 += 5
                else:
                    c6_reason += "Not sorted correctly. "

                # Check rank column is 1-based sequential
                try:
                    ranks = [int(r["rank"]) for r in agent_rows]
                    expected_ranks = list(range(1, len(agent_rows) + 1))
                    if ranks == expected_ranks:
                        c6 += 3
                    else:
                        c6_reason += "Rank column not sequential 1-based. "
                except (ValueError, KeyError):
                    c6_reason += "Rank column missing or invalid. "

                # Check score precision (2 decimal places)
                format_ok = True
                for r in agent_rows:
                    score_str = r.get("composite_risk_score", "")
                    if "." in score_str:
                        decimals = len(score_str.split(".")[-1])
                        if decimals != 2:
                            format_ok = False
                            break
                    else:
                        format_ok = False
                        break
                if format_ok:
                    c6 += 2
                else:
                    c6_reason += "Scores not formatted to 2 decimal places. "
            except (ValueError, KeyError) as e:
                c6_reason += f"Parse error: {e}. "
        else:
            c6_reason = "Cannot evaluate: CSV invalid."

        eval_criteria["sorting_ranking"] = {
            "passed": c6 == 10,
            "score": c6,
            "max_score": 10,
            "reason": c6_reason if c6 < 10 else "",
        }

        # ---- Criterion 7: Risk summary JSON (10 pts) ----
        c7 = 0
        c7_reason = ""
        if os.path.exists(json_path):
            try:
                with open(json_path) as f:
                    summary = json.load(f)
                # Check total_suppliers_assessed
                if summary.get("total_suppliers_assessed") == total_assessed:
                    c7 += 3
                else:
                    c7_reason += f"total_suppliers_assessed: expected {total_assessed}, got {summary.get('total_suppliers_assessed')}. "

                # Check risk_distribution
                agent_dist = summary.get("risk_distribution", {})
                if all(agent_dist.get(k) == v for k, v in dist.items()):
                    c7 += 4
                else:
                    c7_reason += f"risk_distribution mismatch. Expected {dist}, got {agent_dist}. "

                # Check top_risk_factors
                agent_factors = summary.get("top_risk_factors", [])
                if agent_factors == top_factors:
                    c7 += 3
                else:
                    c7_reason += f"top_risk_factors mismatch. Expected {top_factors}, got {agent_factors}. "
            except Exception as e:
                c7_reason += f"JSON parse error: {e}. "
        else:
            c7_reason = "risk_summary.json not found."

        eval_criteria["risk_summary"] = {
            "passed": c7 == 10,
            "score": c7,
            "max_score": 10,
            "reason": c7_reason if c7 < 10 else "",
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # -----------------------------------------------------------------------
    # Verify: self-test using only tools + workspace files
    # -----------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        # --- 1. Read configuration files ---
        with open(os.path.join(self.workspace, "risk_scoring_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "mitigation_playbook.json")) as f:
            playbook = json.load(f)
        crit_matrix = {}
        with open(os.path.join(self.workspace, "criticality_matrix.csv")) as f:
            for row in csv.DictReader(f):
                crit_matrix[int(row["criticality_level"])] = int(row["base_risk_score"])

        weights = config["weights"]
        tiers_cfg = config["risk_tiers"]
        late_thresh = config["late_delivery_threshold_days"]
        short_thresh = config["quantity_shortfall_threshold_pct"]

        # --- 2. Read workspace data files ---
        audit_data: Dict[int, List[dict]] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("audit_report_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        sid = int(row["supplier_id"])
                        audit_data.setdefault(sid, []).append({
                            "quality_score": float(row["quality_score"]),
                            "compliance_flag": int(row["compliance_flag"]),
                        })

        regional_intel: Dict[int, dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("regional_intel_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for entry in json.load(f):
                        regional_intel[entry["region_id"]] = entry

        demand_adj: Dict[int, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("demand_adjustment_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                    for adj in data["adjustments"]:
                        demand_adj[adj["material_id"]] = adj["adjustment_factor"]

        financial: Dict[int, dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("supplier_financials_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                current: dict = {}
                for line in content.splitlines():
                    line = line.strip()
                    if not line:
                        if "Supplier ID" in current:
                            sid_val = int(current["Supplier ID"])
                            financial[sid_val] = {
                                "credit_rating": current.get("Credit Rating", "C"),
                                "debt_ratio": float(current.get("Debt Ratio", "0.5")),
                            }
                        current = {}
                        continue
                    if ":" in line:
                        key, val = line.split(":", 1)
                        current[key.strip()] = val.strip()
                if "Supplier ID" in current:
                    sid_val = int(current["Supplier ID"])
                    financial[sid_val] = {
                        "credit_rating": current.get("Credit Rating", "C"),
                        "debt_ratio": float(current.get("Debt Ratio", "0.5")),
                    }

        # --- 3. Gather all suppliers via tools ---
        all_suppliers = []
        page = 1
        while True:
            result = self.tools["list_suppliers"](page=page, page_size=20)
            all_suppliers.extend(result["suppliers"])
            if not result["has_more"]:
                break
            page += 1

        # --- 4. For each supplier, compute risk ---
        region_cache: dict = {}
        material_cache: dict = {}
        forecast_cache: dict = {}
        results = []

        for supplier in all_suppliers:
            sid = supplier["supplier_id"]
            rid = supplier["region_id"]
            mid = supplier["primary_material_id"]

            # Delivery history (paginated)
            deliveries = []
            dpage = 1
            while True:
                dr = self.tools["get_delivery_history"](supplier_id=sid, page=dpage)
                deliveries.extend(dr["records"])
                if not dr["has_more"]:
                    break
                dpage += 1

            # delivery risk
            if deliveries:
                late = sum(
                    1 for d in deliveries
                    if (datetime.strptime(d["actual_delivery_date"], "%Y-%m-%d")
                        - datetime.strptime(d["promised_date"], "%Y-%m-%d")).days > late_thresh
                )
                shortfall = sum(
                    1 for d in deliveries
                    if d["quantity_delivered"] < d["quantity_ordered"] * (1 - short_thresh / 100.0)
                )
                total = len(deliveries)
                delivery_risk = min(100.0, (late / total) * 60 + (shortfall / total) * 40)
            else:
                delivery_risk = 0.0

            # Region info
            if rid not in region_cache:
                region_cache[rid] = self.tools["get_region_info"](region_id=rid)
            region = region_cache[rid]

            # geo risk
            base_risk = region["base_risk_score"]
            intel = regional_intel.get(rid, {})
            sanctions = intel.get("sanctions_active", False)
            restriction = intel.get("trade_restriction_level", 0)
            trend = intel.get("political_stability_trend", "stable")
            trend_mod = {"improving": -5, "stable": 0, "declining": 10}.get(trend, 0)
            geo_risk = min(100.0, base_risk + (20 if sanctions else 0) + restriction * 5 + trend_mod)

            # Material info
            if mid not in material_cache:
                material_cache[mid] = self.tools["get_material_details"](material_id=mid)
            material = material_cache[mid]

            # Forecast
            if mid not in forecast_cache:
                forecast_cache[mid] = self.tools["get_consumption_forecast"](material_id=mid)
            forecasts_data = forecast_cache[mid]

            # material risk
            crit_level = material["criticality_level"]
            crit_base = crit_matrix.get(crit_level, 45)
            sorted_fc = sorted(forecasts_data["forecasts"], key=lambda x: x["period"])
            if len(sorted_fc) >= 2:
                first_qty = sorted_fc[0]["forecasted_qty"]
                last_qty = sorted_fc[-1]["forecasted_qty"]
                demand_growth = (last_qty - first_qty) / first_qty if first_qty > 0 else 0.0
            else:
                demand_growth = 0.0
            adj = demand_adj.get(mid, 1.0)
            material_risk = min(100.0, crit_base + max(0.0, demand_growth) * adj * 50)

            # Alternate suppliers
            alts_data = self.tools["get_alternate_suppliers"](supplier_id=sid)
            qualified = sum(1 for a in alts_data["alternates"] if a["qualification_status"] == "qualified")
            if qualified == 0:
                alt_risk = 100.0
            elif qualified == 1:
                alt_risk = 60.0
            elif qualified == 2:
                alt_risk = 30.0
            else:
                alt_risk = 10.0

            # Quality
            audits = audit_data.get(sid, [])
            if audits:
                avg_q = sum(a["quality_score"] for a in audits) / len(audits)
                has_viol = any(a["compliance_flag"] == 0 for a in audits)
                quality_risk = min(100.0, (100 - avg_q) + (15 if has_viol else 0))
            else:
                quality_risk = 50.0

            # Financial
            fin = financial.get(sid, None)
            if fin:
                credit_map = {"A": 10, "B": 30, "C": 60, "D": 90}
                fin_base = credit_map.get(fin["credit_rating"], 50)
                fin_risk = min(100.0, fin_base + fin["debt_ratio"] * 20)
            else:
                fin_risk = 50.0

            # Composite
            composite = (
                delivery_risk * weights["delivery_performance"]
                + geo_risk * weights["geopolitical_risk"]
                + material_risk * weights["material_criticality"]
                + alt_risk * weights["supply_alternative"]
                + quality_risk * weights["quality_compliance"]
                + fin_risk * weights["financial_health"]
            )
            composite = round(composite, 2)

            # Tier
            if composite >= tiers_cfg["critical"]["min_score"]:
                tier = "Critical"
                urgency = tiers_cfg["critical"]["urgency_days"]
            elif composite >= tiers_cfg["high"]["min_score"]:
                tier = "High"
                urgency = tiers_cfg["high"]["urgency_days"]
            elif composite >= tiers_cfg["medium"]["min_score"]:
                tier = "Medium"
                urgency = tiers_cfg["medium"]["urgency_days"]
            else:
                tier = "Low"
                urgency = 0

            # Primary risk factor
            components = {
                "delivery_performance": delivery_risk * weights["delivery_performance"],
                "geopolitical_risk": geo_risk * weights["geopolitical_risk"],
                "material_criticality": material_risk * weights["material_criticality"],
                "supply_alternative": alt_risk * weights["supply_alternative"],
                "quality_compliance": quality_risk * weights["quality_compliance"],
                "financial_health": fin_risk * weights["financial_health"],
            }
            primary = sorted(components.keys(), key=lambda k: (-components[k], k))[0]

            # Mitigation action
            if tier != "Low":
                action_text = playbook["actions"][primary][tier.lower()]
            else:
                action_text = ""

            results.append({
                "supplier_id": sid,
                "supplier_name": supplier["name"],
                "region_name": region["name"],
                "primary_material": material["name"],
                "composite_risk_score": composite,
                "risk_tier": tier,
                "primary_risk_factor": primary,
                "mitigation_action": action_text,
                "urgency_days": urgency,
            })

        # --- 5. Sort and filter ---
        results.sort(key=lambda x: (-x["composite_risk_score"], x["supplier_id"]))
        actionable = [r for r in results if r["risk_tier"] in ("Critical", "High", "Medium")]

        # --- 6. Write mitigation_actions.csv ---
        csv_path = os.path.join(self.workspace, "mitigation_actions.csv")
        with open(csv_path, "w", newline="") as f:
            fieldnames = [
                "rank", "supplier_id", "supplier_name", "region_name",
                "primary_material", "composite_risk_score", "risk_tier",
                "primary_risk_factor", "mitigation_action", "urgency_days",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for i, r in enumerate(actionable):
                row = dict(r)
                row["rank"] = i + 1
                row["composite_risk_score"] = f"{r['composite_risk_score']:.2f}"
                writer.writerow(row)

        # --- 7. Write risk_summary.json ---
        dist = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
        for r in results:
            dist[r["risk_tier"]] += 1

        factor_counts: Dict[str, int] = {}
        for r in actionable:
            factor_counts[r["primary_risk_factor"]] = factor_counts.get(r["primary_risk_factor"], 0) + 1
        top_factors = sorted(factor_counts.keys(), key=lambda k: (-factor_counts[k], k))

        summary = {
            "total_suppliers_assessed": len(results),
            "risk_distribution": dist,
            "top_risk_factors": top_factors,
            "assessment_date": "2026-04-22",
        }
        json_path = os.path.join(self.workspace, "risk_summary.json")
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2)

        # --- 8. Construct action string ---
        action = "Supply Risk Assessment Complete.\n\n"
        action += f"Total suppliers assessed: {len(results)}\n"
        action += f"Critical: {dist['Critical']}, High: {dist['High']}, "
        action += f"Medium: {dist['Medium']}, Low: {dist['Low']}\n\n"
        action += "Top 5 highest-risk suppliers:\n"
        for r in actionable[:5]:
            action += (
                f"- {r['supplier_name']} (ID: {r['supplier_id']}): "
                f"Score {r['composite_risk_score']:.2f}, Tier: {r['risk_tier']}, "
                f"Primary Factor: {r['primary_risk_factor']}\n"
                f"  Action: {r['mitigation_action']}\n"
            )

        return self.step(action)
