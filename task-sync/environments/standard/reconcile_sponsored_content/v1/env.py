"""
Sponsored Content Delivery Reconciliation - Task Environment
"""
import csv
import json
import os
import sqlite3
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

    # ── Tools ───────────────────────────────────────────────────────

    @tool(
        description="Look up an insertion order by its reference code. Returns order metadata including id, advertiser_id, status, guaranteed impressions, CPM rate, budget, and contract dates.",
        parameters={
            "type": "object",
            "properties": {
                "order_ref": {
                    "type": "string",
                    "description": "The insertion order reference code, e.g. 'IO-1001'",
                },
            },
            "required": ["order_ref"],
        },
    )
    def lookup_order(self, order_ref: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT id, advertiser_id, order_ref, start_date, end_date, status, "
            "guaranteed_impressions, cpm_rate, total_budget "
            "FROM insertion_orders WHERE order_ref = ?",
            (order_ref,),
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"No order found with ref {order_ref}"}
        return {
            "order_id": row[0],
            "advertiser_id": row[1],
            "order_ref": row[2],
            "start_date": row[3],
            "end_date": row[4],
            "status": row[5],
            "guaranteed_impressions": row[6],
            "cpm_rate": row[7],
            "total_budget": row[8],
        }

    @tool(
        description="Get all campaigns belonging to a given insertion order. Returns campaign id, name, platform, ad format, and status for each campaign.",
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "integer",
                    "description": "The insertion order ID",
                },
            },
            "required": ["order_id"],
        },
    )
    def get_order_campaigns(self, order_id: int) -> list:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT id, campaign_name, platform, ad_format, status "
            "FROM campaigns WHERE order_id = ?",
            (int(order_id),),
        ).fetchall()
        conn.close()
        return [
            {
                "campaign_id": r[0],
                "campaign_name": r[1],
                "platform": r[2],
                "ad_format": r[3],
                "status": r[4],
            }
            for r in rows
        ]

    @tool(
        description="Get total impression and click counts for a specific campaign, aggregated across all dates and segments.",
        parameters={
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "integer",
                    "description": "The campaign ID",
                },
            },
            "required": ["campaign_id"],
        },
    )
    def get_campaign_impressions(self, campaign_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT COALESCE(SUM(impressions_served),0), COALESCE(SUM(clicks),0) "
            "FROM impression_logs WHERE campaign_id = ?",
            (int(campaign_id),),
        ).fetchone()
        conn.close()
        return {
            "campaign_id": int(campaign_id),
            "total_impressions": row[0],
            "total_clicks": row[1],
        }

    @tool(
        description="Get the demographic breakdown of impressions for a campaign. Returns impressions grouped by demographic segment ID.",
        parameters={
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "integer",
                    "description": "The campaign ID",
                },
            },
            "required": ["campaign_id"],
        },
    )
    def get_campaign_demographic_breakdown(self, campaign_id: int) -> list:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT segment_id, SUM(impressions_served) AS impressions, SUM(clicks) AS clicks "
            "FROM impression_logs WHERE campaign_id = ? GROUP BY segment_id",
            (int(campaign_id),),
        ).fetchall()
        conn.close()
        return [
            {"segment_id": r[0], "impressions": r[1], "clicks": r[2]}
            for r in rows
        ]

    @tool(
        description="Get viewability metrics for a campaign aggregated across all reporting periods. Returns total measured impressions, viewable impressions, invalid impressions, and overall viewability rate.",
        parameters={
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "integer",
                    "description": "The campaign ID",
                },
            },
            "required": ["campaign_id"],
        },
    )
    def get_campaign_viewability(self, campaign_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT COALESCE(SUM(measured_impressions),0), "
            "COALESCE(SUM(viewable_impressions),0), "
            "COALESCE(SUM(invalid_impressions),0) "
            "FROM viewability_reports WHERE campaign_id = ?",
            (int(campaign_id),),
        ).fetchone()
        conn.close()
        measured = row[0]
        viewable = row[1]
        invalid_count = row[2]
        rate = viewable / measured if measured > 0 else 0.0
        return {
            "campaign_id": int(campaign_id),
            "total_measured": measured,
            "total_viewable": viewable,
            "total_invalid": invalid_count,
            "viewability_rate": round(rate, 6),
        }

    @tool(
        description="Get advertiser details by advertiser ID. Returns name, industry, contact email, tier, and account status.",
        parameters={
            "type": "object",
            "properties": {
                "advertiser_id": {
                    "type": "integer",
                    "description": "The advertiser ID",
                },
            },
            "required": ["advertiser_id"],
        },
    )
    def get_advertiser_info(self, advertiser_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT id, name, industry, contact_email, tier, account_status "
            "FROM advertisers WHERE id = ?",
            (int(advertiser_id),),
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"No advertiser with id {advertiser_id}"}
        return {
            "advertiser_id": row[0],
            "name": row[1],
            "industry": row[2],
            "contact_email": row[3],
            "tier": row[4],
            "account_status": row[5],
        }

    # ── Helpers for step / verify ───────────────────────────────────

    @staticmethod
    def _parse_simple_yaml(path: str) -> dict:
        """Parse the simple YAML config format used by this task."""
        result = {}
        current_key = None
        with open(path) as f:
            for line in f:
                line = line.rstrip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("  "):
                    k, v = line.strip().split(": ", 1)
                    if current_key is not None:
                        if not isinstance(result[current_key], dict):
                            result[current_key] = {}
                        try:
                            result[current_key][k] = int(v)
                        except ValueError:
                            try:
                                result[current_key][k] = float(v)
                            except ValueError:
                                result[current_key][k] = v
                else:
                    if ": " in line:
                        k, v = line.split(": ", 1)
                        try:
                            result[k] = int(v)
                        except ValueError:
                            try:
                                result[k] = float(v)
                            except ValueError:
                                result[k] = v
                        current_key = None
                    elif line.endswith(":"):
                        current_key = line[:-1]
                        result[current_key] = {}
                    else:
                        current_key = None
        return result

    @staticmethod
    def _read_penalty_schedule(path: str) -> list:
        with open(path) as f:
            reader = csv.DictReader(f)
            return [
                {
                    "min": float(row["shortfall_pct_min"]),
                    "max": float(row["shortfall_pct_max"]),
                    "multiplier": float(row["penalty_multiplier"]),
                }
                for row in reader
            ]

    @staticmethod
    def _get_penalty_multiplier(shortfall_pct: float, schedule: list) -> float:
        for i, bracket in enumerate(schedule):
            if i == len(schedule) - 1:
                if bracket["min"] <= shortfall_pct <= bracket["max"]:
                    return bracket["multiplier"]
            else:
                if bracket["min"] <= shortfall_pct < bracket["max"]:
                    return bracket["multiplier"]
        return 0.0

    @staticmethod
    def _read_tier_adjustments(path: str) -> dict:
        adj = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(": ")
                if len(parts) == 2:
                    adj[parts[0].strip()] = float(parts[1].strip())
        return adj

    @staticmethod
    def _read_seg_mapping(path: str) -> dict:
        """Returns dict: segment_code -> segment_id."""
        mapping = {}
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                mapping[row["segment_code"]] = int(row["segment_id"])
        return mapping

    def _compute_ground_truth(self):
        """Compute ground truth compliance data from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        cfg_dir = os.path.join(self.workspace, "config")

        # Load configs
        thresholds = self._parse_simple_yaml(
            os.path.join(cfg_dir, "compliance_thresholds.yaml")
        )
        base_tolerance = thresholds.get("delivery_tolerance_pct", 2.0)
        penalty_schedule = self._read_penalty_schedule(
            os.path.join(cfg_dir, "penalty_schedule.csv")
        )
        with open(os.path.join(cfg_dir, "viewability_benchmarks.json")) as f:
            benchmarks = json.load(f)
        seg_mapping = self._read_seg_mapping(
            os.path.join(cfg_dir, "demographic_mapping.csv")
        )
        tier_adj = self._read_tier_adjustments(
            os.path.join(cfg_dir, "tier_adjustments.txt")
        )

        # Load all contracts
        contracts_dir = os.path.join(self.workspace, "contracts")
        contracts = {}
        for fname in sorted(os.listdir(contracts_dir)):
            if fname.endswith(".json"):
                with open(os.path.join(contracts_dir, fname)) as f:
                    c = json.load(f)
                    contracts[c["order_ref"]] = c

        ground_truth = {}
        for ref in sorted(contracts.keys()):
            contract = contracts[ref]
            order_row = conn.execute(
                "SELECT id, advertiser_id FROM insertion_orders WHERE order_ref = ?",
                (ref,),
            ).fetchone()
            if not order_row:
                continue
            order_id = order_row[0]

            # Target segment IDs
            target_seg_ids = set()
            for code in contract["target_segments"]:
                sid = seg_mapping.get(code)
                if sid is not None:
                    target_seg_ids.add(sid)

            # Get campaigns
            campaigns = conn.execute(
                "SELECT id, ad_format FROM campaigns WHERE order_id = ?",
                (order_id,),
            ).fetchall()

            total_delivered = 0
            total_target_imp = 0
            total_all_imp = 0
            view_measured = 0
            view_viewable = 0

            for camp_id, ad_format in campaigns:
                # Impressions
                imp_rows = conn.execute(
                    "SELECT segment_id, SUM(impressions_served) "
                    "FROM impression_logs WHERE campaign_id = ? GROUP BY segment_id",
                    (camp_id,),
                ).fetchall()
                camp_total = sum(r[1] for r in imp_rows)
                camp_target = sum(r[1] for r in imp_rows if r[0] in target_seg_ids)
                total_delivered += camp_total
                total_target_imp += camp_target
                total_all_imp += camp_total

                # Viewability
                vrow = conn.execute(
                    "SELECT COALESCE(SUM(measured_impressions),0), "
                    "COALESCE(SUM(viewable_impressions),0) "
                    "FROM viewability_reports WHERE campaign_id = ?",
                    (camp_id,),
                ).fetchone()
                camp_measured = vrow[0]
                camp_viewable = vrow[1]
                min_sample = benchmarks.get(ad_format, {}).get(
                    "min_measurement_sample", 0
                )
                if camp_measured >= min_sample:
                    view_measured += camp_measured
                    view_viewable += camp_viewable

            guaranteed = contract["guaranteed_impressions"]
            delivery_rate = total_delivered / guaranteed if guaranteed > 0 else 0.0
            demo_rate = (
                total_target_imp / total_all_imp if total_all_imp > 0 else 0.0
            )
            view_rate = (
                view_viewable / view_measured if view_measured > 0 else 1.0
            )

            tier = contract.get("advertiser_tier", "Bronze")
            effective_tolerance = base_tolerance + tier_adj.get(tier, 0.0)

            delivery_pass = delivery_rate >= (1 - effective_tolerance / 100)
            demo_pass = demo_rate >= contract["demographic_threshold"]
            view_pass = view_rate >= contract["viewability_threshold"]
            compliant = delivery_pass and demo_pass and view_pass

            # Penalty (only for delivery shortfall)
            penalty = 0.0
            if not delivery_pass:
                shortfall = max(0, guaranteed - total_delivered)
                shortfall_pct = shortfall / guaranteed * 100 if guaranteed > 0 else 0.0
                multiplier = self._get_penalty_multiplier(shortfall_pct, penalty_schedule)
                penalty = round(multiplier * shortfall * contract["cpm_rate"] / 1000, 2)

            ground_truth[ref] = {
                "order_ref": ref,
                "advertiser_name": contract["advertiser_name"],
                "compliance_status": "COMPLIANT" if compliant else "NON-COMPLIANT",
                "guaranteed_impressions": guaranteed,
                "delivered_impressions": total_delivered,
                "delivery_rate": round(delivery_rate, 4),
                "delivery_status": "PASS" if delivery_pass else "FAIL",
                "demographic_rate": round(demo_rate, 4),
                "demographic_threshold": contract["demographic_threshold"],
                "demographic_status": "PASS" if demo_pass else "FAIL",
                "viewability_rate": round(view_rate, 4),
                "viewability_threshold": contract["viewability_threshold"],
                "viewability_status": "PASS" if view_pass else "FAIL",
                "penalty_amount": penalty,
            }

        conn.close()
        return ground_truth

    # ── Evaluation ──────────────────────────────────────────────────

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
        n_orders = len(ground_truth)
        criteria = {}

        # ── 1. Certificate file exists and is valid JSON (10 pts) ───
        cert_path = os.path.join(self.workspace, "compliance_certificate.json")
        cert = None
        try:
            with open(cert_path) as f:
                cert = json.load(f)
            required_keys = {
                "certificate_date", "total_orders_evaluated",
                "compliant_count", "non_compliant_count",
                "total_penalty_amount", "orders",
            }
            if required_keys.issubset(set(cert.keys())):
                criteria["certificate_valid"] = {
                    "passed": True, "score": 10, "max_score": 10,
                }
            else:
                missing = required_keys - set(cert.keys())
                criteria["certificate_valid"] = {
                    "passed": False, "score": 5, "max_score": 10,
                    "reason": f"Missing keys: {missing}",
                }
        except FileNotFoundError:
            criteria["certificate_valid"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "compliance_certificate.json not found",
            }
        except (json.JSONDecodeError, Exception) as e:
            criteria["certificate_valid"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": f"Invalid JSON: {e}",
            }

        # Build lookup from agent's certificate
        agent_orders = {}
        if cert and "orders" in cert:
            for o in cert["orders"]:
                ref = o.get("order_ref", "")
                if ref:
                    agent_orders[ref] = o

        # ── 2. All orders present (10 pts) ──────────────────────────
        gt_refs = set(ground_truth.keys())
        agent_refs = set(agent_orders.keys())
        if gt_refs == agent_refs:
            criteria["orders_present"] = {
                "passed": True, "score": 10, "max_score": 10,
            }
        else:
            missing = gt_refs - agent_refs
            extra = agent_refs - gt_refs
            frac = len(gt_refs & agent_refs) / max(1, len(gt_refs))
            criteria["orders_present"] = {
                "passed": False,
                "score": round(10 * frac),
                "max_score": 10,
                "reason": f"Missing: {missing or 'none'}, Extra: {extra or 'none'}",
            }

        # Helper for numeric comparison
        def close(a, b, tol):
            try:
                return abs(float(a) - float(b)) <= tol
            except (TypeError, ValueError):
                return False

        common_refs = sorted(gt_refs & agent_refs)

        # ── 3. Delivery metrics (20 pts) ────────────────────────────
        delivery_ok = 0
        for ref in common_refs:
            gt = ground_truth[ref]
            ag = agent_orders[ref]
            if (close(ag.get("delivered_impressions", -1),
                      gt["delivered_impressions"], 1)
                and close(ag.get("delivery_rate", -1),
                          gt["delivery_rate"], 0.001)
                and ag.get("delivery_status") == gt["delivery_status"]):
                delivery_ok += 1
        if n_orders > 0:
            score = round(20 * delivery_ok / n_orders)
        else:
            score = 0
        criteria["delivery_metrics"] = {
            "passed": delivery_ok == n_orders,
            "score": score,
            "max_score": 20,
            "reason": f"{delivery_ok}/{n_orders} orders correct"
            if delivery_ok != n_orders else "",
        }

        # ── 4. Demographic metrics (15 pts) ─────────────────────────
        demo_ok = 0
        for ref in common_refs:
            gt = ground_truth[ref]
            ag = agent_orders[ref]
            if (close(ag.get("demographic_rate", -1),
                      gt["demographic_rate"], 0.001)
                and ag.get("demographic_status") == gt["demographic_status"]):
                demo_ok += 1
        if n_orders > 0:
            score = round(15 * demo_ok / n_orders)
        else:
            score = 0
        criteria["demographic_metrics"] = {
            "passed": demo_ok == n_orders,
            "score": score,
            "max_score": 15,
            "reason": f"{demo_ok}/{n_orders} orders correct"
            if demo_ok != n_orders else "",
        }

        # ── 5. Viewability metrics (15 pts) ─────────────────────────
        view_ok = 0
        for ref in common_refs:
            gt = ground_truth[ref]
            ag = agent_orders[ref]
            if (close(ag.get("viewability_rate", -1),
                      gt["viewability_rate"], 0.001)
                and ag.get("viewability_status") == gt["viewability_status"]):
                view_ok += 1
        if n_orders > 0:
            score = round(15 * view_ok / n_orders)
        else:
            score = 0
        criteria["viewability_metrics"] = {
            "passed": view_ok == n_orders,
            "score": score,
            "max_score": 15,
            "reason": f"{view_ok}/{n_orders} orders correct"
            if view_ok != n_orders else "",
        }

        # ── 6. Compliance status (10 pts) ───────────────────────────
        status_ok = 0
        for ref in common_refs:
            gt = ground_truth[ref]
            ag = agent_orders[ref]
            if ag.get("compliance_status") == gt["compliance_status"]:
                status_ok += 1
        if n_orders > 0:
            score = round(10 * status_ok / n_orders)
        else:
            score = 0
        criteria["compliance_status"] = {
            "passed": status_ok == n_orders,
            "score": score,
            "max_score": 10,
            "reason": f"{status_ok}/{n_orders} orders correct"
            if status_ok != n_orders else "",
        }

        # ── 7. Penalty amounts (10 pts) ─────────────────────────────
        penalty_ok = 0
        for ref in common_refs:
            gt = ground_truth[ref]
            ag = agent_orders[ref]
            if close(ag.get("penalty_amount", -1), gt["penalty_amount"], 0.10):
                penalty_ok += 1
        if n_orders > 0:
            score = round(10 * penalty_ok / n_orders)
        else:
            score = 0
        criteria["penalty_amounts"] = {
            "passed": penalty_ok == n_orders,
            "score": score,
            "max_score": 10,
            "reason": f"{penalty_ok}/{n_orders} orders correct"
            if penalty_ok != n_orders else "",
        }

        # ── 8. Shortfall report CSV (10 pts) ────────────────────────
        report_path = os.path.join(self.workspace, "shortfall_report.csv")
        gt_non_compliant = {
            ref: gt for ref, gt in ground_truth.items()
            if gt["compliance_status"] == "NON-COMPLIANT"
        }
        try:
            with open(report_path) as f:
                reader = csv.DictReader(f)
                report_rows = {row["order_ref"]: row for row in reader}

            expected_refs = set(gt_non_compliant.keys())
            actual_refs = set(report_rows.keys())
            if expected_refs == actual_refs:
                # Check failed_checks column
                checks_ok = 0
                for ref in expected_refs:
                    gt = ground_truth[ref]
                    expected_checks = []
                    if gt["delivery_status"] == "FAIL":
                        expected_checks.append("delivery")
                    if gt["demographic_status"] == "FAIL":
                        expected_checks.append("demographic")
                    if gt["viewability_status"] == "FAIL":
                        expected_checks.append("viewability")
                    agent_checks = sorted(
                        [c.strip() for c in report_rows[ref].get("failed_checks", "").split(";")]
                    )
                    if sorted(expected_checks) == agent_checks:
                        checks_ok += 1

                if checks_ok == len(expected_refs):
                    criteria["shortfall_report"] = {
                        "passed": True, "score": 10, "max_score": 10,
                    }
                else:
                    criteria["shortfall_report"] = {
                        "passed": False, "score": 6, "max_score": 10,
                        "reason": f"failed_checks correct for {checks_ok}/{len(expected_refs)} orders",
                    }
            else:
                missing = expected_refs - actual_refs
                extra = actual_refs - expected_refs
                frac = len(expected_refs & actual_refs) / max(1, len(expected_refs))
                criteria["shortfall_report"] = {
                    "passed": False,
                    "score": max(2, round(10 * frac)),
                    "max_score": 10,
                    "reason": f"Missing: {missing or 'none'}, Extra: {extra or 'none'}",
                }
        except FileNotFoundError:
            criteria["shortfall_report"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "shortfall_report.csv not found",
            }
        except Exception as e:
            criteria["shortfall_report"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": f"Error reading report: {e}",
            }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ── Verification ────────────────────────────────────────────────

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
        cfg_dir = os.path.join(self.workspace, "config")

        # Read config files
        thresholds = self._parse_simple_yaml(
            os.path.join(cfg_dir, "compliance_thresholds.yaml")
        )
        base_tolerance = thresholds.get("delivery_tolerance_pct", 2.0)

        penalty_schedule = self._read_penalty_schedule(
            os.path.join(cfg_dir, "penalty_schedule.csv")
        )

        with open(os.path.join(cfg_dir, "viewability_benchmarks.json")) as f:
            benchmarks = json.load(f)

        seg_mapping = self._read_seg_mapping(
            os.path.join(cfg_dir, "demographic_mapping.csv")
        )

        tier_adj = self._read_tier_adjustments(
            os.path.join(cfg_dir, "tier_adjustments.txt")
        )

        # Read all contract files
        contracts_dir = os.path.join(self.workspace, "contracts")
        contracts = {}
        for fname in sorted(os.listdir(contracts_dir)):
            if fname.endswith(".json"):
                with open(os.path.join(contracts_dir, fname)) as f:
                    c = json.load(f)
                    contracts[c["order_ref"]] = c

        tool_call_count = 0
        results = []

        for ref in sorted(contracts.keys()):
            contract = contracts[ref]

            # 1. Lookup order
            order_info = self.tools["lookup_order"](order_ref=ref)
            tool_call_count += 1
            order_id = order_info["order_id"]

            # 2. Get campaigns
            campaigns = self.tools["get_order_campaigns"](order_id=order_id)
            tool_call_count += 1

            # Map target segment codes to IDs
            target_seg_ids = set()
            for code in contract["target_segments"]:
                sid = seg_mapping.get(code)
                if sid is not None:
                    target_seg_ids.add(sid)

            total_delivered = 0
            total_target_imp = 0
            total_all_imp = 0
            view_measured = 0
            view_viewable = 0

            for camp in campaigns:
                cid = camp["campaign_id"]
                ad_format = camp["ad_format"]

                # 3. Impressions
                imp_data = self.tools["get_campaign_impressions"](campaign_id=cid)
                tool_call_count += 1
                total_delivered += imp_data["total_impressions"]

                # 4. Demographic breakdown
                demo_data = self.tools["get_campaign_demographic_breakdown"](
                    campaign_id=cid
                )
                tool_call_count += 1
                camp_all = sum(d["impressions"] for d in demo_data)
                camp_target = sum(
                    d["impressions"] for d in demo_data
                    if d["segment_id"] in target_seg_ids
                )
                total_target_imp += camp_target
                total_all_imp += camp_all

                # 5. Viewability
                view_data = self.tools["get_campaign_viewability"](campaign_id=cid)
                tool_call_count += 1
                camp_measured = view_data["total_measured"]
                camp_viewable = view_data["total_viewable"]
                min_sample = benchmarks.get(ad_format, {}).get(
                    "min_measurement_sample", 0
                )
                if camp_measured >= min_sample:
                    view_measured += camp_measured
                    view_viewable += camp_viewable

            guaranteed = contract["guaranteed_impressions"]
            delivery_rate = total_delivered / guaranteed if guaranteed > 0 else 0.0
            demo_rate = total_target_imp / total_all_imp if total_all_imp > 0 else 0.0
            view_rate = view_viewable / view_measured if view_measured > 0 else 1.0

            tier = contract.get("advertiser_tier", "Bronze")
            effective_tolerance = base_tolerance + tier_adj.get(tier, 0.0)

            delivery_pass = delivery_rate >= (1 - effective_tolerance / 100)
            demo_pass = demo_rate >= contract["demographic_threshold"]
            view_pass = view_rate >= contract["viewability_threshold"]
            compliant = delivery_pass and demo_pass and view_pass

            penalty = 0.0
            if not delivery_pass:
                shortfall = max(0, guaranteed - total_delivered)
                shortfall_pct = shortfall / guaranteed * 100 if guaranteed > 0 else 0.0
                multiplier = self._get_penalty_multiplier(
                    shortfall_pct, penalty_schedule
                )
                penalty = round(
                    multiplier * shortfall * contract["cpm_rate"] / 1000, 2
                )

            results.append({
                "order_ref": ref,
                "advertiser_name": contract["advertiser_name"],
                "compliance_status": "COMPLIANT" if compliant else "NON-COMPLIANT",
                "guaranteed_impressions": guaranteed,
                "delivered_impressions": total_delivered,
                "delivery_rate": round(delivery_rate, 4),
                "delivery_status": "PASS" if delivery_pass else "FAIL",
                "demographic_rate": round(demo_rate, 4),
                "demographic_threshold": contract["demographic_threshold"],
                "demographic_status": "PASS" if demo_pass else "FAIL",
                "viewability_rate": round(view_rate, 4),
                "viewability_threshold": contract["viewability_threshold"],
                "viewability_status": "PASS" if view_pass else "FAIL",
                "penalty_amount": penalty,
            })

        # Build certificate
        compliant_count = sum(1 for r in results if r["compliance_status"] == "COMPLIANT")
        non_compliant_count = len(results) - compliant_count
        total_penalty = round(sum(r["penalty_amount"] for r in results), 2)

        certificate = {
            "certificate_date": "2026-04-20",
            "total_orders_evaluated": len(results),
            "compliant_count": compliant_count,
            "non_compliant_count": non_compliant_count,
            "total_penalty_amount": total_penalty,
            "orders": results,
        }

        with open(os.path.join(self.workspace, "compliance_certificate.json"), "w") as f:
            json.dump(certificate, f, indent=2)

        # Build shortfall report
        non_compliant = [r for r in results if r["compliance_status"] == "NON-COMPLIANT"]
        report_path = os.path.join(self.workspace, "shortfall_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "order_ref", "advertiser_name", "failed_checks",
                "guaranteed_impressions", "delivered_impressions",
                "delivery_rate", "demographic_rate", "viewability_rate",
                "penalty_amount",
            ])
            for r in non_compliant:
                failed = []
                if r["delivery_status"] == "FAIL":
                    failed.append("delivery")
                if r["demographic_status"] == "FAIL":
                    failed.append("demographic")
                if r["viewability_status"] == "FAIL":
                    failed.append("viewability")
                writer.writerow([
                    r["order_ref"],
                    r["advertiser_name"],
                    ";".join(failed),
                    r["guaranteed_impressions"],
                    r["delivered_impressions"],
                    f"{r['delivery_rate']:.4f}",
                    f"{r['demographic_rate']:.4f}",
                    f"{r['viewability_rate']:.4f}",
                    f"{r['penalty_amount']:.2f}",
                ])

        # Action string
        action = (
            f"Compliance reconciliation complete. "
            f"Total orders evaluated: {len(results)}. "
            f"Compliant: {compliant_count}. "
            f"Non-compliant: {non_compliant_count}. "
            f"Total penalty amount: ${total_penalty:.2f} USD."
        )

        assert tool_call_count >= 15, (
            f"Tool call count {tool_call_count} < 15"
        )

        return self.step(action)
