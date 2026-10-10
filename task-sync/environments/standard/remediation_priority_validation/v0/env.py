"""
Environment for post-breach remediation prioritization task.
Provides tools to query vulnerability data and evaluates the agent's remediation plan.
"""

import sqlite3
import os
import json
import csv
import yaml
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

    # ── Tool Methods ─────────────────────────────────────────────────────

    @tool(
        description=(
            "Retrieves paginated vulnerability scan results. Each result shows "
            "a detected vulnerability on a specific asset, including the asset's "
            "hostname, network zone, CVE identifier, CVSS score, scan date, and "
            "detected port. Returns up to 20 results per page along with total "
            "count and total pages."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
            },
            "required": ["page"],
        },
    )
    def get_scan_results(self, page: int) -> dict:
        page_size = 20
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT COUNT(*) as cnt FROM scan_results")
        total = c.fetchone()["cnt"]
        total_pages = max(1, math.ceil(total / page_size))

        offset = (max(1, page) - 1) * page_size
        c.execute(
            """
            SELECT s.scan_id, s.asset_id, a.hostname, a.network_zone,
                   s.cve_id, v.cvss_score, s.scan_date, s.port
            FROM scan_results s
            JOIN assets a ON s.asset_id = a.asset_id
            JOIN vulnerabilities v ON s.cve_id = v.cve_id
            ORDER BY s.scan_id
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()

        return {
            "page": page,
            "total_pages": total_pages,
            "total_results": total,
            "results": rows,
        }

    @tool(
        description=(
            "Retrieves detailed information about a specific CVE, including "
            "its description, CVSS score, affected software, vulnerability type, "
            "publication date, and CVSS vector string."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cve_id": {
                    "type": "string",
                    "description": "The CVE identifier (e.g. 'CVE-2024-10005').",
                },
            },
            "required": ["cve_id"],
        },
    )
    def get_vulnerability_details(self, cve_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM vulnerabilities WHERE cve_id = ?", (cve_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"CVE {cve_id} not found"}
        return dict(row)

    @tool(
        description=(
            "Checks threat intelligence for a specific CVE. Returns whether the "
            "CVE is actively exploited in the wild, its exploit maturity level, "
            "the associated threat actor, last seen date, and any linked campaign "
            "name. Returns a 'no_data' status if no threat intelligence exists "
            "for the given CVE."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cve_id": {
                    "type": "string",
                    "description": "The CVE identifier to check.",
                },
            },
            "required": ["cve_id"],
        },
    )
    def check_threat_intel(self, cve_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM threat_intel WHERE cve_id = ? ORDER BY intel_id LIMIT 1",
            (cve_id,),
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"cve_id": cve_id, "status": "no_data"}
        result = dict(row)
        result["actively_exploited"] = bool(result["actively_exploited"])
        return result

    @tool(
        description=(
            "Retrieves all patch deployment records for a specific asset. Each "
            "record includes the CVE it addresses, the patch identifier, current "
            "deployment status (deployed, pending, failed, scheduled, or "
            "not_available), and the deployment date if applicable."
        ),
        parameters={
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "The asset identifier (e.g. 'ASSET-1005').",
                },
            },
            "required": ["asset_id"],
        },
    )
    def get_asset_patch_status(self, asset_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM patch_deployments WHERE asset_id = ? ORDER BY deployment_id",
            (asset_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"asset_id": asset_id, "patch_records": rows}

    # ── Evaluation ───────────────────────────────────────────────────────

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the ground-truth remediation plan from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Load scan results with asset/vuln info
        c.execute(
            """
            SELECT s.scan_id, s.asset_id, a.hostname, a.network_zone,
                   s.cve_id, v.cvss_score
            FROM scan_results s
            JOIN assets a ON s.asset_id = a.asset_id
            JOIN vulnerabilities v ON s.cve_id = v.cve_id
            """
        )
        scans = [dict(r) for r in c.fetchall()]

        # Load patch deployments
        c.execute("SELECT asset_id, cve_id, status FROM patch_deployments")
        patches = {}
        for r in c.fetchall():
            key = (r["asset_id"], r["cve_id"])
            # If multiple records exist for same pair, 'deployed' wins
            if key not in patches or r["status"] == "deployed":
                patches[key] = r["status"]

        # Load threat intel (first record per CVE)
        c.execute(
            """
            SELECT cve_id, actively_exploited, exploit_maturity
            FROM threat_intel
            ORDER BY intel_id
            """
        )
        threat_map = {}
        for r in c.fetchall():
            cid = r["cve_id"]
            if cid not in threat_map:
                threat_map[cid] = {
                    "actively_exploited": bool(r["actively_exploited"]),
                    "exploit_maturity": r["exploit_maturity"],
                }

        conn.close()

        # Load workspace configs
        with open(os.path.join(self.workspace, "remediation_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "network_zone_config.json")) as f:
            zone_cfg = json.load(f)

        # Load asset criticality from all batch CSVs
        crit_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("asset_criticality_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        crit_map[row["asset_id"]] = int(row["criticality_score"])

        crit_multipliers = {int(k): v for k, v in policy["criticality_multipliers"].items()}
        threat_multipliers = policy["threat_multipliers"]
        zone_multipliers = zone_cfg["zone_multipliers"]
        tiers = policy["priority_tiers"]
        exclude_statuses = set(policy["exclusion_rules"]["exclude_patch_status"])

        # Build remediation items
        items = []
        for scan in scans:
            aid = scan["asset_id"]
            cid = scan["cve_id"]
            pair_key = (aid, cid)

            # Filter: skip deployed patches
            patch_status = patches.get(pair_key)
            if patch_status in exclude_statuses:
                continue

            cvss = scan["cvss_score"]
            hostname = scan["hostname"]
            zone = scan["network_zone"]

            # Criticality multiplier
            crit_score = crit_map.get(aid, 1)
            crit_mult = crit_multipliers.get(crit_score, 1.0)

            # Threat multiplier
            ti = threat_map.get(cid)
            if ti is None:
                threat_mult = threat_multipliers["no_intel"]
            else:
                ae = ti["actively_exploited"]
                em = ti["exploit_maturity"]
                if ae:
                    key = f"actively_exploited_{em}"
                else:
                    key = f"not_exploited_{em}"
                threat_mult = threat_multipliers.get(key, 1.0)

            # Zone multiplier
            zone_mult = zone_multipliers.get(zone, 1.0)

            # Priority score
            priority_score = round(cvss * crit_mult * threat_mult * zone_mult, 2)

            # Determine tier
            tier = "P4"
            action = tiers["P4"]["action"]
            sla = tiers["P4"]["sla_hours"]
            for t_name in ["P1", "P2", "P3", "P4"]:
                if priority_score >= tiers[t_name]["min_score"]:
                    tier = t_name
                    action = tiers[t_name]["action"]
                    sla = tiers[t_name]["sla_hours"]
                    break

            items.append({
                "asset_id": aid,
                "hostname": hostname,
                "cve_id": cid,
                "cvss_score": cvss,
                "criticality_score": crit_score,
                "criticality_multiplier": crit_mult,
                "threat_multiplier": threat_mult,
                "zone_multiplier": zone_mult,
                "priority_score": priority_score,
                "priority_tier": tier,
                "recommended_action": action,
                "sla_hours": sla,
            })

        # Sort: priority_score desc, cvss_score desc, asset_id asc
        items.sort(key=lambda x: (-x["priority_score"], -x["cvss_score"], x["asset_id"]))

        # Add rank
        for i, item in enumerate(items):
            item["priority_rank"] = i + 1

        return items

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
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: CSV exists with correct columns (10 pts) ────────
        c1_max = 10
        max_score += c1_max
        csv_path = os.path.join(self.workspace, "remediation_plan.csv")
        expected_cols = [
            "priority_rank", "asset_id", "hostname", "cve_id", "cvss_score",
            "criticality_score", "criticality_multiplier", "threat_multiplier",
            "zone_multiplier", "priority_score", "priority_tier",
            "recommended_action", "sla_hours",
        ]

        csv_rows = []
        csv_ok = False
        csv_reason = ""
        if not os.path.exists(csv_path):
            csv_reason = "remediation_plan.csv not found"
        else:
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    csv_reason = "CSV has no header"
                else:
                    actual_cols = [c.strip() for c in reader.fieldnames]
                    if actual_cols != expected_cols:
                        csv_reason = f"Column mismatch: expected {expected_cols}, got {actual_cols}"
                    else:
                        csv_rows = [row for row in reader]
                        csv_ok = True

        c1_score = c1_max if csv_ok else 0
        total_score += c1_score
        eval_criteria["csv_structure"] = {
            "passed": csv_ok,
            "score": c1_score,
            "max_score": c1_max,
            "reason": csv_reason if not csv_ok else "",
        }

        # ── Criterion 2: Correct number of rows (15 pts) ────────────────
        c2_max = 15
        max_score += c2_max
        expected_count = len(ground_truth)
        actual_count = len(csv_rows)
        c2_ok = csv_ok and actual_count == expected_count
        c2_score = c2_max if c2_ok else 0
        total_score += c2_score
        eval_criteria["row_count"] = {
            "passed": c2_ok,
            "score": c2_score,
            "max_score": c2_max,
            "reason": "" if c2_ok else f"Expected {expected_count} rows, got {actual_count}",
        }

        # ── Criterion 3: Priority scores correct (25 pts) ───────────────
        c3_max = 25
        max_score += c3_max
        c3_score = 0
        c3_reason = ""
        if csv_ok and csv_rows:
            gt_map = {(g["asset_id"], g["cve_id"]): g for g in ground_truth}
            correct = 0
            total_items = len(ground_truth)
            for row in csv_rows:
                key = (row.get("asset_id", "").strip(), row.get("cve_id", "").strip())
                gt = gt_map.get(key)
                if gt is None:
                    continue
                try:
                    agent_score = round(float(row.get("priority_score", "0")), 2)
                    if abs(agent_score - gt["priority_score"]) < 0.011:
                        # Also check multipliers
                        cm = round(float(row.get("criticality_multiplier", "0")), 1)
                        tm = round(float(row.get("threat_multiplier", "0")), 1)
                        zm = round(float(row.get("zone_multiplier", "0")), 1)
                        if (abs(cm - gt["criticality_multiplier"]) < 0.011 and
                                abs(tm - gt["threat_multiplier"]) < 0.011 and
                                abs(zm - gt["zone_multiplier"]) < 0.011):
                            correct += 1
                except (ValueError, TypeError):
                    pass

            fraction = correct / total_items if total_items > 0 else 0
            c3_score = round(c3_max * fraction)
            if fraction < 1.0:
                c3_reason = f"{correct}/{total_items} items have correct priority scores and multipliers"
        else:
            c3_reason = "CSV not loaded"

        total_score += c3_score
        eval_criteria["priority_scores"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": c3_reason if c3_score < c3_max else "",
        }

        # ── Criterion 4: Correct sorting / ranking (15 pts) ─────────────
        c4_max = 15
        max_score += c4_max
        c4_ok = False
        c4_reason = ""
        if csv_ok and csv_rows and len(csv_rows) == expected_count:
            ranking_correct = True
            for i, (gt_item, csv_row) in enumerate(zip(ground_truth, csv_rows)):
                csv_aid = csv_row.get("asset_id", "").strip()
                csv_cid = csv_row.get("cve_id", "").strip()
                if csv_aid != gt_item["asset_id"] or csv_cid != gt_item["cve_id"]:
                    ranking_correct = False
                    c4_reason = (
                        f"Row {i+1}: expected ({gt_item['asset_id']}, {gt_item['cve_id']}), "
                        f"got ({csv_aid}, {csv_cid})"
                    )
                    break
                try:
                    csv_rank = int(csv_row.get("priority_rank", "0"))
                    if csv_rank != gt_item["priority_rank"]:
                        ranking_correct = False
                        c4_reason = f"Row {i+1}: expected rank {gt_item['priority_rank']}, got {csv_rank}"
                        break
                except ValueError:
                    ranking_correct = False
                    c4_reason = f"Row {i+1}: invalid rank value"
                    break
            c4_ok = ranking_correct
        else:
            c4_reason = "Row count mismatch or CSV not loaded"

        c4_score = c4_max if c4_ok else 0
        total_score += c4_score
        eval_criteria["sorting_ranking"] = {
            "passed": c4_ok,
            "score": c4_score,
            "max_score": c4_max,
            "reason": c4_reason if not c4_ok else "",
        }

        # ── Criterion 5: Correct tier/action/SLA assignments (15 pts) ───
        c5_max = 15
        max_score += c5_max
        c5_score = 0
        c5_reason = ""
        if csv_ok and csv_rows:
            gt_map = {(g["asset_id"], g["cve_id"]): g for g in ground_truth}
            correct = 0
            total_items = len(ground_truth)
            for row in csv_rows:
                key = (row.get("asset_id", "").strip(), row.get("cve_id", "").strip())
                gt = gt_map.get(key)
                if gt is None:
                    continue
                tier_ok = row.get("priority_tier", "").strip() == gt["priority_tier"]
                action_ok = row.get("recommended_action", "").strip() == gt["recommended_action"]
                try:
                    sla_ok = int(row.get("sla_hours", "0")) == gt["sla_hours"]
                except ValueError:
                    sla_ok = False
                if tier_ok and action_ok and sla_ok:
                    correct += 1

            fraction = correct / total_items if total_items > 0 else 0
            c5_score = round(c5_max * fraction)
            if fraction < 1.0:
                c5_reason = f"{correct}/{total_items} items have correct tier/action/SLA"
        else:
            c5_reason = "CSV not loaded"

        total_score += c5_score
        eval_criteria["tier_action_sla"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": c5_reason if c5_score < c5_max else "",
        }

        # ── Criterion 6: Action string summary (20 pts) ─────────────────
        c6_max = 20
        max_score += c6_max
        c6_score = 0
        c6_reason = ""

        if action and ground_truth:
            # Compute expected summary
            tier_counts = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
            for item in ground_truth:
                tier_counts[item["priority_tier"]] += 1

            expected_total = len(ground_truth)
            sub_points = 0

            # Check total count (5 pts)
            if f"Total items: {expected_total}" in action:
                sub_points += 5

            # Check tier breakdown (5 pts)
            tier_str = f"P1: {tier_counts['P1']}, P2: {tier_counts['P2']}, P3: {tier_counts['P3']}, P4: {tier_counts['P4']}"
            if tier_str in action:
                sub_points += 5

            # Check top 5 items listed (10 pts, 2 each)
            top5 = ground_truth[:5]
            top5_correct = 0
            for item in top5:
                expected_line = (
                    f"{item['priority_rank']}. {item['asset_id']} | "
                    f"{item['cve_id']} | {item['priority_score']:.2f} | "
                    f"{item['priority_tier']} | {item['recommended_action']}"
                )
                if expected_line in action:
                    top5_correct += 1
            sub_points += top5_correct * 2

            c6_score = sub_points
            missing = []
            if sub_points < 5:
                missing.append("total count")
            if sub_points < 10:
                missing.append("tier breakdown")
            if top5_correct < 5:
                missing.append(f"top-5 items ({top5_correct}/5)")
            if missing:
                c6_reason = f"Missing or incorrect: {', '.join(missing)}"
        else:
            c6_reason = "Empty action or no ground truth"

        total_score += c6_score
        eval_criteria["action_summary"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": c6_reason if c6_score < c6_max else "",
        }

        # ── Final ────────────────────────────────────────────────────────
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

        This method proves end-to-end solvability. It must:
          - Use self.tools[name](**params) to gather data (no direct DB queries).
          - Read files from self.workspace as needed.
          - Write all required deliverables to self.workspace.
          - Construct the final action string.
          - Return self.step(action).
        """
        import csv as csv_mod

        tool_call_count = 0

        # ── Step 1: Load workspace configuration files ───────────────────
        with open(os.path.join(self.workspace, "remediation_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "network_zone_config.json")) as f:
            zone_cfg = json.load(f)

        # ── Step 2: Load asset criticality from workspace CSVs ───────────
        crit_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("asset_criticality_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv_mod.DictReader(f)
                    for row in reader:
                        crit_map[row["asset_id"]] = int(row["criticality_score"])

        # ── Step 3: Gather all scan results via paginated tool ───────────
        all_scans = []
        result = self.tools["get_scan_results"](page=1)
        tool_call_count += 1
        all_scans.extend(result["results"])
        total_pages = result["total_pages"]

        for p in range(2, total_pages + 1):
            result = self.tools["get_scan_results"](page=p)
            tool_call_count += 1
            all_scans.extend(result["results"])

        # ── Step 4: Get unique CVEs and check threat intel ───────────────
        unique_cves = set(s["cve_id"] for s in all_scans)
        threat_intel_map = {}
        for cve_id in sorted(unique_cves):
            ti = self.tools["check_threat_intel"](cve_id=cve_id)
            tool_call_count += 1
            if ti.get("status") != "no_data":
                threat_intel_map[cve_id] = {
                    "actively_exploited": ti["actively_exploited"],
                    "exploit_maturity": ti["exploit_maturity"],
                }

        # ── Step 5: Get patch status for each unique asset ───────────────
        unique_assets = set(s["asset_id"] for s in all_scans)
        patch_map = {}  # (asset_id, cve_id) -> status
        for asset_id in sorted(unique_assets):
            ps = self.tools["get_asset_patch_status"](asset_id=asset_id)
            tool_call_count += 1
            for rec in ps["patch_records"]:
                key = (rec["asset_id"], rec["cve_id"])
                # deployed status takes priority if multiple records
                if key not in patch_map or rec["status"] == "deployed":
                    patch_map[key] = rec["status"]

        # ── Step 6: Also fetch vulnerability details for a few CVEs ──────
        # (ensures we exercise get_vulnerability_details tool)
        sample_cves = sorted(unique_cves)[:3]
        for cve_id in sample_cves:
            self.tools["get_vulnerability_details"](cve_id=cve_id)
            tool_call_count += 1

        # ── Step 7: Compute priority scores ──────────────────────────────
        crit_multipliers = {int(k): v for k, v in policy["criticality_multipliers"].items()}
        threat_multipliers = policy["threat_multipliers"]
        zone_multipliers = zone_cfg["zone_multipliers"]
        tiers_cfg = policy["priority_tiers"]
        exclude_statuses = set(policy["exclusion_rules"]["exclude_patch_status"])

        items = []
        for scan in all_scans:
            aid = scan["asset_id"]
            cid = scan["cve_id"]
            pair_key = (aid, cid)

            # Filter out deployed patches
            ps = patch_map.get(pair_key)
            if ps in exclude_statuses:
                continue

            cvss = scan["cvss_score"]
            hostname = scan["hostname"]
            zone = scan["network_zone"]

            # Criticality
            crit_score = crit_map.get(aid, 1)
            crit_mult = crit_multipliers.get(crit_score, 1.0)

            # Threat
            ti = threat_intel_map.get(cid)
            if ti is None:
                threat_mult = threat_multipliers["no_intel"]
            else:
                ae = ti["actively_exploited"]
                em = ti["exploit_maturity"]
                key = f"actively_exploited_{em}" if ae else f"not_exploited_{em}"
                threat_mult = threat_multipliers.get(key, 1.0)

            # Zone
            zone_mult = zone_multipliers.get(zone, 1.0)

            # Score
            priority_score = round(cvss * crit_mult * threat_mult * zone_mult, 2)

            # Tier
            tier = "P4"
            rec_action = tiers_cfg["P4"]["action"]
            sla = tiers_cfg["P4"]["sla_hours"]
            for t_name in ["P1", "P2", "P3", "P4"]:
                if priority_score >= tiers_cfg[t_name]["min_score"]:
                    tier = t_name
                    rec_action = tiers_cfg[t_name]["action"]
                    sla = tiers_cfg[t_name]["sla_hours"]
                    break

            items.append({
                "priority_rank": 0,
                "asset_id": aid,
                "hostname": hostname,
                "cve_id": cid,
                "cvss_score": cvss,
                "criticality_score": crit_score,
                "criticality_multiplier": crit_mult,
                "threat_multiplier": threat_mult,
                "zone_multiplier": zone_mult,
                "priority_score": priority_score,
                "priority_tier": tier,
                "recommended_action": rec_action,
                "sla_hours": sla,
            })

        # Sort
        items.sort(key=lambda x: (-x["priority_score"], -x["cvss_score"], x["asset_id"]))
        for i, item in enumerate(items):
            item["priority_rank"] = i + 1

        # ── Step 8: Write remediation_plan.csv ───────────────────────────
        csv_path = os.path.join(self.workspace, "remediation_plan.csv")
        fieldnames = [
            "priority_rank", "asset_id", "hostname", "cve_id", "cvss_score",
            "criticality_score", "criticality_multiplier", "threat_multiplier",
            "zone_multiplier", "priority_score", "priority_tier",
            "recommended_action", "sla_hours",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in items:
                row = dict(item)
                row["priority_score"] = f"{item['priority_score']:.2f}"
                writer.writerow(row)

        # ── Step 9: Construct action string ──────────────────────────────
        tier_counts = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
        for item in items:
            tier_counts[item["priority_tier"]] += 1

        lines = ["REMEDIATION SUMMARY"]
        lines.append(f"Total items: {len(items)}")
        lines.append(
            f"P1: {tier_counts['P1']}, P2: {tier_counts['P2']}, "
            f"P3: {tier_counts['P3']}, P4: {tier_counts['P4']}"
        )
        lines.append("")
        for item in items:
            lines.append(
                f"{item['priority_rank']}. {item['asset_id']} | "
                f"{item['cve_id']} | {item['priority_score']:.2f} | "
                f"{item['priority_tier']} | {item['recommended_action']}"
            )

        action_str = "\n".join(lines)

        assert tool_call_count >= 15, (
            f"Only {tool_call_count} tool calls made; need at least 15"
        )

        return self.step(action_str)
