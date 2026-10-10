"""Environment for tower upgrade prioritization task."""

import csv
import json
import math
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {"description": description, "parameters": parameters}
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

    # ================================================================
    # Tool methods
    # ================================================================

    @tool(
        description="List all cell towers with pagination. Returns tower_id, tower_name, region, and technology for each tower.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1.",
                }
            },
            "required": ["page"],
        },
    )
    def list_towers(self, page: int) -> dict:
        page_size = 20
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM towers")
        total = c.fetchone()[0]
        c.execute(
            "SELECT tower_id, tower_name, region, technology FROM towers ORDER BY tower_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "towers": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description="Get detailed information for a specific cell tower by its tower_id.",
        parameters={
            "type": "object",
            "properties": {
                "tower_id": {
                    "type": "string",
                    "description": "The tower identifier, e.g. 'TWR-0001'.",
                }
            },
            "required": ["tower_id"],
        },
    )
    def get_tower_details(self, tower_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM towers WHERE tower_id = ?", (tower_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Tower {tower_id} not found."}
        return dict(row)

    @tool(
        description="Get a paginated summary of complaint counts and average severity per tower. Each entry contains tower_id, complaint_count, and avg_severity. Only towers with at least one complaint are included.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1.",
                }
            },
            "required": ["page"],
        },
    )
    def get_complaint_summary(self, page: int) -> dict:
        page_size = 20
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM (SELECT tower_id FROM complaints GROUP BY tower_id)"
        )
        total = c.fetchone()[0]
        c.execute(
            """SELECT tower_id,
                      COUNT(*) as complaint_count,
                      ROUND(AVG(severity), 4) as avg_severity
               FROM complaints
               GROUP BY tower_id
               ORDER BY tower_id
               LIMIT ? OFFSET ?""",
            (page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "summaries": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description="Get individual complaint records for a specific tower. Returns complaint_id, subscriber_id, complaint_date, severity, call_type, and description.",
        parameters={
            "type": "object",
            "properties": {
                "tower_id": {
                    "type": "string",
                    "description": "The tower identifier.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1.",
                },
            },
            "required": ["tower_id", "page"],
        },
    )
    def get_complaints_for_tower(self, tower_id: str, page: int) -> dict:
        page_size = 25
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM complaints WHERE tower_id = ?", (tower_id,)
        )
        total = c.fetchone()[0]
        c.execute(
            """SELECT complaint_id, subscriber_id, complaint_date, severity, call_type, description
               FROM complaints WHERE tower_id = ?
               ORDER BY complaint_date DESC
               LIMIT ? OFFSET ?""",
            (tower_id, page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "complaints": rows,
            "tower_id": tower_id,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description="Get aggregated network performance metrics for a specific tower. Returns average signal strength (dBm), average packet loss (%), average latency (ms), average downtime (minutes), and the number of log entries used.",
        parameters={
            "type": "object",
            "properties": {
                "tower_id": {
                    "type": "string",
                    "description": "The tower identifier.",
                }
            },
            "required": ["tower_id"],
        },
    )
    def get_network_metrics(self, tower_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            """SELECT COUNT(*) as log_count,
                      AVG(avg_signal_dbm) as avg_signal_dbm,
                      AVG(packet_loss_pct) as avg_packet_loss_pct,
                      AVG(avg_latency_ms) as avg_latency_ms,
                      AVG(downtime_minutes) as avg_downtime_minutes
               FROM network_logs WHERE tower_id = ?""",
            (tower_id,),
        )
        row = dict(c.fetchone())
        conn.close()
        if row["log_count"] == 0:
            return {
                "tower_id": tower_id,
                "log_count": 0,
                "avg_signal_dbm": None,
                "avg_packet_loss_pct": None,
                "avg_latency_ms": None,
                "avg_downtime_minutes": None,
            }
        return {
            "tower_id": tower_id,
            "log_count": row["log_count"],
            "avg_signal_dbm": row["avg_signal_dbm"],
            "avg_packet_loss_pct": row["avg_packet_loss_pct"],
            "avg_latency_ms": row["avg_latency_ms"],
            "avg_downtime_minutes": row["avg_downtime_minutes"],
        }

    @tool(
        description="Get maintenance records for a specific tower. Returns maintenance_id, start_date, end_date, maintenance_type, impact_level, and status for each record.",
        parameters={
            "type": "object",
            "properties": {
                "tower_id": {
                    "type": "string",
                    "description": "The tower identifier.",
                }
            },
            "required": ["tower_id"],
        },
    )
    def get_maintenance_records(self, tower_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            """SELECT maintenance_id, start_date, end_date, maintenance_type, impact_level, status
               FROM maintenance_schedules WHERE tower_id = ?
               ORDER BY start_date DESC""",
            (tower_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"tower_id": tower_id, "records": rows}

    @tool(
        description="Get subscriber details by subscriber_id. Returns name, plan_tier, home coordinates, primary tower, and registration date.",
        parameters={
            "type": "object",
            "properties": {
                "subscriber_id": {
                    "type": "string",
                    "description": "The subscriber identifier, e.g. 'SUB-00001'.",
                }
            },
            "required": ["subscriber_id"],
        },
    )
    def get_subscriber_info(self, subscriber_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM subscribers WHERE subscriber_id = ?", (subscriber_id,)
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Subscriber {subscriber_id} not found."}
        return dict(row)

    # ================================================================
    # Ground truth computation (used by both step and verify)
    # ================================================================

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the expected tower upgrade priority list from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Load config files
        with open(
            os.path.join(self.workspace, "upgrade_scoring_criteria.yaml")
        ) as f:
            criteria = yaml.safe_load(f)

        with open(
            os.path.join(self.workspace, "technology_upgrade_paths.json")
        ) as f:
            upgrade_paths = json.load(f)

        regional_multipliers = {}
        with open(
            os.path.join(self.workspace, "regional_budget_priorities.csv")
        ) as f:
            reader = csv.DictReader(f)
            for row in reader:
                regional_multipliers[row["region"]] = float(
                    row["priority_multiplier"]
                )

        weights = criteria["weights"]
        qual = criteria["qualification_thresholds"]
        maint_factor = criteria["maintenance_discount"]["factor"]
        issue_mapping = criteria["primary_issue_mapping"]

        # Get complaint summaries
        c.execute(
            """SELECT tower_id,
                      COUNT(*) as complaint_count,
                      AVG(severity) as avg_severity
               FROM complaints GROUP BY tower_id"""
        )
        complaint_map = {}
        for row in c.fetchall():
            complaint_map[row["tower_id"]] = {
                "complaint_count": row["complaint_count"],
                "avg_severity": row["avg_severity"],
            }

        # Get qualifying towers
        qualifying_ids = []
        for tid, info in complaint_map.items():
            if (
                info["complaint_count"] >= qual["min_complaint_count"]
                and info["avg_severity"] >= qual["min_avg_severity"]
            ):
                qualifying_ids.append(tid)

        # Get tower details
        tower_details = {}
        for tid in qualifying_ids:
            c.execute("SELECT * FROM towers WHERE tower_id = ?", (tid,))
            row = c.fetchone()
            if row:
                tower_details[tid] = dict(row)

        # Get network metrics
        network_metrics = {}
        for tid in qualifying_ids:
            c.execute(
                """SELECT AVG(avg_signal_dbm) as avg_signal_dbm,
                          AVG(packet_loss_pct) as avg_packet_loss_pct
                   FROM network_logs WHERE tower_id = ?""",
                (tid,),
            )
            row = c.fetchone()
            if row and row["avg_signal_dbm"] is not None:
                network_metrics[tid] = {
                    "avg_signal_dbm": row["avg_signal_dbm"],
                    "avg_packet_loss_pct": row["avg_packet_loss_pct"],
                }
            else:
                network_metrics[tid] = {
                    "avg_signal_dbm": 0,
                    "avg_packet_loss_pct": 0,
                }

        # Get maintenance records
        maintenance_map = {}
        for tid in qualifying_ids:
            c.execute(
                "SELECT status FROM maintenance_schedules WHERE tower_id = ?",
                (tid,),
            )
            statuses = [r["status"] for r in c.fetchall()]
            maintenance_map[tid] = any(
                s in ("scheduled", "in_progress") for s in statuses
            )

        conn.close()

        # Read signal survey files
        signal_measurements = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("signal_survey_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        signal_measurements.append(
                            {
                                "lat": float(row["latitude"]),
                                "lon": float(row["longitude"]),
                                "signal_dbm": float(row["signal_dbm"]),
                            }
                        )

        # Read call drop report files
        device_signals = {}  # tower_id -> list of signal values
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("call_drop_report_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    for record in data:
                        tid = record["tower_id"]
                        if tid not in device_signals:
                            device_signals[tid] = []
                        device_signals[tid].append(
                            float(record["device_signal_dbm"])
                        )

        # Compute scores for each qualifying tower
        results = []
        for tid in qualifying_ids:
            if tid not in tower_details:
                continue

            details = tower_details[tid]
            comp = complaint_map[tid]
            net = network_metrics[tid]

            # complaint_score
            cs = min(100, comp["complaint_count"] * comp["avg_severity"] * 4)

            # network_score
            avg_sig = net["avg_signal_dbm"]
            pkt_loss = net["avg_packet_loss_pct"]
            ns = min(100, (max(0, (-1 * avg_sig) - 70) * 2 + pkt_loss * 8) / 2)

            # coverage_gap_score
            tower_lat = details["latitude"]
            tower_lon = details["longitude"]
            nearby = [
                m
                for m in signal_measurements
                if abs(m["lat"] - tower_lat) <= 0.5
                and abs(m["lon"] - tower_lon) <= 0.5
            ]
            if nearby:
                below = sum(1 for m in nearby if m["signal_dbm"] < -90)
                cgs = (below / len(nearby)) * 100
            else:
                cgs = 0.0

            # device_signal_score
            if tid in device_signals and device_signals[tid]:
                avg_dev = sum(device_signals[tid]) / len(device_signals[tid])
                dss = min(100, max(0, (-1 * avg_dev) - 80) * 3)
            else:
                dss = 0.0

            # Weighted sum
            raw_score = (
                cs * weights["complaint"]
                + ns * weights["network"]
                + cgs * weights["coverage_gap"]
                + dss * weights["device_signal"]
            )

            # Regional multiplier
            region = details["region"]
            multiplier = regional_multipliers.get(region, 1.0)
            score = raw_score * multiplier

            # Maintenance discount
            if maintenance_map.get(tid, False):
                score *= maint_factor

            score = round(score, 2)

            # Primary issue
            weighted_components = {
                "complaint": cs * weights["complaint"],
                "coverage_gap": cgs * weights["coverage_gap"],
                "device_signal": dss * weights["device_signal"],
                "network": ns * weights["network"],
            }
            primary_component = sorted(
                weighted_components.items(), key=lambda x: (-x[1], x[0])
            )[0][0]
            primary_issue = issue_mapping[primary_component]

            # Priority tier
            if score >= 75:
                tier = "critical"
            elif score >= 50:
                tier = "high"
            elif score >= 25:
                tier = "medium"
            else:
                tier = "low"

            # Recommended upgrade
            tech = details["technology"]
            rec_upgrade = upgrade_paths.get(tech, {}).get(
                "recommended_upgrade", "N/A"
            )

            results.append(
                {
                    "tower_id": tid,
                    "tower_name": details["tower_name"],
                    "region": region,
                    "priority_score": score,
                    "priority_tier": tier,
                    "primary_issue": primary_issue,
                    "recommended_upgrade": rec_upgrade,
                }
            )

        # Sort: priority_score desc, tower_id asc for ties
        results.sort(key=lambda x: (-x["priority_score"], x["tower_id"]))

        # Add rank
        for i, r in enumerate(results):
            r["rank"] = i + 1

        return results

    # ================================================================
    # Step: evaluate agent output
    # ================================================================

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

        # ---- Criterion 1: File exists with correct format (10 pts) ----
        max_score += 10
        output_path = os.path.join(self.workspace, "tower_upgrade_priority.csv")
        expected_columns = [
            "rank",
            "tower_id",
            "tower_name",
            "region",
            "priority_score",
            "priority_tier",
            "primary_issue",
            "recommended_upgrade",
        ]
        agent_rows = []
        if os.path.exists(output_path):
            try:
                with open(output_path, newline="") as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in (reader.fieldnames or [])]
                    if set(expected_columns) <= set(actual_cols):
                        for row in reader:
                            agent_rows.append(
                                {k.strip(): v.strip() for k, v in row.items()}
                            )
                        eval_criteria["file_format"] = {
                            "passed": True,
                            "score": 10,
                            "max_score": 10,
                        }
                        total_score += 10
                    else:
                        missing = set(expected_columns) - set(actual_cols)
                        eval_criteria["file_format"] = {
                            "passed": False,
                            "score": 0,
                            "max_score": 10,
                            "reason": f"Missing columns: {missing}",
                        }
            except Exception as e:
                eval_criteria["file_format"] = {
                    "passed": False,
                    "score": 0,
                    "max_score": 10,
                    "reason": f"Error reading CSV: {e}",
                }
        else:
            eval_criteria["file_format"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "File tower_upgrade_priority.csv not found.",
            }

        # ---- Criterion 2: Correct qualifying towers (20 pts) ----
        max_score += 20
        gt_ids = set(r["tower_id"] for r in ground_truth)
        agent_ids = set(r.get("tower_id", "") for r in agent_rows)
        if gt_ids and agent_ids:
            intersection = gt_ids & agent_ids
            precision = len(intersection) / len(agent_ids) if agent_ids else 0
            recall = len(intersection) / len(gt_ids) if gt_ids else 0
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall) > 0
                else 0
            )
            score_2 = round(20 * f1)
            eval_criteria["qualifying_towers"] = {
                "passed": gt_ids == agent_ids,
                "score": score_2,
                "max_score": 20,
            }
            if gt_ids != agent_ids:
                eval_criteria["qualifying_towers"]["reason"] = (
                    f"Expected {len(gt_ids)} towers, got {len(agent_ids)}. "
                    f"Missing: {gt_ids - agent_ids}, Extra: {agent_ids - gt_ids}"
                )
            total_score += score_2
        elif not gt_ids and not agent_ids:
            eval_criteria["qualifying_towers"] = {
                "passed": True,
                "score": 20,
                "max_score": 20,
            }
            total_score += 20
        else:
            eval_criteria["qualifying_towers"] = {
                "passed": False,
                "score": 0,
                "max_score": 20,
                "reason": f"Expected {len(gt_ids)} towers, got {len(agent_ids)}.",
            }

        # ---- Criterion 3: Correct priority scores (20 pts) ----
        max_score += 20
        if agent_rows and ground_truth:
            gt_scores = {r["tower_id"]: r["priority_score"] for r in ground_truth}
            correct_scores = 0
            total_comparable = 0
            for row in agent_rows:
                tid = row.get("tower_id", "")
                if tid in gt_scores:
                    total_comparable += 1
                    try:
                        agent_score = float(row.get("priority_score", -1))
                        if abs(agent_score - gt_scores[tid]) <= 0.05:
                            correct_scores += 1
                    except (ValueError, TypeError):
                        pass
            frac = correct_scores / total_comparable if total_comparable > 0 else 0
            score_3 = round(20 * frac)
            eval_criteria["priority_scores"] = {
                "passed": frac >= 0.99,
                "score": score_3,
                "max_score": 20,
                "reason": f"{correct_scores}/{total_comparable} scores match within tolerance."
                if frac < 0.99
                else None,
            }
            if eval_criteria["priority_scores"]["reason"] is None:
                del eval_criteria["priority_scores"]["reason"]
            total_score += score_3
        else:
            eval_criteria["priority_scores"] = {
                "passed": False,
                "score": 0,
                "max_score": 20,
                "reason": "No rows to compare.",
            }

        # ---- Criterion 4: Correct ranking order (15 pts) ----
        max_score += 15
        if agent_rows and ground_truth:
            gt_order = [r["tower_id"] for r in ground_truth]
            agent_order = [r.get("tower_id", "") for r in agent_rows]
            # Check if ordering matches (only for towers present in both)
            gt_filtered = [t for t in gt_order if t in agent_ids]
            agent_filtered = [t for t in agent_order if t in gt_ids]
            if gt_filtered == agent_filtered:
                eval_criteria["ranking_order"] = {
                    "passed": True,
                    "score": 15,
                    "max_score": 15,
                }
                total_score += 15
            else:
                # Partial credit based on Kendall tau distance
                common = [t for t in gt_filtered if t in set(agent_filtered)]
                if len(common) >= 2:
                    gt_pos = {t: i for i, t in enumerate(gt_filtered)}
                    agent_pos = {t: i for i, t in enumerate(agent_filtered)}
                    concordant = 0
                    total_pairs = 0
                    common_list = [t for t in gt_filtered if t in set(agent_filtered)]
                    for i in range(len(common_list)):
                        for j in range(i + 1, len(common_list)):
                            ti, tj = common_list[i], common_list[j]
                            if ti in agent_pos and tj in agent_pos:
                                total_pairs += 1
                                if (gt_pos[ti] - gt_pos[tj]) * (
                                    agent_pos[ti] - agent_pos[tj]
                                ) > 0:
                                    concordant += 1
                    tau = concordant / total_pairs if total_pairs > 0 else 0
                    score_4 = round(15 * tau)
                else:
                    score_4 = 0
                eval_criteria["ranking_order"] = {
                    "passed": False,
                    "score": score_4,
                    "max_score": 15,
                    "reason": "Ordering does not match ground truth.",
                }
                total_score += score_4
        else:
            eval_criteria["ranking_order"] = {
                "passed": False,
                "score": 0,
                "max_score": 15,
                "reason": "No rows to compare.",
            }

        # ---- Criterion 5: Correct priority tiers (15 pts) ----
        max_score += 15
        if agent_rows and ground_truth:
            gt_tiers = {r["tower_id"]: r["priority_tier"] for r in ground_truth}
            correct_tiers = 0
            total_comparable = 0
            for row in agent_rows:
                tid = row.get("tower_id", "")
                if tid in gt_tiers:
                    total_comparable += 1
                    if row.get("priority_tier", "").strip().lower() == gt_tiers[tid]:
                        correct_tiers += 1
            frac = correct_tiers / total_comparable if total_comparable > 0 else 0
            score_5 = round(15 * frac)
            eval_criteria["priority_tiers"] = {
                "passed": frac >= 0.99,
                "score": score_5,
                "max_score": 15,
            }
            if frac < 0.99:
                eval_criteria["priority_tiers"]["reason"] = (
                    f"{correct_tiers}/{total_comparable} tiers correct."
                )
            total_score += score_5
        else:
            eval_criteria["priority_tiers"] = {
                "passed": False,
                "score": 0,
                "max_score": 15,
                "reason": "No rows to compare.",
            }

        # ---- Criterion 6: Correct primary issues (10 pts) ----
        max_score += 10
        if agent_rows and ground_truth:
            gt_issues = {r["tower_id"]: r["primary_issue"] for r in ground_truth}
            correct_issues = 0
            total_comparable = 0
            for row in agent_rows:
                tid = row.get("tower_id", "")
                if tid in gt_issues:
                    total_comparable += 1
                    if (
                        row.get("primary_issue", "").strip().lower()
                        == gt_issues[tid].lower()
                    ):
                        correct_issues += 1
            frac = (
                correct_issues / total_comparable if total_comparable > 0 else 0
            )
            score_6 = round(10 * frac)
            eval_criteria["primary_issues"] = {
                "passed": frac >= 0.99,
                "score": score_6,
                "max_score": 10,
            }
            if frac < 0.99:
                eval_criteria["primary_issues"]["reason"] = (
                    f"{correct_issues}/{total_comparable} primary issues correct."
                )
            total_score += score_6
        else:
            eval_criteria["primary_issues"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "No rows to compare.",
            }

        # ---- Criterion 7: Correct recommended upgrades (10 pts) ----
        max_score += 10
        if agent_rows and ground_truth:
            gt_upgrades = {
                r["tower_id"]: r["recommended_upgrade"] for r in ground_truth
            }
            correct_upgrades = 0
            total_comparable = 0
            for row in agent_rows:
                tid = row.get("tower_id", "")
                if tid in gt_upgrades:
                    total_comparable += 1
                    if (
                        row.get("recommended_upgrade", "").strip()
                        == gt_upgrades[tid]
                    ):
                        correct_upgrades += 1
            frac = (
                correct_upgrades / total_comparable if total_comparable > 0 else 0
            )
            score_7 = round(10 * frac)
            eval_criteria["recommended_upgrades"] = {
                "passed": frac >= 0.99,
                "score": score_7,
                "max_score": 10,
            }
            if frac < 0.99:
                eval_criteria["recommended_upgrades"]["reason"] = (
                    f"{correct_upgrades}/{total_comparable} upgrades correct."
                )
            total_score += score_7
        else:
            eval_criteria["recommended_upgrades"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "No rows to compare.",
            }

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ================================================================
    # Verify: prove solvability using only tools + workspace files
    # ================================================================

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
        # ----- Read workspace config files -----
        with open(
            os.path.join(self.workspace, "upgrade_scoring_criteria.yaml")
        ) as f:
            criteria = yaml.safe_load(f)

        with open(
            os.path.join(self.workspace, "technology_upgrade_paths.json")
        ) as f:
            upgrade_paths = json.load(f)

        regional_multipliers = {}
        with open(
            os.path.join(self.workspace, "regional_budget_priorities.csv")
        ) as f:
            reader = csv.DictReader(f)
            for row in reader:
                regional_multipliers[row["region"]] = float(
                    row["priority_multiplier"]
                )

        weights = criteria["weights"]
        qual = criteria["qualification_thresholds"]
        maint_factor = criteria["maintenance_discount"]["factor"]
        issue_mapping = criteria["primary_issue_mapping"]

        # ----- Get complaint summaries via tool (paginated) -----
        complaint_data = {}
        page = 1
        while True:
            result = self.tools["get_complaint_summary"](page=page)
            for item in result["summaries"]:
                complaint_data[item["tower_id"]] = {
                    "complaint_count": item["complaint_count"],
                    "avg_severity": item["avg_severity"],
                }
            if not result["has_more"]:
                break
            page += 1

        # ----- Determine qualifying towers -----
        qualifying_ids = [
            tid
            for tid, info in complaint_data.items()
            if info["complaint_count"] >= qual["min_complaint_count"]
            and info["avg_severity"] >= qual["min_avg_severity"]
        ]

        # ----- For each qualifying tower, get details, network, maintenance -----
        tower_info = {}
        for tid in qualifying_ids:
            details = self.tools["get_tower_details"](tower_id=tid)
            network = self.tools["get_network_metrics"](tower_id=tid)
            maintenance = self.tools["get_maintenance_records"](tower_id=tid)
            tower_info[tid] = {
                "details": details,
                "network": network,
                "maintenance": maintenance,
                "complaints": complaint_data[tid],
            }

        # ----- Read signal survey files -----
        signal_measurements = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("signal_survey_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        signal_measurements.append(
                            {
                                "lat": float(row["latitude"]),
                                "lon": float(row["longitude"]),
                                "signal_dbm": float(row["signal_dbm"]),
                            }
                        )

        # ----- Read call drop report files -----
        device_signals = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("call_drop_report_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    for record in data:
                        tid = record["tower_id"]
                        if tid not in device_signals:
                            device_signals[tid] = []
                        device_signals[tid].append(
                            float(record["device_signal_dbm"])
                        )

        # ----- Compute scores -----
        results = []
        for tid in qualifying_ids:
            info = tower_info[tid]
            details = info["details"]
            comp = info["complaints"]
            net = info["network"]
            maint = info["maintenance"]

            # complaint_score
            cs = min(100, comp["complaint_count"] * comp["avg_severity"] * 4)

            # network_score
            avg_sig = net.get("avg_signal_dbm")
            pkt_loss = net.get("avg_packet_loss_pct")
            if avg_sig is not None and pkt_loss is not None:
                ns = min(
                    100, (max(0, (-1 * avg_sig) - 70) * 2 + pkt_loss * 8) / 2
                )
            else:
                ns = 0.0

            # coverage_gap_score
            tower_lat = details["latitude"]
            tower_lon = details["longitude"]
            nearby = [
                m
                for m in signal_measurements
                if abs(m["lat"] - tower_lat) <= 0.5
                and abs(m["lon"] - tower_lon) <= 0.5
            ]
            if nearby:
                below = sum(1 for m in nearby if m["signal_dbm"] < -90)
                cgs = (below / len(nearby)) * 100
            else:
                cgs = 0.0

            # device_signal_score
            if tid in device_signals and device_signals[tid]:
                avg_dev = sum(device_signals[tid]) / len(device_signals[tid])
                dss = min(100, max(0, (-1 * avg_dev) - 80) * 3)
            else:
                dss = 0.0

            # Weighted sum
            raw_score = (
                cs * weights["complaint"]
                + ns * weights["network"]
                + cgs * weights["coverage_gap"]
                + dss * weights["device_signal"]
            )

            # Regional multiplier
            region = details["region"]
            multiplier = regional_multipliers.get(region, 1.0)
            score = raw_score * multiplier

            # Maintenance discount
            has_active = any(
                r["status"] in ("scheduled", "in_progress")
                for r in maint.get("records", [])
            )
            if has_active:
                score *= maint_factor

            score = round(score, 2)

            # Primary issue
            weighted_components = {
                "complaint": cs * weights["complaint"],
                "coverage_gap": cgs * weights["coverage_gap"],
                "device_signal": dss * weights["device_signal"],
                "network": ns * weights["network"],
            }
            primary_component = sorted(
                weighted_components.items(), key=lambda x: (-x[1], x[0])
            )[0][0]
            primary_issue = issue_mapping[primary_component]

            # Priority tier
            if score >= 75:
                tier = "critical"
            elif score >= 50:
                tier = "high"
            elif score >= 25:
                tier = "medium"
            else:
                tier = "low"

            # Recommended upgrade
            tech = details["technology"]
            rec_upgrade = upgrade_paths.get(tech, {}).get(
                "recommended_upgrade", "N/A"
            )

            results.append(
                {
                    "tower_id": tid,
                    "tower_name": details["tower_name"],
                    "region": region,
                    "priority_score": score,
                    "priority_tier": tier,
                    "primary_issue": primary_issue,
                    "recommended_upgrade": rec_upgrade,
                }
            )

        # Sort
        results.sort(key=lambda x: (-x["priority_score"], x["tower_id"]))

        # Add rank
        for i, r in enumerate(results):
            r["rank"] = i + 1

        # ----- Write output CSV -----
        output_path = os.path.join(self.workspace, "tower_upgrade_priority.csv")
        fieldnames = [
            "rank",
            "tower_id",
            "tower_name",
            "region",
            "priority_score",
            "priority_tier",
            "primary_issue",
            "recommended_upgrade",
        ]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow(r)

        # ----- Build tier counts -----
        tier_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for r in results:
            tier_counts[r["priority_tier"]] += 1

        top_tower = results[0] if results else None
        top_str = (
            f"{top_tower['tower_id']} ({top_tower['tower_name']})"
            if top_tower
            else "none"
        )

        action = (
            f"Analysis complete. Identified {len(results)} towers requiring upgrades. "
            f"Priority tier breakdown: {tier_counts['critical']} critical, "
            f"{tier_counts['high']} high, {tier_counts['medium']} medium, "
            f"{tier_counts['low']} low. "
            f"The tower with the highest priority score is {top_str}."
        )

        return self.step(action)
