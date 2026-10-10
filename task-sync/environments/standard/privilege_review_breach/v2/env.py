#!/usr/bin/env python3
"""Environment for privileged-document clawback task."""

import sqlite3
import os
import csv
import json
from typing import Tuple, Dict, List, Any


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


PAGE_SIZE = 20


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
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description="Search employees by name, role, or department. Returns paginated results (20 per page). At least one filter must be provided.",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Partial or full employee name to search for (case-insensitive).",
                },
                "role": {
                    "type": "string",
                    "description": "Exact role title to filter by, e.g. 'Attorney', 'Paralegal'.",
                },
                "department": {
                    "type": "string",
                    "description": "Department name to filter by.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1.",
                },
            },
            "required": [],
        },
    )
    def search_employees(self, name: str = None, role: str = None, department: str = None, page: int = 1) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        clauses = []
        params: list = []
        if name:
            clauses.append("full_name LIKE ?")
            params.append(f"%{name}%")
        if role:
            clauses.append("role = ?")
            params.append(role)
        if department:
            clauses.append("department = ?")
            params.append(department)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        c.execute(f"SELECT COUNT(*) FROM employees{where}", params)
        total = c.fetchone()[0]
        offset = (max(page, 1) - 1) * PAGE_SIZE
        c.execute(
            f"SELECT employee_id, full_name, email_address, department, role, bar_number, hire_date "
            f"FROM employees{where} ORDER BY employee_id LIMIT ? OFFSET ?",
            params + [PAGE_SIZE, offset],
        )
        rows = c.fetchall()
        conn.close()
        return {
            "employees": [
                {
                    "employee_id": r[0],
                    "full_name": r[1],
                    "email_address": r[2],
                    "department": r[3],
                    "role": r[4],
                    "bar_number": r[5],
                    "hire_date": r[6],
                }
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": PAGE_SIZE,
            "has_more": offset + PAGE_SIZE < total,
        }

    @tool(
        description="Retrieve a single employee record by employee ID.",
        parameters={
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "integer",
                    "description": "The unique employee identifier.",
                },
            },
            "required": ["employee_id"],
        },
    )
    def get_employee_by_id(self, employee_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT employee_id, full_name, email_address, department, role, bar_number, hire_date "
            "FROM employees WHERE employee_id = ?",
            (employee_id,),
        )
        r = c.fetchone()
        conn.close()
        if not r:
            return {"error": f"No employee found with id {employee_id}"}
        return {
            "employee_id": r[0],
            "full_name": r[1],
            "email_address": r[2],
            "department": r[3],
            "role": r[4],
            "bar_number": r[5],
            "hire_date": r[6],
        }

    @tool(
        description="Search email metadata by sender, date range, or subject keyword. Returns paginated results (20 per page).",
        parameters={
            "type": "object",
            "properties": {
                "sender_id": {
                    "type": "integer",
                    "description": "Employee ID of the email sender.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD, inclusive).",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD, inclusive).",
                },
                "subject_keyword": {
                    "type": "string",
                    "description": "Keyword to search for in the subject line (case-insensitive).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1.",
                },
            },
            "required": [],
        },
    )
    def search_emails(self, sender_id: int = None, date_from: str = None, date_to: str = None, subject_keyword: str = None, page: int = 1) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        clauses = []
        params: list = []
        if sender_id is not None:
            clauses.append("sender_id = ?")
            params.append(sender_id)
        if date_from:
            clauses.append("sent_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("sent_date <= ?")
            params.append(date_to)
        if subject_keyword:
            clauses.append("subject LIKE ?")
            params.append(f"%{subject_keyword}%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        c.execute(f"SELECT COUNT(*) FROM emails{where}", params)
        total = c.fetchone()[0]
        offset = (max(page, 1) - 1) * PAGE_SIZE
        c.execute(
            f"SELECT email_id, internal_ref, sender_id, sent_date, subject, has_attachment, confidential_flag "
            f"FROM emails{where} ORDER BY email_id LIMIT ? OFFSET ?",
            params + [PAGE_SIZE, offset],
        )
        rows = c.fetchall()
        conn.close()
        return {
            "emails": [
                {
                    "email_id": r[0],
                    "internal_ref": r[1],
                    "sender_id": r[2],
                    "sent_date": r[3],
                    "subject": r[4],
                    "has_attachment": bool(r[5]),
                    "confidential_flag": bool(r[6]),
                }
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": PAGE_SIZE,
            "has_more": offset + PAGE_SIZE < total,
        }

    @tool(
        description="Get full details of a single email by its internal reference code (e.g. 'EM-00001'). Returns the email metadata together with all recipient entries (employee ID, name, and recipient type). Does NOT include employee roles.",
        parameters={
            "type": "object",
            "properties": {
                "email_ref": {
                    "type": "string",
                    "description": "The internal reference code of the email, e.g. 'EM-00001'.",
                },
            },
            "required": ["email_ref"],
        },
    )
    def get_email_details(self, email_ref: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT e.email_id, e.internal_ref, e.sender_id, emp.full_name, "
            "e.sent_date, e.subject, e.has_attachment, e.confidential_flag "
            "FROM emails e JOIN employees emp ON e.sender_id = emp.employee_id "
            "WHERE e.internal_ref = ?",
            (email_ref,),
        )
        row = c.fetchone()
        if not row:
            conn.close()
            return {"error": f"No email found with ref {email_ref}"}
        email_id = row[0]
        result = {
            "email_id": row[0],
            "internal_ref": row[1],
            "sender_id": row[2],
            "sender_name": row[3],
            "sent_date": row[4],
            "subject": row[5],
            "has_attachment": bool(row[6]),
            "confidential_flag": bool(row[7]),
            "recipients": [],
        }
        c.execute(
            "SELECT er.employee_id, emp.full_name, er.recipient_type "
            "FROM email_recipients er JOIN employees emp ON er.employee_id = emp.employee_id "
            "WHERE er.email_id = ? ORDER BY er.id",
            (email_id,),
        )
        for r in c.fetchall():
            result["recipients"].append(
                {"employee_id": r[0], "name": r[1], "recipient_type": r[2]}
            )
        conn.close()
        return result

    @tool(
        description="Search privilege log entries by email reference, privilege type, or status. Returns paginated results (20 per page).",
        parameters={
            "type": "object",
            "properties": {
                "email_ref": {
                    "type": "string",
                    "description": "The document/email reference code to search for (exact match).",
                },
                "privilege_type": {
                    "type": "string",
                    "description": "Filter by privilege type: 'attorney-client', 'work-product', or 'joint-defense'.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: 'confirmed', 'pending', or 'waived'.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1.",
                },
            },
            "required": [],
        },
    )
    def search_privilege_log(self, email_ref: str = None, privilege_type: str = None, status: str = None, page: int = 1) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        clauses = []
        params: list = []
        if email_ref:
            clauses.append("email_ref = ?")
            params.append(email_ref)
        if privilege_type:
            clauses.append("privilege_type = ?")
            params.append(privilege_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        c.execute(f"SELECT COUNT(*) FROM privilege_log{where}", params)
        total = c.fetchone()[0]
        offset = (max(page, 1) - 1) * PAGE_SIZE
        c.execute(
            f"SELECT log_id, email_ref, privilege_type, basis, date_logged, reviewing_attorney_id, status "
            f"FROM privilege_log{where} ORDER BY log_id LIMIT ? OFFSET ?",
            params + [PAGE_SIZE, offset],
        )
        rows = c.fetchall()
        conn.close()
        return {
            "entries": [
                {
                    "log_id": r[0],
                    "email_ref": r[1],
                    "privilege_type": r[2],
                    "basis": r[3],
                    "date_logged": r[4],
                    "reviewing_attorney_id": r[5],
                    "status": r[6],
                }
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": PAGE_SIZE,
            "has_more": offset + PAGE_SIZE < total,
        }

    @tool(
        description="Retrieve a single privilege log entry by its log ID.",
        parameters={
            "type": "object",
            "properties": {
                "log_id": {
                    "type": "integer",
                    "description": "The unique privilege log entry identifier.",
                },
            },
            "required": ["log_id"],
        },
    )
    def get_privilege_entry(self, log_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT log_id, email_ref, privilege_type, basis, date_logged, reviewing_attorney_id, status "
            "FROM privilege_log WHERE log_id = ?",
            (log_id,),
        )
        r = c.fetchone()
        conn.close()
        if not r:
            return {"error": f"No privilege log entry found with id {log_id}"}
        return {
            "log_id": r[0],
            "email_ref": r[1],
            "privilege_type": r[2],
            "basis": r[3],
            "date_logged": r[4],
            "reviewing_attorney_id": r[5],
            "status": r[6],
        }

    @tool(
        description="List all distinct departments along with the count of employees in each department.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_departments(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT department, COUNT(*) as cnt FROM employees GROUP BY department ORDER BY department"
        )
        rows = c.fetchall()
        conn.close()
        return {
            "departments": [{"department": r[0], "employee_count": r[1]} for r in rows]
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_yaml_list(text: str, key: str) -> list:
        """Extract a list value from a simple YAML file."""
        lines = text.split("\n")
        result = []
        in_list = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                if in_list:
                    continue
                continue
            if in_list:
                if stripped.startswith("- "):
                    result.append(stripped[2:].strip())
                else:
                    break
            elif stripped.startswith(key + ":"):
                val = stripped[len(key) + 1 :].strip()
                if val:
                    return [val]
                in_list = True
        return result

    def _compute_ground_truth(self) -> list:
        """Compute the expected clawback list using DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Read configs
        with open(os.path.join(self.workspace, "privilege_criteria.yaml")) as f:
            yaml_text = f.read()
        triggering_roles = self._parse_yaml_list(yaml_text, "triggering_roles")
        eligible_statuses = self._parse_yaml_list(yaml_text, "clawback_eligible_statuses")

        with open(os.path.join(self.workspace, "clawback_rules.json")) as f:
            rules = json.load(f)
        eligible_types = rules["eligible_privilege_types"]
        cutoff = rules["production_date_cutoff"]

        # Read production batch files
        prod_docs = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("production_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as fh:
                    for row in csv.DictReader(fh):
                        prod_docs.append(row)

        clawback = []
        for doc in prod_docs:
            if doc["document_type"] != "email":
                continue
            if doc["production_date"] > cutoff:
                continue
            ref = doc["source_ref"]

            c.execute("SELECT email_id, sender_id FROM emails WHERE internal_ref = ?", (ref,))
            row = c.fetchone()
            if not row:
                continue
            email_id, sender_id = row

            participant_ids = [sender_id]
            c.execute("SELECT employee_id FROM email_recipients WHERE email_id = ?", (email_id,))
            participant_ids.extend(r[0] for r in c.fetchall())

            ph = ",".join("?" * len(participant_ids))
            rph = ",".join("?" * len(triggering_roles))
            c.execute(
                f"SELECT COUNT(*) FROM employees WHERE employee_id IN ({ph}) AND role IN ({rph})",
                participant_ids + triggering_roles,
            )
            if c.fetchone()[0] == 0:
                continue

            c.execute(
                "SELECT privilege_type, basis, reviewing_attorney_id, status "
                "FROM privilege_log WHERE email_ref = ? ORDER BY log_id",
                (ref,),
            )
            for ptype, basis, rev_id, status in c.fetchall():
                if status not in eligible_statuses:
                    continue
                if ptype not in eligible_types:
                    continue
                c.execute("SELECT full_name FROM employees WHERE employee_id = ?", (rev_id,))
                rev_name = c.fetchone()[0]
                clawback.append({
                    "bates_number": doc["bates_number"],
                    "source_ref": ref,
                    "privilege_type": ptype,
                    "privilege_basis": basis,
                    "reviewing_attorney": rev_name,
                    "production_date": doc["production_date"],
                    "production_batch": doc["batch_id"],
                })
                break

        conn.close()
        clawback.sort(key=lambda x: x["bates_number"])
        return clawback

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

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
        gt_bates = {item["bates_number"] for item in ground_truth}
        gt_map = {item["bates_number"]: item for item in ground_truth}

        eval_criteria: Dict[str, dict] = {}

        # ---- 1. File exists (10 pts) ----
        csv_path = os.path.join(self.workspace, "clawback_request.csv")
        file_exists = os.path.exists(csv_path)
        eval_criteria["clawback_file_exists"] = {
            "passed": file_exists,
            "score": 10 if file_exists else 0,
            "max_score": 10,
        }

        expected_cols = [
            "bates_number", "source_ref", "privilege_type",
            "privilege_basis", "reviewing_attorney",
            "production_date", "production_batch",
        ]

        agent_rows: list = []
        agent_cols: list = []

        if file_exists:
            try:
                with open(csv_path, newline="") as fh:
                    reader = csv.DictReader(fh)
                    agent_cols = list(reader.fieldnames or [])
                    agent_rows = list(reader)
            except Exception:
                agent_rows = []
                agent_cols = []

        # ---- 2. Correct columns (10 pts) ----
        cols_ok = agent_cols == expected_cols
        eval_criteria["correct_columns"] = {
            "passed": cols_ok,
            "score": 10 if cols_ok else 0,
            "max_score": 10,
        }
        if not cols_ok and not file_exists:
            eval_criteria["correct_columns"]["reason"] = "CSV file not found"

        # ---- 3. Recall (25 pts) ----
        agent_bates = {r["bates_number"] for r in agent_rows} if agent_rows else set()
        found = gt_bates & agent_bates
        recall = len(found) / len(gt_bates) if gt_bates else 1.0
        recall_score = round(25 * recall)
        eval_criteria["recall"] = {
            "passed": recall == 1.0,
            "score": recall_score,
            "max_score": 25,
        }
        if recall < 1.0:
            missing = gt_bates - agent_bates
            eval_criteria["recall"]["reason"] = f"Missing {len(missing)} bates numbers"

        # ---- 4. Precision (25 pts) ----
        if agent_bates:
            precision = len(found) / len(agent_bates)
        else:
            precision = 0.0 if gt_bates else 1.0
        precision_score = round(25 * precision)
        eval_criteria["precision"] = {
            "passed": precision == 1.0,
            "score": precision_score,
            "max_score": 25,
        }
        if precision < 1.0:
            extra = agent_bates - gt_bates
            eval_criteria["precision"]["reason"] = f"{len(extra)} false positive(s)"

        # ---- 5. Correct privilege types (10 pts) ----
        type_matches = 0
        type_total = 0
        for row in agent_rows:
            bn = row.get("bates_number", "")
            if bn in gt_map:
                type_total += 1
                if row.get("privilege_type") == gt_map[bn]["privilege_type"]:
                    type_matches += 1
        type_ratio = type_matches / type_total if type_total > 0 else 0.0
        type_score = round(10 * type_ratio)
        eval_criteria["correct_privilege_types"] = {
            "passed": type_ratio == 1.0,
            "score": type_score,
            "max_score": 10,
        }

        # ---- 6. Correct sort order (10 pts) ----
        bates_list = [r.get("bates_number", "") for r in agent_rows]
        is_sorted = bates_list == sorted(bates_list)
        eval_criteria["correct_sort_order"] = {
            "passed": is_sorted,
            "score": 10 if is_sorted else 0,
            "max_score": 10,
        }

        # ---- 7. Response summary (10 pts) ----
        count_ok = str(len(ground_truth)) in action
        all_bates_ok = all(b in action for b in gt_bates) if gt_bates else True
        summary_ok = count_ok and all_bates_ok
        summary_score = 0
        if summary_ok:
            summary_score = 10
        elif count_ok:
            summary_score = 5
        elif all_bates_ok:
            summary_score = 5
        eval_criteria["response_summary"] = {
            "passed": summary_ok,
            "score": summary_score,
            "max_score": 10,
        }
        if not summary_ok:
            parts = []
            if not count_ok:
                parts.append(f"expected count {len(ground_truth)} not found in response")
            if not all_bates_ok:
                parts.append("not all bates numbers listed in response")
            eval_criteria["response_summary"]["reason"] = "; ".join(parts)

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------
    # Verify
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
        # ---- 1. Read configuration files ----
        with open(os.path.join(self.workspace, "privilege_criteria.yaml")) as f:
            yaml_text = f.read()
        triggering_roles = self._parse_yaml_list(yaml_text, "triggering_roles")
        eligible_statuses = self._parse_yaml_list(yaml_text, "clawback_eligible_statuses")

        with open(os.path.join(self.workspace, "clawback_rules.json")) as f:
            rules = json.load(f)
        eligible_types = rules["eligible_privilege_types"]
        cutoff = rules["production_date_cutoff"]

        # ---- 2. Build set of employee IDs with triggering roles ----
        attorney_ids: set = set()
        for role in triggering_roles:
            page = 1
            while True:
                result = self.tools["search_employees"](role=role, page=page)
                for emp in result["employees"]:
                    attorney_ids.add(emp["employee_id"])
                if not result["has_more"]:
                    break
                page += 1

        # ---- 3. Read all production batch manifests ----
        prod_docs = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("production_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as fh:
                    for row in csv.DictReader(fh):
                        prod_docs.append(row)

        # ---- 4. For each email-type production doc, check clawback eligibility ----
        clawback_items = []

        for doc in prod_docs:
            if doc["document_type"] != "email":
                continue
            if doc["production_date"] > cutoff:
                continue

            source_ref = doc["source_ref"]

            # Get email details via tool
            email_info = self.tools["get_email_details"](email_ref=source_ref)
            if "error" in email_info:
                continue

            # Check if any participant has a triggering role
            participant_ids = [email_info["sender_id"]]
            for recip in email_info["recipients"]:
                participant_ids.append(recip["employee_id"])

            has_trigger = False
            for pid in participant_ids:
                if pid in attorney_ids:
                    has_trigger = True
                    break

            if not has_trigger:
                # Double-check via individual lookups for participants
                # not yet in our cache
                for pid in participant_ids:
                    emp = self.tools["get_employee_by_id"](employee_id=pid)
                    if emp.get("role") in triggering_roles:
                        has_trigger = True
                        attorney_ids.add(pid)
                        break
            if not has_trigger:
                continue

            # Check privilege log for this email
            priv_result = self.tools["search_privilege_log"](email_ref=source_ref)
            qualifying_entry = None
            for entry in priv_result["entries"]:
                if entry["status"] not in eligible_statuses:
                    continue
                if entry["privilege_type"] not in eligible_types:
                    continue
                qualifying_entry = entry
                break

            if qualifying_entry is None:
                continue

            # Get reviewing attorney name
            rev_atty = self.tools["get_employee_by_id"](
                employee_id=qualifying_entry["reviewing_attorney_id"]
            )

            clawback_items.append({
                "bates_number": doc["bates_number"],
                "source_ref": source_ref,
                "privilege_type": qualifying_entry["privilege_type"],
                "privilege_basis": qualifying_entry["basis"],
                "reviewing_attorney": rev_atty["full_name"],
                "production_date": doc["production_date"],
                "production_batch": doc["batch_id"],
            })

        # ---- 5. Sort and write output ----
        clawback_items.sort(key=lambda x: x["bates_number"])

        output_path = os.path.join(self.workspace, "clawback_request.csv")
        with open(output_path, "w", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "bates_number", "source_ref", "privilege_type",
                    "privilege_basis", "reviewing_attorney",
                    "production_date", "production_batch",
                ],
            )
            writer.writeheader()
            writer.writerows(clawback_items)

        # ---- 6. Build action string ----
        bates_list = ", ".join(item["bates_number"] for item in clawback_items)
        action = (
            f"Clawback analysis complete. {len(clawback_items)} documents identified "
            f"for clawback. Bates numbers: {bates_list}"
        )

        return self.step(action)
