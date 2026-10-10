"""
Environment for container load planning optimization task.
"""

import os
import re
import json
import csv
import sqlite3
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


# Port discharge order: BRAVO=1 (first discharge), CHARLIE=2, DELTA=3
PORT_ORDER = {"BRAVO": 1, "CHARLIE": 2, "DELTA": 3}


def _compute_rehandles(plan_rows, container_dest_map):
    """
    Compute total re-handling events for a loading plan.
    plan_rows: list of dicts with keys container_id, bay, tier, row
    container_dest_map: dict container_id -> destination_port
    Returns int count of re-handles.
    """
    # Group by (bay, row) stacks
    stacks = {}
    for r in plan_rows:
        key = (int(r["bay"]), int(r["row"]))
        stacks.setdefault(key, []).append(r)

    total = 0
    for key, stack in stacks.items():
        stack_sorted = sorted(stack, key=lambda x: int(x["tier"]))
        for i, entry in enumerate(stack_sorted):
            cid = entry["container_id"]
            dest = container_dest_map.get(cid, "")
            dest_order = PORT_ORDER.get(dest, 99)
            # Count containers above with later discharge
            for j in range(i + 1, len(stack_sorted)):
                above_cid = stack_sorted[j]["container_id"]
                above_dest = container_dest_map.get(above_cid, "")
                above_order = PORT_ORDER.get(above_dest, 99)
                if above_order > dest_order:
                    total += 1
    return total


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
    # TOOLS
    # ================================================================

    @tool(
        description="Lists containers in the cargo manifest with pagination. Returns container_id, container_type, weight_tons, destination_port, hazmat_class, and is_reefer for each container. Results are sorted by container_id.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of containers per page (max 8).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_containers(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 8)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM containers").fetchone()[0]
        rows = conn.execute(
            "SELECT container_id, container_type, weight_tons, destination_port, "
            "hazmat_class, is_reefer FROM containers ORDER BY container_id "
            "LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "containers": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total_containers": total,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description="Retrieves full details for a single container including dimensions, owner, and all attributes.",
        parameters={
            "type": "object",
            "properties": {
                "container_id": {
                    "type": "string",
                    "description": "The container identifier, e.g. CTN0001.",
                },
            },
            "required": ["container_id"],
        },
    )
    def get_container_details(self, container_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM containers WHERE container_id = ?", (container_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Container {container_id} not found."}
        return dict(row)

    @tool(
        description="Returns all stowage cells in a given bay, including cell_id, tier, row_number, max_weight_tons, is_reefer_slot, and cell_size.",
        parameters={
            "type": "object",
            "properties": {
                "bay_number": {
                    "type": "integer",
                    "description": "Bay number to query.",
                },
            },
            "required": ["bay_number"],
        },
    )
    def get_bay_cells(self, bay_number: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM stowage_cells WHERE bay_number = ? ORDER BY tier, row_number",
            (bay_number,),
        ).fetchall()
        conn.close()
        return {
            "bay_number": bay_number,
            "cells": [dict(r) for r in rows],
        }

    @tool(
        description="Lists current loading plan assignments with pagination. Returns container_id, cell_id, bay_number, tier, and row_number for each assignment. Sorted by assignment_id.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of assignments per page (max 8).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def get_current_plan(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 8)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM current_assignments").fetchone()[0]
        rows = conn.execute(
            "SELECT container_id, cell_id, bay_number, tier, row_number "
            "FROM current_assignments ORDER BY assignment_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "assignments": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total_assignments": total,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description="Returns all land-transport bookings for containers discharging at the specified port, including booking_id, container_id, vehicle_type, pickup_datetime, and deadline_datetime.",
        parameters={
            "type": "object",
            "properties": {
                "port_code": {
                    "type": "string",
                    "description": "Port code, e.g. BRAVO, CHARLIE, DELTA.",
                },
            },
            "required": ["port_code"],
        },
    )
    def get_transport_bookings(self, port_code: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM transport_bookings WHERE port_code = ? ORDER BY booking_id",
            (port_code,),
        ).fetchall()
        conn.close()
        return {
            "port_code": port_code,
            "bookings": [dict(r) for r in rows],
        }

    # ================================================================
    # EVALUATION
    # ================================================================

    def _load_ground_truth(self):
        """Load all data needed for evaluation."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        containers = {
            r["container_id"]: dict(r)
            for r in conn.execute("SELECT * FROM containers").fetchall()
        }
        cells = {
            r["cell_id"]: dict(r)
            for r in conn.execute("SELECT * FROM stowage_cells").fetchall()
        }
        current = [
            dict(r)
            for r in conn.execute("SELECT * FROM current_assignments").fetchall()
        ]
        conn.close()

        # Read vessel spec
        with open(os.path.join(self.workspace, "vessel_spec.json")) as f:
            vessel = json.load(f)

        # Read temp control from cargo batch files
        temp_control_set = set()
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("cargo_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if str(row["requires_temp_control"]).strip().lower() == "true":
                            temp_control_set.add(row["container_id"])

        # Determine all containers needing reefer
        needs_reefer = set()
        for cid, c in containers.items():
            if c["is_reefer"] == 1 or cid in temp_control_set:
                needs_reefer.add(cid)

        return containers, cells, current, vessel, needs_reefer

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
        containers, cells, current_plan, vessel, needs_reefer = self._load_ground_truth()
        bay_weight_limit = vessel["bay_weight_limit_tons"]

        info = {"eval_criteria": {}}
        total_score = 0.0
        max_score = 0.0

        # Helper to add a criterion
        def add_criterion(name, passed, score, ms, reason=""):
            nonlocal total_score, max_score
            entry = {"passed": passed, "score": round(score, 2), "max_score": ms}
            if not passed and reason:
                entry["reason"] = reason
            info["eval_criteria"][name] = entry
            total_score += score
            max_score += ms

        # --- Criterion 1: file_format (10 pts) ---
        plan_path = os.path.join(self.workspace, "revised_plan.csv")
        plan_rows = []
        required_cols = {"container_id", "cell_id", "bay", "tier", "row"}
        c1_ok = False
        c1_reason = ""
        if not os.path.exists(plan_path):
            c1_reason = "revised_plan.csv not found"
        else:
            try:
                with open(plan_path) as f:
                    reader = csv.DictReader(f)
                    if not required_cols.issubset(set(reader.fieldnames or [])):
                        c1_reason = f"Missing columns. Expected {required_cols}, got {set(reader.fieldnames or [])}"
                    else:
                        for row in reader:
                            plan_rows.append(row)
                        if len(plan_rows) == 0:
                            c1_reason = "File has no data rows"
                        else:
                            c1_ok = True
            except Exception as e:
                c1_reason = f"Error reading file: {e}"

        add_criterion("file_format", c1_ok, 10 if c1_ok else 0, 10, c1_reason)

        if not c1_ok:
            # Can't evaluate further
            for name, ms in [
                ("assignment_validity", 15),
                ("weight_constraints", 15),
                ("reefer_compliance", 15),
                ("hazmat_compliance", 15),
                ("rehandle_improvement", 15),
                ("response_metrics", 15),
            ]:
                add_criterion(name, False, 0, ms, "Cannot evaluate: plan file missing/malformed")
            info["total_score"] = round(total_score, 2)
            info["max_score"] = round(max_score, 2)
            return total_score / max_score, info

        # --- Criterion 2: assignment_validity (15 pts) ---
        all_cids = set(containers.keys())
        plan_cids = [r["container_id"] for r in plan_rows]
        plan_cellids = [r["cell_id"] for r in plan_rows]

        dup_containers = len(plan_cids) - len(set(plan_cids))
        dup_cells = len(plan_cellids) - len(set(plan_cellids))
        missing_containers = all_cids - set(plan_cids)
        extra_containers = set(plan_cids) - all_cids

        # Type matching
        type_mismatches = 0
        for r in plan_rows:
            cid = r["container_id"]
            cellid = r["cell_id"]
            if cid in containers and cellid in cells:
                if containers[cid]["container_type"] != cells[cellid]["cell_size"]:
                    type_mismatches += 1

        violations_2 = dup_containers + dup_cells + len(missing_containers) + len(extra_containers) + type_mismatches
        c2_score = 15 * max(0, 1 - violations_2 / max(1, len(all_cids)))
        c2_reason = ""
        if violations_2 > 0:
            parts = []
            if dup_containers:
                parts.append(f"{dup_containers} duplicate containers")
            if dup_cells:
                parts.append(f"{dup_cells} duplicate cells")
            if missing_containers:
                parts.append(f"{len(missing_containers)} missing containers")
            if extra_containers:
                parts.append(f"{len(extra_containers)} extra containers")
            if type_mismatches:
                parts.append(f"{type_mismatches} type mismatches")
            c2_reason = "; ".join(parts)
        add_criterion("assignment_validity", violations_2 == 0, c2_score, 15, c2_reason)

        # --- Criterion 3: weight_constraints (15 pts) ---
        # 3a: cell max_weight (7.5 pts)
        cell_violations = 0
        for r in plan_rows:
            cid = r["container_id"]
            cellid = r["cell_id"]
            if cid in containers and cellid in cells:
                if containers[cid]["weight_tons"] > cells[cellid]["max_weight_tons"]:
                    cell_violations += 1

        # 3b: stack weight ordering - non-increasing bottom to top (7.5 pts)
        stacks = {}
        for r in plan_rows:
            key = (int(r["bay"]), int(r["row"]))
            stacks.setdefault(key, []).append(r)

        stack_violations = 0
        total_stacks = len(stacks)
        for key, stack in stacks.items():
            stack_sorted = sorted(stack, key=lambda x: int(x["tier"]))
            for i in range(len(stack_sorted) - 1):
                lower_cid = stack_sorted[i]["container_id"]
                upper_cid = stack_sorted[i + 1]["container_id"]
                if lower_cid in containers and upper_cid in containers:
                    if containers[lower_cid]["weight_tons"] < containers[upper_cid]["weight_tons"]:
                        stack_violations += 1
                        break  # one violation per stack

        c3a = 7.5 * max(0, 1 - cell_violations / max(1, len(plan_rows)))
        c3b = 7.5 * max(0, 1 - stack_violations / max(1, total_stacks))
        c3_score = c3a + c3b
        c3_reason = ""
        parts = []
        if cell_violations:
            parts.append(f"{cell_violations} cell weight limit violations")
        if stack_violations:
            parts.append(f"{stack_violations} stacks with weight ordering violations")
        if parts:
            c3_reason = "; ".join(parts)
        add_criterion(
            "weight_constraints",
            cell_violations == 0 and stack_violations == 0,
            c3_score, 15, c3_reason,
        )

        # --- Criterion 4: reefer_compliance (15 pts) ---
        reefer_violations = 0
        for r in plan_rows:
            cid = r["container_id"]
            cellid = r["cell_id"]
            if cid in needs_reefer and cellid in cells:
                if cells[cellid]["is_reefer_slot"] != 1:
                    reefer_violations += 1

        c4_score = 15 * max(0, 1 - reefer_violations / max(1, len(needs_reefer)))
        c4_reason = ""
        if reefer_violations:
            c4_reason = f"{reefer_violations} reefer/temp-control containers not in reefer cells"
        add_criterion("reefer_compliance", reefer_violations == 0, c4_score, 15, c4_reason)

        # --- Criterion 5: hazmat_compliance (15 pts) ---
        bay_hazmat_classes = {}  # bay -> set of hazmat classes
        for r in plan_rows:
            cid = r["container_id"]
            bay = int(r["bay"])
            if cid in containers and containers[cid]["hazmat_class"]:
                bay_hazmat_classes.setdefault(bay, set()).add(containers[cid]["hazmat_class"])

        hazmat_bay_violations = sum(
            1 for classes in bay_hazmat_classes.values() if len(classes) > 1
        )
        total_hazmat_bays = len(bay_hazmat_classes)
        c5_score = 15 * max(0, 1 - hazmat_bay_violations / max(1, total_hazmat_bays))
        c5_reason = ""
        if hazmat_bay_violations:
            c5_reason = f"{hazmat_bay_violations} bays have mixed hazmat classes"
        add_criterion("hazmat_compliance", hazmat_bay_violations == 0, c5_score, 15, c5_reason)

        # --- Criterion 6: rehandle_improvement (15 pts) ---
        # Compute re-handles for current plan
        container_dest = {cid: c["destination_port"] for cid, c in containers.items()}
        current_rows = [
            {"container_id": a["container_id"], "bay": a["bay_number"],
             "tier": a["tier"], "row": a["row_number"]}
            for a in current_plan
        ]
        current_rehandles = _compute_rehandles(current_rows, container_dest)

        # Compute re-handles for revised plan
        revised_rehandles = _compute_rehandles(plan_rows, container_dest)

        # Also check bay weight limits
        bay_weights = {}
        for r in plan_rows:
            cid = r["container_id"]
            bay = int(r["bay"])
            if cid in containers:
                bay_weights[bay] = bay_weights.get(bay, 0) + containers[cid]["weight_tons"]

        bay_weight_violations = sum(
            1 for w in bay_weights.values() if w > bay_weight_limit
        )

        c6_score = 0
        c6_reason = ""
        if bay_weight_violations > 0:
            c6_score = 0
            c6_reason = f"{bay_weight_violations} bays exceed weight limit of {bay_weight_limit}t"
        elif revised_rehandles < current_rehandles:
            c6_score = 15
        else:
            c6_reason = (
                f"Revised re-handles ({revised_rehandles}) not less than "
                f"current ({current_rehandles})"
            )
        add_criterion(
            "rehandle_improvement",
            c6_score == 15,
            c6_score, 15, c6_reason,
        )

        # --- Criterion 7: response_metrics (15 pts) ---
        # Parse utilization and re-handle count from response
        actual_util = len(set(plan_cids) & all_cids) / len(all_cids) * 100
        actual_rehandles = revised_rehandles

        # Parse utilization from action
        util_match = re.search(r"(\d+\.\d{2})%", action)
        rehandle_match = re.search(r"re-handl\w*[^0-9]*(\d+)", action, re.IGNORECASE)
        if not rehandle_match:
            rehandle_match = re.search(r"(\d+)\s+re-handl", action, re.IGNORECASE)

        c7_score = 0
        c7_parts = []
        if util_match:
            reported_util = float(util_match.group(1))
            if abs(reported_util - actual_util) < 0.02:
                c7_score += 7.5
            else:
                c7_parts.append(
                    f"Utilization: reported {reported_util:.2f}% vs actual {actual_util:.2f}%"
                )
        else:
            c7_parts.append("Could not parse utilization percentage from response")

        if rehandle_match:
            reported_rh = int(rehandle_match.group(1))
            if reported_rh == actual_rehandles:
                c7_score += 7.5
            else:
                c7_parts.append(
                    f"Re-handles: reported {reported_rh} vs actual {actual_rehandles}"
                )
        else:
            c7_parts.append("Could not parse re-handle count from response")

        c7_reason = "; ".join(c7_parts) if c7_parts else ""
        add_criterion("response_metrics", c7_score == 15, c7_score, 15, c7_reason)

        info["total_score"] = round(total_score, 2)
        info["max_score"] = round(max_score, 2)
        return round(total_score / max_score, 4), info

    # ================================================================
    # VERIFY
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

        # ---- 1. Read workspace files ----
        with open(os.path.join(self.workspace, "voyage_route.json")) as f:
            voyage = json.load(f)
        with open(os.path.join(self.workspace, "vessel_spec.json")) as f:
            vessel = json.load(f)

        # Build port discharge order from voyage legs
        port_order = {}
        for leg in voyage["legs"]:
            port_order[leg["to"]] = leg["leg"]
        # BRAVO=1, CHARLIE=2, DELTA=3

        bay_weight_limit = vessel["bay_weight_limit_tons"]
        n_bays = vessel["num_bays"]

        # Read cargo batch files for temp control
        temp_control_set = set()
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("cargo_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if str(row["requires_temp_control"]).strip().lower() == "true":
                            temp_control_set.add(row["container_id"])

        # Read stacking rules and hazmat policy (for completeness)
        with open(os.path.join(self.workspace, "stacking_rules.txt")) as f:
            _ = f.read()
        with open(os.path.join(self.workspace, "hazmat_policy.md")) as f:
            _ = f.read()

        # ---- 2. Gather data via tools ----

        # Get all containers (paginated)
        all_containers = []
        page = 1
        while True:
            result = self.tools["list_containers"](page=page, page_size=8)
            all_containers.extend(result["containers"])
            if page >= result["total_pages"]:
                break
            page += 1

        containers_map = {c["container_id"]: c for c in all_containers}

        # Get all cells via bay queries
        all_cells = []
        for bay_num in range(1, n_bays + 1):
            result = self.tools["get_bay_cells"](bay_number=bay_num)
            all_cells.extend(result["cells"])

        # Get current plan (paginated)
        current_assignments = []
        page = 1
        while True:
            result = self.tools["get_current_plan"](page=page, page_size=8)
            current_assignments.extend(result["assignments"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Get transport bookings for all discharge ports
        all_bookings = {}
        for port in ["BRAVO", "CHARLIE", "DELTA"]:
            result = self.tools["get_transport_bookings"](port_code=port)
            for b in result["bookings"]:
                all_bookings[b["container_id"]] = b

        # ---- 3. Determine constraints per container ----
        needs_reefer = set()
        for c in all_containers:
            if c["is_reefer"] == 1 or c["container_id"] in temp_control_set:
                needs_reefer.add(c["container_id"])

        # Build bay metadata
        bay_meta = {}
        for cell in all_cells:
            b = cell["bay_number"]
            if b not in bay_meta:
                bay_meta[b] = {
                    "type": cell["cell_size"],
                    "is_reefer": cell["is_reefer_slot"] == 1,
                }

        # Build stacks: (bay, row) -> list of cell dicts sorted by tier
        stack_cells = {}
        for cell in all_cells:
            key = (cell["bay_number"], cell["row_number"])
            stack_cells.setdefault(key, []).append(cell)
        for key in stack_cells:
            stack_cells[key].sort(key=lambda c: c["tier"])

        # ---- 4. Two-pass assignment algorithm ----
        # Pass 1: Assign containers to stacks, heaviest first.
        #         Each container is placed in the lowest available tier of its stack,
        #         automatically maintaining weight ordering (heavier = lower tier).
        # Pass 2: Fallback for any containers not placed in pass 1.

        # Sort: most constrained first, then heaviest first.
        def constraint_priority(c):
            n = 0
            if c["container_id"] in needs_reefer:
                n += 2
            if c["hazmat_class"]:
                n += 1
            return n

        sorted_containers = sorted(
            all_containers,
            key=lambda c: (-c["weight_tons"], -constraint_priority(c)),
        )

        # State trackers
        used_cells_set = set()
        bay_hazmat_class = {}   # bay -> hazmat class str
        bay_total_weight = {}   # bay -> float
        stack_dests = {}        # (bay, row) -> [dest_port, ...]

        final_assignments = {}  # container_id -> cell dict

        def find_best_cell(c):
            """Find the best cell for container c."""
            cid = c["container_id"]
            ctype = c["container_type"]
            weight = c["weight_tons"]
            hc = c["hazmat_class"] if c["hazmat_class"] else ""
            nr = cid in needs_reefer
            dest = c["destination_port"]
            dest_ord = port_order.get(dest, 0)

            best_cell = None
            best_score = -float("inf")

            for skey, cells_in_stack in stack_cells.items():
                bay, row = skey
                bi = bay_meta[bay]

                # Hard constraints on bay
                if bi["type"] != ctype:
                    continue
                if nr and not bi["is_reefer"]:
                    continue
                if hc and bay in bay_hazmat_class and bay_hazmat_class[bay] != hc:
                    continue
                if bay_total_weight.get(bay, 0) + weight > bay_weight_limit:
                    continue

                # Find lowest available cell in this stack
                target_cell = None
                for cell in cells_in_stack:  # sorted by tier ascending
                    if cell["cell_id"] not in used_cells_set:
                        if weight <= cell["max_weight_tons"]:
                            target_cell = cell
                            break

                if target_cell is None:
                    continue

                # Score this stack/cell combo
                score = 0.0

                # Reefer affinity: keep non-reefer out of reefer bays
                if not nr and bi["is_reefer"]:
                    score -= 5000  # strongly discourage non-reefer in reefer bay

                # Hazmat affinity
                if hc:
                    if bay in bay_hazmat_class and bay_hazmat_class[bay] == hc:
                        score += 10000
                    elif bay not in bay_hazmat_class:
                        score += 5000
                else:
                    if bay not in bay_hazmat_class:
                        score += 500

                # Destination clustering
                for sd in stack_dests.get(skey, []):
                    if sd == dest:
                        score += 300

                # Discharge optimization
                tier = target_cell["tier"]
                if dest_ord >= 2:
                    score -= tier * 15
                else:
                    score += tier * 15

                # Balance weight across bays
                score -= bay_total_weight.get(bay, 0) * 0.3

                # Prefer emptier stacks
                score -= len(stack_dests.get(skey, [])) * 20

                if score > best_score:
                    best_score = score
                    best_cell = target_cell

            return best_cell

        # Pass 1: Assign all containers
        for c in sorted_containers:
            cell = find_best_cell(c)
            if cell is not None:
                cid = c["container_id"]
                bay = cell["bay_number"]
                hc = c["hazmat_class"] if c["hazmat_class"] else ""
                final_assignments[cid] = cell
                used_cells_set.add(cell["cell_id"])
                bay_total_weight[bay] = bay_total_weight.get(bay, 0) + c["weight_tons"]
                if hc:
                    bay_hazmat_class[bay] = hc
                skey = (bay, cell["row_number"])
                stack_dests.setdefault(skey, []).append(c["destination_port"])

        # Pass 2: Fallback for unassigned - try any valid cell
        unassigned = [c for c in all_containers if c["container_id"] not in final_assignments]
        for c in unassigned:
            cid = c["container_id"]
            hc = c["hazmat_class"] if c["hazmat_class"] else ""
            nr = cid in needs_reefer
            for cell in all_cells:
                if cell["cell_id"] in used_cells_set:
                    continue
                bay = cell["bay_number"]
                bi = bay_meta[bay]
                if bi["type"] != c["container_type"]:
                    continue
                if nr and not bi["is_reefer"]:
                    continue
                if hc and bay in bay_hazmat_class and bay_hazmat_class[bay] != hc:
                    continue
                if bay_total_weight.get(bay, 0) + c["weight_tons"] > bay_weight_limit:
                    continue
                if c["weight_tons"] > cell["max_weight_tons"]:
                    continue
                final_assignments[cid] = cell
                used_cells_set.add(cell["cell_id"])
                bay_total_weight[bay] = bay_total_weight.get(bay, 0) + c["weight_tons"]
                if hc:
                    bay_hazmat_class[bay] = hc
                break

        # ---- 5. Write revised_plan.csv ----
        plan_path = os.path.join(self.workspace, "revised_plan.csv")
        with open(plan_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["container_id", "cell_id", "bay", "tier", "row"])
            for cid in sorted(final_assignments.keys()):
                cell = final_assignments[cid]
                writer.writerow([
                    cid, cell["cell_id"],
                    cell["bay_number"], cell["tier"], cell["row_number"],
                ])

        # ---- 6. Compute metrics ----
        utilization = len(final_assignments) / len(all_containers) * 100

        plan_rows = []
        for cid, cell in final_assignments.items():
            plan_rows.append({
                "container_id": cid,
                "bay": cell["bay_number"],
                "tier": cell["tier"],
                "row": cell["row_number"],
            })
        container_dest = {c["container_id"]: c["destination_port"] for c in all_containers}
        rehandles = _compute_rehandles(plan_rows, container_dest)

        action = (
            f"Revised loading plan has been saved to revised_plan.csv. "
            f"Capacity utilization: {utilization:.2f}%. "
            f"Total re-handling events: {rehandles}."
        )

        return self.step(action)
