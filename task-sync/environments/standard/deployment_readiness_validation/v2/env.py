"""
Environment for Microservice Deployment Readiness Validation task.
"""

import os
import json
import csv
import sqlite3
from typing import Tuple, Dict, List, Any


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

    # ----------------------------------------------------------------
    # Tool methods
    # ----------------------------------------------------------------

    @tool(
        description="List microservices with pagination. Returns a page of services with their basic info (id, name, team, namespace, priority). Use page and page_size to paginate through all services.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of services per page (max 20).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_services(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM microservices").fetchone()[0]
        rows = cur.execute(
            "SELECT id, name, team, namespace, priority FROM microservices ORDER BY id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "services": [dict(r) for r in rows],
        }

    @tool(
        description="Get detailed information about a specific microservice by its ID, including image registry, image tag, namespace, team, priority, and last deployment date.",
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "integer",
                    "description": "The microservice ID.",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_service_info(self, service_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM microservices WHERE id = ?", (service_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Service {service_id} not found"}
        return dict(row)

    @tool(
        description="Retrieve vulnerability scan results for a specific service. Returns all CVEs found for that service with severity, CVSS score, status, and package info.",
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "integer",
                    "description": "The microservice ID to get vulnerability scans for.",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_vulnerability_report(self, service_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT cve_id, severity, cvss_score, status, package_name, scan_date "
            "FROM vulnerability_scans WHERE service_id = ? ORDER BY cvss_score DESC",
            (service_id,),
        ).fetchall()
        conn.close()
        return {
            "service_id": service_id,
            "total_vulnerabilities": len(rows),
            "vulnerabilities": [dict(r) for r in rows],
        }

    @tool(
        description="Get the current resource quota and usage for a specific namespace and resource type. Returns the most recent quota snapshot (highest last_updated date) for that namespace-resource combination.",
        parameters={
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "The Kubernetes namespace to check.",
                },
                "resource_type": {
                    "type": "string",
                    "enum": ["cpu_cores", "memory_gb", "storage_gb", "pod_count"],
                    "description": "The type of resource to query.",
                },
            },
            "required": ["namespace", "resource_type"],
        },
    )
    def get_namespace_quota(self, namespace: str, resource_type: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM resource_quotas WHERE namespace = ? AND resource_type = ? "
            "ORDER BY last_updated DESC LIMIT 1",
            (namespace, resource_type),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"No quota found for {namespace}/{resource_type}"}
        return dict(row)

    @tool(
        description="Get all dependencies for a specific service, including their health status, criticality level, protocol, and latency. Returns the list of services that the given service depends on.",
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "integer",
                    "description": "The microservice ID to get dependencies for.",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_service_dependencies(self, service_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT depends_on_service_id, depends_on_service_name, criticality, "
            "protocol, health_status, latency_ms, last_checked "
            "FROM dependency_map WHERE service_id = ? ORDER BY criticality, depends_on_service_name",
            (service_id,),
        ).fetchall()
        conn.close()
        return {
            "service_id": service_id,
            "total_dependencies": len(rows),
            "dependencies": [dict(r) for r in rows],
        }

    @tool(
        description="Get change request information for a specific service. Returns all change requests associated with the service, including status, approver count, and risk level.",
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "integer",
                    "description": "The microservice ID to get change requests for.",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_change_requests(self, service_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT cr_number, title, status, submitted_by, approvers, num_approvals, "
            "submitted_date, resolved_date, risk_level "
            "FROM change_requests WHERE service_id = ? ORDER BY submitted_date DESC",
            (service_id,),
        ).fetchall()
        conn.close()
        return {
            "service_id": service_id,
            "total_change_requests": len(rows),
            "change_requests": [dict(r) for r in rows],
        }

    # ----------------------------------------------------------------
    # Evaluation
    # ----------------------------------------------------------------

    def _compute_ground_truth(self) -> dict:
        """Compute the expected go/no-go decisions for all pending services."""
        import yaml

        # Load policy
        with open(os.path.join(self.workspace, "deployment_policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)

        # Load risk scoring
        risk_map = {}
        with open(os.path.join(self.workspace, "risk_scoring.csv"), "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                risk_map[row["severity"]] = float(row["risk_score"])

        # Load namespace buffers
        with open(os.path.join(self.workspace, "namespace_resource_buffer.json"), "r") as f:
            ns_buffers = json.load(f)

        # Find all deployment request files
        deploy_requests = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("deploy_request_"):
                deploy_requests[fname] = self._parse_deploy_request(
                    os.path.join(self.workspace, fname)
                )

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        vuln_policy = policy["vulnerability_policy"]
        res_policy = policy["resource_policy"]
        dep_policy = policy["dependency_policy"]
        cr_policy = policy["change_request_policy"]
        priority_override = policy["priority_override"]
        excluded_statuses = vuln_policy["excluded_statuses"]

        results = {}
        for fname, req in sorted(deploy_requests.items()):
            svc_name = req["service_name"]
            svc_id = int(req["service_id"])
            namespace = req["target_namespace"]
            req_cpu = float(req["requested_cpu_cores"])
            req_mem = float(req["requested_memory_gb"])

            # Get service priority
            svc_row = conn.execute(
                "SELECT priority FROM microservices WHERE id = ?", (svc_id,)
            ).fetchone()
            svc_priority = svc_row["priority"] if svc_row else "medium"

            blockers = []

            # --- Vulnerability check ---
            vulns = conn.execute(
                "SELECT severity, status FROM vulnerability_scans WHERE service_id = ?",
                (svc_id,),
            ).fetchall()

            # Count actionable vulns (not mitigated/false_positive)
            actionable = [v for v in vulns if v["status"] not in excluded_statuses]
            critical_count = sum(1 for v in actionable if v["severity"] == "critical")
            high_count = sum(1 for v in actionable if v["severity"] == "high")

            # Risk score
            vuln_risk_score = sum(risk_map.get(v["severity"], 0) for v in actionable)
            vuln_risk_score = round(vuln_risk_score, 2)

            if critical_count > vuln_policy["max_critical_open"]:
                blockers.append(f"VULN: {critical_count} critical open vulnerabilities (max {vuln_policy['max_critical_open']})")

            if high_count > vuln_policy["max_high_open"]:
                blockers.append(f"VULN: {high_count} high open vulnerabilities (max {vuln_policy['max_high_open']})")

            # Priority override: critical services cannot have any high vulns
            if svc_priority == "critical" and priority_override.get("critical_services_require_zero_high_vulns", False):
                if high_count > 0:
                    blockers.append(f"VULN: critical-priority service has {high_count} high vulnerabilities (must be 0)")

            if vuln_risk_score > vuln_policy["max_risk_score"]:
                blockers.append(f"VULN: risk score {vuln_risk_score} exceeds max {vuln_policy['max_risk_score']}")

            vuln_pass = len([b for b in blockers if b.startswith("VULN:")]) == 0

            # --- Resource check ---
            resource_pass = True
            resource_blockers = []
            for rt in res_policy["required_resource_checks"]:
                quota_row = conn.execute(
                    "SELECT quota_limit, current_usage FROM resource_quotas "
                    "WHERE namespace = ? AND resource_type = ? ORDER BY last_updated DESC LIMIT 1",
                    (namespace, rt),
                ).fetchone()
                if quota_row is None:
                    resource_blockers.append(f"RES: no quota data for {namespace}/{rt}")
                    resource_pass = False
                    continue

                limit = quota_row["quota_limit"]
                current = quota_row["current_usage"]

                # Get buffer for this namespace
                buffer_key = f"{rt}_reserved"
                buffer_val = 0.0
                if namespace in ns_buffers:
                    buffer_val = ns_buffers[namespace].get(buffer_key, 0.0)

                requested = req_cpu if rt == "cpu_cores" else req_mem
                projected = current + requested + buffer_val
                utilization = projected / limit if limit > 0 else 1.0

                if utilization > res_policy["max_utilization_after_deploy"]:
                    resource_blockers.append(
                        f"RES: {rt} projected utilization {utilization:.4f} exceeds max {res_policy['max_utilization_after_deploy']}"
                    )
                    resource_pass = False

            blockers.extend(resource_blockers)

            # --- Dependency check ---
            deps = conn.execute(
                "SELECT criticality, health_status FROM dependency_map WHERE service_id = ?",
                (svc_id,),
            ).fetchall()

            dep_pass = True
            if deps:
                for d in deps:
                    if d["criticality"] == "critical" and dep_policy["critical_must_be_healthy"]:
                        if d["health_status"] != "healthy":
                            blockers.append(
                                f"DEP: critical dependency is {d['health_status']}"
                            )
                            dep_pass = False
                    if dep_policy["unhealthy_blocks_deploy"] and d["health_status"] == "unhealthy":
                        blockers.append("DEP: unhealthy dependency detected")
                        dep_pass = False

                standard_deps = [d for d in deps if d["criticality"] == "standard"]
                if standard_deps:
                    degraded_standard = sum(
                        1 for d in standard_deps if d["health_status"] in ("degraded", "unknown")
                    )
                    ratio = degraded_standard / len(standard_deps)
                    if ratio > dep_policy["max_degraded_standard_ratio"]:
                        blockers.append(
                            f"DEP: {degraded_standard}/{len(standard_deps)} standard deps degraded/unknown (ratio {ratio:.4f} > max {dep_policy['max_degraded_standard_ratio']})"
                        )
                        dep_pass = False

            # --- Change request check ---
            crs = conn.execute(
                "SELECT status, num_approvals FROM change_requests WHERE service_id = ?",
                (svc_id,),
            ).fetchall()

            cr_pass = False
            if crs:
                for cr in crs:
                    if cr["status"] in cr_policy["required_status"] and cr["num_approvals"] >= cr_policy["min_approvals"]:
                        cr_pass = True
                        break

            if not cr_pass:
                blockers.append(
                    f"CR: no approved change request with >= {cr_policy['min_approvals']} approvals"
                )

            # Deduplicate blockers
            seen = set()
            unique_blockers = []
            for b in blockers:
                if b not in seen:
                    seen.add(b)
                    unique_blockers.append(b)
            blockers = unique_blockers

            decision = "GO" if len(blockers) == 0 else "NO-GO"

            results[svc_name] = {
                "service_name": svc_name,
                "service_id": svc_id,
                "decision": decision,
                "vulnerability_risk_score": vuln_risk_score,
                "vulnerability_check": "PASS" if vuln_pass else "FAIL",
                "resource_check": "PASS" if resource_pass else "FAIL",
                "dependency_check": "PASS" if dep_pass else "FAIL",
                "cr_check": "PASS" if cr_pass else "FAIL",
                "blockers": blockers,
            }

        conn.close()

        # Summary
        go_list = sorted([r["service_name"] for r in results.values() if r["decision"] == "GO"])
        nogo_list = sorted([r["service_name"] for r in results.values() if r["decision"] == "NO-GO"])

        return {
            "services": results,
            "go_services": go_list,
            "nogo_services": nogo_list,
            "total": len(results),
            "go_count": len(go_list),
            "nogo_count": len(nogo_list),
        }

    def _parse_deploy_request(self, filepath: str) -> dict:
        """Parse a deployment request file regardless of format."""
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".yaml":
            import yaml
            with open(filepath, "r") as f:
                return yaml.safe_load(f)
        elif ext == ".json":
            with open(filepath, "r") as f:
                return json.load(f)
        elif ext == ".csv":
            with open(filepath, "r") as f:
                reader = csv.DictReader(f)
                return next(reader)
        elif ext == ".txt":
            data = {}
            with open(filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    if ":" in line and not line.startswith("="):
                        key, _, val = line.partition(":")
                        data[key.strip()] = val.strip()
            return data
        elif ext == ".md":
            data = {}
            with open(filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("|") and "---" not in line and "Field" not in line:
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) == 2:
                            data[parts[0]] = parts[1]
            return data
        return {}

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
        gt = self._compute_ground_truth()
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: deployment_manifest.json exists and is valid JSON (10 pts) ---
        manifest_path = os.path.join(self.workspace, "deployment_manifest.json")
        manifest = None
        c1_pass = False
        c1_reason = ""
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
            if isinstance(manifest, dict) and "services" in manifest:
                c1_pass = True
            else:
                c1_reason = "manifest missing 'services' key"
        except FileNotFoundError:
            c1_reason = "deployment_manifest.json not found"
        except json.JSONDecodeError:
            c1_reason = "deployment_manifest.json is not valid JSON"

        eval_criteria["manifest_structure"] = {
            "passed": c1_pass,
            "score": 10 if c1_pass else 0,
            "max_score": 10,
            "reason": c1_reason if not c1_pass else "",
        }
        total_score += eval_criteria["manifest_structure"]["score"]
        max_score += 10

        # --- Criterion 2: Correct go/no-go decisions (30 pts) ---
        c2_score = 0
        c2_max = 30
        c2_reason = ""
        if manifest and "services" in manifest:
            manifest_services = manifest["services"]
            if isinstance(manifest_services, list):
                manifest_map = {}
                for ms in manifest_services:
                    if isinstance(ms, dict) and "service_name" in ms:
                        manifest_map[ms["service_name"]] = ms.get("decision", "").upper()
            elif isinstance(manifest_services, dict):
                manifest_map = {}
                for k, v in manifest_services.items():
                    if isinstance(v, dict):
                        manifest_map[k] = v.get("decision", "").upper()
                    else:
                        manifest_map[k] = str(v).upper()
            else:
                manifest_map = {}

            correct = 0
            expected_total = len(gt["services"])
            for svc_name, gt_data in gt["services"].items():
                if svc_name in manifest_map:
                    if manifest_map[svc_name] == gt_data["decision"]:
                        correct += 1

            if expected_total > 0:
                c2_score = round(c2_max * correct / expected_total)
            c2_reason = f"{correct}/{expected_total} correct decisions" if correct < expected_total else ""
        else:
            c2_reason = "no valid manifest to check"

        eval_criteria["go_nogo_decisions"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": c2_reason if c2_score < c2_max else "",
        }
        total_score += c2_score
        max_score += c2_max

        # --- Criterion 3: Vulnerability risk scores (15 pts) ---
        c3_score = 0
        c3_max = 15
        c3_reason = ""
        if manifest and "services" in manifest:
            manifest_services = manifest["services"]
            if isinstance(manifest_services, list):
                ms_list = manifest_services
            elif isinstance(manifest_services, dict):
                ms_list = list(manifest_services.values())
            else:
                ms_list = []

            ms_risk_map = {}
            for ms in ms_list:
                if isinstance(ms, dict) and "service_name" in ms and "vulnerability_risk_score" in ms:
                    try:
                        ms_risk_map[ms["service_name"]] = float(ms["vulnerability_risk_score"])
                    except (ValueError, TypeError):
                        pass

            correct_risk = 0
            expected_total = len(gt["services"])
            for svc_name, gt_data in gt["services"].items():
                if svc_name in ms_risk_map:
                    if abs(ms_risk_map[svc_name] - gt_data["vulnerability_risk_score"]) < 0.1:
                        correct_risk += 1

            if expected_total > 0:
                c3_score = round(c3_max * correct_risk / expected_total)
            c3_reason = f"{correct_risk}/{expected_total} correct risk scores" if correct_risk < expected_total else ""
        else:
            c3_reason = "no valid manifest to check"

        eval_criteria["vulnerability_risk_scores"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": c3_reason if c3_score < c3_max else "",
        }
        total_score += c3_score
        max_score += c3_max

        # --- Criterion 4: Per-service check fields (15 pts) ---
        c4_score = 0
        c4_max = 15
        c4_reason = ""
        check_fields = ["vulnerability_check", "resource_check", "dependency_check", "cr_check"]
        if manifest and "services" in manifest:
            manifest_services = manifest["services"]
            if isinstance(manifest_services, list):
                ms_list = manifest_services
            elif isinstance(manifest_services, dict):
                ms_list = list(manifest_services.values())
            else:
                ms_list = []

            total_checks = 0
            correct_checks = 0
            for ms in ms_list:
                if not isinstance(ms, dict) or "service_name" not in ms:
                    continue
                svc_name = ms["service_name"]
                if svc_name not in gt["services"]:
                    continue
                gt_svc = gt["services"][svc_name]
                for field in check_fields:
                    total_checks += 1
                    ms_val = str(ms.get(field, "")).upper()
                    gt_val = gt_svc[field].upper()
                    if ms_val == gt_val:
                        correct_checks += 1

            if total_checks > 0:
                c4_score = round(c4_max * correct_checks / total_checks)
            c4_reason = f"{correct_checks}/{total_checks} correct check fields" if correct_checks < total_checks else ""
        else:
            c4_reason = "no valid manifest to check"

        eval_criteria["per_service_checks"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": c4_reason if c4_score < c4_max else "",
        }
        total_score += c4_score
        max_score += c4_max

        # --- Criterion 5: Summary counts in manifest (10 pts) ---
        c5_score = 0
        c5_max = 10
        c5_reason = ""
        if manifest and "summary" in manifest and isinstance(manifest["summary"], dict):
            summary = manifest["summary"]
            try:
                total_ok = int(summary.get("total_services", -1)) == gt["total"]
                go_ok = int(summary.get("go_count", -1)) == gt["go_count"]
                nogo_ok = int(summary.get("nogo_count", -1)) == gt["nogo_count"]
                if total_ok and go_ok and nogo_ok:
                    c5_score = c5_max
                else:
                    parts = []
                    if not total_ok:
                        parts.append(f"total_services: got {summary.get('total_services')}, expected {gt['total']}")
                    if not go_ok:
                        parts.append(f"go_count: got {summary.get('go_count')}, expected {gt['go_count']}")
                    if not nogo_ok:
                        parts.append(f"nogo_count: got {summary.get('nogo_count')}, expected {gt['nogo_count']}")
                    c5_reason = "; ".join(parts)
            except (ValueError, TypeError) as e:
                c5_reason = f"summary parsing error: {e}"
        else:
            c5_reason = "manifest missing 'summary' key"

        eval_criteria["manifest_summary"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": c5_reason if c5_score < c5_max else "",
        }
        total_score += c5_score
        max_score += c5_max

        # --- Criterion 6: Response contains correct GO/NO-GO service lists (20 pts) ---
        c6_score = 0
        c6_max = 20
        c6_reason = ""
        action_upper = action.upper() if action else ""

        # Check GO services listed in response
        go_found = 0
        for svc in gt["go_services"]:
            if svc in action:
                go_found += 1

        nogo_found = 0
        for svc in gt["nogo_services"]:
            if svc in action:
                nogo_found += 1

        total_expected = len(gt["go_services"]) + len(gt["nogo_services"])
        total_found = go_found + nogo_found

        # Also check that GO/NO-GO labels are correctly associated
        # Look for patterns like "service_name: GO" or "service_name - GO"
        correct_labels = 0
        for svc_name, gt_data in gt["services"].items():
            if svc_name in action:
                # Check if the decision label appears near the service name
                idx = action.find(svc_name)
                if idx >= 0:
                    # Check a window around the service name
                    window = action[idx:idx + len(svc_name) + 50]
                    if gt_data["decision"] in window.upper():
                        correct_labels += 1

        if total_expected > 0:
            # Half points for mentioning services, half for correct labels
            mention_score = round((c6_max / 2) * total_found / total_expected)
            label_score = round((c6_max / 2) * correct_labels / total_expected)
            c6_score = mention_score + label_score

        reasons = []
        if total_found < total_expected:
            reasons.append(f"{total_found}/{total_expected} services mentioned in response")
        if correct_labels < total_expected:
            reasons.append(f"{correct_labels}/{total_expected} correct decision labels in response")
        c6_reason = "; ".join(reasons)

        eval_criteria["response_service_decisions"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": c6_reason if c6_score < c6_max else "",
        }
        total_score += c6_score
        max_score += c6_max

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml

        # Step 1: Read workspace files to discover deployment requests and policy
        workspace_files = os.listdir(self.workspace)

        # Read policy
        with open(os.path.join(self.workspace, "deployment_policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)

        # Read risk scoring
        risk_map = {}
        with open(os.path.join(self.workspace, "risk_scoring.csv"), "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                risk_map[row["severity"]] = float(row["risk_score"])

        # Read namespace buffers
        with open(os.path.join(self.workspace, "namespace_resource_buffer.json"), "r") as f:
            ns_buffers = json.load(f)

        # Parse all deployment request files
        deploy_requests = {}
        for fname in workspace_files:
            if fname.startswith("deploy_request_"):
                filepath = os.path.join(self.workspace, fname)
                deploy_requests[fname] = self._parse_deploy_request(filepath)

        vuln_policy = policy["vulnerability_policy"]
        res_policy = policy["resource_policy"]
        dep_policy = policy["dependency_policy"]
        cr_policy = policy["change_request_policy"]
        priority_override = policy["priority_override"]
        excluded_statuses = vuln_policy["excluded_statuses"]

        # Step 2: For each pending service, call tools to gather data and make decisions
        tool_call_count = 0
        results = []

        for fname, req in sorted(deploy_requests.items()):
            svc_name = req["service_name"]
            svc_id = int(req["service_id"])
            namespace = req["target_namespace"]
            req_cpu = float(req["requested_cpu_cores"])
            req_mem = float(req["requested_memory_gb"])

            # Get service info via tool
            svc_info = self.tools["get_service_info"](service_id=svc_id)
            tool_call_count += 1
            svc_priority = svc_info.get("priority", "medium")

            blockers = []

            # --- Vulnerability check via tool ---
            vuln_report = self.tools["get_vulnerability_report"](service_id=svc_id)
            tool_call_count += 1

            actionable = [
                v for v in vuln_report["vulnerabilities"]
                if v["status"] not in excluded_statuses
            ]
            critical_count = sum(1 for v in actionable if v["severity"] == "critical")
            high_count = sum(1 for v in actionable if v["severity"] == "high")
            vuln_risk_score = sum(risk_map.get(v["severity"], 0) for v in actionable)
            vuln_risk_score = round(vuln_risk_score, 2)

            if critical_count > vuln_policy["max_critical_open"]:
                blockers.append(
                    f"VULN: {critical_count} critical open vulnerabilities (max {vuln_policy['max_critical_open']})"
                )
            if high_count > vuln_policy["max_high_open"]:
                blockers.append(
                    f"VULN: {high_count} high open vulnerabilities (max {vuln_policy['max_high_open']})"
                )
            if svc_priority == "critical" and priority_override.get("critical_services_require_zero_high_vulns", False):
                if high_count > 0:
                    blockers.append(
                        f"VULN: critical-priority service has {high_count} high vulnerabilities (must be 0)"
                    )
            if vuln_risk_score > vuln_policy["max_risk_score"]:
                blockers.append(
                    f"VULN: risk score {vuln_risk_score} exceeds max {vuln_policy['max_risk_score']}"
                )

            vuln_pass = len([b for b in blockers if b.startswith("VULN:")]) == 0

            # --- Resource check via tool ---
            resource_pass = True
            for rt in res_policy["required_resource_checks"]:
                quota_data = self.tools["get_namespace_quota"](
                    namespace=namespace, resource_type=rt
                )
                tool_call_count += 1

                if "error" in quota_data:
                    blockers.append(f"RES: no quota data for {namespace}/{rt}")
                    resource_pass = False
                    continue

                limit = quota_data["quota_limit"]
                current = quota_data["current_usage"]
                buffer_key = f"{rt}_reserved"
                buffer_val = ns_buffers.get(namespace, {}).get(buffer_key, 0.0)

                requested = req_cpu if rt == "cpu_cores" else req_mem
                projected = current + requested + buffer_val
                utilization = projected / limit if limit > 0 else 1.0

                if utilization > res_policy["max_utilization_after_deploy"]:
                    blockers.append(
                        f"RES: {rt} projected utilization {utilization:.4f} exceeds max {res_policy['max_utilization_after_deploy']}"
                    )
                    resource_pass = False

            # --- Dependency check via tool ---
            dep_data = self.tools["get_service_dependencies"](service_id=svc_id)
            tool_call_count += 1
            deps = dep_data["dependencies"]

            dep_pass = True
            if deps:
                for d in deps:
                    if d["criticality"] == "critical" and dep_policy["critical_must_be_healthy"]:
                        if d["health_status"] != "healthy":
                            blockers.append(f"DEP: critical dependency is {d['health_status']}")
                            dep_pass = False
                    if dep_policy["unhealthy_blocks_deploy"] and d["health_status"] == "unhealthy":
                        blockers.append("DEP: unhealthy dependency detected")
                        dep_pass = False

                standard_deps = [d for d in deps if d["criticality"] == "standard"]
                if standard_deps:
                    degraded_standard = sum(
                        1 for d in standard_deps if d["health_status"] in ("degraded", "unknown")
                    )
                    ratio = degraded_standard / len(standard_deps)
                    if ratio > dep_policy["max_degraded_standard_ratio"]:
                        blockers.append(
                            f"DEP: {degraded_standard}/{len(standard_deps)} standard deps degraded/unknown (ratio {ratio:.4f} > max {dep_policy['max_degraded_standard_ratio']})"
                        )
                        dep_pass = False

            # --- CR check via tool ---
            cr_data = self.tools["get_change_requests"](service_id=svc_id)
            tool_call_count += 1
            crs = cr_data["change_requests"]

            cr_pass = False
            for cr in crs:
                if cr["status"] in cr_policy["required_status"] and cr["num_approvals"] >= cr_policy["min_approvals"]:
                    cr_pass = True
                    break

            if not cr_pass:
                blockers.append(
                    f"CR: no approved change request with >= {cr_policy['min_approvals']} approvals"
                )

            # Deduplicate blockers
            seen = set()
            unique_blockers = []
            for b in blockers:
                if b not in seen:
                    seen.add(b)
                    unique_blockers.append(b)
            blockers = unique_blockers

            decision = "GO" if len(blockers) == 0 else "NO-GO"
            results.append({
                "service_name": svc_name,
                "service_id": svc_id,
                "decision": decision,
                "vulnerability_risk_score": vuln_risk_score,
                "vulnerability_check": "PASS" if vuln_pass else "FAIL",
                "resource_check": "PASS" if resource_pass else "FAIL",
                "dependency_check": "PASS" if dep_pass else "FAIL",
                "cr_check": "PASS" if cr_pass else "FAIL",
                "blockers": blockers,
            })

        # Build manifest
        go_list = sorted([r["service_name"] for r in results if r["decision"] == "GO"])
        nogo_list = sorted([r["service_name"] for r in results if r["decision"] == "NO-GO"])

        manifest = {
            "services": results,
            "summary": {
                "total_services": len(results),
                "go_count": len(go_list),
                "nogo_count": len(nogo_list),
            },
        }

        # Write manifest to workspace
        with open(os.path.join(self.workspace, "deployment_manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)

        # Build response
        action_lines = ["Deployment Readiness Assessment Complete.", ""]
        for r in sorted(results, key=lambda x: x["service_name"]):
            action_lines.append(
                f"{r['service_name']}: {r['decision']} "
                f"(vuln={r['vulnerability_check']}, res={r['resource_check']}, "
                f"dep={r['dependency_check']}, cr={r['cr_check']}, "
                f"risk_score={r['vulnerability_risk_score']})"
            )
            if r["blockers"]:
                for b in r["blockers"]:
                    action_lines.append(f"  - {b}")

        action_lines.append("")
        action_lines.append(f"GO services ({len(go_list)}): {', '.join(go_list)}")
        action_lines.append(f"NO-GO services ({len(nogo_list)}): {', '.join(nogo_list)}")

        action = "\n".join(action_lines)

        print(f"[verify] Tool calls made: {tool_call_count}")
        return self.step(action)
