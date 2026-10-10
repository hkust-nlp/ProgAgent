"""
Commercial Property Insurance Risk Assessment - Environment

Provides tools for querying insurance data and evaluates the agent's
risk-tiered quote list output.
"""

import sqlite3
import os
import json
import csv
import math
import glob as glob_mod
from typing import Tuple, Dict, List, Any

import yaml


# --- Decorator ---
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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description="Lists insurance applications filtered by status. Returns a paginated list of applications with basic info. Each page contains up to page_size results.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by application status: pending_review, approved, rejected, or under_investigation",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20)",
                },
            },
            "required": ["status", "page", "page_size"],
        },
    )
    def list_applications(self, status: str, page: int, page_size: int) -> dict:
        page_size = min(int(page_size), 20)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM applications WHERE status = ?", (status,))
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT application_id, property_id, applicant_id, status, requested_coverage, submission_date "
            "FROM applications WHERE status = ? ORDER BY application_id LIMIT ? OFFSET ?",
            (status, page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total > 0 else 0,
            "applications": rows,
        }

    @tool(
        description="Retrieves detailed information for a single application, including the linked applicant company name and property address/region.",
        parameters={
            "type": "object",
            "properties": {
                "application_id": {
                    "type": "string",
                    "description": "The application ID (e.g. APPL-0001)",
                },
            },
            "required": ["application_id"],
        },
    )
    def get_application_details(self, application_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.application_id, a.property_id, a.applicant_id, a.status,
                   a.requested_coverage, a.submission_date,
                   ap.company_name, ap.contact_email, ap.industry,
                   p.address, p.region_code, p.building_name
            FROM applications a
            JOIN applicants ap ON a.applicant_id = ap.applicant_id
            JOIN properties p ON a.property_id = p.property_id
            WHERE a.application_id = ?
            """,
            (application_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Application {application_id} not found"}
        return dict(row)

    @tool(
        description="Retrieves building permit and construction details for a property.",
        parameters={
            "type": "object",
            "properties": {
                "property_id": {
                    "type": "string",
                    "description": "The property ID (e.g. PROP-0001)",
                },
            },
            "required": ["property_id"],
        },
    )
    def get_building_permit(self, property_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM building_permits WHERE property_id = ?",
            (property_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"No permit found for property {property_id}"}
        return dict(row)

    @tool(
        description="Retrieves historical flood and fire claims for a specific region. Optionally filter by claim type.",
        parameters={
            "type": "object",
            "properties": {
                "region_code": {
                    "type": "string",
                    "description": "Region code (e.g. NE-01)",
                },
                "claim_type": {
                    "type": "string",
                    "description": "Optional: filter by 'flood' or 'fire'. Omit to get both.",
                },
            },
            "required": ["region_code"],
        },
    )
    def get_claims_by_region(self, region_code: str, claim_type: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if claim_type:
            cur.execute(
                "SELECT * FROM claims_history WHERE region_code = ? AND claim_type = ? "
                "AND claim_year BETWEEN 2016 AND 2025 ORDER BY claim_year DESC",
                (region_code, claim_type),
            )
        else:
            cur.execute(
                "SELECT * FROM claims_history WHERE region_code = ? "
                "AND claim_year BETWEEN 2016 AND 2025 ORDER BY claim_year DESC",
                (region_code,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        # Compute summary stats
        flood_sevs = [r["severity"] for r in rows if r["claim_type"] == "flood"]
        fire_sevs = [r["severity"] for r in rows if r["claim_type"] == "fire"]
        summary = {
            "region_code": region_code,
            "total_claims": len(rows),
            "flood_count": len(flood_sevs),
            "fire_count": len(fire_sevs),
            "avg_flood_severity": round(sum(flood_sevs) / len(flood_sevs), 2) if flood_sevs else 0,
            "avg_fire_severity": round(sum(fire_sevs) / len(fire_sevs), 2) if fire_sevs else 0,
        }
        return {"summary": summary, "claims": rows}

    @tool(
        description="Retrieves occupancy sensor readings for a property. Returns all available readings sorted by date.",
        parameters={
            "type": "object",
            "properties": {
                "property_id": {
                    "type": "string",
                    "description": "The property ID (e.g. PROP-0001)",
                },
            },
            "required": ["property_id"],
        },
    )
    def get_occupancy_readings(self, property_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM occupancy_sensors WHERE property_id = ? ORDER BY reading_date DESC",
            (property_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"property_id": property_id, "reading_count": len(rows), "readings": rows}

    @tool(
        description="Retrieves the most recent financial assessment for an applicant, including stability score, debt ratio, credit rating, and liquidity ratio.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID (e.g. APP-0001)",
                },
            },
            "required": ["applicant_id"],
        },
    )
    def get_financial_profile(self, applicant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM financial_scores WHERE applicant_id = ? ORDER BY assessment_date DESC LIMIT 1",
            (applicant_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"No financial data for applicant {applicant_id}"}
        return dict(row)

    # ------------------------------------------------------------------
    # Ground-truth helpers (used by step and verify)
    # ------------------------------------------------------------------

    def _load_assessment_map(self) -> Dict[str, dict]:
        """Load all property assessments from workspace files into a dict keyed by property_id."""
        amap = {}
        pattern = os.path.join(self.workspace, "property_assessment_batch_*.json")
        for fpath in sorted(glob_mod.glob(pattern)):
            with open(fpath) as f:
                data = json.load(f)
            for a in data["assessments"]:
                amap[a["property_id"]] = a
        return amap

    def _load_coverage_matrix(self) -> Dict[str, int]:
        """Returns dict of (tier_code, construction_type) -> max_coverage in dollars."""
        cov = {}
        with open(os.path.join(self.workspace, "coverage_matrix.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["tier_code"], row["construction_type"])
                cov[key] = int(row["max_coverage_millions"]) * 1_000_000
        return cov

    def _load_risk_rules(self) -> dict:
        with open(os.path.join(self.workspace, "risk_scoring_rules.yaml")) as f:
            return yaml.safe_load(f)

    def _load_premium_schedule(self) -> dict:
        with open(os.path.join(self.workspace, "premium_schedule.json")) as f:
            return json.load(f)

    def _compute_construction_risk(self, permit: dict, rules: dict) -> int:
        comp = rules["components"]["construction_risk"]
        base = comp["base_scores"].get(permit["construction_type"], 14)
        age_decades = (comp["age_reference_year"] - permit["year_built"]) // 10
        age_pen = age_decades * comp["age_penalty_per_decade"]
        fire_bonus = permit["fire_safety_rating"] * comp["fire_safety_bonus_per_point"]
        struct_pen = comp["structural_grade_penalty"].get(permit["structural_grade"], 3)
        return max(0, min(base + age_pen + fire_bonus + struct_pen, comp["max_points"]))

    def _compute_claims_risk(self, region_code: str, rules: dict) -> int:
        comp = rules["components"]["claims_risk"]
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT claim_type, severity FROM claims_history "
            "WHERE region_code = ? AND claim_year BETWEEN 2016 AND 2025",
            (region_code,),
        )
        rows = cur.fetchall()
        conn.close()
        flood_sevs = [r["severity"] for r in rows if r["claim_type"] == "flood"]
        fire_sevs = [r["severity"] for r in rows if r["claim_type"] == "fire"]
        avg_flood = sum(flood_sevs) / len(flood_sevs) if flood_sevs else 0
        avg_fire = sum(fire_sevs) / len(fire_sevs) if fire_sevs else 0
        dual = comp["dual_peril_bonus"] if (flood_sevs and fire_sevs) else 0
        score = round(avg_flood * comp["flood_severity_weight"] + avg_fire * comp["fire_severity_weight"] + dual)
        return max(0, min(score, comp["max_points"]))

    def _compute_occupancy_risk(self, property_id: str, rules: dict) -> int:
        comp = rules["components"]["occupancy_risk"]
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT avg_occupancy_pct, sensor_status FROM occupancy_sensors WHERE property_id = ?",
            (property_id,),
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return 0
        mean_occ = sum(r["avg_occupancy_pct"] for r in rows) / len(rows)
        bracket_score = 0
        for bracket in comp["avg_occupancy_brackets"]:
            if mean_occ <= bracket["max_pct"]:
                bracket_score = bracket["score"]
                break
        else:
            bracket_score = comp["avg_occupancy_brackets"][-1]["score"]
        has_degraded = any(r["sensor_status"] == "degraded" for r in rows)
        penalty = comp["degraded_sensor_penalty"] if has_degraded else 0
        return max(0, min(bracket_score + penalty, comp["max_points"]))

    def _compute_financial_risk(self, applicant_id: str, rules: dict) -> Tuple[int, int, float]:
        """Returns (financial_risk_score, stability_score, debt_ratio)."""
        comp = rules["components"]["financial_risk"]
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT stability_score, debt_ratio FROM financial_scores "
            "WHERE applicant_id = ? ORDER BY assessment_date DESC LIMIT 1",
            (applicant_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return 0, 50, 0.5
        stab = row["stability_score"]
        debt = row["debt_ratio"]
        base = round((100 - stab) * 15 / 100)
        if debt > 0.60:
            base += 3
        return max(0, min(base, comp["max_points"])), stab, debt

    def _compute_environmental_risk(self, property_id: str, assessment_map: dict, rules: dict) -> int:
        comp = rules["components"]["environmental_risk"]
        assess = assessment_map.get(property_id)
        if assess is None:
            return 0
        flood_dist = assess["flood_zone_distance_m"]
        flood_score = 0
        for bracket in comp["flood_proximity_brackets"]:
            if flood_dist <= bracket["max_distance_m"]:
                flood_score = bracket["score"]
                break
        fire_km = assess["nearest_fire_station_km"]
        fire_score = 0
        for bracket in comp["fire_station_brackets"]:
            if fire_km <= bracket["max_km"]:
                fire_score = bracket["score"]
                break
        cond_score = comp["condition_scores"].get(assess["building_condition"], 0)
        return max(0, min(flood_score + fire_score + cond_score, comp["max_points"]))

    def _get_tier(self, risk_score: int, rules: dict) -> str:
        for tier in rules["tier_mapping"]:
            if tier["min_score"] <= risk_score <= tier["max_score"]:
                return tier["tier_code"]
        return "T4"

    def _compute_premium(self, tier_code: str, construction_type: str,
                         recommended_coverage: float, risk_score: int,
                         stability_score: int, schedule: dict) -> float:
        base_rate = schedule["tier_base_rate_per_million"].get(tier_code, 8500)
        cons_mult = schedule["construction_multiplier"].get(construction_type, 1.0)
        base = base_rate * (recommended_coverage / 1_000_000)
        base *= cons_mult
        base *= (1 + risk_score / 200)
        if stability_score >= schedule["stability_discount"]["min_stability_score"]:
            base *= (1 - schedule["stability_discount"]["discount_pct"] / 100)
        return round(base, 2)

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the full ground-truth quote list."""
        rules = self._load_risk_rules()
        schedule = self._load_premium_schedule()
        cov_matrix = self._load_coverage_matrix()
        assess_map = self._load_assessment_map()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.application_id, a.property_id, a.applicant_id,
                   a.requested_coverage,
                   ap.company_name,
                   p.address, p.region_code
            FROM applications a
            JOIN applicants ap ON a.applicant_id = ap.applicant_id
            JOIN properties p ON a.property_id = p.property_id
            WHERE a.status = 'pending_review'
            ORDER BY a.application_id
            """
        )
        pending = [dict(r) for r in cur.fetchall()]
        conn.close()

        results = []
        for app in pending:
            aid = app["applicant_id"]
            pid = app["property_id"]
            region = app["region_code"]

            # Get permit
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM building_permits WHERE property_id = ?", (pid,))
            permit = dict(cur.fetchone())
            conn.close()

            # Financial
            fin_risk, stab, debt = self._compute_financial_risk(aid, rules)

            # Eligibility check
            declined = stab < 30 and debt > 0.70

            if declined:
                results.append({
                    "application_id": app["application_id"],
                    "company_name": app["company_name"],
                    "property_address": app["address"],
                    "region_code": region,
                    "risk_score": "",
                    "risk_tier": "",
                    "recommended_coverage": "",
                    "annual_premium": "",
                    "status": "DECLINED",
                })
                continue

            # Risk components
            cons_risk = self._compute_construction_risk(permit, rules)
            claims_risk = self._compute_claims_risk(region, rules)
            occ_risk = self._compute_occupancy_risk(pid, rules)
            env_risk = self._compute_environmental_risk(pid, assess_map, rules)
            total_risk = max(0, min(cons_risk + claims_risk + occ_risk + fin_risk + env_risk, 100))

            tier = self._get_tier(total_risk, rules)
            construction_type = permit["construction_type"]
            max_cov = cov_matrix.get((tier, construction_type), 0)
            rec_cov = min(int(app["requested_coverage"]), max_cov)
            premium = self._compute_premium(tier, construction_type, rec_cov, total_risk, stab, schedule)

            results.append({
                "application_id": app["application_id"],
                "company_name": app["company_name"],
                "property_address": app["address"],
                "region_code": region,
                "risk_score": total_risk,
                "risk_tier": tier,
                "recommended_coverage": rec_cov,
                "annual_premium": premium,
                "status": "QUOTED",
            })

        # Sort: risk_score desc (DECLINED have "" so they go at end), then application_id asc
        quoted = [r for r in results if r["status"] == "QUOTED"]
        declined = [r for r in results if r["status"] == "DECLINED"]
        quoted.sort(key=lambda r: (-r["risk_score"], r["application_id"]))
        declined.sort(key=lambda r: r["application_id"])
        return quoted + declined

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        gt = self._compute_ground_truth()
        rules = self._load_risk_rules()
        schedule = self._load_premium_schedule()

        total_pending = len(gt)
        gt_quoted = [r for r in gt if r["status"] == "QUOTED"]
        gt_declined = [r for r in gt if r["status"] == "DECLINED"]

        criteria = {}
        max_score = 0
        total_score = 0

        # ---- Criterion 1: quote_list.csv exists and has correct columns (10 pts) ----
        c1_max = 10
        max_score += c1_max
        quote_path = os.path.join(self.workspace, "quote_list.csv")
        expected_cols = [
            "application_id", "company_name", "property_address", "region_code",
            "risk_score", "risk_tier", "recommended_coverage", "annual_premium", "status",
        ]
        if os.path.exists(quote_path):
            with open(quote_path) as f:
                reader = csv.DictReader(f)
                actual_cols = reader.fieldnames or []
                agent_rows = list(reader)
            if actual_cols == expected_cols:
                criteria["quote_list_structure"] = {"passed": True, "score": c1_max, "max_score": c1_max}
                total_score += c1_max
            else:
                criteria["quote_list_structure"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"Expected columns {expected_cols}, got {actual_cols}",
                }
                agent_rows = []
        else:
            criteria["quote_list_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "quote_list.csv not found",
            }
            agent_rows = []

        # ---- Criterion 2: Correct number of rows (10 pts) ----
        c2_max = 10
        max_score += c2_max
        if len(agent_rows) == total_pending:
            criteria["row_count"] = {"passed": True, "score": c2_max, "max_score": c2_max}
            total_score += c2_max
        else:
            criteria["row_count"] = {
                "passed": False, "score": 0, "max_score": c2_max,
                "reason": f"Expected {total_pending} rows, got {len(agent_rows)}",
            }

        # Build agent lookup by application_id
        agent_map = {}
        for r in agent_rows:
            agent_map[r.get("application_id", "")] = r

        # ---- Criterion 3: Correct declined vs quoted status (15 pts) ----
        c3_max = 15
        max_score += c3_max
        gt_status_map = {r["application_id"]: r["status"] for r in gt}
        status_correct = 0
        status_total = len(gt)
        for app_id, expected_status in gt_status_map.items():
            agent_r = agent_map.get(app_id)
            if agent_r and agent_r.get("status", "").strip().upper() == expected_status:
                status_correct += 1
        if status_total > 0:
            c3_score = round(c3_max * status_correct / status_total, 2)
        else:
            c3_score = c3_max
        criteria["status_accuracy"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_score == c3_max else f"{status_correct}/{status_total} statuses correct",
        }
        total_score += c3_score

        # ---- Criterion 4: Risk scores accurate within ±3 (20 pts) ----
        c4_max = 20
        max_score += c4_max
        rs_correct = 0
        rs_total = len(gt_quoted)
        for r in gt_quoted:
            agent_r = agent_map.get(r["application_id"])
            if agent_r:
                try:
                    agent_rs = int(agent_r.get("risk_score", -999))
                    if abs(agent_rs - r["risk_score"]) <= 3:
                        rs_correct += 1
                except (ValueError, TypeError):
                    pass
        if rs_total > 0:
            c4_score = round(c4_max * rs_correct / rs_total, 2)
        else:
            c4_score = c4_max
        criteria["risk_score_accuracy"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if c4_score == c4_max else f"{rs_correct}/{rs_total} risk scores within tolerance",
        }
        total_score += c4_score

        # ---- Criterion 5: Risk tier assignments correct (15 pts) ----
        c5_max = 15
        max_score += c5_max
        tier_correct = 0
        tier_total = len(gt_quoted)
        for r in gt_quoted:
            agent_r = agent_map.get(r["application_id"])
            if agent_r and agent_r.get("risk_tier", "").strip() == r["risk_tier"]:
                tier_correct += 1
        if tier_total > 0:
            c5_score = round(c5_max * tier_correct / tier_total, 2)
        else:
            c5_score = c5_max
        criteria["tier_accuracy"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": "" if c5_score == c5_max else f"{tier_correct}/{tier_total} tiers correct",
        }
        total_score += c5_score

        # ---- Criterion 6: Recommended coverage correct (10 pts) ----
        c6_max = 10
        max_score += c6_max
        cov_correct = 0
        cov_total = len(gt_quoted)
        for r in gt_quoted:
            agent_r = agent_map.get(r["application_id"])
            if agent_r:
                try:
                    agent_cov = int(float(agent_r.get("recommended_coverage", -1)))
                    if agent_cov == r["recommended_coverage"]:
                        cov_correct += 1
                except (ValueError, TypeError):
                    pass
        if cov_total > 0:
            c6_score = round(c6_max * cov_correct / cov_total, 2)
        else:
            c6_score = c6_max
        criteria["coverage_accuracy"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_score == c6_max else f"{cov_correct}/{cov_total} coverages correct",
        }
        total_score += c6_score

        # ---- Criterion 7: Premium within ±5% (10 pts) ----
        c7_max = 10
        max_score += c7_max
        prem_correct = 0
        prem_total = len(gt_quoted)
        for r in gt_quoted:
            agent_r = agent_map.get(r["application_id"])
            if agent_r:
                try:
                    agent_prem = float(agent_r.get("annual_premium", -1))
                    expected_prem = r["annual_premium"]
                    if expected_prem > 0 and abs(agent_prem - expected_prem) / expected_prem <= 0.05:
                        prem_correct += 1
                    elif expected_prem == 0 and agent_prem == 0:
                        prem_correct += 1
                except (ValueError, TypeError):
                    pass
        if prem_total > 0:
            c7_score = round(c7_max * prem_correct / prem_total, 2)
        else:
            c7_score = c7_max
        criteria["premium_accuracy"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": "" if c7_score == c7_max else f"{prem_correct}/{prem_total} premiums within 5%",
        }
        total_score += c7_score

        # ---- Criterion 8: risk_summary.json correctness (10 pts) ----
        c8_max = 10
        max_score += c8_max
        summary_path = os.path.join(self.workspace, "risk_summary.json")
        c8_score = 0
        c8_reason = ""
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    agent_summary = json.load(f)
                # Expected summary
                tier_dist = {"T1": 0, "T2": 0, "T3": 0, "T4": 0}
                for r in gt_quoted:
                    tier_dist[r["risk_tier"]] = tier_dist.get(r["risk_tier"], 0) + 1
                premiums = [r["annual_premium"] for r in gt_quoted]
                expected_summary = {
                    "total_reviewed": total_pending,
                    "declined_count": len(gt_declined),
                    "quoted_count": len(gt_quoted),
                    "tier_distribution": tier_dist,
                    "average_premium": round(sum(premiums) / len(premiums), 2) if premiums else 0,
                    "total_recommended_coverage": sum(r["recommended_coverage"] for r in gt_quoted),
                }
                checks = 0
                total_checks = 6
                if agent_summary.get("total_reviewed") == expected_summary["total_reviewed"]:
                    checks += 1
                if agent_summary.get("declined_count") == expected_summary["declined_count"]:
                    checks += 1
                if agent_summary.get("quoted_count") == expected_summary["quoted_count"]:
                    checks += 1
                # Tier distribution
                agent_td = agent_summary.get("tier_distribution", {})
                if all(agent_td.get(k, -1) == v for k, v in expected_summary["tier_distribution"].items()):
                    checks += 1
                # Average premium within 5%
                agent_avg = agent_summary.get("average_premium", -1)
                exp_avg = expected_summary["average_premium"]
                if exp_avg > 0 and abs(float(agent_avg) - exp_avg) / exp_avg <= 0.05:
                    checks += 1
                elif exp_avg == 0 and float(agent_avg) == 0:
                    checks += 1
                # Total coverage
                agent_tc = agent_summary.get("total_recommended_coverage", -1)
                if int(agent_tc) == expected_summary["total_recommended_coverage"]:
                    checks += 1
                c8_score = round(c8_max * checks / total_checks, 2)
                if checks < total_checks:
                    c8_reason = f"{checks}/{total_checks} summary fields correct"
            except Exception as e:
                c8_reason = f"Error parsing risk_summary.json: {e}"
        else:
            c8_reason = "risk_summary.json not found"

        criteria["risk_summary"] = {
            "passed": c8_score == c8_max,
            "score": c8_score,
            "max_score": c8_max,
            "reason": c8_reason,
        }
        total_score += c8_score

        total_score = round(total_score, 2)
        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0

        return reward, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import glob as g

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # --- Step 1: Load workspace config files ---
        with open(os.path.join(self.workspace, "risk_scoring_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "premium_schedule.json")) as f:
            schedule = json.load(f)

        # Coverage matrix
        cov_matrix = {}
        with open(os.path.join(self.workspace, "coverage_matrix.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                cov_matrix[(row["tier_code"], row["construction_type"])] = int(row["max_coverage_millions"]) * 1_000_000

        # Load all assessment files
        assess_map = {}
        assessment_files = sorted(g.glob(os.path.join(self.workspace, "property_assessment_batch_*.json")))
        for fpath in assessment_files:
            with open(fpath) as f:
                data = json.load(f)
            for a in data["assessments"]:
                assess_map[a["property_id"]] = a

        # --- Step 2: Get all pending applications ---
        all_pending = []
        page = 1
        while True:
            result = call_tool("list_applications", status="pending_review", page=page, page_size=20)
            all_pending.extend(result["applications"])
            if page >= result["total_pages"]:
                break
            page += 1

        # --- Step 3: For each pending application, gather data and compute risk ---
        output_rows = []
        for app in all_pending:
            app_id = app["application_id"]
            prop_id = app["property_id"]
            applicant_id = app["applicant_id"]

            # Get details
            details = call_tool("get_application_details", application_id=app_id)
            company_name = details["company_name"]
            address = details["address"]
            region_code = details["region_code"]
            requested_coverage = details["requested_coverage"]

            # Get financial profile
            fin = call_tool("get_financial_profile", applicant_id=applicant_id)
            stability_score = fin["stability_score"]
            debt_ratio = fin["debt_ratio"]

            # Check eligibility
            if stability_score < 30 and debt_ratio > 0.70:
                output_rows.append({
                    "application_id": app_id,
                    "company_name": company_name,
                    "property_address": address,
                    "region_code": region_code,
                    "risk_score": "",
                    "risk_tier": "",
                    "recommended_coverage": "",
                    "annual_premium": "",
                    "status": "DECLINED",
                })
                continue

            # Get building permit
            permit = call_tool("get_building_permit", property_id=prop_id)
            construction_type = permit["construction_type"]

            # Construction risk
            comp = rules["components"]["construction_risk"]
            cons_base = comp["base_scores"].get(construction_type, 14)
            age_decades = (comp["age_reference_year"] - permit["year_built"]) // 10
            age_pen = age_decades * comp["age_penalty_per_decade"]
            fire_bonus = permit["fire_safety_rating"] * comp["fire_safety_bonus_per_point"]
            struct_pen = comp["structural_grade_penalty"].get(permit["structural_grade"], 3)
            construction_risk = max(0, min(cons_base + age_pen + fire_bonus + struct_pen, comp["max_points"]))

            # Claims risk
            claims_data = call_tool("get_claims_by_region", region_code=region_code)
            summary = claims_data["summary"]
            avg_flood_sev = summary["avg_flood_severity"]
            avg_fire_sev = summary["avg_fire_severity"]
            comp_c = rules["components"]["claims_risk"]
            dual_bonus = comp_c["dual_peril_bonus"] if (summary["flood_count"] > 0 and summary["fire_count"] > 0) else 0
            claims_risk = max(0, min(
                round(avg_flood_sev * comp_c["flood_severity_weight"] + avg_fire_sev * comp_c["fire_severity_weight"] + dual_bonus),
                comp_c["max_points"]
            ))

            # Occupancy risk
            sensor_data = call_tool("get_occupancy_readings", property_id=prop_id)
            readings = sensor_data["readings"]
            comp_o = rules["components"]["occupancy_risk"]
            if readings:
                mean_occ = sum(r["avg_occupancy_pct"] for r in readings) / len(readings)
                bracket_score = 0
                for bracket in comp_o["avg_occupancy_brackets"]:
                    if mean_occ <= bracket["max_pct"]:
                        bracket_score = bracket["score"]
                        break
                else:
                    bracket_score = comp_o["avg_occupancy_brackets"][-1]["score"]
                has_degraded = any(r["sensor_status"] == "degraded" for r in readings)
                degraded_pen = comp_o["degraded_sensor_penalty"] if has_degraded else 0
                occupancy_risk = max(0, min(bracket_score + degraded_pen, comp_o["max_points"]))
            else:
                occupancy_risk = 0

            # Financial risk
            comp_f = rules["components"]["financial_risk"]
            fin_base = round((100 - stability_score) * 15 / 100)
            if debt_ratio > 0.60:
                fin_base += 3
            financial_risk = max(0, min(fin_base, comp_f["max_points"]))

            # Environmental risk
            assess = assess_map.get(prop_id)
            comp_e = rules["components"]["environmental_risk"]
            if assess:
                flood_dist = assess["flood_zone_distance_m"]
                flood_score = 0
                for bracket in comp_e["flood_proximity_brackets"]:
                    if flood_dist <= bracket["max_distance_m"]:
                        flood_score = bracket["score"]
                        break
                fire_km = assess["nearest_fire_station_km"]
                fire_score = 0
                for bracket in comp_e["fire_station_brackets"]:
                    if fire_km <= bracket["max_km"]:
                        fire_score = bracket["score"]
                        break
                cond_score = comp_e["condition_scores"].get(assess["building_condition"], 0)
                environmental_risk = max(0, min(flood_score + fire_score + cond_score, comp_e["max_points"]))
            else:
                environmental_risk = 0

            total_risk = max(0, min(construction_risk + claims_risk + occupancy_risk + financial_risk + environmental_risk, 100))

            # Tier assignment
            tier_code = None
            for tier in rules["tier_mapping"]:
                if tier["min_score"] <= total_risk <= tier["max_score"]:
                    tier_code = tier["tier_code"]
                    break
            if tier_code is None:
                tier_code = "T4"

            # Coverage
            max_cov = cov_matrix.get((tier_code, construction_type), 0)
            rec_cov = min(int(requested_coverage), max_cov)

            # Premium
            base_rate = schedule["tier_base_rate_per_million"].get(tier_code, 8500)
            cons_mult = schedule["construction_multiplier"].get(construction_type, 1.0)
            prem = base_rate * (rec_cov / 1_000_000)
            prem *= cons_mult
            prem *= (1 + total_risk / 200)
            if stability_score >= schedule["stability_discount"]["min_stability_score"]:
                prem *= (1 - schedule["stability_discount"]["discount_pct"] / 100)
            annual_premium = round(prem, 2)

            output_rows.append({
                "application_id": app_id,
                "company_name": company_name,
                "property_address": address,
                "region_code": region_code,
                "risk_score": total_risk,
                "risk_tier": tier_code,
                "recommended_coverage": rec_cov,
                "annual_premium": annual_premium,
                "status": "QUOTED",
            })

        # --- Step 4: Sort results ---
        quoted = [r for r in output_rows if r["status"] == "QUOTED"]
        declined = [r for r in output_rows if r["status"] == "DECLINED"]
        quoted.sort(key=lambda r: (-r["risk_score"], r["application_id"]))
        declined.sort(key=lambda r: r["application_id"])
        sorted_rows = quoted + declined

        # --- Step 5: Write quote_list.csv ---
        fieldnames = [
            "application_id", "company_name", "property_address", "region_code",
            "risk_score", "risk_tier", "recommended_coverage", "annual_premium", "status",
        ]
        quote_path = os.path.join(self.workspace, "quote_list.csv")
        with open(quote_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sorted_rows)

        # --- Step 6: Write risk_summary.json ---
        premiums = [r["annual_premium"] for r in quoted]
        tier_dist = {"T1": 0, "T2": 0, "T3": 0, "T4": 0}
        for r in quoted:
            tier_dist[r["risk_tier"]] = tier_dist.get(r["risk_tier"], 0) + 1
        summary = {
            "total_reviewed": len(output_rows),
            "declined_count": len(declined),
            "quoted_count": len(quoted),
            "tier_distribution": tier_dist,
            "average_premium": round(sum(premiums) / len(premiums), 2) if premiums else 0,
            "total_recommended_coverage": sum(r["recommended_coverage"] for r in quoted),
        }
        summary_path = os.path.join(self.workspace, "risk_summary.json")
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        # --- Step 7: Build action string ---
        action = (
            f"Processed {len(output_rows)} pending applications. "
            f"{len(declined)} declined due to eligibility failure. "
            f"{len(quoted)} quoted across tiers: "
            + ", ".join(f"{k}={v}" for k, v in tier_dist.items())
            + f". Average premium: ${summary['average_premium']:,.2f}. "
            f"Total recommended coverage: ${summary['total_recommended_coverage']:,}. "
            f"Results saved to quote_list.csv and risk_summary.json."
        )

        print(f"[verify] Tool calls made: {tool_call_count}")
        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls; need >=15"

        return self.step(action)
