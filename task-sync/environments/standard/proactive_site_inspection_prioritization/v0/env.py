"""
Environment for construction site inspection prioritization task.
Provides tools for querying permits, contractors, violations, zones, and complaints.
Evaluates the agent's ability to generate a prioritized inspection list with risk scores.
"""

import sqlite3
import os
import json
import csv
import re
import math
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
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

    # ═══════════════════════════════════════════════════════════════
    #  Tool methods
    # ═══════════════════════════════════════════════════════════════

    @tool(
        description="Search construction permits with optional filters. Returns paginated results (max 20 per page). Each result includes permit_id, site_address, contractor_id, zone_id, permit_type, submission_date, status, project_value, num_stories, and square_footage.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by permit status (e.g. 'active', 'pending_review', 'approved', 'completed', 'rejected', 'suspended')"
                },
                "permit_type": {
                    "type": "string",
                    "description": "Filter by permit type (e.g. 'new_construction', 'renovation', 'demolition')"
                },
                "zone_id": {
                    "type": "string",
                    "description": "Filter by zone ID (e.g. 'Z-0001')"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based, default 1)"
                }
            },
            "required": []
        }
    )
    def search_permits(self, status: str = None, permit_type: str = None,
                       zone_id: str = None, page: int = 1) -> dict:
        page_size = 20
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        query = "SELECT * FROM permits WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if permit_type:
            query += " AND permit_type = ?"
            params.append(permit_type)
        if zone_id:
            query += " AND zone_id = ?"
            params.append(zone_id)
        query += " ORDER BY permit_id"

        c.execute(query, params)
        all_rows = [dict(r) for r in c.fetchall()]
        conn.close()

        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = all_rows[start:end]

        return {
            "results": page_rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if total > 0 else 1,
        }

    @tool(
        description="Get detailed information for a specific permit by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "permit_id": {
                    "type": "string",
                    "description": "The permit ID (e.g. 'P-0001')"
                }
            },
            "required": ["permit_id"]
        }
    )
    def get_permit_details(self, permit_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM permits WHERE permit_id = ?", (permit_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Permit {permit_id} not found"}

    @tool(
        description="Get contractor information by contractor ID. Returns company_name, license_number, license_expiry, insurance_valid, years_in_business, and specialty.",
        parameters={
            "type": "object",
            "properties": {
                "contractor_id": {
                    "type": "string",
                    "description": "The contractor ID (e.g. 'C-0001')"
                }
            },
            "required": ["contractor_id"]
        }
    )
    def get_contractor(self, contractor_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM contractors WHERE contractor_id = ?", (contractor_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Contractor {contractor_id} not found"}

    @tool(
        description="Get violation records for a specific contractor. Returns all violations including violation_id, violation_type, severity, violation_date, resolved status, and fine_amount.",
        parameters={
            "type": "object",
            "properties": {
                "contractor_id": {
                    "type": "string",
                    "description": "The contractor ID (e.g. 'C-0001')"
                }
            },
            "required": ["contractor_id"]
        }
    )
    def get_violations(self, contractor_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM violations WHERE contractor_id = ? ORDER BY violation_date DESC",
                  (contractor_id,))
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"contractor_id": contractor_id, "violations": rows, "count": len(rows)}

    @tool(
        description="Get zone information by zone ID. Returns zone_name, zone_type, district, and max_building_height.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "The zone ID (e.g. 'Z-0001')"
                }
            },
            "required": ["zone_id"]
        }
    )
    def get_zone(self, zone_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM zones WHERE zone_id = ?", (zone_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Zone {zone_id} not found"}

    @tool(
        description="Search complaints linked to a specific permit. Returns paginated results (max 20 per page) with complaint_id, complaint_type, complaint_date, severity, status, and reporter_type.",
        parameters={
            "type": "object",
            "properties": {
                "permit_id": {
                    "type": "string",
                    "description": "The permit ID to search complaints for (e.g. 'P-0001')"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based, default 1)"
                }
            },
            "required": ["permit_id"]
        }
    )
    def search_complaints(self, permit_id: str, page: int = 1) -> dict:
        page_size = 20
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM complaints WHERE permit_id = ? ORDER BY complaint_date DESC",
                  (permit_id,))
        all_rows = [dict(r) for r in c.fetchall()]
        conn.close()

        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = all_rows[start:end]

        return {
            "results": page_rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if total > 0 else 1,
        }

    @tool(
        description="List all available permit statuses and their counts in the database.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def list_permit_statuses(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT status, COUNT(*) as count FROM permits GROUP BY status ORDER BY status")
        rows = c.fetchall()
        conn.close()
        return {"statuses": [{"status": r[0], "count": r[1]} for r in rows]}

    @tool(
        description="List all zones with their basic information. Returns zone_id, zone_name, zone_type, and district for each zone.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based, default 1). 25 zones per page."
                }
            },
            "required": []
        }
    )
    def list_zones(self, page: int = 1) -> dict:
        page_size = 25
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT zone_id, zone_name, zone_type, district FROM zones ORDER BY zone_id")
        all_rows = [dict(r) for r in c.fetchall()]
        conn.close()

        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "results": all_rows[start:end],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if total > 0 else 1,
        }

    # ═══════════════════════════════════════════════════════════════
    #  Evaluation
    # ═══════════════════════════════════════════════════════════════

    def _load_config(self):
        """Load risk_config.yaml from workspace."""
        import yaml
        config_path = os.path.join(self.workspace, "risk_config.yaml")
        with open(config_path, "r") as f:
            return yaml.safe_load(f)

    def _load_zone_hazards(self):
        """Load zone hazard overlay data."""
        hazards = {}
        path = os.path.join(self.workspace, "zone_hazard_overlay.csv")
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                hazards[row["zone_id"]] = {
                    "flood_risk": float(row["flood_risk"]),
                    "seismic_factor": float(row["seismic_factor"]),
                    "environmental_sensitivity": float(row["environmental_sensitivity"]),
                    "infrastructure_proximity": float(row["infrastructure_proximity"]),
                }
        return hazards

    def _load_site_surveys(self):
        """Load all site survey data from workspace."""
        surveys = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("site_survey_batch_") and fname.endswith(".csv"):
                path = os.path.join(self.workspace, fname)
                with open(path, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        surveys[row["permit_id"]] = {
                            "structural_score": float(row["structural_score"]),
                            "safety_score": float(row["safety_score"]),
                            "environmental_score": float(row["environmental_score"]),
                        }
        return surveys

    def _load_complaint_details(self):
        """Load all complaint detail data from workspace."""
        details = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("complaint_detail_") and fname.endswith(".json"):
                path = os.path.join(self.workspace, fname)
                with open(path, "r") as f:
                    records = json.load(f)
                    for r in records:
                        details[r["complaint_id"]] = {
                            "escalation_flag": r["escalation_flag"],
                        }
        return details

    def _load_contractor_audits(self):
        """Load all contractor audit data from workspace."""
        audits = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("contractor_audit_") and fname.endswith(".txt"):
                path = os.path.join(self.workspace, fname)
                with open(path, "r") as f:
                    content = f.read()
                blocks = content.split("=" * 50)
                for block in blocks:
                    block = block.strip()
                    if not block or "Contractor ID:" not in block:
                        continue
                    cid_match = re.search(r"Contractor ID:\s*(\S+)", block)
                    score_match = re.search(r"Safety Audit Score:\s*([\d.]+)", block)
                    if cid_match and score_match:
                        audits[cid_match.group(1)] = {
                            "safety_audit_score": float(score_match.group(1)),
                        }
        return audits

    def _compute_ground_truth(self):
        """Compute the complete ground truth inspection priority list."""
        config = self._load_config()
        zone_hazards = self._load_zone_hazards()
        site_surveys = self._load_site_surveys()
        complaint_details = self._load_complaint_details()
        contractor_audits = self._load_contractor_audits()

        ref_date = datetime.strptime(config["reference_date"], "%Y-%m-%d")
        weights = config["risk_weights"]
        sev_mult = {int(k): v for k, v in config["severity_multipliers"].items()}
        value_tiers = config["project_value_tiers"]
        risk_tiers = config["risk_tiers"]

        # Query all inspectable permits from DB
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT * FROM permits WHERE status IN ('active', 'pending_review') ORDER BY permit_id")
        permits = [dict(r) for r in c.fetchall()]

        results = []
        for p in permits:
            pid = p["permit_id"]
            cid = p["contractor_id"]
            zid = p["zone_id"]

            # Get contractor
            c.execute("SELECT * FROM contractors WHERE contractor_id = ?", (cid,))
            contractor = dict(c.fetchone())

            # Get violations for contractor
            c.execute("SELECT * FROM violations WHERE contractor_id = ?", (cid,))
            violations = [dict(r) for r in c.fetchall()]

            # Get complaints for permit
            c.execute("SELECT * FROM complaints WHERE permit_id = ?", (pid,))
            complaints = [dict(r) for r in c.fetchall()]

            # 1. Violation history score
            violation_score = 0
            for v in violations:
                sev = v["severity"]
                base = config["violation_base_score"] * sev_mult.get(sev, 0.5)
                if not v["resolved"]:
                    base *= config["unresolved_violation_multiplier"]
                v_date = datetime.strptime(v["violation_date"], "%Y-%m-%d")
                if (ref_date - v_date).days <= config["recent_violation_days"]:
                    base += config["recent_violation_bonus"]
                violation_score += base
            violation_score = min(violation_score, config["max_violation_score"])

            # 2. Zone hazard score
            zh = zone_hazards.get(zid, {"flood_risk": 50, "seismic_factor": 50,
                                         "environmental_sensitivity": 50,
                                         "infrastructure_proximity": 50})
            zone_hazard_score = (zh["flood_risk"] + zh["seismic_factor"] +
                                 zh["environmental_sensitivity"] + zh["infrastructure_proximity"]) / 4

            # 3. Complaint severity score
            complaint_score = 0
            for cm in complaints:
                sev = cm["severity"]
                base = config["complaint_base_score"] * sev_mult.get(sev, 0.5)
                # Check escalation flag from workspace
                if cm["complaint_id"] in complaint_details:
                    if complaint_details[cm["complaint_id"]]["escalation_flag"]:
                        base += config["escalated_complaint_bonus"]
                complaint_score += base
            complaint_score = min(complaint_score, config["max_complaint_score"])

            # 4. Project scale score
            pv = p["project_value"]
            project_scale_score = 20  # default low
            for tier in value_tiers:
                if tier["min_value"] <= pv < tier["max_value"]:
                    project_scale_score = tier["risk_score"]
                    break

            # 5. Contractor reliability score
            if cid in contractor_audits:
                contractor_reliability_score = 100 - contractor_audits[cid]["safety_audit_score"]
            else:
                contractor_reliability_score = 50

            # 6. Site condition score
            if pid in site_surveys:
                ss = site_surveys[pid]
                avg_survey = (ss["structural_score"] + ss["safety_score"] + ss["environmental_score"]) / 3
                site_condition_score = 100 - avg_survey
            else:
                site_condition_score = 50

            # Weighted sum
            components = {
                "violation_history": violation_score,
                "zone_hazard": zone_hazard_score,
                "complaint_severity": complaint_score,
                "project_scale": project_scale_score,
                "contractor_reliability": contractor_reliability_score,
                "site_condition": site_condition_score,
            }
            weighted = {k: weights[k] * v for k, v in components.items()}
            raw_score = sum(weighted.values())

            # License penalties
            license_expiry = datetime.strptime(contractor["license_expiry"], "%Y-%m-%d")
            if license_expiry < ref_date:
                raw_score += config["expired_license_penalty"]
            elif license_expiry < ref_date + timedelta(days=config["license_expiry_window_days"]):
                raw_score += config["expiring_license_penalty"]

            risk_score = round(min(100, raw_score), 2)

            # Risk tier
            risk_tier = "low"
            for rt in risk_tiers:
                if rt["name"] == "critical":
                    if risk_score >= rt["min_score"]:
                        risk_tier = rt["name"]
                else:
                    if rt["min_score"] <= risk_score < rt["max_score"]:
                        risk_tier = rt["name"]

            # Primary risk factors (top 2 by weighted contribution)
            sorted_factors = sorted(weighted.items(), key=lambda x: x[1], reverse=True)
            primary = "; ".join([f[0] for f in sorted_factors[:2]])

            results.append({
                "permit_id": pid,
                "site_address": p["site_address"],
                "contractor_name": contractor["company_name"],
                "risk_score": risk_score,
                "risk_tier": risk_tier,
                "primary_risk_factors": primary,
                "submission_date": p["submission_date"],
            })

        conn.close()

        # Sort: risk_score DESC, submission_date ASC, permit_id ASC
        results.sort(key=lambda x: (-x["risk_score"], x["submission_date"], x["permit_id"]))

        # Assign ranks
        for i, r in enumerate(results):
            r["rank"] = i + 1

        return results

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
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
        eval_criteria = {}

        # ── Criterion 1: CSV file exists with correct columns (15 pts) ──
        csv_path = os.path.join(self.workspace, "inspection_priority_list.csv")
        csv_exists = os.path.exists(csv_path)
        expected_cols = ["rank", "permit_id", "site_address", "contractor_name",
                         "risk_score", "risk_tier", "primary_risk_factors"]
        csv_correct_cols = False
        csv_rows = []
        if csv_exists:
            try:
                with open(csv_path, "r") as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in reader.fieldnames] if reader.fieldnames else []
                    csv_correct_cols = all(c in actual_cols for c in expected_cols)
                    csv_rows = [r for r in reader]
            except Exception:
                pass

        eval_criteria["csv_file_structure"] = {
            "passed": csv_exists and csv_correct_cols,
            "score": 15 if (csv_exists and csv_correct_cols) else (5 if csv_exists else 0),
            "max_score": 15,
            "reason": "" if (csv_exists and csv_correct_cols) else
                      ("Missing columns" if csv_exists else "File not found"),
        }

        # ── Criterion 2: Correct number of permits included (15 pts) ──
        expected_count = len(ground_truth)
        actual_count = len(csv_rows)
        count_correct = actual_count == expected_count
        eval_criteria["permit_count"] = {
            "passed": count_correct,
            "score": 15 if count_correct else (8 if abs(actual_count - expected_count) <= 2 else 0),
            "max_score": 15,
            "reason": "" if count_correct else f"Expected {expected_count}, got {actual_count}",
        }

        # ── Criterion 3: Risk scores accuracy (25 pts) ──
        gt_by_pid = {r["permit_id"]: r for r in ground_truth}
        score_matches = 0
        score_close = 0
        total_permits = len(ground_truth)
        for row in csv_rows:
            pid = row.get("permit_id", "").strip()
            if pid in gt_by_pid:
                try:
                    agent_score = float(row.get("risk_score", "0").strip())
                    gt_score = gt_by_pid[pid]["risk_score"]
                    if abs(agent_score - gt_score) < 0.01:
                        score_matches += 1
                    elif abs(agent_score - gt_score) < 1.0:
                        score_close += 1
                except (ValueError, TypeError):
                    pass

        if total_permits > 0:
            exact_pct = score_matches / total_permits
            close_pct = (score_matches + score_close) / total_permits
        else:
            exact_pct = 0
            close_pct = 0

        score_pts = 0
        if exact_pct >= 0.95:
            score_pts = 25
        elif exact_pct >= 0.80:
            score_pts = 20
        elif close_pct >= 0.80:
            score_pts = 15
        elif close_pct >= 0.50:
            score_pts = 10
        elif close_pct >= 0.25:
            score_pts = 5

        eval_criteria["risk_scores"] = {
            "passed": exact_pct >= 0.95,
            "score": score_pts,
            "max_score": 25,
            "reason": "" if exact_pct >= 0.95 else
                      f"Exact match: {score_matches}/{total_permits}, close: {score_close}/{total_permits}",
        }

        # ── Criterion 4: Correct ranking order (15 pts) ──
        gt_ranking = [r["permit_id"] for r in ground_truth]
        agent_ranking = [row.get("permit_id", "").strip() for row in csv_rows]

        if len(agent_ranking) == len(gt_ranking) and len(agent_ranking) > 0:
            # Check Kendall tau-like similarity
            matches = sum(1 for a, g in zip(agent_ranking, gt_ranking) if a == g)
            rank_pct = matches / len(gt_ranking)
            # Also check top-10 order
            top_n = min(10, len(gt_ranking))
            top_matches = sum(1 for a, g in zip(agent_ranking[:top_n], gt_ranking[:top_n]) if a == g)
            top_pct = top_matches / top_n
        else:
            rank_pct = 0
            top_pct = 0

        rank_pts = 0
        if rank_pct >= 0.95:
            rank_pts = 15
        elif top_pct >= 0.80:
            rank_pts = 10
        elif top_pct >= 0.50:
            rank_pts = 5

        eval_criteria["ranking_order"] = {
            "passed": rank_pct >= 0.95,
            "score": rank_pts,
            "max_score": 15,
            "reason": "" if rank_pct >= 0.95 else
                      f"Position match: {rank_pct:.1%}, top-10: {top_pct:.1%}",
        }

        # ── Criterion 5: Risk tier assignments (10 pts) ──
        tier_matches = 0
        for row in csv_rows:
            pid = row.get("permit_id", "").strip()
            if pid in gt_by_pid:
                agent_tier = row.get("risk_tier", "").strip().lower()
                gt_tier = gt_by_pid[pid]["risk_tier"].lower()
                if agent_tier == gt_tier:
                    tier_matches += 1

        tier_pct = tier_matches / total_permits if total_permits > 0 else 0
        tier_pts = 0
        if tier_pct >= 0.95:
            tier_pts = 10
        elif tier_pct >= 0.80:
            tier_pts = 7
        elif tier_pct >= 0.50:
            tier_pts = 4

        eval_criteria["risk_tiers"] = {
            "passed": tier_pct >= 0.95,
            "score": tier_pts,
            "max_score": 10,
            "reason": "" if tier_pct >= 0.95 else f"Tier match: {tier_matches}/{total_permits}",
        }

        # ── Criterion 6: Primary risk factors (10 pts) ──
        factor_matches = 0
        for row in csv_rows:
            pid = row.get("permit_id", "").strip()
            if pid in gt_by_pid:
                agent_factors = set(f.strip() for f in row.get("primary_risk_factors", "").split(";"))
                gt_factors = set(f.strip() for f in gt_by_pid[pid]["primary_risk_factors"].split(";"))
                if agent_factors == gt_factors:
                    factor_matches += 1

        factor_pct = factor_matches / total_permits if total_permits > 0 else 0
        factor_pts = 0
        if factor_pct >= 0.90:
            factor_pts = 10
        elif factor_pct >= 0.70:
            factor_pts = 7
        elif factor_pct >= 0.40:
            factor_pts = 4

        eval_criteria["primary_risk_factors"] = {
            "passed": factor_pct >= 0.90,
            "score": factor_pts,
            "max_score": 10,
            "reason": "" if factor_pct >= 0.90 else f"Factor match: {factor_matches}/{total_permits}",
        }

        # ── Criterion 7: Response contains top-5 summary (10 pts) ──
        top5_gt = ground_truth[:5]
        top5_found = 0
        action_lower = action.lower() if action else ""
        for item in top5_gt:
            # Check if permit ID appears in response
            if item["permit_id"].lower() in action_lower:
                top5_found += 1

        top5_pts = 0
        if top5_found >= 5:
            top5_pts = 10
        elif top5_found >= 3:
            top5_pts = 6
        elif top5_found >= 1:
            top5_pts = 3

        eval_criteria["response_top5_summary"] = {
            "passed": top5_found >= 5,
            "score": top5_pts,
            "max_score": 10,
            "reason": "" if top5_found >= 5 else f"Found {top5_found}/5 top permits in response",
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return total_score / max_score, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml

        # ── Step 1: Read workspace configuration files ──────────────
        config_path = os.path.join(self.workspace, "risk_config.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        ref_date = datetime.strptime(config["reference_date"], "%Y-%m-%d")
        weights = config["risk_weights"]
        sev_mult = {int(k): v for k, v in config["severity_multipliers"].items()}

        # Read zone hazard overlay
        zone_hazards = {}
        zh_path = os.path.join(self.workspace, "zone_hazard_overlay.csv")
        with open(zh_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                zone_hazards[row["zone_id"]] = {
                    "flood_risk": float(row["flood_risk"]),
                    "seismic_factor": float(row["seismic_factor"]),
                    "environmental_sensitivity": float(row["environmental_sensitivity"]),
                    "infrastructure_proximity": float(row["infrastructure_proximity"]),
                }

        # Read site surveys
        site_surveys = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("site_survey_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        site_surveys[row["permit_id"]] = {
                            "structural_score": float(row["structural_score"]),
                            "safety_score": float(row["safety_score"]),
                            "environmental_score": float(row["environmental_score"]),
                        }

        # Read complaint details
        complaint_details = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("complaint_detail_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    records = json.load(f)
                    for r in records:
                        complaint_details[r["complaint_id"]] = {
                            "escalation_flag": r["escalation_flag"],
                        }

        # Read contractor audits
        contractor_audits = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("contractor_audit_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    content = f.read()
                blocks = content.split("=" * 50)
                for block in blocks:
                    block = block.strip()
                    if not block or "Contractor ID:" not in block:
                        continue
                    cid_match = re.search(r"Contractor ID:\s*(\S+)", block)
                    score_match = re.search(r"Safety Audit Score:\s*([\d.]+)", block)
                    if cid_match and score_match:
                        contractor_audits[cid_match.group(1)] = {
                            "safety_audit_score": float(score_match.group(1)),
                        }

        # Read inspection policy
        policy_path = os.path.join(self.workspace, "inspection_policy.md")
        with open(policy_path, "r") as f:
            _ = f.read()  # Read for reference

        # ── Step 2: Discover inspectable permits via tools ──────────
        tool_calls = 0

        # Search active permits (paginated)
        all_inspectable = []
        for status in ["active", "pending_review"]:
            page = 1
            while True:
                result = self.tools["search_permits"](status=status, page=page)
                tool_calls += 1
                all_inspectable.extend(result["results"])
                if page >= result["total_pages"]:
                    break
                page += 1

        # ── Step 3: For each permit, gather data via tools ──────────
        contractor_cache = {}
        violation_cache = {}
        zone_cache = {}
        complaint_cache = {}

        for permit in all_inspectable:
            pid = permit["permit_id"]
            cid = permit["contractor_id"]
            zid = permit["zone_id"]

            # Get contractor info
            if cid not in contractor_cache:
                contractor_cache[cid] = self.tools["get_contractor"](contractor_id=cid)
                tool_calls += 1

            # Get violations
            if cid not in violation_cache:
                violation_cache[cid] = self.tools["get_violations"](contractor_id=cid)
                tool_calls += 1

            # Get zone info
            if zid not in zone_cache:
                zone_cache[zid] = self.tools["get_zone"](zone_id=zid)
                tool_calls += 1

            # Get complaints for this permit
            permit_complaints = []
            page = 1
            while True:
                result = self.tools["search_complaints"](permit_id=pid, page=page)
                tool_calls += 1
                permit_complaints.extend(result["results"])
                if page >= result["total_pages"]:
                    break
                page += 1
            complaint_cache[pid] = permit_complaints

        # ── Step 4: Compute risk scores ─────────────────────────────
        results = []
        for permit in all_inspectable:
            pid = permit["permit_id"]
            cid = permit["contractor_id"]
            zid = permit["zone_id"]
            contractor = contractor_cache[cid]
            violations = violation_cache[cid]["violations"]
            complaints = complaint_cache[pid]

            # 1. Violation history score
            violation_score = 0
            for v in violations:
                sev = v["severity"]
                base = config["violation_base_score"] * sev_mult.get(sev, 0.5)
                if not v["resolved"]:
                    base *= config["unresolved_violation_multiplier"]
                v_date = datetime.strptime(v["violation_date"], "%Y-%m-%d")
                if (ref_date - v_date).days <= config["recent_violation_days"]:
                    base += config["recent_violation_bonus"]
                violation_score += base
            violation_score = min(violation_score, config["max_violation_score"])

            # 2. Zone hazard score
            zh = zone_hazards.get(zid, {"flood_risk": 50, "seismic_factor": 50,
                                         "environmental_sensitivity": 50,
                                         "infrastructure_proximity": 50})
            zone_hazard_score = (zh["flood_risk"] + zh["seismic_factor"] +
                                 zh["environmental_sensitivity"] +
                                 zh["infrastructure_proximity"]) / 4

            # 3. Complaint severity score
            complaint_score = 0
            for cm in complaints:
                sev = cm["severity"]
                base = config["complaint_base_score"] * sev_mult.get(sev, 0.5)
                if cm["complaint_id"] in complaint_details:
                    if complaint_details[cm["complaint_id"]]["escalation_flag"]:
                        base += config["escalated_complaint_bonus"]
                complaint_score += base
            complaint_score = min(complaint_score, config["max_complaint_score"])

            # 4. Project scale score
            pv = permit["project_value"]
            project_scale_score = 20
            for tier in config["project_value_tiers"]:
                if tier["min_value"] <= pv < tier["max_value"]:
                    project_scale_score = tier["risk_score"]
                    break

            # 5. Contractor reliability score
            if cid in contractor_audits:
                contractor_reliability_score = 100 - contractor_audits[cid]["safety_audit_score"]
            else:
                contractor_reliability_score = 50

            # 6. Site condition score
            if pid in site_surveys:
                ss = site_surveys[pid]
                avg_survey = (ss["structural_score"] + ss["safety_score"] +
                              ss["environmental_score"]) / 3
                site_condition_score = 100 - avg_survey
            else:
                site_condition_score = 50

            # Weighted sum
            components = {
                "violation_history": violation_score,
                "zone_hazard": zone_hazard_score,
                "complaint_severity": complaint_score,
                "project_scale": project_scale_score,
                "contractor_reliability": contractor_reliability_score,
                "site_condition": site_condition_score,
            }
            weighted = {k: weights[k] * v for k, v in components.items()}
            raw_score = sum(weighted.values())

            # License penalties
            license_expiry = datetime.strptime(contractor["license_expiry"], "%Y-%m-%d")
            if license_expiry < ref_date:
                raw_score += config["expired_license_penalty"]
            elif license_expiry < ref_date + timedelta(days=config["license_expiry_window_days"]):
                raw_score += config["expiring_license_penalty"]

            risk_score = round(min(100, raw_score), 2)

            # Risk tier
            risk_tier = "low"
            for rt in config["risk_tiers"]:
                if rt["name"] == "critical":
                    if risk_score >= rt["min_score"]:
                        risk_tier = rt["name"]
                else:
                    if rt["min_score"] <= risk_score < rt["max_score"]:
                        risk_tier = rt["name"]

            # Primary risk factors
            sorted_factors = sorted(weighted.items(), key=lambda x: x[1], reverse=True)
            primary = "; ".join([f[0] for f in sorted_factors[:2]])

            results.append({
                "permit_id": pid,
                "site_address": permit["site_address"],
                "contractor_name": contractor["company_name"],
                "risk_score": risk_score,
                "risk_tier": risk_tier,
                "primary_risk_factors": primary,
                "submission_date": permit["submission_date"],
            })

        # Sort: risk_score DESC, submission_date ASC, permit_id ASC
        results.sort(key=lambda x: (-x["risk_score"], x["submission_date"], x["permit_id"]))

        # Assign ranks
        for i, r in enumerate(results):
            r["rank"] = i + 1

        # ── Step 5: Write deliverables ──────────────────────────────
        csv_path = os.path.join(self.workspace, "inspection_priority_list.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "rank", "permit_id", "site_address", "contractor_name",
                "risk_score", "risk_tier", "primary_risk_factors"
            ])
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "rank": r["rank"],
                    "permit_id": r["permit_id"],
                    "site_address": r["site_address"],
                    "contractor_name": r["contractor_name"],
                    "risk_score": r["risk_score"],
                    "risk_tier": r["risk_tier"],
                    "primary_risk_factors": r["primary_risk_factors"],
                })

        # ── Step 6: Build response with top-5 summary ──────────────
        top5 = results[:5]
        response_lines = ["Weekly Inspection Priority List - Top 5 Highest Risk Sites:\n"]
        for item in top5:
            response_lines.append(
                f"Rank {item['rank']}: {item['permit_id']} at {item['site_address']} "
                f"(Contractor: {item['contractor_name']}) — "
                f"Risk Score: {item['risk_score']}, Tier: {item['risk_tier']}, "
                f"Primary Factors: {item['primary_risk_factors']}"
            )
        response_lines.append(f"\nTotal permits on inspection list: {len(results)}")
        response_lines.append(f"Tool calls made: {tool_calls}")

        action = "\n".join(response_lines)
        return self.step(action)
