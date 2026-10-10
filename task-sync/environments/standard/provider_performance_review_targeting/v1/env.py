import os
import csv
import json
import sqlite3
import math
from typing import Tuple, Dict, List, Any


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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List providers in the network, with optional filters. "
            "Returns a paginated list of providers (10 per page)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "specialty": {
                    "type": "string",
                    "description": "Filter by specialty name (exact match). Optional.",
                },
                "network_tier": {
                    "type": "string",
                    "description": "Filter by network tier (Tier1, Tier2, Tier3). Optional.",
                },
            },
            "required": [],
        },
    )
    def list_providers(self, page: int = 1, specialty: str = None,
                       network_tier: str = None):
        page_size = 10
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM providers WHERE 1=1"
        params = []
        if specialty:
            query += " AND specialty = ?"
            params.append(specialty)
        if network_tier:
            query += " AND network_tier = ?"
            params.append(network_tier)
        query += " ORDER BY provider_id"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start:start + page_size]
        return {
            "providers": [
                {
                    "provider_id": r["provider_id"],
                    "name": r["name"],
                    "specialty": r["specialty"],
                    "network_tier": r["network_tier"],
                    "region": r["region"],
                    "contract_start_date": r["contract_start_date"],
                }
                for r in page_rows
            ],
            "page": page,
            "total_providers": total,
            "has_more": start + page_size < total,
        }

    @tool(
        description=(
            "Retrieve all claims for a specific provider. "
            "Optionally filter by claim status (approved, denied, pending)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "string",
                    "description": "The provider ID, e.g. PRV00001.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: approved, denied, or pending. "
                                   "If omitted, returns all statuses.",
                },
            },
            "required": ["provider_id"],
        },
    )
    def get_provider_claims(self, provider_id: str, status: str = None):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM claims WHERE provider_id = ?"
        params = [provider_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY claim_id"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        claims = [
            {
                "claim_id": r["claim_id"],
                "member_id": r["member_id"],
                "service_code": r["service_code"],
                "service_date": r["service_date"],
                "billed_amount": r["billed_amount"],
                "paid_amount": r["paid_amount"],
                "status": r["status"],
            }
            for r in rows
        ]
        return {
            "provider_id": provider_id,
            "total_claims": len(claims),
            "claims": claims,
        }

    @tool(
        description=(
            "Retrieve satisfaction survey records for a specific provider. "
            "Returns survey IDs, overall ratings, and dates."
        ),
        parameters={
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "string",
                    "description": "The provider ID.",
                },
            },
            "required": ["provider_id"],
        },
    )
    def get_satisfaction_surveys(self, provider_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM satisfaction_surveys WHERE provider_id = ? "
            "ORDER BY survey_id",
            (provider_id,),
        ).fetchall()
        conn.close()
        surveys = [
            {
                "survey_id": r["survey_id"],
                "member_id": r["member_id"],
                "overall_rating": r["overall_rating"],
                "survey_date": r["survey_date"],
            }
            for r in rows
        ]
        return {
            "provider_id": provider_id,
            "total_surveys": len(surveys),
            "surveys": surveys,
        }

    @tool(
        description=(
            "Look up the base fee rate for a given service code from "
            "the in-network fee schedule."
        ),
        parameters={
            "type": "object",
            "properties": {
                "service_code": {
                    "type": "string",
                    "description": "The service code, e.g. SVC0001.",
                },
            },
            "required": ["service_code"],
        },
    )
    def lookup_fee_rate(self, service_code: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM fee_schedules WHERE service_code = ?",
            (service_code,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"No fee schedule found for {service_code}"}
        return {
            "service_code": row["service_code"],
            "base_rate": row["base_rate"],
            "effective_date": row["effective_date"],
        }

    @tool(
        description=(
            "Retrieve outgoing or incoming referral records for a provider. "
            "Direction 'outgoing' returns referrals made by this provider; "
            "'incoming' returns referrals received."
        ),
        parameters={
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "string",
                    "description": "The provider ID.",
                },
                "direction": {
                    "type": "string",
                    "enum": ["outgoing", "incoming"],
                    "description": "Direction of referrals. Defaults to 'outgoing'.",
                },
            },
            "required": ["provider_id"],
        },
    )
    def get_provider_referrals(self, provider_id: str,
                               direction: str = "outgoing"):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if direction == "incoming":
            col = "referred_provider_id"
        else:
            col = "referring_provider_id"
        rows = conn.execute(
            f"SELECT * FROM referrals WHERE {col} = ? ORDER BY referral_id",
            (provider_id,),
        ).fetchall()
        conn.close()
        referrals = [
            {
                "referral_id": r["referral_id"],
                "referring_provider_id": r["referring_provider_id"],
                "referred_provider_id": r["referred_provider_id"],
                "member_id": r["member_id"],
                "referral_date": r["referral_date"],
                "is_in_network": bool(r["is_in_network"]),
                "status": r["status"],
            }
            for r in rows
        ]
        return {
            "provider_id": provider_id,
            "direction": direction,
            "total_referrals": len(referrals),
            "referrals": referrals,
        }

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute the full ground-truth review list from DB + workspace."""
        import yaml

        ws = self.workspace

        # --- Read workspace configs ---
        with open(os.path.join(ws, "review_criteria.yaml")) as f:
            criteria = yaml.safe_load(f)
        with open(os.path.join(ws, "satisfaction_weights.yaml")) as f:
            sat_wt = yaml.safe_load(f)["weights"]
        with open(os.path.join(ws, "network_tier_config.json")) as f:
            tier_cfg = json.load(f)

        # Specialty benchmarks
        benchmarks = {}
        with open(os.path.join(ws, "specialty_benchmarks.csv")) as f:
            for row in csv.DictReader(f):
                benchmarks[row["specialty"]] = float(row["benchmark_cost_ratio"])

        # Exclusion list
        excluded_ids = set()
        with open(os.path.join(ws, "exclusion_list.md")) as f:
            for line in f:
                line = line.strip()
                if line.startswith("PRV"):
                    excluded_ids.add(line.split()[0])

        # Claims detail (workspace CSVs)
        claims_adj = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("claims_detail_") and fname.endswith(".csv"):
                with open(os.path.join(ws, fname)) as f:
                    for row in csv.DictReader(f):
                        claims_adj[row["claim_id"]] = float(
                            row["cost_adjustment_factor"])

        # Survey dimension scores (workspace JSONs)
        survey_dims = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("survey_responses_") and fname.endswith(".json"):
                with open(os.path.join(ws, fname)) as f:
                    for item in json.load(f):
                        survey_dims[item["survey_id"]] = item

        # Referral urgency (workspace TXTs)
        ref_urgency = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("referral_annotations_") and fname.endswith(".txt"):
                with open(os.path.join(ws, fname)) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("referral_id"):
                            continue
                        parts = line.split("|")
                        if len(parts) == 2:
                            ref_urgency[parts[0]] = parts[1]

        # --- Query DB ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        providers = conn.execute(
            "SELECT * FROM providers ORDER BY provider_id"
        ).fetchall()

        review_list = []
        for prov in providers:
            pid = prov["provider_id"]
            if pid in excluded_ids:
                continue
            tier = prov["network_tier"]
            spec = prov["specialty"]
            tier_mult = tier_cfg[tier]["rate_multiplier"]
            benchmark = benchmarks.get(spec, 1.0)

            # Cost ratio
            claims = conn.execute(
                "SELECT * FROM claims WHERE provider_id=? AND status='approved'",
                (pid,),
            ).fetchall()
            if len(claims) < criteria["min_claims_required"]:
                continue
            total_paid = 0.0
            total_expected = 0.0
            for c in claims:
                fee_row = conn.execute(
                    "SELECT base_rate FROM fee_schedules WHERE service_code=?",
                    (c["service_code"],),
                ).fetchone()
                base_rate = fee_row["base_rate"] if fee_row else 0.0
                adj = claims_adj.get(c["claim_id"], 1.0)
                total_expected += base_rate * tier_mult * adj
                total_paid += c["paid_amount"]
            raw_cost_ratio = total_paid / total_expected if total_expected > 0 else 0.0
            adjusted_cost_ratio = raw_cost_ratio / benchmark if benchmark > 0 else 0.0

            # Satisfaction
            surveys = conn.execute(
                "SELECT * FROM satisfaction_surveys WHERE provider_id=?",
                (pid,),
            ).fetchall()
            if not surveys:
                continue
            weighted_sats = []
            for s in surveys:
                sid = s["survey_id"]
                dims = survey_dims.get(sid, {})
                ws_val = (
                    s["overall_rating"] * sat_wt["overall"]
                    + dims.get("communication_score", s["overall_rating"]) * sat_wt["communication"]
                    + dims.get("timeliness_score", s["overall_rating"]) * sat_wt["timeliness"]
                    + dims.get("outcome_score", s["overall_rating"]) * sat_wt["outcome"]
                )
                weighted_sats.append(ws_val)
            avg_sat = sum(weighted_sats) / len(weighted_sats)

            # Referral leakage
            refs = conn.execute(
                "SELECT * FROM referrals WHERE referring_provider_id=?",
                (pid,),
            ).fetchall()
            leakage_count = 0
            non_urgent_total = 0
            for r in refs:
                urgency = ref_urgency.get(r["referral_id"], "medium")
                if urgency != "high":
                    non_urgent_total += 1
                    if not r["is_in_network"]:
                        leakage_count += 1
            leakage_rate = (leakage_count / non_urgent_total
                            if non_urgent_total > 0 else 0.0)

            is_high_cost = adjusted_cost_ratio > criteria["cost_ratio_threshold"]
            is_low_sat = avg_sat < criteria["satisfaction_floor"]

            if is_high_cost and is_low_sat:
                cw = criteria["composite_weights"]
                cost_excess = max(0.0, adjusted_cost_ratio - criteria["cost_ratio_threshold"])
                sat_deficit = max(0.0, criteria["satisfaction_floor"] - avg_sat)
                composite = (
                    cw["cost_excess"] * cost_excess
                    + cw["satisfaction_deficit"] * sat_deficit
                    + cw["referral_leakage"] * leakage_rate
                )
                high_leakage = leakage_rate > criteria["referral_leakage_threshold"]
                review_list.append({
                    "provider_id": pid,
                    "provider_name": prov["name"],
                    "specialty": spec,
                    "network_tier": tier,
                    "adjusted_cost_ratio": round(adjusted_cost_ratio, 4),
                    "weighted_satisfaction": round(avg_sat, 2),
                    "referral_leakage_rate": round(leakage_rate, 4),
                    "composite_score": round(composite, 4),
                    "high_leakage_flag": high_leakage,
                })

        conn.close()
        review_list.sort(key=lambda x: (-x["composite_score"], x["provider_id"]))
        return review_list

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
        gt_ids = [r["provider_id"] for r in ground_truth]
        gt_map = {r["provider_id"]: r for r in ground_truth}

        eval_criteria = {}
        total_score = 0
        max_score = 0

        EXPECTED_COLS = [
            "provider_id", "provider_name", "specialty", "network_tier",
            "adjusted_cost_ratio", "weighted_satisfaction",
            "referral_leakage_rate", "composite_score", "high_leakage_flag",
        ]

        # --- Criterion 1: File exists with correct columns (10 pts) ---
        cr1_max = 10
        cr1_score = 0
        cr1_reason = ""
        review_path = os.path.join(self.workspace, "review_list.csv")
        agent_rows = []
        if os.path.exists(review_path):
            try:
                with open(review_path) as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    agent_rows = list(reader)
                if all(c in cols for c in EXPECTED_COLS):
                    cr1_score = cr1_max
                else:
                    missing = [c for c in EXPECTED_COLS if c not in cols]
                    cr1_reason = f"Missing columns: {missing}"
                    cr1_score = 4
            except Exception as e:
                cr1_reason = f"Error reading CSV: {e}"
        else:
            cr1_reason = "review_list.csv not found in workspace"
        eval_criteria["file_structure"] = {
            "passed": cr1_score == cr1_max,
            "score": cr1_score,
            "max_score": cr1_max,
            "reason": cr1_reason,
        }

        # --- Criterion 2: Correct provider set (25 pts) ---
        cr2_max = 25
        cr2_score = 0
        cr2_reason = ""
        agent_ids = [r.get("provider_id", "").strip() for r in agent_rows]
        if gt_ids:
            gt_set = set(gt_ids)
            agent_set = set(agent_ids)
            correct = gt_set & agent_set
            extra = agent_set - gt_set
            missing_set = gt_set - agent_set
            precision = len(correct) / len(agent_set) if agent_set else 0
            recall = len(correct) / len(gt_set) if gt_set else 0
            f1 = (2 * precision * recall / (precision + recall)
                   if (precision + recall) > 0 else 0)
            cr2_score = round(cr2_max * f1)
            if cr2_score < cr2_max:
                cr2_reason = (
                    f"Expected {len(gt_set)} providers, got {len(agent_set)}. "
                    f"Missing: {sorted(missing_set)}, Extra: {sorted(extra)}"
                )
        else:
            if not agent_ids:
                cr2_score = cr2_max
            else:
                cr2_reason = "Ground truth has 0 providers but agent produced some"
        eval_criteria["provider_set"] = {
            "passed": cr2_score == cr2_max,
            "score": cr2_score,
            "max_score": cr2_max,
            "reason": cr2_reason,
        }

        # Build agent map for subsequent checks
        agent_map = {}
        for r in agent_rows:
            pid = r.get("provider_id", "").strip()
            if pid:
                agent_map[pid] = r

        # --- Criterion 3: Adjusted cost ratios (15 pts) ---
        cr3_max = 15
        cr3_correct = 0
        cr3_total = 0
        cr3_reason = ""
        for pid in gt_ids:
            if pid in agent_map:
                cr3_total += 1
                try:
                    agent_val = float(agent_map[pid].get("adjusted_cost_ratio", 0))
                    gt_val = gt_map[pid]["adjusted_cost_ratio"]
                    if abs(agent_val - gt_val) < 0.02:
                        cr3_correct += 1
                except (ValueError, TypeError):
                    pass
        ratio3 = cr3_correct / cr3_total if cr3_total > 0 else 0
        cr3_score = round(cr3_max * ratio3)
        if cr3_score < cr3_max:
            cr3_reason = f"{cr3_correct}/{cr3_total} cost ratios within tolerance"
        eval_criteria["cost_ratios"] = {
            "passed": cr3_score == cr3_max,
            "score": cr3_score,
            "max_score": cr3_max,
            "reason": cr3_reason,
        }

        # --- Criterion 4: Weighted satisfaction (15 pts) ---
        cr4_max = 15
        cr4_correct = 0
        cr4_total = 0
        cr4_reason = ""
        for pid in gt_ids:
            if pid in agent_map:
                cr4_total += 1
                try:
                    agent_val = float(agent_map[pid].get("weighted_satisfaction", 0))
                    gt_val = gt_map[pid]["weighted_satisfaction"]
                    if abs(agent_val - gt_val) < 0.05:
                        cr4_correct += 1
                except (ValueError, TypeError):
                    pass
        ratio4 = cr4_correct / cr4_total if cr4_total > 0 else 0
        cr4_score = round(cr4_max * ratio4)
        if cr4_score < cr4_max:
            cr4_reason = f"{cr4_correct}/{cr4_total} satisfaction scores within tolerance"
        eval_criteria["satisfaction_scores"] = {
            "passed": cr4_score == cr4_max,
            "score": cr4_score,
            "max_score": cr4_max,
            "reason": cr4_reason,
        }

        # --- Criterion 5: Referral leakage rates (10 pts) ---
        cr5_max = 10
        cr5_correct = 0
        cr5_total = 0
        cr5_reason = ""
        for pid in gt_ids:
            if pid in agent_map:
                cr5_total += 1
                try:
                    agent_val = float(agent_map[pid].get("referral_leakage_rate", 0))
                    gt_val = gt_map[pid]["referral_leakage_rate"]
                    if abs(agent_val - gt_val) < 0.02:
                        cr5_correct += 1
                except (ValueError, TypeError):
                    pass
        ratio5 = cr5_correct / cr5_total if cr5_total > 0 else 0
        cr5_score = round(cr5_max * ratio5)
        if cr5_score < cr5_max:
            cr5_reason = f"{cr5_correct}/{cr5_total} leakage rates within tolerance"
        eval_criteria["leakage_rates"] = {
            "passed": cr5_score == cr5_max,
            "score": cr5_score,
            "max_score": cr5_max,
            "reason": cr5_reason,
        }

        # --- Criterion 6: Composite scores & sort order (15 pts) ---
        cr6_max = 15
        cr6_score = 0
        cr6_reason = ""
        # Score accuracy (10 pts)
        cr6a_correct = 0
        cr6a_total = 0
        for pid in gt_ids:
            if pid in agent_map:
                cr6a_total += 1
                try:
                    agent_val = float(agent_map[pid].get("composite_score", 0))
                    gt_val = gt_map[pid]["composite_score"]
                    if abs(agent_val - gt_val) < 0.02:
                        cr6a_correct += 1
                except (ValueError, TypeError):
                    pass
        ratio6a = cr6a_correct / cr6a_total if cr6a_total > 0 else 0
        cr6_score += round(10 * ratio6a)

        # Sort order (5 pts)
        if agent_ids and gt_ids:
            # Check if agent list is sorted by composite_score desc, provider_id asc
            correct_order = True
            for idx in range(len(agent_ids) - 1):
                a = agent_map.get(agent_ids[idx], {})
                b = agent_map.get(agent_ids[idx + 1], {})
                try:
                    sa = float(a.get("composite_score", 0))
                    sb = float(b.get("composite_score", 0))
                    if sa < sb:
                        correct_order = False
                        break
                    if abs(sa - sb) < 1e-9:
                        if a.get("provider_id", "") > b.get("provider_id", ""):
                            correct_order = False
                            break
                except (ValueError, TypeError):
                    correct_order = False
                    break
            if correct_order:
                cr6_score += 5
            else:
                cr6_reason = "Sort order incorrect"
        elif not agent_ids and not gt_ids:
            cr6_score += 5
        else:
            cr6_reason = "Cannot verify sort order"
        if cr6_score < cr6_max and not cr6_reason:
            cr6_reason = f"{cr6a_correct}/{cr6a_total} composite scores within tolerance"
        eval_criteria["composite_and_sort"] = {
            "passed": cr6_score == cr6_max,
            "score": cr6_score,
            "max_score": cr6_max,
            "reason": cr6_reason,
        }

        # --- Criterion 7: High leakage flag (10 pts) ---
        cr7_max = 10
        cr7_correct = 0
        cr7_total = 0
        cr7_reason = ""
        for pid in gt_ids:
            if pid in agent_map:
                cr7_total += 1
                agent_flag_raw = agent_map[pid].get("high_leakage_flag", "").strip()
                agent_flag = agent_flag_raw.lower() in ("true", "1", "yes")
                gt_flag = gt_map[pid]["high_leakage_flag"]
                if agent_flag == gt_flag:
                    cr7_correct += 1
        ratio7 = cr7_correct / cr7_total if cr7_total > 0 else 0
        cr7_score = round(cr7_max * ratio7)
        if cr7_score < cr7_max:
            cr7_reason = f"{cr7_correct}/{cr7_total} flags correct"
        eval_criteria["high_leakage_flag"] = {
            "passed": cr7_score == cr7_max,
            "score": cr7_score,
            "max_score": cr7_max,
            "reason": cr7_reason,
        }

        # --- Aggregate ---
        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())
        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

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

        ws = self.workspace
        tool_calls = 0

        # ---- 1. Read workspace configuration files ----
        with open(os.path.join(ws, "review_criteria.yaml")) as f:
            criteria = yaml.safe_load(f)
        with open(os.path.join(ws, "satisfaction_weights.yaml")) as f:
            sat_wt = yaml.safe_load(f)["weights"]
        with open(os.path.join(ws, "network_tier_config.json")) as f:
            tier_cfg = json.load(f)

        benchmarks = {}
        with open(os.path.join(ws, "specialty_benchmarks.csv")) as f:
            for row in csv.DictReader(f):
                benchmarks[row["specialty"]] = float(row["benchmark_cost_ratio"])

        excluded_ids = set()
        with open(os.path.join(ws, "exclusion_list.md")) as f:
            for line in f:
                line = line.strip()
                if line.startswith("PRV"):
                    excluded_ids.add(line.split()[0])

        # Read claims detail CSVs
        claims_adj = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("claims_detail_") and fname.endswith(".csv"):
                with open(os.path.join(ws, fname)) as f:
                    for row in csv.DictReader(f):
                        claims_adj[row["claim_id"]] = float(
                            row["cost_adjustment_factor"])

        # Read survey dimension JSONs
        survey_dims = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("survey_responses_") and fname.endswith(".json"):
                with open(os.path.join(ws, fname)) as f:
                    for item in json.load(f):
                        survey_dims[item["survey_id"]] = item

        # Read referral urgency TXTs
        ref_urgency = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("referral_annotations_") and fname.endswith(".txt"):
                with open(os.path.join(ws, fname)) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("referral_id"):
                            continue
                        parts = line.split("|")
                        if len(parts) == 2:
                            ref_urgency[parts[0]] = parts[1]

        # ---- 2. Discover all providers via tool ----
        all_providers = []
        page = 1
        while True:
            result = self.tools["list_providers"](page=page)
            tool_calls += 1
            all_providers.extend(result["providers"])
            if not result["has_more"]:
                break
            page += 1

        # ---- 3. Cache fee rates ----
        fee_cache = {}

        def get_fee(service_code):
            nonlocal tool_calls
            if service_code not in fee_cache:
                res = self.tools["lookup_fee_rate"](service_code=service_code)
                tool_calls += 1
                fee_cache[service_code] = res.get("base_rate", 0.0)
            return fee_cache[service_code]

        # ---- 4. Process each provider ----
        review_list = []
        for prov in all_providers:
            pid = prov["provider_id"]
            if pid in excluded_ids:
                continue

            tier = prov["network_tier"]
            spec = prov["specialty"]
            tier_mult = tier_cfg[tier]["rate_multiplier"]
            benchmark = benchmarks.get(spec, 1.0)

            # Claims
            claims_res = self.tools["get_provider_claims"](
                provider_id=pid, status="approved")
            tool_calls += 1
            claims = claims_res["claims"]

            if len(claims) < criteria["min_claims_required"]:
                continue

            total_paid = 0.0
            total_expected = 0.0
            for c in claims:
                base_rate = get_fee(c["service_code"])
                adj = claims_adj.get(c["claim_id"], 1.0)
                expected = base_rate * tier_mult * adj
                total_paid += c["paid_amount"]
                total_expected += expected
            raw_cost_ratio = total_paid / total_expected if total_expected > 0 else 0.0
            adjusted_cost_ratio = raw_cost_ratio / benchmark if benchmark > 0 else 0.0

            # Satisfaction
            sat_res = self.tools["get_satisfaction_surveys"](provider_id=pid)
            tool_calls += 1
            surveys = sat_res["surveys"]
            if not surveys:
                continue
            weighted_sats = []
            for s in surveys:
                sid = s["survey_id"]
                dims = survey_dims.get(sid, {})
                ws_val = (
                    s["overall_rating"] * sat_wt["overall"]
                    + dims.get("communication_score", s["overall_rating"]) * sat_wt["communication"]
                    + dims.get("timeliness_score", s["overall_rating"]) * sat_wt["timeliness"]
                    + dims.get("outcome_score", s["overall_rating"]) * sat_wt["outcome"]
                )
                weighted_sats.append(ws_val)
            avg_sat = sum(weighted_sats) / len(weighted_sats)

            # Referrals
            ref_res = self.tools["get_provider_referrals"](
                provider_id=pid, direction="outgoing")
            tool_calls += 1
            referrals = ref_res["referrals"]
            leakage_count = 0
            non_urgent_total = 0
            for r in referrals:
                urgency = ref_urgency.get(r["referral_id"], "medium")
                if urgency != "high":
                    non_urgent_total += 1
                    if not r["is_in_network"]:
                        leakage_count += 1
            leakage_rate = (leakage_count / non_urgent_total
                            if non_urgent_total > 0 else 0.0)

            is_high_cost = adjusted_cost_ratio > criteria["cost_ratio_threshold"]
            is_low_sat = avg_sat < criteria["satisfaction_floor"]

            if is_high_cost and is_low_sat:
                cw = criteria["composite_weights"]
                cost_excess = max(0.0, adjusted_cost_ratio - criteria["cost_ratio_threshold"])
                sat_deficit = max(0.0, criteria["satisfaction_floor"] - avg_sat)
                composite = (
                    cw["cost_excess"] * cost_excess
                    + cw["satisfaction_deficit"] * sat_deficit
                    + cw["referral_leakage"] * leakage_rate
                )
                high_leakage = leakage_rate > criteria["referral_leakage_threshold"]
                review_list.append({
                    "provider_id": pid,
                    "provider_name": prov["name"],
                    "specialty": spec,
                    "network_tier": tier,
                    "adjusted_cost_ratio": round(adjusted_cost_ratio, 4),
                    "weighted_satisfaction": round(avg_sat, 2),
                    "referral_leakage_rate": round(leakage_rate, 4),
                    "composite_score": round(composite, 4),
                    "high_leakage_flag": high_leakage,
                })

        review_list.sort(key=lambda x: (-x["composite_score"], x["provider_id"]))

        # ---- 5. Write deliverables ----
        output_path = os.path.join(ws, "review_list.csv")
        fieldnames = [
            "provider_id", "provider_name", "specialty", "network_tier",
            "adjusted_cost_ratio", "weighted_satisfaction",
            "referral_leakage_rate", "composite_score", "high_leakage_flag",
        ]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in review_list:
                writer.writerow({
                    **row,
                    "high_leakage_flag": str(row["high_leakage_flag"]),
                })

        # ---- 6. Build action string ----
        action_parts = [
            f"The targeted review list has been generated with "
            f"{len(review_list)} providers identified for contract renegotiation.",
            "",
            "Top providers by composite score:",
        ]
        for i, r in enumerate(review_list[:3]):
            action_parts.append(
                f"{i+1}. {r['provider_id']} ({r['provider_name']}): "
                f"composite_score={r['composite_score']}"
            )
        action_parts.append("")
        action_parts.append("The review list has been saved to review_list.csv.")
        action = "\n".join(action_parts)

        assert tool_calls >= 15, (
            f"verify used only {tool_calls} tool calls (minimum 15)")

        return self.step(action)
