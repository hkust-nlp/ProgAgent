"""
REC Portfolio Compliance Gap Analysis - Task Environment
"""

import csv
import json
import math
import os
import re
import sqlite3
from datetime import date
from typing import Any, Dict, List, Tuple


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
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row

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

    # ───────────────────── Tool methods ─────────────────────

    @tool(
        description="Returns a paginated list of REC portfolios.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 25).",
                },
                "jurisdiction_filter": {
                    "type": "string",
                    "description": "Optional jurisdiction code to filter by.",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_portfolios(self, page: int, page_size: int, jurisdiction_filter: str = None):
        page_size = min(int(page_size), 25)
        page = max(int(page), 1)
        offset = (page - 1) * page_size

        if jurisdiction_filter:
            rows = self._conn.execute(
                "SELECT * FROM portfolios WHERE jurisdiction_code = ? ORDER BY portfolio_id LIMIT ? OFFSET ?",
                (jurisdiction_filter, page_size, offset),
            ).fetchall()
            total = self._conn.execute(
                "SELECT COUNT(*) FROM portfolios WHERE jurisdiction_code = ?",
                (jurisdiction_filter,),
            ).fetchone()[0]
        else:
            rows = self._conn.execute(
                "SELECT * FROM portfolios ORDER BY portfolio_id LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
            total = self._conn.execute("SELECT COUNT(*) FROM portfolios").fetchone()[0]

        total_pages = math.ceil(total / page_size) if page_size > 0 else 1
        return {
            "portfolios": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "total_pages": total_pages,
        }

    @tool(
        description="Returns full details for a single portfolio.",
        parameters={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "string",
                    "description": "The portfolio ID (e.g. P-0001).",
                },
            },
            "required": ["portfolio_id"],
        },
    )
    def get_portfolio_details(self, portfolio_id: str):
        row = self._conn.execute(
            "SELECT * FROM portfolios WHERE portfolio_id = ?", (portfolio_id,)
        ).fetchone()
        if row is None:
            return {"error": f"Portfolio {portfolio_id} not found"}
        return dict(row)

    @tool(
        description="Returns all certificates for a given portfolio.",
        parameters={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "string",
                    "description": "The portfolio ID.",
                },
            },
            "required": ["portfolio_id"],
        },
    )
    def get_certificates(self, portfolio_id: str):
        rows = self._conn.execute(
            "SELECT * FROM certificates WHERE portfolio_id = ? ORDER BY cert_id",
            (portfolio_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    @tool(
        description="Returns all purchase contracts for a given portfolio.",
        parameters={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "string",
                    "description": "The portfolio ID.",
                },
            },
            "required": ["portfolio_id"],
        },
    )
    def get_contracts(self, portfolio_id: str):
        rows = self._conn.execute(
            "SELECT * FROM purchase_contracts WHERE portfolio_id = ? ORDER BY contract_id",
            (portfolio_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    @tool(
        description="Returns details for a single facility.",
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility ID (e.g. F-0001).",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_facility_info(self, facility_id: str):
        row = self._conn.execute(
            "SELECT * FROM facilities WHERE facility_id = ?", (facility_id,)
        ).fetchone()
        if row is None:
            return {"error": f"Facility {facility_id} not found"}
        return dict(row)

    @tool(
        description="Returns all grid injection records for a given facility.",
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility ID.",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_injections(self, facility_id: str):
        rows = self._conn.execute(
            "SELECT * FROM grid_injections WHERE facility_id = ? ORDER BY injection_id",
            (facility_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    @tool(
        description="Returns regulatory deadlines for a given jurisdiction.",
        parameters={
            "type": "object",
            "properties": {
                "jurisdiction_code": {
                    "type": "string",
                    "description": "The jurisdiction code (e.g. CA, TX, PJM).",
                },
            },
            "required": ["jurisdiction_code"],
        },
    )
    def get_deadlines(self, jurisdiction_code: str):
        rows = self._conn.execute(
            "SELECT * FROM regulatory_deadlines WHERE jurisdiction_code = ? ORDER BY deadline_date",
            (jurisdiction_code,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ───────────────────── Shared compliance engine ─────────────────────

    def _load_workspace_data(self):
        """Load all workspace files and return parsed structures."""
        # 1. Compliance config
        with open(os.path.join(self.workspace, "compliance_config.json")) as f:
            config = json.load(f)

        # 2. Technology multipliers
        tech_mult = {}
        with open(os.path.join(self.workspace, "technology_multipliers.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                tech_mult[row["tech_type"]] = float(row["credit_multiplier"])

        # 3. Penalty schedule (simple YAML parsing)
        penalty = {}
        with open(os.path.join(self.workspace, "penalty_schedule.yaml")) as f:
            current_jur = None
            for line in f:
                line = line.rstrip()
                if not line:
                    continue
                if not line.startswith(" "):
                    current_jur = line.rstrip(":")
                    penalty[current_jur] = {}
                else:
                    key, val = line.strip().split(": ", 1)
                    penalty[current_jur][key] = float(val)

        # 4. Portfolio adjustments
        adjustments = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("portfolio_adjustments_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        adjustments[row["portfolio_id"]] = float(row["adjustment_factor"])

        # 5. Contract amendments
        amendments = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("contract_amendments_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                blocks = re.split(r"---\n?", content)
                for block in blocks:
                    block = block.strip()
                    if not block:
                        continue
                    cid_match = re.search(r"Contract ID:\s*(\S+)", block)
                    mwh_match = re.search(r"Amended MWh:\s*([\d.]+)", block)
                    if cid_match and mwh_match:
                        amendments[cid_match.group(1)] = float(mwh_match.group(1))

        # 6. Injection overrides
        inj_overrides = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("injection_overrides_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                for item in data:
                    inj_overrides[item["injection_id"]] = item["verified_override"]

        # 7. Cert status updates
        cert_updates = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("cert_updates_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                for match in re.finditer(
                    r'- cert_id:\s*"([^"]+)"\s*\n\s*updated_status:\s*"([^"]+)"',
                    content,
                ):
                    cert_updates[match.group(1)] = match.group(2)

        return config, tech_mult, penalty, adjustments, amendments, inj_overrides, cert_updates

    def _compute_ground_truth(self):
        """Compute the full ground truth compliance analysis using direct DB access."""
        config, tech_mult, penalty, adjustments, amendments, inj_overrides, cert_updates = (
            self._load_workspace_data()
        )

        eligible_years = config["eligible_vintage_years"]
        reference_date = date.fromisoformat(config["reference_date"])
        min_threshold = config["minimum_shortfall_threshold_mwh"]

        portfolios_2026 = self._conn.execute(
            "SELECT * FROM portfolios WHERE compliance_year = 2026 ORDER BY portfolio_id"
        ).fetchall()

        results = []

        for prow in portfolios_2026:
            pid = prow["portfolio_id"]
            owner = prow["owner_name"]
            jur = prow["jurisdiction_code"]
            target = prow["target_mwh"]
            tech_pref = prow["technology_preference"]

            # 1. Adjusted target
            adj_factor = adjustments.get(pid, 1.0)
            adjusted_target = target * adj_factor

            # 2. Current holdings
            certs = self._conn.execute(
                "SELECT * FROM certificates WHERE portfolio_id = ?", (pid,)
            ).fetchall()

            current_holdings = 0.0
            active_tech_counts = {}
            cert_facility_ids = set()
            for c in certs:
                cert_facility_ids.add(c["facility_id"])
                cid = c["cert_id"]
                effective_status = cert_updates.get(cid, c["status"])
                if effective_status == "active" and c["vintage_year"] in eligible_years:
                    mult = tech_mult.get(c["tech_type"], 1.0)
                    current_holdings += c["capacity_mwh"] * mult
                if effective_status == "active":
                    tt = c["tech_type"]
                    active_tech_counts[tt] = active_tech_counts.get(tt, 0) + 1

            # 3. Get annual compliance deadline
            deadline_row = self._conn.execute(
                "SELECT deadline_date FROM regulatory_deadlines "
                "WHERE jurisdiction_code = ? AND submission_type = 'annual_compliance'",
                (jur,),
            ).fetchone()
            if deadline_row is None:
                continue
            deadline_date_val = date.fromisoformat(deadline_row["deadline_date"])

            # 4. Pending deliveries
            contracts = self._conn.execute(
                "SELECT * FROM purchase_contracts WHERE portfolio_id = ?", (pid,)
            ).fetchall()

            pending_deliveries = 0.0
            for con in contracts:
                if con["delivery_status"] == "pending":
                    del_date = date.fromisoformat(con["delivery_date"])
                    if del_date <= deadline_date_val:
                        amended_mwh = amendments.get(
                            con["contract_id"], con["contracted_mwh"]
                        )
                        pending_deliveries += amended_mwh

            # 5. Injection credits
            injection_credits = 0.0
            for fid in cert_facility_ids:
                injs = self._conn.execute(
                    "SELECT * FROM grid_injections WHERE facility_id = ?", (fid,)
                ).fetchall()
                for inj in injs:
                    eff_verified = inj_overrides.get(
                        inj["injection_id"], bool(inj["verified"])
                    )
                    if eff_verified and not inj["credited"]:
                        injection_credits += inj["injected_mwh"]

            # 6. Shortfall
            total_available = current_holdings + pending_deliveries + injection_credits
            shortfall = adjusted_target - total_available

            if shortfall <= min_threshold:
                continue

            # 7. Priority score
            days_until = (deadline_date_val - reference_date).days
            penalty_rate = penalty.get(jur, {}).get("penalty_rate_per_mwh", 0.0)
            priority_score = (shortfall / adjusted_target) * penalty_rate / max(days_until, 1)

            # 8. Recommended tech
            if tech_pref and tech_pref != "any":
                recommended_tech = tech_pref
            elif active_tech_counts:
                recommended_tech = max(active_tech_counts, key=active_tech_counts.get)
            else:
                recommended_tech = max(tech_mult, key=tech_mult.get)

            results.append({
                "portfolio_id": pid,
                "owner_name": owner,
                "jurisdiction_code": jur,
                "adjusted_target_mwh": round(adjusted_target, 2),
                "current_holdings_mwh": round(current_holdings, 2),
                "expected_incoming_mwh": round(pending_deliveries + injection_credits, 2),
                "shortfall_mwh": round(shortfall, 2),
                "priority_score": round(priority_score, 4),
                "recommended_tech": recommended_tech,
                "deadline_date": deadline_date_val.isoformat(),
                "days_until_deadline": days_until,
                "penalty_rate": penalty_rate,
            })

        results.sort(key=lambda x: (-x["priority_score"], x["portfolio_id"]))
        return results, len([r for r in portfolios_2026])

    # ───────────────────── step() ─────────────────────

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
        gt, total_2026 = self._compute_ground_truth()
        gt_ids = set(r["portfolio_id"] for r in gt)

        eval_criteria = {}

        # ── Criterion 1: procurement_list.csv exists with correct columns (10 pts) ──
        csv_path = os.path.join(self.workspace, "procurement_list.csv")
        expected_cols = [
            "portfolio_id", "owner_name", "jurisdiction_code",
            "adjusted_target_mwh", "current_holdings_mwh", "expected_incoming_mwh",
            "shortfall_mwh", "priority_score", "recommended_tech",
            "deadline_date", "days_until_deadline", "penalty_rate",
        ]
        agent_rows = []
        csv_ok = False
        if os.path.exists(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and set(expected_cols).issubset(set(reader.fieldnames)):
                    csv_ok = True
                    for row in reader:
                        agent_rows.append(row)
        eval_criteria["csv_format"] = {
            "passed": csv_ok,
            "score": 10 if csv_ok else 0,
            "max_score": 10,
            "reason": "" if csv_ok else "procurement_list.csv missing or has wrong columns",
        }

        # ── Criterion 2: Correct at-risk portfolio IDs (20 pts) ──
        agent_ids = set(r.get("portfolio_id", "") for r in agent_rows)
        if agent_ids == gt_ids and len(agent_ids) > 0:
            c2_score = 20
            c2_reason = ""
        elif len(gt_ids) > 0:
            correct = len(agent_ids & gt_ids)
            expected = len(gt_ids)
            partial = int(20 * correct / expected) if expected > 0 else 0
            extras = len(agent_ids - gt_ids)
            partial = max(0, partial - extras * 2)
            c2_score = partial
            c2_reason = f"matched {correct}/{expected}, extras {extras}"
        else:
            c2_score = 0
            c2_reason = "no ground truth portfolios found"
        eval_criteria["portfolio_ids"] = {
            "passed": c2_score == 20,
            "score": c2_score,
            "max_score": 20,
            "reason": c2_reason,
        }

        # ── Criterion 3: Correct shortfall calculations (20 pts) ──
        gt_shortfalls = {r["portfolio_id"]: r["shortfall_mwh"] for r in gt}
        agent_shortfalls = {}
        for r in agent_rows:
            try:
                agent_shortfalls[r["portfolio_id"]] = float(r["shortfall_mwh"])
            except (KeyError, ValueError):
                pass

        if gt_shortfalls:
            matched = 0
            for pid, expected_sf in gt_shortfalls.items():
                agent_sf = agent_shortfalls.get(pid)
                if agent_sf is not None and abs(agent_sf - expected_sf) <= 0.01:
                    matched += 1
            ratio = matched / len(gt_shortfalls)
            c3_score = int(20 * ratio)
            c3_reason = f"{matched}/{len(gt_shortfalls)} shortfalls correct"
        else:
            c3_score = 0
            c3_reason = "no ground truth data"
        eval_criteria["shortfall_values"] = {
            "passed": c3_score == 20,
            "score": c3_score,
            "max_score": 20,
            "reason": "" if c3_score == 20 else c3_reason,
        }

        # ── Criterion 4: Correct priority scoring and sort order (15 pts) ──
        gt_scores = {r["portfolio_id"]: r["priority_score"] for r in gt}
        agent_scores_map = {}
        for r in agent_rows:
            try:
                agent_scores_map[r["portfolio_id"]] = float(r["priority_score"])
            except (KeyError, ValueError):
                pass

        c4_score = 0
        c4_reason = ""
        if gt_scores:
            matched_scores = 0
            for pid, expected_ps in gt_scores.items():
                agent_ps = agent_scores_map.get(pid)
                if agent_ps is not None and abs(agent_ps - expected_ps) <= 0.001:
                    matched_scores += 1
            ratio = matched_scores / len(gt_scores)
            c4_vals = int(10 * ratio)

            gt_order = [r["portfolio_id"] for r in gt]
            agent_order = [r.get("portfolio_id", "") for r in agent_rows if r.get("portfolio_id", "") in gt_ids]
            c4_order = 5 if agent_order == gt_order else 0
            c4_score = c4_vals + c4_order
            if c4_score < 15:
                c4_reason = f"scores: {matched_scores}/{len(gt_scores)}, order: {'correct' if c4_order == 5 else 'wrong'}"
        eval_criteria["priority_and_sort"] = {
            "passed": c4_score == 15,
            "score": c4_score,
            "max_score": 15,
            "reason": "" if c4_score == 15 else c4_reason,
        }

        # ── Criterion 5: compliance_summary.json (20 pts) ──
        summary_path = os.path.join(self.workspace, "compliance_summary.json")
        c5_score = 0
        c5_reason = ""
        if os.path.exists(summary_path):
            with open(summary_path) as f:
                try:
                    summary = json.load(f)
                except json.JSONDecodeError:
                    summary = {}

            gt_at_risk = len(gt)
            gt_total_shortfall = round(sum(r["shortfall_mwh"] for r in gt), 2)
            gt_avg_priority = round(
                sum(r["priority_score"] for r in gt) / len(gt), 4
            ) if gt else 0.0
            gt_top3 = [r["portfolio_id"] for r in gt[:3]]

            checks = 0
            if summary.get("total_portfolios_analyzed") == total_2026:
                checks += 1
            if summary.get("at_risk_count") == gt_at_risk:
                checks += 1
            if isinstance(summary.get("total_shortfall_mwh"), (int, float)):
                if abs(summary["total_shortfall_mwh"] - gt_total_shortfall) <= 0.1:
                    checks += 1
            if isinstance(summary.get("average_priority_score"), (int, float)):
                if abs(summary["average_priority_score"] - gt_avg_priority) <= 0.01:
                    checks += 1
            if summary.get("top_3_portfolio_ids") == gt_top3:
                checks += 1

            c5_score = int(20 * checks / 5)
            if checks < 5:
                c5_reason = f"{checks}/5 summary fields correct"
        else:
            c5_reason = "compliance_summary.json not found"
        eval_criteria["compliance_summary"] = {
            "passed": c5_score == 20,
            "score": c5_score,
            "max_score": 20,
            "reason": "" if c5_score == 20 else c5_reason,
        }

        # ── Criterion 6: Final response text (15 pts) ──
        c6_score = 0
        c6_reason = ""
        if action:
            gt_count = len(gt)
            gt_total_shortfall = round(sum(r["shortfall_mwh"] for r in gt), 2)
            gt_top3 = [r["portfolio_id"] for r in gt[:3]]

            if str(gt_count) in action:
                c6_score += 5
            if str(gt_total_shortfall) in action:
                c6_score += 5
            if all(pid in action for pid in gt_top3):
                c6_score += 5
            if c6_score < 15:
                missing = []
                if str(gt_count) not in action:
                    missing.append("count")
                if str(gt_total_shortfall) not in action:
                    missing.append("shortfall")
                if not all(pid in action for pid in gt_top3):
                    missing.append("top3")
                c6_reason = f"missing: {', '.join(missing)}"
        else:
            c6_reason = "empty response"
        eval_criteria["response_text"] = {
            "passed": c6_score == 15,
            "score": c6_score,
            "max_score": 15,
            "reason": "" if c6_score == 15 else c6_reason,
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return total_score / max_score, info

    # ───────────────────── verify() ─────────────────────

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
        # Load workspace config and scaling data
        config, tech_mult, penalty, adjustments, amendments, inj_overrides, cert_updates = (
            self._load_workspace_data()
        )

        eligible_years = config["eligible_vintage_years"]
        reference_date = date.fromisoformat(config["reference_date"])
        min_threshold = config["minimum_shortfall_threshold_mwh"]

        # Gather all portfolios via paginated tool calls
        all_portfolios = []
        page = 1
        tool_call_count = 0
        while True:
            result = self.tools["list_portfolios"](page=page, page_size=25)
            tool_call_count += 1
            all_portfolios.extend(result["portfolios"])
            if page >= result["total_pages"]:
                break
            page += 1

        portfolios_2026 = [p for p in all_portfolios if p["compliance_year"] == 2026]

        # Cache deadline lookups per jurisdiction
        deadline_cache = {}
        results = []

        for p in portfolios_2026:
            pid = p["portfolio_id"]

            # Tool call: get portfolio details
            pdetails = self.tools["get_portfolio_details"](portfolio_id=pid)
            tool_call_count += 1

            jur = pdetails["jurisdiction_code"]
            target = pdetails["target_mwh"]
            tech_pref = pdetails["technology_preference"]

            # Adjusted target
            adj_factor = adjustments.get(pid, 1.0)
            adjusted_target = target * adj_factor

            # Tool call: get certificates
            certs = self.tools["get_certificates"](portfolio_id=pid)
            tool_call_count += 1

            current_holdings = 0.0
            active_tech_counts = {}
            cert_facility_ids = set()
            for c in certs:
                cert_facility_ids.add(c["facility_id"])
                cid = c["cert_id"]
                effective_status = cert_updates.get(cid, c["status"])
                if effective_status == "active" and c["vintage_year"] in eligible_years:
                    mult = tech_mult.get(c["tech_type"], 1.0)
                    current_holdings += c["capacity_mwh"] * mult
                if effective_status == "active":
                    tt = c["tech_type"]
                    active_tech_counts[tt] = active_tech_counts.get(tt, 0) + 1

            # Tool call: get deadlines (cached per jurisdiction)
            if jur not in deadline_cache:
                deadlines = self.tools["get_deadlines"](jurisdiction_code=jur)
                tool_call_count += 1
                annual_dl = None
                for dl in deadlines:
                    if dl["submission_type"] == "annual_compliance":
                        annual_dl = dl
                        break
                deadline_cache[jur] = annual_dl
            annual_dl = deadline_cache[jur]
            if annual_dl is None:
                continue
            deadline_date_val = date.fromisoformat(annual_dl["deadline_date"])

            # Tool call: get contracts
            contracts = self.tools["get_contracts"](portfolio_id=pid)
            tool_call_count += 1

            pending_deliveries = 0.0
            for con in contracts:
                if con["delivery_status"] == "pending":
                    del_date = date.fromisoformat(con["delivery_date"])
                    if del_date <= deadline_date_val:
                        amended_mwh = amendments.get(
                            con["contract_id"], con["contracted_mwh"]
                        )
                        pending_deliveries += amended_mwh

            # Tool calls: get injections for each facility linked to this portfolio
            injection_credits = 0.0
            for fid in cert_facility_ids:
                injs = self.tools["get_injections"](facility_id=fid)
                tool_call_count += 1
                for inj in injs:
                    eff_verified = inj_overrides.get(
                        inj["injection_id"], bool(inj["verified"])
                    )
                    if eff_verified and not inj["credited"]:
                        injection_credits += inj["injected_mwh"]

            total_available = current_holdings + pending_deliveries + injection_credits
            shortfall = adjusted_target - total_available

            if shortfall <= min_threshold:
                continue

            days_until = (deadline_date_val - reference_date).days
            penalty_rate = penalty.get(jur, {}).get("penalty_rate_per_mwh", 0.0)
            priority_score = (shortfall / adjusted_target) * penalty_rate / max(days_until, 1)

            if tech_pref and tech_pref != "any":
                recommended_tech = tech_pref
            elif active_tech_counts:
                recommended_tech = max(active_tech_counts, key=active_tech_counts.get)
            else:
                recommended_tech = max(tech_mult, key=tech_mult.get)

            results.append({
                "portfolio_id": pid,
                "owner_name": pdetails["owner_name"],
                "jurisdiction_code": jur,
                "adjusted_target_mwh": round(adjusted_target, 2),
                "current_holdings_mwh": round(current_holdings, 2),
                "expected_incoming_mwh": round(pending_deliveries + injection_credits, 2),
                "shortfall_mwh": round(shortfall, 2),
                "priority_score": round(priority_score, 4),
                "recommended_tech": recommended_tech,
                "deadline_date": deadline_date_val.isoformat(),
                "days_until_deadline": days_until,
                "penalty_rate": penalty_rate,
            })

        # Sort by priority_score descending, portfolio_id ascending
        results.sort(key=lambda x: (-x["priority_score"], x["portfolio_id"]))

        # Write procurement_list.csv
        csv_path = os.path.join(self.workspace, "procurement_list.csv")
        fieldnames = [
            "portfolio_id", "owner_name", "jurisdiction_code",
            "adjusted_target_mwh", "current_holdings_mwh", "expected_incoming_mwh",
            "shortfall_mwh", "priority_score", "recommended_tech",
            "deadline_date", "days_until_deadline", "penalty_rate",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        # Write compliance_summary.json
        at_risk_count = len(results)
        total_shortfall = round(sum(r["shortfall_mwh"] for r in results), 2)
        avg_priority = round(
            sum(r["priority_score"] for r in results) / len(results), 4
        ) if results else 0.0
        top3 = [r["portfolio_id"] for r in results[:3]]

        summary = {
            "total_portfolios_analyzed": len(portfolios_2026),
            "at_risk_count": at_risk_count,
            "total_shortfall_mwh": total_shortfall,
            "average_priority_score": avg_priority,
            "top_3_portfolio_ids": top3,
        }
        with open(os.path.join(self.workspace, "compliance_summary.json"), "w") as f:
            json.dump(summary, f, indent=2)

        # Build response text
        response = (
            f"At-risk portfolios: {at_risk_count}. "
            f"Total shortfall: {total_shortfall} MWh. "
            f"Top 3 priority portfolio IDs: {', '.join(top3)}."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made"

        return self.step(response)
