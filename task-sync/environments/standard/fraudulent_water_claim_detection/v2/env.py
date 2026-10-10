"""
Environment for fraudulent water damage claim detection task.
Provides tools for querying policy, claim, weather, and history data,
plus evaluation of the agent's investigation output.
"""

import csv
import json
import os
import sqlite3
import yaml
from datetime import datetime, timedelta
from typing import Tuple, Dict, List, Any


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

    # ─── Tool Methods ───

    @tool(
        description="List claims filtered by status, with pagination. Returns a list of claim IDs and basic info.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "approved", "denied", "under_review", "closed"],
                    "description": "Claim status to filter by"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20)"
                }
            },
            "required": ["status", "page", "page_size"]
        }
    )
    def list_claims_by_status(self, status: str, page: int, page_size: int) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM claims WHERE status = ?", (status,))
        total = c.fetchone()[0]

        c.execute(
            "SELECT claim_id, policy_id, incident_date, claimed_amount FROM claims WHERE status = ? ORDER BY claim_id LIMIT ? OFFSET ?",
            (status, page_size, offset)
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()

        return {
            "claims": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }

    @tool(
        description="Get full details for a specific claim by claim_id.",
        parameters={
            "type": "object",
            "properties": {
                "claim_id": {
                    "type": "string",
                    "description": "The claim ID (e.g., CLM-20001)"
                }
            },
            "required": ["claim_id"]
        }
    )
    def get_claim_details(self, claim_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Claim {claim_id} not found"}

    @tool(
        description="Get policy details for a given policy_id.",
        parameters={
            "type": "object",
            "properties": {
                "policy_id": {
                    "type": "string",
                    "description": "The policy ID (e.g., POL-10001)"
                }
            },
            "required": ["policy_id"]
        }
    )
    def get_policy_details(self, policy_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM policies WHERE policy_id = ?", (policy_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Policy {policy_id} not found"}

    @tool(
        description="Get weather data for a specific zip code on a specific date. Returns precipitation, wind speed, temperature, flood alerts, and storm events.",
        parameters={
            "type": "object",
            "properties": {
                "zip_code": {
                    "type": "string",
                    "description": "5-digit zip code"
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format"
                }
            },
            "required": ["zip_code", "date"]
        }
    )
    def get_weather_data(self, zip_code: str, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM weather_records WHERE zip_code = ? AND date = ?",
            (zip_code, date)
        )
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"zip_code": zip_code, "date": date, "precipitation_mm": 0.0,
                "wind_speed_kmh": 0.0, "temperature_c": 20.0,
                "flood_alert": 0, "storm_event": None,
                "note": "No weather record found for this location/date; assume dry conditions"}

    @tool(
        description="Get all prior claims for a given policy_id. Returns the policyholder's claims history.",
        parameters={
            "type": "object",
            "properties": {
                "policy_id": {
                    "type": "string",
                    "description": "The policy ID"
                }
            },
            "required": ["policy_id"]
        }
    )
    def get_prior_claims(self, policy_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM claim_history WHERE policy_id = ? ORDER BY prior_claim_date DESC",
            (policy_id,)
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"policy_id": policy_id, "prior_claims": rows, "total": len(rows)}

    @tool(
        description="Check if a policy was active (not expired) on a given date.",
        parameters={
            "type": "object",
            "properties": {
                "policy_id": {
                    "type": "string",
                    "description": "The policy ID"
                },
                "check_date": {
                    "type": "string",
                    "description": "Date to check in YYYY-MM-DD format"
                }
            },
            "required": ["policy_id", "check_date"]
        }
    )
    def check_policy_active(self, policy_id: str, check_date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT effective_date, expiration_date FROM policies WHERE policy_id = ?", (policy_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            return {"error": f"Policy {policy_id} not found"}

        eff = row["effective_date"]
        exp = row["expiration_date"]
        is_active = eff <= check_date <= exp
        return {
            "policy_id": policy_id,
            "check_date": check_date,
            "effective_date": eff,
            "expiration_date": exp,
            "is_active": is_active
        }

    # ─── Step (Evaluation) ───

    def _compute_ground_truth(self):
        """Compute the ground truth investigation list using DB + workspace."""
        # Load fraud config
        config_path = os.path.join(self.workspace, "fraud_detection_config.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)

        indicators = config["fraud_indicators"]
        priority_levels = config["priority_levels"]
        output_cfg = config["output_format"]

        # Load contractor registry
        registry = {}
        reg_path = os.path.join(self.workspace, "contractor_registry.csv")
        with open(reg_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                registry[row["contractor_id"]] = row

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Get all pending claims
        c.execute("SELECT * FROM claims WHERE status = 'pending' ORDER BY claim_id")
        pending = [dict(r) for r in c.fetchall()]

        results = []

        for claim in pending:
            claim_id = claim["claim_id"]
            policy_id = claim["policy_id"]
            incident_date = claim["incident_date"]
            filed_date = claim["filed_date"]
            incident_zip = claim["incident_zip"]
            claimed_amount = claim["claimed_amount"]

            flags = []
            fraud_score = 0

            # Get policy info
            c.execute("SELECT * FROM policies WHERE policy_id = ?", (policy_id,))
            policy = dict(c.fetchone())

            # 1. Coverage gap check
            eff = policy["effective_date"]
            exp = policy["expiration_date"]
            if not (eff <= incident_date <= exp):
                flags.append("coverage_gap")
                fraud_score += indicators["coverage_gap"]["weight"]

            # 2. Weather mismatch check
            c.execute(
                "SELECT * FROM weather_records WHERE zip_code = ? AND date = ?",
                (incident_zip, incident_date)
            )
            weather = c.fetchone()
            if weather:
                weather = dict(weather)
                precip = weather["precipitation_mm"]
                wind = weather["wind_speed_kmh"]
                storm = weather["storm_event"]
            else:
                precip = 0.0
                wind = 0.0
                storm = None

            precip_thresh = indicators["weather_mismatch"]["precipitation_threshold_mm"]
            wind_thresh = indicators["weather_mismatch"]["wind_threshold_kmh"]
            if precip < precip_thresh and wind < wind_thresh and storm is None:
                flags.append("weather_mismatch")
                fraud_score += indicators["weather_mismatch"]["weight"]

            # 3. Estimate discrepancy check
            est_file = os.path.join(self.workspace, "estimates", f"{claim_id}.json")
            if os.path.exists(est_file):
                with open(est_file) as f:
                    est_data = json.load(f)
                estimates = est_data.get("estimates", [])
                if estimates:
                    max_estimate = max(e["estimate_amount"] for e in estimates)
                    excess_pct = ((claimed_amount - max_estimate) / max_estimate) * 100 if max_estimate > 0 else 0
                    if excess_pct > indicators["estimate_discrepancy"]["excess_threshold_pct"]:
                        flags.append("estimate_discrepancy")
                        fraud_score += indicators["estimate_discrepancy"]["weight"]

                    # 5. Unlicensed contractor check
                    for est in estimates:
                        ctr_id = est["contractor_id"]
                        if ctr_id in registry:
                            if registry[ctr_id]["license_status"] != "active":
                                flags.append("unlicensed_contractor")
                                fraud_score += indicators["unlicensed_contractor"]["weight"]
                                break

            # 4. Repeat claimant check
            lookback_months = indicators["repeat_claimant"]["lookback_months"]
            min_claims = indicators["repeat_claimant"]["min_prior_claims"]
            cutoff_date = str(
                (datetime.strptime(incident_date, "%Y-%m-%d") - timedelta(days=lookback_months * 30)).date()
            )
            c.execute(
                "SELECT COUNT(*) FROM claim_history WHERE policy_id = ? AND prior_claim_date >= ?",
                (policy_id, cutoff_date)
            )
            prior_count = c.fetchone()[0]
            if prior_count >= min_claims:
                flags.append("repeat_claimant")
                fraud_score += indicators["repeat_claimant"]["weight"]

            # 6. Late filing check
            max_days = indicators["late_filing"]["max_days_to_file"]
            days_diff = (datetime.strptime(filed_date, "%Y-%m-%d") - datetime.strptime(incident_date, "%Y-%m-%d")).days
            if days_diff > max_days:
                flags.append("late_filing")
                fraud_score += indicators["late_filing"]["weight"]

            if fraud_score > 0:
                # Determine priority level
                priority = "low"
                for level in ["critical", "high", "medium", "low"]:
                    if fraud_score >= priority_levels[level]["min_score"]:
                        priority = level
                        break

                results.append({
                    "claim_id": claim_id,
                    "policy_id": policy_id,
                    "holder_name": policy["holder_name"],
                    "fraud_score": fraud_score,
                    "flags": "; ".join(sorted(flags)),
                    "priority_level": priority,
                })

        conn.close()

        # Sort by fraud_score desc, then claim_id asc
        results.sort(key=lambda x: (-x["fraud_score"], x["claim_id"]))

        # Add priority rank
        for i, r in enumerate(results):
            r["priority_rank"] = i + 1

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
        gt_claim_ids = [r["claim_id"] for r in ground_truth]
        gt_by_id = {r["claim_id"]: r for r in ground_truth}

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ─── Criterion 1: investigation_list.csv exists and is parseable (10 pts) ───
        max_score += 10
        csv_path = os.path.join(self.workspace, "investigation_list.csv")
        csv_exists = False
        agent_rows = []
        expected_cols = ["claim_id", "policy_id", "holder_name", "fraud_score", "flags", "priority_level", "priority_rank"]

        if os.path.exists(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(c in cols for c in expected_cols):
                        agent_rows = list(reader)
                        csv_exists = True
                        eval_criteria["csv_format"] = {
                            "passed": True, "score": 10, "max_score": 10
                        }
                        total_score += 10
                    else:
                        missing = [c for c in expected_cols if c not in cols]
                        eval_criteria["csv_format"] = {
                            "passed": False, "score": 0, "max_score": 10,
                            "reason": f"Missing columns: {missing}"
                        }
            except Exception as e:
                eval_criteria["csv_format"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": f"CSV parse error: {str(e)}"
                }
        else:
            eval_criteria["csv_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "investigation_list.csv not found"
            }

        # ─── Criterion 2: Correct set of flagged claims (20 pts) ───
        max_score += 20
        if csv_exists:
            agent_claim_ids = [r["claim_id"] for r in agent_rows]
            agent_set = set(agent_claim_ids)
            gt_set = set(gt_claim_ids)

            if agent_set == gt_set:
                eval_criteria["claim_coverage"] = {
                    "passed": True, "score": 20, "max_score": 20
                }
                total_score += 20
            else:
                missing = gt_set - agent_set
                extra = agent_set - gt_set
                overlap = len(gt_set & agent_set)
                partial = int(20 * overlap / max(len(gt_set), 1))
                eval_criteria["claim_coverage"] = {
                    "passed": False, "score": partial, "max_score": 20,
                    "reason": f"Missing {len(missing)} claims, {len(extra)} extra claims"
                }
                total_score += partial
        else:
            eval_criteria["claim_coverage"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "CSV not available"
            }

        # ─── Criterion 3: Correct fraud scores (20 pts) ───
        max_score += 20
        if csv_exists and agent_rows:
            correct_scores = 0
            total_matched = 0
            for row in agent_rows:
                cid = row["claim_id"]
                if cid in gt_by_id:
                    total_matched += 1
                    try:
                        agent_score = int(float(row["fraud_score"]))
                        gt_score = gt_by_id[cid]["fraud_score"]
                        if agent_score == gt_score:
                            correct_scores += 1
                    except (ValueError, KeyError):
                        pass

            if total_matched > 0:
                ratio = correct_scores / total_matched
                pts = int(20 * ratio)
                eval_criteria["fraud_scores"] = {
                    "passed": ratio == 1.0, "score": pts, "max_score": 20,
                    "reason": None if ratio == 1.0 else f"{correct_scores}/{total_matched} scores correct"
                }
                total_score += pts
            else:
                eval_criteria["fraud_scores"] = {
                    "passed": False, "score": 0, "max_score": 20,
                    "reason": "No matching claims to score"
                }
        else:
            eval_criteria["fraud_scores"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "CSV not available"
            }

        # ─── Criterion 4: Correct flags (15 pts) ───
        max_score += 15
        if csv_exists and agent_rows:
            correct_flags = 0
            total_checked = 0
            for row in agent_rows:
                cid = row["claim_id"]
                if cid in gt_by_id:
                    total_checked += 1
                    agent_flags = set(f.strip() for f in row.get("flags", "").split(";") if f.strip())
                    gt_flags = set(f.strip() for f in gt_by_id[cid]["flags"].split(";") if f.strip())
                    if agent_flags == gt_flags:
                        correct_flags += 1

            if total_checked > 0:
                ratio = correct_flags / total_checked
                pts = int(15 * ratio)
                eval_criteria["flags_accuracy"] = {
                    "passed": ratio == 1.0, "score": pts, "max_score": 15,
                    "reason": None if ratio == 1.0 else f"{correct_flags}/{total_checked} flag sets correct"
                }
                total_score += pts
            else:
                eval_criteria["flags_accuracy"] = {
                    "passed": False, "score": 0, "max_score": 15,
                    "reason": "No matching claims"
                }
        else:
            eval_criteria["flags_accuracy"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "CSV not available"
            }

        # ─── Criterion 5: Correct sort order / priority rank (15 pts) ───
        max_score += 15
        if csv_exists and agent_rows:
            agent_order = [r["claim_id"] for r in agent_rows]
            gt_order = [r["claim_id"] for r in ground_truth]

            if agent_order == gt_order:
                eval_criteria["sort_order"] = {
                    "passed": True, "score": 15, "max_score": 15
                }
                total_score += 15
            else:
                # Partial credit: check how many are at correct position
                correct_pos = sum(1 for a, g in zip(agent_order, gt_order) if a == g)
                ratio = correct_pos / max(len(gt_order), 1)
                pts = int(15 * ratio)
                eval_criteria["sort_order"] = {
                    "passed": False, "score": pts, "max_score": 15,
                    "reason": f"{correct_pos}/{len(gt_order)} in correct position"
                }
                total_score += pts
        else:
            eval_criteria["sort_order"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "CSV not available"
            }

        # ─── Criterion 6: Priority levels correct (10 pts) ───
        max_score += 10
        if csv_exists and agent_rows:
            correct_levels = 0
            total_checked = 0
            for row in agent_rows:
                cid = row["claim_id"]
                if cid in gt_by_id:
                    total_checked += 1
                    if row.get("priority_level", "").strip() == gt_by_id[cid]["priority_level"]:
                        correct_levels += 1

            if total_checked > 0:
                ratio = correct_levels / total_checked
                pts = int(10 * ratio)
                eval_criteria["priority_levels"] = {
                    "passed": ratio == 1.0, "score": pts, "max_score": 10,
                    "reason": None if ratio == 1.0 else f"{correct_levels}/{total_checked} correct"
                }
                total_score += pts
            else:
                eval_criteria["priority_levels"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": "No matching claims"
                }
        else:
            eval_criteria["priority_levels"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "CSV not available"
            }

        # ─── Criterion 7: Response summary mentions top-3 critical claims (10 pts) ───
        max_score += 10
        top_critical = [r for r in ground_truth if r["priority_level"] == "critical"][:3]
        if not top_critical:
            top_critical = ground_truth[:3]

        if top_critical:
            found = sum(1 for r in top_critical if r["claim_id"] in action)
            ratio = found / len(top_critical)
            pts = int(10 * ratio)
            eval_criteria["response_summary"] = {
                "passed": ratio == 1.0, "score": pts, "max_score": 10,
                "reason": None if ratio == 1.0 else f"Only {found}/{len(top_critical)} top claims mentioned in response"
            }
            total_score += pts
        else:
            eval_criteria["response_summary"] = {
                "passed": True, "score": 10, "max_score": 10
            }
            total_score += 10

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return reward, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import os
        import json
        import csv
        import yaml

        # Step 1: Read fraud detection config from workspace
        config_path = os.path.join(self.workspace, "fraud_detection_config.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)

        indicators = config["fraud_indicators"]
        priority_levels = config["priority_levels"]
        output_cfg = config["output_format"]

        # Step 2: Read contractor registry from workspace
        registry = {}
        reg_path = os.path.join(self.workspace, "contractor_registry.csv")
        with open(reg_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                registry[row["contractor_id"]] = row

        # Step 3: Get all pending claims using tools (paginated)
        all_pending = []
        page = 1
        while True:
            result = self.tools["list_claims_by_status"](status="pending", page=page, page_size=20)
            all_pending.extend(result["claims"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 4: For each pending claim, gather details and check fraud indicators
        investigation = []
        tool_call_count = 0

        for claim_summary in all_pending:
            claim_id = claim_summary["claim_id"]
            policy_id = claim_summary["policy_id"]

            # Get claim details
            claim = self.tools["get_claim_details"](claim_id=claim_id)
            tool_call_count += 1

            # Get policy details
            policy = self.tools["get_policy_details"](policy_id=policy_id)
            tool_call_count += 1

            # Get weather data
            weather = self.tools["get_weather_data"](
                zip_code=claim["incident_zip"],
                date=claim["incident_date"]
            )
            tool_call_count += 1

            # Check policy active
            active_check = self.tools["check_policy_active"](
                policy_id=policy_id,
                check_date=claim["incident_date"]
            )
            tool_call_count += 1

            # Get prior claims
            history = self.tools["get_prior_claims"](policy_id=policy_id)
            tool_call_count += 1

            flags = []
            fraud_score = 0

            # Check 1: Coverage gap
            if not active_check.get("is_active", True):
                flags.append("coverage_gap")
                fraud_score += indicators["coverage_gap"]["weight"]

            # Check 2: Weather mismatch
            precip = weather.get("precipitation_mm", 0)
            wind = weather.get("wind_speed_kmh", 0)
            storm = weather.get("storm_event")
            if (precip < indicators["weather_mismatch"]["precipitation_threshold_mm"] and
                    wind < indicators["weather_mismatch"]["wind_threshold_kmh"] and
                    storm is None):
                flags.append("weather_mismatch")
                fraud_score += indicators["weather_mismatch"]["weight"]

            # Check 3: Estimate discrepancy - read from workspace
            est_file = os.path.join(self.workspace, "estimates", f"{claim_id}.json")
            if os.path.exists(est_file):
                with open(est_file) as f:
                    est_data = json.load(f)
                estimates = est_data.get("estimates", [])
                if estimates:
                    max_est = max(e["estimate_amount"] for e in estimates)
                    claimed = claim["claimed_amount"]
                    if max_est > 0:
                        excess_pct = ((claimed - max_est) / max_est) * 100
                        if excess_pct > indicators["estimate_discrepancy"]["excess_threshold_pct"]:
                            flags.append("estimate_discrepancy")
                            fraud_score += indicators["estimate_discrepancy"]["weight"]

                    # Check 5: Unlicensed contractor
                    for est in estimates:
                        ctr_id = est["contractor_id"]
                        if ctr_id in registry:
                            if registry[ctr_id]["license_status"] != "active":
                                flags.append("unlicensed_contractor")
                                fraud_score += indicators["unlicensed_contractor"]["weight"]
                                break

            # Check 4: Repeat claimant
            lookback_months = indicators["repeat_claimant"]["lookback_months"]
            min_claims = indicators["repeat_claimant"]["min_prior_claims"]
            from datetime import datetime, timedelta
            incident_dt = datetime.strptime(claim["incident_date"], "%Y-%m-%d")
            cutoff = incident_dt - timedelta(days=lookback_months * 30)
            cutoff_str = str(cutoff.date())

            prior_in_window = [
                p for p in history["prior_claims"]
                if p["prior_claim_date"] >= cutoff_str
            ]
            if len(prior_in_window) >= min_claims:
                flags.append("repeat_claimant")
                fraud_score += indicators["repeat_claimant"]["weight"]

            # Check 6: Late filing
            max_days = indicators["late_filing"]["max_days_to_file"]
            filed_dt = datetime.strptime(claim["filed_date"], "%Y-%m-%d")
            days_diff = (filed_dt - incident_dt).days
            if days_diff > max_days:
                flags.append("late_filing")
                fraud_score += indicators["late_filing"]["weight"]

            if fraud_score > 0:
                # Determine priority level
                priority = "low"
                for level in ["critical", "high", "medium", "low"]:
                    if fraud_score >= priority_levels[level]["min_score"]:
                        priority = level
                        break

                investigation.append({
                    "claim_id": claim_id,
                    "policy_id": policy_id,
                    "holder_name": policy["holder_name"],
                    "fraud_score": fraud_score,
                    "flags": "; ".join(sorted(flags)),
                    "priority_level": priority,
                })

        # Sort by fraud_score desc, then claim_id asc
        investigation.sort(key=lambda x: (-x["fraud_score"], x["claim_id"]))

        # Add priority_rank
        for i, r in enumerate(investigation):
            r["priority_rank"] = i + 1

        # Write investigation_list.csv
        csv_path = os.path.join(self.workspace, "investigation_list.csv")
        cols = output_cfg["columns"]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for r in investigation:
                writer.writerow(r)

        # Build action string (summary)
        top3 = investigation[:3]
        action_parts = [
            "Fraud investigation analysis complete.",
            f"Total flagged claims: {len(investigation)}.",
            "Top priority claims for investigation:"
        ]
        for r in top3:
            action_parts.append(
                f"- {r['claim_id']} (score: {r['fraud_score']}, "
                f"level: {r['priority_level']}, flags: {r['flags']})"
            )
        action = "\n".join(action_parts)

        # Count tool calls from pagination
        tool_call_count += page  # list_claims_by_status calls

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need >= 15"

        return self.step(action)
