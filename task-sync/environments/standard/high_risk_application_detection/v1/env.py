import os
import json
import csv
import sqlite3
from typing import Tuple, Dict, List, Any


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ---------------------------------------------------------------------------
# Shared risk-score computation (used by both verify and step)
# ---------------------------------------------------------------------------

def _load_yaml_config(path: str) -> dict:
    """Minimal YAML-subset loader (avoids pyyaml dependency at eval time)."""
    import yaml
    with open(path) as f:
        return yaml.safe_load(f)


def _read_income_data(workspace: str) -> Dict[str, dict]:
    """Read all income verification batch JSON files from workspace."""
    income = {}
    for fname in sorted(os.listdir(workspace)):
        if fname.startswith("income_verification_batch_") and fname.endswith(".json"):
            with open(os.path.join(workspace, fname)) as f:
                for rec in json.load(f):
                    income[rec["applicant_id"]] = rec
    return income


def _read_appraisal_data(workspace: str) -> Dict[str, dict]:
    """Read all property appraisal CSV files from workspace."""
    appraisals = {}
    for fname in sorted(os.listdir(workspace)):
        if fname.startswith("property_appraisal_") and fname.endswith(".csv"):
            with open(os.path.join(workspace, fname)) as f:
                for row in csv.DictReader(f):
                    appraisals[row["application_id"]] = row
    return appraisals


def _compute_single_risk(app: dict, credit: dict, fraud_alerts: list,
                         history: list, income_rec: dict | None,
                         appraisal_rec: dict | None,
                         regional_rate: float, config: dict) -> dict:
    """Compute base risk score and components for one application."""
    weights = config["risk_weights"]

    # 1. Credit score risk factor
    cs = credit["credit_score"]
    credit_risk = 1.0
    for tier in ["excellent", "good", "fair", "poor", "very_poor"]:
        if cs >= config["credit_score_tiers"][tier]["min_score"]:
            credit_risk = config["credit_score_tiers"][tier]["risk_factor"]
            break

    # 2. DTI risk factor
    monthly_debt = credit["monthly_debt_payment"]
    if income_rec and income_rec.get("verified_annual_income", 0) > 0:
        monthly_income = income_rec["verified_annual_income"] / 12.0
        dti = monthly_debt / monthly_income
    else:
        dti = 1.0
    dti_risk = 1.0
    for tier in ["low", "moderate", "high", "very_high"]:
        if dti <= config["dti_thresholds"][tier]["max_ratio"]:
            dti_risk = config["dti_thresholds"][tier]["risk_factor"]
            break

    # 3. Fraud severity risk factor
    unresolved = [a for a in fraud_alerts if not a.get("is_resolved", False)]
    if unresolved:
        sev_scores = config["fraud_severity_scores"]
        fraud_risk = max(sev_scores.get(a["severity"], 0) for a in unresolved)
    else:
        fraud_risk = 0.0

    # 4. Regional default risk factor
    regional_risk = 0.2
    for tier in ["high_risk", "elevated", "moderate", "low_risk"]:
        if regional_rate >= config["regional_risk_thresholds"][tier]["min_default_rate"]:
            regional_risk = config["regional_risk_thresholds"][tier]["risk_factor"]
            break

    # 5. LTV risk factor
    loan_amount = app["loan_amount"]
    loan_type = app["loan_type"]
    if loan_type in ("mortgage", "home_equity") and appraisal_rec:
        appraised = float(appraisal_rec["appraised_value"])
        ltv = loan_amount / appraised if appraised > 0 else 1.0
        ltv_risk = 1.0
        for tier in ["safe", "standard", "high", "very_high"]:
            if ltv <= config["ltv_thresholds"][tier]["max_ltv"]:
                ltv_risk = config["ltv_thresholds"][tier]["risk_factor"]
                break
    else:
        ltv_risk = config["ltv_non_applicable_risk_factor"]

    # 6. Prior default risk factor
    n_defaults = sum(1 for h in history if h["outcome"] == "defaulted")
    default_risk = 1.0
    for tier in config["prior_default_risk"]:
        if n_defaults <= tier["max_defaults"]:
            default_risk = tier["risk_factor"]
            break

    # Weighted sum
    components = {
        "credit_score": weights["credit_score"] * credit_risk,
        "debt_to_income": weights["debt_to_income"] * dti_risk,
        "fraud_severity": weights["fraud_severity"] * fraud_risk,
        "regional_default": weights["regional_default"] * regional_risk,
        "loan_to_value": weights["loan_to_value"] * ltv_risk,
        "prior_defaults": weights["prior_defaults"] * default_risk,
    }
    risk_score = sum(components.values())
    primary_factor = max(components, key=components.get)

    return {
        "application_id": app["application_id"],
        "applicant_name": app["applicant_name"],
        "risk_score": round(risk_score, 4),
        "primary_risk_factor": primary_factor,
        "loan_amount": app["loan_amount"],
        "region": app["region"],
        "loan_type": app["loan_type"],
        # Carry forward for override logic
        "_dti": dti,
        "_unresolved_count": len(unresolved),
        "_has_critical_unresolved": any(
            a["severity"] == config["policy_overrides"]["critical_fraud_override"]["trigger_severity"]
            for a in unresolved
        ),
    }


def _apply_overrides(results: list, config: dict) -> list:
    """Apply policy override rules in order. Mutates results in place."""
    ov = config["policy_overrides"]
    tier_order = ["critical", "high", "medium", "low"]

    for r in results:
        adjusted_score = r["risk_score"]

        # Rule 2: multiple unresolved alerts adjustment (score bump)
        ma = ov["multiple_alerts_adjustment"]
        if ma["enabled"] and r["_unresolved_count"] >= ma["min_unresolved_alerts"]:
            adjusted_score = min(1.0, round(adjusted_score + ma["score_adjustment"], 4))

        # Assign tier based on (possibly adjusted) score
        tier = "low"
        for t in tier_order:
            if adjusted_score >= config["priority_tiers"][t]["min_score"]:
                tier = t
                break

        # Rule 3: combined DTI + fraud escalation
        ce = ov["combined_dti_fraud_escalation"]
        if ce["enabled"]:
            if r["_dti"] > ce["dti_threshold"] and r["_unresolved_count"] >= 1:
                min_tier = ce["min_tier"]
                if tier_order.index(tier) > tier_order.index(min_tier):
                    tier = min_tier

        # Rule 1: critical fraud override (absolute precedence)
        cf = ov["critical_fraud_override"]
        if cf["enabled"] and r["_has_critical_unresolved"]:
            tier = cf["assign_tier"]

        r["risk_score"] = adjusted_score
        r["priority_tier"] = tier

    return results


def _build_ground_truth(db_path: str, workspace: str):
    """Compute full ground-truth review queue from DB + workspace."""
    config = _load_yaml_config(os.path.join(workspace, "risk_scoring_config.yaml"))
    income_data = _read_income_data(workspace)
    appraisal_data = _read_appraisal_data(workspace)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    pending = [dict(r) for r in conn.execute(
        "SELECT * FROM loan_applications WHERE status='pending'"
    ).fetchall()]

    results = []
    region_cache = {}

    for app in pending:
        aid = app["application_id"]

        credit = dict(conn.execute(
            "SELECT * FROM credit_bureau WHERE applicant_id=?", (aid,)
        ).fetchone())

        fraud_rows = conn.execute(
            "SELECT * FROM fraud_alerts WHERE applicant_id=?", (aid,)
        ).fetchall()
        fraud_alerts = [dict(r) for r in fraud_rows]

        history_rows = conn.execute(
            "SELECT * FROM applicant_history WHERE applicant_id=?", (aid,)
        ).fetchall()
        history = [dict(r) for r in history_rows]

        region = app["region"]
        if region not in region_cache:
            rows = conn.execute(
                "SELECT default_rate_pct FROM regional_defaults "
                "WHERE region=? AND year >= 2023 AND year <= 2025",
                (region,),
            ).fetchall()
            if rows:
                region_cache[region] = round(sum(r[0] for r in rows) / len(rows), 4)
            else:
                region_cache[region] = 5.0
        regional_rate = region_cache[region]

        r = _compute_single_risk(
            app, credit, fraud_alerts, history,
            income_data.get(aid), appraisal_data.get(aid),
            regional_rate, config,
        )
        results.append(r)

    conn.close()

    results = _apply_overrides(results, config)
    results.sort(key=lambda x: (-x["risk_score"], x["application_id"]))
    return results, config


# ---------------------------------------------------------------------------
# Task_Env
# ---------------------------------------------------------------------------

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
    # Tools
    # ------------------------------------------------------------------

    @tool(
        description=(
            "Search loan applications filtered by status. Returns a paginated "
            "list of applications (10 per page). Each result contains "
            "application_id, applicant_name, region, loan_amount, loan_type, "
            "property_type, and application_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "approved", "rejected"],
                    "description": "Filter by application status.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
            },
            "required": ["status", "page"],
        },
    )
    def search_applications(self, status: str, page: int) -> str:
        page_size = 10
        offset = (max(1, int(page)) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT application_id, applicant_name, region, loan_amount, "
            "loan_type, property_type, application_date "
            "FROM loan_applications WHERE status=? "
            "ORDER BY application_id "
            "LIMIT ? OFFSET ?",
            (status, page_size, offset),
        ).fetchall()
        conn.close()
        return json.dumps([dict(r) for r in rows])

    @tool(
        description=(
            "Retrieve the credit bureau report for a single applicant. Returns "
            "credit_score, num_delinquencies, credit_utilization_pct, "
            "total_revolving_debt, total_installment_debt, monthly_debt_payment, "
            "hard_inquiries_12m, and oldest_account_years."
        ),
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The application/applicant ID (e.g. APP-0001).",
                },
            },
            "required": ["applicant_id"],
        },
    )
    def get_credit_report(self, applicant_id: str) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT credit_score, num_delinquencies, credit_utilization_pct, "
            "total_revolving_debt, total_installment_debt, monthly_debt_payment, "
            "hard_inquiries_12m, oldest_account_years "
            "FROM credit_bureau WHERE applicant_id=?",
            (applicant_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": "No credit report found"})
        return json.dumps(dict(row))

    @tool(
        description=(
            "Retrieve all fraud alerts for a single applicant. Each alert "
            "includes alert_type, severity (low/medium/high/critical), "
            "description, alert_date, and is_resolved (boolean)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The application/applicant ID (e.g. APP-0001).",
                },
            },
            "required": ["applicant_id"],
        },
    )
    def get_fraud_alerts(self, applicant_id: str) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT alert_type, severity, description, alert_date, is_resolved "
            "FROM fraud_alerts WHERE applicant_id=?",
            (applicant_id,),
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["is_resolved"] = bool(d["is_resolved"])
            result.append(d)
        return json.dumps(result)

    @tool(
        description=(
            "Get the average historical default rate for a region over the "
            "most recent three years (2023-2025). Returns the region name "
            "and the three_year_avg_default_rate as a percentage."
        ),
        parameters={
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "Region name (e.g. Northeast, Southwest).",
                },
            },
            "required": ["region"],
        },
    )
    def get_regional_default_rate(self, region: str) -> str:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT default_rate_pct FROM regional_defaults "
            "WHERE region=? AND year >= 2023 AND year <= 2025",
            (region,),
        ).fetchall()
        conn.close()
        if not rows:
            return json.dumps({"region": region, "three_year_avg_default_rate": None})
        avg = round(sum(r[0] for r in rows) / len(rows), 4)
        return json.dumps({"region": region, "three_year_avg_default_rate": avg})

    @tool(
        description=(
            "Retrieve the loan history for a single applicant. Each record "
            "includes prior_application_date, prior_loan_amount, "
            "prior_loan_type, and outcome (repaid/defaulted/current/settled)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The application/applicant ID (e.g. APP-0001).",
                },
            },
            "required": ["applicant_id"],
        },
    )
    def get_applicant_history(self, applicant_id: str) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT prior_application_date, prior_loan_amount, "
            "prior_loan_type, outcome "
            "FROM applicant_history WHERE applicant_id=?",
            (applicant_id,),
        ).fetchall()
        conn.close()
        return json.dumps([dict(r) for r in rows])

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------

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
        expected, config = _build_ground_truth(self.db_path, self.workspace)
        n_expected = len(expected)
        expected_map = {r["application_id"]: r for r in expected}

        criteria = {}

        # --- Criterion 1: review_queue.csv exists with correct columns (10 pts) ---
        csv_path = os.path.join(self.workspace, "review_queue.csv")
        required_cols = [
            "application_id", "applicant_name", "risk_score",
            "priority_tier", "primary_risk_factor", "loan_amount", "region",
        ]
        agent_rows = []
        if os.path.isfile(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                if all(c in cols for c in required_cols):
                    agent_rows = list(reader)
                    criteria["csv_format"] = {
                        "passed": True, "score": 10, "max_score": 10,
                    }
                else:
                    missing = [c for c in required_cols if c not in cols]
                    criteria["csv_format"] = {
                        "passed": False, "score": 0, "max_score": 10,
                        "reason": f"Missing columns: {missing}",
                    }
        else:
            criteria["csv_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "review_queue.csv not found",
            }

        # --- Criterion 2: correct application count (15 pts) ---
        agent_count = len(agent_rows)
        if agent_count == n_expected:
            criteria["app_count"] = {"passed": True, "score": 15, "max_score": 15}
        else:
            criteria["app_count"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": f"Expected {n_expected} rows, got {agent_count}",
            }

        # --- Criterion 3: risk score accuracy (20 pts) ---
        correct_scores = 0
        for row in agent_rows:
            aid = row.get("application_id", "")
            if aid in expected_map:
                try:
                    agent_score = round(float(row["risk_score"]), 4)
                    exp_score = expected_map[aid]["risk_score"]
                    if abs(agent_score - exp_score) < 0.005:
                        correct_scores += 1
                except (ValueError, KeyError):
                    pass
        if n_expected > 0:
            score3 = round(20 * correct_scores / n_expected, 2)
        else:
            score3 = 20
        criteria["risk_scores"] = {
            "passed": score3 >= 19.0,
            "score": score3,
            "max_score": 20,
            "reason": f"{correct_scores}/{n_expected} scores correct"
            if score3 < 20 else "",
        }

        # --- Criterion 4: priority tier accuracy (15 pts) ---
        correct_tiers = 0
        for row in agent_rows:
            aid = row.get("application_id", "")
            if aid in expected_map:
                if row.get("priority_tier", "").strip().lower() == expected_map[aid]["priority_tier"]:
                    correct_tiers += 1
        if n_expected > 0:
            score4 = round(15 * correct_tiers / n_expected, 2)
        else:
            score4 = 15
        criteria["tier_accuracy"] = {
            "passed": score4 >= 14.0,
            "score": score4,
            "max_score": 15,
            "reason": f"{correct_tiers}/{n_expected} tiers correct"
            if score4 < 15 else "",
        }

        # --- Criterion 5: correct sorting (10 pts) ---
        agent_ids_order = [r["application_id"] for r in agent_rows]
        expected_ids_order = [r["application_id"] for r in expected]
        if agent_ids_order == expected_ids_order:
            criteria["sorting"] = {"passed": True, "score": 10, "max_score": 10}
        else:
            criteria["sorting"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "Row order does not match expected sorting",
            }

        # --- Criterion 6: policy overrides applied (10 pts) ---
        override_apps = [
            aid for aid, r in expected_map.items()
            if r.get("_has_critical_unresolved")
            or r.get("_unresolved_count", 0) >= config["policy_overrides"]["multiple_alerts_adjustment"]["min_unresolved_alerts"]
            or (r.get("_dti", 0) > config["policy_overrides"]["combined_dti_fraud_escalation"]["dti_threshold"]
                and r.get("_unresolved_count", 0) >= 1)
        ]
        agent_map = {r["application_id"]: r for r in agent_rows}
        override_correct = 0
        for aid in override_apps:
            if aid in agent_map and aid in expected_map:
                if agent_map[aid].get("priority_tier", "").strip().lower() == expected_map[aid]["priority_tier"]:
                    override_correct += 1
        if override_apps:
            score6 = round(10 * override_correct / len(override_apps), 2)
        else:
            score6 = 10
        criteria["policy_overrides"] = {
            "passed": score6 >= 9.0,
            "score": score6,
            "max_score": 10,
            "reason": f"{override_correct}/{len(override_apps)} override-affected apps correct"
            if score6 < 10 else "",
        }

        # --- Criterion 7: risk_summary.json (10 pts) ---
        summary_path = os.path.join(self.workspace, "risk_summary.json")
        score7 = 0
        reason7 = ""
        if os.path.isfile(summary_path):
            try:
                with open(summary_path) as f:
                    summary = json.load(f)
                checks = 0
                total_checks = 4
                if summary.get("total_applications_reviewed") == n_expected:
                    checks += 1
                # tier counts
                exp_tier_counts = {}
                for r in expected:
                    t = r["priority_tier"]
                    exp_tier_counts[t] = exp_tier_counts.get(t, 0) + 1
                if summary.get("tier_counts") == exp_tier_counts:
                    checks += 1
                # tier avg scores
                exp_avg = {}
                tier_scores_map = {}
                for r in expected:
                    tier_scores_map.setdefault(r["priority_tier"], []).append(r["risk_score"])
                for t, scores in tier_scores_map.items():
                    exp_avg[t] = round(sum(scores) / len(scores), 4)
                agent_avg = summary.get("tier_average_scores", {})
                avg_ok = True
                for t in exp_avg:
                    if t not in agent_avg or abs(float(agent_avg[t]) - exp_avg[t]) > 0.005:
                        avg_ok = False
                        break
                if avg_ok and set(agent_avg.keys()) == set(exp_avg.keys()):
                    checks += 1
                # highest risk app
                if expected and summary.get("highest_risk_application") == expected[0]["application_id"]:
                    checks += 1
                score7 = round(10 * checks / total_checks, 2)
                if checks < total_checks:
                    reason7 = f"{checks}/{total_checks} summary checks passed"
            except (json.JSONDecodeError, Exception) as e:
                reason7 = f"Failed to parse risk_summary.json: {e}"
        else:
            reason7 = "risk_summary.json not found"
        criteria["summary_json"] = {
            "passed": score7 >= 9.0,
            "score": score7,
            "max_score": 10,
            "reason": reason7 if score7 < 10 else "",
        }

        # --- Criterion 8: response completeness (10 pts) ---
        score8 = 0
        reason8_parts = []
        action_lower = action.lower() if action else ""
        # Check total count mentioned
        if str(n_expected) in action:
            score8 += 2.5
        else:
            reason8_parts.append("total count not found")
        # Check tier counts mentioned
        exp_tier_counts_2 = {}
        for r in expected:
            t = r["priority_tier"]
            exp_tier_counts_2[t] = exp_tier_counts_2.get(t, 0) + 1
        tier_mentions = 0
        for t in ["critical", "high", "medium", "low"]:
            cnt = exp_tier_counts_2.get(t, 0)
            if t in action_lower and str(cnt) in action:
                tier_mentions += 1
        score8 += 2.5 * (tier_mentions / max(len(exp_tier_counts_2), 1))
        # Check top 3 apps mentioned
        top3 = expected[:3]
        top3_found = 0
        for r in top3:
            if r["application_id"] in action:
                top3_found += 1
        score8 += 5.0 * (top3_found / max(len(top3), 1))
        score8 = round(score8, 2)
        criteria["response_completeness"] = {
            "passed": score8 >= 9.0,
            "score": score8,
            "max_score": 10,
            "reason": "; ".join(reason8_parts) if score8 < 10 else "",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
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

        This method proves end-to-end solvability. It must:
          - Use self.tools[name](**params) to gather data (no direct DB queries).
          - Read files from self.workspace as needed.
          - Write all required deliverables to self.workspace.
          - Construct the final action string.
          - Return self.step(action).
        """
        import yaml

        # --- Read workspace config files ---
        config = _load_yaml_config(os.path.join(self.workspace, "risk_scoring_config.yaml"))
        income_data = _read_income_data(self.workspace)
        appraisal_data = _read_appraisal_data(self.workspace)

        # Read policy (for awareness; parameters are in config)
        with open(os.path.join(self.workspace, "underwriting_policy.md")) as f:
            _ = f.read()

        # --- Gather all pending applications via tool ---
        all_apps = []
        page = 1
        while True:
            result = self.tools["search_applications"](status="pending", page=page)
            apps_page = json.loads(result)
            if not apps_page:
                break
            all_apps.extend(apps_page)
            page += 1

        # --- For each unique region, get default rate ---
        region_rates = {}
        for app in all_apps:
            region = app["region"]
            if region not in region_rates:
                res = json.loads(self.tools["get_regional_default_rate"](region=region))
                region_rates[region] = res.get("three_year_avg_default_rate", 5.0) or 5.0

        # --- For each pending application, gather tool data ---
        results = []
        for app in all_apps:
            aid = app["application_id"]
            credit = json.loads(self.tools["get_credit_report"](applicant_id=aid))
            fraud_alerts = json.loads(self.tools["get_fraud_alerts"](applicant_id=aid))
            history = json.loads(self.tools["get_applicant_history"](applicant_id=aid))

            r = _compute_single_risk(
                app, credit, fraud_alerts, history,
                income_data.get(aid), appraisal_data.get(aid),
                region_rates[app["region"]], config,
            )
            results.append(r)

        # --- Apply overrides ---
        results = _apply_overrides(results, config)

        # --- Sort ---
        results.sort(key=lambda x: (-x["risk_score"], x["application_id"]))

        # --- Write review_queue.csv ---
        csv_path = os.path.join(self.workspace, "review_queue.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "application_id", "applicant_name", "risk_score",
                "priority_tier", "primary_risk_factor", "loan_amount", "region",
            ])
            for r in results:
                writer.writerow([
                    r["application_id"],
                    r["applicant_name"],
                    f"{r['risk_score']:.4f}",
                    r["priority_tier"],
                    r["primary_risk_factor"],
                    f"{r['loan_amount']:.2f}",
                    r["region"],
                ])

        # --- Write risk_summary.json ---
        tier_counts = {}
        tier_scores_map = {}
        for r in results:
            t = r["priority_tier"]
            tier_counts[t] = tier_counts.get(t, 0) + 1
            tier_scores_map.setdefault(t, []).append(r["risk_score"])

        summary = {
            "total_applications_reviewed": len(results),
            "tier_counts": tier_counts,
            "tier_average_scores": {
                t: round(sum(s) / len(s), 4)
                for t, s in tier_scores_map.items()
            },
            "highest_risk_application": results[0]["application_id"] if results else None,
        }
        with open(os.path.join(self.workspace, "risk_summary.json"), "w") as f:
            json.dump(summary, f, indent=2)

        # --- Construct action string ---
        action_lines = [
            f"Reviewed {len(results)} pending loan applications.",
        ]
        for tier in ["critical", "high", "medium", "low"]:
            cnt = tier_counts.get(tier, 0)
            action_lines.append(f"{tier.capitalize()} priority: {cnt} applications")
        action_lines.append("")
        action_lines.append("Top 3 highest risk applications:")
        for r in results[:3]:
            action_lines.append(
                f"- {r['application_id']} ({r['applicant_name']}): "
                f"risk score {r['risk_score']:.4f}, tier: {r['priority_tier']}, "
                f"primary factor: {r['primary_risk_factor']}"
            )
        action = "\n".join(action_lines)

        return self.step(action)
