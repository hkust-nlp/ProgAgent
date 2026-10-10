"""
Traffic Signal Maintenance Task - Environment
Defines tools for querying signal data and evaluation logic.
"""

import sqlite3
import os
import re
import json
import csv
import math
import yaml
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

    # ── Tool methods ────────────────────────────────────────────────────

    @tool(
        description="List traffic signals with optional filters. Returns paginated results including signal_id, intersection_name, district, and status.",
        parameters={
            "type": "object",
            "properties": {
                "district": {
                    "type": "string",
                    "description": "Filter by district name (Central, North, South, East, West).",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: 'active' or 'inactive'.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1. Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (default 20, max 50).",
                },
            },
            "required": [],
        },
    )
    def list_signals(self, district=None, status=None, page=1, page_size=20):
        page = max(1, int(page) if page is not None else 1)
        page_size = min(50, max(1, int(page_size) if page_size is not None else 20))

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        query = "SELECT signal_id, intersection_name, district, status FROM signals WHERE 1=1"
        params = []
        if district:
            query += " AND district = ?"
            params.append(str(district))
        if status:
            query += " AND status = ?"
            params.append(str(status))
        query += " ORDER BY signal_id"
        c.execute(query, params)
        all_rows = c.fetchall()
        conn.close()

        total = len(all_rows)
        total_pages = max(1, math.ceil(total / page_size))
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = all_rows[start:end]

        return {
            "signals": [
                {
                    "signal_id": r[0],
                    "intersection_name": r[1],
                    "district": r[2],
                    "status": r[3],
                }
                for r in page_rows
            ],
            "page": page,
            "page_size": page_size,
            "total_signals": total,
            "total_pages": total_pages,
        }

    @tool(
        description="Get full details for a specific traffic signal, including type, installation date, and coordinates.",
        parameters={
            "type": "object",
            "properties": {
                "signal_id": {
                    "type": "string",
                    "description": "The signal identifier (e.g. SIG-0001).",
                },
            },
            "required": ["signal_id"],
        },
    )
    def get_signal_info(self, signal_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM signals WHERE signal_id = ?", (str(signal_id),))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Signal {signal_id} not found."}
        return {
            "signal_id": row[0],
            "intersection_name": row[1],
            "district": row[2],
            "signal_type": row[3],
            "install_date": row[4],
            "latitude": row[5],
            "longitude": row[6],
            "status": row[7],
        }

    @tool(
        description="Get aggregated pedestrian push-button log statistics for a specific signal. Returns average response time, maximum response time, and total number of presses recorded.",
        parameters={
            "type": "object",
            "properties": {
                "signal_id": {
                    "type": "string",
                    "description": "The signal identifier.",
                },
            },
            "required": ["signal_id"],
        },
    )
    def get_button_log_stats(self, signal_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT AVG(response_time_ms), MAX(response_time_ms), COUNT(*) "
            "FROM button_logs WHERE signal_id = ?",
            (str(signal_id),),
        )
        row = c.fetchone()
        conn.close()
        avg_rt = round(row[0], 2) if row[0] is not None else None
        max_rt = row[1]
        total = row[2]
        return {
            "signal_id": str(signal_id),
            "avg_response_time_ms": avg_rt,
            "max_response_time_ms": max_rt,
            "total_presses": total,
        }

    @tool(
        description="Get phase change telemetry anomaly statistics for a specific signal. Returns total telemetry records, count of anomalous records, and the anomaly rate.",
        parameters={
            "type": "object",
            "properties": {
                "signal_id": {
                    "type": "string",
                    "description": "The signal identifier.",
                },
            },
            "required": ["signal_id"],
        },
    )
    def get_phase_anomaly_stats(self, signal_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*), SUM(anomaly_flag) FROM phase_telemetry WHERE signal_id = ?",
            (str(signal_id),),
        )
        row = c.fetchone()
        conn.close()
        total = row[0] if row[0] else 0
        anomalies = row[1] if row[1] else 0
        rate = round(anomalies / total, 4) if total > 0 else None
        return {
            "signal_id": str(signal_id),
            "total_records": total,
            "anomaly_count": anomalies,
            "anomaly_rate": rate,
        }

    @tool(
        description="Get congestion alert summary for a specific signal. Returns total alert count, breakdown by severity level, and average delay in seconds.",
        parameters={
            "type": "object",
            "properties": {
                "signal_id": {
                    "type": "string",
                    "description": "The signal identifier.",
                },
            },
            "required": ["signal_id"],
        },
    )
    def get_congestion_alert_summary(self, signal_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*), AVG(avg_delay_s) FROM congestion_alerts WHERE signal_id = ?",
            (str(signal_id),),
        )
        row = c.fetchone()
        total = row[0] if row[0] else 0
        avg_delay = round(row[1], 2) if row[1] is not None else None

        c.execute(
            "SELECT severity, COUNT(*) FROM congestion_alerts "
            "WHERE signal_id = ? GROUP BY severity",
            (str(signal_id),),
        )
        breakdown = {r[0]: r[1] for r in c.fetchall()}
        conn.close()

        return {
            "signal_id": str(signal_id),
            "total_alerts": total,
            "severity_breakdown": breakdown,
            "avg_delay_s": avg_delay,
        }

    # ── Ground-truth computation (shared by step & verify) ──────────────

    def _compute_ground_truth(self):
        """Compute the expected dispatch list from DB + workspace."""
        # Read config
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "district_priorities.json")) as f:
            dist_prio = json.load(f)

        weights = config["scoring_weights"]
        thresholds = config["thresholds"]
        dispatch_threshold = config["dispatch_threshold"]
        tiers = config["urgency_tiers"]

        # All active signals
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT signal_id, intersection_name, district "
            "FROM signals WHERE status = 'active' ORDER BY signal_id"
        )
        active_signals = c.fetchall()

        # Button stats per signal
        button_avgs = {}
        for sig_id, _, _ in active_signals:
            c.execute(
                "SELECT AVG(response_time_ms) FROM button_logs WHERE signal_id = ?",
                (sig_id,),
            )
            val = c.fetchone()[0]
            button_avgs[sig_id] = round(val, 2) if val is not None else None

        # Phase anomaly rate per signal
        phase_rates = {}
        for sig_id, _, _ in active_signals:
            c.execute(
                "SELECT COUNT(*), SUM(anomaly_flag) FROM phase_telemetry WHERE signal_id = ?",
                (sig_id,),
            )
            row = c.fetchone()
            total, anom = row[0] or 0, row[1] or 0
            phase_rates[sig_id] = round(anom / total, 4) if total > 0 else None

        # Congestion alert count per signal
        congestion_counts = {}
        for sig_id, _, _ in active_signals:
            c.execute(
                "SELECT COUNT(*) FROM congestion_alerts WHERE signal_id = ?",
                (sig_id,),
            )
            congestion_counts[sig_id] = c.fetchone()[0]

        conn.close()

        # Complaint counts from workspace CSVs
        complaint_counts = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("complaint_report_week_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row["resolved"].strip().lower() == "no":
                            sid = row["signal_id"].strip()
                            complaint_counts[sid] = complaint_counts.get(sid, 0) + 1

        # Inspection faults from workspace TXTs
        inspection_faults = set()
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("inspection_notes_batch_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                current_signal = None
                for line in content.split("\n"):
                    m = re.match(r"Signal (SIG-\d+)", line)
                    if m:
                        current_signal = m.group(1)
                    if current_signal and "Fault Code:" in line:
                        inspection_faults.add(current_signal)
                        current_signal = None
                    if current_signal and "Status: PASS" in line:
                        current_signal = None

        # Outage exclusions from workspace YAMLs
        outage_signals = set()
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("planned_outage_schedule_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                for entry in data.get("planned_outages", []):
                    outage_signals.add(entry["signal_id"])

        # Score each signal
        component_order = [
            "button_malfunction", "phase_anomaly", "congestion_impact",
            "complaint_severity", "inspection_findings",
        ]
        dispatch = []
        for sig_id, intersection, district in active_signals:
            if sig_id in outage_signals:
                continue

            multiplier = dist_prio.get(district, 1.0)

            # Button malfunction
            avg_rt = button_avgs.get(sig_id)
            bt = thresholds["button_avg_response_ms"]
            if avg_rt is not None and avg_rt >= bt:
                btn_score = weights["button_malfunction"]
            elif avg_rt is not None and avg_rt >= bt / 2:
                btn_score = weights["button_malfunction"] / 2
            else:
                btn_score = 0

            # Phase anomaly
            ar = phase_rates.get(sig_id)
            pt = thresholds["phase_anomaly_rate"]
            if ar is not None and ar >= pt:
                pha_score = weights["phase_anomaly"]
            elif ar is not None and ar >= pt / 2:
                pha_score = weights["phase_anomaly"] / 2
            else:
                pha_score = 0

            # Congestion impact
            ac = congestion_counts.get(sig_id, 0)
            ct = thresholds["congestion_alert_count"]
            if ac >= ct:
                con_score = weights["congestion_impact"]
            elif ac >= ct / 2:
                con_score = weights["congestion_impact"] / 2
            else:
                con_score = 0

            # Complaint severity
            cc = complaint_counts.get(sig_id, 0)
            cct = thresholds["unresolved_complaint_count"]
            if cc >= cct:
                cmp_score = weights["complaint_severity"]
            elif cc >= cct / 2:
                cmp_score = weights["complaint_severity"] / 2
            else:
                cmp_score = 0

            # Inspection findings (binary)
            ins_score = weights["inspection_findings"] if sig_id in inspection_faults else 0

            raw = btn_score + pha_score + con_score + cmp_score + ins_score
            urgency = round(raw * multiplier, 2)

            if urgency < dispatch_threshold:
                continue

            # Determine tier
            tier_name = None
            tier_action = None
            for tname in ["critical", "high", "medium"]:
                if urgency >= tiers[tname]["min_score"]:
                    tier_name = tname
                    tier_action = tiers[tname]["action"]
                    break
            if tier_name is None:
                continue

            # Primary issue
            scores_map = {
                "button_malfunction": btn_score,
                "phase_anomaly": pha_score,
                "congestion_impact": con_score,
                "complaint_severity": cmp_score,
                "inspection_findings": ins_score,
            }
            max_s = max(scores_map.values())
            primary = next(c for c in component_order if scores_map[c] == max_s)

            dispatch.append({
                "signal_id": sig_id,
                "intersection_name": intersection,
                "district": district,
                "urgency_score": urgency,
                "primary_issue": primary,
                "recommended_action": tier_action,
            })

        dispatch.sort(key=lambda x: (-x["urgency_score"], x["signal_id"]))
        for i, entry in enumerate(dispatch):
            entry["rank"] = i + 1

        return dispatch

    # ── Evaluation ──────────────────────────────────────────────────────

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
        expected = self._compute_ground_truth()
        criteria = {}

        # ── Criterion 1: dispatch_list.csv exists with correct headers (15 pts)
        csv_path = os.path.join(self.workspace, "dispatch_list.csv")
        expected_cols = [
            "rank", "signal_id", "intersection_name", "district",
            "urgency_score", "primary_issue", "recommended_action",
        ]
        actual_rows = []
        if os.path.exists(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    headers = reader.fieldnames or []
                    actual_rows = list(reader)
                if list(headers) == expected_cols:
                    criteria["csv_format"] = {
                        "passed": True, "score": 15, "max_score": 15,
                    }
                else:
                    criteria["csv_format"] = {
                        "passed": False, "score": 5, "max_score": 15,
                        "reason": f"Headers mismatch: got {headers}, expected {expected_cols}",
                    }
            except Exception as e:
                criteria["csv_format"] = {
                    "passed": False, "score": 0, "max_score": 15,
                    "reason": f"CSV parse error: {e}",
                }
        else:
            criteria["csv_format"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "dispatch_list.csv not found.",
            }

        # ── Criterion 2: correct signal IDs on the list (20 pts)
        expected_ids = {e["signal_id"] for e in expected}
        actual_ids = {r.get("signal_id", "").strip() for r in actual_rows}
        if expected_ids and actual_ids == expected_ids:
            criteria["signal_ids"] = {"passed": True, "score": 20, "max_score": 20}
        elif expected_ids:
            overlap = len(expected_ids & actual_ids)
            total = len(expected_ids | actual_ids)
            partial = round(20 * overlap / total) if total > 0 else 0
            criteria["signal_ids"] = {
                "passed": False, "score": partial, "max_score": 20,
                "reason": f"Expected {len(expected_ids)} signals, got {len(actual_ids)}. "
                          f"Correct: {overlap}, missing: {len(expected_ids - actual_ids)}, "
                          f"extra: {len(actual_ids - expected_ids)}.",
            }
        else:
            criteria["signal_ids"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "No expected signals (possible ground-truth issue).",
            }

        # ── Criterion 3: correct urgency scores (20 pts)
        expected_scores = {e["signal_id"]: f"{e['urgency_score']:.2f}" for e in expected}
        actual_scores = {}
        for r in actual_rows:
            sid = r.get("signal_id", "").strip()
            actual_scores[sid] = r.get("urgency_score", "").strip()

        score_matches = 0
        score_total = len(expected_scores)
        for sid, exp_s in expected_scores.items():
            act_s = actual_scores.get(sid, "")
            try:
                if abs(float(act_s) - float(exp_s)) < 0.015:
                    score_matches += 1
            except (ValueError, TypeError):
                pass

        if score_total > 0 and score_matches == score_total:
            criteria["urgency_scores"] = {"passed": True, "score": 20, "max_score": 20}
        elif score_total > 0:
            partial = round(20 * score_matches / score_total)
            criteria["urgency_scores"] = {
                "passed": False, "score": partial, "max_score": 20,
                "reason": f"{score_matches}/{score_total} scores match.",
            }
        else:
            criteria["urgency_scores"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "No expected scores.",
            }

        # ── Criterion 4: correct ranking order (15 pts)
        expected_order = [e["signal_id"] for e in expected]
        actual_order = [r.get("signal_id", "").strip() for r in actual_rows]
        if expected_order and actual_order == expected_order:
            criteria["ranking_order"] = {"passed": True, "score": 15, "max_score": 15}
        elif expected_order:
            # Partial credit: Kendall tau distance-based
            common = [s for s in actual_order if s in expected_ids]
            if len(common) == len(expected_order):
                # Check how many are in the right relative position
                correct_pos = sum(
                    1 for a, e in zip(actual_order, expected_order) if a == e
                )
                partial = round(15 * correct_pos / len(expected_order))
            else:
                partial = 0
            criteria["ranking_order"] = {
                "passed": False, "score": partial, "max_score": 15,
                "reason": f"Order mismatch. Correct positions: {correct_pos if len(common) == len(expected_order) else 'N/A'}.",
            }
        else:
            criteria["ranking_order"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "No expected order.",
            }

        # ── Criterion 5: correct primary_issue (10 pts)
        expected_issues = {e["signal_id"]: e["primary_issue"] for e in expected}
        issue_matches = 0
        for r in actual_rows:
            sid = r.get("signal_id", "").strip()
            if sid in expected_issues and r.get("primary_issue", "").strip() == expected_issues[sid]:
                issue_matches += 1
        if expected_issues and issue_matches == len(expected_issues):
            criteria["primary_issue"] = {"passed": True, "score": 10, "max_score": 10}
        elif expected_issues:
            partial = round(10 * issue_matches / len(expected_issues))
            criteria["primary_issue"] = {
                "passed": False, "score": partial, "max_score": 10,
                "reason": f"{issue_matches}/{len(expected_issues)} primary issues match.",
            }
        else:
            criteria["primary_issue"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "No expected issues.",
            }

        # ── Criterion 6: correct recommended_action (10 pts)
        expected_actions = {e["signal_id"]: e["recommended_action"] for e in expected}
        action_matches = 0
        for r in actual_rows:
            sid = r.get("signal_id", "").strip()
            if sid in expected_actions and r.get("recommended_action", "").strip() == expected_actions[sid]:
                action_matches += 1
        if expected_actions and action_matches == len(expected_actions):
            criteria["recommended_action"] = {"passed": True, "score": 10, "max_score": 10}
        elif expected_actions:
            partial = round(10 * action_matches / len(expected_actions))
            criteria["recommended_action"] = {
                "passed": False, "score": partial, "max_score": 10,
                "reason": f"{action_matches}/{len(expected_actions)} actions match.",
            }
        else:
            criteria["recommended_action"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "No expected actions.",
            }

        # ── Criterion 7: response summary (10 pts)
        resp_score = 0
        # Check total count mentioned
        total_expected = len(expected)
        if str(total_expected) in (action or ""):
            resp_score += 5
        # Check that at least 80% of signal IDs appear in the response text
        mentioned = sum(1 for e in expected if e["signal_id"] in (action or ""))
        if total_expected > 0 and mentioned >= total_expected * 0.8:
            resp_score += 5
        criteria["response_summary"] = {
            "passed": resp_score == 10,
            "score": resp_score,
            "max_score": 10,
            "reason": None if resp_score == 10 else
                f"Count mentioned: {str(total_expected) in (action or '')}, "
                f"IDs mentioned: {mentioned}/{total_expected}.",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return total_score / max_score if max_score > 0 else 0.0, info

    # ── Self-test / verification ────────────────────────────────────────

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
        # Read config files from workspace
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "district_priorities.json")) as f:
            dist_prio = json.load(f)

        weights = config["scoring_weights"]
        thresholds = config["thresholds"]
        dispatch_threshold = config["dispatch_threshold"]
        tiers = config["urgency_tiers"]

        component_order = [
            "button_malfunction", "phase_anomaly", "congestion_impact",
            "complaint_severity", "inspection_findings",
        ]

        # ── Gather all active signals via tools ──
        all_signals = []
        page = 1
        while True:
            result = self.tools["list_signals"](status="active", page=page, page_size=50)
            all_signals.extend(result["signals"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ── Read complaint CSVs from workspace ──
        complaint_counts = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("complaint_report_week_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row["resolved"].strip().lower() == "no":
                            sid = row["signal_id"].strip()
                            complaint_counts[sid] = complaint_counts.get(sid, 0) + 1

        # ── Read inspection TXTs from workspace ──
        inspection_faults = set()
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("inspection_notes_batch_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                current_signal = None
                for line in content.split("\n"):
                    m = re.match(r"Signal (SIG-\d+)", line)
                    if m:
                        current_signal = m.group(1)
                    if current_signal and "Fault Code:" in line:
                        inspection_faults.add(current_signal)
                        current_signal = None
                    if current_signal and "Status: PASS" in line:
                        current_signal = None

        # ── Read outage YAMLs from workspace ──
        outage_signals = set()
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("planned_outage_schedule_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                for entry in data.get("planned_outages", []):
                    outage_signals.add(entry["signal_id"])

        # ── Query tools for each signal and compute scores ──
        tool_call_count = 0
        dispatch_list = []

        for sig in all_signals:
            sig_id = sig["signal_id"]
            if sig_id in outage_signals:
                continue

            district = sig["district"]
            intersection = sig["intersection_name"]
            multiplier = dist_prio.get(district, 1.0)

            # Button stats via tool
            btn_result = self.tools["get_button_log_stats"](signal_id=sig_id)
            tool_call_count += 1
            avg_rt = btn_result["avg_response_time_ms"]

            # Phase stats via tool
            pha_result = self.tools["get_phase_anomaly_stats"](signal_id=sig_id)
            tool_call_count += 1
            anomaly_rate = pha_result["anomaly_rate"]

            # Congestion stats via tool
            con_result = self.tools["get_congestion_alert_summary"](signal_id=sig_id)
            tool_call_count += 1
            alert_count = con_result["total_alerts"]

            # Button score
            bt = thresholds["button_avg_response_ms"]
            if avg_rt is not None and avg_rt >= bt:
                btn_score = weights["button_malfunction"]
            elif avg_rt is not None and avg_rt >= bt / 2:
                btn_score = weights["button_malfunction"] / 2
            else:
                btn_score = 0

            # Phase score
            pt = thresholds["phase_anomaly_rate"]
            if anomaly_rate is not None and anomaly_rate >= pt:
                pha_score = weights["phase_anomaly"]
            elif anomaly_rate is not None and anomaly_rate >= pt / 2:
                pha_score = weights["phase_anomaly"] / 2
            else:
                pha_score = 0

            # Congestion score
            ct = thresholds["congestion_alert_count"]
            if alert_count >= ct:
                con_score = weights["congestion_impact"]
            elif alert_count >= ct / 2:
                con_score = weights["congestion_impact"] / 2
            else:
                con_score = 0

            # Complaint score
            cc = complaint_counts.get(sig_id, 0)
            cct = thresholds["unresolved_complaint_count"]
            if cc >= cct:
                cmp_score = weights["complaint_severity"]
            elif cc >= cct / 2:
                cmp_score = weights["complaint_severity"] / 2
            else:
                cmp_score = 0

            # Inspection score (binary)
            ins_score = weights["inspection_findings"] if sig_id in inspection_faults else 0

            raw = btn_score + pha_score + con_score + cmp_score + ins_score
            urgency = round(raw * multiplier, 2)

            if urgency < dispatch_threshold:
                continue

            # Tier
            tier_name = None
            tier_action = None
            for tname in ["critical", "high", "medium"]:
                if urgency >= tiers[tname]["min_score"]:
                    tier_name = tname
                    tier_action = tiers[tname]["action"]
                    break
            if tier_name is None:
                continue

            # Primary issue
            scores_map = {
                "button_malfunction": btn_score,
                "phase_anomaly": pha_score,
                "congestion_impact": con_score,
                "complaint_severity": cmp_score,
                "inspection_findings": ins_score,
            }
            max_s = max(scores_map.values())
            primary = next(c for c in component_order if scores_map[c] == max_s)

            dispatch_list.append({
                "signal_id": sig_id,
                "intersection_name": intersection,
                "district": district,
                "urgency_score": urgency,
                "primary_issue": primary,
                "recommended_action": tier_action,
            })

        # Sort by urgency_score desc, signal_id asc
        dispatch_list.sort(key=lambda x: (-x["urgency_score"], x["signal_id"]))
        for i, entry in enumerate(dispatch_list):
            entry["rank"] = i + 1

        # ── Write dispatch_list.csv ──
        fieldnames = [
            "rank", "signal_id", "intersection_name", "district",
            "urgency_score", "primary_issue", "recommended_action",
        ]
        with open(os.path.join(self.workspace, "dispatch_list.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for entry in dispatch_list:
                row = dict(entry)
                row["urgency_score"] = f"{entry['urgency_score']:.2f}"
                writer.writerow(row)

        # ── Build action string ──
        lines = [f"Total signals on dispatch list: {len(dispatch_list)}"]
        for entry in dispatch_list:
            lines.append(
                f"{entry['rank']}. {entry['signal_id']} | "
                f"{entry['intersection_name']} | "
                f"{entry['urgency_score']:.2f} | "
                f"{entry['recommended_action']}"
            )
        action = "\n".join(lines)

        # Count tool calls: list_signals pages + 3 per active signal
        # (actual count tracked above)
        assert tool_call_count >= 15, (
            f"Only {tool_call_count} tool calls made; need at least 15."
        )

        return self.step(action)
