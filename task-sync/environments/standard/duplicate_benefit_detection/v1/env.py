#!/usr/bin/env python3
"""
Duplicate Benefit Application Detection - Environment
Tools and evaluation for identifying duplicate benefit applications.
"""

import sqlite3
import os
import json
import csv
import re
import yaml
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

    # ==============================================================
    # Tool methods
    # ==============================================================

    @tool(
        description="Lists applicants with basic identity information. Returns a paginated list. Each page contains up to page_size records.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 20, default 20)"
                }
            },
            "required": ["page"]
        }
    )
    def list_applicants(self, page: int, page_size: int = 20) -> dict:
        page_size = min(page_size, 20)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM applicants").fetchone()[0]
        total_pages = max(1, (total + page_size - 1) // page_size)
        offset = (page - 1) * page_size
        rows = cur.execute(
            "SELECT applicant_id, first_name, last_name, ssn, dob, "
            "address, city, state, zip_code "
            "FROM applicants ORDER BY applicant_id LIMIT ? OFFSET ?",
            (page_size, offset)).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_applicants": total,
            "applicants": [dict(r) for r in rows],
        }

    @tool(
        description="Retrieves full details for a single applicant by their ID, including phone and email.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID (e.g. APP-0001)"
                }
            },
            "required": ["applicant_id"]
        }
    )
    def get_applicant_details(self, applicant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM applicants WHERE applicant_id = ?",
            (applicant_id,)).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Applicant {applicant_id} not found"}
        return dict(row)

    @tool(
        description="Retrieves all household members for a given applicant. Returns member details including relationship, name, date of birth, and SSN.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID (e.g. APP-0001)"
                }
            },
            "required": ["applicant_id"]
        }
    )
    def get_household_members(self, applicant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT member_id, applicant_id, relationship, first_name, "
            "last_name, dob, ssn FROM household_members "
            "WHERE applicant_id = ? ORDER BY member_id",
            (applicant_id,)).fetchall()
        conn.close()
        return {
            "applicant_id": applicant_id,
            "members": [dict(r) for r in rows],
            "count": len(rows),
        }

    @tool(
        description="Retrieves all benefit applications submitted by a given applicant.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID (e.g. APP-0001)"
                }
            },
            "required": ["applicant_id"]
        }
    )
    def get_applications(self, applicant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM applications WHERE applicant_id = ? "
            "ORDER BY application_id",
            (applicant_id,)).fetchall()
        conn.close()
        return {
            "applicant_id": applicant_id,
            "applications": [dict(r) for r in rows],
            "count": len(rows),
        }

    @tool(
        description="Retrieves income verification records for a given applicant. These are self-reported or agency-collected income records stored in the system.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID (e.g. APP-0001)"
                }
            },
            "required": ["applicant_id"]
        }
    )
    def get_income_verifications(self, applicant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM income_verifications WHERE applicant_id = ? "
            "ORDER BY verification_id",
            (applicant_id,)).fetchall()
        conn.close()
        return {
            "applicant_id": applicant_id,
            "verifications": [dict(r) for r in rows],
            "count": len(rows),
        }

    @tool(
        description="Retrieves details for a single application by its application ID, including prior application reference.",
        parameters={
            "type": "object",
            "properties": {
                "application_id": {
                    "type": "string",
                    "description": "The application ID (e.g. APPL-00001)"
                }
            },
            "required": ["application_id"]
        }
    )
    def get_application_details(self, application_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM applications WHERE application_id = ?",
            (application_id,)).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Application {application_id} not found"}
        return dict(row)

    # ==============================================================
    # Ground-truth computation (used by step and verify)
    # ==============================================================

    def _compute_ground_truth(self) -> List[dict]:
        """Compute all ground-truth flagged cases from DB and workspace."""
        # Load detection rules
        rules_path = os.path.join(self.workspace, "detection_rules.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        det_rules = rules["duplicate_detection_rules"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load all applicants
        applicants = [dict(r) for r in conn.execute(
            "SELECT * FROM applicants ORDER BY applicant_id").fetchall()]
        aid_list = [a["applicant_id"] for a in applicants]

        # Load all household members
        all_hh = {}
        for row in conn.execute(
                "SELECT applicant_id, ssn FROM household_members"):
            aid = row[0]
            ssn = row[1]
            all_hh.setdefault(aid, set()).add(ssn)

        # Load all applications
        all_apps = {}
        for row in conn.execute(
                "SELECT applicant_id, program_type FROM applications"):
            all_apps.setdefault(row[0], set()).add(row[1])

        # Load all income verifications
        all_income = {}
        for row in conn.execute(
                "SELECT applicant_id, annual_amount FROM income_verifications"):
            all_income.setdefault(row[0], []).append(row[1])

        conn.close()

        # Load identity docs from workspace
        identity_docs = {}  # aid -> doc_number
        for fname in os.listdir(self.workspace):
            if fname.startswith("identity_docs_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    docs = json.load(f)
                for doc in docs:
                    identity_docs[doc["applicant_id"]] = doc["document_number"]

        # Load employer-verified income from workspace income reports
        employer_income = {}  # aid -> list of amounts
        for fname in os.listdir(self.workspace):
            if fname.startswith("income_report_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                for block in content.split("=== INCOME REPORT:"):
                    block = block.strip()
                    if not block:
                        continue
                    aid_match = re.search(r"Applicant ID:\s*(APP-\d+)", block)
                    inc_match = re.search(r"Annual Income:\s*([\d.]+)", block)
                    if aid_match and inc_match:
                        aid = aid_match.group(1)
                        amount = float(inc_match.group(1))
                        employer_income.setdefault(aid, []).append(amount)

        # Build flagged pairs (set to deduplicate)
        seen_pairs = set()
        flagged = []

        def add_flag(aid1, aid2, dup_type, confidence, action):
            pair = tuple(sorted([aid1, aid2]))
            if pair in seen_pairs:
                return
            seen_pairs.add(pair)
            # Determine programs_affected
            progs1 = all_apps.get(pair[0], set())
            progs2 = all_apps.get(pair[1], set())
            common = sorted(progs1 & progs2)
            flagged.append({
                "applicant_id_1": pair[0],
                "applicant_id_2": pair[1],
                "duplicate_type": dup_type,
                "confidence_score": confidence,
                "programs_affected": ";".join(common) if common else "",
                "recommended_action": action,
            })

        # 1. SSN_MATCH
        if det_rules["SSN_MATCH"]["enabled"]:
            ssn_map = {}
            for a in applicants:
                ssn_map.setdefault(a["ssn"], []).append(a["applicant_id"])
            for ssn, aids in ssn_map.items():
                if len(aids) >= 2:
                    for i in range(len(aids)):
                        for j in range(i + 1, len(aids)):
                            add_flag(aids[i], aids[j], "SSN_MATCH",
                                     det_rules["SSN_MATCH"]["confidence"],
                                     det_rules["SSN_MATCH"]["action"])

        # 2. NAME_DOB_MATCH
        if det_rules["NAME_DOB_MATCH"]["enabled"]:
            nd_map = {}
            for a in applicants:
                key = (a["first_name"].lower(), a["last_name"].lower(),
                       a["dob"])
                nd_map.setdefault(key, []).append(a["applicant_id"])
            for key, aids in nd_map.items():
                if len(aids) >= 2:
                    for i in range(len(aids)):
                        for j in range(i + 1, len(aids)):
                            add_flag(aids[i], aids[j], "NAME_DOB_MATCH",
                                     det_rules["NAME_DOB_MATCH"]["confidence"],
                                     det_rules["NAME_DOB_MATCH"]["action"])

        # 3. HOUSEHOLD_OVERLAP
        if det_rules["HOUSEHOLD_OVERLAP"]["enabled"]:
            min_shared = det_rules["HOUSEHOLD_OVERLAP"]["min_shared_members"]
            for i in range(len(aid_list)):
                for j in range(i + 1, len(aid_list)):
                    a1, a2 = aid_list[i], aid_list[j]
                    s1 = all_hh.get(a1, set())
                    s2 = all_hh.get(a2, set())
                    if len(s1 & s2) >= min_shared:
                        add_flag(a1, a2, "HOUSEHOLD_OVERLAP",
                                 det_rules["HOUSEHOLD_OVERLAP"]["confidence"],
                                 det_rules["HOUSEHOLD_OVERLAP"]["action"])

        # 4. ID_DOC_MATCH
        if det_rules["ID_DOC_MATCH"]["enabled"]:
            doc_map = {}
            for aid, doc_num in identity_docs.items():
                doc_map.setdefault(doc_num, []).append(aid)
            for doc_num, aids in doc_map.items():
                if len(aids) >= 2:
                    for i in range(len(aids)):
                        for j in range(i + 1, len(aids)):
                            add_flag(aids[i], aids[j], "ID_DOC_MATCH",
                                     det_rules["ID_DOC_MATCH"]["confidence"],
                                     det_rules["ID_DOC_MATCH"]["action"])

        # 5. ADDRESS_INCOME_MATCH
        if det_rules["ADDRESS_INCOME_MATCH"]["enabled"]:
            tol = det_rules["ADDRESS_INCOME_MATCH"]["income_tolerance_pct"]
            addr_map = {}
            for a in applicants:
                key = (a["address"].lower(), a["city"].lower(),
                       a["state"].lower(), a["zip_code"])
                addr_map.setdefault(key, []).append(a["applicant_id"])
            for key, aids in addr_map.items():
                if len(aids) < 2:
                    continue
                for i in range(len(aids)):
                    for j in range(i + 1, len(aids)):
                        a1, a2 = aids[i], aids[j]
                        # Check same program
                        progs1 = all_apps.get(a1, set())
                        progs2 = all_apps.get(a2, set())
                        if not (progs1 & progs2):
                            continue
                        # Check employer-verified income within tolerance
                        inc1 = employer_income.get(a1, [])
                        inc2 = employer_income.get(a2, [])
                        if not inc1 or not inc2:
                            continue
                        val1 = max(inc1)
                        val2 = max(inc2)
                        max_inc = max(val1, val2)
                        if max_inc == 0:
                            continue
                        pct_diff = abs(val1 - val2) / max_inc * 100
                        if pct_diff <= tol:
                            add_flag(
                                a1, a2, "ADDRESS_INCOME_MATCH",
                                det_rules["ADDRESS_INCOME_MATCH"]["confidence"],
                                det_rules["ADDRESS_INCOME_MATCH"]["action"])

        # Sort: confidence desc, then applicant_id_1 asc, then applicant_id_2 asc
        flagged.sort(key=lambda x: (
            -x["confidence_score"],
            x["applicant_id_1"],
            x["applicant_id_2"]))

        # Assign case IDs
        for idx, case in enumerate(flagged):
            case["case_id"] = f"CASE-{idx + 1:03d}"

        return flagged

    # ==============================================================
    # step
    # ==============================================================

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        ground_truth = self._compute_ground_truth()
        gt_pairs = {(c["applicant_id_1"], c["applicant_id_2"]): c
                    for c in ground_truth}

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: flagged_cases.csv exists (10 pts) ---
        csv_path = os.path.join(self.workspace, "flagged_cases.csv")
        c1_max = 10
        max_score += c1_max
        if os.path.exists(csv_path):
            c1_score = c1_max
            eval_criteria["file_exists"] = {
                "passed": True, "score": c1_score, "max_score": c1_max}
        else:
            eval_criteria["file_exists"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "flagged_cases.csv not found in workspace"}
            total_score = 0
            return total_score / max(max_score, 1), {
                "eval_criteria": eval_criteria,
                "total_score": total_score, "max_score": 100}

        total_score += c1_score

        # Parse the CSV
        try:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                submitted_rows = list(reader)
                submitted_cols = reader.fieldnames or []
        except Exception as e:
            eval_criteria["csv_parse"] = {
                "passed": False, "score": 0, "max_score": 0,
                "reason": f"Failed to parse CSV: {e}"}
            return total_score / 100, {
                "eval_criteria": eval_criteria,
                "total_score": total_score, "max_score": 100}

        # --- Criterion 2: Correct columns (10 pts) ---
        c2_max = 10
        max_score += c2_max
        expected_cols = ["case_id", "applicant_id_1", "applicant_id_2",
                         "duplicate_type", "confidence_score",
                         "programs_affected", "recommended_action"]
        if submitted_cols == expected_cols:
            c2_score = c2_max
            eval_criteria["correct_columns"] = {
                "passed": True, "score": c2_score, "max_score": c2_max}
        else:
            missing = set(expected_cols) - set(submitted_cols)
            extra = set(submitted_cols) - set(expected_cols)
            if not missing:
                c2_score = 5  # columns present but wrong order
            else:
                c2_score = 0
            eval_criteria["correct_columns"] = {
                "passed": False, "score": c2_score, "max_score": c2_max,
                "reason": f"Missing: {missing}, Extra: {extra}"}
        total_score += c2_score

        # Build submitted pairs
        submitted_pairs = {}
        for row in submitted_rows:
            aid1 = row.get("applicant_id_1", "").strip()
            aid2 = row.get("applicant_id_2", "").strip()
            if aid1 and aid2:
                pair = tuple(sorted([aid1, aid2]))
                submitted_pairs[pair] = row

        # --- Criterion 3: SSN_MATCH detection (20 pts) ---
        c3_max = 20
        max_score += c3_max
        gt_ssn = {p for p, c in gt_pairs.items()
                  if c["duplicate_type"] == "SSN_MATCH"}
        sub_ssn = {p for p, r in submitted_pairs.items()
                   if r.get("duplicate_type", "").strip() == "SSN_MATCH"}
        c3_score = self._jaccard_score(gt_ssn, sub_ssn, c3_max)
        eval_criteria["ssn_match_detection"] = {
            "passed": c3_score == c3_max, "score": c3_score,
            "max_score": c3_max,
            "reason": f"GT={len(gt_ssn)}, found={len(sub_ssn & gt_ssn)}, "
                      f"FP={len(sub_ssn - gt_ssn)}, FN={len(gt_ssn - sub_ssn)}"}
        total_score += c3_score

        # --- Criterion 4: NAME_DOB_MATCH detection (15 pts) ---
        c4_max = 15
        max_score += c4_max
        gt_nd = {p for p, c in gt_pairs.items()
                 if c["duplicate_type"] == "NAME_DOB_MATCH"}
        sub_nd = {p for p, r in submitted_pairs.items()
                  if r.get("duplicate_type", "").strip() == "NAME_DOB_MATCH"}
        c4_score = self._jaccard_score(gt_nd, sub_nd, c4_max)
        eval_criteria["name_dob_match_detection"] = {
            "passed": c4_score == c4_max, "score": c4_score,
            "max_score": c4_max,
            "reason": f"GT={len(gt_nd)}, found={len(sub_nd & gt_nd)}, "
                      f"FP={len(sub_nd - gt_nd)}, FN={len(gt_nd - sub_nd)}"}
        total_score += c4_score

        # --- Criterion 5: HOUSEHOLD_OVERLAP detection (15 pts) ---
        c5_max = 15
        max_score += c5_max
        gt_hh = {p for p, c in gt_pairs.items()
                 if c["duplicate_type"] == "HOUSEHOLD_OVERLAP"}
        sub_hh = {p for p, r in submitted_pairs.items()
                  if r.get("duplicate_type", "").strip() == "HOUSEHOLD_OVERLAP"}
        c5_score = self._jaccard_score(gt_hh, sub_hh, c5_max)
        eval_criteria["household_overlap_detection"] = {
            "passed": c5_score == c5_max, "score": c5_score,
            "max_score": c5_max,
            "reason": f"GT={len(gt_hh)}, found={len(sub_hh & gt_hh)}, "
                      f"FP={len(sub_hh - gt_hh)}, FN={len(gt_hh - sub_hh)}"}
        total_score += c5_score

        # --- Criterion 6: ID_DOC_MATCH detection (15 pts) ---
        c6_max = 15
        max_score += c6_max
        gt_doc = {p for p, c in gt_pairs.items()
                  if c["duplicate_type"] == "ID_DOC_MATCH"}
        sub_doc = {p for p, r in submitted_pairs.items()
                   if r.get("duplicate_type", "").strip() == "ID_DOC_MATCH"}
        c6_score = self._jaccard_score(gt_doc, sub_doc, c6_max)
        eval_criteria["id_doc_match_detection"] = {
            "passed": c6_score == c6_max, "score": c6_score,
            "max_score": c6_max,
            "reason": f"GT={len(gt_doc)}, found={len(sub_doc & gt_doc)}, "
                      f"FP={len(sub_doc - gt_doc)}, FN={len(gt_doc - sub_doc)}"}
        total_score += c6_score

        # --- Criterion 7: ADDRESS_INCOME_MATCH detection (10 pts) ---
        c7_max = 10
        max_score += c7_max
        gt_addr = {p for p, c in gt_pairs.items()
                   if c["duplicate_type"] == "ADDRESS_INCOME_MATCH"}
        sub_addr = {p for p, r in submitted_pairs.items()
                    if r.get("duplicate_type", "").strip() == "ADDRESS_INCOME_MATCH"}
        c7_score = self._jaccard_score(gt_addr, sub_addr, c7_max)
        eval_criteria["address_income_match_detection"] = {
            "passed": c7_score == c7_max, "score": c7_score,
            "max_score": c7_max,
            "reason": f"GT={len(gt_addr)}, found={len(sub_addr & gt_addr)}, "
                      f"FP={len(sub_addr - gt_addr)}, FN={len(gt_addr - sub_addr)}"}
        total_score += c7_score

        # --- Criterion 8: Confidence scores correct (10 pts) ---
        c8_max = 10
        max_score += c8_max
        correct_conf = 0
        total_matched = 0
        for pair, gt_case in gt_pairs.items():
            if pair in submitted_pairs:
                total_matched += 1
                try:
                    sub_conf = float(submitted_pairs[pair].get(
                        "confidence_score", "0"))
                    if abs(sub_conf - gt_case["confidence_score"]) < 0.01:
                        correct_conf += 1
                except (ValueError, TypeError):
                    pass
        if total_matched > 0:
            c8_score = round(correct_conf / total_matched * c8_max)
        else:
            c8_score = 0
        eval_criteria["confidence_scores"] = {
            "passed": c8_score == c8_max, "score": c8_score,
            "max_score": c8_max,
            "reason": f"{correct_conf}/{total_matched} correct confidence scores"}
        total_score += c8_score

        # --- Criterion 9: Programs affected correct (10 pts) ---
        c9_max = 10
        max_score += c9_max
        correct_progs = 0
        for pair, gt_case in gt_pairs.items():
            if pair in submitted_pairs:
                gt_prog = gt_case["programs_affected"]
                sub_prog = submitted_pairs[pair].get(
                    "programs_affected", "").strip()
                # Normalize: split, sort, rejoin
                gt_set = set(p.strip() for p in gt_prog.split(";")
                             if p.strip())
                sub_set = set(p.strip() for p in sub_prog.split(";")
                              if p.strip())
                if gt_set == sub_set:
                    correct_progs += 1
        if total_matched > 0:
            c9_score = round(correct_progs / total_matched * c9_max)
        else:
            c9_score = 0
        eval_criteria["programs_affected"] = {
            "passed": c9_score == c9_max, "score": c9_score,
            "max_score": c9_max,
            "reason": f"{correct_progs}/{total_matched} correct programs_affected"}
        total_score += c9_score

        # --- Criterion 10: Summary in response (5 pts) ---
        c10_max = 5
        max_score += c10_max
        expected_total = len(ground_truth)
        c10_score = 0
        if str(expected_total) in action:
            c10_score += 3
        # Check for at least some type counts mentioned
        type_counts = {}
        for c in ground_truth:
            t = c["duplicate_type"]
            type_counts[t] = type_counts.get(t, 0) + 1
        types_mentioned = sum(1 for t, cnt in type_counts.items()
                              if str(cnt) in action and t in action)
        if types_mentioned >= 2:
            c10_score += 2
        eval_criteria["summary_in_response"] = {
            "passed": c10_score == c10_max, "score": c10_score,
            "max_score": c10_max,
            "reason": f"Total count {'found' if str(expected_total) in action else 'missing'}, "
                      f"{types_mentioned} type counts mentioned"}
        total_score += c10_score

        reward = total_score / max_score
        return reward, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    @staticmethod
    def _jaccard_score(gt_set: set, sub_set: set, max_pts: int) -> int:
        """Jaccard-based scoring: TP / (TP + FP + FN) * max_pts"""
        if not gt_set and not sub_set:
            return max_pts
        if not gt_set:
            return 0 if sub_set else max_pts
        tp = len(gt_set & sub_set)
        fp = len(sub_set - gt_set)
        fn = len(gt_set - sub_set)
        denom = tp + fp + fn
        if denom == 0:
            return max_pts
        return round(tp / denom * max_pts)

    # ==============================================================
    # verify
    # ==============================================================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import re as _re

        # Step 1: Read detection rules from workspace
        rules_path = os.path.join(self.workspace, "detection_rules.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        det_rules = rules["duplicate_detection_rules"]
        output_fmt = rules["output_format"]

        # Step 2: List all applicants via paginated tool calls
        all_applicants = []
        page = 1
        while True:
            result = self.tools["list_applicants"](page=page, page_size=20)
            all_applicants.extend(result["applicants"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 3: Find SSN duplicates
        flagged = []
        seen_pairs = set()

        def add_flag(aid1, aid2, dup_type, confidence, action, progs):
            pair = tuple(sorted([aid1, aid2]))
            if pair in seen_pairs:
                return
            seen_pairs.add(pair)
            flagged.append({
                "applicant_id_1": pair[0],
                "applicant_id_2": pair[1],
                "duplicate_type": dup_type,
                "confidence_score": confidence,
                "programs_affected": progs,
                "recommended_action": action,
            })

        # Helper: get common programs for a pair
        app_programs_cache = {}

        def get_programs(aid):
            if aid not in app_programs_cache:
                res = self.tools["get_applications"](applicant_id=aid)
                app_programs_cache[aid] = set(
                    a["program_type"] for a in res["applications"])
            return app_programs_cache[aid]

        def common_programs_str(aid1, aid2):
            p1 = get_programs(aid1)
            p2 = get_programs(aid2)
            common = sorted(p1 & p2)
            return ";".join(common)

        # 3a. SSN_MATCH
        if det_rules["SSN_MATCH"]["enabled"]:
            ssn_map = {}
            for a in all_applicants:
                ssn_map.setdefault(a["ssn"], []).append(a["applicant_id"])
            for ssn, aids in ssn_map.items():
                if len(aids) >= 2:
                    for i in range(len(aids)):
                        for j in range(i + 1, len(aids)):
                            progs = common_programs_str(aids[i], aids[j])
                            add_flag(aids[i], aids[j], "SSN_MATCH",
                                     det_rules["SSN_MATCH"]["confidence"],
                                     det_rules["SSN_MATCH"]["action"],
                                     progs)

        # 3b. NAME_DOB_MATCH
        if det_rules["NAME_DOB_MATCH"]["enabled"]:
            nd_map = {}
            for a in all_applicants:
                key = (a["first_name"].lower(), a["last_name"].lower(),
                       a["dob"])
                nd_map.setdefault(key, []).append(a["applicant_id"])
            for key, aids in nd_map.items():
                if len(aids) >= 2:
                    for i in range(len(aids)):
                        for j in range(i + 1, len(aids)):
                            progs = common_programs_str(aids[i], aids[j])
                            add_flag(aids[i], aids[j], "NAME_DOB_MATCH",
                                     det_rules["NAME_DOB_MATCH"]["confidence"],
                                     det_rules["NAME_DOB_MATCH"]["action"],
                                     progs)

        # 3c. HOUSEHOLD_OVERLAP
        if det_rules["HOUSEHOLD_OVERLAP"]["enabled"]:
            min_shared = det_rules["HOUSEHOLD_OVERLAP"]["min_shared_members"]
            hh_ssns = {}
            for a in all_applicants:
                aid = a["applicant_id"]
                res = self.tools["get_household_members"](applicant_id=aid)
                hh_ssns[aid] = set(m["ssn"] for m in res["members"])

            aid_list = list(hh_ssns.keys())
            for i in range(len(aid_list)):
                for j in range(i + 1, len(aid_list)):
                    a1, a2 = aid_list[i], aid_list[j]
                    shared = hh_ssns[a1] & hh_ssns[a2]
                    if len(shared) >= min_shared:
                        progs = common_programs_str(a1, a2)
                        add_flag(
                            a1, a2, "HOUSEHOLD_OVERLAP",
                            det_rules["HOUSEHOLD_OVERLAP"]["confidence"],
                            det_rules["HOUSEHOLD_OVERLAP"]["action"],
                            progs)

        # 3d. ID_DOC_MATCH - read identity doc files from workspace
        if det_rules["ID_DOC_MATCH"]["enabled"]:
            doc_map = {}  # doc_number -> list of applicant_ids
            for fname in sorted(os.listdir(self.workspace)):
                if fname.startswith("identity_docs_") and fname.endswith(".json"):
                    with open(os.path.join(self.workspace, fname)) as f:
                        docs = json.load(f)
                    for doc in docs:
                        doc_map.setdefault(doc["document_number"], []).append(
                            doc["applicant_id"])
            for doc_num, aids in doc_map.items():
                if len(aids) >= 2:
                    for i in range(len(aids)):
                        for j in range(i + 1, len(aids)):
                            progs = common_programs_str(aids[i], aids[j])
                            add_flag(
                                aids[i], aids[j], "ID_DOC_MATCH",
                                det_rules["ID_DOC_MATCH"]["confidence"],
                                det_rules["ID_DOC_MATCH"]["action"],
                                progs)

        # 3e. ADDRESS_INCOME_MATCH - requires workspace income reports
        if det_rules["ADDRESS_INCOME_MATCH"]["enabled"]:
            tol = det_rules["ADDRESS_INCOME_MATCH"]["income_tolerance_pct"]
            # Read employer-verified income from workspace
            emp_income = {}
            for fname in sorted(os.listdir(self.workspace)):
                if fname.startswith("income_report_") and fname.endswith(".txt"):
                    with open(os.path.join(self.workspace, fname)) as f:
                        content = f.read()
                    for block in content.split("=== INCOME REPORT:"):
                        block = block.strip()
                        if not block:
                            continue
                        aid_m = _re.search(
                            r"Applicant ID:\s*(APP-\d+)", block)
                        inc_m = _re.search(
                            r"Annual Income:\s*([\d.]+)", block)
                        if aid_m and inc_m:
                            aid = aid_m.group(1)
                            amount = float(inc_m.group(1))
                            emp_income.setdefault(aid, []).append(amount)

            # Group by address
            addr_map = {}
            for a in all_applicants:
                key = (a["address"].lower(), a["city"].lower(),
                       a["state"].lower(), a["zip_code"])
                addr_map.setdefault(key, []).append(a["applicant_id"])

            for key, aids in addr_map.items():
                if len(aids) < 2:
                    continue
                for i in range(len(aids)):
                    for j in range(i + 1, len(aids)):
                        a1, a2 = aids[i], aids[j]
                        # Check same program
                        p1 = get_programs(a1)
                        p2 = get_programs(a2)
                        if not (p1 & p2):
                            continue
                        # Check employer-verified income
                        inc1 = emp_income.get(a1, [])
                        inc2 = emp_income.get(a2, [])
                        if not inc1 or not inc2:
                            continue
                        val1 = max(inc1)
                        val2 = max(inc2)
                        max_inc = max(val1, val2)
                        if max_inc == 0:
                            continue
                        pct_diff = abs(val1 - val2) / max_inc * 100
                        if pct_diff <= tol:
                            progs = common_programs_str(a1, a2)
                            add_flag(
                                a1, a2, "ADDRESS_INCOME_MATCH",
                                det_rules["ADDRESS_INCOME_MATCH"]["confidence"],
                                det_rules["ADDRESS_INCOME_MATCH"]["action"],
                                progs)

        # Sort: confidence desc, applicant_id_1 asc, applicant_id_2 asc
        flagged.sort(key=lambda x: (
            -x["confidence_score"],
            x["applicant_id_1"],
            x["applicant_id_2"]))

        # Assign case IDs
        for idx, case in enumerate(flagged):
            case["case_id"] = f"CASE-{idx + 1:03d}"

        # Write flagged_cases.csv
        csv_path = os.path.join(self.workspace, "flagged_cases.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "case_id", "applicant_id_1", "applicant_id_2",
                "duplicate_type", "confidence_score",
                "programs_affected", "recommended_action"])
            writer.writeheader()
            for case in flagged:
                row = dict(case)
                row["confidence_score"] = f"{row['confidence_score']:.2f}"
                writer.writerow(row)

        # Build summary for action string
        type_counts = {}
        for c in flagged:
            t = c["duplicate_type"]
            type_counts[t] = type_counts.get(t, 0) + 1

        summary_parts = [
            f"Duplicate detection complete. "
            f"Total flagged cases: {len(flagged)}."]
        for t, cnt in sorted(type_counts.items()):
            summary_parts.append(f"{t}: {cnt}")
        action = " ".join(summary_parts)

        return self.step(action)
