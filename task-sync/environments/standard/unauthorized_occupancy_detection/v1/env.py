"""
Task environment for unauthorized subletting / occupancy-violation detection.
"""

from typing import Tuple, Dict, List, Any
import sqlite3
import os
import json
import csv
import yaml


# ---------------------------------------------------------------------------
# Tool decorator
# ---------------------------------------------------------------------------

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ---------------------------------------------------------------------------
# Task_Env
# ---------------------------------------------------------------------------

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

    # ==================================================================
    # TOOL METHODS
    # ==================================================================

    @tool(
        description=(
            "List all residential units with pagination.  Returns unit IDs, "
            "building, floor, bedroom count, and unit type."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Units per page (default 10, max 20).",
                },
            },
            "required": ["page"],
        },
    )
    def list_units(self, page: int, page_size: int = 10) -> dict:
        page_size = min(int(page_size), 20)
        page = int(page)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM units").fetchone()[0]
        total_pages = (total + page_size - 1) // page_size
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT * FROM units ORDER BY unit_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "units": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_units": total,
        }

    @tool(
        description=(
            "Get lease agreement details for a specific unit, including "
            "tenant name, lease period, maximum allowed occupants, "
            "subletting policy, and monthly rent."
        ),
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {
                    "type": "string",
                    "description": "Unit identifier, e.g. 'U0001'.",
                },
            },
            "required": ["unit_id"],
        },
    )
    def get_lease_info(self, unit_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM leases WHERE unit_id = ?", (unit_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"No lease found for unit {unit_id}"}
        d = dict(row)
        d["subletting_allowed"] = bool(d["subletting_allowed"])
        return d

    @tool(
        description=(
            "Get the list of occupants registered on the lease for a "
            "specific unit."
        ),
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {
                    "type": "string",
                    "description": "Unit identifier, e.g. 'U0001'.",
                },
            },
            "required": ["unit_id"],
        },
    )
    def get_registered_occupants(self, unit_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT occupant_name, is_primary "
            "FROM registered_occupants WHERE unit_id = ?",
            (unit_id,),
        ).fetchall()
        conn.close()
        return {
            "unit_id": unit_id,
            "occupants": [
                {"name": r["occupant_name"], "is_primary": bool(r["is_primary"])}
                for r in rows
            ],
            "count": len(rows),
        }

    @tool(
        description=(
            "Retrieve all complaints filed against a specific unit, "
            "including category, date, reporting unit, description, "
            "and current status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {
                    "type": "string",
                    "description": "Target unit identifier, e.g. 'U0001'.",
                },
            },
            "required": ["unit_id"],
        },
    )
    def get_complaints_for_unit(self, unit_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM complaints WHERE target_unit = ? ORDER BY date",
            (unit_id,),
        ).fetchall()
        conn.close()
        return {
            "unit_id": unit_id,
            "complaints": [dict(r) for r in rows],
            "count": len(rows),
        }

    # ==================================================================
    # GROUND TRUTH
    # ==================================================================

    def _compute_ground_truth(self) -> List[dict]:
        """Return the deterministic list of flagged units (sorted)."""
        # Read policy from workspace
        policy_path = os.path.join(self.workspace, "investigation_policy.yaml")
        with open(policy_path) as _f:
            policy = yaml.safe_load(_f)

        crit = policy["investigation_criteria"]
        threshold = int(policy["investigation_threshold"])

        elec_thresh = float(crit["high_electricity"]["threshold_kwh_per_occupant"])
        elec_pts    = int(crit["high_electricity"]["score"])
        water_thresh = float(crit["high_water"]["threshold_gallons_per_occupant"])
        water_pts    = int(crit["high_water"]["score"])
        card_mult    = float(crit["excess_access_cards"]["multiplier"])
        card_pts     = int(crit["excess_access_cards"]["score"])
        concern_cats = set(crit["complaint_signals"]["categories_of_concern"])
        comp_per     = int(crit["complaint_signals"]["score_per_complaint"])
        comp_max     = int(crit["complaint_signals"]["max_score"])
        subl_pts     = int(crit["subletting_prohibited"]["score"])

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        units = conn.execute("SELECT * FROM units ORDER BY unit_id").fetchall()

        results = []
        for unit in units:
            uid = unit["unit_id"]

            # Lease
            lease = conn.execute(
                "SELECT * FROM leases WHERE unit_id = ?", (uid,)
            ).fetchone()
            max_occ = lease["max_occupants"]
            subl_allowed = bool(lease["subletting_allowed"])

            # Utility averages
            util = conn.execute(
                "SELECT AVG(electricity_kwh) AS avg_e, "
                "       AVG(water_gallons)   AS avg_w "
                "FROM utility_readings WHERE unit_id = ?",
                (uid,),
            ).fetchone()
            avg_e = float(util["avg_e"] or 0)
            avg_w = float(util["avg_w"] or 0)

            # Unique access cards
            cards = conn.execute(
                "SELECT COUNT(DISTINCT card_id) AS n "
                "FROM access_logs WHERE unit_id = ?",
                (uid,),
            ).fetchone()
            n_cards = int(cards["n"])

            # Concern-category complaints
            placeholders = ",".join("?" * len(concern_cats))
            comps = conn.execute(
                f"SELECT COUNT(*) AS n FROM complaints "
                f"WHERE target_unit = ? AND category IN ({placeholders})",
                (uid, *concern_cats),
            ).fetchone()
            n_concern = int(comps["n"])

            # Score
            signals = []
            score = 0

            if avg_e > elec_thresh * max_occ:
                signals.append("high_electricity")
                score += elec_pts
            if avg_w > water_thresh * max_occ:
                signals.append("high_water")
                score += water_pts
            if n_cards > card_mult * max_occ:
                signals.append("excess_access_cards")
                score += card_pts
            comp_val = min(n_concern * comp_per, comp_max)
            if comp_val > 0:
                signals.append("complaint_signals")
                score += comp_val
            if not subl_allowed and len(signals) > 0:
                signals.append("subletting_prohibited")
                score += subl_pts

            if score >= threshold:
                signals.sort()
                results.append({
                    "unit_id": uid,
                    "total_score": score,
                    "signals": "; ".join(signals),
                    "subletting_allowed": "yes" if subl_allowed else "no",
                })

        conn.close()

        results.sort(key=lambda x: (-x["total_score"], x["unit_id"]))
        return results

    # ==================================================================
    # STEP  (evaluation)
    # ==================================================================

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
        gt_units = set(r["unit_id"] for r in ground_truth)
        gt_dict = {r["unit_id"]: r for r in ground_truth}

        eval_criteria: Dict[str, dict] = {}

        # ---- 1. Report file exists with correct columns (10 pts) ----
        report_path = os.path.join(self.workspace, "investigation_report.csv")
        report_exists = os.path.exists(report_path)
        report_data: List[dict] = []
        correct_columns = False

        if report_exists:
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = set(reader.fieldnames or [])
                    report_data = list(reader)
                    correct_columns = {"unit_id", "total_score", "signals",
                                       "subletting_allowed"}.issubset(cols)
            except Exception:
                pass

        eval_criteria["report_format"] = {
            "passed": report_exists and correct_columns,
            "score": 10 if (report_exists and correct_columns) else 0,
            "max_score": 10,
            "reason": ("" if (report_exists and correct_columns)
                       else "investigation_report.csv missing or has wrong columns"),
        }

        # ---- 2. Precision of flagged units (15 pts) ----
        reported_units = set(r["unit_id"] for r in report_data)
        if reported_units:
            precision = len(reported_units & gt_units) / len(reported_units)
        else:
            precision = 0.0 if gt_units else 1.0
        prec_pts = round(15 * precision)
        eval_criteria["flagged_precision"] = {
            "passed": precision == 1.0,
            "score": prec_pts,
            "max_score": 15,
            "reason": "" if precision == 1.0 else f"precision={precision:.3f}",
        }

        # ---- 3. Recall of flagged units (15 pts) ----
        if gt_units:
            recall = len(reported_units & gt_units) / len(gt_units)
        else:
            recall = 1.0 if not reported_units else 0.0
        rec_pts = round(15 * recall)
        eval_criteria["flagged_recall"] = {
            "passed": recall == 1.0,
            "score": rec_pts,
            "max_score": 15,
            "reason": "" if recall == 1.0 else f"recall={recall:.3f}",
        }

        # ---- 4. Correct total_score values (20 pts) ----
        report_dict = {r["unit_id"]: r for r in report_data}
        n_check = len(gt_units)
        correct_scores = 0
        for uid in gt_units:
            if uid in report_dict:
                try:
                    if int(report_dict[uid]["total_score"]) == gt_dict[uid]["total_score"]:
                        correct_scores += 1
                except (ValueError, KeyError):
                    pass
        score_ratio = correct_scores / n_check if n_check else 1.0
        sc_pts = round(20 * score_ratio)
        eval_criteria["correct_scores"] = {
            "passed": score_ratio == 1.0,
            "score": sc_pts,
            "max_score": 20,
            "reason": ("" if score_ratio == 1.0
                       else f"correct {correct_scores}/{n_check}"),
        }

        # ---- 5. Correct signals strings (15 pts) ----
        correct_sigs = 0
        for uid in gt_units:
            if uid in report_dict:
                gt_parts = sorted(
                    s.strip() for s in gt_dict[uid]["signals"].split(";"))
                rp_parts = sorted(
                    s.strip()
                    for s in report_dict[uid].get("signals", "").split(";"))
                if gt_parts == rp_parts:
                    correct_sigs += 1
        sig_ratio = correct_sigs / n_check if n_check else 1.0
        sig_pts = round(15 * sig_ratio)
        eval_criteria["correct_signals"] = {
            "passed": sig_ratio == 1.0,
            "score": sig_pts,
            "max_score": 15,
            "reason": ("" if sig_ratio == 1.0
                       else f"correct {correct_sigs}/{n_check}"),
        }

        # ---- 6. Sort order (10 pts) ----
        sort_ok = False
        if len(report_data) == len(ground_truth) and len(ground_truth) > 0:
            try:
                sort_ok = all(
                    report_data[j]["unit_id"] == ground_truth[j]["unit_id"]
                    for j in range(len(ground_truth))
                )
            except (IndexError, KeyError):
                pass
        elif not ground_truth and not report_data:
            sort_ok = True
        eval_criteria["sort_order"] = {
            "passed": sort_ok,
            "score": 10 if sort_ok else 0,
            "max_score": 10,
            "reason": ("" if sort_ok
                       else "rows not sorted by total_score desc / unit_id asc"),
        }

        # ---- 7. Response mentions all flagged units (15 pts) ----
        resp_ok = False
        resp_pts = 0
        if action and gt_units:
            found = sum(1 for uid in gt_units if uid in action)
            ratio = found / len(gt_units)
            resp_pts = round(15 * ratio)
            resp_ok = ratio == 1.0
        elif not gt_units:
            resp_pts = 15
            resp_ok = True
        eval_criteria["response_units"] = {
            "passed": resp_ok,
            "score": resp_pts,
            "max_score": 15,
            "reason": ("" if resp_ok
                       else "not all flagged unit IDs appear in the response"),
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ==================================================================
    # VERIFY  (self-test)
    # ==================================================================

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
        # 1. Read investigation policy
        policy_path = os.path.join(self.workspace, "investigation_policy.yaml")
        with open(policy_path) as _f:
            policy = yaml.safe_load(_f)

        crit = policy["investigation_criteria"]
        threshold = int(policy["investigation_threshold"])

        elec_thresh = float(crit["high_electricity"]["threshold_kwh_per_occupant"])
        elec_pts    = int(crit["high_electricity"]["score"])
        water_thresh = float(crit["high_water"]["threshold_gallons_per_occupant"])
        water_pts    = int(crit["high_water"]["score"])
        card_mult    = float(crit["excess_access_cards"]["multiplier"])
        card_pts     = int(crit["excess_access_cards"]["score"])
        concern_cats = set(crit["complaint_signals"]["categories_of_concern"])
        comp_per     = int(crit["complaint_signals"]["score_per_complaint"])
        comp_max     = int(crit["complaint_signals"]["max_score"])
        subl_pts     = int(crit["subletting_prohibited"]["score"])

        # 2. Read utility data from workspace CSVs
        utility_data: Dict[str, list] = {}   # uid -> list of readings
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("utility_bills_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname), newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        uid = row["unit_id"]
                        utility_data.setdefault(uid, []).append({
                            "electricity_kwh": float(row["electricity_kwh"]),
                            "water_gallons": float(row["water_gallons"]),
                        })

        # 3. Read access card data from workspace JSONs
        access_data: Dict[str, int] = {}   # uid -> unique card count
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("access_card_report_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    records = json.load(f)
                    for rec in records:
                        access_data[rec["unit_id"]] = rec["unique_access_cards"]

        # 4. Get all units via tool (paginated)
        all_units: list = []
        page = 1
        while True:
            result = self.tools["list_units"](page=page)
            all_units.extend(result["units"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 5. For each unit, get lease and complaints via tools, score
        flagged: list = []

        for unit in all_units:
            uid = unit["unit_id"]

            lease = self.tools["get_lease_info"](unit_id=uid)
            max_occ = lease["max_occupants"]
            subl_allowed = lease["subletting_allowed"]

            comps_result = self.tools["get_complaints_for_unit"](unit_id=uid)
            complaints = comps_result["complaints"]

            signals = []
            score = 0

            # Utility signals
            if uid in utility_data:
                readings = utility_data[uid]
                avg_e = sum(r["electricity_kwh"] for r in readings) / len(readings)
                avg_w = sum(r["water_gallons"] for r in readings) / len(readings)
                if avg_e > elec_thresh * max_occ:
                    signals.append("high_electricity")
                    score += elec_pts
                if avg_w > water_thresh * max_occ:
                    signals.append("high_water")
                    score += water_pts

            # Access card signal
            if uid in access_data:
                if access_data[uid] > card_mult * max_occ:
                    signals.append("excess_access_cards")
                    score += card_pts

            # Complaint signal
            n_concern = sum(
                1 for c in complaints if c["category"] in concern_cats
            )
            comp_val = min(n_concern * comp_per, comp_max)
            if comp_val > 0:
                signals.append("complaint_signals")
                score += comp_val

            # Subletting-prohibited bonus
            if not subl_allowed and len(signals) > 0:
                signals.append("subletting_prohibited")
                score += subl_pts

            if score >= threshold:
                signals.sort()
                flagged.append({
                    "unit_id": uid,
                    "total_score": score,
                    "signals": "; ".join(signals),
                    "subletting_allowed": "yes" if subl_allowed else "no",
                })

        # Sort: total_score desc, unit_id asc
        flagged.sort(key=lambda x: (-x["total_score"], x["unit_id"]))

        # 6. Write investigation_report.csv
        report_path = os.path.join(self.workspace, "investigation_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["unit_id", "total_score", "signals",
                            "subletting_allowed"],
            )
            writer.writeheader()
            writer.writerows(flagged)

        # 7. Construct action string
        unit_list = ", ".join(r["unit_id"] for r in flagged)
        action = f"Units requiring formal investigation: {unit_list}"

        return self.step(action)
