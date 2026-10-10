"""
Emergency Resource Utilization Audit - Task Environment
"""

from typing import Tuple, Dict, List, Any
import sqlite3
import os
import json
import csv
import yaml
from datetime import datetime, timedelta
import re
import glob as globmod


# ── Decorator ─────────────────────────────────────────────────────────────────

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── Task Environment ──────────────────────────────────────────────────────────

def _envelope(payload):
    """MCP-style tool result: payload JSON-encoded in a text content block."""
    return {"content": [{"type": "text",
                          "text": json.dumps(payload, ensure_ascii=False, default=str)}],
            "isError": False}


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

    # ── Tool Methods ──────────────────────────────────────────────────────

    @tool(
        description="List all emergency response units, paginated. Returns unit_id, unit_name, unit_type, and station for each unit.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Each page returns up to 20 units.",
                },
            },
            "required": ["page"],
        },
    )
    def list_units(self, page: int = 1) -> dict:
        page_size = 20
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        total = c.execute("SELECT COUNT(*) FROM units").fetchone()[0]
        total_pages = max(1, (total + page_size - 1) // page_size)
        offset = (page - 1) * page_size
        rows = c.execute(
            "SELECT unit_id, unit_name, unit_type, station FROM units ORDER BY unit_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return _envelope({
            "units": [dict(r) for r in rows],
            "page": page,
            "total_pages": total_pages,
            "total_units": total,
        })

    @tool(
        description="Get all personnel assigned to a specific unit. Returns person_id, name, role, certification_level, cert_expiry_date, and years_experience for each person.",
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {
                    "type": "string",
                    "description": "The unit identifier, e.g. 'UNIT-0001'.",
                },
            },
            "required": ["unit_id"],
        },
    )
    def get_unit_personnel(self, unit_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT person_id, name, role, certification_level, cert_expiry_date, years_experience "
            "FROM personnel WHERE unit_id = ? ORDER BY person_id",
            (unit_id,),
        ).fetchall()
        conn.close()
        return json.dumps({"unit_id": unit_id, "personnel": [dict(r) for r in rows]}, ensure_ascii=False, default=str)

    @tool(
        description="Get all equipment assigned to a specific unit. Returns equipment_id, equipment_type, serial_number, condition_rating, and acquisition_date for each item.",
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {
                    "type": "string",
                    "description": "The unit identifier, e.g. 'UNIT-0001'.",
                },
            },
            "required": ["unit_id"],
        },
    )
    def get_unit_equipment(self, unit_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT equipment_id, equipment_type, serial_number, condition_rating, acquisition_date "
            "FROM equipment WHERE unit_id = ? ORDER BY equipment_id",
            (unit_id,),
        ).fetchall()
        conn.close()
        return _envelope({"unit_id": unit_id, "equipment": [dict(r) for r in rows]})

    @tool(
        description="Get maintenance history for a specific piece of equipment. Returns log_id, maintenance_date, maintenance_type, result, technician, and next_due_date for each record, ordered by maintenance_date descending.",
        parameters={
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "The equipment identifier, e.g. 'EQ-0001'.",
                },
            },
            "required": ["equipment_id"],
        },
    )
    def get_maintenance_history(self, equipment_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT log_id, maintenance_date, maintenance_type, result, technician, next_due_date "
            "FROM maintenance_logs WHERE equipment_id = ? ORDER BY maintenance_date DESC",
            (equipment_id,),
        ).fetchall()
        conn.close()
        return _envelope({"equipment_id": equipment_id, "logs": [dict(r) for r in rows]})

    @tool(
        description="Get dispatch records for a specific unit, paginated. Returns incident_id, incident_date, incident_type, severity, dispatch_time, and arrival_time for each dispatch. Ordered by dispatch_time descending.",
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {
                    "type": "string",
                    "description": "The unit identifier, e.g. 'UNIT-0001'.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Each page returns up to 10 records.",
                },
            },
            "required": ["unit_id", "page"],
        },
    )
    def get_unit_dispatches(self, unit_id: str, page: int = 1) -> dict:
        page_size = 10
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        total = c.execute(
            "SELECT COUNT(*) FROM dispatches WHERE unit_id = ?", (unit_id,)
        ).fetchone()[0]
        total_pages = max(1, (total + page_size - 1) // page_size)
        offset = (page - 1) * page_size
        rows = c.execute(
            "SELECT d.dispatch_id, d.incident_id, i.incident_date, i.incident_type, i.severity, "
            "d.dispatch_time, d.arrival_time "
            "FROM dispatches d JOIN incidents i ON d.incident_id = i.incident_id "
            "WHERE d.unit_id = ? ORDER BY d.dispatch_time DESC LIMIT ? OFFSET ?",
            (unit_id, page_size, offset),
        ).fetchall()
        conn.close()
        return json.dumps({
            "unit_id": unit_id,
            "dispatches": [dict(r) for r in rows],
            "page": page,
            "total_pages": total_pages,
            "total_dispatches": total,
        }, ensure_ascii=False, default=str)

    @tool(
        description="Get the outcome report for a specific incident. Returns outcome_rating (1-5 scale), civilian_injuries, property_damage_k (in thousands), and after_action_notes.",
        parameters={
            "type": "object",
            "properties": {
                "incident_id": {
                    "type": "string",
                    "description": "The incident identifier, e.g. 'INC-0001'.",
                },
            },
            "required": ["incident_id"],
        },
    )
    def get_incident_outcome(self, incident_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT outcome_id, incident_id, outcome_rating, civilian_injuries, "
            "property_damage_k, after_action_notes "
            "FROM incident_outcomes WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"No outcome found for incident {incident_id}"}, ensure_ascii=False, default=str)
        return json.dumps({"outcome": dict(row)}, ensure_ascii=False, default=str)

    # ── Ground Truth Computation ──────────────────────────────────────────

    def _load_config(self):
        """Load workspace config files."""
        with open(os.path.join(self.workspace, "audit_policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "certification_requirements.json"), "r") as f:
            cert_reqs = json.load(f)

        penalties = {}
        with open(os.path.join(self.workspace, "scoring_matrix.csv"), "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                penalties[row["deficiency_type"]] = {
                    "penalty": int(row["penalty_points"]),
                    "category": row["category"],
                }

        return policy, cert_reqs, penalties

    def _parse_transcript_violations(self, policy, unit_names):
        """Parse all transcript files for protocol violations per unit."""
        keywords = policy.get("protocol_violation_keywords", [])
        violation_counts = {}  # unit_name -> count

        # Build regex patterns for exact unit name matching (word boundaries)
        unit_patterns = {uname: re.compile(r'\b' + re.escape(uname) + r'\b') for uname in unit_names}

        transcript_files = sorted(globmod.glob(os.path.join(self.workspace, "dispatch_transcript_*.txt")))
        for fpath in transcript_files:
            # Read dispatched units from header for this transcript
            dispatched_in_file = set()
            with open(fpath, "r") as f:
                lines = f.readlines()
            for line in lines:
                if line.startswith("Dispatched Units:"):
                    names_str = line.split(":", 1)[1].strip()
                    dispatched_in_file = {n.strip() for n in names_str.split(",")}
                    break

            for line in lines:
                line_lower = line.lower()
                for kw in keywords:
                    if kw.lower() in line_lower:
                        # Find which dispatched unit name appears in this line
                        for uname in dispatched_in_file:
                            if uname in unit_patterns and unit_patterns[uname].search(line):
                                violation_counts[uname] = violation_counts.get(uname, 0) + 1
                        break  # Only count one keyword per line

        return violation_counts

    def _compute_ground_truth(self):
        """Compute ground truth priority scores."""
        policy, cert_reqs, penalties = self._load_config()

        thresholds = policy["thresholds"]
        audit_date = datetime.strptime(policy["audit_date"], "%Y-%m-%d")
        warning_cutoff = audit_date + timedelta(days=thresholds["cert_expiry_warning_days"])
        response_threshold = thresholds["response_time_minutes"]
        min_outcome = thresholds["min_outcome_rating"]
        min_condition = thresholds["min_equipment_condition"]

        retraining_factors = set(policy["scoring"]["retraining_factors"])
        reequip_factors = set(policy["scoring"]["reequip_factors"])

        cert_level_order = {"basic": 0, "intermediate": 1, "advanced": 2, "specialist": 3}

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get all units
        units = [dict(r) for r in conn.execute("SELECT * FROM units ORDER BY unit_id").fetchall()]
        uid_to_name = {u["unit_id"]: u["unit_name"] for u in units}
        uid_to_type = {u["unit_id"]: u["unit_type"] for u in units}
        name_to_uid = {u["unit_name"]: u["unit_id"] for u in units}

        # Parse transcript violations
        all_unit_names = [u["unit_name"] for u in units]
        violation_counts_by_name = self._parse_transcript_violations(policy, all_unit_names)
        violation_counts = {}
        for uname, count in violation_counts_by_name.items():
            uid = name_to_uid.get(uname)
            if uid:
                violation_counts[uid] = count

        results = {}
        for unit in units:
            uid = unit["unit_id"]
            ut = unit["unit_type"]
            scores = {
                "slow_response": 0,
                "certification_deficiency": 0,
                "poor_outcome": 0,
                "protocol_violation": 0,
                "overdue_maintenance": 0,
                "poor_equipment_condition": 0,
            }

            # 1. Response time
            dispatches = conn.execute(
                "SELECT dispatch_time, arrival_time FROM dispatches WHERE unit_id = ?",
                (uid,),
            ).fetchall()
            if dispatches:
                response_times = []
                for d in dispatches:
                    dt = datetime.strptime(d["dispatch_time"], "%Y-%m-%d %H:%M:%S")
                    at = datetime.strptime(d["arrival_time"], "%Y-%m-%d %H:%M:%S")
                    rt = (at - dt).total_seconds() / 60.0
                    response_times.append(rt)
                avg_rt = sum(response_times) / len(response_times)
                if avg_rt > response_threshold:
                    scores["slow_response"] = penalties["slow_response"]["penalty"]

            # 2. Certification deficiency
            personnel = conn.execute(
                "SELECT role, certification_level, cert_expiry_date FROM personnel WHERE unit_id = ?",
                (uid,),
            ).fetchall()
            for p in personnel:
                expiry = datetime.strptime(p["cert_expiry_date"], "%Y-%m-%d")
                required_level = cert_reqs.get(ut, {}).get(p["role"], "basic")
                is_expiring = expiry <= warning_cutoff
                is_underqualified = cert_level_order.get(p["certification_level"], 0) < cert_level_order.get(required_level, 0)
                if is_expiring or is_underqualified:
                    scores["certification_deficiency"] += penalties["certification_deficiency"]["penalty"]

            # 3. Poor outcomes
            incident_ids = conn.execute(
                "SELECT DISTINCT incident_id FROM dispatches WHERE unit_id = ?",
                (uid,),
            ).fetchall()
            for row in incident_ids:
                outcome = conn.execute(
                    "SELECT outcome_rating FROM incident_outcomes WHERE incident_id = ?",
                    (row["incident_id"],),
                ).fetchone()
                if outcome and outcome["outcome_rating"] < min_outcome:
                    scores["poor_outcome"] += penalties["poor_outcome"]["penalty"]

            # 4. Protocol violations
            n_violations = violation_counts.get(uid, 0)
            scores["protocol_violation"] = n_violations * penalties["protocol_violation"]["penalty"]

            # 5. Overdue maintenance
            equip_rows = conn.execute(
                "SELECT equipment_id, condition_rating FROM equipment WHERE unit_id = ?",
                (uid,),
            ).fetchall()
            for eq in equip_rows:
                # Get latest maintenance log
                latest = conn.execute(
                    "SELECT next_due_date FROM maintenance_logs WHERE equipment_id = ? ORDER BY maintenance_date DESC LIMIT 1",
                    (eq["equipment_id"],),
                ).fetchone()
                if latest:
                    ndd = datetime.strptime(latest["next_due_date"], "%Y-%m-%d")
                    if ndd < audit_date:
                        scores["overdue_maintenance"] += penalties["overdue_maintenance"]["penalty"]

                # 6. Poor equipment condition
                if eq["condition_rating"] < min_condition:
                    scores["poor_equipment_condition"] += penalties["poor_equipment_condition"]["penalty"]

            # Compute category scores
            retraining_score = sum(scores[f] for f in retraining_factors if f in scores)
            reequip_score = sum(scores[f] for f in reequip_factors if f in scores)
            total = retraining_score + reequip_score

            if total > 0:
                if retraining_score > 0 and reequip_score > 0:
                    action = "RETRAIN_AND_RE-EQUIP"
                elif retraining_score > 0:
                    action = "RETRAIN"
                else:
                    action = "RE-EQUIP"

                results[uid] = {
                    "unit_id": uid,
                    "unit_name": uid_to_name[uid],
                    "unit_type": ut,
                    "retraining_score": retraining_score,
                    "reequip_score": reequip_score,
                    "total_priority_score": total,
                    "action_required": action,
                }

        conn.close()

        # Sort: total_priority_score desc, unit_id asc
        sorted_results = sorted(
            results.values(),
            key=lambda x: (-x["total_priority_score"], x["unit_id"]),
        )
        return sorted_results

    # ── Step (Evaluation) ─────────────────────────────────────────────────

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
        gt_by_uid = {r["unit_id"]: r for r in ground_truth}
        gt_uids = set(gt_by_uid.keys())

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: Report exists with correct headers (10 pts) ──
        max_score += 10
        report_path = os.path.join(self.workspace, "priority_report.csv")
        expected_cols = ["unit_id", "unit_name", "unit_type", "retraining_score",
                         "reequip_score", "total_priority_score", "action_required"]
        report_rows = []
        if os.path.exists(report_path):
            try:
                with open(report_path, "r") as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in (reader.fieldnames or [])]
                    if actual_cols == expected_cols:
                        report_rows = [r for r in reader]
                        eval_criteria["report_format"] = {
                            "passed": True, "score": 10, "max_score": 10
                        }
                        total_score += 10
                    else:
                        eval_criteria["report_format"] = {
                            "passed": False, "score": 0, "max_score": 10,
                            "reason": f"Column mismatch. Expected {expected_cols}, got {actual_cols}",
                        }
            except Exception as e:
                eval_criteria["report_format"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": f"Failed to parse CSV: {e}",
                }
        else:
            eval_criteria["report_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "priority_report.csv not found",
            }

        # ── Criterion 2: Correct units included (15 pts) ──
        max_score += 15
        report_uids = set()
        report_by_uid = {}
        for row in report_rows:
            uid = row.get("unit_id", "").strip()
            report_uids.add(uid)
            report_by_uid[uid] = row

        if gt_uids:
            correct_uids = gt_uids & report_uids
            extra_uids = report_uids - gt_uids
            missing_uids = gt_uids - report_uids
            # Partial credit: proportion of correct minus penalty for extra
            precision = len(correct_uids) / max(1, len(report_uids))
            recall = len(correct_uids) / len(gt_uids)
            f1 = 2 * precision * recall / max(1e-9, precision + recall)
            c2_score = round(15 * f1)
            passed = (missing_uids == set() and extra_uids == set())
            eval_criteria["correct_units"] = {
                "passed": passed, "score": c2_score, "max_score": 15,
            }
            if not passed:
                eval_criteria["correct_units"]["reason"] = (
                    f"Missing {len(missing_uids)}, extra {len(extra_uids)} units"
                )
            total_score += c2_score
        else:
            eval_criteria["correct_units"] = {
                "passed": len(report_uids) == 0, "score": 15 if len(report_uids) == 0 else 0,
                "max_score": 15,
            }
            total_score += eval_criteria["correct_units"]["score"]

        # ── Criterion 3: Retraining scores correct (20 pts) ──
        max_score += 20
        if gt_uids and report_by_uid:
            correct_rt = 0
            for uid in gt_uids & report_uids:
                try:
                    agent_val = int(report_by_uid[uid].get("retraining_score", "").strip())
                except (ValueError, AttributeError):
                    agent_val = -1
                if agent_val == gt_by_uid[uid]["retraining_score"]:
                    correct_rt += 1
            if len(gt_uids & report_uids) > 0:
                ratio = correct_rt / len(gt_uids & report_uids)
            else:
                ratio = 0
            c3_score = round(20 * ratio)
            eval_criteria["retraining_scores"] = {
                "passed": ratio == 1.0, "score": c3_score, "max_score": 20,
            }
            if ratio < 1.0:
                eval_criteria["retraining_scores"]["reason"] = (
                    f"{correct_rt}/{len(gt_uids & report_uids)} retraining scores correct"
                )
            total_score += c3_score
        else:
            eval_criteria["retraining_scores"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "No matching units to compare",
            }

        # ── Criterion 4: Re-equip scores correct (20 pts) ──
        max_score += 20
        if gt_uids and report_by_uid:
            correct_re = 0
            for uid in gt_uids & report_uids:
                try:
                    agent_val = int(report_by_uid[uid].get("reequip_score", "").strip())
                except (ValueError, AttributeError):
                    agent_val = -1
                if agent_val == gt_by_uid[uid]["reequip_score"]:
                    correct_re += 1
            if len(gt_uids & report_uids) > 0:
                ratio = correct_re / len(gt_uids & report_uids)
            else:
                ratio = 0
            c4_score = round(20 * ratio)
            eval_criteria["reequip_scores"] = {
                "passed": ratio == 1.0, "score": c4_score, "max_score": 20,
            }
            if ratio < 1.0:
                eval_criteria["reequip_scores"]["reason"] = (
                    f"{correct_re}/{len(gt_uids & report_uids)} reequip scores correct"
                )
            total_score += c4_score
        else:
            eval_criteria["reequip_scores"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "No matching units to compare",
            }

        # ── Criterion 5: Correct sorting (10 pts) ──
        max_score += 10
        if report_rows and ground_truth:
            agent_order = [r.get("unit_id", "").strip() for r in report_rows]
            gt_order = [r["unit_id"] for r in ground_truth]
            # Check if report order matches ground truth order for overlapping units
            agent_order_filtered = [u for u in agent_order if u in gt_uids]
            gt_order_filtered = [u for u in gt_order if u in report_uids]
            if agent_order_filtered == gt_order_filtered and len(agent_order_filtered) > 0:
                eval_criteria["correct_sorting"] = {
                    "passed": True, "score": 10, "max_score": 10,
                }
                total_score += 10
            else:
                # Partial credit for mostly correct ordering (Kendall tau)
                if len(agent_order_filtered) > 1:
                    # Simple: count correctly ordered consecutive pairs
                    gt_rank = {u: i for i, u in enumerate(gt_order_filtered)}
                    correct_pairs = 0
                    total_pairs = 0
                    for i in range(len(agent_order_filtered)):
                        for j in range(i + 1, len(agent_order_filtered)):
                            total_pairs += 1
                            a_i = agent_order_filtered[i]
                            a_j = agent_order_filtered[j]
                            if a_i in gt_rank and a_j in gt_rank:
                                if gt_rank[a_i] < gt_rank[a_j]:
                                    correct_pairs += 1
                    ratio = correct_pairs / max(1, total_pairs)
                    c5_score = round(10 * ratio)
                else:
                    c5_score = 5
                eval_criteria["correct_sorting"] = {
                    "passed": False, "score": c5_score, "max_score": 10,
                    "reason": "Order does not match expected priority ranking",
                }
                total_score += c5_score
        else:
            eval_criteria["correct_sorting"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "No report data to check sorting",
            }

        # ── Criterion 6: Correct action labels (15 pts) ──
        max_score += 15
        if gt_uids and report_by_uid:
            correct_act = 0
            for uid in gt_uids & report_uids:
                agent_act = report_by_uid[uid].get("action_required", "").strip()
                if agent_act == gt_by_uid[uid]["action_required"]:
                    correct_act += 1
            n_overlap = len(gt_uids & report_uids)
            if n_overlap > 0:
                ratio = correct_act / n_overlap
            else:
                ratio = 0
            c6_score = round(15 * ratio)
            eval_criteria["correct_actions"] = {
                "passed": ratio == 1.0, "score": c6_score, "max_score": 15,
            }
            if ratio < 1.0:
                eval_criteria["correct_actions"]["reason"] = (
                    f"{correct_act}/{n_overlap} action labels correct"
                )
            total_score += c6_score
        else:
            eval_criteria["correct_actions"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "No matching units to compare",
            }

        # ── Criterion 7: Response mentions top 5 correctly (10 pts) ──
        max_score += 10
        if ground_truth and action:
            top5_gt = ground_truth[:5]
            found = 0
            for entry in top5_gt:
                # Check if unit_id or unit_name appears in response
                if entry["unit_id"] in action or entry["unit_name"] in action:
                    found += 1
            ratio = found / len(top5_gt) if top5_gt else 0
            c7_score = round(10 * ratio)
            eval_criteria["response_top5"] = {
                "passed": ratio == 1.0, "score": c7_score, "max_score": 10,
            }
            if ratio < 1.0:
                eval_criteria["response_top5"]["reason"] = (
                    f"Found {found}/{len(top5_gt)} top-5 units in response"
                )
            total_score += c7_score
        else:
            eval_criteria["response_top5"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "No ground truth or empty response",
            }

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ── Verify ────────────────────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as csv_mod

        # --- 1. Read config files from workspace ---
        with open(os.path.join(self.workspace, "audit_policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "certification_requirements.json"), "r") as f:
            cert_reqs = json.load(f)

        penalties = {}
        with open(os.path.join(self.workspace, "scoring_matrix.csv"), "r") as f:
            reader = csv_mod.DictReader(f)
            for row in reader:
                penalties[row["deficiency_type"]] = {
                    "penalty": int(row["penalty_points"]),
                    "category": row["category"],
                }

        thresholds = policy["thresholds"]
        audit_date = datetime.strptime(policy["audit_date"], "%Y-%m-%d")
        warning_cutoff = audit_date + timedelta(days=thresholds["cert_expiry_warning_days"])
        response_threshold = thresholds["response_time_minutes"]
        min_outcome = thresholds["min_outcome_rating"]
        min_condition = thresholds["min_equipment_condition"]
        retraining_factors = set(policy["scoring"]["retraining_factors"])
        reequip_factors = set(policy["scoring"]["reequip_factors"])
        violation_keywords = policy.get("protocol_violation_keywords", [])

        cert_level_order = {"basic": 0, "intermediate": 1, "advanced": 2, "specialist": 3}

        # --- 2. Read all transcript files and count violations per unit name ---
        violation_counts_by_name = {}  # unit_name -> count
        transcript_files = sorted(
            f for f in os.listdir(self.workspace)
            if f.startswith("dispatch_transcript_") and f.endswith(".txt")
        )
        for fname in transcript_files:
            with open(os.path.join(self.workspace, fname), "r") as f:
                lines = f.readlines()
            # First, extract dispatched unit names from header
            dispatched_names = []
            for line in lines:
                if line.startswith("Dispatched Units:"):
                    names_str = line.split(":", 1)[1].strip()
                    dispatched_names = [n.strip() for n in names_str.split(",")]
                    break
            # Build regex patterns for exact name matching
            name_patterns = {n: re.compile(r'\b' + re.escape(n) + r'\b') for n in dispatched_names}
            # Scan for violations
            for line in lines:
                line_lower = line.lower()
                for kw in violation_keywords:
                    if kw.lower() in line_lower:
                        for uname in dispatched_names:
                            if name_patterns[uname].search(line):
                                violation_counts_by_name[uname] = violation_counts_by_name.get(uname, 0) + 1
                        break  # one keyword per line

        # --- 3. List all units via tool ---
        all_units = []
        page = 1
        while True:
            result = json.loads(self.tools["list_units"](page=page)["content"][0]["text"])
            all_units.extend(result["units"])
            if page >= result["total_pages"]:
                break
            page += 1

        name_to_uid = {u["unit_name"]: u["unit_id"] for u in all_units}
        uid_to_name = {u["unit_id"]: u["unit_name"] for u in all_units}
        uid_to_type = {u["unit_id"]: u["unit_type"] for u in all_units}

        # Map violation counts to unit_ids
        violation_counts = {}
        for uname, count in violation_counts_by_name.items():
            uid = name_to_uid.get(uname)
            if uid:
                violation_counts[uid] = count

        # --- 4. For each unit, compute scores ---
        results = []
        for unit in all_units:
            uid = unit["unit_id"]
            ut = unit["unit_type"]
            scores = {
                "slow_response": 0,
                "certification_deficiency": 0,
                "poor_outcome": 0,
                "protocol_violation": 0,
                "overdue_maintenance": 0,
                "poor_equipment_condition": 0,
            }

            # 4a. Get dispatches and compute avg response time
            all_dispatches = []
            dp = 1
            while True:
                d_result = json.loads(self.tools["get_unit_dispatches"](unit_id=uid, page=dp))
                all_dispatches.extend(d_result["dispatches"])
                if dp >= d_result["total_pages"]:
                    break
                dp += 1

            if all_dispatches:
                response_times = []
                for d in all_dispatches:
                    dt = datetime.strptime(d["dispatch_time"], "%Y-%m-%d %H:%M:%S")
                    at = datetime.strptime(d["arrival_time"], "%Y-%m-%d %H:%M:%S")
                    rt = (at - dt).total_seconds() / 60.0
                    response_times.append(rt)
                avg_rt = sum(response_times) / len(response_times)
                if avg_rt > response_threshold:
                    scores["slow_response"] = penalties["slow_response"]["penalty"]

            # 4b. Check incident outcomes
            seen_incidents = set()
            for d in all_dispatches:
                iid = d["incident_id"]
                if iid in seen_incidents:
                    continue
                seen_incidents.add(iid)
                outcome = json.loads(self.tools["get_incident_outcome"](incident_id=iid))
                if "outcome" in outcome:
                    if outcome["outcome"]["outcome_rating"] < min_outcome:
                        scores["poor_outcome"] += penalties["poor_outcome"]["penalty"]

            # 4c. Get personnel and check certification
            pers_result = json.loads(self.tools["get_unit_personnel"](unit_id=uid))
            for p in pers_result["personnel"]:
                expiry = datetime.strptime(p["cert_expiry_date"], "%Y-%m-%d")
                required_level = cert_reqs.get(ut, {}).get(p["role"], "basic")
                is_expiring = expiry <= warning_cutoff
                is_underqualified = cert_level_order.get(p["certification_level"], 0) < cert_level_order.get(required_level, 0)
                if is_expiring or is_underqualified:
                    scores["certification_deficiency"] += penalties["certification_deficiency"]["penalty"]

            # 4d. Get equipment and check condition + maintenance
            eq_result = json.loads(self.tools["get_unit_equipment"](unit_id=uid)["content"][0]["text"])
            for eq in eq_result["equipment"]:
                if eq["condition_rating"] < min_condition:
                    scores["poor_equipment_condition"] += penalties["poor_equipment_condition"]["penalty"]

                maint_result = json.loads(self.tools["get_maintenance_history"](equipment_id=eq["equipment_id"])["content"][0]["text"])
                if maint_result["logs"]:
                    # Latest log is first (sorted desc by maintenance_date)
                    latest = maint_result["logs"][0]
                    ndd = datetime.strptime(latest["next_due_date"], "%Y-%m-%d")
                    if ndd < audit_date:
                        scores["overdue_maintenance"] += penalties["overdue_maintenance"]["penalty"]

            # 4e. Protocol violations
            n_violations = violation_counts.get(uid, 0)
            scores["protocol_violation"] = n_violations * penalties["protocol_violation"]["penalty"]

            # Compute category scores
            retraining_score = sum(scores[f] for f in retraining_factors if f in scores)
            reequip_score = sum(scores[f] for f in reequip_factors if f in scores)
            total = retraining_score + reequip_score

            if total > 0:
                if retraining_score > 0 and reequip_score > 0:
                    action = "RETRAIN_AND_RE-EQUIP"
                elif retraining_score > 0:
                    action = "RETRAIN"
                else:
                    action = "RE-EQUIP"

                results.append({
                    "unit_id": uid,
                    "unit_name": uid_to_name[uid],
                    "unit_type": ut,
                    "retraining_score": retraining_score,
                    "reequip_score": reequip_score,
                    "total_priority_score": total,
                    "action_required": action,
                })

        # Sort: total_priority_score desc, unit_id asc
        results.sort(key=lambda x: (-x["total_priority_score"], x["unit_id"]))

        # --- 5. Write priority_report.csv ---
        report_path = os.path.join(self.workspace, "priority_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(
                f,
                fieldnames=["unit_id", "unit_name", "unit_type", "retraining_score",
                            "reequip_score", "total_priority_score", "action_required"],
            )
            writer.writeheader()
            for r in results:
                writer.writerow(r)

        # --- 6. Build action string ---
        top5 = results[:5]
        top5_lines = []
        for r in top5:
            top5_lines.append(
                f"{r['unit_id']} ({r['unit_name']}): total_priority_score={r['total_priority_score']}, "
                f"retraining_score={r['retraining_score']}, reequip_score={r['reequip_score']}, "
                f"action={r['action_required']}"
            )

        action = (
            f"Audit complete. {len(results)} units flagged for action.\n\n"
            f"Top 5 highest-priority units:\n" + "\n".join(top5_lines) + "\n\n"
            f"Full results written to priority_report.csv."
        )

        return self.step(action)
