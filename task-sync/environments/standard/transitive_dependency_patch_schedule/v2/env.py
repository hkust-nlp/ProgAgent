"""
Environment for the transitive dependency patch schedule task.
"""

import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple


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

    # -----------------------------------------------------------------------
    # Tool methods
    # -----------------------------------------------------------------------

    @tool(
        description="Retrieve detailed information about a specific CVE vulnerability, including its CVSS score, affected version range, and the version that fixes the issue (if available). Only accepts a single CVE identifier per call.",
        parameters={
            "type": "object",
            "properties": {
                "cve_id": {
                    "type": "string",
                    "description": "The CVE identifier, e.g. CVE-2025-01000",
                },
            },
            "required": ["cve_id"],
        },
    )
    def get_vulnerability_details(self, cve_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM vulnerabilities WHERE cve_id = ?", (cve_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"CVE {cve_id} not found"}
        return {
            "cve_id": row["cve_id"],
            "component_name": row["component_name"],
            "affected_version": row["affected_version"],
            "fixed_version": row["fixed_version"],
            "severity": row["severity"],
            "cvss_score": row["cvss_score"],
            "published_date": row["published_date"],
            "description": row["description"],
        }

    @tool(
        description="Check whether a patched version exists for a given component at its current version. Returns patch availability status and, if a fix exists, the version that resolves known vulnerabilities.",
        parameters={
            "type": "object",
            "properties": {
                "component_name": {
                    "type": "string",
                    "description": "The full component/package name",
                },
                "current_version": {
                    "type": "string",
                    "description": "The currently deployed version string, e.g. 1.2.3",
                },
            },
            "required": ["component_name", "current_version"],
        },
    )
    def check_patch_available(self, component_name: str, current_version: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Find vulnerabilities with fixes for this component at this version
        cur.execute(
            """SELECT cve_id, fixed_version, severity, cvss_score
               FROM vulnerabilities
               WHERE component_name = ? AND affected_version = ? AND fixed_version IS NOT NULL
               ORDER BY cvss_score DESC""",
            (component_name, current_version),
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return {
                "component_name": component_name,
                "current_version": current_version,
                "patch_available": False,
                "patches": [],
            }

        patches = []
        for r in rows:
            patches.append({
                "cve_id": r["cve_id"],
                "fixed_version": r["fixed_version"],
                "severity": r["severity"],
                "cvss_score": r["cvss_score"],
            })

        return {
            "component_name": component_name,
            "current_version": current_version,
            "patch_available": True,
            "patches": patches,
        }

    @tool(
        description="List all production services that actively use a given component, resolving transitive dependency chains. Returns service names and deployment details for active production deployments only.",
        parameters={
            "type": "object",
            "properties": {
                "component_name": {
                    "type": "string",
                    "description": "The full component/package name to look up",
                },
            },
            "required": ["component_name"],
        },
    )
    def get_active_services(self, component_name: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Find the component
        cur.execute("SELECT * FROM components WHERE name = ?", (component_name,))
        comp = cur.fetchone()
        if comp is None:
            conn.close()
            return {"error": f"Component {component_name} not found"}

        # Resolve to direct ancestor(s) for deployment lookup
        direct_ancestor_ids = set()
        if comp["is_direct"]:
            direct_ancestor_ids.add(comp["id"])
        else:
            # Walk up the parent chain to find direct ancestors
            stack = [comp["parent_id"]]
            visited = set()
            while stack:
                pid = stack.pop()
                if pid is None or pid in visited:
                    continue
                visited.add(pid)
                cur.execute("SELECT * FROM components WHERE id = ?", (pid,))
                parent = cur.fetchone()
                if parent is None:
                    continue
                if parent["is_direct"]:
                    direct_ancestor_ids.add(parent["id"])
                else:
                    stack.append(parent["parent_id"])

        # Find active production deployments of direct ancestors
        services = []
        seen_svc = set()
        for da_id in direct_ancestor_ids:
            cur.execute(
                """SELECT d.service_name, d.deploy_date, c.name as direct_dep_name
                   FROM deployments d
                   JOIN components c ON c.id = d.component_id
                   WHERE d.component_id = ? AND d.environment = 'production' AND d.is_active = 1""",
                (da_id,),
            )
            for row in cur.fetchall():
                if row["service_name"] not in seen_svc:
                    seen_svc.add(row["service_name"])
                    services.append({
                        "service_name": row["service_name"],
                        "via_direct_dependency": row["direct_dep_name"],
                        "deploy_date": row["deploy_date"],
                    })

        conn.close()
        return {
            "component_name": component_name,
            "is_direct": bool(comp["is_direct"]),
            "active_production_services": services,
        }

    @tool(
        description="Get metadata for a component including its ecosystem, description, and dependency type. Returns basic catalog information about the package.",
        parameters={
            "type": "object",
            "properties": {
                "component_name": {
                    "type": "string",
                    "description": "The full component/package name",
                },
            },
            "required": ["component_name"],
        },
    )
    def get_component_metadata(self, component_name: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM components WHERE name = ?", (component_name,))
        row = cur.fetchone()
        if row is None:
            conn.close()
            return {"error": f"Component {component_name} not found"}

        parent_name = None
        if row["parent_id"]:
            cur.execute("SELECT name FROM components WHERE id = ?", (row["parent_id"],))
            p = cur.fetchone()
            if p:
                parent_name = p["name"]

        conn.close()
        return {
            "component_name": row["name"],
            "version": row["version"],
            "ecosystem": row["ecosystem"],
            "is_direct_dependency": bool(row["is_direct"]),
            "parent_component": parent_name,
            "description": row["description"],
        }

    @tool(
        description="Search for vulnerabilities affecting a specific component. Returns a paginated list of CVE identifiers and severity levels. Use page and page_size to iterate through results.",
        parameters={
            "type": "object",
            "properties": {
                "component_name": {
                    "type": "string",
                    "description": "Component name to search vulnerabilities for",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Defaults to 10. Max 50.",
                },
            },
            "required": ["component_name"],
        },
    )
    def search_component_vulnerabilities(self, component_name: str, page: int = 1, page_size: int = 10) -> dict:
        page_size = min(page_size, 50)
        offset = (max(1, page) - 1) * page_size

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(*) as cnt FROM vulnerabilities WHERE component_name = ?",
            (component_name,),
        )
        total = cur.fetchone()["cnt"]

        cur.execute(
            """SELECT cve_id, severity, cvss_score, published_date
               FROM vulnerabilities
               WHERE component_name = ?
               ORDER BY cvss_score DESC
               LIMIT ? OFFSET ?""",
            (component_name, page_size, offset),
        )
        results = [dict(r) for r in cur.fetchall()]
        conn.close()

        return {
            "component_name": component_name,
            "total_results": total,
            "page": page,
            "page_size": page_size,
            "results": results,
        }

    @tool(
        description="Retrieve the dependency chain for a component: its parent dependencies up to the root direct dependency. Useful for understanding how a transitive dependency enters the dependency tree.",
        parameters={
            "type": "object",
            "properties": {
                "component_name": {
                    "type": "string",
                    "description": "The component name to trace",
                },
            },
            "required": ["component_name"],
        },
    )
    def get_dependency_chain(self, component_name: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT * FROM components WHERE name = ?", (component_name,))
        comp = cur.fetchone()
        if comp is None:
            conn.close()
            return {"error": f"Component {component_name} not found"}

        chain = [{
            "name": comp["name"],
            "version": comp["version"],
            "is_direct": bool(comp["is_direct"]),
        }]

        current = comp
        visited = {comp["id"]}
        while current["parent_id"] and current["parent_id"] not in visited:
            visited.add(current["parent_id"])
            cur.execute("SELECT * FROM components WHERE id = ?", (current["parent_id"],))
            parent = cur.fetchone()
            if parent is None:
                break
            chain.append({
                "name": parent["name"],
                "version": parent["version"],
                "is_direct": bool(parent["is_direct"]),
            })
            current = parent

        conn.close()
        return {
            "component_name": component_name,
            "chain": chain,
            "depth": len(chain),
        }

    # -----------------------------------------------------------------------
    # Evaluation
    # -----------------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute the expected patch schedule from DB + workspace config."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Load policy config from workspace
        policy_path = os.path.join(self.workspace, "prioritization_policy.json")
        with open(policy_path) as f:
            policy = json.load(f)

        crit_path = os.path.join(self.workspace, "service_criticality.yaml")
        service_tiers = {}
        with open(crit_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or not line or line.startswith("service_tiers"):
                    continue
                parts = line.split(":")
                if len(parts) == 2:
                    svc = parts[0].strip()
                    tier = parts[1].strip()
                    service_tiers[svc] = tier

        sev_weights = policy["severity_weights"]
        crit_mults = policy["service_criticality_multipliers"]
        included_sev = policy["included_severities"]
        ref_date = policy["reference_date"]
        deadlines = policy["patch_deadlines_days"]

        # Get all transitive components with high-severity vulnerabilities that have fixes
        cur.execute("""
            SELECT v.cve_id, v.component_name, v.affected_version, v.fixed_version,
                   v.severity, v.cvss_score, c.id as comp_id, c.parent_id
            FROM vulnerabilities v
            JOIN components c ON v.component_name = c.name
            WHERE c.is_direct = 0
              AND v.severity IN ({})
              AND v.fixed_version IS NOT NULL
        """.format(",".join("?" for _ in included_sev)), included_sev)

        candidates = [dict(r) for r in cur.fetchall()]

        schedule = []
        for cand in candidates:
            # Resolve direct ancestor(s) to find production services
            direct_ancestor_ids = set()
            stack = [cand["parent_id"]]
            visited = set()
            while stack:
                pid = stack.pop()
                if pid is None or pid in visited:
                    continue
                visited.add(pid)
                cur.execute("SELECT id, is_direct, parent_id FROM components WHERE id = ?", (pid,))
                p = cur.fetchone()
                if p is None:
                    continue
                if p["is_direct"]:
                    direct_ancestor_ids.add(p["id"])
                else:
                    stack.append(p["parent_id"])

            # Find active production services for direct ancestors
            affected_services = set()
            for da_id in direct_ancestor_ids:
                cur.execute(
                    """SELECT service_name FROM deployments
                       WHERE component_id = ? AND environment = 'production' AND is_active = 1""",
                    (da_id,),
                )
                for row in cur.fetchall():
                    affected_services.add(row["service_name"])

            if not affected_services:
                continue

            # Compute priority score
            sev_w = sev_weights.get(cand["severity"], 1)
            max_mult = max(
                crit_mults.get(service_tiers.get(svc, "standard"), 1.0)
                for svc in affected_services
            )
            priority_score = round(cand["cvss_score"] * sev_w * max_mult, 2)

            # Compute patch deadline
            deadline_days = deadlines.get(cand["severity"], 90)
            ref = datetime.strptime(ref_date, "%Y-%m-%d")
            patch_deadline = (ref + timedelta(days=deadline_days)).strftime("%Y-%m-%d")

            schedule.append({
                "cve_id": cand["cve_id"],
                "component_name": cand["component_name"],
                "current_version": cand["affected_version"],
                "patched_version": cand["fixed_version"],
                "severity": cand["severity"],
                "cvss_score": cand["cvss_score"],
                "priority_score": priority_score,
                "affected_services": ";".join(sorted(affected_services)),
                "patch_deadline": patch_deadline,
            })

        conn.close()

        # Sort: priority_score desc, cvss_score desc, cve_id asc
        schedule.sort(key=lambda x: (-x["priority_score"], -x["cvss_score"], x["cve_id"]))

        # Assign ranks
        for i, entry in enumerate(schedule):
            entry["rank"] = i + 1

        return schedule

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
        gt_count = len(ground_truth)

        criteria = {}
        total_score = 0
        max_score = 0

        # ---- Criterion 1: patch_schedule.csv exists and is parseable (10 pts) ----
        csv_path = os.path.join(self.workspace, "patch_schedule.csv")
        csv_exists = os.path.exists(csv_path)
        csv_rows = []
        csv_parse_ok = False
        expected_cols = [
            "rank", "cve_id", "component_name", "current_version", "patched_version",
            "severity", "cvss_score", "priority_score", "affected_services", "patch_deadline",
        ]

        if csv_exists:
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    csv_rows = list(reader)
                    if reader.fieldnames and set(expected_cols).issubset(set(reader.fieldnames)):
                        csv_parse_ok = True
            except Exception:
                pass

        c1_score = 0
        if csv_exists and csv_parse_ok:
            c1_score = 10
        elif csv_exists:
            c1_score = 5
        criteria["output_file_format"] = {
            "passed": c1_score == 10,
            "score": c1_score,
            "max_score": 10,
            "reason": "" if c1_score == 10 else "File missing or columns incorrect",
        }
        total_score += c1_score
        max_score += 10

        # ---- Criterion 2: Correct CVE identification (20 pts) ----
        gt_cves = {e["cve_id"] for e in ground_truth}
        agent_cves = {r.get("cve_id", "").strip() for r in csv_rows}

        if gt_cves:
            correct_cves = gt_cves & agent_cves
            extra_cves = agent_cves - gt_cves
            precision = len(correct_cves) / len(agent_cves) if agent_cves else 0
            recall = len(correct_cves) / len(gt_cves)
            f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0
            c2_score = round(20 * f1)
        else:
            c2_score = 20 if not agent_cves else 0

        criteria["cve_identification"] = {
            "passed": c2_score >= 18,
            "score": c2_score,
            "max_score": 20,
            "reason": "" if c2_score >= 18 else f"Expected {len(gt_cves)} CVEs, got {len(agent_cves)} ({len(gt_cves & agent_cves)} correct)",
        }
        total_score += c2_score
        max_score += 20

        # ---- Criterion 3: Correct patched versions (15 pts) ----
        gt_patches = {e["cve_id"]: e["patched_version"] for e in ground_truth}
        agent_patches = {}
        for r in csv_rows:
            cve = r.get("cve_id", "").strip()
            pv = r.get("patched_version", "").strip()
            if cve:
                agent_patches[cve] = pv

        correct_patches = 0
        for cve, expected_pv in gt_patches.items():
            if agent_patches.get(cve) == expected_pv:
                correct_patches += 1

        c3_score = round(15 * correct_patches / len(gt_patches)) if gt_patches else 15
        criteria["patched_versions"] = {
            "passed": c3_score >= 13,
            "score": c3_score,
            "max_score": 15,
            "reason": "" if c3_score >= 13 else f"{correct_patches}/{len(gt_patches)} correct",
        }
        total_score += c3_score
        max_score += 15

        # ---- Criterion 4: Correct affected services (15 pts) ----
        gt_services = {e["cve_id"]: set(e["affected_services"].split(";")) for e in ground_truth}
        correct_svc = 0
        for r in csv_rows:
            cve = r.get("cve_id", "").strip()
            if cve in gt_services:
                agent_svcs = set(s.strip() for s in r.get("affected_services", "").split(";") if s.strip())
                if agent_svcs == gt_services[cve]:
                    correct_svc += 1

        c4_score = round(15 * correct_svc / len(gt_services)) if gt_services else 15
        criteria["affected_services"] = {
            "passed": c4_score >= 13,
            "score": c4_score,
            "max_score": 15,
            "reason": "" if c4_score >= 13 else f"{correct_svc}/{len(gt_services)} correct",
        }
        total_score += c4_score
        max_score += 15

        # ---- Criterion 5: Correct priority scores (20 pts) ----
        gt_pscores = {e["cve_id"]: e["priority_score"] for e in ground_truth}
        correct_ps = 0
        for r in csv_rows:
            cve = r.get("cve_id", "").strip()
            if cve in gt_pscores:
                try:
                    agent_ps = round(float(r.get("priority_score", "0")), 2)
                    if abs(agent_ps - gt_pscores[cve]) < 0.01:
                        correct_ps += 1
                except (ValueError, TypeError):
                    pass

        c5_score = round(20 * correct_ps / len(gt_pscores)) if gt_pscores else 20
        criteria["priority_scores"] = {
            "passed": c5_score >= 18,
            "score": c5_score,
            "max_score": 20,
            "reason": "" if c5_score >= 18 else f"{correct_ps}/{len(gt_pscores)} correct",
        }
        total_score += c5_score
        max_score += 20

        # ---- Criterion 6: Correct ranking order (10 pts) ----
        gt_order = [e["cve_id"] for e in ground_truth]
        agent_order = [r.get("cve_id", "").strip() for r in csv_rows]

        # Check if the top-N match in order (where N = min of both lengths)
        n_check = min(len(gt_order), len(agent_order))
        order_correct = 0
        if n_check > 0:
            for k in range(n_check):
                if gt_order[k] == agent_order[k]:
                    order_correct += 1
            c6_score = round(10 * order_correct / n_check)
        else:
            c6_score = 0

        criteria["ranking_order"] = {
            "passed": c6_score >= 8,
            "score": c6_score,
            "max_score": 10,
            "reason": "" if c6_score >= 8 else f"{order_correct}/{n_check} positions correct",
        }
        total_score += c6_score
        max_score += 10

        # ---- Criterion 7: Response summary (10 pts) ----
        c7_score = 0
        action_lower = action.lower() if action else ""
        # Check that the response mentions the total count
        if str(gt_count) in action:
            c7_score += 4
        # Check for mention of severity breakdown
        n_critical = sum(1 for e in ground_truth if e["severity"] == "Critical")
        n_high = sum(1 for e in ground_truth if e["severity"] == "High")
        if str(n_critical) in action and str(n_high) in action:
            c7_score += 3
        # Check top 3 CVEs mentioned
        top3 = [e["cve_id"] for e in ground_truth[:3]]
        mentioned_top3 = sum(1 for cve in top3 if cve in action)
        c7_score += min(3, mentioned_top3)

        criteria["response_summary"] = {
            "passed": c7_score >= 8,
            "score": c7_score,
            "max_score": 10,
            "reason": "" if c7_score >= 8 else "Missing summary elements in response",
        }
        total_score += c7_score
        max_score += 10

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return reward, info

    # -----------------------------------------------------------------------
    # Verification
    # -----------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import glob as glob_mod

        # Step 1: Read SBOM files to identify transitive components
        sbom_files = sorted(glob_mod.glob(os.path.join(self.workspace, "sbom_*.json")))
        transitive_components = {}  # name -> {version, parent_component}
        for sf in sbom_files:
            with open(sf) as f:
                sbom = json.load(f)
            for comp in sbom.get("components", []):
                if comp.get("dependency_type") == "transitive":
                    transitive_components[comp["name"]] = {
                        "version": comp["version"],
                        "parent_component": comp.get("parent_component"),
                    }

        # Step 2: Read vulnerability feed CSVs to find CVEs affecting transitive components
        vuln_files = sorted(glob_mod.glob(os.path.join(self.workspace, "vuln_feed_*.csv")))
        candidate_cves = []  # (cve_id, component_name, severity)
        for vf in vuln_files:
            with open(vf) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    comp = row["component_name"].strip()
                    sev = row["severity"].strip()
                    if comp in transitive_components and sev in ("Critical", "High"):
                        candidate_cves.append((row["cve_id"].strip(), comp, sev))

        # Step 3: Read policy config
        with open(os.path.join(self.workspace, "prioritization_policy.json")) as f:
            policy = json.load(f)

        sev_weights = policy["severity_weights"]
        crit_mults = policy["service_criticality_multipliers"]
        ref_date = policy["reference_date"]
        deadlines = policy["patch_deadlines_days"]

        # Step 4: Read service criticality
        service_tiers = {}
        with open(os.path.join(self.workspace, "service_criticality.yaml")) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or not line or line.startswith("service_tiers"):
                    continue
                parts = line.split(":")
                if len(parts) == 2:
                    service_tiers[parts[0].strip()] = parts[1].strip()

        # Step 5: For each candidate CVE, use tools to get details and check patch
        tool_call_count = 0
        schedule_entries = []

        for cve_id, comp_name, sev in candidate_cves:
            # Tool call: get vulnerability details (for CVSS score and fixed version)
            vuln_details = self.tools["get_vulnerability_details"](cve_id=cve_id)
            tool_call_count += 1

            if "error" in vuln_details:
                continue
            if vuln_details.get("fixed_version") is None:
                continue

            cvss = vuln_details["cvss_score"]
            fixed_ver = vuln_details["fixed_version"]
            current_ver = vuln_details["affected_version"]

            # Tool call: check patch available (confirms fix exists)
            patch_info = self.tools["check_patch_available"](
                component_name=comp_name, current_version=current_ver
            )
            tool_call_count += 1

            if not patch_info.get("patch_available"):
                continue

            # Tool call: get active services
            svc_info = self.tools["get_active_services"](component_name=comp_name)
            tool_call_count += 1

            active_svcs = svc_info.get("active_production_services", [])
            if not active_svcs:
                continue

            svc_names = sorted(s["service_name"] for s in active_svcs)

            # Compute priority score
            sev_w = sev_weights.get(sev, 1)
            max_mult = max(
                crit_mults.get(service_tiers.get(s, "standard"), 1.0)
                for s in svc_names
            )
            priority_score = round(cvss * sev_w * max_mult, 2)

            # Compute deadline
            deadline_days = deadlines.get(sev, 90)
            ref = datetime.strptime(ref_date, "%Y-%m-%d")
            patch_deadline = (ref + timedelta(days=deadline_days)).strftime("%Y-%m-%d")

            schedule_entries.append({
                "cve_id": cve_id,
                "component_name": comp_name,
                "current_version": current_ver,
                "patched_version": fixed_ver,
                "severity": sev,
                "cvss_score": cvss,
                "priority_score": priority_score,
                "affected_services": ";".join(svc_names),
                "patch_deadline": patch_deadline,
            })

        # Sort: priority_score desc, cvss_score desc, cve_id asc
        schedule_entries.sort(
            key=lambda x: (-x["priority_score"], -x["cvss_score"], x["cve_id"])
        )

        # Assign ranks
        for i, entry in enumerate(schedule_entries):
            entry["rank"] = i + 1

        # Write patch_schedule.csv
        csv_path = os.path.join(self.workspace, "patch_schedule.csv")
        fieldnames = [
            "rank", "cve_id", "component_name", "current_version", "patched_version",
            "severity", "cvss_score", "priority_score", "affected_services", "patch_deadline",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for entry in schedule_entries:
                writer.writerow(entry)

        # Build summary action string
        n_total = len(schedule_entries)
        n_critical = sum(1 for e in schedule_entries if e["severity"] == "Critical")
        n_high = sum(1 for e in schedule_entries if e["severity"] == "High")
        top3 = schedule_entries[:3]
        top3_str = ", ".join(
            f"{e['cve_id']} ({e['component_name']})" for e in top3
        )

        action = (
            f"Patch schedule generated with {n_total} entries. "
            f"Severity breakdown: {n_critical} Critical, {n_high} High. "
            f"Top 3 priorities: {top3_str}. "
            f"Results saved to patch_schedule.csv."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made"

        return self.step(action)
