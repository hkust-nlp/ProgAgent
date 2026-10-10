"""
Environment for cloud storage volume reclamation task.
"""

import csv
import glob
import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Tuple

import yaml


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
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

    # ──────────────────────────────────────────────────────────
    # Tool methods
    # ──────────────────────────────────────────────────────────

    @tool(
        description=(
            "Lists storage volumes with pagination. Returns volume_id, volume_name, "
            "status, project_id, volume_type, region, and size_gb for each volume. "
            "Use page and page_size to paginate. Optionally filter by status."
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
                    "description": "Number of results per page (max 25).",
                },
                "status_filter": {
                    "type": "string",
                    "enum": ["attached", "available", "all"],
                    "description": "Filter volumes by status. Defaults to 'all'.",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_volumes(self, page: int, page_size: int, status_filter: str = "all") -> dict:
        page_size = min(page_size, 25)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if status_filter and status_filter != "all":
            c.execute(
                "SELECT volume_id, volume_name, status, project_id, volume_type, region, size_gb "
                "FROM volumes WHERE status = ? ORDER BY volume_id LIMIT ? OFFSET ?",
                (status_filter, page_size, offset),
            )
            c2 = conn.cursor()
            c2.execute("SELECT COUNT(*) FROM volumes WHERE status = ?", (status_filter,))
        else:
            c.execute(
                "SELECT volume_id, volume_name, status, project_id, volume_type, region, size_gb "
                "FROM volumes ORDER BY volume_id LIMIT ? OFFSET ?",
                (page_size, offset),
            )
            c2 = conn.cursor()
            c2.execute("SELECT COUNT(*) FROM volumes")
        total = c2.fetchone()[0]
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return _envelope({
            "volumes": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        })

    @tool(
        description=(
            "Retrieves full details for a single volume by its volume_id, including "
            "volume_name, project_id, size_gb, volume_type, region, status, created_at, "
            "and description."
        ),
        parameters={
            "type": "object",
            "properties": {
                "volume_id": {
                    "type": "string",
                    "description": "The volume identifier, e.g. 'vol-000001'.",
                },
            },
            "required": ["volume_id"],
        },
    )
    def get_volume_details(self, volume_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM volumes WHERE volume_id = ?", (volume_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return _envelope(dict(row))
        return _envelope({"error": f"Volume {volume_id} not found."})

    @tool(
        description=(
            "Returns the attachment event history for a given volume. Each event includes "
            "event_id, instance_id, event_type (attach or detach), and event_timestamp."
        ),
        parameters={
            "type": "object",
            "properties": {
                "volume_id": {
                    "type": "string",
                    "description": "The volume identifier.",
                },
            },
            "required": ["volume_id"],
        },
    )
    def get_attachment_history(self, volume_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT event_id, instance_id, event_type, event_timestamp "
            "FROM attachment_events WHERE volume_id = ? ORDER BY event_timestamp",
            (volume_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps({"volume_id": volume_id, "events": rows, "count": len(rows)}, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns all snapshots associated with a given volume. Each snapshot includes "
            "snapshot_id, snapshot_name, created_at, size_gb, and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "volume_id": {
                    "type": "string",
                    "description": "The volume identifier.",
                },
            },
            "required": ["volume_id"],
        },
    )
    def get_volume_snapshots(self, volume_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT snapshot_id, snapshot_name, created_at, size_gb, status "
            "FROM snapshots WHERE volume_id = ? ORDER BY created_at",
            (volume_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps({"volume_id": volume_id, "snapshots": rows, "count": len(rows)}, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Retrieves project information by project_id, including project_name, "
            "department, budget_limit, current_spend, created_at, and owner_email."
        ),
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The project identifier, e.g. 'proj-0001'.",
                },
            },
            "required": ["project_id"],
        },
    )
    def get_project_info(self, project_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return json.dumps(dict(row), ensure_ascii=False, default=str)
        return json.dumps({"error": f"Project {project_id} not found."}, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns all budget alerts for a given project. Each alert includes "
            "alert_id, alert_type, threshold_pct, triggered_at, severity, and "
            "resolved (0 = unresolved, 1 = resolved)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The project identifier.",
                },
            },
            "required": ["project_id"],
        },
    )
    def get_project_budget_alerts(self, project_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT alert_id, alert_type, threshold_pct, triggered_at, severity, resolved "
            "FROM budget_alerts WHERE project_id = ? ORDER BY triggered_at DESC",
            (project_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return _envelope({"project_id": project_id, "alerts": rows, "count": len(rows)})

    # ──────────────────────────────────────────────────────────
    # Evaluation
    # ──────────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the ground-truth reclamation report from DB + workspace."""
        # Load policy
        policy_path = os.path.join(self.workspace, "reclamation_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)["reclamation_policy"]
        ref_date = datetime.strptime(policy["reference_date"], "%Y-%m-%d")
        threshold_days = policy["unattached_threshold_days"]
        exclude_labels = set(policy["exclude_volume_labels"])

        # Load pricing
        pricing_path = os.path.join(self.workspace, "pricing_tiers.json")
        with open(pricing_path) as f:
            pricing = json.load(f)["pricing_tiers"]

        # Load region multipliers
        region_mult = {}
        rm_path = os.path.join(self.workspace, "region_multipliers.csv")
        with open(rm_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                region_mult[row["region"]] = float(row["multiplier"])

        # Load volume labels from workspace files
        vol_labels_map = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "volume_labels_batch_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    labels = set(l.strip() for l in row["labels"].split(";"))
                    vol_labels_map[row["volume_id"]] = labels

        # Load maintenance schedules
        maint_vols = set()
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "maintenance_schedule_*.yaml"))):
            with open(fpath) as f:
                data = yaml.safe_load(f)
                for m in data.get("maintenance_windows", []):
                    if m.get("status") == "active":
                        maint_vols.add(m["volume_id"])

        # Query DB for available volumes and their last detach events
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT v.volume_id, v.volume_name, v.project_id, v.size_gb, v.volume_type, "
            "v.region, v.created_at FROM volumes v WHERE v.status = 'available'"
        )
        available = [dict(r) for r in c.fetchall()]

        report_rows = []
        for vol in available:
            vid = vol["volume_id"]

            # Find last detach timestamp
            c.execute(
                "SELECT MAX(event_timestamp) FROM attachment_events "
                "WHERE volume_id = ? AND event_type = 'detach'",
                (vid,),
            )
            row = c.fetchone()
            last_detach_str = row[0] if row and row[0] else None

            if last_detach_str is None:
                # Never attached → use creation date
                last_date = datetime.strptime(vol["created_at"], "%Y-%m-%d")
            else:
                last_date = datetime.strptime(last_detach_str, "%Y-%m-%d %H:%M:%S")

            days_unattached = (ref_date - last_date).days
            if days_unattached <= threshold_days:
                continue

            # Check excluded labels
            labels = vol_labels_map.get(vid, set())
            if labels & exclude_labels:
                continue

            # Check maintenance
            if vid in maint_vols:
                continue

            # Snapshots
            c.execute(
                "SELECT COUNT(*) FROM snapshots WHERE volume_id = ?", (vid,)
            )
            snap_count = c.fetchone()[0]

            # Project info
            c.execute(
                "SELECT project_name, department FROM projects WHERE project_id = ?",
                (vol["project_id"],),
            )
            proj_row = c.fetchone()
            project_name = proj_row["project_name"] if proj_row else "Unknown"
            department = proj_row["department"] if proj_row else "Unknown"

            # Budget alerts (unresolved)
            c.execute(
                "SELECT COUNT(*) FROM budget_alerts WHERE project_id = ? AND resolved = 0",
                (vol["project_id"],),
            )
            has_active_alert = c.fetchone()[0] > 0

            # Savings calculation
            base_price = pricing.get(vol["volume_type"], 0)
            rm = region_mult.get(vol["region"], 1.0)
            savings = round(vol["size_gb"] * base_price * rm, 2)

            last_attachment_date = last_date.strftime("%Y-%m-%d")

            report_rows.append({
                "volume_id": vid,
                "volume_name": vol["volume_name"],
                "project_name": project_name,
                "department": department,
                "size_gb": vol["size_gb"],
                "volume_type": vol["volume_type"],
                "region": vol["region"],
                "days_unattached": days_unattached,
                "last_attachment_date": last_attachment_date,
                "snapshot_count": snap_count,
                "has_active_budget_alert": has_active_alert,
                "estimated_monthly_savings": savings,
            })

        conn.close()

        # Sort: primary = estimated_monthly_savings desc, tiebreaker = days_unattached desc
        report_rows.sort(
            key=lambda r: (-r["estimated_monthly_savings"], -r["days_unattached"])
        )

        # Summary stats
        total_savings = round(sum(r["estimated_monthly_savings"] for r in report_rows), 2)
        total_volumes = len(report_rows)
        total_size_gb = sum(r["size_gb"] for r in report_rows)

        return {
            "report_rows": report_rows,
            "total_savings": total_savings,
            "total_volumes": total_volumes,
            "total_size_gb": total_size_gb,
        }

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
        gt = self._compute_ground_truth()
        gt_rows = gt["report_rows"]
        gt_savings = gt["total_savings"]
        gt_count = gt["total_volumes"]
        gt_size = gt["total_size_gb"]

        criteria = {}

        # ── Criterion 1: reclamation_report.csv exists and has correct columns (15 pts)
        report_path = os.path.join(self.workspace, "reclamation_report.csv")
        correct_columns = [
            "volume_id", "volume_name", "project_name", "department", "size_gb",
            "volume_type", "region", "days_unattached", "last_attachment_date",
            "snapshot_count", "has_active_budget_alert", "estimated_monthly_savings",
        ]
        report_exists = os.path.exists(report_path)
        report_data = []
        columns_correct = False
        if report_exists:
            try:
                with open(report_path) as f:
                    reader = csv.DictReader(f)
                    actual_cols = reader.fieldnames or []
                    columns_correct = actual_cols == correct_columns
                    report_data = list(reader)
            except Exception:
                pass
        criteria["report_file_structure"] = {
            "passed": report_exists and columns_correct,
            "score": 15 if (report_exists and columns_correct) else 0,
            "max_score": 15,
            "reason": (
                None if (report_exists and columns_correct)
                else (
                    "reclamation_report.csv missing" if not report_exists
                    else f"Column mismatch. Expected {correct_columns}, got {actual_cols}"
                )
            ),
        }

        # ── Criterion 2: Correct set of volume_ids in report (20 pts)
        gt_vol_ids = set(r["volume_id"] for r in gt_rows)
        report_vol_ids = set(r.get("volume_id", "") for r in report_data)
        ids_match = gt_vol_ids == report_vol_ids
        criteria["correct_volume_set"] = {
            "passed": ids_match,
            "score": 20 if ids_match else 0,
            "max_score": 20,
            "reason": (
                None if ids_match
                else f"Expected {sorted(gt_vol_ids)}, got {sorted(report_vol_ids)}"
            ),
        }

        # ── Criterion 3: Correct sort order (15 pts)
        report_order = [r.get("volume_id", "") for r in report_data]
        gt_order = [r["volume_id"] for r in gt_rows]
        order_correct = report_order == gt_order
        criteria["sort_order"] = {
            "passed": order_correct,
            "score": 15 if order_correct else 0,
            "max_score": 15,
            "reason": (
                None if order_correct
                else f"Expected order {gt_order}, got {report_order}"
            ),
        }

        # ── Criterion 4: Correct per-row field values (20 pts)
        # Check days_unattached, estimated_monthly_savings, snapshot_count, has_active_budget_alert
        gt_lookup = {r["volume_id"]: r for r in gt_rows}
        fields_to_check = [
            "days_unattached", "estimated_monthly_savings",
            "snapshot_count", "has_active_budget_alert",
        ]
        total_fields = 0
        correct_fields = 0
        field_errors = []
        for rr in report_data:
            vid = rr.get("volume_id", "")
            if vid not in gt_lookup:
                continue
            gt_r = gt_lookup[vid]
            for field in fields_to_check:
                total_fields += 1
                rr_val = str(rr.get(field, "")).strip()
                gt_val = gt_r[field]
                # Normalize booleans
                if isinstance(gt_val, bool):
                    gt_str = str(gt_val)
                else:
                    gt_str = str(gt_val)
                if rr_val == gt_str:
                    correct_fields += 1
                else:
                    field_errors.append(f"{vid}.{field}: expected={gt_str}, got={rr_val}")

        if total_fields > 0:
            field_score = round(20 * correct_fields / total_fields, 1)
        else:
            field_score = 0
        criteria["field_accuracy"] = {
            "passed": field_score == 20,
            "score": field_score,
            "max_score": 20,
            "reason": (
                None if field_score == 20
                else f"{len(field_errors)} field mismatches: {field_errors[:5]}"
            ),
        }

        # ── Criterion 5: Response contains correct summary statistics (15 pts)
        action_lower = action.lower() if action else ""
        summary_score = 0
        summary_reasons = []

        # Check total volumes count
        if str(gt_count) in action:
            summary_score += 5
        else:
            summary_reasons.append(f"Total volumes count {gt_count} not found in response")

        # Check total monthly savings
        gt_savings_str = f"{gt_savings:.2f}"
        if gt_savings_str in action:
            summary_score += 5
        else:
            summary_reasons.append(f"Total savings {gt_savings_str} not found in response")

        # Check total size
        if str(gt_size) in action:
            summary_score += 5
        else:
            summary_reasons.append(f"Total size {gt_size} GB not found in response")

        criteria["summary_statistics"] = {
            "passed": summary_score == 15,
            "score": summary_score,
            "max_score": 15,
            "reason": None if summary_score == 15 else "; ".join(summary_reasons),
        }

        # ── Criterion 6: Excluded volumes correctly filtered out (15 pts)
        # Check that exempt/maintenance volumes are NOT in the report
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Get all available volumes that SHOULD be excluded
        policy_path = os.path.join(self.workspace, "reclamation_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)["reclamation_policy"]
        ref_date = datetime.strptime(policy["reference_date"], "%Y-%m-%d")
        threshold_days = policy["unattached_threshold_days"]
        exclude_labels_set = set(policy["exclude_volume_labels"])

        vol_labels_map = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "volume_labels_batch_*.csv"))):
            with open(fpath) as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    labels = set(l.strip() for l in row["labels"].split(";"))
                    vol_labels_map[row["volume_id"]] = labels

        maint_vols = set()
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "maintenance_schedule_*.yaml"))):
            with open(fpath) as fh:
                data = yaml.safe_load(fh)
                for m in data.get("maintenance_windows", []):
                    if m.get("status") == "active":
                        maint_vols.add(m["volume_id"])

        c.execute("SELECT volume_id FROM volumes WHERE status = 'available'")
        all_avail = [r["volume_id"] for r in c.fetchall()]

        should_exclude = set()
        for vid in all_avail:
            # Check >90 days
            c.execute(
                "SELECT MAX(event_timestamp) FROM attachment_events "
                "WHERE volume_id = ? AND event_type = 'detach'",
                (vid,),
            )
            row = c.fetchone()
            last_str = row[0] if row and row[0] else None
            if last_str:
                last_dt = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
            else:
                c.execute("SELECT created_at FROM volumes WHERE volume_id = ?", (vid,))
                last_dt = datetime.strptime(c.fetchone()[0], "%Y-%m-%d")

            days = (ref_date - last_dt).days
            if days <= threshold_days:
                continue  # Not a candidate at all

            # This volume IS >90 days unattached but should be excluded
            labels = vol_labels_map.get(vid, set())
            if labels & exclude_labels_set:
                should_exclude.add(vid)
            elif vid in maint_vols:
                should_exclude.add(vid)

        conn.close()

        leaked = report_vol_ids & should_exclude
        exclusion_correct = len(leaked) == 0

        criteria["exclusion_filtering"] = {
            "passed": exclusion_correct,
            "score": 15 if exclusion_correct else 0,
            "max_score": 15,
            "reason": (
                None if exclusion_correct
                else f"Excluded volumes found in report: {sorted(leaked)}"
            ),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import os as _os

        # Step 1: Read policy config from workspace
        policy_path = _os.path.join(self.workspace, "reclamation_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)["reclamation_policy"]
        ref_date = datetime.strptime(policy["reference_date"], "%Y-%m-%d")
        threshold_days = policy["unattached_threshold_days"]
        exclude_labels = set(policy["exclude_volume_labels"])
        exclude_maintenance = policy["exclude_volumes_in_maintenance"]

        # Step 2: Read pricing tiers
        pricing_path = _os.path.join(self.workspace, "pricing_tiers.json")
        with open(pricing_path) as f:
            pricing = json.load(f)["pricing_tiers"]

        # Step 3: Read region multipliers
        region_mult = {}
        rm_path = _os.path.join(self.workspace, "region_multipliers.csv")
        with open(rm_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                region_mult[row["region"]] = float(row["multiplier"])

        # Step 4: Read volume labels from workspace
        vol_labels_map = {}
        for fpath in sorted(glob.glob(_os.path.join(self.workspace, "volume_labels_batch_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    labels = set(l.strip() for l in row["labels"].split(";"))
                    vol_labels_map[row["volume_id"]] = labels

        # Step 5: Read maintenance schedules
        maint_vols = set()
        if exclude_maintenance:
            for fpath in sorted(glob.glob(_os.path.join(self.workspace, "maintenance_schedule_*.yaml"))):
                with open(fpath) as f:
                    data = yaml.safe_load(f)
                    for m in data.get("maintenance_windows", []):
                        if m.get("status") == "active":
                            maint_vols.add(m["volume_id"])

        # Step 6: List all available volumes via paginated tool calls
        tool_call_count = 0
        all_available = []
        page = 1
        while True:
            result = json.loads(self.tools["list_volumes"](page=page, page_size=20, status_filter="available")["content"][0]["text"])
            tool_call_count += 1
            all_available.extend(result["volumes"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 7: For each available volume, get attachment history
        candidates = []
        for vol in all_available:
            vid = vol["volume_id"]
            hist = json.loads(self.tools["get_attachment_history"](volume_id=vid))
            tool_call_count += 1

            # Find last detach event
            detach_events = [e for e in hist["events"] if e["event_type"] == "detach"]
            if detach_events:
                last_detach_str = max(e["event_timestamp"] for e in detach_events)
                last_date = datetime.strptime(last_detach_str, "%Y-%m-%d %H:%M:%S")
            else:
                # Never attached, get volume details for created_at
                details = json.loads(self.tools["get_volume_details"](volume_id=vid)["content"][0]["text"])
                tool_call_count += 1
                last_date = datetime.strptime(details["created_at"], "%Y-%m-%d")

            days_unattached = (ref_date - last_date).days
            if days_unattached <= threshold_days:
                continue

            # Check labels from workspace
            labels = vol_labels_map.get(vid, set())
            if labels & exclude_labels:
                continue

            # Check maintenance
            if vid in maint_vols:
                continue

            candidates.append({
                "volume_id": vid,
                "volume_name": vol["volume_name"],
                "project_id": vol["project_id"],
                "size_gb": vol["size_gb"],
                "volume_type": vol["volume_type"],
                "region": vol["region"],
                "days_unattached": days_unattached,
                "last_attachment_date": last_date.strftime("%Y-%m-%d"),
            })

        # Step 8: For each candidate, get snapshots
        for cand in candidates:
            snaps = json.loads(self.tools["get_volume_snapshots"](volume_id=cand["volume_id"]))
            tool_call_count += 1
            cand["snapshot_count"] = snaps["count"]

        # Step 9: Get project info and budget alerts for each unique project
        project_cache = {}
        alert_cache = {}
        for cand in candidates:
            pid = cand["project_id"]
            if pid not in project_cache:
                proj_info = json.loads(self.tools["get_project_info"](project_id=pid))
                tool_call_count += 1
                project_cache[pid] = proj_info
                alerts_info = json.loads(self.tools["get_project_budget_alerts"](project_id=pid)["content"][0]["text"])
                tool_call_count += 1
                alert_cache[pid] = alerts_info

            proj = project_cache[pid]
            cand["project_name"] = proj.get("project_name", "Unknown")
            cand["department"] = proj.get("department", "Unknown")

            alerts = alert_cache[pid]
            has_active = any(a["resolved"] == 0 for a in alerts["alerts"])
            cand["has_active_budget_alert"] = has_active

        # Step 10: Calculate estimated monthly savings
        for cand in candidates:
            base_price = pricing.get(cand["volume_type"], 0)
            rm = region_mult.get(cand["region"], 1.0)
            cand["estimated_monthly_savings"] = round(cand["size_gb"] * base_price * rm, 2)

        # Step 11: Sort
        candidates.sort(
            key=lambda r: (-r["estimated_monthly_savings"], -r["days_unattached"])
        )

        # Step 12: Write reclamation_report.csv
        report_path = _os.path.join(self.workspace, "reclamation_report.csv")
        fieldnames = [
            "volume_id", "volume_name", "project_name", "department", "size_gb",
            "volume_type", "region", "days_unattached", "last_attachment_date",
            "snapshot_count", "has_active_budget_alert", "estimated_monthly_savings",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for cand in candidates:
                row = {k: cand[k] for k in fieldnames}
                writer.writerow(row)

        # Step 13: Build summary action string
        total_savings = round(sum(c["estimated_monthly_savings"] for c in candidates), 2)
        total_volumes = len(candidates)
        total_size = sum(c["size_gb"] for c in candidates)

        action = (
            f"Reclamation Report Summary:\n"
            f"Total reclaimable volumes: {total_volumes}\n"
            f"Total storage: {total_size} GB\n"
            f"Total estimated monthly savings: {total_savings:.2f} USD\n\n"
            f"The reclamation_report.csv has been saved with {total_volumes} volumes "
            f"sorted by estimated monthly savings (descending), with ties broken by "
            f"days unattached (descending). Volumes with exempt labels "
            f"({', '.join(sorted(exclude_labels))}) and volumes currently in active "
            f"maintenance windows have been excluded."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need at least 15"

        return self.step(action)
