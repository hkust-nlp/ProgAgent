"""
Insurance Claims Fraud Investigation - Task Environment
"""
import sqlite3
import os
import json
import csv
import re
import math
from typing import Tuple, Dict, List, Any
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

    # ------------------------------------------------------------------ #
    #                           TOOL METHODS                              #
    # ------------------------------------------------------------------ #

    @tool(
        description="Search for claims by status. Returns a paginated list of basic claim information (claim_id, claim_date, claim_amount, status). Use page and page_size to navigate results.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Claim status to filter by (e.g. 'under_investigation', 'approved', 'denied', 'pending')",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 20.",
                },
            },
            "required": ["status"],
        },
    )
    def search_claims(self, status: str, page: int = 1, page_size: int = 20) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        total = cur.execute(
            "SELECT COUNT(*) FROM claims WHERE status = ?", (status,)
        ).fetchone()[0]
        offset = (page - 1) * page_size
        rows = cur.execute(
            "SELECT claim_id, claim_date, claim_amount, status FROM claims WHERE status = ? ORDER BY claim_id LIMIT ? OFFSET ?",
            (status, page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "claims": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if page_size > 0 else 0,
        }

    @tool(
        description="Get full details for a specific claim including policy_id, claimant_id, provider_id, procedure_code, diagnosis_code, claim_amount, claim_date, status, and description.",
        parameters={
            "type": "object",
            "properties": {
                "claim_id": {
                    "type": "string",
                    "description": "The claim identifier (e.g. 'CLM-0001')",
                },
            },
            "required": ["claim_id"],
        },
    )
    def get_claim_details(self, claim_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM claims WHERE claim_id = ?", (claim_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Claim {claim_id} not found"}
        return dict(row)

    @tool(
        description="Get policy details for a specific policy including policy_type, coverage_amount, premium_monthly, start_date, end_date, status, and the associated claimant_id.",
        parameters={
            "type": "object",
            "properties": {
                "policy_id": {
                    "type": "string",
                    "description": "The policy identifier (e.g. 'POL-0001')",
                },
            },
            "required": ["policy_id"],
        },
    )
    def get_policy_details(self, policy_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM policies WHERE policy_id = ?", (policy_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Policy {policy_id} not found"}
        return dict(row)

    @tool(
        description="Get personal information for a claimant including first_name, last_name, date_of_birth, address, city, state, zip_code, phone, and email.",
        parameters={
            "type": "object",
            "properties": {
                "claimant_id": {
                    "type": "string",
                    "description": "The claimant identifier (e.g. 'CLT-0001')",
                },
            },
            "required": ["claimant_id"],
        },
    )
    def get_claimant_info(self, claimant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM claimants WHERE claimant_id = ?", (claimant_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Claimant {claimant_id} not found"}
        return dict(row)

    @tool(
        description="Get provider details including provider_name, specialty, license_number, address, city, state, region, phone, and npi_number.",
        parameters={
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "string",
                    "description": "The provider identifier (e.g. 'PRV-0001')",
                },
            },
            "required": ["provider_id"],
        },
    )
    def get_provider_info(self, provider_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM providers WHERE provider_id = ?", (provider_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Provider {provider_id} not found"}
        return dict(row)

    @tool(
        description="Get the full claim history for a claimant. Returns all claims filed by this claimant with claim_id, claim_date, claim_amount, status, procedure_code, and provider_id.",
        parameters={
            "type": "object",
            "properties": {
                "claimant_id": {
                    "type": "string",
                    "description": "The claimant identifier (e.g. 'CLT-0001')",
                },
            },
            "required": ["claimant_id"],
        },
    )
    def get_claim_history(self, claimant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT claim_id, claim_date, claim_amount, status, procedure_code, provider_id FROM claims WHERE claimant_id = ? ORDER BY claim_date",
            (claimant_id,),
        ).fetchall()
        conn.close()
        return {"claimant_id": claimant_id, "claims": [dict(r) for r in rows]}

    @tool(
        description="Look up billing code information for a procedure code. Returns the description, category, expected_min cost, and expected_max cost.",
        parameters={
            "type": "object",
            "properties": {
                "procedure_code": {
                    "type": "string",
                    "description": "The procedure/billing code (e.g. 'CPT-10000')",
                },
            },
            "required": ["procedure_code"],
        },
    )
    def lookup_billing_code(self, procedure_code: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM billing_codes WHERE code = ?", (procedure_code,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Billing code {procedure_code} not found"}
        return dict(row)

    # ------------------------------------------------------------------ #
    #                       GROUND-TRUTH HELPERS                          #
    # ------------------------------------------------------------------ #

    def _load_fraud_rules(self) -> dict:
        path = os.path.join(self.workspace, "fraud_scoring_rules.yaml")
        with open(path) as f:
            return yaml.safe_load(f)

    def _load_regional_adjustments(self) -> dict:
        path = os.path.join(self.workspace, "regional_cost_adjustments.csv")
        adj = {}
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                adj[row["region"]] = float(row["adjustment_factor"])
        return adj

    def _load_provider_deviations(self) -> dict:
        """Return {provider_id: avg_claim_deviation_pct} from audit files."""
        devs = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("provider_audit_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                for p in data["providers"]:
                    devs[p["provider_id"]] = p["avg_claim_deviation_pct"]
        return devs

    def _load_adjuster_flags(self) -> dict:
        """Return {claim_id: set_of_triggered_keywords} from adjuster report files."""
        RED_FLAG_KEYWORDS = [
            "inconsistent statements",
            "pre-existing condition suspected",
            "unverified injury",
            "suspicious timing",
            "conflicting documentation",
            "exaggerated symptoms",
        ]
        flags = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("adjuster_report_") and fname.endswith(".md"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                # Split by claim sections
                sections = re.split(r"## Claim (CLM-\d+)", content)
                # sections[0] is header; then alternating claim_id, section_text
                i = 1
                while i < len(sections) - 1:
                    cid = sections[i]
                    text = sections[i + 1].lower()
                    found = set()
                    for kw in RED_FLAG_KEYWORDS:
                        if kw in text:
                            found.add(kw)
                    flags[cid] = found
                    i += 2
        return flags

    def _compute_ground_truth(self) -> dict:
        """Compute fraud scores for all under_investigation claims."""
        rules = self._load_fraud_rules()
        weights = rules["scoring_weights"]
        thresholds = rules["thresholds"]
        prov_risk_thresh = rules["provider_risk_thresholds"]
        priority_tiers = rules["priority_tiers"]

        regional_adj = self._load_regional_adjustments()
        prov_devs = self._load_provider_deviations()
        adj_flags = self._load_adjuster_flags()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load all under_investigation claims
        inv_claims = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM claims WHERE status = 'under_investigation' ORDER BY claim_id"
            ).fetchall()
        ]

        cases = []
        for claim in inv_claims:
            triggered = []

            # 1. amount_anomaly
            bc = conn.execute(
                "SELECT * FROM billing_codes WHERE code = ?",
                (claim["procedure_code"],),
            ).fetchone()
            prov = conn.execute(
                "SELECT * FROM providers WHERE provider_id = ?",
                (claim["provider_id"],),
            ).fetchone()
            if bc and prov:
                region = prov["region"]
                adj_factor = regional_adj.get(region, 1.0)
                adjusted_max = bc["expected_max"] * adj_factor
                if claim["claim_amount"] > adjusted_max * (
                    1 + thresholds["amount_deviation_pct"] / 100
                ):
                    triggered.append("amount_anomaly")

            # 2. rapid_claims
            history = conn.execute(
                "SELECT claim_date FROM claims WHERE claimant_id = ?",
                (claim["claimant_id"],),
            ).fetchall()
            from datetime import datetime, timedelta

            claim_dt = datetime.fromisoformat(claim["claim_date"])
            window = timedelta(days=thresholds["rapid_claims_window_days"])
            count_in_window = sum(
                1
                for r in history
                if abs((datetime.fromisoformat(r["claim_date"]) - claim_dt).days)
                <= thresholds["rapid_claims_window_days"]
            )
            if count_in_window >= thresholds["rapid_claims_min_count"]:
                triggered.append("rapid_claims")

            # 3. provider_risk
            dev = prov_devs.get(claim["provider_id"], 0)
            if dev >= prov_risk_thresh["high"]:
                triggered.append("provider_risk")

            # 4. new_policy
            policy = conn.execute(
                "SELECT * FROM policies WHERE policy_id = ?",
                (claim["policy_id"],),
            ).fetchone()
            if policy:
                policy_start = datetime.fromisoformat(policy["start_date"])
                days_diff = (claim_dt - policy_start).days
                if 0 <= days_diff <= thresholds["new_policy_max_days"]:
                    triggered.append("new_policy")

            # 5. adjuster_flags
            claim_flags = adj_flags.get(claim["claim_id"], set())
            if len(claim_flags) > 0:
                triggered.append("adjuster_flags")

            # 6. coverage_ratio
            if policy:
                ratio = claim["claim_amount"] / policy["coverage_amount"]
                if ratio >= thresholds["coverage_ratio_min"]:
                    triggered.append("coverage_ratio")

            fraud_score = sum(weights[t] for t in triggered)

            # Claimant name
            claimant = conn.execute(
                "SELECT first_name, last_name FROM claimants WHERE claimant_id = ?",
                (claim["claimant_id"],),
            ).fetchone()
            cname = (
                f"{claimant['first_name']} {claimant['last_name']}"
                if claimant
                else "Unknown"
            )

            # Provider name
            prov_name = prov["provider_name"] if prov else "Unknown"

            cases.append(
                {
                    "claim_id": claim["claim_id"],
                    "claimant_name": cname,
                    "provider_name": prov_name,
                    "fraud_score": fraud_score,
                    "triggered": triggered,
                    "evidence_summary": "|".join(triggered) if triggered else "",
                }
            )

        conn.close()

        # Sort by fraud_score DESC, claim_id ASC
        cases.sort(key=lambda x: (-x["fraud_score"], x["claim_id"]))
        for rank, c in enumerate(cases, 1):
            c["priority_rank"] = rank

        # Tier counts
        critical = sum(1 for c in cases if c["fraud_score"] >= priority_tiers["critical"])
        high = sum(
            1
            for c in cases
            if priority_tiers["high"] <= c["fraud_score"] < priority_tiers["critical"]
        )
        medium = sum(
            1
            for c in cases
            if priority_tiers["medium"] <= c["fraud_score"] < priority_tiers["high"]
        )
        low = sum(1 for c in cases if c["fraud_score"] < priority_tiers["medium"])

        top_3 = cases[:3]

        return {
            "cases": cases,
            "total_cases": len(cases),
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": low,
            "top_3": top_3,
        }

    # ------------------------------------------------------------------ #
    #                              STEP                                   #
    # ------------------------------------------------------------------ #

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
        criteria = {}
        total_score = 0
        max_score = 0

        # ---- 1. CSV structure (10 pts) ----
        csv_path = os.path.join(self.workspace, "fraud_cases.csv")
        expected_cols = [
            "claim_id",
            "claimant_name",
            "provider_name",
            "fraud_score",
            "priority_rank",
            "evidence_summary",
        ]
        csv_rows = []
        csv_ok = False
        if os.path.exists(csv_path):
            try:
                with open(csv_path, newline="") as f:
                    reader = csv.DictReader(f)
                    headers = [h.strip() for h in (reader.fieldnames or [])]
                    if all(c in headers for c in expected_cols):
                        csv_rows = [r for r in reader]
                        csv_ok = True
            except Exception:
                pass

        pts = 10 if csv_ok else 0
        criteria["csv_structure"] = {
            "passed": csv_ok,
            "score": pts,
            "max_score": 10,
            "reason": "" if csv_ok else "fraud_cases.csv missing or has wrong columns",
        }
        total_score += pts
        max_score += 10

        # ---- 2. CSV completeness (15 pts) ----
        gt_ids = {c["claim_id"] for c in gt["cases"]}
        agent_ids = {r["claim_id"].strip() for r in csv_rows} if csv_rows else set()
        completeness_ok = gt_ids == agent_ids
        pts = 15 if completeness_ok else 0
        reason = ""
        if not completeness_ok:
            missing = gt_ids - agent_ids
            extra = agent_ids - gt_ids
            parts = []
            if missing:
                parts.append(f"missing {len(missing)}")
            if extra:
                parts.append(f"extra {len(extra)}")
            reason = ", ".join(parts)
        criteria["csv_completeness"] = {
            "passed": completeness_ok,
            "score": pts,
            "max_score": 15,
            "reason": reason,
        }
        total_score += pts
        max_score += 15

        # ---- 3. Fraud scores (25 pts) ----
        if csv_rows and csv_ok:
            gt_scores = {c["claim_id"]: c["fraud_score"] for c in gt["cases"]}
            correct = 0
            total_checked = 0
            for row in csv_rows:
                cid = row["claim_id"].strip()
                if cid in gt_scores:
                    total_checked += 1
                    try:
                        agent_score = int(float(row["fraud_score"].strip()))
                        if abs(agent_score - gt_scores[cid]) <= 2:
                            correct += 1
                    except (ValueError, KeyError):
                        pass
            if total_checked > 0:
                frac = correct / total_checked
            else:
                frac = 0
            pts = round(25 * frac)
            scores_ok = frac >= 0.99
        else:
            pts = 0
            scores_ok = False
            frac = 0
        criteria["fraud_scores"] = {
            "passed": scores_ok,
            "score": pts,
            "max_score": 25,
            "reason": "" if scores_ok else f"accuracy {frac:.2%}",
        }
        total_score += pts
        max_score += 25

        # ---- 4. Ranking (15 pts) ----
        ranking_ok = False
        if csv_rows and csv_ok:
            gt_ranking = {c["claim_id"]: c["priority_rank"] for c in gt["cases"]}
            correct_rank = 0
            total_rank = 0
            for row in csv_rows:
                cid = row["claim_id"].strip()
                if cid in gt_ranking:
                    total_rank += 1
                    try:
                        agent_rank = int(float(row["priority_rank"].strip()))
                        if agent_rank == gt_ranking[cid]:
                            correct_rank += 1
                    except (ValueError, KeyError):
                        pass
            if total_rank > 0:
                rank_frac = correct_rank / total_rank
            else:
                rank_frac = 0
            pts = round(15 * rank_frac)
            ranking_ok = rank_frac >= 0.99
        else:
            pts = 0
            rank_frac = 0
        criteria["ranking"] = {
            "passed": ranking_ok,
            "score": pts,
            "max_score": 15,
            "reason": "" if ranking_ok else f"accuracy {rank_frac:.2%}",
        }
        total_score += pts
        max_score += 15

        # ---- 5. Evidence summaries (20 pts) ----
        evidence_ok = False
        if csv_rows and csv_ok:
            gt_evidence = {c["claim_id"]: c["evidence_summary"] for c in gt["cases"]}
            correct_ev = 0
            total_ev = 0
            for row in csv_rows:
                cid = row["claim_id"].strip()
                if cid in gt_evidence:
                    total_ev += 1
                    agent_ev = row.get("evidence_summary", "").strip()
                    if agent_ev == gt_evidence[cid]:
                        correct_ev += 1
            if total_ev > 0:
                ev_frac = correct_ev / total_ev
            else:
                ev_frac = 0
            pts = round(20 * ev_frac)
            evidence_ok = ev_frac >= 0.99
        else:
            pts = 0
            ev_frac = 0
        criteria["evidence_summaries"] = {
            "passed": evidence_ok,
            "score": pts,
            "max_score": 20,
            "reason": "" if evidence_ok else f"accuracy {ev_frac:.2%}",
        }
        total_score += pts
        max_score += 20

        # ---- 6. Summary statistics in action (15 pts) ----
        summary_pts = 0
        summary_max = 15
        checks = []
        action_lower = action.lower() if action else ""

        # Total cases
        if f"total cases analyzed: {gt['total_cases']}" in action_lower:
            summary_pts += 3
            checks.append(True)
        else:
            checks.append(False)

        # Tier counts
        for tier_name, tier_count in [
            ("critical", gt["critical"]),
            ("high", gt["high"]),
            ("medium", gt["medium"]),
            ("low", gt["low"]),
        ]:
            if f"{tier_name}: {tier_count}" in action_lower:
                summary_pts += 2
                checks.append(True)
            else:
                checks.append(False)

        # Top 3 claim IDs
        top3_found = 0
        for c in gt["top_3"]:
            if c["claim_id"].lower() in action_lower:
                top3_found += 1
        if top3_found == len(gt["top_3"]):
            summary_pts += 4
            checks.append(True)
        else:
            checks.append(False)

        summary_ok = summary_pts == summary_max
        criteria["summary_statistics"] = {
            "passed": summary_ok,
            "score": summary_pts,
            "max_score": summary_max,
            "reason": "" if summary_ok else "some summary items missing or incorrect",
        }
        total_score += summary_pts
        max_score += summary_max

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ------------------------------------------------------------------ #
    #                             VERIFY                                  #
    # ------------------------------------------------------------------ #

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
        from datetime import datetime, timedelta

        # --- Step 1: Load config from workspace ---
        with open(os.path.join(self.workspace, "fraud_scoring_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        weights = rules["scoring_weights"]
        thresholds = rules["thresholds"]
        prov_risk_thresh = rules["provider_risk_thresholds"]
        priority_tiers = rules["priority_tiers"]

        # Regional adjustments
        regional_adj = {}
        with open(
            os.path.join(self.workspace, "regional_cost_adjustments.csv"), newline=""
        ) as f:
            for row in csv.DictReader(f):
                regional_adj[row["region"]] = float(row["adjustment_factor"])

        # Provider deviations from audit files
        prov_devs = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("provider_audit_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                for p in data["providers"]:
                    prov_devs[p["provider_id"]] = p["avg_claim_deviation_pct"]

        # Adjuster flags from report files
        RED_FLAG_KEYWORDS = [
            "inconsistent statements",
            "pre-existing condition suspected",
            "unverified injury",
            "suspicious timing",
            "conflicting documentation",
            "exaggerated symptoms",
        ]
        adj_flags = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("adjuster_report_") and fname.endswith(".md"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                sections = re.split(r"## Claim (CLM-\d+)", content)
                i = 1
                while i < len(sections) - 1:
                    cid = sections[i]
                    text = sections[i + 1].lower()
                    found = set()
                    for kw in RED_FLAG_KEYWORDS:
                        if kw in text:
                            found.add(kw)
                    adj_flags[cid] = found
                    i += 2

        # --- Step 2: Find all under_investigation claims via tools ---
        all_inv_claims = []
        page = 1
        while True:
            result = self.tools["search_claims"](
                status="under_investigation", page=page, page_size=20
            )
            all_inv_claims.extend(result["claims"])
            if page >= result["total_pages"]:
                break
            page += 1

        # --- Step 3: For each claim, gather details via tools ---
        # Cache to avoid redundant calls
        policy_cache = {}
        claimant_cache = {}
        provider_cache = {}
        billing_cache = {}
        history_cache = {}

        cases = []
        for basic in all_inv_claims:
            cid = basic["claim_id"]

            # Get full claim details
            claim = self.tools["get_claim_details"](claim_id=cid)

            # Get policy
            pol_id = claim["policy_id"]
            if pol_id not in policy_cache:
                policy_cache[pol_id] = self.tools["get_policy_details"](
                    policy_id=pol_id
                )
            policy = policy_cache[pol_id]

            # Get claimant
            clt_id = claim["claimant_id"]
            if clt_id not in claimant_cache:
                claimant_cache[clt_id] = self.tools["get_claimant_info"](
                    claimant_id=clt_id
                )
            claimant = claimant_cache[clt_id]

            # Get provider
            prv_id = claim["provider_id"]
            if prv_id not in provider_cache:
                provider_cache[prv_id] = self.tools["get_provider_info"](
                    provider_id=prv_id
                )
            provider = provider_cache[prv_id]

            # Get billing code
            pcode = claim["procedure_code"]
            if pcode not in billing_cache:
                billing_cache[pcode] = self.tools["lookup_billing_code"](
                    procedure_code=pcode
                )
            bcode = billing_cache[pcode]

            # Get claim history
            if clt_id not in history_cache:
                history_cache[clt_id] = self.tools["get_claim_history"](
                    claimant_id=clt_id
                )
            history = history_cache[clt_id]

            # --- Compute fraud factors ---
            triggered = []

            # 1. amount_anomaly
            region = provider.get("region", "")
            adj_factor = regional_adj.get(region, 1.0)
            adjusted_max = bcode["expected_max"] * adj_factor
            if claim["claim_amount"] > adjusted_max * (
                1 + thresholds["amount_deviation_pct"] / 100
            ):
                triggered.append("amount_anomaly")

            # 2. rapid_claims
            claim_dt = datetime.fromisoformat(claim["claim_date"])
            count_in_window = sum(
                1
                for h in history["claims"]
                if abs(
                    (datetime.fromisoformat(h["claim_date"]) - claim_dt).days
                )
                <= thresholds["rapid_claims_window_days"]
            )
            if count_in_window >= thresholds["rapid_claims_min_count"]:
                triggered.append("rapid_claims")

            # 3. provider_risk
            dev = prov_devs.get(claim["provider_id"], 0)
            if dev >= prov_risk_thresh["high"]:
                triggered.append("provider_risk")

            # 4. new_policy
            policy_start = datetime.fromisoformat(policy["start_date"])
            days_diff = (claim_dt - policy_start).days
            if 0 <= days_diff <= thresholds["new_policy_max_days"]:
                triggered.append("new_policy")

            # 5. adjuster_flags
            if len(adj_flags.get(cid, set())) > 0:
                triggered.append("adjuster_flags")

            # 6. coverage_ratio
            ratio = claim["claim_amount"] / policy["coverage_amount"]
            if ratio >= thresholds["coverage_ratio_min"]:
                triggered.append("coverage_ratio")

            fraud_score = sum(weights[t] for t in triggered)
            cname = f"{claimant['first_name']} {claimant['last_name']}"
            pname = provider["provider_name"]
            evidence = "|".join(triggered) if triggered else ""

            cases.append(
                {
                    "claim_id": cid,
                    "claimant_name": cname,
                    "provider_name": pname,
                    "fraud_score": fraud_score,
                    "evidence_summary": evidence,
                }
            )

        # --- Step 4: Sort and rank ---
        cases.sort(key=lambda x: (-x["fraud_score"], x["claim_id"]))
        for rank, c in enumerate(cases, 1):
            c["priority_rank"] = rank

        # --- Step 5: Write fraud_cases.csv ---
        csv_path = os.path.join(self.workspace, "fraud_cases.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "claim_id",
                    "claimant_name",
                    "provider_name",
                    "fraud_score",
                    "priority_rank",
                    "evidence_summary",
                ],
            )
            writer.writeheader()
            for c in cases:
                writer.writerow(
                    {
                        "claim_id": c["claim_id"],
                        "claimant_name": c["claimant_name"],
                        "provider_name": c["provider_name"],
                        "fraud_score": c["fraud_score"],
                        "priority_rank": c["priority_rank"],
                        "evidence_summary": c["evidence_summary"],
                    }
                )

        # --- Step 6: Build action string ---
        total_cases = len(cases)
        critical = sum(
            1 for c in cases if c["fraud_score"] >= priority_tiers["critical"]
        )
        high = sum(
            1
            for c in cases
            if priority_tiers["high"] <= c["fraud_score"] < priority_tiers["critical"]
        )
        medium = sum(
            1
            for c in cases
            if priority_tiers["medium"] <= c["fraud_score"] < priority_tiers["high"]
        )
        low = sum(
            1 for c in cases if c["fraud_score"] < priority_tiers["medium"]
        )

        top_3 = cases[:3]
        top_3_lines = "\n".join(
            f"  {c['claim_id']}: fraud_score={c['fraud_score']}, evidence={c['evidence_summary']}"
            for c in top_3
        )

        action = (
            f"Total cases analyzed: {total_cases}\n"
            f"Critical: {critical}\n"
            f"High: {high}\n"
            f"Medium: {medium}\n"
            f"Low: {low}\n"
            f"\nTop 3 highest-scoring cases:\n{top_3_lines}\n"
            f"\nAll results saved to fraud_cases.csv."
        )

        return self.step(action)
