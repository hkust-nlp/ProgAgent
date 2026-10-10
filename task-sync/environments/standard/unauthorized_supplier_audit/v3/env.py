"""
Environment for franchisee procurement compliance audit task.
Defines tools for querying franchisee/supplier/PO/complaint data
and evaluation logic for the compliance report deliverable.
"""

import sqlite3
import os
import json
import csv
import yaml
import glob as _glob
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

    # ==================================================================
    # Tool methods
    # ==================================================================

    @tool(
        description="List franchisees with pagination. Returns a page of franchisee records including id, name, region, city, state, status, and join_date.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 20)",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_franchisees(self, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM franchisees")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT * FROM franchisees ORDER BY id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "data": rows,
        }

    @tool(
        description="Get detailed information for a single franchisee by ID.",
        parameters={
            "type": "object",
            "properties": {
                "franchisee_id": {
                    "type": "integer",
                    "description": "The franchisee ID to look up",
                },
            },
            "required": ["franchisee_id"],
        },
    )
    def get_franchisee_details(self, franchisee_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM franchisees WHERE id = ?", (franchisee_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Franchisee {franchisee_id} not found"}
        return dict(row)

    @tool(
        description="Get purchase orders for a specific franchisee with pagination. Returns order details including supplier_id, product, amounts, dates, and invoice numbers.",
        parameters={
            "type": "object",
            "properties": {
                "franchisee_id": {
                    "type": "integer",
                    "description": "The franchisee ID whose purchase orders to retrieve",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 20)",
                },
            },
            "required": ["franchisee_id", "page", "page_size"],
        },
    )
    def get_purchase_orders(self, franchisee_id: int, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM purchase_orders WHERE franchisee_id = ?",
            (franchisee_id,),
        )
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT * FROM purchase_orders WHERE franchisee_id = ? "
            "ORDER BY id LIMIT ? OFFSET ?",
            (franchisee_id, page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "franchisee_id": franchisee_id,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "data": rows,
        }

    @tool(
        description="Get information about a specific supplier by ID, including name, primary category, certification level, and contact details.",
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "integer",
                    "description": "The supplier ID to look up",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_supplier_info(self, supplier_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Supplier {supplier_id} not found"}
        return dict(row)

    @tool(
        description="Get quality complaints filed against a specific supplier, with pagination. Returns complaint details including type, severity, date, and resolution status.",
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "integer",
                    "description": "The supplier ID whose complaints to retrieve",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 20)",
                },
            },
            "required": ["supplier_id", "page", "page_size"],
        },
    )
    def get_quality_complaints(self, supplier_id: int, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM quality_complaints WHERE supplier_id = ?",
            (supplier_id,),
        )
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT * FROM quality_complaints WHERE supplier_id = ? "
            "ORDER BY id LIMIT ? OFFSET ?",
            (supplier_id, page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "supplier_id": supplier_id,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "data": rows,
        }

    # ==================================================================
    # Ground truth computation (used by step and verify)
    # ==================================================================

    def _compute_ground_truth(self):
        """
        Compute the full set of violations from the database and workspace.
        Returns a list of violation dicts (one per PO-violation pair).
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # --- Load audit parameters ---
        audit_params = {}
        ap_path = os.path.join(self.workspace, "audit_parameters.txt")
        with open(ap_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    audit_params[k.strip()] = v.strip()
        status_filter = [
            s.strip() for s in audit_params["franchisee_status_filter"].split(",")
        ]

        # --- Load compliance policy ---
        pol_path = os.path.join(self.workspace, "compliance_policy.yaml")
        with open(pol_path) as f:
            policy = yaml.safe_load(f)
        complaint_threshold = policy["complaint_threshold"]
        severity_weights = {
            k: v["severity_weight"] for k, v in policy["violation_types"].items()
        }
        sev_multipliers = policy["severity_multipliers"]

        # --- Load approved vendor lists ---
        # region -> {supplier_id: {approval_start, approval_end, ...}}
        approved_vendors = {}
        for fp in sorted(_glob.glob(os.path.join(self.workspace, "approved_vendors_*.csv"))):
            # Extract region from filename
            basename = os.path.basename(fp)
            # e.g. approved_vendors_region_a.csv -> region_a
            region_part = basename.replace("approved_vendors_", "").replace(".csv", "")
            region_key = region_part  # lowercase
            avl = {}
            import pandas as pd
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                avl[int(row["supplier_id"])] = {
                    "supplier_name": row["supplier_name"],
                    "approved_categories": row["approved_categories"],
                    "approval_start": row["approval_start"],
                    "approval_end": row["approval_end"],
                }
            approved_vendors[region_key] = avl

        # --- Load DC shipment records ---
        dc_invoice_refs = set()
        for fp in sorted(_glob.glob(os.path.join(self.workspace, "dc_shipment_batch_*.json"))):
            with open(fp) as f:
                records = json.load(f)
            for rec in records:
                dc_invoice_refs.add(rec["invoice_ref"])

        # --- Load complaint counts per supplier ---
        cur = conn.cursor()
        cur.execute(
            "SELECT supplier_id, COUNT(*) as cnt FROM quality_complaints GROUP BY supplier_id"
        )
        complaint_counts = {row[0]: row[1] for row in cur.fetchall()}

        # Max severity per supplier
        cur.execute(
            "SELECT supplier_id, severity_level FROM quality_complaints"
        )
        supplier_severities = {}
        for row in cur.fetchall():
            sid, sev = row
            supplier_severities.setdefault(sid, []).append(sev)

        # --- Load franchisees ---
        cur.execute("SELECT * FROM franchisees")
        franchisees = {}
        for row in cur.fetchall():
            f = dict(zip([d[0] for d in cur.description], row))
            franchisees[f["id"]] = f

        # --- Load suppliers ---
        cur.execute("SELECT * FROM suppliers")
        suppliers = {}
        for row in cur.fetchall():
            s = dict(zip([d[0] for d in cur.description], row))
            suppliers[s["id"]] = s

        # --- Load purchase orders ---
        cur.execute("SELECT * FROM purchase_orders")
        purchase_orders = []
        for row in cur.fetchall():
            po = dict(zip([d[0] for d in cur.description], row))
            purchase_orders.append(po)

        conn.close()

        # --- Compute violations ---
        violations = []

        for po in purchase_orders:
            fid = po["franchisee_id"]
            sid = po["supplier_id"]
            franchisee = franchisees[fid]
            supplier = suppliers[sid]

            # Filter by status
            if franchisee["status"] not in status_filter:
                continue

            region_key = franchisee["region"].lower()
            avl = approved_vendors.get(region_key, {})

            # UNAPPROVED_SUPPLIER vs EXPIRED_APPROVAL (mutually exclusive)
            if sid not in avl:
                violations.append({
                    "franchisee_id": fid,
                    "franchisee_name": franchisee["name"],
                    "supplier_id": sid,
                    "supplier_name": supplier["name"],
                    "violation_type": "UNAPPROVED_SUPPLIER",
                    "invoice_number": po["invoice_number"],
                    "order_date": po["order_date"],
                    "total_amount": po["total_amount"],
                    "severity_score": round(float(severity_weights["UNAPPROVED_SUPPLIER"]), 2),
                    "evidence": (
                        f"Supplier {supplier['name']} (ID: {sid}) not found in "
                        f"approved vendor list for {franchisee['region']}"
                    ),
                })
            else:
                vendor_entry = avl[sid]
                if po["order_date"] > vendor_entry["approval_end"]:
                    violations.append({
                        "franchisee_id": fid,
                        "franchisee_name": franchisee["name"],
                        "supplier_id": sid,
                        "supplier_name": supplier["name"],
                        "violation_type": "EXPIRED_APPROVAL",
                        "invoice_number": po["invoice_number"],
                        "order_date": po["order_date"],
                        "total_amount": po["total_amount"],
                        "severity_score": round(float(severity_weights["EXPIRED_APPROVAL"]), 2),
                        "evidence": (
                            f"Approval for supplier {supplier['name']} (ID: {sid}) "
                            f"expired on {vendor_entry['approval_end']}, "
                            f"order placed on {po['order_date']}"
                        ),
                    })

            # QUALITY_FLAGGED
            cnt = complaint_counts.get(sid, 0)
            if cnt >= complaint_threshold:
                sevs = supplier_severities.get(sid, [])
                max_mult = max(sev_multipliers.get(s, 1.0) for s in sevs) if sevs else 1.0
                score = round(float(severity_weights["QUALITY_FLAGGED"]) * max_mult, 2)
                highest_sev = max(sevs, key=lambda s: sev_multipliers.get(s, 0))
                violations.append({
                    "franchisee_id": fid,
                    "franchisee_name": franchisee["name"],
                    "supplier_id": sid,
                    "supplier_name": supplier["name"],
                    "violation_type": "QUALITY_FLAGGED",
                    "invoice_number": po["invoice_number"],
                    "order_date": po["order_date"],
                    "total_amount": po["total_amount"],
                    "severity_score": score,
                    "severity_detail": {"count": cnt, "highest": highest_sev},
                    "evidence": (
                        f"Supplier {supplier['name']} (ID: {sid}) has {cnt} complaints "
                        f"(threshold: {complaint_threshold}), "
                        f"highest severity: {highest_sev}"
                    ),
                })

            # DC_BYPASS
            if po["invoice_number"] not in dc_invoice_refs:
                violations.append({
                    "franchisee_id": fid,
                    "franchisee_name": franchisee["name"],
                    "supplier_id": sid,
                    "supplier_name": supplier["name"],
                    "violation_type": "DC_BYPASS",
                    "invoice_number": po["invoice_number"],
                    "order_date": po["order_date"],
                    "total_amount": po["total_amount"],
                    "severity_score": round(float(severity_weights["DC_BYPASS"]), 2),
                    "evidence": (
                        f"No matching DC shipment record found for "
                        f"invoice {po['invoice_number']}"
                    ),
                })

        # Sort: descending severity_score, ascending franchisee_id, ascending order_date
        violations.sort(
            key=lambda v: (-v["severity_score"], v["franchisee_id"], v["order_date"])
        )

        return violations

    # ==================================================================
    # step
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
        import pandas as pd

        ground_truth = self._compute_ground_truth()
        gt_keys = set()
        gt_map = {}
        for v in ground_truth:
            key = (v["franchisee_id"], v["supplier_id"],
                   v["invoice_number"], v["violation_type"])
            gt_keys.add(key)
            gt_map[key] = v

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: Report file exists with correct columns (10 pts) ---
        cr1_max = 10
        max_score += cr1_max
        report_path = os.path.join(self.workspace, "compliance_report.csv")
        expected_cols = [
            "franchisee_id", "franchisee_name", "supplier_id", "supplier_name",
            "violation_type", "invoice_number", "order_date", "total_amount",
            "severity_score", "evidence",
        ]
        agent_df = None
        if os.path.exists(report_path):
            try:
                agent_df = pd.read_csv(report_path)
                agent_cols = list(agent_df.columns)
                if agent_cols == expected_cols:
                    cr1_score = cr1_max
                    cr1_passed = True
                    cr1_reason = ""
                else:
                    cr1_score = 4
                    cr1_passed = False
                    cr1_reason = f"Column mismatch: expected {expected_cols}, got {agent_cols}"
            except Exception as e:
                cr1_score = 0
                cr1_passed = False
                cr1_reason = f"Failed to parse CSV: {e}"
        else:
            cr1_score = 0
            cr1_passed = False
            cr1_reason = "compliance_report.csv not found"

        total_score += cr1_score
        eval_criteria["report_format"] = {
            "passed": cr1_passed,
            "score": cr1_score,
            "max_score": cr1_max,
            **({"reason": cr1_reason} if not cr1_passed else {}),
        }

        # --- Criterion 2: Violation recall (25 pts) ---
        cr2_max = 25
        max_score += cr2_max
        agent_keys = set()
        if agent_df is not None and not agent_df.empty:
            for _, row in agent_df.iterrows():
                try:
                    key = (
                        int(row["franchisee_id"]),
                        int(row["supplier_id"]),
                        str(row["invoice_number"]),
                        str(row["violation_type"]),
                    )
                    agent_keys.add(key)
                except (ValueError, KeyError):
                    continue

        if len(gt_keys) > 0:
            recall = len(agent_keys & gt_keys) / len(gt_keys)
        else:
            recall = 1.0 if len(agent_keys) == 0 else 0.0
        cr2_score = round(cr2_max * recall, 2)
        cr2_passed = recall >= 0.99
        total_score += cr2_score
        eval_criteria["violations_recall"] = {
            "passed": cr2_passed,
            "score": cr2_score,
            "max_score": cr2_max,
            **({"reason": f"Recall={recall:.4f}, found {len(agent_keys & gt_keys)}/{len(gt_keys)} violations"} if not cr2_passed else {}),
        }

        # --- Criterion 3: Violation precision (20 pts) ---
        cr3_max = 20
        max_score += cr3_max
        if len(agent_keys) > 0:
            precision = len(agent_keys & gt_keys) / len(agent_keys)
        else:
            precision = 1.0 if len(gt_keys) == 0 else 0.0
        cr3_score = round(cr3_max * precision, 2)
        cr3_passed = precision >= 0.99
        total_score += cr3_score
        eval_criteria["violations_precision"] = {
            "passed": cr3_passed,
            "score": cr3_score,
            "max_score": cr3_max,
            **({"reason": f"Precision={precision:.4f}, {len(agent_keys - gt_keys)} false positives"} if not cr3_passed else {}),
        }

        # --- Criterion 4: Severity scores correct (15 pts) ---
        cr4_max = 15
        max_score += cr4_max
        matched_keys = agent_keys & gt_keys
        correct_severity = 0
        if agent_df is not None and not agent_df.empty and len(matched_keys) > 0:
            agent_severity_map = {}
            for _, row in agent_df.iterrows():
                try:
                    key = (
                        int(row["franchisee_id"]),
                        int(row["supplier_id"]),
                        str(row["invoice_number"]),
                        str(row["violation_type"]),
                    )
                    agent_severity_map[key] = float(row["severity_score"])
                except (ValueError, KeyError):
                    continue

            for key in matched_keys:
                expected_sev = gt_map[key]["severity_score"]
                agent_sev = agent_severity_map.get(key)
                if agent_sev is not None and abs(agent_sev - expected_sev) < 0.01:
                    correct_severity += 1

        severity_rate = correct_severity / len(matched_keys) if len(matched_keys) > 0 else (1.0 if len(gt_keys) == 0 else 0.0)
        cr4_score = round(cr4_max * severity_rate, 2)
        cr4_passed = severity_rate >= 0.99
        total_score += cr4_score
        eval_criteria["severity_scores"] = {
            "passed": cr4_passed,
            "score": cr4_score,
            "max_score": cr4_max,
            **({"reason": f"Correct severity in {correct_severity}/{len(matched_keys)} matched violations"} if not cr4_passed else {}),
        }

        # --- Criterion 5: Sort order correct (10 pts) ---
        cr5_max = 10
        max_score += cr5_max
        cr5_score = 0
        cr5_passed = False
        cr5_reason = "No report data"
        if agent_df is not None and len(agent_df) > 1:
            try:
                sevs = agent_df["severity_score"].astype(float).tolist()
                fids = agent_df["franchisee_id"].astype(int).tolist()
                dates = agent_df["order_date"].astype(str).tolist()

                correctly_sorted = True
                for i in range(len(agent_df) - 1):
                    if sevs[i] < sevs[i + 1]:
                        correctly_sorted = False
                        break
                    if sevs[i] == sevs[i + 1]:
                        if fids[i] > fids[i + 1]:
                            correctly_sorted = False
                            break
                        if fids[i] == fids[i + 1] and dates[i] > dates[i + 1]:
                            correctly_sorted = False
                            break

                if correctly_sorted:
                    cr5_score = cr5_max
                    cr5_passed = True
                    cr5_reason = ""
                else:
                    cr5_score = 0
                    cr5_reason = "Report rows not sorted correctly"
            except Exception as e:
                cr5_reason = f"Sort check error: {e}"
        elif agent_df is not None and len(agent_df) == 1:
            cr5_score = cr5_max
            cr5_passed = True
            cr5_reason = ""

        total_score += cr5_score
        eval_criteria["sort_order"] = {
            "passed": cr5_passed,
            "score": cr5_score,
            "max_score": cr5_max,
            **({"reason": cr5_reason} if not cr5_passed else {}),
        }

        # --- Criterion 6: Response summary (20 pts) ---
        cr6_max = 20
        max_score += cr6_max
        cr6_score = 0
        checks = 0
        total_checks = 4
        action_lower = action.lower()

        # Check total violation count mentioned
        total_violations = len(ground_truth)
        if str(total_violations) in action:
            checks += 1

        # Check violation type breakdown: at least 3 of 4 types mentioned
        type_counts = {}
        for v in ground_truth:
            vt = v["violation_type"]
            type_counts[vt] = type_counts.get(vt, 0) + 1
        types_found = 0
        for vt, cnt in type_counts.items():
            if vt.lower().replace("_", " ") in action_lower or vt in action:
                if str(cnt) in action:
                    types_found += 1
        if types_found >= min(3, len(type_counts)):
            checks += 1

        # Check distinct franchisee/supplier counts
        dist_franchisees = len(set(v["franchisee_id"] for v in ground_truth))
        dist_suppliers = len(set(v["supplier_id"] for v in ground_truth))
        if str(dist_franchisees) in action or str(dist_suppliers) in action:
            checks += 1

        # Check top-3 franchisees mentioned
        fran_violation_counts = {}
        for v in ground_truth:
            fran_violation_counts[v["franchisee_id"]] = (
                fran_violation_counts.get(v["franchisee_id"], 0) + 1
            )
        top3_ids = sorted(
            fran_violation_counts, key=lambda x: -fran_violation_counts[x]
        )[:3]
        # Check if at least 2 of the top 3 franchisee names appear in the response
        top3_names_found = 0
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        for fid in top3_ids:
            cur.execute("SELECT name FROM franchisees WHERE id = ?", (fid,))
            row = cur.fetchone()
            if row and row[0].lower() in action_lower:
                top3_names_found += 1
        conn.close()
        if top3_names_found >= min(2, len(top3_ids)):
            checks += 1

        cr6_score = round(cr6_max * checks / total_checks, 2)
        cr6_passed = checks == total_checks
        total_score += cr6_score
        eval_criteria["response_summary"] = {
            "passed": cr6_passed,
            "score": cr6_score,
            "max_score": cr6_max,
            **({"reason": f"Passed {checks}/{total_checks} summary checks"} if not cr6_passed else {}),
        }

        # --- Final ---
        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": round(total_score, 2),
            "max_score": max_score,
        }
        return reward, info

    # ==================================================================
    # verify
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
        import pandas as pd

        tool_call_count = 0

        # --- Read workspace files ---

        # Audit parameters
        with open(os.path.join(self.workspace, "audit_parameters.txt")) as f:
            audit_params = {}
            for line in f:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    audit_params[k.strip()] = v.strip()
        status_filter = [
            s.strip() for s in audit_params["franchisee_status_filter"].split(",")
        ]

        # Compliance policy
        with open(os.path.join(self.workspace, "compliance_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        complaint_threshold = policy["complaint_threshold"]
        severity_weights = {
            k: v["severity_weight"] for k, v in policy["violation_types"].items()
        }
        sev_multipliers = policy["severity_multipliers"]

        # Approved vendor lists
        approved_vendors = {}  # region_key -> {supplier_id: {...}}
        for fp in sorted(_glob.glob(os.path.join(self.workspace, "approved_vendors_*.csv"))):
            basename = os.path.basename(fp)
            region_key = basename.replace("approved_vendors_", "").replace(".csv", "")
            avl = {}
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                avl[int(row["supplier_id"])] = {
                    "supplier_name": row["supplier_name"],
                    "approved_categories": row["approved_categories"],
                    "approval_start": row["approval_start"],
                    "approval_end": row["approval_end"],
                }
            approved_vendors[region_key] = avl

        # DC shipment records
        dc_invoice_refs = set()
        for fp in sorted(_glob.glob(os.path.join(self.workspace, "dc_shipment_batch_*.json"))):
            with open(fp) as f:
                records = json.load(f)
            for rec in records:
                dc_invoice_refs.add(rec["invoice_ref"])

        # --- Gather data via tools ---

        # List all franchisees
        all_franchisees = []
        page = 1
        while True:
            result = self.tools["list_franchisees"](page=page, page_size=20)
            tool_call_count += 1
            all_franchisees.extend(result["data"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Filter by status
        in_scope = [f for f in all_franchisees if f["status"] in status_filter]

        # Get purchase orders for each in-scope franchisee
        all_pos = []
        for franchisee in in_scope:
            fid = franchisee["id"]
            page = 1
            while True:
                result = self.tools["get_purchase_orders"](
                    franchisee_id=fid, page=page, page_size=20
                )
                tool_call_count += 1
                all_pos.extend(
                    [(franchisee, po) for po in result["data"]]
                )
                if page >= result["total_pages"]:
                    break
                page += 1

        # Collect unique supplier IDs
        unique_supplier_ids = set()
        for _, po in all_pos:
            unique_supplier_ids.add(po["supplier_id"])

        # Get supplier info
        supplier_map = {}
        for sid in sorted(unique_supplier_ids):
            result = self.tools["get_supplier_info"](supplier_id=sid)
            tool_call_count += 1
            supplier_map[sid] = result

        # Get quality complaints for each supplier
        complaint_data = {}  # sid -> {count, severities}
        for sid in sorted(unique_supplier_ids):
            complaints = []
            page = 1
            while True:
                result = self.tools["get_quality_complaints"](
                    supplier_id=sid, page=page, page_size=20
                )
                tool_call_count += 1
                complaints.extend(result["data"])
                if page >= result["total_pages"]:
                    break
                page += 1
            complaint_data[sid] = {
                "count": len(complaints),
                "severities": [c["severity_level"] for c in complaints],
            }

        # --- Compute violations ---
        violations = []

        for franchisee, po in all_pos:
            fid = franchisee["id"]
            sid = po["supplier_id"]
            supplier = supplier_map[sid]
            region_key = franchisee["region"].lower()
            avl = approved_vendors.get(region_key, {})

            # UNAPPROVED vs EXPIRED (mutually exclusive)
            if sid not in avl:
                violations.append({
                    "franchisee_id": fid,
                    "franchisee_name": franchisee["name"],
                    "supplier_id": sid,
                    "supplier_name": supplier["name"],
                    "violation_type": "UNAPPROVED_SUPPLIER",
                    "invoice_number": po["invoice_number"],
                    "order_date": po["order_date"],
                    "total_amount": po["total_amount"],
                    "severity_score": f"{float(severity_weights['UNAPPROVED_SUPPLIER']):.2f}",
                    "evidence": (
                        f"Supplier {supplier['name']} (ID: {sid}) not found in "
                        f"approved vendor list for {franchisee['region']}"
                    ),
                })
            else:
                vendor_entry = avl[sid]
                if po["order_date"] > vendor_entry["approval_end"]:
                    violations.append({
                        "franchisee_id": fid,
                        "franchisee_name": franchisee["name"],
                        "supplier_id": sid,
                        "supplier_name": supplier["name"],
                        "violation_type": "EXPIRED_APPROVAL",
                        "invoice_number": po["invoice_number"],
                        "order_date": po["order_date"],
                        "total_amount": po["total_amount"],
                        "severity_score": f"{float(severity_weights['EXPIRED_APPROVAL']):.2f}",
                        "evidence": (
                            f"Approval for supplier {supplier['name']} (ID: {sid}) "
                            f"expired on {vendor_entry['approval_end']}, "
                            f"order placed on {po['order_date']}"
                        ),
                    })

            # QUALITY_FLAGGED
            cd = complaint_data.get(sid, {"count": 0, "severities": []})
            if cd["count"] >= complaint_threshold:
                max_mult = max(
                    (sev_multipliers.get(s, 1.0) for s in cd["severities"]),
                    default=1.0,
                )
                score = float(severity_weights["QUALITY_FLAGGED"]) * max_mult
                highest_sev = max(
                    cd["severities"],
                    key=lambda s: sev_multipliers.get(s, 0),
                )
                violations.append({
                    "franchisee_id": fid,
                    "franchisee_name": franchisee["name"],
                    "supplier_id": sid,
                    "supplier_name": supplier["name"],
                    "violation_type": "QUALITY_FLAGGED",
                    "invoice_number": po["invoice_number"],
                    "order_date": po["order_date"],
                    "total_amount": po["total_amount"],
                    "severity_score": f"{score:.2f}",
                    "evidence": (
                        f"Supplier {supplier['name']} (ID: {sid}) has {cd['count']} complaints "
                        f"(threshold: {complaint_threshold}), "
                        f"highest severity: {highest_sev}"
                    ),
                })

            # DC_BYPASS
            if po["invoice_number"] not in dc_invoice_refs:
                violations.append({
                    "franchisee_id": fid,
                    "franchisee_name": franchisee["name"],
                    "supplier_id": sid,
                    "supplier_name": supplier["name"],
                    "violation_type": "DC_BYPASS",
                    "invoice_number": po["invoice_number"],
                    "order_date": po["order_date"],
                    "total_amount": po["total_amount"],
                    "severity_score": f"{float(severity_weights['DC_BYPASS']):.2f}",
                    "evidence": (
                        f"No matching DC shipment record found for "
                        f"invoice {po['invoice_number']}"
                    ),
                })

        # Sort: descending severity_score, ascending franchisee_id, ascending order_date
        violations.sort(
            key=lambda v: (-float(v["severity_score"]), v["franchisee_id"], v["order_date"])
        )

        # --- Write compliance_report.csv ---
        report_path = os.path.join(self.workspace, "compliance_report.csv")
        columns = [
            "franchisee_id", "franchisee_name", "supplier_id", "supplier_name",
            "violation_type", "invoice_number", "order_date", "total_amount",
            "severity_score", "evidence",
        ]
        df = pd.DataFrame(violations, columns=columns)
        df.to_csv(report_path, index=False)

        # --- Build summary response ---
        total_violations = len(violations)
        type_counts = {}
        for v in violations:
            vt = v["violation_type"]
            type_counts[vt] = type_counts.get(vt, 0) + 1

        dist_franchisees = len(set(v["franchisee_id"] for v in violations))
        dist_suppliers = len(set(v["supplier_id"] for v in violations))

        fran_counts = {}
        for v in violations:
            fran_counts[v["franchisee_id"]] = fran_counts.get(v["franchisee_id"], 0) + 1
        top3 = sorted(fran_counts.items(), key=lambda x: -x[1])[:3]

        # Build franchisee name lookup
        fran_names = {f["id"]: f["name"] for f in all_franchisees}

        type_breakdown = ", ".join(
            f"{vt}: {cnt}" for vt, cnt in sorted(type_counts.items())
        )
        top3_str = ", ".join(
            f"{fran_names.get(fid, f'Franchisee {fid}')} ({cnt} violations)"
            for fid, cnt in top3
        )

        action = (
            f"Procurement Compliance Audit Complete.\n\n"
            f"Total violations found: {total_violations}\n"
            f"Breakdown by type: {type_breakdown}\n"
            f"Distinct franchisees with violations: {dist_franchisees}\n"
            f"Distinct suppliers involved: {dist_suppliers}\n"
            f"Top 3 franchisees by violation count: {top3_str}\n\n"
            f"The compliance report has been saved to compliance_report.csv "
            f"with {total_violations} rows, sorted by severity score "
            f"(descending), franchisee ID (ascending), and order date (ascending)."
        )

        assert tool_call_count >= 15, (
            f"Tool call count {tool_call_count} is below minimum 15"
        )

        return self.step(action)
