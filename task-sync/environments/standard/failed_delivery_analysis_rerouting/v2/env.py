"""
Environment for failed delivery rerouting analysis task.
"""
import sqlite3
import os
import json
import csv
import re
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

    # ----------------------------------------------------------------
    # Tool methods
    # ----------------------------------------------------------------

    @tool(
        description=(
            "Returns a paginated list of packages that have at least one failed "
            "delivery attempt and no successful delivery. Each page contains up "
            "to 10 results sorted by package_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)."
                }
            },
            "required": ["page"]
        }
    )
    def list_failed_packages(self, page: int) -> dict:
        page = int(page)
        per_page = 10
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT DISTINCT da.package_id, COUNT(*) as num_attempts
            FROM delivery_attempts da
            WHERE da.status = 'failed'
              AND da.package_id NOT IN (
                  SELECT package_id FROM delivery_attempts WHERE status = 'success'
              )
            GROUP BY da.package_id
            ORDER BY da.package_id
        """)
        all_rows = c.fetchall()
        conn.close()
        total = len(all_rows)
        total_pages = max(1, math.ceil(total / per_page))
        start = (page - 1) * per_page
        page_rows = all_rows[start:start + per_page]
        return {
            "packages": [
                {"package_id": r[0], "num_failed_attempts": r[1]}
                for r in page_rows
            ],
            "page": page,
            "total_pages": total_pages,
            "total_results": total
        }

    @tool(
        description="Returns detailed information about a specific package.",
        parameters={
            "type": "object",
            "properties": {
                "package_id": {
                    "type": "string",
                    "description": "The package identifier, e.g. PKG00001."
                }
            },
            "required": ["package_id"]
        }
    )
    def get_package_details(self, package_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM packages WHERE package_id = ?", (package_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Package {package_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Returns all delivery attempt records for a given package, "
            "ordered by attempt_date ascending."
        ),
        parameters={
            "type": "object",
            "properties": {
                "package_id": {
                    "type": "string",
                    "description": "The package identifier."
                }
            },
            "required": ["package_id"]
        }
    )
    def get_delivery_attempts(self, package_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM delivery_attempts WHERE package_id = ? ORDER BY attempt_date ASC",
            (package_id,)
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"attempts": rows, "count": len(rows)}

    @tool(
        description="Returns customer information for a given customer ID.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer identifier, e.g. C0001."
                }
            },
            "required": ["customer_id"]
        }
    )
    def get_customer_info(self, customer_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Customer {customer_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Returns performance metrics and certifications for a given driver."
        ),
        parameters={
            "type": "object",
            "properties": {
                "driver_id": {
                    "type": "string",
                    "description": "The driver identifier, e.g. D0001."
                }
            },
            "required": ["driver_id"]
        }
    )
    def get_driver_metrics(self, driver_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM drivers WHERE driver_id = ?", (driver_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Driver {driver_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Returns information about a neighborhood including security level "
            "and access characteristics."
        ),
        parameters={
            "type": "object",
            "properties": {
                "neighborhood_id": {
                    "type": "string",
                    "description": "The neighborhood identifier, e.g. N0001."
                }
            },
            "required": ["neighborhood_id"]
        }
    )
    def get_neighborhood_info(self, neighborhood_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM neighborhoods WHERE neighborhood_id = ?",
            (neighborhood_id,)
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Neighborhood {neighborhood_id} not found."}
        return dict(row)

    # ----------------------------------------------------------------
    # Helpers used by step() and verify()
    # ----------------------------------------------------------------

    def _load_policy(self) -> dict:
        with open(os.path.join(self.workspace, "rerouting_policy.json")) as f:
            return json.load(f)

    def _load_handling_matrix(self) -> dict:
        """Parse the handling_matrix.yaml into a dict keyed by handling code."""
        path = os.path.join(self.workspace, "handling_matrix.yaml")
        matrix = {}
        with open(path) as f:
            content = f.read()
        # Simple parser for our known YAML structure
        blocks = re.split(r'\n  (\w+):\n', content)
        # blocks[0] = "handling_codes:\n", then alternating key, body
        for i in range(1, len(blocks), 2):
            code = blocks[i]
            body = blocks[i + 1]
            entry = {}
            for line in body.strip().split("\n"):
                line = line.strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    entry[k.strip()] = v.strip().strip('"')
            matrix[code] = entry
        return matrix

    def _load_supervisor_flags(self) -> dict:
        """Load supervisor_priority_flag per attempt_id from delivery log CSVs."""
        flags = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("delivery_log_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        flags[row["attempt_id"]] = row["supervisor_priority_flag"]
        return flags

    def _load_customer_access(self) -> dict:
        """Load customer access instructions keyed by customer_id."""
        access = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("customer_access_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    records = json.load(f)
                for rec in records:
                    access[rec["customer_id"]] = rec
        return access

    def _load_neighborhood_bulletins(self) -> dict:
        """Load neighborhood bulletin data keyed by neighborhood_id."""
        bulletins = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("neighborhood_bulletin_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                for block in content.split("- neighborhood_id:"):
                    block = block.strip()
                    if not block:
                        continue
                    entry = {}
                    lines = ("neighborhood_id:" + block).split("\n")
                    for line in lines:
                        line = line.strip().lstrip("- ")
                        if ":" in line:
                            k, v = line.split(":", 1)
                            entry[k.strip()] = v.strip().strip('"')
                    nid = entry.get("neighborhood_id", "")
                    if nid:
                        bulletins[nid] = entry
        return bulletins

    def _load_driver_vehicles(self) -> dict:
        """Load driver vehicle types from driver_report TXT files."""
        vehicles = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("driver_report_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                for block in content.split("=== DRIVER REPORT ==="):
                    block = block.strip()
                    if not block:
                        continue
                    did = None
                    vtype = None
                    for line in block.split("\n"):
                        line = line.strip()
                        if line.startswith("Driver ID:"):
                            did = line.split(":", 1)[1].strip()
                        elif line.startswith("Vehicle Type:"):
                            vtype = line.split(":", 1)[1].strip()
                    if did and vtype:
                        vehicles[did] = vtype
        return vehicles

    def _compute_ground_truth(self):
        """Compute the full ground-truth rerouting list."""
        policy = self._load_policy()
        matrix = self._load_handling_matrix()
        flags = self._load_supervisor_flags()
        cust_access = self._load_customer_access()
        bulletins = self._load_neighborhood_bulletins()
        driver_vehicles = self._load_driver_vehicles()

        threshold = policy["high_value_threshold"]
        max_att = policy["max_reroute_attempts"]
        weights = policy["priority_weights"]
        sec_scores = policy["security_risk_scores"]
        hand_scores = policy["handling_complexity_scores"]
        urgent_bonus = policy["urgent_flag_bonus"]
        val_cap = policy["value_normalization_cap"]
        att_cap = policy["attempts_normalization_cap"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Find eligible packages
        c.execute("""
            SELECT da.package_id, COUNT(*) as num_att
            FROM delivery_attempts da
            WHERE da.status = 'failed'
              AND da.package_id NOT IN (
                  SELECT package_id FROM delivery_attempts WHERE status = 'success'
              )
            GROUP BY da.package_id
            HAVING COUNT(*) <= ?
        """, (max_att,))
        failed_pkgs = {r["package_id"]: r["num_att"] for r in c.fetchall()}

        results = []
        for pkg_id, num_att in failed_pkgs.items():
            c.execute("SELECT * FROM packages WHERE package_id = ?", (pkg_id,))
            pkg = dict(c.fetchone())
            if pkg["declared_value"] < threshold:
                continue

            c.execute("SELECT * FROM customers WHERE customer_id = ?",
                      (pkg["customer_id"],))
            cust = dict(c.fetchone())

            # Get the most recent failed attempt for neighborhood
            c.execute("""
                SELECT * FROM delivery_attempts
                WHERE package_id = ? AND status = 'failed'
                ORDER BY attempt_date DESC LIMIT 1
            """, (pkg_id,))
            last_att = dict(c.fetchone())
            nb_id = last_att["neighborhood_id"]

            c.execute("SELECT * FROM neighborhoods WHERE neighborhood_id = ?",
                      (nb_id,))
            nb = dict(c.fetchone())

            # Collect all attempt IDs for this package
            c.execute(
                "SELECT attempt_id FROM delivery_attempts WHERE package_id = ?",
                (pkg_id,)
            )
            att_ids = [r["attempt_id"] for r in c.fetchall()]

            # Collect unique failure reasons
            c.execute("""
                SELECT DISTINCT failure_reason FROM delivery_attempts
                WHERE package_id = ? AND failure_reason IS NOT NULL
                ORDER BY failure_reason
            """, (pkg_id,))
            failure_reasons = [r["failure_reason"] for r in c.fetchall()]

            # Check urgent flag
            has_urgent = any(
                flags.get(aid) == "urgent" for aid in att_ids
            )

            # Priority score
            norm_val = min(pkg["declared_value"] / val_cap, 1.0)
            norm_att = min(num_att / att_cap, 1.0)
            sec_score = sec_scores.get(nb["security_level"], 0.5)
            hand_score = hand_scores.get(pkg["handling_code"], 0.2)

            priority = (
                norm_val * weights["declared_value"]
                + norm_att * weights["failed_attempts"]
                + sec_score * weights["security_risk"]
                + hand_score * weights["handling_complexity"]
            )
            if has_urgent:
                priority += urgent_bonus
            priority = round(priority, 4)

            # Driver recommendation
            req_cert = matrix.get(pkg["handling_code"], {}).get(
                "required_certification", "standard"
            )
            req_vehicle = matrix.get(pkg["handling_code"], {}).get(
                "required_vehicle_type", "standard_truck"
            )
            handling_note = matrix.get(pkg["handling_code"], {}).get(
                "handling_note", "Standard handling procedures apply"
            )

            # Find best driver
            c.execute("SELECT * FROM drivers WHERE active_status = 1")
            all_drivers = [dict(r) for r in c.fetchall()]
            candidates = []
            for drv in all_drivers:
                certs = drv["certifications"].split(",")
                if req_cert not in certs:
                    continue
                vtype = driver_vehicles.get(drv["driver_id"], "")
                if vtype != req_vehicle:
                    continue
                candidates.append(drv)

            if candidates:
                candidates.sort(
                    key=lambda d: (-d["success_rate"], d["driver_id"])
                )
                best = candidates[0]
            else:
                # Fallback: cert match only, ignore vehicle
                fallback = [
                    d for d in all_drivers
                    if req_cert in d["certifications"].split(",")
                ]
                if fallback:
                    fallback.sort(
                        key=lambda d: (-d["success_rate"], d["driver_id"])
                    )
                    best = fallback[0]
                else:
                    best = {"driver_id": "NONE", "name": "NONE",
                            "success_rate": 0}

            # Special instructions
            ca = cust_access.get(pkg["customer_id"], {})
            access_parts = []
            if ca.get("gate_code"):
                access_parts.append(f"Gate code: {ca['gate_code']}")
            if ca.get("buzzer_info"):
                access_parts.append(f"Buzzer: {ca['buzzer_info']}")
            access_parts.append(
                f"Preferred spot: {ca.get('preferred_delivery_spot', 'front door')}"
            )
            access_str = ", ".join(access_parts)

            bulletin = bulletins.get(nb_id, {})
            safe_hours = bulletin.get("safe_delivery_hours", "08:00-18:00")

            special = (
                f"{handling_note} | Access: {access_str} | "
                f"Safe hours: {safe_hours}"
            )

            results.append({
                "package_id": pkg_id,
                "customer_name": cust["name"],
                "declared_value": pkg["declared_value"],
                "priority_score": priority,
                "num_failed_attempts": num_att,
                "failure_reasons": "; ".join(failure_reasons),
                "neighborhood_name": nb["name"],
                "security_level": nb["security_level"],
                "handling_code": pkg["handling_code"],
                "recommended_driver_id": best["driver_id"],
                "recommended_driver_name": best["name"],
                "special_instructions": special,
            })

        conn.close()

        # Sort: priority desc, package_id asc
        results.sort(key=lambda r: (-r["priority_score"], r["package_id"]))
        # Add rank
        for i, r in enumerate(results):
            r["rank"] = i + 1

        return results

    # ----------------------------------------------------------------
    # step
    # ----------------------------------------------------------------

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
        gt_ids = set(r["package_id"] for r in ground_truth)
        gt_map = {r["package_id"]: r for r in ground_truth}

        criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: File exists with correct columns (10 pts) ---
        csv_path = os.path.join(self.workspace, "rerouting_list.csv")
        expected_cols = [
            "rank", "package_id", "customer_name", "declared_value",
            "priority_score", "num_failed_attempts", "failure_reasons",
            "neighborhood_name", "security_level", "handling_code",
            "recommended_driver_id", "recommended_driver_name",
            "special_instructions"
        ]
        c1_score = 0
        c1_max = 10
        agent_rows = []
        if os.path.exists(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                agent_rows = list(reader)
            if set(expected_cols).issubset(set(cols)):
                c1_score = c1_max
            else:
                missing = set(expected_cols) - set(cols)
                c1_score = 5  # partial
                criteria["file_structure"] = {
                    "passed": False, "score": c1_score, "max_score": c1_max,
                    "reason": f"Missing columns: {missing}"
                }
        if "file_structure" not in criteria:
            criteria["file_structure"] = {
                "passed": c1_score == c1_max,
                "score": c1_score, "max_score": c1_max,
                "reason": "" if c1_score == c1_max else "rerouting_list.csv not found"
            }
        total_score += c1_score
        max_score += c1_max

        # --- Criterion 2: Correct eligible packages (20 pts) ---
        c2_max = 20
        agent_ids = set()
        for row in agent_rows:
            pid = row.get("package_id", "").strip()
            if pid:
                agent_ids.add(pid)
        if gt_ids and agent_ids:
            correct = agent_ids & gt_ids
            extra = agent_ids - gt_ids
            missing = gt_ids - agent_ids
            precision = len(correct) / len(agent_ids) if agent_ids else 0
            recall = len(correct) / len(gt_ids) if gt_ids else 0
            f1 = (2 * precision * recall / (precision + recall)
                   if (precision + recall) > 0 else 0)
            c2_score = round(c2_max * f1)
        elif not gt_ids and not agent_ids:
            c2_score = c2_max
        else:
            c2_score = 0
        criteria["eligible_packages"] = {
            "passed": c2_score == c2_max,
            "score": c2_score, "max_score": c2_max,
            "reason": ("" if c2_score == c2_max
                       else f"Expected {len(gt_ids)} packages, got {len(agent_ids)}")
        }
        total_score += c2_score
        max_score += c2_max

        # --- Criterion 3: Priority scores (20 pts) ---
        c3_max = 20
        c3_correct = 0
        c3_total = len(gt_ids)
        for row in agent_rows:
            pid = row.get("package_id", "").strip()
            if pid in gt_map:
                try:
                    agent_ps = round(float(row.get("priority_score", 0)), 4)
                    gt_ps = gt_map[pid]["priority_score"]
                    if abs(agent_ps - gt_ps) < 0.002:
                        c3_correct += 1
                except (ValueError, TypeError):
                    pass
        c3_score = round(c3_max * c3_correct / max(c3_total, 1))
        criteria["priority_scores"] = {
            "passed": c3_score == c3_max,
            "score": c3_score, "max_score": c3_max,
            "reason": ("" if c3_score == c3_max
                       else f"{c3_correct}/{c3_total} scores correct")
        }
        total_score += c3_score
        max_score += c3_max

        # --- Criterion 4: Sort order (10 pts) ---
        c4_max = 10
        agent_pids_ordered = [
            row.get("package_id", "").strip() for row in agent_rows
        ]
        gt_pids_ordered = [r["package_id"] for r in ground_truth]
        if agent_pids_ordered == gt_pids_ordered:
            c4_score = c4_max
        else:
            # Partial: check how many are in correct position
            matches = sum(
                1 for a, g in zip(agent_pids_ordered, gt_pids_ordered)
                if a == g
            )
            c4_score = round(c4_max * matches / max(len(gt_pids_ordered), 1))
        criteria["sort_order"] = {
            "passed": c4_score == c4_max,
            "score": c4_score, "max_score": c4_max,
            "reason": "" if c4_score == c4_max else "Incorrect sort order"
        }
        total_score += c4_score
        max_score += c4_max

        # --- Criterion 5: Driver recommendations (15 pts) ---
        c5_max = 15
        c5_correct = 0
        for row in agent_rows:
            pid = row.get("package_id", "").strip()
            if pid in gt_map:
                if (row.get("recommended_driver_id", "").strip()
                        == gt_map[pid]["recommended_driver_id"]):
                    c5_correct += 1
        c5_score = round(c5_max * c5_correct / max(c3_total, 1))
        criteria["driver_recommendations"] = {
            "passed": c5_score == c5_max,
            "score": c5_score, "max_score": c5_max,
            "reason": ("" if c5_score == c5_max
                       else f"{c5_correct}/{c3_total} drivers correct")
        }
        total_score += c5_score
        max_score += c5_max

        # --- Criterion 6: Special instructions (15 pts) ---
        c6_max = 15
        c6_correct = 0
        for row in agent_rows:
            pid = row.get("package_id", "").strip()
            if pid in gt_map:
                gt_si = gt_map[pid]["special_instructions"]
                agent_si = row.get("special_instructions", "").strip()
                # Check key components present
                if (gt_si.split(" | ")[0] in agent_si
                        and "Safe hours:" in agent_si):
                    c6_correct += 1
        c6_score = round(c6_max * c6_correct / max(c3_total, 1))
        criteria["special_instructions"] = {
            "passed": c6_score == c6_max,
            "score": c6_score, "max_score": c6_max,
            "reason": ("" if c6_score == c6_max
                       else f"{c6_correct}/{c3_total} instructions correct")
        }
        total_score += c6_score
        max_score += c6_max

        # --- Criterion 7: Response summary (10 pts) ---
        c7_max = 10
        c7_score = 0
        expected_count = len(ground_truth)
        expected_top_id = ground_truth[0]["package_id"] if ground_truth else ""
        expected_avg = round(
            sum(r["priority_score"] for r in ground_truth) / max(len(ground_truth), 1),
            4
        )
        action_lower = action.lower() if action else ""

        count_ok = str(expected_count) in action
        top_ok = expected_top_id.lower() in action_lower if expected_top_id else True
        # Check avg with some tolerance
        avg_ok = False
        for m in re.finditer(r'(\d+\.\d{2,4})', action):
            try:
                val = float(m.group(1))
                if abs(val - expected_avg) < 0.002:
                    avg_ok = True
                    break
            except ValueError:
                pass

        if count_ok:
            c7_score += 4
        if top_ok:
            c7_score += 3
        if avg_ok:
            c7_score += 3
        criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score, "max_score": c7_max,
            "reason": ("" if c7_score == c7_max
                       else f"count_ok={count_ok}, top_ok={top_ok}, avg_ok={avg_ok}")
        }
        total_score += c7_score
        max_score += c7_max

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, info

    # ----------------------------------------------------------------
    # verify
    # ----------------------------------------------------------------

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
        # 1. Load workspace config files
        with open(os.path.join(self.workspace, "rerouting_policy.json")) as f:
            policy = json.load(f)

        matrix = self._load_handling_matrix()
        cust_access = self._load_customer_access()
        bulletins = self._load_neighborhood_bulletins()
        driver_vehicles = self._load_driver_vehicles()
        sup_flags = self._load_supervisor_flags()

        threshold = policy["high_value_threshold"]
        max_att = policy["max_reroute_attempts"]
        weights = policy["priority_weights"]
        sec_scores = policy["security_risk_scores"]
        hand_scores = policy["handling_complexity_scores"]
        urgent_bonus_val = policy["urgent_flag_bonus"]
        val_cap = policy["value_normalization_cap"]
        att_cap = policy["attempts_normalization_cap"]

        # 2. List all failed packages via tool (paginate)
        failed_packages = []
        page = 1
        while True:
            result = self.tools["list_failed_packages"](page=page)
            failed_packages.extend(result["packages"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 3. For each, get details and filter
        driver_cache = {}  # (req_cert, req_vehicle) -> (primary, fallback)
        eligible = []
        for fp in failed_packages:
            pid = fp["package_id"]
            n_att = fp["num_failed_attempts"]
            if n_att > max_att:
                continue

            pkg = self.tools["get_package_details"](package_id=pid)
            if pkg.get("declared_value", 0) < threshold:
                continue

            # Get attempts
            att_result = self.tools["get_delivery_attempts"](package_id=pid)
            attempts = att_result["attempts"]

            # Get customer info
            cust = self.tools["get_customer_info"](customer_id=pkg["customer_id"])

            # Most recent failed attempt for neighborhood
            failed_atts = [a for a in attempts if a["status"] == "failed"]
            failed_atts.sort(key=lambda a: a["attempt_date"], reverse=True)
            last_att = failed_atts[0]
            nb_id = last_att["neighborhood_id"]

            nb = self.tools["get_neighborhood_info"](neighborhood_id=nb_id)

            # Failure reasons
            reasons = sorted(set(
                a["failure_reason"] for a in attempts
                if a["failure_reason"]
            ))

            # Check urgent flag from workspace
            att_ids = [a["attempt_id"] for a in attempts]
            has_urgent = any(sup_flags.get(aid) == "urgent" for aid in att_ids)

            # Priority score
            norm_val = min(pkg["declared_value"] / val_cap, 1.0)
            norm_att = min(n_att / att_cap, 1.0)
            sec_score = sec_scores.get(nb["security_level"], 0.5)
            hand_score = hand_scores.get(pkg["handling_code"], 0.2)

            priority = (
                norm_val * weights["declared_value"]
                + norm_att * weights["failed_attempts"]
                + sec_score * weights["security_risk"]
                + hand_score * weights["handling_complexity"]
            )
            if has_urgent:
                priority += urgent_bonus_val
            priority = round(priority, 4)

            # Driver recommendation using cached data
            req_cert = matrix.get(pkg["handling_code"], {}).get(
                "required_certification", "standard"
            )
            req_vehicle = matrix.get(pkg["handling_code"], {}).get(
                "required_vehicle_type", "standard_truck"
            )
            handling_note = matrix.get(pkg["handling_code"], {}).get(
                "handling_note", "Standard handling procedures apply"
            )

            # Use pre-cached driver data for this handling code
            cache_key = (req_cert, req_vehicle)
            if cache_key not in driver_cache:
                primary = []
                fallback = []
                for did, vtype in driver_vehicles.items():
                    drv = self.tools["get_driver_metrics"](driver_id=did)
                    if drv.get("error") or drv.get("active_status") != 1:
                        continue
                    certs = drv.get("certifications", "").split(",")
                    if req_cert not in certs:
                        continue
                    if vtype == req_vehicle:
                        primary.append(drv)
                    fallback.append(drv)
                primary.sort(key=lambda d: (-d["success_rate"], d["driver_id"]))
                fallback.sort(key=lambda d: (-d["success_rate"], d["driver_id"]))
                driver_cache[cache_key] = (primary, fallback)

            primary_candidates, fallback_candidates = driver_cache[cache_key]
            if primary_candidates:
                best = primary_candidates[0]
            elif fallback_candidates:
                best = fallback_candidates[0]
            else:
                best = {"driver_id": "NONE", "name": "NONE"}

            # Special instructions
            ca = cust_access.get(pkg["customer_id"], {})
            access_parts = []
            if ca.get("gate_code"):
                access_parts.append(f"Gate code: {ca['gate_code']}")
            if ca.get("buzzer_info"):
                access_parts.append(f"Buzzer: {ca['buzzer_info']}")
            access_parts.append(
                f"Preferred spot: {ca.get('preferred_delivery_spot', 'front door')}"
            )
            access_str = ", ".join(access_parts)

            bulletin = bulletins.get(nb_id, {})
            safe_hours = bulletin.get("safe_delivery_hours", "08:00-18:00")

            special = (
                f"{handling_note} | Access: {access_str} | "
                f"Safe hours: {safe_hours}"
            )

            eligible.append({
                "package_id": pid,
                "customer_name": cust["name"],
                "declared_value": pkg["declared_value"],
                "priority_score": priority,
                "num_failed_attempts": n_att,
                "failure_reasons": "; ".join(reasons),
                "neighborhood_name": nb["name"],
                "security_level": nb["security_level"],
                "handling_code": pkg["handling_code"],
                "recommended_driver_id": best["driver_id"],
                "recommended_driver_name": best["name"],
                "special_instructions": special,
            })

        # Sort
        eligible.sort(key=lambda r: (-r["priority_score"], r["package_id"]))
        for i, r in enumerate(eligible):
            r["rank"] = i + 1

        # Write rerouting_list.csv
        csv_path = os.path.join(self.workspace, "rerouting_list.csv")
        fieldnames = [
            "rank", "package_id", "customer_name", "declared_value",
            "priority_score", "num_failed_attempts", "failure_reasons",
            "neighborhood_name", "security_level", "handling_code",
            "recommended_driver_id", "recommended_driver_name",
            "special_instructions"
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in eligible:
                writer.writerow(r)

        # Build response summary
        total_rerouted = len(eligible)
        top_id = eligible[0]["package_id"] if eligible else "N/A"
        avg_score = round(
            sum(r["priority_score"] for r in eligible) / max(total_rerouted, 1),
            4
        )

        action = (
            f"Rerouting analysis complete. "
            f"Total packages rerouted: {total_rerouted}. "
            f"Highest priority package: {top_id}. "
            f"Average priority score: {avg_score}."
        )

        return self.step(action)
