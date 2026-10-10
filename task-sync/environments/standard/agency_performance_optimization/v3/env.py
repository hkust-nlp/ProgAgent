"""Environment for recruitment agency vendor performance evaluation task."""
from typing import Tuple, Dict, List, Any
import sqlite3
import os
import json
import csv
import math


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

    # ----------------------------------------------------------------
    # Tool methods
    # ----------------------------------------------------------------

    @tool(
        description=(
            "List all recruitment agencies with pagination. "
            "Returns agency_id and name for each agency."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of agencies per page (max 20). Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_agencies(self, page: int = 1, page_size: int = 20) -> dict:
        page_size = min(page_size, 20)
        conn = sqlite3.connect(self.db_path)
        total = conn.execute("SELECT COUNT(*) FROM agencies").fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT agency_id, name FROM agencies ORDER BY agency_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return json.dumps({
            "agencies": [{"agency_id": r[0], "name": r[1]} for r in rows],
            "page": page,
            "page_size": page_size,
            "total_count": total,
            "total_pages": total_pages,
        }, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Get detailed profile for a specific agency by ID. "
            "Returns name, specialty, region, founded_year, and fee_rate_pct."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agency_id": {
                    "type": "integer",
                    "description": "The agency ID.",
                },
            },
            "required": ["agency_id"],
        },
    )
    def get_agency_profile(self, agency_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT agency_id, name, specialty, region, founded_year, fee_rate_pct "
            "FROM agencies WHERE agency_id = ?",
            (agency_id,),
        ).fetchone()
        conn.close()
        if not row:
            return _envelope({"error": f"Agency {agency_id} not found"})
        return _envelope({
            "agency_id": row[0],
            "name": row[1],
            "specialty": row[2],
            "region": row[3],
            "founded_year": row[4],
            "fee_rate_pct": row[5],
        })

    @tool(
        description=(
            "Get all candidates submitted by a specific agency, with pagination. "
            "Each candidate includes their status (rejected_screening, rejected_interview, "
            "offer_declined, hired) and average interview score."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agency_id": {
                    "type": "integer",
                    "description": "The agency ID.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50). Default 50.",
                },
            },
            "required": ["agency_id"],
        },
    )
    def get_agency_candidates(self, agency_id: int, page: int = 1, page_size: int = 50) -> dict:
        page_size = min(page_size, 50)
        conn = sqlite3.connect(self.db_path)
        total = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE agency_id = ?", (agency_id,)
        ).fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT candidate_id, name, role_title, department, submission_date, "
            "experience_years, education_level, status "
            "FROM candidates WHERE agency_id = ? ORDER BY candidate_id LIMIT ? OFFSET ?",
            (agency_id, page_size, offset),
        ).fetchall()

        result = []
        for r in rows:
            cid = r[0]
            # Compute avg interview score for this candidate
            scores = conn.execute(
                "SELECT score FROM interviews WHERE candidate_id = ?", (cid,)
            ).fetchall()
            avg_score = (
                round(sum(s[0] for s in scores) / len(scores), 2) if scores else None
            )
            result.append({
                "candidate_id": cid,
                "name": r[1],
                "role_title": r[2],
                "department": r[3],
                "submission_date": r[4],
                "experience_years": r[5],
                "education_level": r[6],
                "status": r[7],
                "avg_interview_score": avg_score,
            })

        conn.close()
        return json.dumps({
            "candidates": result,
            "page": page,
            "page_size": page_size,
            "total_count": total,
            "total_pages": total_pages,
        }, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Get detailed interview history for a specific candidate. "
            "Returns each interview round with date, score, and pass/fail status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "candidate_id": {
                    "type": "integer",
                    "description": "The candidate ID.",
                },
            },
            "required": ["candidate_id"],
        },
    )
    def get_candidate_interviews(self, candidate_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT round_number, interview_date, score, passed "
            "FROM interviews WHERE candidate_id = ? ORDER BY round_number",
            (candidate_id,),
        ).fetchall()
        conn.close()
        return json.dumps({
            "candidate_id": candidate_id,
            "interviews": [
                {
                    "round_number": r[0],
                    "interview_date": r[1],
                    "score": r[2],
                    "passed": bool(r[3]),
                }
                for r in rows
            ],
        }, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Get hire record for a specific candidate. "
            "Returns offer_date, start_date, annual_salary, is_active, "
            "months_retained, and departure_reason if the candidate was hired. "
            "Returns found=false if no hire record exists."
        ),
        parameters={
            "type": "object",
            "properties": {
                "candidate_id": {
                    "type": "integer",
                    "description": "The candidate ID.",
                },
            },
            "required": ["candidate_id"],
        },
    )
    def get_hire_record(self, candidate_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT hire_id, offer_date, start_date, annual_salary, is_active, "
            "months_retained, departure_reason "
            "FROM hires WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        conn.close()
        if not row:
            return _envelope({"found": False, "candidate_id": candidate_id})
        return _envelope({
            "found": True,
            "candidate_id": candidate_id,
            "hire_id": row[0],
            "offer_date": row[1],
            "start_date": row[2],
            "annual_salary": row[3],
            "is_active": bool(row[4]),
            "months_retained": row[5],
            "departure_reason": row[6],
        })

    # ----------------------------------------------------------------
    # Evaluation
    # ----------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute ground truth scorecard from database and workspace files."""
        import yaml

        conn = sqlite3.connect(self.db_path)
        agencies = conn.execute(
            "SELECT agency_id, name FROM agencies ORDER BY agency_id"
        ).fetchall()
        candidates_rows = conn.execute(
            "SELECT candidate_id, agency_id, submission_date, status FROM candidates"
        ).fetchall()
        interviews_rows = conn.execute(
            "SELECT candidate_id, score FROM interviews"
        ).fetchall()
        hires_rows = conn.execute(
            "SELECT candidate_id, start_date, is_active, months_retained FROM hires"
        ).fetchall()
        conn.close()

        # Build lookups
        cand_by_agency = {}
        cand_sub_date = {}
        cand_status = {}
        for cid, aid, sub_d, status in candidates_rows:
            cand_by_agency.setdefault(aid, []).append(cid)
            cand_sub_date[cid] = sub_d
            cand_status[cid] = status

        iv_scores_by_cand = {}
        for cid, score in interviews_rows:
            iv_scores_by_cand.setdefault(cid, []).append(score)

        hire_info = {}
        for cid, start_d, is_act, mr in hires_rows:
            hire_info[cid] = {"start_date": start_d, "is_active": is_act, "months_retained": mr}

        # Load config
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            config = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "performance_tiers.json")) as f:
            tiers_config = json.load(f)

        # Load spend
        total_spend = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("monthly_spend_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        aid = int(row["agency_id"])
                        total_spend[aid] = total_spend.get(aid, 0) + float(row["total_spend"])

        retention_threshold = config["retention_threshold_months"]
        zero_defaults = config["zero_hire_defaults"]
        weights = config["metric_weights"]
        norms = config["normalization"]

        gt = {}
        for aid, aname in agencies:
            cids = cand_by_agency.get(aid, [])
            total_submissions = len(cids)
            hired_cids = [c for c in cids if cand_status[c] == "hired"]
            total_hires = len(hired_cids)

            conversion_rate = total_hires / total_submissions if total_submissions > 0 else 0.0

            if total_hires > 0:
                from datetime import datetime
                ttf_list = []
                retained_count = 0
                quality_per_cand = []

                for cid in hired_cids:
                    hi = hire_info.get(cid)
                    if hi:
                        sub_dt = datetime.strptime(cand_sub_date[cid], "%Y-%m-%d")
                        start_dt = datetime.strptime(hi["start_date"], "%Y-%m-%d")
                        ttf_list.append((start_dt - sub_dt).days)
                        if hi["is_active"] or hi["months_retained"] >= retention_threshold:
                            retained_count += 1

                    scores = iv_scores_by_cand.get(cid, [])
                    if scores:
                        quality_per_cand.append(sum(scores) / len(scores))

                avg_ttf = sum(ttf_list) / len(ttf_list) if ttf_list else zero_defaults["avg_time_to_fill_days"]
                retention_rate = retained_count / total_hires
                avg_quality = (
                    sum(quality_per_cand) / len(quality_per_cand)
                    if quality_per_cand
                    else zero_defaults["avg_quality_score"]
                )
                cph = total_spend.get(aid, 0) / total_hires
            else:
                avg_ttf = zero_defaults["avg_time_to_fill_days"]
                retention_rate = zero_defaults["retention_rate"]
                avg_quality = zero_defaults["avg_quality_score"]
                cph = zero_defaults["cost_per_hire"]

            # Compute overall score
            metrics = {
                "conversion_rate": conversion_rate,
                "avg_time_to_fill_days": avg_ttf,
                "retention_rate": retention_rate,
                "cost_per_hire": cph,
                "avg_quality_score": avg_quality,
            }
            overall = 0.0
            for mname, w in weights.items():
                val = metrics[mname]
                lo = norms[mname]["min"]
                hi_val = norms[mname]["max"]
                hib = norms[mname]["higher_is_better"]
                if hi_val > lo:
                    normed = (val - lo) / (hi_val - lo)
                    if not hib:
                        normed = 1.0 - normed
                else:
                    normed = 0.0
                normed = max(0.0, min(1.0, normed))
                overall += normed * w

            # Assign tier
            tier_defs = sorted(tiers_config["tiers"], key=lambda t: t["min_score"], reverse=True)
            tier = "Bronze"
            for td in tier_defs:
                if overall >= td["min_score"]:
                    tier = td["name"]
                    break

            # Assign recommendation
            if tier == "Platinum":
                rec = "Strongly Recommend Renewal"
            elif tier == "Gold":
                rec = "Recommend Renewal" if retention_rate >= 0.50 else "Conditional Renewal"
            elif tier == "Silver":
                if conversion_rate >= 0.15 and retention_rate >= 0.40:
                    rec = "Conditional Renewal"
                else:
                    rec = "Review Required"
            else:  # Bronze
                if total_hires >= 1 and conversion_rate >= 0.10:
                    rec = "Review Required"
                else:
                    rec = "Do Not Renew"

            gt[aid] = {
                "agency_name": aname,
                "total_submissions": total_submissions,
                "total_hires": total_hires,
                "conversion_rate": conversion_rate,
                "avg_time_to_fill_days": avg_ttf,
                "retention_rate": retention_rate,
                "cost_per_hire": cph,
                "avg_quality_score": avg_quality,
                "overall_score": overall,
                "tier": tier,
                "recommendation": rec,
            }

        return gt

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
        gt = self._compute_ground_truth()
        n_agencies = len(gt)

        # Sort ground truth by overall_score descending
        sorted_gt = sorted(gt.values(), key=lambda x: x["overall_score"], reverse=True)
        # When ties exist at the boundary, any agency tied at that score is an
        # acceptable member of top-3 / bottom-3. Build candidate sets accordingly.
        if len(sorted_gt) >= 3:
            top_cutoff = sorted_gt[2]["overall_score"]
            bot_cutoff = sorted_gt[-3]["overall_score"]
            top3_candidates = [a["agency_name"] for a in sorted_gt if a["overall_score"] >= top_cutoff]
            bottom3_candidates = [a["agency_name"] for a in sorted_gt if a["overall_score"] <= bot_cutoff]
        else:
            top3_candidates = [a["agency_name"] for a in sorted_gt]
            bottom3_candidates = [a["agency_name"] for a in sorted_gt]
        top3_names = top3_candidates
        bottom3_names = bottom3_candidates

        # Build name-indexed ground truth
        gt_by_name = {v["agency_name"]: v for v in gt.values()}

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ---- Criterion 1: Scorecard file structure (10 pts) ----
        crit_max = 10
        max_score += crit_max
        scorecard_path = os.path.join(self.workspace, "vendor_scorecard.csv")
        expected_cols = [
            "agency_name", "total_submissions", "total_hires", "conversion_rate",
            "avg_time_to_fill_days", "retention_rate", "cost_per_hire",
            "avg_quality_score", "overall_score", "tier", "recommendation",
        ]
        agent_rows = {}
        structure_ok = True
        structure_reason = ""

        if not os.path.exists(scorecard_path):
            structure_ok = False
            structure_reason = "vendor_scorecard.csv not found"
        else:
            try:
                with open(scorecard_path) as f:
                    reader = csv.DictReader(f)
                    headers = reader.fieldnames or []
                    if [h.strip() for h in headers] != expected_cols:
                        structure_ok = False
                        structure_reason = f"Column mismatch: got {headers}"
                    else:
                        for row in reader:
                            name = row["agency_name"].strip()
                            agent_rows[name] = row
                        if len(agent_rows) != n_agencies:
                            structure_ok = False
                            structure_reason = (
                                f"Expected {n_agencies} rows, got {len(agent_rows)}"
                            )
            except Exception as e:
                structure_ok = False
                structure_reason = f"Error reading CSV: {e}"

        crit_score = crit_max if structure_ok else 0
        total_score += crit_score
        eval_criteria["scorecard_structure"] = {
            "passed": structure_ok,
            "score": crit_score,
            "max_score": crit_max,
            "reason": structure_reason if not structure_ok else "",
        }

        # If structure failed, remaining criteria score 0
        if not agent_rows:
            for crit_name, crit_pts in [
                ("conversion_rate", 15), ("time_to_fill", 15),
                ("retention_rate", 15), ("cost_and_quality", 15),
                ("overall_scoring", 20), ("response_summary", 10),
            ]:
                max_score += crit_pts
                eval_criteria[crit_name] = {
                    "passed": False, "score": 0, "max_score": crit_pts,
                    "reason": "Scorecard file missing or malformed",
                }
            reward = total_score / max_score if max_score > 0 else 0.0
            return reward, {
                "eval_criteria": eval_criteria,
                "total_score": total_score,
                "max_score": max_score,
            }

        # Helper: count matches
        def _count_matches(metric, tolerance, parse_fn=float):
            hits = 0
            for name, gt_vals in gt_by_name.items():
                if name not in agent_rows:
                    continue
                try:
                    agent_val = parse_fn(agent_rows[name][metric].strip())
                    if abs(agent_val - gt_vals[metric]) <= tolerance:
                        hits += 1
                except (ValueError, KeyError):
                    pass
            return hits

        # ---- Criterion 2: Conversion rate accuracy (15 pts) ----
        crit_max = 15
        max_score += crit_max
        hits = _count_matches("conversion_rate", 0.005)
        crit_score = round(crit_max * hits / n_agencies, 2)
        total_score += crit_score
        eval_criteria["conversion_rate"] = {
            "passed": hits == n_agencies,
            "score": crit_score,
            "max_score": crit_max,
            "reason": "" if hits == n_agencies else f"{n_agencies - hits} agencies incorrect",
        }

        # ---- Criterion 3: Time-to-fill accuracy (15 pts) ----
        crit_max = 15
        max_score += crit_max
        hits = _count_matches("avg_time_to_fill_days", 2.0)
        crit_score = round(crit_max * hits / n_agencies, 2)
        total_score += crit_score
        eval_criteria["time_to_fill"] = {
            "passed": hits == n_agencies,
            "score": crit_score,
            "max_score": crit_max,
            "reason": "" if hits == n_agencies else f"{n_agencies - hits} agencies incorrect",
        }

        # ---- Criterion 4: Retention rate accuracy (15 pts) ----
        crit_max = 15
        max_score += crit_max
        hits = _count_matches("retention_rate", 0.005)
        crit_score = round(crit_max * hits / n_agencies, 2)
        total_score += crit_score
        eval_criteria["retention_rate"] = {
            "passed": hits == n_agencies,
            "score": crit_score,
            "max_score": crit_max,
            "reason": "" if hits == n_agencies else f"{n_agencies - hits} agencies incorrect",
        }

        # ---- Criterion 5: Cost-per-hire + quality score (15 pts) ----
        crit_max = 15
        max_score += crit_max
        cph_hits = _count_matches("cost_per_hire", 100.0)
        qs_hits = _count_matches("avg_quality_score", 0.05)
        cph_score = round(8 * cph_hits / n_agencies, 2)
        qs_score = round(7 * qs_hits / n_agencies, 2)
        crit_score = round(cph_score + qs_score, 2)
        total_score += crit_score
        eval_criteria["cost_and_quality"] = {
            "passed": cph_hits == n_agencies and qs_hits == n_agencies,
            "score": crit_score,
            "max_score": crit_max,
            "reason": (
                ""
                if cph_hits == n_agencies and qs_hits == n_agencies
                else f"cost_per_hire: {n_agencies-cph_hits} wrong; avg_quality_score: {n_agencies-qs_hits} wrong"
            ),
        }

        # ---- Criterion 6: Overall score + tier + recommendation (20 pts) ----
        crit_max = 20
        max_score += crit_max
        os_hits = _count_matches("overall_score", 0.01)
        tier_hits = 0
        rec_hits = 0
        for name, gt_vals in gt_by_name.items():
            if name not in agent_rows:
                continue
            if agent_rows[name].get("tier", "").strip() == gt_vals["tier"]:
                tier_hits += 1
            if agent_rows[name].get("recommendation", "").strip() == gt_vals["recommendation"]:
                rec_hits += 1

        os_score = round(8 * os_hits / n_agencies, 2)
        tier_score = round(6 * tier_hits / n_agencies, 2)
        rec_score = round(6 * rec_hits / n_agencies, 2)
        crit_score = round(os_score + tier_score + rec_score, 2)
        total_score += crit_score
        eval_criteria["overall_scoring"] = {
            "passed": os_hits == n_agencies and tier_hits == n_agencies and rec_hits == n_agencies,
            "score": crit_score,
            "max_score": crit_max,
            "reason": (
                ""
                if os_hits == n_agencies and tier_hits == n_agencies and rec_hits == n_agencies
                else (
                    f"overall_score: {n_agencies-os_hits} wrong; "
                    f"tier: {n_agencies-tier_hits} wrong; "
                    f"recommendation: {n_agencies-rec_hits} wrong"
                )
            ),
        }

        # ---- Criterion 7: Response summary (10 pts) ----
        crit_max = 10
        max_score += crit_max
        action_lower = (action or "").lower()
        top3_found = min(3, sum(1 for n in top3_names if n.lower() in action_lower))
        bot3_found = min(3, sum(1 for n in bottom3_names if n.lower() in action_lower))
        top_pts = round(5 * top3_found / 3, 2)
        bot_pts = round(5 * bot3_found / 3, 2)
        crit_score = round(top_pts + bot_pts, 2)
        total_score += crit_score
        eval_criteria["response_summary"] = {
            "passed": top3_found == 3 and bot3_found == 3,
            "score": crit_score,
            "max_score": crit_max,
            "reason": (
                ""
                if top3_found == 3 and bot3_found == 3
                else f"Top 3 found: {top3_found}/3, Bottom 3 found: {bot3_found}/3"
            ),
        }

        total_score = round(total_score, 2)
        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0
        return reward, {
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
        import yaml
        from datetime import datetime

        # 1. List all agencies
        all_agencies = []
        page = 1
        while True:
            res = json.loads(self.tools["list_agencies"](page=page, page_size=20))
            all_agencies.extend(res["agencies"])
            if page >= res["total_pages"]:
                break
            page += 1

        # 2. Read workspace config files
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            config = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "performance_tiers.json")) as f:
            tiers_config = json.load(f)

        with open(os.path.join(self.workspace, "renewal_rules.md")) as f:
            renewal_rules_text = f.read()

        # 3. Read all monthly spend files
        total_spend = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("monthly_spend_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        aid = int(row["agency_id"])
                        total_spend[aid] = total_spend.get(aid, 0) + float(row["total_spend"])

        retention_threshold = config["retention_threshold_months"]
        zero_defaults = config["zero_hire_defaults"]
        weights = config["metric_weights"]
        norms = config["normalization"]

        # 4. For each agency, get candidates and compute metrics
        scorecard = []
        tool_call_count = 0

        for agency in all_agencies:
            aid = agency["agency_id"]
            aname = agency["name"]

            # Get all candidates for this agency
            candidates = []
            page = 1
            while True:
                res = json.loads(self.tools["get_agency_candidates"](agency_id=aid, page=page, page_size=50))
                tool_call_count += 1
                candidates.extend(res["candidates"])
                if page >= res["total_pages"]:
                    break
                page += 1

            total_submissions = len(candidates)
            hired = [c for c in candidates if c["status"] == "hired"]
            total_hires = len(hired)

            conversion_rate = total_hires / total_submissions if total_submissions > 0 else 0.0

            if total_hires > 0:
                ttf_list = []
                retained_count = 0
                quality_per_cand = []

                for h in hired:
                    rec = json.loads(self.tools["get_hire_record"](candidate_id=h["candidate_id"])["content"][0]["text"])
                    tool_call_count += 1
                    if rec.get("found"):
                        sub_dt = datetime.strptime(h["submission_date"], "%Y-%m-%d")
                        start_dt = datetime.strptime(rec["start_date"], "%Y-%m-%d")
                        ttf_list.append((start_dt - sub_dt).days)
                        if rec["is_active"] or rec["months_retained"] >= retention_threshold:
                            retained_count += 1

                    if h["avg_interview_score"] is not None:
                        quality_per_cand.append(h["avg_interview_score"])

                avg_ttf = sum(ttf_list) / len(ttf_list) if ttf_list else zero_defaults["avg_time_to_fill_days"]
                retention_rate = retained_count / total_hires
                avg_quality = (
                    sum(quality_per_cand) / len(quality_per_cand)
                    if quality_per_cand
                    else zero_defaults["avg_quality_score"]
                )
                cph = total_spend.get(aid, 0) / total_hires
            else:
                avg_ttf = zero_defaults["avg_time_to_fill_days"]
                retention_rate = zero_defaults["retention_rate"]
                avg_quality = zero_defaults["avg_quality_score"]
                cph = zero_defaults["cost_per_hire"]

            # Compute overall score
            metrics_dict = {
                "conversion_rate": conversion_rate,
                "avg_time_to_fill_days": avg_ttf,
                "retention_rate": retention_rate,
                "cost_per_hire": cph,
                "avg_quality_score": avg_quality,
            }
            overall = 0.0
            for mname, w in weights.items():
                val = metrics_dict[mname]
                lo = norms[mname]["min"]
                hi_val = norms[mname]["max"]
                hib = norms[mname]["higher_is_better"]
                if hi_val > lo:
                    normed = (val - lo) / (hi_val - lo)
                    if not hib:
                        normed = 1.0 - normed
                else:
                    normed = 0.0
                normed = max(0.0, min(1.0, normed))
                overall += normed * w

            # Assign tier
            tier_defs = sorted(tiers_config["tiers"], key=lambda t: t["min_score"], reverse=True)
            tier = "Bronze"
            for td in tier_defs:
                if overall >= td["min_score"]:
                    tier = td["name"]
                    break

            # Assign recommendation
            if tier == "Platinum":
                rec_label = "Strongly Recommend Renewal"
            elif tier == "Gold":
                rec_label = "Recommend Renewal" if retention_rate >= 0.50 else "Conditional Renewal"
            elif tier == "Silver":
                if conversion_rate >= 0.15 and retention_rate >= 0.40:
                    rec_label = "Conditional Renewal"
                else:
                    rec_label = "Review Required"
            else:
                if total_hires >= 1 and conversion_rate >= 0.10:
                    rec_label = "Review Required"
                else:
                    rec_label = "Do Not Renew"

            scorecard.append({
                "agency_name": aname,
                "total_submissions": total_submissions,
                "total_hires": total_hires,
                "conversion_rate": conversion_rate,
                "avg_time_to_fill_days": avg_ttf,
                "retention_rate": retention_rate,
                "cost_per_hire": cph,
                "avg_quality_score": avg_quality,
                "overall_score": overall,
                "tier": tier,
                "recommendation": rec_label,
            })

        # Account for list_agencies calls
        tool_call_count += math.ceil(len(all_agencies) / 20)

        # Sort by overall_score descending
        scorecard.sort(key=lambda x: x["overall_score"], reverse=True)

        # Write vendor_scorecard.csv
        scorecard_path = os.path.join(self.workspace, "vendor_scorecard.csv")
        fieldnames = [
            "agency_name", "total_submissions", "total_hires", "conversion_rate",
            "avg_time_to_fill_days", "retention_rate", "cost_per_hire",
            "avg_quality_score", "overall_score", "tier", "recommendation",
        ]
        with open(scorecard_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in scorecard:
                writer.writerow({
                    "agency_name": row["agency_name"],
                    "total_submissions": row["total_submissions"],
                    "total_hires": row["total_hires"],
                    "conversion_rate": f"{row['conversion_rate']:.4f}",
                    "avg_time_to_fill_days": round(row["avg_time_to_fill_days"]),
                    "retention_rate": f"{row['retention_rate']:.4f}",
                    "cost_per_hire": f"{row['cost_per_hire']:.2f}",
                    "avg_quality_score": f"{row['avg_quality_score']:.2f}",
                    "overall_score": f"{row['overall_score']:.4f}",
                    "tier": row["tier"],
                    "recommendation": row["recommendation"],
                })

        # Build action string
        top3 = scorecard[:3]
        bottom3 = scorecard[-3:]

        # Find most differentiating metric
        metric_keys = ["conversion_rate", "avg_time_to_fill_days", "retention_rate",
                       "cost_per_hire", "avg_quality_score"]
        max_diff = 0
        diff_metric = "conversion_rate"
        for mk in metric_keys:
            top_avg = sum(r[mk] for r in top3) / 3
            bot_avg = sum(r[mk] for r in bottom3) / 3
            # Normalize difference to make comparable
            norm_range = norms[mk]["max"] - norms[mk]["min"]
            if norm_range > 0:
                diff = abs(top_avg - bot_avg) / norm_range
            else:
                diff = 0
            if diff > max_diff:
                max_diff = diff
                diff_metric = mk

        action_lines = ["Vendor Performance Analysis Complete.", ""]
        action_lines.append("Top 3 Highest-Scoring Agencies:")
        for r in top3:
            action_lines.append(
                f"  - {r['agency_name']}: Overall Score {r['overall_score']:.4f}, "
                f"Tier: {r['tier']}, Recommendation: {r['recommendation']}"
            )
        action_lines.append("")
        action_lines.append("Bottom 3 Lowest-Scoring Agencies:")
        for r in bottom3:
            action_lines.append(
                f"  - {r['agency_name']}: Overall Score {r['overall_score']:.4f}, "
                f"Tier: {r['tier']}, Recommendation: {r['recommendation']}"
            )
        action_lines.append("")
        action_lines.append(
            f"The metric that most differentiated top performers from bottom performers "
            f"was {diff_metric}."
        )

        action = "\n".join(action_lines)
        return self.step(action)
