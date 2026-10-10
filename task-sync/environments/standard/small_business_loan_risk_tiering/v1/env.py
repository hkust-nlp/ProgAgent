import sqlite3
import os
import json
import csv
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

    # ===================================================================
    # Tool methods
    # ===================================================================

    @tool(
        description="List loan applications filtered by status. Returns a paginated list of application summaries.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "approved", "denied", "withdrawn"],
                    "description": "Filter applications by this status.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20).",
                },
            },
            "required": ["status", "page", "page_size"],
        },
    )
    def list_applications(self, status: str, page: int, page_size: int) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) as cnt FROM loan_applications WHERE status = ?",
            (status,),
        )
        total = c.fetchone()["cnt"]
        c.execute(
            "SELECT application_id, business_name, industry_code, submission_date "
            "FROM loan_applications WHERE status = ? "
            "ORDER BY submission_date ASC, application_id ASC "
            "LIMIT ? OFFSET ?",
            (status, page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "results": rows,
        }

    @tool(
        description="Get full details of a single loan application by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "application_id": {
                    "type": "string",
                    "description": "The application identifier, e.g. APP_0001.",
                },
            },
            "required": ["application_id"],
        },
    )
    def get_application(self, application_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM loan_applications WHERE application_id = ?",
            (application_id,),
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Application {application_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Retrieve bank transaction history for an application within a date range. "
            "Returns individual transactions sorted by date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "application_id": {
                    "type": "string",
                    "description": "The application identifier.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (inclusive) in YYYY-MM-DD format.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (inclusive) in YYYY-MM-DD format.",
                },
            },
            "required": ["application_id", "start_date", "end_date"],
        },
    )
    def get_transaction_history(
        self, application_id: str, start_date: str, end_date: str
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT transaction_id, transaction_date, amount, type, category "
            "FROM bank_transactions "
            "WHERE application_id = ? AND transaction_date >= ? AND transaction_date <= ? "
            "ORDER BY transaction_date ASC",
            (application_id, start_date, end_date),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"application_id": application_id, "transactions": rows}

    @tool(
        description="List all collateral assets pledged for a given loan application.",
        parameters={
            "type": "object",
            "properties": {
                "application_id": {
                    "type": "string",
                    "description": "The application identifier.",
                },
            },
            "required": ["application_id"],
        },
    )
    def get_collateral_assets(self, application_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT asset_id, asset_type, description, declared_value "
            "FROM collateral_assets WHERE application_id = ?",
            (application_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"application_id": application_id, "assets": rows}

    @tool(
        description="Get the current market valuation for a specific collateral asset.",
        parameters={
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "The asset identifier, e.g. AST_0001.",
                },
            },
            "required": ["asset_id"],
        },
    )
    def get_collateral_valuation(self, asset_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT asset_id, asset_type, current_market_value "
            "FROM collateral_assets WHERE asset_id = ?",
            (asset_id,),
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Asset {asset_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Check a lender's current and maximum exposure for a specific industry. "
            "Returns the exposure figures or an error if the combination is not found."
        ),
        parameters={
            "type": "object",
            "properties": {
                "lender_id": {
                    "type": "string",
                    "description": "The lender identifier, e.g. L001.",
                },
                "industry_code": {
                    "type": "string",
                    "description": "The industry code, e.g. RET, MFG, TECH.",
                },
            },
            "required": ["lender_id", "industry_code"],
        },
    )
    def check_lender_exposure(self, lender_id: str, industry_code: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT lender_id, industry_code, current_exposure, max_exposure "
            "FROM lender_portfolios "
            "WHERE lender_id = ? AND industry_code = ?",
            (lender_id, industry_code),
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"No portfolio entry for lender {lender_id} / industry {industry_code}."}
        return dict(row)

    # ===================================================================
    # Ground-truth computation helpers (used by step & verify)
    # ===================================================================

    def _load_industry_default_rates(self) -> Dict[str, float]:
        rates = {}
        path = os.path.join(self.workspace, "industry_default_rates.csv")
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rates[row["industry_code"]] = float(row["default_rate_pct"])
        return rates

    def _load_risk_config(self) -> dict:
        import yaml  # noqa
        path = os.path.join(self.workspace, "risk_config.yaml")
        with open(path) as f:
            return yaml.safe_load(f)

    def _compute_cash_flow_class(self, application_id: str) -> str:
        """Classify cash flow using the 6-month rule from lending_policy.md."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT transaction_date, amount, type FROM bank_transactions "
            "WHERE application_id = ? AND transaction_date >= '2025-09-20' "
            "AND transaction_date <= '2026-03-20' "
            "ORDER BY transaction_date ASC",
            (application_id,),
        )
        txns = c.fetchall()
        conn.close()

        if not txns:
            return "stable"

        monthly = {}
        for t in txns:
            month_key = t["transaction_date"][:7]  # YYYY-MM
            if month_key not in monthly:
                monthly[month_key] = 0.0
            if t["type"] == "credit":
                monthly[month_key] += t["amount"]
            else:
                monthly[month_key] -= t["amount"]

        sorted_months = sorted(monthly.keys())
        if len(sorted_months) <= 1:
            # Only one month → can't split into halves meaningfully
            overall_avg = sum(monthly.values()) / len(sorted_months)
            if overall_avg < 0:
                return "negative"
            return "stable"

        # Split: earlier half gets the middle element on odd count
        mid = (len(sorted_months) + 1) // 2
        earlier = sorted_months[:mid]
        later = sorted_months[mid:]

        if not earlier or not later:
            return "stable"

        overall_avg = sum(monthly.values()) / len(sorted_months)
        if overall_avg < 0:
            return "negative"

        earlier_avg = sum(monthly[m] for m in earlier) / len(earlier)
        later_avg = sum(monthly[m] for m in later) / len(later)

        if earlier_avg == 0:
            # Avoid division by zero
            if later_avg > 0:
                return "positive_trend"
            elif later_avg < 0:
                return "declining"
            return "stable"

        ratio = (later_avg - earlier_avg) / abs(earlier_avg)
        if ratio > 0.05:
            return "positive_trend"
        elif ratio < -0.05:
            return "declining"
        return "stable"

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the full ground-truth approval queue."""
        cfg = self._load_risk_config()
        default_rates = self._load_industry_default_rates()
        scoring = cfg["risk_scoring"]
        weights = scoring["weights"]
        tiers_cfg = cfg["risk_tiers"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Pending applications
        c.execute(
            "SELECT * FROM loan_applications WHERE status = 'pending' "
            "ORDER BY submission_date ASC, application_id ASC"
        )
        pending = [dict(r) for r in c.fetchall()]

        results = []
        for app in pending:
            app_id = app["application_id"]
            industry = app["industry_code"]
            requested = app["requested_amount"]
            lender_id = app["lender_id"]
            submission_date = app["submission_date"]

            # Financial profile from workspace
            profile_path = os.path.join(
                self.workspace, "financials", f"{app_id}.json"
            )
            with open(profile_path) as f:
                profile = json.load(f)

            credit_score = profile["credit_score"]
            annual_revenue = profile["annual_revenue"]
            total_debt = profile["total_existing_debt"]
            years_biz = profile["years_in_business"]

            dti = total_debt / annual_revenue if annual_revenue > 0 else 999.0

            # Collateral
            c.execute(
                "SELECT asset_id, current_market_value FROM collateral_assets "
                "WHERE application_id = ?",
                (app_id,),
            )
            assets = c.fetchall()
            total_collateral = sum(a["current_market_value"] for a in assets)
            collateral_coverage = total_collateral / requested if requested > 0 else 0.0

            # Lender exposure
            c.execute(
                "SELECT current_exposure, max_exposure FROM lender_portfolios "
                "WHERE lender_id = ? AND industry_code = ?",
                (lender_id, industry),
            )
            lender_row = c.fetchone()
            if lender_row is None:
                remaining_capacity = 0.0
            else:
                remaining_capacity = lender_row["max_exposure"] - lender_row["current_exposure"]

            # --- Eligibility ---
            denial_reasons = []
            if credit_score < 580:
                denial_reasons.append("credit_score_below_580")
            if dti > 0.65:
                denial_reasons.append("dti_exceeds_0.65")
            if years_biz < 1:
                denial_reasons.append("years_in_business_below_1")
            if collateral_coverage < 0.15:
                denial_reasons.append("collateral_coverage_below_0.15")

            # --- Component scores ---
            # 1. Credit score
            cs_bands = scoring["credit_score_bands"]
            if credit_score >= cs_bands["excellent"]["min"]:
                cs_component = cs_bands["excellent"]["component_score"]
            elif credit_score >= cs_bands["good"]["min"]:
                cs_component = cs_bands["good"]["component_score"]
            elif credit_score >= cs_bands["fair"]["min"]:
                cs_component = cs_bands["fair"]["component_score"]
            else:
                cs_component = cs_bands["poor"]["component_score"]

            # 2. DTI
            dti_bands = scoring["dti_bands"]
            if dti <= dti_bands["low"]["max"]:
                dti_component = dti_bands["low"]["component_score"]
            elif dti <= dti_bands["moderate"]["max"]:
                dti_component = dti_bands["moderate"]["component_score"]
            elif dti <= dti_bands["high"]["max"]:
                dti_component = dti_bands["high"]["component_score"]
            else:
                dti_component = dti_bands["very_high"]["component_score"]

            # 3. Cash flow
            cf_class = self._compute_cash_flow_class(app_id)
            cf_component = scoring["cash_flow_assessment"][cf_class]["component_score"]

            # 4. Collateral coverage
            cc_bands = scoring["collateral_coverage_bands"]
            if collateral_coverage >= cc_bands["full"]["min"]:
                cc_component = cc_bands["full"]["component_score"]
            elif collateral_coverage >= cc_bands["substantial"]["min"]:
                cc_component = cc_bands["substantial"]["component_score"]
            elif collateral_coverage >= cc_bands["partial"]["min"]:
                cc_component = cc_bands["partial"]["component_score"]
            else:
                cc_component = cc_bands["insufficient"]["component_score"]

            # 5. Industry risk
            dr = default_rates.get(industry, 5.0)
            ind_component = max(0, 100 - dr * 10)

            # 6. Business maturity
            bm_bands = scoring["business_maturity_bands"]
            if years_biz >= bm_bands["established"]["min_years"]:
                bm_component = bm_bands["established"]["component_score"]
            elif years_biz >= bm_bands["mature"]["min_years"]:
                bm_component = bm_bands["mature"]["component_score"]
            elif years_biz >= bm_bands["growing"]["min_years"]:
                bm_component = bm_bands["growing"]["component_score"]
            else:
                bm_component = bm_bands["startup"]["component_score"]

            # Composite
            composite = (
                weights["credit_score"] * cs_component
                + weights["dti_ratio"] * dti_component
                + weights["cash_flow_stability"] * cf_component
                + weights["collateral_coverage"] * cc_component
                + weights["industry_risk"] * ind_component
                + weights["business_maturity"] * bm_component
            )
            composite = round(composite, 2)

            # Risk tier
            tier_name = "tier_4"
            for tname in ["tier_1", "tier_2", "tier_3", "tier_4"]:
                if composite >= tiers_cfg[tname]["min_score"]:
                    tier_name = tname
                    break

            credit_limit_pct = tiers_cfg[tier_name]["credit_limit_pct"]

            # Check lender capacity for eligibility
            proposed_limit = min(
                requested * credit_limit_pct,
                total_collateral,
                remaining_capacity,
            )
            proposed_limit = round(max(proposed_limit, 0), 2)

            if remaining_capacity <= 0:
                denial_reasons.append("lender_exposure_exceeded")
            elif proposed_limit > remaining_capacity:
                # The credit limit itself doesn't exceed capacity since we
                # already took the min, but if current + proposed > max
                # we handled it via remaining_capacity being the cap.
                pass

            decision = "DENIED" if denial_reasons else "APPROVED"
            credit_limit = proposed_limit if decision == "APPROVED" else 0.00
            denial_reason = "; ".join(denial_reasons) if denial_reasons else ""

            results.append({
                "application_id": app_id,
                "business_name": app["business_name"],
                "industry_code": industry,
                "risk_score": composite,
                "risk_tier": tier_name,
                "credit_limit": credit_limit,
                "decision": decision,
                "denial_reason": denial_reason,
                "submission_date": submission_date,
            })

        conn.close()

        # Sort approved by risk_score desc, submission_date asc, app_id asc
        approved = [r for r in results if r["decision"] == "APPROVED"]
        denied = [r for r in results if r["decision"] == "DENIED"]
        approved.sort(
            key=lambda x: (-x["risk_score"], x["submission_date"], x["application_id"])
        )

        # Assign ranks
        for i, r in enumerate(approved):
            r["rank"] = i + 1
        for r in denied:
            r["rank"] = ""

        return approved + denied

    # ===================================================================
    # step
    # ===================================================================

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

        gt_by_id = {r["application_id"]: r for r in ground_truth}
        gt_approved = [r for r in ground_truth if r["decision"] == "APPROVED"]
        gt_denied = [r for r in ground_truth if r["decision"] == "DENIED"]

        criteria = {}

        # -----------------------------------------------------------
        # 1. Output file exists and has correct headers (10 pts)
        # -----------------------------------------------------------
        csv_path = os.path.join(self.workspace, "approval_queue.csv")
        expected_headers = [
            "rank", "application_id", "business_name", "industry_code",
            "risk_score", "risk_tier", "credit_limit", "decision", "denial_reason",
        ]
        agent_rows = []
        file_ok = False
        headers_ok = False
        try:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                actual_headers = reader.fieldnames or []
                headers_ok = actual_headers == expected_headers
                agent_rows = list(reader)
                file_ok = True
        except Exception:
            pass

        criteria["output_file_format"] = {
            "passed": file_ok and headers_ok,
            "score": 10 if (file_ok and headers_ok) else 0,
            "max_score": 10,
            "reason": "" if (file_ok and headers_ok) else (
                "File missing" if not file_ok else f"Headers mismatch: got {actual_headers}"
            ),
        }

        # -----------------------------------------------------------
        # 2. Correct set of applications (15 pts)
        # -----------------------------------------------------------
        agent_ids = {r.get("application_id", "") for r in agent_rows}
        expected_ids = set(gt_by_id.keys())
        ids_match = agent_ids == expected_ids
        criteria["correct_applications"] = {
            "passed": ids_match,
            "score": 15 if ids_match else max(0, 15 - 3 * len(agent_ids.symmetric_difference(expected_ids))),
            "max_score": 15,
            "reason": "" if ids_match else f"Missing: {expected_ids - agent_ids}, Extra: {agent_ids - expected_ids}",
        }

        # -----------------------------------------------------------
        # 3. Eligibility decisions correct (20 pts)
        # -----------------------------------------------------------
        decision_correct = 0
        decision_total = len(gt_by_id)
        for r in agent_rows:
            aid = r.get("application_id", "")
            if aid in gt_by_id:
                if r.get("decision", "").strip().upper() == gt_by_id[aid]["decision"]:
                    decision_correct += 1
        dec_score = round(20 * decision_correct / max(decision_total, 1), 1)
        criteria["eligibility_decisions"] = {
            "passed": decision_correct == decision_total,
            "score": dec_score,
            "max_score": 20,
            "reason": "" if decision_correct == decision_total else f"{decision_correct}/{decision_total} correct",
        }

        # -----------------------------------------------------------
        # 4. Risk scores within tolerance (20 pts)
        # -----------------------------------------------------------
        score_correct = 0
        score_total = len(gt_by_id)
        for r in agent_rows:
            aid = r.get("application_id", "")
            if aid in gt_by_id:
                try:
                    agent_score = float(r.get("risk_score", -1))
                    expected_score = gt_by_id[aid]["risk_score"]
                    if abs(agent_score - expected_score) <= 0.05:
                        score_correct += 1
                except (ValueError, TypeError):
                    pass
        rs_score = round(20 * score_correct / max(score_total, 1), 1)
        criteria["risk_scores"] = {
            "passed": score_correct == score_total,
            "score": rs_score,
            "max_score": 20,
            "reason": "" if score_correct == score_total else f"{score_correct}/{score_total} within tolerance",
        }

        # -----------------------------------------------------------
        # 5. Risk tier assignments correct (10 pts)
        # -----------------------------------------------------------
        # Accept either the tier key (e.g. "tier_1") or the human label
        # (e.g. "Low Risk") that risk_config.yaml defines for that tier.
        cfg_for_labels = self._load_risk_config()
        tier_label_to_key = {
            tcfg["label"]: tkey
            for tkey, tcfg in cfg_for_labels["risk_tiers"].items()
        }
        tier_correct = 0
        tier_total = len(gt_by_id)
        for r in agent_rows:
            aid = r.get("application_id", "")
            if aid in gt_by_id:
                agent_tier_raw = r.get("risk_tier", "").strip()
                # Normalize: if it's a label, map to key
                agent_tier_key = tier_label_to_key.get(agent_tier_raw, agent_tier_raw)
                if agent_tier_key == gt_by_id[aid]["risk_tier"]:
                    tier_correct += 1
        tier_score = round(10 * tier_correct / max(tier_total, 1), 1)
        criteria["risk_tiers"] = {
            "passed": tier_correct == tier_total,
            "score": tier_score,
            "max_score": 10,
            "reason": "" if tier_correct == tier_total else f"{tier_correct}/{tier_total} correct",
        }

        # -----------------------------------------------------------
        # 6. Credit limits within tolerance (15 pts)
        # -----------------------------------------------------------
        cl_correct = 0
        cl_total = len(gt_by_id)
        for r in agent_rows:
            aid = r.get("application_id", "")
            if aid in gt_by_id:
                try:
                    agent_cl = float(r.get("credit_limit", -1))
                    expected_cl = gt_by_id[aid]["credit_limit"]
                    if abs(agent_cl - expected_cl) <= 0.02:
                        cl_correct += 1
                except (ValueError, TypeError):
                    pass
        cl_score = round(15 * cl_correct / max(cl_total, 1), 1)
        criteria["credit_limits"] = {
            "passed": cl_correct == cl_total,
            "score": cl_score,
            "max_score": 15,
            "reason": "" if cl_correct == cl_total else f"{cl_correct}/{cl_total} within tolerance",
        }

        # -----------------------------------------------------------
        # 7. Priority ordering of approved applications (10 pts)
        # -----------------------------------------------------------
        expected_order = [r["application_id"] for r in gt_approved]
        agent_approved = [
            r for r in agent_rows
            if r.get("decision", "").strip().upper() == "APPROVED"
        ]
        # Sort agent_approved by their rank field
        try:
            agent_approved_sorted = sorted(
                agent_approved, key=lambda x: int(x.get("rank", 9999))
            )
        except (ValueError, TypeError):
            agent_approved_sorted = agent_approved
        agent_order = [r.get("application_id", "") for r in agent_approved_sorted]
        order_ok = agent_order == expected_order
        criteria["priority_order"] = {
            "passed": order_ok,
            "score": 10 if order_ok else 0,
            "max_score": 10,
            "reason": "" if order_ok else "Approved application ordering does not match expected",
        }

        # -----------------------------------------------------------
        # Totals
        # -----------------------------------------------------------
        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return total_score / max_score, info

    # ===================================================================
    # verify
    # ===================================================================

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
        import yaml  # noqa

        tool_calls = 0

        def call_tool(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # 1. Read config files
        with open(os.path.join(self.workspace, "risk_config.yaml")) as f:
            cfg = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "lending_policy.md")) as f:
            policy_text = f.read()

        default_rates = {}
        with open(os.path.join(self.workspace, "industry_default_rates.csv"), newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                default_rates[row["industry_code"]] = float(row["default_rate_pct"])

        scoring = cfg["risk_scoring"]
        weights = scoring["weights"]
        tiers_cfg = cfg["risk_tiers"]

        # 2. List all pending applications (paginated)
        all_pending = []
        page = 1
        while True:
            result = call_tool("list_applications", status="pending", page=page, page_size=5)
            all_pending.extend(result["results"])
            if page * 5 >= result["total"]:
                break
            page += 1

        # 3. Process each pending application
        results = []
        for app_summary in all_pending:
            app_id = app_summary["application_id"]

            # Get full application details
            app = call_tool("get_application", application_id=app_id)

            industry = app["industry_code"]
            requested = app["requested_amount"]
            lender_id = app["lender_id"]
            submission_date = app["submission_date"]

            # Read financial profile from workspace
            profile_path = os.path.join(
                self.workspace, "financials", f"{app_id}.json"
            )
            with open(profile_path) as f:
                profile = json.load(f)

            credit_score = profile["credit_score"]
            annual_revenue = profile["annual_revenue"]
            total_debt = profile["total_existing_debt"]
            years_biz = profile["years_in_business"]

            dti = total_debt / annual_revenue if annual_revenue > 0 else 999.0

            # Get transaction history (6 months before 2026-03-20)
            txn_result = call_tool(
                "get_transaction_history",
                application_id=app_id,
                start_date="2025-09-20",
                end_date="2026-03-20",
            )
            transactions = txn_result["transactions"]

            # Compute cash flow classification
            monthly = {}
            for t in transactions:
                month_key = t["transaction_date"][:7]
                if month_key not in monthly:
                    monthly[month_key] = 0.0
                if t["type"] == "credit":
                    monthly[month_key] += t["amount"]
                else:
                    monthly[month_key] -= t["amount"]

            sorted_months = sorted(monthly.keys())
            if len(sorted_months) <= 1:
                overall_avg = sum(monthly.values()) / max(len(sorted_months), 1)
                if overall_avg < 0:
                    cf_class = "negative"
                else:
                    cf_class = "stable"
            else:
                mid = (len(sorted_months) + 1) // 2
                earlier = sorted_months[:mid]
                later = sorted_months[mid:]
                if not earlier or not later:
                    cf_class = "stable"
                else:
                    overall_avg = sum(monthly.values()) / len(sorted_months)
                    if overall_avg < 0:
                        cf_class = "negative"
                    else:
                        earlier_avg = sum(monthly[m] for m in earlier) / len(earlier)
                        later_avg = sum(monthly[m] for m in later) / len(later)
                        if earlier_avg == 0:
                            if later_avg > 0:
                                cf_class = "positive_trend"
                            elif later_avg < 0:
                                cf_class = "declining"
                            else:
                                cf_class = "stable"
                        else:
                            ratio = (later_avg - earlier_avg) / abs(earlier_avg)
                            if ratio > 0.05:
                                cf_class = "positive_trend"
                            elif ratio < -0.05:
                                cf_class = "declining"
                            else:
                                cf_class = "stable"

            # Get collateral assets
            coll_result = call_tool("get_collateral_assets", application_id=app_id)
            asset_list = coll_result["assets"]

            total_collateral = 0.0
            for asset in asset_list:
                val_result = call_tool("get_collateral_valuation", asset_id=asset["asset_id"])
                total_collateral += val_result["current_market_value"]

            collateral_coverage = total_collateral / requested if requested > 0 else 0.0

            # Check lender exposure
            exp_result = call_tool(
                "check_lender_exposure",
                lender_id=lender_id,
                industry_code=industry,
            )
            if "error" in exp_result:
                remaining_capacity = 0.0
            else:
                remaining_capacity = exp_result["max_exposure"] - exp_result["current_exposure"]

            # --- Eligibility check ---
            denial_reasons = []
            if credit_score < 580:
                denial_reasons.append("credit_score_below_580")
            if dti > 0.65:
                denial_reasons.append("dti_exceeds_0.65")
            if years_biz < 1:
                denial_reasons.append("years_in_business_below_1")
            if collateral_coverage < 0.15:
                denial_reasons.append("collateral_coverage_below_0.15")
            if remaining_capacity <= 0:
                denial_reasons.append("lender_exposure_exceeded")

            # --- Component scores ---
            cs_bands = scoring["credit_score_bands"]
            if credit_score >= cs_bands["excellent"]["min"]:
                cs_component = cs_bands["excellent"]["component_score"]
            elif credit_score >= cs_bands["good"]["min"]:
                cs_component = cs_bands["good"]["component_score"]
            elif credit_score >= cs_bands["fair"]["min"]:
                cs_component = cs_bands["fair"]["component_score"]
            else:
                cs_component = cs_bands["poor"]["component_score"]

            dti_bands = scoring["dti_bands"]
            if dti <= dti_bands["low"]["max"]:
                dti_component = dti_bands["low"]["component_score"]
            elif dti <= dti_bands["moderate"]["max"]:
                dti_component = dti_bands["moderate"]["component_score"]
            elif dti <= dti_bands["high"]["max"]:
                dti_component = dti_bands["high"]["component_score"]
            else:
                dti_component = dti_bands["very_high"]["component_score"]

            cf_component = scoring["cash_flow_assessment"][cf_class]["component_score"]

            cc_bands = scoring["collateral_coverage_bands"]
            if collateral_coverage >= cc_bands["full"]["min"]:
                cc_component = cc_bands["full"]["component_score"]
            elif collateral_coverage >= cc_bands["substantial"]["min"]:
                cc_component = cc_bands["substantial"]["component_score"]
            elif collateral_coverage >= cc_bands["partial"]["min"]:
                cc_component = cc_bands["partial"]["component_score"]
            else:
                cc_component = cc_bands["insufficient"]["component_score"]

            dr = default_rates.get(industry, 5.0)
            ind_component = max(0, 100 - dr * 10)

            bm_bands = scoring["business_maturity_bands"]
            if years_biz >= bm_bands["established"]["min_years"]:
                bm_component = bm_bands["established"]["component_score"]
            elif years_biz >= bm_bands["mature"]["min_years"]:
                bm_component = bm_bands["mature"]["component_score"]
            elif years_biz >= bm_bands["growing"]["min_years"]:
                bm_component = bm_bands["growing"]["component_score"]
            else:
                bm_component = bm_bands["startup"]["component_score"]

            composite = (
                weights["credit_score"] * cs_component
                + weights["dti_ratio"] * dti_component
                + weights["cash_flow_stability"] * cf_component
                + weights["collateral_coverage"] * cc_component
                + weights["industry_risk"] * ind_component
                + weights["business_maturity"] * bm_component
            )
            composite = round(composite, 2)

            # Risk tier
            tier_name = "tier_4"
            for tname in ["tier_1", "tier_2", "tier_3", "tier_4"]:
                if composite >= tiers_cfg[tname]["min_score"]:
                    tier_name = tname
                    break

            credit_limit_pct = tiers_cfg[tier_name]["credit_limit_pct"]

            proposed_limit = min(
                requested * credit_limit_pct,
                total_collateral,
                remaining_capacity,
            )
            proposed_limit = round(max(proposed_limit, 0), 2)

            decision = "DENIED" if denial_reasons else "APPROVED"
            credit_limit = proposed_limit if decision == "APPROVED" else 0.00
            denial_reason = "; ".join(denial_reasons) if denial_reasons else ""

            results.append({
                "application_id": app_id,
                "business_name": app["business_name"],
                "industry_code": industry,
                "risk_score": composite,
                "risk_tier": tier_name,
                "credit_limit": credit_limit,
                "decision": decision,
                "denial_reason": denial_reason,
                "submission_date": submission_date,
            })

        # Sort approved
        approved = [r for r in results if r["decision"] == "APPROVED"]
        denied = [r for r in results if r["decision"] == "DENIED"]
        approved.sort(
            key=lambda x: (-x["risk_score"], x["submission_date"], x["application_id"])
        )
        for i, r in enumerate(approved):
            r["rank"] = i + 1
        for r in denied:
            r["rank"] = ""

        all_results = approved + denied

        # Write approval_queue.csv
        csv_path = os.path.join(self.workspace, "approval_queue.csv")
        fieldnames = [
            "rank", "application_id", "business_name", "industry_code",
            "risk_score", "risk_tier", "credit_limit", "decision", "denial_reason",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in all_results:
                writer.writerow({
                    "rank": r["rank"],
                    "application_id": r["application_id"],
                    "business_name": r["business_name"],
                    "industry_code": r["industry_code"],
                    "risk_score": f"{r['risk_score']:.2f}",
                    "risk_tier": r["risk_tier"],
                    "credit_limit": f"{r['credit_limit']:.2f}",
                    "decision": r["decision"],
                    "denial_reason": r["denial_reason"],
                })

        # Build final action string
        n_total = len(all_results)
        n_approved = len(approved)
        n_denied = len(denied)
        top3 = approved[:3]
        top3_str = "; ".join(
            f"{r['application_id']} (score={r['risk_score']:.2f}, limit={r['credit_limit']:.2f})"
            for r in top3
        )

        action = (
            f"Evaluated {n_total} pending applications: {n_approved} approved, {n_denied} denied. "
            f"Top 3 in priority queue: {top3_str}"
        )

        print(f"verify: {tool_calls} tool calls made")
        assert tool_calls >= 15, f"Only {tool_calls} tool calls; need ≥ 15"

        return self.step(action)
