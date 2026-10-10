#!/usr/bin/env python3
"""License compliance analysis task - environment."""

import sqlite3
import os
import json
import csv
import re
from datetime import datetime, timedelta
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

    # ── Tool methods ──

    PAGE_SIZE = 10

    @tool(
        description="List all projects with their metadata including product line, criticality level, and upcoming release date.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def list_projects(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
        conn.close()
        return _envelope([dict(r) for r in rows])

    @tool(
        description="Get paginated list of software components belonging to a specific project. Returns component name, version, license, deployment environment, and last update date.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "The project ID to list components for"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                    "default": 1
                }
            },
            "required": ["project_id"]
        }
    )
    def get_project_components(self, project_id: int, page: int = 1):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM components WHERE project_id = ?",
            (project_id,)
        ).fetchone()["cnt"]

        offset = (page - 1) * self.PAGE_SIZE
        rows = conn.execute(
            "SELECT c.id, c.name, c.current_version, c.license_spdx, c.deployment_env, c.last_updated "
            "FROM components c WHERE c.project_id = ? ORDER BY c.id LIMIT ? OFFSET ?",
            (project_id, self.PAGE_SIZE, offset)
        ).fetchall()

        proj = conn.execute(
            "SELECT name FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        conn.close()

        return _envelope({
            "project_id": project_id,
            "project_name": proj["name"] if proj else "unknown",
            "components": [dict(r) for r in rows],
            "page": page,
            "page_size": self.PAGE_SIZE,
            "total_components": total,
            "has_more": offset + self.PAGE_SIZE < total,
        })

    @tool(
        description="Get detailed information about a single component by its ID, including its project association.",
        parameters={
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "integer",
                    "description": "The component ID"
                }
            },
            "required": ["component_id"]
        }
    )
    def get_component_details(self, component_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT c.*, p.name as project_name, p.criticality as project_criticality "
            "FROM components c JOIN projects p ON c.project_id = p.id WHERE c.id = ?",
            (component_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Component {component_id} not found"}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description="Look up a license in the registry by its SPDX identifier. Returns category, risk level, OSI approval status, and organizational approval status.",
        parameters={
            "type": "object",
            "properties": {
                "spdx_id": {
                    "type": "string",
                    "description": "The SPDX license identifier (e.g. 'MIT', 'GPL-3.0-only')"
                }
            },
            "required": ["spdx_id"]
        }
    )
    def get_license_info(self, spdx_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT spdx_id, full_name, category, osi_approved, risk_level, approval_status "
            "FROM license_registry WHERE spdx_id = ?",
            (spdx_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"License {spdx_id} not found in registry", "spdx_id": spdx_id,
                    "category": "unknown", "risk_level": "critical", "approval_status": "denied"}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description="Get the version change history for a component. Each entry shows the old and new version, any license change, the date, and the type of change (patch, minor_upgrade, major_upgrade, security_fix, or license_change).",
        parameters={
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "integer",
                    "description": "The component ID"
                }
            },
            "required": ["component_id"]
        }
    )
    def get_version_history(self, component_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT from_version, to_version, from_license, to_license, change_date, change_type "
            "FROM version_history WHERE component_id = ? ORDER BY change_date DESC",
            (component_id,)
        ).fetchall()
        conn.close()
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str)

    @tool(
        description="Get all legal exception tickets for a component, ordered from most recent to oldest. Each ticket includes its status (approved, expired, pending, denied), type, conditions, and expiry date if applicable. The most recent ticket represents the current exception state.",
        parameters={
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "integer",
                    "description": "The component ID"
                }
            },
            "required": ["component_id"]
        }
    )
    def get_exception_status(self, component_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ticket_id, exception_type, status, granted_by, grant_date, "
            "expiry_date, conditions, justification "
            "FROM legal_exceptions WHERE component_id = ? ORDER BY id DESC",
            (component_id,)
        ).fetchall()
        conn.close()
        return _envelope([dict(r) for r in rows])

    @tool(
        description="Search for components by name pattern. Returns paginated results matching the query string (case-insensitive substring match).",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search string to match against component names"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                    "default": 1
                }
            },
            "required": ["query"]
        }
    )
    def search_components(self, query: str, page: int = 1):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        pattern = f"%{query}%"
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM components WHERE name LIKE ?",
            (pattern,)
        ).fetchone()["cnt"]

        offset = (page - 1) * self.PAGE_SIZE
        rows = conn.execute(
            "SELECT id, name, current_version, license_spdx, project_id, deployment_env, last_updated "
            "FROM components WHERE name LIKE ? ORDER BY id LIMIT ? OFFSET ?",
            (pattern, self.PAGE_SIZE, offset)
        ).fetchall()
        conn.close()
        return json.dumps({
            "query": query,
            "components": [dict(r) for r in rows],
            "page": page,
            "page_size": self.PAGE_SIZE,
            "total_matches": total,
            "has_more": offset + self.PAGE_SIZE < total,
        }, ensure_ascii=False, default=str)

    # ── Ground-truth computation (used by step and verify) ──

    def _compute_ground_truth(self):
        """Compute the expected compliance report from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load policy
        policy_path = os.path.join(self.workspace, "compliance_policy.json")
        with open(policy_path) as f:
            policy = json.load(f)

        ref_date = datetime.strptime(policy["reference_date"], "%Y-%m-%d")
        lookback_days = policy["license_change_lookback_days"]
        cutoff_date = ref_date - timedelta(days=lookback_days)

        base_weights = policy["risk_scoring"]["base_risk_weight"]
        crit_mults = policy["risk_scoring"]["criticality_multiplier"]
        replace_threshold = policy["action_thresholds"]["replace"]["min_risk_score"]
        obtain_threshold = policy["action_thresholds"]["obtain_exception"]["min_risk_score"]

        # Load approved license sets from YAML file
        approved_set, restricted_set, denied_set = self._parse_approved_licenses()

        # Load vulnerability counts from SCA CSVs
        vuln_data = self._load_sca_data()

        # Query all components with project info
        components = conn.execute(
            "SELECT c.*, p.name as project_name, p.criticality as project_criticality "
            "FROM components c JOIN projects p ON c.project_id = p.id ORDER BY c.id"
        ).fetchall()

        # Build license info map
        lic_rows = conn.execute("SELECT * FROM license_registry").fetchall()
        lic_map = {r["spdx_id"]: dict(r) for r in lic_rows}

        # Query all exceptions grouped by component
        all_exceptions = conn.execute(
            "SELECT * FROM legal_exceptions ORDER BY id DESC"
        ).fetchall()
        exc_by_comp = {}
        for ex in all_exceptions:
            exc_by_comp.setdefault(ex["component_id"], []).append(dict(ex))

        # Query version history for license changes
        all_history = conn.execute(
            "SELECT * FROM version_history WHERE change_type = 'license_change'"
        ).fetchall()
        recent_changes = {}  # component_id -> True if has recent license change
        for vh in all_history:
            try:
                change_dt = datetime.strptime(vh["change_date"], "%Y-%m-%d")
                if change_dt >= cutoff_date:
                    recent_changes[vh["component_id"]] = True
            except (ValueError, TypeError):
                pass

        conn.close()

        # Determine compliance for each component
        report_rows = []
        total_analyzed = len(components)
        total_flagged = 0
        total_replace = 0

        for comp in components:
            comp = dict(comp)
            lic_spdx = comp["license_spdx"]
            lic_info = lic_map.get(lic_spdx, {
                "category": "unknown", "risk_level": "critical", "approval_status": "denied"
            })

            # Determine approval from the YAML-based sets
            if lic_spdx in approved_set:
                approval = "approved"
            elif lic_spdx in restricted_set:
                approval = "restricted"
            elif lic_spdx in denied_set:
                approval = "denied"
            else:
                approval = "denied"

            risk_level = lic_info.get("risk_level", "critical")
            proj_crit = comp["project_criticality"]

            vuln_count = vuln_data.get(comp["name"], 0)
            vuln_factor = min(1 + vuln_count * 0.1, 3.0)
            risk_score = round(
                base_weights.get(risk_level, 10) *
                crit_mults.get(proj_crit, 1) *
                vuln_factor,
                2
            )

            has_recent_change = recent_changes.get(comp["id"], False)
            exceptions = exc_by_comp.get(comp["id"], [])
            latest_exc = exceptions[0] if exceptions else None

            result = self._determine_compliance(
                approval, comp["deployment_env"], latest_exc,
                has_recent_change, risk_score, ref_date,
                replace_threshold, obtain_threshold
            )

            if result is not None:
                status, action = result
                report_rows.append({
                    "component_name": comp["name"],
                    "project_name": comp["project_name"],
                    "license_spdx": lic_spdx,
                    "license_category": lic_info.get("category", "unknown"),
                    "deployment_env": comp["deployment_env"],
                    "compliance_status": status,
                    "risk_score": f"{risk_score:.2f}",
                    "action_required": action,
                })
                total_flagged += 1
                if action == "replace":
                    total_replace += 1

        # Sort by risk_score descending, then component_name ascending
        report_rows.sort(key=lambda r: (-float(r["risk_score"]), r["component_name"]))

        return {
            "report_rows": report_rows,
            "total_analyzed": total_analyzed,
            "total_flagged": total_flagged,
            "total_replace": total_replace,
        }

    def _determine_compliance(self, approval, deployment_env, latest_exc,
                              has_recent_change, risk_score, ref_date,
                              replace_threshold, obtain_threshold):
        """
        Returns (compliance_status, action_required) or None if compliant.

        A recent license change flags the component for re-evaluation regardless
        of its current exception status, per the prompt.
        """
        if approval == "approved":
            if has_recent_change:
                return ("license_changed", "re_evaluate")
            return None  # Fully compliant

        # Non-approved tier: a recent license change always overrides
        # the current exception/deployment status with re_evaluate.
        if has_recent_change:
            return ("license_changed", "re_evaluate")

        if approval == "restricted":
            if deployment_env in ("production", "staging"):
                return ("restricted_deployment", "legal_review")
            return None  # Restricted in dev/test/internal is OK

        # approval == "denied"
        if latest_exc is None:
            if risk_score >= replace_threshold:
                return ("non_compliant", "replace")
            if risk_score >= obtain_threshold:
                return ("non_compliant", "obtain_exception")
            return ("non_compliant", "obtain_exception")

        exc_status = latest_exc["status"]

        if exc_status == "denied":
            if risk_score >= replace_threshold:
                return ("exception_denied", "replace")
            return ("exception_denied", "obtain_exception")

        if exc_status == "pending":
            return ("exception_pending", "pending_review")

        if exc_status in ("expired", "approved"):
            # Check actual expiry
            expiry_str = latest_exc.get("expiry_date", "")
            if expiry_str:
                try:
                    expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d")
                    if expiry_dt < ref_date:
                        return ("exception_expired", "renew_exception")
                except (ValueError, TypeError):
                    pass

            if exc_status == "expired":
                return ("exception_expired", "renew_exception")

            # status == "approved" and not expired
            return None  # Valid exception

        # Fallback
        return ("non_compliant", "obtain_exception")

    def _parse_approved_licenses(self):
        """Parse approved_licenses.yaml and return sets of SPDX IDs."""
        approved = set()
        restricted = set()
        denied = set()

        yaml_path = os.path.join(self.workspace, "approved_licenses.yaml")
        with open(yaml_path) as f:
            content = f.read()

        current_section = None
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if stripped in ("approved:", "restricted:", "denied:"):
                current_section = stripped.rstrip(":")
                continue
            if "spdx_id:" in stripped:
                match = re.search(r'spdx_id:\s*"([^"]+)"', stripped)
                if match:
                    spdx = match.group(1)
                    if current_section == "approved":
                        approved.add(spdx)
                    elif current_section == "restricted":
                        restricted.add(spdx)
                    elif current_section == "denied":
                        denied.add(spdx)

        return approved, restricted, denied

    def _load_sca_data(self):
        """Load vulnerability counts from all SCA scan CSV files."""
        vuln_data = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("sca_scan_batch_") and fname.endswith(".csv"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        name = row["component_name"]
                        vuln_data[name] = int(row["vulnerability_count"])
        return vuln_data

    # ── Evaluation ──

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
        criteria = {}

        # --- Criterion 1: Report exists (10 pts) ---
        report_path = os.path.join(self.workspace, "compliance_report.csv")
        report_exists = os.path.exists(report_path)
        criteria["report_exists"] = {
            "passed": report_exists,
            "score": 10 if report_exists else 0,
            "max_score": 10,
        }
        if not report_exists:
            criteria["report_exists"]["reason"] = "compliance_report.csv not found in workspace"

        # Parse the report if it exists
        agent_rows = []
        agent_row_map = {}
        expected_cols = [
            "component_name", "project_name", "license_spdx", "license_category",
            "deployment_env", "compliance_status", "risk_score", "action_required"
        ]
        has_correct_structure = False

        if report_exists:
            try:
                with open(report_path) as f:
                    reader = csv.DictReader(f)
                    actual_cols = reader.fieldnames or []
                    has_correct_structure = actual_cols == expected_cols
                    for row in reader:
                        agent_rows.append(row)
                        agent_row_map[row.get("component_name", "")] = row
            except Exception:
                pass

        # --- Criterion 2: Report structure (10 pts) ---
        criteria["report_structure"] = {
            "passed": has_correct_structure,
            "score": 10 if has_correct_structure else 0,
            "max_score": 10,
        }
        if not has_correct_structure:
            criteria["report_structure"]["reason"] = f"Expected columns {expected_cols}"

        # --- Criterion 3: Flagged components (20 pts) ---
        gt_names = {r["component_name"] for r in gt["report_rows"]}
        agent_names = {r.get("component_name", "") for r in agent_rows}

        if gt_names:
            correct_names = gt_names & agent_names
            extra_names = agent_names - gt_names
            missing_names = gt_names - agent_names
            # Score: proportion of correct minus penalty for extras
            precision = len(correct_names) / len(agent_names) if agent_names else 0
            recall = len(correct_names) / len(gt_names)
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            flagged_score = round(f1 * 20)
        else:
            flagged_score = 20 if len(agent_names) == 0 else 0

        criteria["flagged_components"] = {
            "passed": flagged_score == 20,
            "score": flagged_score,
            "max_score": 20,
        }
        if flagged_score < 20:
            criteria["flagged_components"]["reason"] = (
                f"Expected {len(gt_names)} flagged, got {len(agent_names)}; "
                f"missing={len(gt_names - agent_names)}, extra={len(agent_names - gt_names)}"
            )

        # --- Criterion 4: Compliance status (20 pts) ---
        gt_map = {r["component_name"]: r for r in gt["report_rows"]}
        matched = gt_names & agent_names
        status_correct = 0
        status_total = len(matched)
        for name in matched:
            if agent_row_map.get(name, {}).get("compliance_status") == gt_map[name]["compliance_status"]:
                status_correct += 1
        status_score = round((status_correct / status_total * 20) if status_total > 0 else 0)
        criteria["compliance_status"] = {
            "passed": status_score == 20,
            "score": status_score,
            "max_score": 20,
        }
        if status_score < 20:
            criteria["compliance_status"]["reason"] = f"{status_correct}/{status_total} statuses correct"

        # --- Criterion 5: Risk scores (15 pts) ---
        risk_correct = 0
        risk_total = len(matched)
        for name in matched:
            try:
                agent_score = float(agent_row_map[name].get("risk_score", -1))
                gt_score = float(gt_map[name]["risk_score"])
                if abs(agent_score - gt_score) < 0.015:
                    risk_correct += 1
            except (ValueError, TypeError):
                pass
        risk_score_pts = round((risk_correct / risk_total * 15) if risk_total > 0 else 0)
        criteria["risk_scores"] = {
            "passed": risk_score_pts == 15,
            "score": risk_score_pts,
            "max_score": 15,
        }
        if risk_score_pts < 15:
            criteria["risk_scores"]["reason"] = f"{risk_correct}/{risk_total} risk scores correct"

        # --- Criterion 6: Action required (15 pts) ---
        action_correct = 0
        action_total = len(matched)
        for name in matched:
            if agent_row_map.get(name, {}).get("action_required") == gt_map[name]["action_required"]:
                action_correct += 1
        action_score = round((action_correct / action_total * 15) if action_total > 0 else 0)
        criteria["action_required"] = {
            "passed": action_score == 15,
            "score": action_score,
            "max_score": 15,
        }
        if action_score < 15:
            criteria["action_required"]["reason"] = f"{action_correct}/{action_total} actions correct"

        # --- Criterion 7: Response summary (10 pts) ---
        summary_score = 0
        action_str = action if action else ""

        # Check for total analyzed count
        if str(gt["total_analyzed"]) in action_str:
            summary_score += 4
        # Check for total flagged count
        if str(gt["total_flagged"]) in action_str:
            summary_score += 3
        # Check for replacement count
        if str(gt["total_replace"]) in action_str:
            summary_score += 3

        criteria["response_summary"] = {
            "passed": summary_score == 10,
            "score": summary_score,
            "max_score": 10,
        }
        if summary_score < 10:
            criteria["response_summary"]["reason"] = (
                f"Expected totals: analyzed={gt['total_analyzed']}, "
                f"flagged={gt['total_flagged']}, replace={gt['total_replace']}"
            )

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ── Verification ──

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as csv_mod

        # 1. Read policy files from workspace
        policy_path = os.path.join(self.workspace, "compliance_policy.json")
        with open(policy_path) as f:
            policy = json.load(f)

        ref_date = datetime.strptime(policy["reference_date"], "%Y-%m-%d")
        lookback_days = policy["license_change_lookback_days"]
        cutoff_date = ref_date - timedelta(days=lookback_days)
        base_weights = policy["risk_scoring"]["base_risk_weight"]
        crit_mults = policy["risk_scoring"]["criticality_multiplier"]
        replace_threshold = policy["action_thresholds"]["replace"]["min_risk_score"]
        obtain_threshold = policy["action_thresholds"]["obtain_exception"]["min_risk_score"]

        # 2. Parse approved licenses YAML
        approved_set, restricted_set, denied_set = set(), set(), set()
        yaml_path = os.path.join(self.workspace, "approved_licenses.yaml")
        with open(yaml_path) as f:
            content = f.read()
        current_section = None
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if stripped in ("approved:", "restricted:", "denied:"):
                current_section = stripped.rstrip(":")
                continue
            if "spdx_id:" in stripped:
                match = re.search(r'spdx_id:\s*"([^"]+)"', stripped)
                if match:
                    spdx = match.group(1)
                    if current_section == "approved":
                        approved_set.add(spdx)
                    elif current_section == "restricted":
                        restricted_set.add(spdx)
                    elif current_section == "denied":
                        denied_set.add(spdx)

        # 3. Load SCA vulnerability data from workspace CSVs
        vuln_data = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("sca_scan_batch_") and fname.endswith(".csv"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as f:
                    reader = csv_mod.DictReader(f)
                    for row in reader:
                        vuln_data[row["component_name"]] = int(row["vulnerability_count"])

        # 4. Get all projects and components via tools
        projects = json.loads(self.tools["list_projects"]()["content"][0]["text"])
        proj_crit = {p["id"]: p["criticality"] for p in projects}

        all_components = []
        for proj in projects:
            page = 1
            while True:
                result = json.loads(self.tools["get_project_components"](
                    project_id=proj["id"], page=page
                )["content"][0]["text"])
                for comp in result["components"]:
                    comp["project_name"] = result["project_name"]
                    comp["project_criticality"] = proj["criticality"]
                all_components.extend(result["components"])
                if not result["has_more"]:
                    break
                page += 1

        # 5. Analyze each component
        # Cache license lookups
        lic_cache = {}
        report_rows = []
        total_replace = 0

        for comp in all_components:
            lic_spdx = comp["license_spdx"]

            # Get license info (cached)
            if lic_spdx not in lic_cache:
                lic_cache[lic_spdx] = json.loads(self.tools["get_license_info"](spdx_id=lic_spdx))
            lic_info = lic_cache[lic_spdx]

            # Determine approval
            if lic_spdx in approved_set:
                approval = "approved"
            elif lic_spdx in restricted_set:
                approval = "restricted"
            elif lic_spdx in denied_set:
                approval = "denied"
            else:
                approval = "denied"

            # Get vulnerability count
            vuln_count = vuln_data.get(comp["name"], 0)
            vuln_factor = min(1 + vuln_count * 0.1, 3.0)
            risk_level = lic_info.get("risk_level", "critical")
            risk_score = round(
                base_weights.get(risk_level, 10) *
                crit_mults.get(comp["project_criticality"], 1) *
                vuln_factor,
                2
            )

            # Check version history for recent license changes
            history = json.loads(self.tools["get_version_history"](component_id=comp["id"]))
            has_recent_change = False
            for vh in history:
                if vh["change_type"] == "license_change":
                    try:
                        change_dt = datetime.strptime(vh["change_date"], "%Y-%m-%d")
                        if change_dt >= cutoff_date:
                            has_recent_change = True
                            break
                    except (ValueError, TypeError):
                        pass

            # Quick check: if approved and no recent change, skip
            if approval == "approved" and not has_recent_change:
                continue

            if approval == "restricted" and comp["deployment_env"] not in ("production", "staging") and not has_recent_change:
                continue

            # For denied licenses or restricted in prod/staging, check exceptions
            latest_exc = None
            if approval == "denied":
                exceptions = json.loads(self.tools["get_exception_status"](component_id=comp["id"])["content"][0]["text"])
                latest_exc = exceptions[0] if exceptions else None

            # Determine compliance
            result = self._determine_compliance(
                approval, comp["deployment_env"], latest_exc,
                has_recent_change, risk_score, ref_date,
                replace_threshold, obtain_threshold
            )

            if result is not None:
                status, action_req = result
                report_rows.append({
                    "component_name": comp["name"],
                    "project_name": comp["project_name"],
                    "license_spdx": lic_spdx,
                    "license_category": lic_info.get("category", "unknown"),
                    "deployment_env": comp["deployment_env"],
                    "compliance_status": status,
                    "risk_score": f"{risk_score:.2f}",
                    "action_required": action_req,
                })
                if action_req == "replace":
                    total_replace += 1

        # 6. Sort: risk_score descending, then component_name ascending
        report_rows.sort(key=lambda r: (-float(r["risk_score"]), r["component_name"]))

        # 7. Write compliance_report.csv
        report_path = os.path.join(self.workspace, "compliance_report.csv")
        cols = [
            "component_name", "project_name", "license_spdx", "license_category",
            "deployment_env", "compliance_status", "risk_score", "action_required"
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for row in report_rows:
                writer.writerow(row)

        # 8. Build response summary
        total_analyzed = len(all_components)
        total_flagged = len(report_rows)
        action_str = (
            f"Compliance analysis complete. "
            f"Total components analyzed: {total_analyzed}. "
            f"Components flagged for compliance issues: {total_flagged}. "
            f"Components requiring immediate replacement: {total_replace}. "
            f"The full compliance report has been saved to compliance_report.csv."
        )

        return self.step(action_str)
