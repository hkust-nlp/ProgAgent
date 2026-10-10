import sqlite3
import json
import os
import csv
import yaml
import re
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta


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

    # ── tool methods ──────────────────────────────────────────────────

    @tool(
        description="List claims with pagination. Returns basic claim information for each claim.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of claims per page (max 25)",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_claims(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 25)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM claims")
        total = cur.fetchone()[0]
        offset = (page - 1) * page_size
        cur.execute(
            "SELECT claim_id, employee_id, injury_date, filing_date, "
            "claim_amount, injury_type, status FROM claims "
            "ORDER BY claim_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "claims": rows,
            "page": page,
            "page_size": page_size,
            "total_claims": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get full details for a single claim by its claim ID.",
        parameters={
            "type": "object",
            "properties": {
                "claim_id": {
                    "type": "string",
                    "description": "The claim identifier, e.g. CLM-0001",
                },
            },
            "required": ["claim_id"],
        },
    )
    def get_claim_details(self, claim_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Claim {claim_id} not found"}
        return dict(row)

    @tool(
        description="Get the employment record for a single employee.",
        parameters={
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "The employee identifier, e.g. EMP-0001",
                },
            },
            "required": ["employee_id"],
        },
    )
    def get_employee_record(self, employee_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Employee {employee_id} not found"}
        return dict(row)

    @tool(
        description="Get all medical treatments associated with a given claim.",
        parameters={
            "type": "object",
            "properties": {
                "claim_id": {
                    "type": "string",
                    "description": "The claim identifier, e.g. CLM-0001",
                },
            },
            "required": ["claim_id"],
        },
    )
    def get_medical_treatments(self, claim_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM medical_treatments WHERE claim_id = ? ORDER BY treatment_date",
            (claim_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"claim_id": claim_id, "treatments": rows}

    @tool(
        description="Get all witness statements associated with a given claim.",
        parameters={
            "type": "object",
            "properties": {
                "claim_id": {
                    "type": "string",
                    "description": "The claim identifier, e.g. CLM-0001",
                },
            },
            "required": ["claim_id"],
        },
    )
    def get_witness_statements(self, claim_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM witness_statements WHERE claim_id = ? ORDER BY statement_date",
            (claim_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"claim_id": claim_id, "statements": rows}

    @tool(
        description="Get information about a medical provider by provider ID.",
        parameters={
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "string",
                    "description": "The provider identifier, e.g. PRV-0001",
                },
            },
            "required": ["provider_id"],
        },
    )
    def get_provider_info(self, provider_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM medical_providers WHERE provider_id = ?", (provider_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Provider {provider_id} not found"}
        return dict(row)

    @tool(
        description="Get the claims history for a given employee, listing all claims they have filed.",
        parameters={
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "The employee identifier, e.g. EMP-0001",
                },
            },
            "required": ["employee_id"],
        },
    )
    def get_employee_claims_history(self, employee_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT claim_id, injury_date, claim_amount, status "
            "FROM claims WHERE employee_id = ? ORDER BY injury_date",
            (employee_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"employee_id": employee_id, "claims": rows}

    # ── ground truth computation (used by step and verify) ────────────

    def _compute_ground_truth(self) -> dict:
        """Compute the full ground truth scoring using DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # load scoring rules
        rules_path = os.path.join(self.workspace, "fraud_scoring_rules.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        scoring = rules["scoring_rules"]
        risk_levels = rules["risk_levels"]
        inv_threshold = rules["investigation_threshold"]

        # load risk thresholds
        thresholds_path = os.path.join(self.workspace, "risk_thresholds.csv")
        amount_thresholds = {}
        with open(thresholds_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                amount_thresholds[row["injury_type"]] = float(row["amount_threshold"])

        # load dossiers
        dossier_dir = os.path.join(self.workspace, "claim_dossiers")
        credibility_scores = {}
        if os.path.isdir(dossier_dir):
            for fname in sorted(os.listdir(dossier_dir)):
                if fname.endswith(".json"):
                    with open(os.path.join(dossier_dir, fname)) as f:
                        entries = json.load(f)
                    for entry in entries:
                        credibility_scores[entry["claim_id"]] = entry["credibility_score"]

        # load provider audit scores
        audit_dir = os.path.join(self.workspace, "provider_audit_reports")
        provider_anomaly = {}
        if os.path.isdir(audit_dir):
            for fname in sorted(os.listdir(audit_dir)):
                if fname.endswith(".csv"):
                    with open(os.path.join(audit_dir, fname)) as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            provider_anomaly[row["provider_id"]] = float(row["billing_anomaly_score"])

        # load witness reliability ratings
        assess_dir = os.path.join(self.workspace, "witness_assessments")
        # claim_id -> list of reliability ratings
        witness_reliability = {}
        if os.path.isdir(assess_dir):
            for fname in sorted(os.listdir(assess_dir)):
                if fname.endswith(".txt"):
                    with open(os.path.join(assess_dir, fname)) as f:
                        content = f.read()
                    # parse witness assessments
                    blocks = content.split("---")
                    for block in blocks:
                        cid_match = re.search(r"Claim ID:\s*(CLM-\d+)", block)
                        rel_match = re.search(r"Reliability Rating:\s*([\d.]+)", block)
                        if cid_match and rel_match:
                            cid = cid_match.group(1)
                            rel = float(rel_match.group(1))
                            witness_reliability.setdefault(cid, []).append(rel)

        # get all claims
        cur.execute("SELECT * FROM claims ORDER BY claim_id")
        claims = [dict(r) for r in cur.fetchall()]

        # get employee info
        cur.execute("SELECT * FROM employees")
        employees = {r["employee_id"]: dict(r) for r in cur.fetchall()}

        # get all treatments grouped by claim
        cur.execute("SELECT * FROM medical_treatments ORDER BY claim_id, treatment_date")
        treatments_by_claim = {}
        for r in cur.fetchall():
            r = dict(r)
            treatments_by_claim.setdefault(r["claim_id"], []).append(r)

        # get all witness statements grouped by claim
        cur.execute("SELECT * FROM witness_statements ORDER BY claim_id")
        witnesses_by_claim = {}
        for r in cur.fetchall():
            r = dict(r)
            witnesses_by_claim.setdefault(r["claim_id"], []).append(r)

        # get claims per employee (for repeat claimant check)
        emp_claims = {}
        for c in claims:
            emp_claims.setdefault(c["employee_id"], []).append(c)

        conn.close()

        # ── score each claim ───────────────────────────────────────────
        claim_scores = []
        total_risk_sum = 0
        for c in claims:
            cid = c["claim_id"]
            score = 0
            indicators = []

            # 1. late_filing
            injury_dt = datetime.strptime(c["injury_date"], "%Y-%m-%d")
            filing_dt = datetime.strptime(c["filing_date"], "%Y-%m-%d")
            if (filing_dt - injury_dt).days > scoring["late_filing"]["threshold_days"]:
                score += scoring["late_filing"]["weight"]
                indicators.append("late_filing")

            # 2. excessive_amount
            thresh = amount_thresholds.get(c["injury_type"], 999999)
            if c["claim_amount"] > thresh:
                score += scoring["excessive_amount"]["weight"]
                indicators.append("excessive_amount")

            # 3. provider_anomaly
            treats = treatments_by_claim.get(cid, [])
            anomaly_thresh = scoring["provider_anomaly"]["anomaly_threshold"]
            has_anomaly = False
            for t in treats:
                pid = t["provider_id"]
                if provider_anomaly.get(pid, 0) > anomaly_thresh:
                    has_anomaly = True
                    break
            if has_anomaly:
                score += scoring["provider_anomaly"]["weight"]
                indicators.append("provider_anomaly")

            # 4. witness_inconsistency
            wits = witnesses_by_claim.get(cid, [])
            avg_consistency = sum(w["consistency_rating"] for w in wits) / len(wits) if wits else 5.0
            reliabilities = witness_reliability.get(cid, [])
            avg_reliability = sum(reliabilities) / len(reliabilities) if reliabilities else 1.0
            if avg_consistency < scoring["witness_inconsistency"]["consistency_threshold"] or \
               avg_reliability < scoring["witness_inconsistency"]["reliability_threshold"]:
                score += scoring["witness_inconsistency"]["weight"]
                indicators.append("witness_inconsistency")

            # 5. repeat_claimant
            emp_id = c["employee_id"]
            lookback = scoring["repeat_claimant"]["lookback_months"]
            emp_all_claims = emp_claims.get(emp_id, [])
            if len(emp_all_claims) > 1:
                # check if any pair is within lookback months
                dates = sorted([datetime.strptime(ec["injury_date"], "%Y-%m-%d") for ec in emp_all_claims])
                has_repeat = False
                for i in range(len(dates)):
                    for j in range(i + 1, len(dates)):
                        diff_months = (dates[j] - dates[i]).days / 30.44
                        if diff_months <= lookback:
                            has_repeat = True
                            break
                    if has_repeat:
                        break
                if has_repeat:
                    score += scoring["repeat_claimant"]["weight"]
                    indicators.append("repeat_claimant")

            # 6. treatment_timing
            has_early_treatment = False
            for t in treats:
                treat_dt = datetime.strptime(t["treatment_date"], "%Y-%m-%d")
                if treat_dt < injury_dt:
                    has_early_treatment = True
                    break
            if has_early_treatment:
                score += scoring["treatment_timing"]["weight"]
                indicators.append("treatment_timing")

            # 7. new_employee
            emp = employees.get(emp_id, {})
            if emp:
                hire_dt = datetime.strptime(emp["hire_date"], "%Y-%m-%d")
                if (injury_dt - hire_dt).days < scoring["new_employee"]["threshold_days"] and \
                   (injury_dt - hire_dt).days >= 0:
                    score += scoring["new_employee"]["weight"]
                    indicators.append("new_employee")

            # 8. low_credibility
            cred = credibility_scores.get(cid, 1.0)
            if cred < scoring["low_credibility"]["credibility_threshold"]:
                score += scoring["low_credibility"]["weight"]
                indicators.append("low_credibility")

            total_risk_sum += score
            emp_name = emp.get("name", "Unknown") if emp else "Unknown"
            dept = emp.get("department", "Unknown") if emp else "Unknown"

            claim_scores.append({
                "claim_id": cid,
                "employee_id": emp_id,
                "employee_name": emp_name,
                "department": dept,
                "risk_score": score,
                "indicators": sorted(indicators),
            })

        # classify risk levels and filter
        for cs in claim_scores:
            s = cs["risk_score"]
            if s >= risk_levels["critical"]["min_score"]:
                cs["risk_level"] = "critical"
                cs["recommended_action"] = risk_levels["critical"]["recommended_action"]
            elif s >= risk_levels["high"]["min_score"]:
                cs["risk_level"] = "high"
                cs["recommended_action"] = risk_levels["high"]["recommended_action"]
            elif s >= inv_threshold:
                cs["risk_level"] = "medium"
                cs["recommended_action"] = risk_levels["medium"]["recommended_action"]
            else:
                cs["risk_level"] = "low"
                cs["recommended_action"] = "Standard processing"

        # investigation list: score >= threshold, sorted by score desc then claim_id asc
        inv_list = [cs for cs in claim_scores if cs["risk_score"] >= inv_threshold]
        inv_list.sort(key=lambda x: (-x["risk_score"], x["claim_id"]))
        for rank, item in enumerate(inv_list, 1):
            item["rank"] = rank

        # summary stats
        avg_score = round(total_risk_sum / len(claims), 2) if claims else 0.0
        risk_dist = {"critical": 0, "high": 0, "medium": 0}
        for item in inv_list:
            risk_dist[item["risk_level"]] += 1

        summary = {
            "total_claims_analyzed": len(claims),
            "flagged_claims": len(inv_list),
            "risk_distribution": risk_dist,
            "average_risk_score": avg_score,
        }

        return {
            "investigation_list": inv_list,
            "summary": summary,
            "all_scores": claim_scores,
        }

    # ── step ──────────────────────────────────────────────────────────

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
        gt = self._compute_ground_truth()
        gt_list = gt["investigation_list"]
        gt_summary = gt["summary"]
        gt_ids = {item["claim_id"] for item in gt_list}

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── C1: investigation_list.csv exists with correct columns (10 pts) ──
        c1_max = 10
        max_score += c1_max
        inv_path = os.path.join(self.workspace, "investigation_list.csv")
        agent_list = []
        c1_pass = False
        required_cols = {"rank", "claim_id", "employee_name", "department",
                         "risk_score", "risk_level", "fraud_indicators", "recommended_action"}
        if os.path.isfile(inv_path):
            try:
                with open(inv_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = set(reader.fieldnames) if reader.fieldnames else set()
                    if required_cols.issubset(cols):
                        agent_list = list(reader)
                        c1_pass = True
            except Exception:
                pass
        c1_score = c1_max if c1_pass else 0
        total_score += c1_score
        eval_criteria["investigation_list_format"] = {
            "passed": c1_pass,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if c1_pass else f"Missing file or columns. Expected: {sorted(required_cols)}",
        }

        # ── C2: recall – all ground-truth claims present (25 pts) ────
        c2_max = 25
        max_score += c2_max
        if agent_list:
            agent_ids = {row["claim_id"].strip() for row in agent_list}
            missing = gt_ids - agent_ids
            recall = 1.0 - len(missing) / len(gt_ids) if gt_ids else 1.0
            c2_score = round(c2_max * max(0, recall))
        else:
            missing = gt_ids
            c2_score = 0
        c2_pass = c2_score == c2_max
        total_score += c2_score
        eval_criteria["recall_flagged_claims"] = {
            "passed": c2_pass,
            "score": c2_score,
            "max_score": c2_max,
            "reason": "" if c2_pass else f"Missing {len(missing)} flagged claim(s)",
        }

        # ── C3: risk scores correct within ±2 (20 pts) ──────────────
        c3_max = 20
        max_score += c3_max
        gt_score_map = {item["claim_id"]: item["risk_score"] for item in gt_list}
        if agent_list:
            correct = 0
            total_checked = 0
            for row in agent_list:
                cid = row["claim_id"].strip()
                if cid in gt_score_map:
                    total_checked += 1
                    try:
                        agent_score = int(row["risk_score"].strip())
                    except (ValueError, KeyError):
                        continue
                    if abs(agent_score - gt_score_map[cid]) <= 2:
                        correct += 1
            frac = correct / total_checked if total_checked > 0 else 0
            c3_score = round(c3_max * frac)
        else:
            c3_score = 0
        c3_pass = c3_score == c3_max
        total_score += c3_score
        eval_criteria["risk_scores_accuracy"] = {
            "passed": c3_pass,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_pass else "Some risk scores differ from ground truth",
        }

        # ── C4: correct ranking order (15 pts) ──────────────────────
        c4_max = 15
        max_score += c4_max
        if agent_list and len(agent_list) >= len(gt_list):
            gt_order = [item["claim_id"] for item in gt_list]
            agent_order = [row["claim_id"].strip() for row in agent_list
                           if row["claim_id"].strip() in gt_ids]
            # check pairwise ordering
            if agent_order == gt_order:
                c4_score = c4_max
            else:
                # partial credit: Kendall tau distance
                gt_pos = {cid: i for i, cid in enumerate(gt_order)}
                concordant = 0
                total_pairs = 0
                for i in range(len(agent_order)):
                    for j in range(i + 1, len(agent_order)):
                        a, b = agent_order[i], agent_order[j]
                        if a in gt_pos and b in gt_pos:
                            total_pairs += 1
                            if gt_pos[a] < gt_pos[b]:
                                concordant += 1
                tau = concordant / total_pairs if total_pairs > 0 else 0
                c4_score = round(c4_max * tau)
        else:
            c4_score = 0
        c4_pass = c4_score == c4_max
        total_score += c4_score
        eval_criteria["ranking_order"] = {
            "passed": c4_pass,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if c4_pass else "Ranking order differs from expected",
        }

        # ── C5: risk_summary.json correct (15 pts) ──────────────────
        c5_max = 15
        max_score += c5_max
        summary_path = os.path.join(self.workspace, "risk_summary.json")
        c5_score = 0
        if os.path.isfile(summary_path):
            try:
                with open(summary_path) as f:
                    agent_summary = json.load(f)
                checks = 0
                passed_checks = 0
                # total_claims_analyzed
                checks += 1
                if agent_summary.get("total_claims_analyzed") == gt_summary["total_claims_analyzed"]:
                    passed_checks += 1
                # flagged_claims
                checks += 1
                if agent_summary.get("flagged_claims") == gt_summary["flagged_claims"]:
                    passed_checks += 1
                # risk_distribution
                checks += 1
                agent_dist = agent_summary.get("risk_distribution", {})
                if all(agent_dist.get(k) == v for k, v in gt_summary["risk_distribution"].items()):
                    passed_checks += 1
                # average_risk_score
                checks += 1
                try:
                    agent_avg = float(agent_summary.get("average_risk_score", -1))
                    if abs(agent_avg - gt_summary["average_risk_score"]) <= 0.05:
                        passed_checks += 1
                except (TypeError, ValueError):
                    pass
                c5_score = round(c5_max * passed_checks / checks)
            except Exception:
                pass
        c5_pass = c5_score == c5_max
        total_score += c5_score
        eval_criteria["risk_summary_json"] = {
            "passed": c5_pass,
            "score": c5_score,
            "max_score": c5_max,
            "reason": "" if c5_pass else "Summary file missing or contains incorrect values",
        }

        # ── C6: risk level classifications correct (15 pts) ─────────
        c6_max = 15
        max_score += c6_max
        gt_level_map = {item["claim_id"]: item["risk_level"] for item in gt_list}
        if agent_list:
            correct = 0
            total_checked = 0
            for row in agent_list:
                cid = row["claim_id"].strip()
                if cid in gt_level_map:
                    total_checked += 1
                    if row.get("risk_level", "").strip() == gt_level_map[cid]:
                        correct += 1
            frac = correct / total_checked if total_checked > 0 else 0
            c6_score = round(c6_max * frac)
        else:
            c6_score = 0
        c6_pass = c6_score == c6_max
        total_score += c6_score
        eval_criteria["risk_level_accuracy"] = {
            "passed": c6_pass,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_pass else "Some risk level classifications are incorrect",
        }

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ── verify ────────────────────────────────────────────────────────

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
        import re as _re

        # ── 1. Read workspace config files ─────────────────────────────
        rules_path = os.path.join(self.workspace, "fraud_scoring_rules.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        scoring = rules["scoring_rules"]
        risk_levels = rules["risk_levels"]
        inv_threshold = rules["investigation_threshold"]

        thresholds_path = os.path.join(self.workspace, "risk_thresholds.csv")
        amount_thresholds = {}
        with open(thresholds_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                amount_thresholds[row["injury_type"]] = float(row["amount_threshold"])

        # Read dossiers for credibility scores
        dossier_dir = os.path.join(self.workspace, "claim_dossiers")
        credibility_scores = {}
        for fname in sorted(os.listdir(dossier_dir)):
            if fname.endswith(".json"):
                with open(os.path.join(dossier_dir, fname)) as f:
                    entries = json.load(f)
                for entry in entries:
                    credibility_scores[entry["claim_id"]] = entry["credibility_score"]

        # Read provider audit scores
        audit_dir = os.path.join(self.workspace, "provider_audit_reports")
        provider_anomaly = {}
        for fname in sorted(os.listdir(audit_dir)):
            if fname.endswith(".csv"):
                with open(os.path.join(audit_dir, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        provider_anomaly[row["provider_id"]] = float(row["billing_anomaly_score"])

        # Read witness reliability ratings
        assess_dir = os.path.join(self.workspace, "witness_assessments")
        witness_reliability = {}
        for fname in sorted(os.listdir(assess_dir)):
            if fname.endswith(".txt"):
                with open(os.path.join(assess_dir, fname)) as f:
                    content = f.read()
                blocks = content.split("---")
                for block in blocks:
                    cid_match = _re.search(r"Claim ID:\s*(CLM-\d+)", block)
                    rel_match = _re.search(r"Reliability Rating:\s*([\d.]+)", block)
                    if cid_match and rel_match:
                        cid = cid_match.group(1)
                        rel = float(rel_match.group(1))
                        witness_reliability.setdefault(cid, []).append(rel)

        # ── 2. Gather all claims via tools ─────────────────────────────
        all_claims = []
        page = 1
        while True:
            result = self.tools["list_claims"](page=page, page_size=25)
            all_claims.extend(result["claims"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ── 3. For each claim, gather detailed data via tools ──────────
        claim_details = {}
        claim_treatments = {}
        claim_witnesses = {}
        employee_cache = {}
        emp_claims_cache = {}

        for c in all_claims:
            cid = c["claim_id"]
            eid = c["employee_id"]

            # Get treatments
            treat_result = self.tools["get_medical_treatments"](claim_id=cid)
            claim_treatments[cid] = treat_result["treatments"]

            # Get witness statements
            wit_result = self.tools["get_witness_statements"](claim_id=cid)
            claim_witnesses[cid] = wit_result["statements"]

            # Get employee record (cached)
            if eid not in employee_cache:
                emp_result = self.tools["get_employee_record"](employee_id=eid)
                employee_cache[eid] = emp_result

            # Get employee claims history (cached)
            if eid not in emp_claims_cache:
                hist_result = self.tools["get_employee_claims_history"](employee_id=eid)
                emp_claims_cache[eid] = hist_result["claims"]

        # ── 4. Score each claim ────────────────────────────────────────
        claim_scores = []
        total_risk_sum = 0

        for c in all_claims:
            cid = c["claim_id"]
            eid = c["employee_id"]
            score = 0
            indicators = []

            injury_dt = datetime.strptime(c["injury_date"], "%Y-%m-%d")
            filing_dt = datetime.strptime(c["filing_date"], "%Y-%m-%d")

            # late_filing
            if (filing_dt - injury_dt).days > scoring["late_filing"]["threshold_days"]:
                score += scoring["late_filing"]["weight"]
                indicators.append("late_filing")

            # excessive_amount
            thresh = amount_thresholds.get(c["injury_type"], 999999)
            if c["claim_amount"] > thresh:
                score += scoring["excessive_amount"]["weight"]
                indicators.append("excessive_amount")

            # provider_anomaly
            treats = claim_treatments.get(cid, [])
            anomaly_thresh = scoring["provider_anomaly"]["anomaly_threshold"]
            for t in treats:
                pid = t["provider_id"]
                if provider_anomaly.get(pid, 0) > anomaly_thresh:
                    score += scoring["provider_anomaly"]["weight"]
                    indicators.append("provider_anomaly")
                    break

            # witness_inconsistency
            wits = claim_witnesses.get(cid, [])
            avg_consistency = sum(w["consistency_rating"] for w in wits) / len(wits) if wits else 5.0
            reliabilities = witness_reliability.get(cid, [])
            avg_reliability = sum(reliabilities) / len(reliabilities) if reliabilities else 1.0
            if avg_consistency < scoring["witness_inconsistency"]["consistency_threshold"] or \
               avg_reliability < scoring["witness_inconsistency"]["reliability_threshold"]:
                score += scoring["witness_inconsistency"]["weight"]
                indicators.append("witness_inconsistency")

            # repeat_claimant
            emp_history = emp_claims_cache.get(eid, [])
            if len(emp_history) > 1:
                lookback = scoring["repeat_claimant"]["lookback_months"]
                dates = sorted([datetime.strptime(ec["injury_date"], "%Y-%m-%d") for ec in emp_history])
                has_repeat = False
                for i in range(len(dates)):
                    for j in range(i + 1, len(dates)):
                        diff_months = (dates[j] - dates[i]).days / 30.44
                        if diff_months <= lookback:
                            has_repeat = True
                            break
                    if has_repeat:
                        break
                if has_repeat:
                    score += scoring["repeat_claimant"]["weight"]
                    indicators.append("repeat_claimant")

            # treatment_timing
            for t in treats:
                treat_dt = datetime.strptime(t["treatment_date"], "%Y-%m-%d")
                if treat_dt < injury_dt:
                    score += scoring["treatment_timing"]["weight"]
                    indicators.append("treatment_timing")
                    break

            # new_employee
            emp = employee_cache.get(eid, {})
            if emp and "hire_date" in emp:
                hire_dt = datetime.strptime(emp["hire_date"], "%Y-%m-%d")
                if (injury_dt - hire_dt).days < scoring["new_employee"]["threshold_days"] and \
                   (injury_dt - hire_dt).days >= 0:
                    score += scoring["new_employee"]["weight"]
                    indicators.append("new_employee")

            # low_credibility
            cred = credibility_scores.get(cid, 1.0)
            if cred < scoring["low_credibility"]["credibility_threshold"]:
                score += scoring["low_credibility"]["weight"]
                indicators.append("low_credibility")

            total_risk_sum += score
            emp_name = emp.get("name", "Unknown")
            dept = emp.get("department", "Unknown")

            # classify risk level
            if score >= risk_levels["critical"]["min_score"]:
                risk_level = "critical"
                rec_action = risk_levels["critical"]["recommended_action"]
            elif score >= risk_levels["high"]["min_score"]:
                risk_level = "high"
                rec_action = risk_levels["high"]["recommended_action"]
            elif score >= inv_threshold:
                risk_level = "medium"
                rec_action = risk_levels["medium"]["recommended_action"]
            else:
                risk_level = "low"
                rec_action = "Standard processing"

            claim_scores.append({
                "claim_id": cid,
                "employee_name": emp_name,
                "department": dept,
                "risk_score": score,
                "risk_level": risk_level,
                "indicators": sorted(indicators),
                "recommended_action": rec_action,
            })

        # ── 5. Build investigation list ────────────────────────────────
        inv_list = [cs for cs in claim_scores if cs["risk_score"] >= inv_threshold]
        inv_list.sort(key=lambda x: (-x["risk_score"], x["claim_id"]))

        # Write investigation_list.csv
        inv_csv_path = os.path.join(self.workspace, "investigation_list.csv")
        with open(inv_csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["rank", "claim_id", "employee_name", "department",
                             "risk_score", "risk_level", "fraud_indicators", "recommended_action"])
            for rank, item in enumerate(inv_list, 1):
                writer.writerow([
                    rank,
                    item["claim_id"],
                    item["employee_name"],
                    item["department"],
                    item["risk_score"],
                    item["risk_level"],
                    "|".join(item["indicators"]),
                    item["recommended_action"],
                ])

        # ── 6. Build risk_summary.json ─────────────────────────────────
        avg_score = round(total_risk_sum / len(all_claims), 2) if all_claims else 0.0
        risk_dist = {"critical": 0, "high": 0, "medium": 0}
        for item in inv_list:
            risk_dist[item["risk_level"]] += 1

        summary = {
            "total_claims_analyzed": len(all_claims),
            "flagged_claims": len(inv_list),
            "risk_distribution": risk_dist,
            "average_risk_score": avg_score,
        }
        summary_path = os.path.join(self.workspace, "risk_summary.json")
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        # ── 7. Construct action string ─────────────────────────────────
        action_lines = [
            f"Fraud risk analysis complete. Analyzed {len(all_claims)} claims.",
            f"Flagged {len(inv_list)} claims for investigation.",
            f"Risk distribution: {risk_dist['critical']} critical, "
            f"{risk_dist['high']} high, {risk_dist['medium']} medium.",
            f"Average risk score: {avg_score}.",
            "Investigation list saved to investigation_list.csv.",
            "Risk summary saved to risk_summary.json.",
        ]
        action = "\n".join(action_lines)

        return self.step(action)
