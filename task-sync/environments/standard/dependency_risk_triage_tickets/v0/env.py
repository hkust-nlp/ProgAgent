"""
Environment for dependency-risk triage task.
Defines tools the agent can call, scoring logic, and self-verification.
"""

import sqlite3
import os
import json
import csv
import math
from typing import Tuple, Dict, List, Any

import yaml


# ---------------------------------------------------------------------------
# Decorator
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
# Helpers
# ---------------------------------------------------------------------------
def _parse_version(v: str):
    """Parse a dotted version string into a comparable tuple of ints."""
    parts = v.split(".")
    result = []
    for p in parts[:3]:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    while len(result) < 3:
        result.append(0)
    return tuple(result)


def _version_lt(a: str, b: str) -> bool:
    return _parse_version(a) < _parse_version(b)


# ---------------------------------------------------------------------------
# Task_Env
# ---------------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List open dependabot alerts with pagination. Returns a page of "
            "open alerts sorted by alert_id ascending."
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
                    "description": "Number of alerts per page (max 20, default 10).",
                },
            },
            "required": ["page"],
        },
    )
    def list_open_alerts(self, page: int, page_size: int = 10) -> dict:
        page_size = max(1, min(page_size, 20))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM dependabot_alerts WHERE status='open'"
        )
        total = c.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        c.execute(
            "SELECT alert_id, package_name, severity, created_at "
            "FROM dependabot_alerts WHERE status='open' "
            "ORDER BY alert_id ASC LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return _envelope({
            "alerts": rows,
            "page": page,
            "page_size": page_size,
            "total_alerts": total,
            "total_pages": total_pages,
        })

    @tool(
        description=(
            "Get full details of a single dependabot alert by its ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "alert_id": {
                    "type": "integer",
                    "description": "The alert ID to look up.",
                },
            },
            "required": ["alert_id"],
        },
    )
    def get_alert_detail(self, alert_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM dependabot_alerts WHERE alert_id=?", (alert_id,)
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Alert {alert_id} not found"}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description=(
            "Query threat-intelligence data for a given CVE identifier. "
            "Returns exploit maturity, EPSS score, and known-exploited flag."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cve_id": {
                    "type": "string",
                    "description": "CVE identifier, e.g. CVE-2025-12345.",
                },
            },
            "required": ["cve_id"],
        },
    )
    def query_threat_intel(self, cve_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT cve_id, epss_score, exploit_maturity, "
            "known_exploited, last_updated "
            "FROM threat_intelligence WHERE cve_id=?",
            (cve_id,),
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"No threat intelligence for {cve_id}"}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description=(
            "Look up service ownership information by service name. "
            "Returns the owning team, service tier, and on-call contact."
        ),
        parameters={
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Exact service name.",
                },
            },
            "required": ["service_name"],
        },
    )
    def get_service_owner(self, service_name: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT service_name, team_name, tier, oncall_email, description "
            "FROM services WHERE service_name=?",
            (service_name,),
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Service '{service_name}' not found"}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description=(
            "Retrieve remediation history entries for a given alert ID. "
            "Returns all historical tickets associated with the alert."
        ),
        parameters={
            "type": "object",
            "properties": {
                "alert_id": {
                    "type": "integer",
                    "description": "The alert ID to look up history for.",
                },
            },
            "required": ["alert_id"],
        },
    )
    def get_remediation_history(self, alert_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT ticket_id, alert_id, service_name, status, "
            "assigned_team, created_at, resolved_at "
            "FROM remediation_history WHERE alert_id=?",
            (alert_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return _envelope({"alert_id": alert_id, "history": rows})

    # ------------------------------------------------------------------
    # Ground-truth computation (used by both step and verify)
    # ------------------------------------------------------------------

    def _compute_ground_truth(self) -> list:
        """Return the sorted list of expected ticket dicts."""
        # 1. Read config files
        with open(os.path.join(self.workspace, "priority_config.yaml")) as f:
            pcfg = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "sla_policy.yaml")) as f:
            sla_cfg = yaml.safe_load(f)

        sev_w = pcfg["severity_weights"]
        exp_w = pcfg["exploit_maturity_weights"]
        tier_w = pcfg["service_tier_weights"]
        sla_tiers = sorted(
            sla_cfg["sla_tiers"], key=lambda t: -t["min_priority_score"]
        )

        # 2. Read exceptions
        exceptions: set = set()
        exc_path = os.path.join(self.workspace, "known_exceptions.txt")
        if os.path.exists(exc_path):
            with open(exc_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        exceptions.add(line)

        # 3. Read deployment manifests
        deployments: dict = {}  # svc_name -> [{package, version}, ...]
        for fname in os.listdir(self.workspace):
            if fname.startswith("deploy_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    m = json.load(f)
                deployments[m["service_name"]] = m["dependencies"]

        # 4. Query DB for open alerts, threat intel, services, history
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT * FROM dependabot_alerts WHERE status='open' ORDER BY alert_id")
        open_alerts = [dict(r) for r in c.fetchall()]

        c.execute("SELECT * FROM threat_intelligence")
        intel_map = {r["cve_id"]: dict(r) for r in c.fetchall()}

        c.execute("SELECT * FROM services")
        svc_map = {r["service_name"]: dict(r) for r in c.fetchall()}

        c.execute("SELECT * FROM remediation_history")
        all_history = [dict(r) for r in c.fetchall()]
        conn.close()

        # Index history by (alert_id, service_name)
        hist_index: dict = {}
        for h in all_history:
            key = (h["alert_id"], h["service_name"])
            hist_index.setdefault(key, []).append(h)

        # 5. Build tickets
        tickets = []
        for alert in open_alerts:
            pkg = alert["package_name"]
            if pkg in exceptions:
                continue
            patched = alert["patched_version"]
            cve = alert["cve_id"]
            severity = alert["severity"]

            for svc_name, deps in deployments.items():
                for dep in deps:
                    if dep["package"] != pkg:
                        continue
                    if not _version_lt(dep["version"], patched):
                        continue

                    # Duplicate check
                    hist_key = (alert["alert_id"], svc_name)
                    if hist_key in hist_index:
                        if any(
                            h["status"] in ("in_progress", "completed")
                            for h in hist_index[hist_key]
                        ):
                            continue

                    # Threat intel
                    intel = intel_map.get(cve, {})
                    exploit_mat = intel.get("exploit_maturity", "none")

                    # Service info
                    svc_info = svc_map.get(svc_name, {})
                    tier = svc_info.get("tier", 4)
                    team = svc_info.get("team_name", "unknown")
                    oncall = svc_info.get("oncall_email", "unknown")

                    # Priority score
                    s_w = sev_w.get(severity, 1)
                    e_w = exp_w.get(exploit_mat, 1)
                    t_w = tier_w.get(str(tier), 1)
                    priority_score = s_w * e_w * t_w

                    # SLA
                    sla_hours = 336
                    sla_label = "P3-Low"
                    for st in sla_tiers:
                        if priority_score >= st["min_priority_score"]:
                            sla_hours = st["sla_hours"]
                            sla_label = st["label"]
                            break

                    tickets.append({
                        "alert_id": alert["alert_id"],
                        "cve_id": cve,
                        "package_name": pkg,
                        "service_name": svc_name,
                        "severity": severity,
                        "exploit_maturity": exploit_mat,
                        "service_tier": tier,
                        "priority_score": priority_score,
                        "sla_hours": sla_hours,
                        "sla_label": sla_label,
                        "assigned_team": team,
                        "oncall_email": oncall,
                    })

        # Sort by priority_score DESC, alert_id ASC, service_name ASC
        tickets.sort(
            key=lambda t: (-t["priority_score"], t["alert_id"], t["service_name"])
        )

        # Assign ticket IDs
        for i, t in enumerate(tickets):
            t["ticket_id"] = f"TKT-{i + 1:04d}"

        return tickets

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

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
        criteria: dict = {}

        # ── 1. File structure (10 pts) ────────────────────────────────────
        csv_path = os.path.join(self.workspace, "prioritized_tickets.csv")
        required_cols = [
            "ticket_id", "alert_id", "cve_id", "package_name",
            "service_name", "severity", "exploit_maturity", "service_tier",
            "priority_score", "sla_hours", "sla_label", "assigned_team",
            "oncall_email",
        ]
        actual_rows: list = []
        file_ok = False
        if os.path.exists(csv_path):
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and all(
                    c in reader.fieldnames for c in required_cols
                ):
                    actual_rows = list(reader)
                    file_ok = True
        criteria["file_structure"] = {
            "passed": file_ok,
            "score": 10 if file_ok else 0,
            "max_score": 10,
            "reason": "" if file_ok else "CSV missing or has wrong columns",
        }

        # ── 2. Ticket coverage – no missing (20 pts) ─────────────────────
        expected_pairs = {
            (str(t["alert_id"]), t["service_name"]) for t in expected
        }
        actual_pairs = set()
        for r in actual_rows:
            actual_pairs.add((str(r.get("alert_id", "")), r.get("service_name", "")))
        found = expected_pairs & actual_pairs
        if expected_pairs:
            coverage_ratio = len(found) / len(expected_pairs)
        else:
            coverage_ratio = 1.0 if not actual_pairs else 0.0
        coverage_score = round(20 * coverage_ratio)
        criteria["ticket_coverage"] = {
            "passed": coverage_ratio == 1.0,
            "score": coverage_score,
            "max_score": 20,
            "reason": (
                ""
                if coverage_ratio == 1.0
                else f"Missing {len(expected_pairs) - len(found)} of {len(expected_pairs)} tickets"
            ),
        }

        # ── 3. No false positives (15 pts) ───────────────────────────────
        false_pos = actual_pairs - expected_pairs
        fp_ok = len(false_pos) == 0
        if actual_pairs:
            fp_ratio = max(0.0, 1.0 - len(false_pos) / len(actual_pairs))
        else:
            fp_ratio = 1.0 if not expected_pairs else 0.0
        fp_score = round(15 * fp_ratio)
        criteria["no_false_positives"] = {
            "passed": fp_ok,
            "score": fp_score,
            "max_score": 15,
            "reason": (
                "" if fp_ok else f"{len(false_pos)} unexpected ticket(s)"
            ),
        }

        # ── 4. Priority scores (20 pts) ──────────────────────────────────
        expected_map = {
            (str(t["alert_id"]), t["service_name"]): t for t in expected
        }
        correct_scores = 0
        total_scored = 0
        for r in actual_rows:
            key = (str(r.get("alert_id", "")), r.get("service_name", ""))
            if key in expected_map:
                total_scored += 1
                try:
                    if int(float(r.get("priority_score", -1))) == expected_map[key]["priority_score"]:
                        correct_scores += 1
                except (ValueError, TypeError):
                    pass
        if total_scored > 0:
            ps_ratio = correct_scores / total_scored
        else:
            ps_ratio = 0.0
        ps_score = round(20 * ps_ratio)
        criteria["priority_scores"] = {
            "passed": ps_ratio == 1.0,
            "score": ps_score,
            "max_score": 20,
            "reason": (
                ""
                if ps_ratio == 1.0
                else f"{total_scored - correct_scores} incorrect priority score(s)"
            ),
        }

        # ── 5. SLA assignment (15 pts) ───────────────────────────────────
        correct_sla = 0
        total_sla = 0
        for r in actual_rows:
            key = (str(r.get("alert_id", "")), r.get("service_name", ""))
            if key in expected_map:
                total_sla += 1
                exp = expected_map[key]
                try:
                    hours_ok = int(float(r.get("sla_hours", -1))) == exp["sla_hours"]
                except (ValueError, TypeError):
                    hours_ok = False
                label_ok = r.get("sla_label", "").strip() == exp["sla_label"]
                if hours_ok and label_ok:
                    correct_sla += 1
        if total_sla > 0:
            sla_ratio = correct_sla / total_sla
        else:
            sla_ratio = 0.0
        sla_score = round(15 * sla_ratio)
        criteria["sla_assignment"] = {
            "passed": sla_ratio == 1.0,
            "score": sla_score,
            "max_score": 15,
            "reason": (
                ""
                if sla_ratio == 1.0
                else f"{total_sla - correct_sla} incorrect SLA assignment(s)"
            ),
        }

        # ── 6. Sort order (10 pts) ───────────────────────────────────────
        sort_ok = False
        if actual_rows and len(actual_rows) == len(expected):
            sort_ok = True
            for ar, er in zip(actual_rows, expected):
                if (str(ar.get("alert_id", "")) != str(er["alert_id"])
                        or ar.get("service_name", "") != er["service_name"]):
                    sort_ok = False
                    break
        criteria["sort_order"] = {
            "passed": sort_ok,
            "score": 10 if sort_ok else 0,
            "max_score": 10,
            "reason": (
                ""
                if sort_ok
                else "Rows not sorted by priority_score desc / alert_id asc / service_name asc"
            ),
        }

        # ── 7. Response summary (10 pts) ─────────────────────────────────
        sla_counts: dict = {}
        for t in expected:
            sla_counts[t["sla_label"]] = sla_counts.get(t["sla_label"], 0) + 1
        expected_total = len(expected)

        summary_pts = 0
        max_summary = 10
        # Check total count in response
        if str(expected_total) in action:
            summary_pts += 4
        # Check per-SLA counts
        labels = ["P0-Critical", "P1-High", "P2-Medium", "P3-Low"]
        per_label_pts = 6.0 / max(len(labels), 1)
        for label in labels:
            cnt = sla_counts.get(label, 0)
            # Look for "P0-Critical: N" or "P0-Critical N" patterns
            if f"{label}: {cnt}" in action or f"{label} {cnt}" in action or f"{label}:{cnt}" in action:
                summary_pts += per_label_pts
        summary_pts = min(max_summary, round(summary_pts))
        criteria["response_summary"] = {
            "passed": summary_pts == max_summary,
            "score": summary_pts,
            "max_score": max_summary,
            "reason": (
                ""
                if summary_pts == max_summary
                else "Response missing total count or per-SLA breakdown"
            ),
        }

        # ── Aggregate ────────────────────────────────────────────────────
        total_score = sum(cr["score"] for cr in criteria.values())
        max_score = sum(cr["max_score"] for cr in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------
    # Self-verification
    # ------------------------------------------------------------------

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
        # 1. Read config files from workspace
        with open(os.path.join(self.workspace, "priority_config.yaml")) as f:
            pcfg = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "sla_policy.yaml")) as f:
            sla_cfg = yaml.safe_load(f)

        sev_w = pcfg["severity_weights"]
        exp_w = pcfg["exploit_maturity_weights"]
        tier_w = pcfg["service_tier_weights"]
        sla_tiers = sorted(
            sla_cfg["sla_tiers"], key=lambda t: -t["min_priority_score"]
        )

        # 2. Read known exceptions
        exceptions: set = set()
        with open(os.path.join(self.workspace, "known_exceptions.txt")) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    exceptions.add(line)

        # 3. Read deployment manifests from workspace
        deployments: dict = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("deploy_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    m = json.load(f)
                deployments[m["service_name"]] = m["dependencies"]

        # 4. List all open alerts (paginated)
        all_alerts: list = []
        page = 1
        while True:
            result = json.loads(self.tools["list_open_alerts"](page=page, page_size=10)["content"][0]["text"])
            all_alerts.extend(result["alerts"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 5. For each open alert, get detail and cross-reference
        intel_cache: dict = {}
        owner_cache: dict = {}
        tickets: list = []

        for alert_summary in all_alerts:
            aid = alert_summary["alert_id"]
            detail = json.loads(self.tools["get_alert_detail"](alert_id=aid))

            pkg = detail["package_name"]
            if pkg in exceptions:
                continue
            patched = detail["patched_version"]
            cve = detail["cve_id"]
            severity = detail["severity"]

            for svc_name, deps in deployments.items():
                for dep in deps:
                    if dep["package"] != pkg:
                        continue
                    if not _version_lt(dep["version"], patched):
                        continue

                    # Check remediation history
                    hist = json.loads(self.tools["get_remediation_history"](alert_id=aid)["content"][0]["text"])
                    blocked = any(
                        h["service_name"] == svc_name
                        and h["status"] in ("in_progress", "completed")
                        for h in hist["history"]
                    )
                    if blocked:
                        continue

                    # Threat intel (cache to reduce redundant calls)
                    if cve not in intel_cache:
                        intel_cache[cve] = json.loads(self.tools["query_threat_intel"](
                            cve_id=cve
                        ))
                    intel = intel_cache[cve]
                    exploit_mat = intel.get("exploit_maturity", "none")

                    # Service owner (cache)
                    if svc_name not in owner_cache:
                        owner_cache[svc_name] = json.loads(self.tools["get_service_owner"](
                            service_name=svc_name
                        ))
                    owner = owner_cache[svc_name]
                    tier = owner.get("tier", 4)
                    team = owner.get("team_name", "unknown")
                    oncall = owner.get("oncall_email", "unknown")

                    # Priority
                    s = sev_w.get(severity, 1)
                    e = exp_w.get(exploit_mat, 1)
                    t = tier_w.get(str(tier), 1)
                    priority_score = s * e * t

                    # SLA
                    sla_hours = 336
                    sla_label = "P3-Low"
                    for st in sla_tiers:
                        if priority_score >= st["min_priority_score"]:
                            sla_hours = st["sla_hours"]
                            sla_label = st["label"]
                            break

                    tickets.append({
                        "alert_id": aid,
                        "cve_id": cve,
                        "package_name": pkg,
                        "service_name": svc_name,
                        "severity": severity,
                        "exploit_maturity": exploit_mat,
                        "service_tier": tier,
                        "priority_score": priority_score,
                        "sla_hours": sla_hours,
                        "sla_label": sla_label,
                        "assigned_team": team,
                        "oncall_email": oncall,
                    })

        # Sort: priority_score DESC, alert_id ASC, service_name ASC
        tickets.sort(
            key=lambda t: (-t["priority_score"], t["alert_id"], t["service_name"])
        )

        # Assign ticket IDs
        for i, t in enumerate(tickets):
            t["ticket_id"] = f"TKT-{i + 1:04d}"

        # 6. Write deliverable CSV
        csv_path = os.path.join(self.workspace, "prioritized_tickets.csv")
        fieldnames = [
            "ticket_id", "alert_id", "cve_id", "package_name",
            "service_name", "severity", "exploit_maturity", "service_tier",
            "priority_score", "sla_hours", "sla_label", "assigned_team",
            "oncall_email",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(tickets)

        # 7. Build response summary
        sla_counts: dict = {}
        for t in tickets:
            sla_counts[t["sla_label"]] = sla_counts.get(t["sla_label"], 0) + 1

        lines = [f"Total tickets: {len(tickets)}"]
        for label in ["P0-Critical", "P1-High", "P2-Medium", "P3-Low"]:
            lines.append(f"{label}: {sla_counts.get(label, 0)}")
        action = "\n".join(lines)

        return self.step(action)
