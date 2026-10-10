"""
Environment for Fraudulent International Call Traffic Detection task.
"""

import csv
import json
import os
import sqlite3
import glob as glob_module
from typing import Tuple, Dict, List, Any

import yaml


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

    # ═══════════════════════════════════════════════════════════════════════
    # Tool Methods
    # ═══════════════════════════════════════════════════════════════════════

    @tool(
        description="List interconnect routes with optional status filter. Returns paginated results with 20 routes per page. Each route includes route_id, carrier_name, origin_country, destination_region, capacity, cost, and status.",
        parameters={
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "enum": ["active", "inactive", "maintenance", "all"],
                    "description": "Filter routes by status. Use 'all' to list every route."
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1."
                }
            },
            "required": ["status_filter", "page"]
        }
    )
    def list_routes(self, status_filter: str, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if status_filter == "all":
            rows = conn.execute("SELECT * FROM routes ORDER BY route_id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM routes WHERE status = ? ORDER BY route_id",
                (status_filter,)
            ).fetchall()
        conn.close()

        page_size = 20
        total = len(rows)
        total_pages = max(1, (total + page_size - 1) // page_size)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = rows[start:end]

        return {
            "page": page,
            "total_pages": total_pages,
            "total_routes": total,
            "routes": [dict(r) for r in page_rows],
        }

    @tool(
        description="Retrieve historical traffic baseline statistics for a specific route and destination country combination. Returns baseline data for all available hours of the day, including average calls per hour and standard deviation.",
        parameters={
            "type": "object",
            "properties": {
                "route_id": {
                    "type": "string",
                    "description": "The route identifier, e.g. 'RT-0001'."
                },
                "destination_country": {
                    "type": "string",
                    "description": "ISO alpha-2 country code of the destination, e.g. 'NG'."
                }
            },
            "required": ["route_id", "destination_country"]
        }
    )
    def get_historical_baseline(self, route_id: str, destination_country: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT hour_of_day, avg_calls_per_hour, std_dev_calls "
            "FROM historical_baselines "
            "WHERE route_id = ? AND destination_country = ? "
            "ORDER BY hour_of_day",
            (route_id, destination_country)
        ).fetchall()
        conn.close()

        if not rows:
            return {"found": False, "route_id": route_id,
                    "destination_country": destination_country, "baselines": []}

        return {
            "found": True,
            "route_id": route_id,
            "destination_country": destination_country,
            "baselines": [dict(r) for r in rows],
        }

    @tool(
        description="Query Call Detail Records (CDRs) for a specific route and destination country. Returns paginated results with up to 25 records per page. Each record includes cdr_id, caller_number, callee_number, duration, timestamp, and cost.",
        parameters={
            "type": "object",
            "properties": {
                "route_id": {
                    "type": "string",
                    "description": "The route identifier, e.g. 'RT-0001'."
                },
                "destination_country": {
                    "type": "string",
                    "description": "ISO alpha-2 country code of the destination."
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1."
                }
            },
            "required": ["route_id", "destination_country", "page"]
        }
    )
    def query_cdrs(self, route_id: str, destination_country: str, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM cdr_records "
            "WHERE route_id = ? AND destination_country = ? "
            "ORDER BY call_timestamp",
            (route_id, destination_country)
        ).fetchall()
        conn.close()

        page_size = 25
        total = len(rows)
        total_pages = max(1, (total + page_size - 1) // page_size)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = rows[start:end]

        return {
            "page": page,
            "total_pages": total_pages,
            "total_records": total,
            "records": [dict(r) for r in page_rows],
        }

    @tool(
        description="Check whether a phone number is listed in the known fraudulent numbers database. Returns the fraud status, fraud type, and reporting details if found.",
        parameters={
            "type": "object",
            "properties": {
                "phone_number": {
                    "type": "string",
                    "description": "The full international phone number to check, e.g. '+2348031234567'."
                }
            },
            "required": ["phone_number"]
        }
    )
    def check_fraud_status(self, phone_number: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM known_fraud_numbers WHERE phone_number = ?",
            (phone_number,)
        ).fetchone()
        conn.close()

        if row is None:
            return {"phone_number": phone_number, "is_fraudulent": False}

        r = dict(row)
        return {
            "phone_number": phone_number,
            "is_fraudulent": bool(r["is_active"]),
            "fraud_type": r["fraud_type"],
            "date_flagged": r["date_flagged"],
            "reporting_source": r["reporting_source"],
        }

    @tool(
        description="Get the aggregated country-level risk assessment for a destination country. Returns the maximum risk score across all number prefixes registered for that country, along with the corresponding risk tier.",
        parameters={
            "type": "object",
            "properties": {
                "country_code": {
                    "type": "string",
                    "description": "ISO alpha-2 country code, e.g. 'NG'."
                }
            },
            "required": ["country_code"]
        }
    )
    def get_country_risk(self, country_code: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT MAX(risk_score) as max_risk_score "
            "FROM prefix_risk WHERE country_code = ?",
            (country_code,)
        ).fetchone()

        if row is None or row[0] is None:
            conn.close()
            return {"country_code": country_code, "found": False}

        max_score = row[0]
        # Determine tier from max score
        if max_score >= 70:
            tier = "critical"
        elif max_score >= 50:
            tier = "high"
        elif max_score >= 30:
            tier = "medium"
        else:
            tier = "low"

        # Count prefixes
        count = conn.execute(
            "SELECT COUNT(*) FROM prefix_risk WHERE country_code = ?",
            (country_code,)
        ).fetchone()[0]

        conn.close()

        return {
            "country_code": country_code,
            "found": True,
            "risk_score": max_score,
            "risk_tier": tier,
            "prefix_count": count,
        }

    @tool(
        description="Get detailed information about a specific route, including carrier, origin, destination region, capacity, cost per minute, and current operational status.",
        parameters={
            "type": "object",
            "properties": {
                "route_id": {
                    "type": "string",
                    "description": "The route identifier, e.g. 'RT-0001'."
                }
            },
            "required": ["route_id"]
        }
    )
    def get_route_details(self, route_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM routes WHERE route_id = ?", (route_id,)
        ).fetchone()
        conn.close()

        if row is None:
            return {"route_id": route_id, "found": False}

        return {"found": True, **dict(row)}

    # ═══════════════════════════════════════════════════════════════════════
    # Evaluation
    # ═══════════════════════════════════════════════════════════════════════

    def _compute_ground_truth(self):
        """Compute ground truth alerts from DB and workspace files."""
        # Read config files
        with open(os.path.join(self.workspace, "detection_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)
        spike_multiplier = thresholds["spike_detection"]["multiplier"]
        min_calls = thresholds["spike_detection"]["min_calls_threshold"]

        with open(os.path.join(self.workspace, "alert_classification.json")) as f:
            classification = json.load(f)

        # Read all traffic snapshots
        snapshot_files = sorted(glob_module.glob(
            os.path.join(self.workspace, "traffic_snapshot_*.json")
        ))
        current_volumes = {}  # (route_id, dest_country) -> call_count
        for sf in snapshot_files:
            with open(sf) as f:
                snap = json.load(f)
            monitoring_hour = snap["monitoring_hour"]
            for entry in snap["traffic_data"]:
                key = (entry["route_id"], entry["destination_country"])
                current_volumes[key] = current_volumes.get(key, 0) + entry["call_count"]

        # Get baselines from DB
        conn = sqlite3.connect(self.db_path)

        # Compute spike ratios
        spiking = []
        for (rid, dc), vol in current_volumes.items():
            if vol < min_calls:
                continue
            row = conn.execute(
                "SELECT avg_calls_per_hour FROM historical_baselines "
                "WHERE route_id = ? AND destination_country = ? AND hour_of_day = ?",
                (rid, dc, monitoring_hour)
            ).fetchone()
            if row is None or row[0] == 0:
                continue
            baseline_avg = row[0]
            spike_ratio = vol / baseline_avg
            if spike_ratio >= spike_multiplier:
                spiking.append({
                    "route_id": rid,
                    "destination_country": dc,
                    "current_volume": vol,
                    "baseline_avg": baseline_avg,
                    "spike_ratio": round(spike_ratio, 2),
                })

        # For each spiking combo, count fraud calls and get risk score
        for s in spiking:
            rid, dc = s["route_id"], s["destination_country"]
            cdrs = conn.execute(
                "SELECT callee_number FROM cdr_records "
                "WHERE route_id = ? AND destination_country = ?",
                (rid, dc)
            ).fetchall()
            s["total_calls"] = len(cdrs)
            fraud_count = 0
            for (callee,) in cdrs:
                frow = conn.execute(
                    "SELECT is_active FROM known_fraud_numbers WHERE phone_number = ?",
                    (callee,)
                ).fetchone()
                if frow and frow[0]:
                    fraud_count += 1
            s["fraud_call_count"] = fraud_count

            rrow = conn.execute(
                "SELECT MAX(risk_score) FROM prefix_risk WHERE country_code = ?",
                (dc,)
            ).fetchone()
            s["country_risk_score"] = rrow[0] if rrow and rrow[0] else 0

        conn.close()

        # Classify severity
        rules = classification["classification_rules"]
        for s in spiking:
            severity = "LOW"  # default
            for rule in rules:
                sev = rule["severity"]
                if sev == "CRITICAL":
                    if (s["spike_ratio"] >= rule["min_spike_ratio"] and
                        s["country_risk_score"] >= rule["min_country_risk_score"] and
                        s["fraud_call_count"] >= rule["min_fraud_call_count"]):
                        severity = "CRITICAL"
                        break
                elif sev in ("HIGH", "MEDIUM"):
                    if s["spike_ratio"] >= rule["min_spike_ratio"]:
                        additional = rule.get("additional_conditions", [])
                        if not additional:
                            severity = sev
                            break
                        any_met = False
                        for cond in additional:
                            field = cond["field"]
                            min_val = cond["min_value"]
                            if s.get(field, 0) >= min_val:
                                any_met = True
                                break
                        if any_met:
                            severity = sev
                            break
                elif sev == "LOW":
                    if s["spike_ratio"] >= rule["min_spike_ratio"]:
                        severity = "LOW"
                        break
            s["severity"] = severity

        # Determine recommended action
        action_map = {
            "CRITICAL": "immediate_block",
            "HIGH": "block_pending_review",
            "MEDIUM": "rate_limit",
            "LOW": "monitor",
        }
        for s in spiking:
            s["recommended_action"] = action_map[s["severity"]]

        # Sort by severity priority, then spike_ratio desc
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        spiking.sort(key=lambda x: (severity_order[x["severity"]], -x["spike_ratio"]))

        # Assign alert IDs
        for i, s in enumerate(spiking):
            s["alert_id"] = f"ALT-{i+1:03d}"

        return spiking

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

        criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: alert_report.csv exists with correct columns (10 pts) ──
        c1_max = 10
        max_score += c1_max
        report_path = os.path.join(self.workspace, "alert_report.csv")
        expected_columns = [
            "alert_id", "route_id", "destination_country", "current_volume",
            "baseline_avg", "spike_ratio", "fraud_call_count", "total_calls",
            "country_risk_score", "severity", "recommended_action"
        ]
        if os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    reader = csv.DictReader(f)
                    agent_rows = list(reader)
                    agent_cols = reader.fieldnames or []
                if set(expected_columns).issubset(set(agent_cols)):
                    c1_score = c1_max
                    c1_reason = ""
                else:
                    missing = set(expected_columns) - set(agent_cols)
                    c1_score = c1_max // 2
                    c1_reason = f"Missing columns: {missing}"
            except Exception as e:
                agent_rows = []
                c1_score = 0
                c1_reason = f"Error reading CSV: {e}"
        else:
            agent_rows = []
            c1_score = 0
            c1_reason = "alert_report.csv not found"
        total_score += c1_score
        criteria["csv_format"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": c1_reason if c1_score < c1_max else "",
        }

        # ── Criterion 2: Correct set of alerted routes (20 pts) ──
        c2_max = 20
        max_score += c2_max
        gt_keys = {(a["route_id"], a["destination_country"]) for a in ground_truth}
        agent_keys = set()
        for row in agent_rows:
            agent_keys.add((row.get("route_id", ""), row.get("destination_country", "")))
        if gt_keys or agent_keys:
            intersection = gt_keys & agent_keys
            denom = max(len(gt_keys), len(agent_keys))
            c2_score = round(c2_max * len(intersection) / denom) if denom > 0 else 0
        else:
            c2_score = c2_max  # both empty
        c2_reason = ""
        if c2_score < c2_max:
            missing_alerts = gt_keys - agent_keys
            extra_alerts = agent_keys - gt_keys
            parts = []
            if missing_alerts:
                parts.append(f"Missing: {missing_alerts}")
            if extra_alerts:
                parts.append(f"Extra: {extra_alerts}")
            c2_reason = "; ".join(parts)
        total_score += c2_score
        criteria["route_identification"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": c2_reason,
        }

        # Build lookup for agent rows
        agent_lookup = {}
        for row in agent_rows:
            k = (row.get("route_id", ""), row.get("destination_country", ""))
            agent_lookup[k] = row

        # ── Criterion 3: Correct spike_ratio values (15 pts) ──
        c3_max = 15
        max_score += c3_max
        ratio_matches = 0
        ratio_total = len(ground_truth)
        for gt in ground_truth:
            k = (gt["route_id"], gt["destination_country"])
            ar = agent_lookup.get(k)
            if ar:
                try:
                    agent_ratio = round(float(ar.get("spike_ratio", 0)), 2)
                    if abs(agent_ratio - gt["spike_ratio"]) <= 0.05:
                        ratio_matches += 1
                except (ValueError, TypeError):
                    pass
        c3_score = round(c3_max * ratio_matches / ratio_total) if ratio_total > 0 else c3_max
        total_score += c3_score
        criteria["spike_ratio_accuracy"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": f"{ratio_matches}/{ratio_total} ratios correct" if c3_score < c3_max else "",
        }

        # ── Criterion 4: Correct fraud_call_count (15 pts) ──
        c4_max = 15
        max_score += c4_max
        fraud_matches = 0
        for gt in ground_truth:
            k = (gt["route_id"], gt["destination_country"])
            ar = agent_lookup.get(k)
            if ar:
                try:
                    if int(ar.get("fraud_call_count", -1)) == gt["fraud_call_count"]:
                        fraud_matches += 1
                except (ValueError, TypeError):
                    pass
        c4_score = round(c4_max * fraud_matches / ratio_total) if ratio_total > 0 else c4_max
        total_score += c4_score
        criteria["fraud_count_accuracy"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": f"{fraud_matches}/{ratio_total} counts correct" if c4_score < c4_max else "",
        }

        # ── Criterion 5: Correct severity classification (15 pts) ──
        c5_max = 15
        max_score += c5_max
        sev_matches = 0
        for gt in ground_truth:
            k = (gt["route_id"], gt["destination_country"])
            ar = agent_lookup.get(k)
            if ar:
                if ar.get("severity", "").strip().upper() == gt["severity"]:
                    sev_matches += 1
        c5_score = round(c5_max * sev_matches / ratio_total) if ratio_total > 0 else c5_max
        total_score += c5_score
        criteria["severity_accuracy"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": f"{sev_matches}/{ratio_total} severities correct" if c5_score < c5_max else "",
        }

        # ── Criterion 6: recommended_blocks.json correct (15 pts) ──
        c6_max = 15
        max_score += c6_max
        blocks_path = os.path.join(self.workspace, "recommended_blocks.json")
        gt_blocks = [a for a in ground_truth if a["severity"] in ("CRITICAL", "HIGH")]
        gt_block_keys = {(b["route_id"], b["destination_country"]) for b in gt_blocks}

        if os.path.exists(blocks_path):
            try:
                with open(blocks_path) as f:
                    agent_blocks = json.load(f)
                agent_block_keys = {
                    (b.get("route_id", ""), b.get("destination_country", ""))
                    for b in agent_blocks
                }
                if gt_block_keys or agent_block_keys:
                    bi = gt_block_keys & agent_block_keys
                    bd = max(len(gt_block_keys), len(agent_block_keys))
                    c6_score = round(c6_max * len(bi) / bd) if bd > 0 else 0
                else:
                    c6_score = c6_max

                # Check action correctness for matching entries
                if bi:
                    action_correct = 0
                    gt_block_lookup = {(b["route_id"], b["destination_country"]): b for b in gt_blocks}
                    for ab in agent_blocks:
                        k = (ab.get("route_id", ""), ab.get("destination_country", ""))
                        if k in bi:
                            gt_b = gt_block_lookup[k]
                            if ab.get("action", "") == gt_b["recommended_action"]:
                                action_correct += 1
                    action_ratio = action_correct / len(bi)
                    c6_score = round(c6_score * (0.5 + 0.5 * action_ratio))

                c6_reason = ""
                if c6_score < c6_max:
                    missing_b = gt_block_keys - agent_block_keys
                    extra_b = agent_block_keys - gt_block_keys
                    parts = []
                    if missing_b:
                        parts.append(f"Missing blocks: {missing_b}")
                    if extra_b:
                        parts.append(f"Extra blocks: {extra_b}")
                    c6_reason = "; ".join(parts)
            except Exception as e:
                c6_score = 0
                c6_reason = f"Error reading blocks JSON: {e}"
        else:
            c6_score = 0
            c6_reason = "recommended_blocks.json not found"
        total_score += c6_score
        criteria["blocks_report"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": c6_reason if c6_score < c6_max else "",
        }

        # ── Criterion 7: Response summary (10 pts) ──
        c7_max = 10
        max_score += c7_max
        c7_score = 0
        action_lower = action.lower() if action else ""

        total_alerts = len(ground_truth)
        n_critical = sum(1 for a in ground_truth if a["severity"] == "CRITICAL")
        n_high = sum(1 for a in ground_truth if a["severity"] == "HIGH")
        n_blocks = len(gt_blocks)

        checks = [
            (str(total_alerts) in action, 3, "total alert count"),
            (str(n_critical) in action, 3, "CRITICAL count"),
            (str(n_blocks) in action, 4, "block count"),
        ]
        c7_reasons = []
        for cond, pts, label in checks:
            if cond:
                c7_score += pts
            else:
                c7_reasons.append(f"Missing {label}")

        total_score += c7_score
        criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": "; ".join(c7_reasons) if c7_score < c7_max else "",
        }

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": criteria,
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
        # Step 1: Read configuration files
        with open(os.path.join(self.workspace, "detection_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)
        spike_multiplier = thresholds["spike_detection"]["multiplier"]
        min_calls = thresholds["spike_detection"]["min_calls_threshold"]

        with open(os.path.join(self.workspace, "alert_classification.json")) as f:
            classification = json.load(f)
        rules = classification["classification_rules"]

        # Read blocking policy to determine action mapping
        with open(os.path.join(self.workspace, "route_blocking_policy.md")) as f:
            policy_text = f.read()
        # Parse action mapping from policy
        action_map = {}
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            # Extract action for each severity
            import re
            pattern = rf'{sev} severity.*?recommended action is "([^"]+)"'
            match = re.search(pattern, policy_text, re.IGNORECASE | re.DOTALL)
            if match:
                action_map[sev] = match.group(1)
        # Fallback
        action_map.setdefault("CRITICAL", "immediate_block")
        action_map.setdefault("HIGH", "block_pending_review")
        action_map.setdefault("MEDIUM", "rate_limit")
        action_map.setdefault("LOW", "monitor")

        # Step 2: Read all traffic snapshot files
        snapshot_files = sorted(glob_module.glob(
            os.path.join(self.workspace, "traffic_snapshot_*.json")
        ))
        current_volumes = {}  # (route_id, dest_country) -> call_count
        monitoring_hour = None
        for sf in snapshot_files:
            with open(sf) as f:
                snap = json.load(f)
            monitoring_hour = snap["monitoring_hour"]
            for entry in snap["traffic_data"]:
                key = (entry["route_id"], entry["destination_country"])
                current_volumes[key] = current_volumes.get(key, 0) + entry["call_count"]

        tool_call_count = 0

        # Step 3: For each (route, country) combo, get historical baseline
        spiking = []
        for (rid, dc), vol in current_volumes.items():
            if vol < min_calls:
                continue
            result = self.tools["get_historical_baseline"](
                route_id=rid, destination_country=dc
            )
            tool_call_count += 1
            if not result.get("found"):
                continue
            # Find baseline for monitoring hour
            baseline_avg = None
            for bl in result["baselines"]:
                if bl["hour_of_day"] == monitoring_hour:
                    baseline_avg = bl["avg_calls_per_hour"]
                    break
            if baseline_avg is None or baseline_avg == 0:
                continue
            spike_ratio = round(vol / baseline_avg, 2)
            if spike_ratio >= spike_multiplier:
                spiking.append({
                    "route_id": rid,
                    "destination_country": dc,
                    "current_volume": vol,
                    "baseline_avg": baseline_avg,
                    "spike_ratio": spike_ratio,
                })

        # Step 4: For spiking combos, query CDRs and check fraud status
        for s in spiking:
            rid = s["route_id"]
            dc = s["destination_country"]

            # Collect all CDRs via pagination
            all_callee_numbers = []
            page = 1
            while True:
                result = self.tools["query_cdrs"](
                    route_id=rid, destination_country=dc, page=page
                )
                tool_call_count += 1
                for rec in result["records"]:
                    all_callee_numbers.append(rec["callee_number"])
                if page >= result["total_pages"]:
                    break
                page += 1

            s["total_calls"] = len(all_callee_numbers)

            # Check each unique callee for fraud
            unique_callees = set(all_callee_numbers)
            fraud_numbers_found = set()
            for callee in unique_callees:
                result = self.tools["check_fraud_status"](phone_number=callee)
                tool_call_count += 1
                if result.get("is_fraudulent"):
                    fraud_numbers_found.add(callee)

            # Count total fraud calls (including duplicates)
            fraud_count = sum(1 for c in all_callee_numbers if c in fraud_numbers_found)
            s["fraud_call_count"] = fraud_count

        # Step 5: Get country risk scores
        country_risk_cache = {}
        for s in spiking:
            dc = s["destination_country"]
            if dc not in country_risk_cache:
                result = self.tools["get_country_risk"](country_code=dc)
                tool_call_count += 1
                country_risk_cache[dc] = result.get("risk_score", 0) if result.get("found") else 0
            s["country_risk_score"] = country_risk_cache[dc]

        # Step 6: Classify severity
        for s in spiking:
            severity = "LOW"
            for rule in rules:
                sev = rule["severity"]
                if sev == "CRITICAL":
                    if (s["spike_ratio"] >= rule["min_spike_ratio"] and
                        s["country_risk_score"] >= rule["min_country_risk_score"] and
                        s["fraud_call_count"] >= rule["min_fraud_call_count"]):
                        severity = "CRITICAL"
                        break
                elif sev in ("HIGH", "MEDIUM"):
                    if s["spike_ratio"] >= rule["min_spike_ratio"]:
                        additional = rule.get("additional_conditions", [])
                        if not additional:
                            severity = sev
                            break
                        any_met = False
                        for cond in additional:
                            field = cond["field"]
                            min_val = cond["min_value"]
                            if s.get(field, 0) >= min_val:
                                any_met = True
                                break
                        if any_met:
                            severity = sev
                            break
                elif sev == "LOW":
                    if s["spike_ratio"] >= rule["min_spike_ratio"]:
                        severity = "LOW"
                        break
            s["severity"] = severity
            s["recommended_action"] = action_map.get(severity, "monitor")

        # Step 7: Sort and assign alert IDs
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        spiking.sort(key=lambda x: (severity_order[x["severity"]], -x["spike_ratio"]))
        for i, s in enumerate(spiking):
            s["alert_id"] = f"ALT-{i+1:03d}"

        # Step 8: Write alert_report.csv
        report_path = os.path.join(self.workspace, "alert_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "alert_id", "route_id", "destination_country", "current_volume",
                "baseline_avg", "spike_ratio", "fraud_call_count", "total_calls",
                "country_risk_score", "severity", "recommended_action"
            ])
            writer.writeheader()
            for s in spiking:
                writer.writerow({
                    "alert_id": s["alert_id"],
                    "route_id": s["route_id"],
                    "destination_country": s["destination_country"],
                    "current_volume": s["current_volume"],
                    "baseline_avg": s["baseline_avg"],
                    "spike_ratio": f"{s['spike_ratio']:.2f}",
                    "fraud_call_count": s["fraud_call_count"],
                    "total_calls": s["total_calls"],
                    "country_risk_score": s["country_risk_score"],
                    "severity": s["severity"],
                    "recommended_action": s["recommended_action"],
                })

        # Step 9: Write recommended_blocks.json
        blocks = []
        for s in spiking:
            if s["severity"] in ("CRITICAL", "HIGH"):
                blocks.append({
                    "route_id": s["route_id"],
                    "destination_country": s["destination_country"],
                    "severity": s["severity"],
                    "action": s["recommended_action"],
                    "spike_ratio": s["spike_ratio"],
                    "fraud_call_count": s["fraud_call_count"],
                    "country_risk_score": s["country_risk_score"],
                })
        blocks_path = os.path.join(self.workspace, "recommended_blocks.json")
        with open(blocks_path, "w") as f:
            json.dump(blocks, f, indent=2)

        # Step 10: Construct response summary
        n_critical = sum(1 for s in spiking if s["severity"] == "CRITICAL")
        n_high = sum(1 for s in spiking if s["severity"] == "HIGH")
        n_medium = sum(1 for s in spiking if s["severity"] == "MEDIUM")
        n_low = sum(1 for s in spiking if s["severity"] == "LOW")
        n_blocks = len(blocks)

        action = (
            f"Fraud traffic analysis complete. "
            f"Total alerts: {len(spiking)}. "
            f"Severity breakdown - CRITICAL: {n_critical}, HIGH: {n_high}, "
            f"MEDIUM: {n_medium}, LOW: {n_low}. "
            f"Routes recommended for blocking: {n_blocks}. "
            f"Alert report saved to alert_report.csv. "
            f"Recommended blocks saved to recommended_blocks.json. "
            f"Total tool calls made: {tool_call_count}."
        )

        return self.step(action)
