import sqlite3
import os
import json
import csv
import glob
import math
from typing import Tuple, Dict, List, Any


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
        }
        return func
    return decorator


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

    # ========== Tool methods ==========

    @tool(
        description="Lists servers with optional filters. Returns paginated results (20 per page) with basic server info including server_id, hostname, datacenter, status, and server_type.",
        parameters={
            "type": "object",
            "properties": {
                "datacenter": {
                    "type": "string",
                    "description": "Filter by datacenter name (e.g., 'DC-EAST'). Omit to list all datacenters."
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "maintenance", "decommissioned"],
                    "description": "Filter by server status. Omit to list all statuses."
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1."
                }
            },
            "required": []
        }
    )
    def list_servers(self, datacenter: str = None, status: str = None, page: int = 1):
        page_size = 20
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        query = "SELECT server_id, hostname, datacenter, status, server_type FROM servers WHERE 1=1"
        params = []
        if datacenter:
            query += " AND datacenter = ?"
            params.append(datacenter)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY server_id"

        cur.execute(query, params)
        all_rows = cur.fetchall()
        conn.close()

        total = len(all_rows)
        total_pages = max(1, math.ceil(total / page_size))
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = all_rows[start:end]

        return json.dumps({
            "servers": [dict(r) for r in page_rows],
            "page": page,
            "total_pages": total_pages,
            "total_servers": total,
        }, ensure_ascii=False, default=str)

    @tool(
        description="Retrieves full details for a single server by its ID, including hardware specs, rack, OS, status, commission date, and server type.",
        parameters={
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "The server identifier (e.g., 'SRV-0001')."
                }
            },
            "required": ["server_id"]
        }
    )
    def get_server_details(self, server_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM servers WHERE server_id = ?", (server_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Server {server_id} not found."}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description="Returns 90-day CPU utilization summary statistics for a server: average, peak, minimum, p95, and standard deviation of daily average CPU percentages.",
        parameters={
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "The server identifier."
                }
            },
            "required": ["server_id"]
        }
    )
    def get_cpu_utilization_summary(self, server_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT avg_cpu_pct FROM cpu_utilization WHERE server_id = ? ORDER BY log_date",
            (server_id,)
        )
        rows = [r[0] for r in cur.fetchall()]
        conn.close()
        if not rows:
            return json.dumps({"error": f"No CPU data for {server_id}."}, ensure_ascii=False, default=str)
        import numpy as np
        arr = np.array(rows)
        return json.dumps({
            "server_id": server_id,
            "period_days": len(rows),
            "avg_cpu_pct": round(float(np.mean(arr)), 2),
            "peak_cpu_pct": round(float(np.max(arr)), 2),
            "min_cpu_pct": round(float(np.min(arr)), 2),
            "p95_cpu_pct": round(float(np.percentile(arr, 95)), 2),
            "std_cpu_pct": round(float(np.std(arr)), 2),
        }, ensure_ascii=False, default=str)

    @tool(
        description="Returns 90-day power consumption summary for a server: average watts, peak watts, minimum watts, and total energy in kWh.",
        parameters={
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "The server identifier."
                }
            },
            "required": ["server_id"]
        }
    )
    def get_power_consumption_summary(self, server_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT avg_watts, peak_watts FROM power_consumption WHERE server_id = ? ORDER BY reading_date",
            (server_id,)
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return _envelope({"error": f"No power data for {server_id}."})
        avg_vals = [r[0] for r in rows]
        peak_vals = [r[1] for r in rows]
        import numpy as np
        avg_arr = np.array(avg_vals)
        return _envelope({
            "server_id": server_id,
            "period_days": len(rows),
            "avg_watts": round(float(np.mean(avg_arr)), 2),
            "peak_watts": round(float(np.max(peak_vals)), 2),
            "min_watts": round(float(np.min(avg_arr)), 2),
            "total_kwh": round(float(np.sum(avg_arr) * 24 / 1000), 2),
        })

    @tool(
        description="Lists all virtual machines assigned to a given host server. Returns VM details including vcpus, RAM, disk, and status. Returns an empty list if the server is not a VM host.",
        parameters={
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "The host server identifier."
                }
            },
            "required": ["server_id"]
        }
    )
    def get_vm_allocation(self, server_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM vm_assignments WHERE host_server_id = ? ORDER BY vm_id",
            (server_id,)
        )
        rows = cur.fetchall()
        conn.close()
        return _envelope({"server_id": server_id, "vms": [dict(r) for r in rows]})

    @tool(
        description="Lists all services running on a given server, including service ID, name, criticality level, port, and protocol.",
        parameters={
            "type": "object",
            "properties": {
                "server_id": {
                    "type": "string",
                    "description": "The server identifier."
                }
            },
            "required": ["server_id"]
        }
    )
    def get_server_services(self, server_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM service_registry WHERE server_id = ? ORDER BY service_id",
            (server_id,)
        )
        rows = cur.fetchall()
        conn.close()
        return _envelope({"server_id": server_id, "services": [dict(r) for r in rows]})

    @tool(
        description="Retrieves details for a single service by its ID, including the server it runs on, criticality, port, and protocol.",
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "description": "The service identifier (e.g., 'SVC-0001')."
                }
            },
            "required": ["service_id"]
        }
    )
    def get_service_details(self, service_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM service_registry WHERE service_id = ?", (service_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Service {service_id} not found."}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    # ========== Evaluation ==========

    def _compute_ground_truth(self):
        """Compute the full ground-truth decommissioning schedule from DB + workspace."""
        import numpy as np

        # --- Read workspace config files ---
        # consolidation_policy.yaml (parse manually to avoid yaml dep)
        policy = {}
        with open(os.path.join(self.workspace, "consolidation_policy.yaml"), "r") as f:
            lines = f.read().strip().split("\n")

        # Simple YAML parser for our known structure
        current_dict = None
        current_key = None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not line.startswith(" ") and not line.startswith("\t"):
                # Top-level key
                if ":" in stripped:
                    key, _, val = stripped.partition(":")
                    key = key.strip()
                    val = val.strip()
                    if val:
                        try:
                            policy[key] = int(val)
                        except ValueError:
                            try:
                                policy[key] = float(val)
                            except ValueError:
                                policy[key] = val
                    else:
                        policy[key] = {}
                        current_key = key
            else:
                # Nested key
                if current_key and ":" in stripped:
                    k, _, v = stripped.partition(":")
                    k = k.strip()
                    v = v.strip()
                    try:
                        policy[current_key][k] = int(v)
                    except ValueError:
                        try:
                            policy[current_key][k] = float(v)
                        except ValueError:
                            policy[current_key][k] = v

        cpu_threshold = policy["cpu_threshold_pct"]
        power_factor = policy["power_utilization_factor"]
        crit_weights = policy["criticality_weights"]
        dep_weight = policy["dependency_weight"]
        vm_penalty = policy["vm_host_penalty"]
        phase_thresholds = policy["phase_thresholds"]

        # datacenter_config.json
        with open(os.path.join(self.workspace, "datacenter_config.json"), "r") as f:
            dc_config = json.load(f)

        # Read all server_specs files to get rated_power_watts
        rated_power = {}
        spec_files = sorted(glob.glob(os.path.join(self.workspace, "server_specs_batch_*.csv")))
        for sf in spec_files:
            with open(sf, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rated_power[row["server_id"]] = float(row["rated_power_watts"])

        # Read all service dependency files
        all_deps = {}
        dep_files = sorted(glob.glob(os.path.join(self.workspace, "service_deps_batch_*.json")))
        for df in dep_files:
            with open(df, "r") as f:
                batch = json.load(f)
                all_deps.update(batch)

        # Build reverse dependency map: service -> list of services that depend on it
        reverse_deps = {}
        for svc_id, dep_list in all_deps.items():
            for dep in dep_list:
                if dep not in reverse_deps:
                    reverse_deps[dep] = []
                reverse_deps[dep].append(svc_id)

        # --- Query DB for ground truth ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Get all active servers
        cur.execute("SELECT * FROM servers WHERE status = 'active' ORDER BY server_id")
        active_servers = [dict(r) for r in cur.fetchall()]

        # For each active server, compute 90-day avg CPU and avg power
        underutilized = []
        for srv in active_servers:
            sid = srv["server_id"]

            # CPU avg
            cur.execute("SELECT AVG(avg_cpu_pct) FROM cpu_utilization WHERE server_id = ?", (sid,))
            avg_cpu = cur.fetchone()[0]
            if avg_cpu is None:
                continue
            avg_cpu = round(avg_cpu, 2)

            # Power avg
            cur.execute("SELECT AVG(avg_watts) FROM power_consumption WHERE server_id = ?", (sid,))
            avg_power = cur.fetchone()[0]
            if avg_power is None:
                continue
            avg_power = round(avg_power, 2)

            # Check thresholds
            rated = rated_power.get(sid, 0)
            if avg_cpu < cpu_threshold and avg_power < rated * power_factor:
                # Get services
                cur.execute("SELECT * FROM service_registry WHERE server_id = ?", (sid,))
                svcs = [dict(r) for r in cur.fetchall()]

                # Compute migration priority score
                score = 0
                for svc in svcs:
                    score += crit_weights.get(svc["criticality"], 0)

                # Inbound dependency count
                for svc in svcs:
                    inbound = len(reverse_deps.get(svc["service_id"], []))
                    score += inbound * dep_weight

                # VM host penalty
                if srv["server_type"] == "vm_host":
                    score += vm_penalty

                # Assign phase
                p1 = phase_thresholds["phase_1_max"]
                p2 = phase_thresholds["phase_2_max"]
                p3 = phase_thresholds["phase_3_max"]
                if score <= p1:
                    phase = 1
                elif score <= p2:
                    phase = 2
                elif score <= p3:
                    phase = 3
                else:
                    phase = 4

                # Savings
                dc = srv["datacenter"]
                pue = dc_config[dc]["pue"]
                cost_kwh = dc_config[dc]["electricity_cost_per_kwh"]
                annual_savings = round((rated / 1000.0) * pue * cost_kwh * 8760, 2)

                underutilized.append({
                    "server_id": sid,
                    "hostname": srv["hostname"],
                    "datacenter": dc,
                    "avg_cpu_pct": avg_cpu,
                    "avg_power_watts": avg_power,
                    "rated_power_watts": rated,
                    "service_count": len(svcs),
                    "migration_priority_score": score,
                    "decommission_phase": phase,
                    "estimated_annual_savings_usd": annual_savings,
                })

        conn.close()

        # Sort: phase ASC, score ASC, server_id ASC
        underutilized.sort(key=lambda x: (x["decommission_phase"],
                                          x["migration_priority_score"],
                                          x["server_id"]))
        return underutilized

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
        gt_ids = set(r["server_id"] for r in ground_truth)
        gt_by_id = {r["server_id"]: r for r in ground_truth}

        eval_criteria = {}

        # --- Criterion 1: Correct identification of underutilized servers (20 pts) ---
        csv_path = os.path.join(self.workspace, "decommissioning_schedule.csv")
        submitted_rows = []
        submitted_ids = set()
        csv_exists = os.path.exists(csv_path)
        if csv_exists:
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    submitted_rows.append(row)
                    submitted_ids.add(row.get("server_id", ""))

        if not csv_exists:
            eval_criteria["server_identification"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "decommissioning_schedule.csv not found"
            }
        else:
            correct_ids = gt_ids & submitted_ids
            extra_ids = submitted_ids - gt_ids
            missing_ids = gt_ids - submitted_ids
            if correct_ids == gt_ids and not extra_ids:
                eval_criteria["server_identification"] = {
                    "passed": True, "score": 20, "max_score": 20
                }
            else:
                # Partial credit: proportion correct minus penalty for extras
                if len(gt_ids) > 0:
                    recall = len(correct_ids) / len(gt_ids)
                    precision = len(correct_ids) / max(1, len(submitted_ids))
                    f1 = 2 * recall * precision / max(0.001, recall + precision)
                    score = round(20 * f1)
                else:
                    score = 20 if len(submitted_ids) == 0 else 0
                eval_criteria["server_identification"] = {
                    "passed": False, "score": score, "max_score": 20,
                    "reason": f"Missing: {len(missing_ids)}, Extra: {len(extra_ids)}"
                }

        # --- Criterion 2: Correct CPU and power values (15 pts) ---
        if not csv_exists or not submitted_rows:
            eval_criteria["utilization_values"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "No CSV data"
            }
        else:
            correct_values = 0
            total_checks = 0
            for row in submitted_rows:
                sid = row.get("server_id", "")
                if sid in gt_by_id:
                    gt = gt_by_id[sid]
                    total_checks += 2
                    try:
                        if abs(float(row.get("avg_cpu_pct", -1)) - gt["avg_cpu_pct"]) < 0.1:
                            correct_values += 1
                    except (ValueError, TypeError):
                        pass
                    try:
                        if abs(float(row.get("avg_power_watts", -1)) - gt["avg_power_watts"]) < 1.0:
                            correct_values += 1
                    except (ValueError, TypeError):
                        pass

            if total_checks == 0:
                score_val = 0
            else:
                score_val = round(15 * correct_values / total_checks)
            eval_criteria["utilization_values"] = {
                "passed": score_val == 15, "score": score_val, "max_score": 15,
                "reason": f"{correct_values}/{total_checks} values correct" if score_val < 15 else ""
            }

        # --- Criterion 3: Correct migration priority scores (20 pts) ---
        if not csv_exists or not submitted_rows:
            eval_criteria["priority_scores"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "No CSV data"
            }
        else:
            correct_scores = 0
            correct_phases = 0
            matched = 0
            for row in submitted_rows:
                sid = row.get("server_id", "")
                if sid in gt_by_id:
                    matched += 1
                    gt = gt_by_id[sid]
                    try:
                        if abs(float(row.get("migration_priority_score", -1)) - gt["migration_priority_score"]) < 0.5:
                            correct_scores += 1
                    except (ValueError, TypeError):
                        pass
                    try:
                        if int(row.get("decommission_phase", -1)) == gt["decommission_phase"]:
                            correct_phases += 1
                    except (ValueError, TypeError):
                        pass

            if matched == 0:
                score_prio = 0
            else:
                pct_scores = correct_scores / matched
                pct_phases = correct_phases / matched
                score_prio = round(20 * (0.6 * pct_scores + 0.4 * pct_phases))

            eval_criteria["priority_scores"] = {
                "passed": score_prio == 20, "score": score_prio, "max_score": 20,
                "reason": f"Scores: {correct_scores}/{matched}, Phases: {correct_phases}/{matched}" if score_prio < 20 else ""
            }

        # --- Criterion 4: Correct annual savings (15 pts) ---
        if not csv_exists or not submitted_rows:
            eval_criteria["annual_savings"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "No CSV data"
            }
        else:
            correct_savings = 0
            matched_s = 0
            for row in submitted_rows:
                sid = row.get("server_id", "")
                if sid in gt_by_id:
                    matched_s += 1
                    gt = gt_by_id[sid]
                    try:
                        submitted_val = float(row.get("estimated_annual_savings_usd", -1))
                        if abs(submitted_val - gt["estimated_annual_savings_usd"]) < 0.5:
                            correct_savings += 1
                    except (ValueError, TypeError):
                        pass

            if matched_s == 0:
                score_sav = 0
            else:
                score_sav = round(15 * correct_savings / matched_s)

            eval_criteria["annual_savings"] = {
                "passed": score_sav == 15, "score": score_sav, "max_score": 15,
                "reason": f"{correct_savings}/{matched_s} savings correct" if score_sav < 15 else ""
            }

        # --- Criterion 5: Correct sort order and format (15 pts) ---
        expected_columns = [
            "server_id", "hostname", "datacenter", "avg_cpu_pct", "avg_power_watts",
            "rated_power_watts", "service_count", "migration_priority_score",
            "decommission_phase", "estimated_annual_savings_usd"
        ]
        if not csv_exists:
            eval_criteria["format_and_sorting"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "CSV not found"
            }
        else:
            fmt_score = 0
            # Check column names (5 pts)
            if submitted_rows:
                actual_cols = list(submitted_rows[0].keys())
                if actual_cols == expected_columns:
                    fmt_score += 5
                elif set(actual_cols) == set(expected_columns):
                    fmt_score += 2  # correct columns but wrong order

            # Check sort order (5 pts)
            if len(submitted_rows) > 1:
                sorted_ok = True
                for i in range(len(submitted_rows) - 1):
                    a = submitted_rows[i]
                    b = submitted_rows[i + 1]
                    try:
                        key_a = (int(a.get("decommission_phase", 0)),
                                 float(a.get("migration_priority_score", 0)),
                                 a.get("server_id", ""))
                        key_b = (int(b.get("decommission_phase", 0)),
                                 float(b.get("migration_priority_score", 0)),
                                 b.get("server_id", ""))
                        if key_a > key_b:
                            sorted_ok = False
                            break
                    except (ValueError, TypeError):
                        sorted_ok = False
                        break
                if sorted_ok:
                    fmt_score += 5
            elif len(submitted_rows) == 1:
                fmt_score += 5

            # Check decimal formatting (5 pts)
            decimal_ok = True
            for row in submitted_rows[:5]:  # check first 5 rows
                for col in ["avg_cpu_pct", "avg_power_watts", "estimated_annual_savings_usd"]:
                    val_str = row.get(col, "")
                    if val_str and "." in val_str:
                        decimal_part = val_str.split(".")[-1]
                        if len(decimal_part) != 2:
                            decimal_ok = False
                            break
                if not decimal_ok:
                    break
            if decimal_ok:
                fmt_score += 5

            eval_criteria["format_and_sorting"] = {
                "passed": fmt_score == 15, "score": fmt_score, "max_score": 15,
                "reason": "" if fmt_score == 15 else f"Format score: {fmt_score}/15"
            }

        # --- Criterion 6: Response summary (15 pts) ---
        import re
        action_lower = action.lower() if action else ""
        resp_score = 0

        # Check total count
        total_gt = len(ground_truth)
        count_match = re.search(r'total\s+underutilized[:\s]*(\d+)', action_lower)
        if count_match and int(count_match.group(1)) == total_gt:
            resp_score += 5
        else:
            # Try other patterns
            if str(total_gt) in action:
                # Check if the number appears near "underutilized" or "total"
                for m in re.finditer(r'\b' + str(total_gt) + r'\b', action):
                    context = action[max(0, m.start()-50):m.end()+50].lower()
                    if "underutilized" in context or "total" in context:
                        resp_score += 3
                        break

        # Check phase breakdown
        phase_counts = {}
        for r in ground_truth:
            p = r["decommission_phase"]
            phase_counts[p] = phase_counts.get(p, 0) + 1

        phase_correct = 0
        for phase_num, expected_count in phase_counts.items():
            pattern = rf'phase\s*{phase_num}[:\s]*(\d+)'
            match = re.search(pattern, action_lower)
            if match and int(match.group(1)) == expected_count:
                phase_correct += 1

        if phase_correct == len(phase_counts):
            resp_score += 5
        elif phase_correct > 0:
            resp_score += round(5 * phase_correct / len(phase_counts))

        # Check total savings
        total_savings = round(sum(r["estimated_annual_savings_usd"] for r in ground_truth), 2)
        savings_str = f"{total_savings:.2f}"
        # Look for the savings value in the response
        savings_found = False
        for m in re.finditer(r'[\$]?([\d,]+\.?\d*)', action):
            try:
                val = float(m.group(1).replace(",", ""))
                if abs(val - total_savings) < 1.0:
                    savings_found = True
                    break
            except ValueError:
                continue
        if savings_found:
            resp_score += 5

        eval_criteria["response_summary"] = {
            "passed": resp_score == 15, "score": resp_score, "max_score": 15,
            "reason": "" if resp_score == 15 else f"Response score: {resp_score}/15"
        }

        # --- Aggregate ---
        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return total_score / max_score, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import re as _re

        # Step 1: Read workspace configuration files
        with open(os.path.join(self.workspace, "consolidation_policy.yaml"), "r") as f:
            policy_text = f.read()

        # Parse policy
        policy = {}
        current_key = None
        for line in policy_text.strip().split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not line.startswith(" ") and not line.startswith("\t"):
                if ":" in stripped:
                    key, _, val = stripped.partition(":")
                    key = key.strip()
                    val = val.strip()
                    if val:
                        try:
                            policy[key] = int(val)
                        except ValueError:
                            try:
                                policy[key] = float(val)
                            except ValueError:
                                policy[key] = val
                    else:
                        policy[key] = {}
                        current_key = key
            else:
                if current_key and ":" in stripped:
                    k, _, v = stripped.partition(":")
                    k = k.strip()
                    v = v.strip()
                    try:
                        policy[current_key][k] = int(v)
                    except ValueError:
                        try:
                            policy[current_key][k] = float(v)
                        except ValueError:
                            policy[current_key][k] = v

        cpu_threshold = policy["cpu_threshold_pct"]
        power_factor = policy["power_utilization_factor"]
        crit_weights = policy["criticality_weights"]
        dep_weight = policy["dependency_weight"]
        vm_penalty = policy["vm_host_penalty"]
        phase_thresholds = policy["phase_thresholds"]

        with open(os.path.join(self.workspace, "datacenter_config.json"), "r") as f:
            dc_config = json.load(f)

        # Read server specs from workspace
        rated_power = {}
        spec_files = sorted(glob.glob(os.path.join(self.workspace, "server_specs_batch_*.csv")))
        for sf in spec_files:
            with open(sf, "r") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    rated_power[row["server_id"]] = float(row["rated_power_watts"])

        # Read service dependencies from workspace
        all_deps = {}
        dep_files = sorted(glob.glob(os.path.join(self.workspace, "service_deps_batch_*.json")))
        for df in dep_files:
            with open(df, "r") as fh:
                batch = json.load(fh)
                all_deps.update(batch)

        # Build reverse dependency map
        reverse_deps = {}
        for svc_id, dep_list in all_deps.items():
            for dep in dep_list:
                if dep not in reverse_deps:
                    reverse_deps[dep] = []
                reverse_deps[dep].append(svc_id)

        # Step 2: List all active servers via tools
        all_servers = []
        page = 1
        while True:
            result = json.loads(self.tools["list_servers"](status="active", page=page))
            all_servers.extend(result["servers"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 3: For each active server, get CPU utilization summary
        cpu_low_servers = []
        for srv in all_servers:
            sid = srv["server_id"]
            cpu_result = json.loads(self.tools["get_cpu_utilization_summary"](server_id=sid))
            if "error" in cpu_result:
                continue
            if cpu_result["avg_cpu_pct"] < cpu_threshold:
                cpu_low_servers.append({
                    "server_id": sid,
                    "hostname": srv["hostname"],
                    "datacenter": srv["datacenter"],
                    "server_type": srv["server_type"],
                    "avg_cpu_pct": cpu_result["avg_cpu_pct"],
                })

        # Step 4: For CPU-low servers, check power utilization
        underutilized = []
        for srv in cpu_low_servers:
            sid = srv["server_id"]
            power_result = json.loads(self.tools["get_power_consumption_summary"](server_id=sid)["content"][0]["text"])
            if "error" in power_result:
                continue
            rated = rated_power.get(sid, 0)
            if power_result["avg_watts"] < rated * power_factor:
                srv["avg_power_watts"] = power_result["avg_watts"]
                srv["rated_power_watts"] = rated
                underutilized.append(srv)

        # Step 5: For each underutilized server, get services and compute score
        for srv in underutilized:
            sid = srv["server_id"]
            svc_result = json.loads(self.tools["get_server_services"](server_id=sid)["content"][0]["text"])
            svcs = svc_result["services"]
            srv["service_count"] = len(svcs)

            # Compute migration priority score
            score = 0
            for svc in svcs:
                score += crit_weights.get(svc["criticality"], 0)
                inbound = len(reverse_deps.get(svc["service_id"], []))
                score += inbound * dep_weight

            if srv["server_type"] == "vm_host":
                score += vm_penalty

            srv["migration_priority_score"] = score

            # Assign phase
            p1 = phase_thresholds["phase_1_max"]
            p2 = phase_thresholds["phase_2_max"]
            p3 = phase_thresholds["phase_3_max"]
            if score <= p1:
                phase = 1
            elif score <= p2:
                phase = 2
            elif score <= p3:
                phase = 3
            else:
                phase = 4
            srv["decommission_phase"] = phase

            # Compute savings
            dc = srv["datacenter"]
            pue = dc_config[dc]["pue"]
            cost_kwh = dc_config[dc]["electricity_cost_per_kwh"]
            annual_savings = round((rated_power.get(sid, 0) / 1000.0) * pue * cost_kwh * 8760, 2)
            srv["estimated_annual_savings_usd"] = annual_savings

        # Sort: phase ASC, score ASC, server_id ASC
        underutilized.sort(key=lambda x: (x["decommission_phase"],
                                          x["migration_priority_score"],
                                          x["server_id"]))

        # Step 6: Write decommissioning_schedule.csv
        csv_path = os.path.join(self.workspace, "decommissioning_schedule.csv")
        columns = [
            "server_id", "hostname", "datacenter", "avg_cpu_pct", "avg_power_watts",
            "rated_power_watts", "service_count", "migration_priority_score",
            "decommission_phase", "estimated_annual_savings_usd"
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for srv in underutilized:
                writer.writerow([
                    srv["server_id"],
                    srv["hostname"],
                    srv["datacenter"],
                    f"{srv['avg_cpu_pct']:.2f}",
                    f"{srv['avg_power_watts']:.2f}",
                    f"{srv['rated_power_watts']:.2f}" if isinstance(srv['rated_power_watts'], float) else f"{srv['rated_power_watts']:.1f}0" if str(srv['rated_power_watts']).endswith('.0') else str(srv['rated_power_watts']),
                    srv["service_count"],
                    srv["migration_priority_score"],
                    srv["decommission_phase"],
                    f"{srv['estimated_annual_savings_usd']:.2f}",
                ])

        # Step 7: Build action string
        total_count = len(underutilized)
        phase_counts = {}
        for srv in underutilized:
            p = srv["decommission_phase"]
            phase_counts[p] = phase_counts.get(p, 0) + 1

        total_savings = round(sum(srv["estimated_annual_savings_usd"] for srv in underutilized), 2)

        action_parts = [f"Total underutilized: {total_count}"]
        for phase_num in sorted(phase_counts.keys()):
            action_parts.append(f"Phase {phase_num}: {phase_counts[phase_num]} servers")
        action_parts.append(f"Total annual savings: ${total_savings:.2f}")

        action = "\n".join(action_parts)

        return self.step(action)
