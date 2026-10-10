import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import pandas as pd
import yaml


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

    # =================================================================
    # TOOL METHODS
    # =================================================================

    @tool(
        description="Search satellite change detection records with optional filters. Returns paginated results (20 per page).",
        parameters={
            "type": "object",
            "properties": {
                "change_type": {
                    "type": "string",
                    "description": "Filter by change type (e.g. 'deforestation', 'land_clearing', 'regrowth').",
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum confidence score (0.0–1.0).",
                },
                "parcel_id": {
                    "type": "string",
                    "description": "Filter by parcel ID (e.g. 'P-0001').",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Default 1.",
                },
            },
            "required": [],
        },
    )
    def search_satellite_changes(
        self,
        change_type: str = None,
        min_confidence: float = None,
        parcel_id: str = None,
        page: int = 1,
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        query = "SELECT * FROM satellite_changes WHERE 1=1"
        params: list = []
        if change_type:
            query += " AND change_type = ?"
            params.append(change_type)
        if min_confidence is not None:
            query += " AND confidence_score >= ?"
            params.append(float(min_confidence))
        if parcel_id:
            query += " AND parcel_id = ?"
            params.append(parcel_id)
        query += " ORDER BY change_id"
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        page_size = 20
        total = len(df)
        total_pages = max(1, (total + page_size - 1) // page_size)
        start = (page - 1) * page_size
        page_data = df.iloc[start: start + page_size]
        return {
            "results": page_data.to_dict(orient="records"),
            "page": int(page),
            "total_pages": int(total_pages),
            "total_results": int(total),
        }

    @tool(
        description="Get basic information for a specific parcel by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "parcel_id": {
                    "type": "string",
                    "description": "Parcel ID (e.g. 'P-0001').",
                },
            },
            "required": ["parcel_id"],
        },
    )
    def get_parcel_info(self, parcel_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM parcels WHERE parcel_id = ?", conn, params=[parcel_id]
        )
        conn.close()
        if df.empty:
            return {"error": f"Parcel {parcel_id} not found."}
        return df.iloc[0].to_dict()

    @tool(
        description="Get current ownership information for a parcel. Returns the current owner record.",
        parameters={
            "type": "object",
            "properties": {
                "parcel_id": {
                    "type": "string",
                    "description": "Parcel ID (e.g. 'P-0001').",
                },
            },
            "required": ["parcel_id"],
        },
    )
    def get_ownership_info(self, parcel_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM land_ownership WHERE parcel_id = ? AND is_current = 1",
            conn,
            params=[parcel_id],
        )
        conn.close()
        if df.empty:
            return {"error": f"No current ownership record for {parcel_id}."}
        return df.iloc[0].to_dict()

    @tool(
        description="Get all logging concession records for a parcel, including expired, active, and suspended.",
        parameters={
            "type": "object",
            "properties": {
                "parcel_id": {
                    "type": "string",
                    "description": "Parcel ID (e.g. 'P-0001').",
                },
            },
            "required": ["parcel_id"],
        },
    )
    def get_concessions_for_parcel(self, parcel_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM logging_concessions WHERE parcel_id = ? ORDER BY granted_date",
            conn,
            params=[parcel_id],
        )
        conn.close()
        return {"concessions": df.to_dict(orient="records")}

    @tool(
        description="Get all conservation / habitat assessment reports for a parcel.",
        parameters={
            "type": "object",
            "properties": {
                "parcel_id": {
                    "type": "string",
                    "description": "Parcel ID (e.g. 'P-0001').",
                },
            },
            "required": ["parcel_id"],
        },
    )
    def get_conservation_reports(self, parcel_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM conservation_reports WHERE parcel_id = ? ORDER BY report_date",
            conn,
            params=[parcel_id],
        )
        conn.close()
        return {"reports": df.to_dict(orient="records")}

    @tool(
        description="List all parcel IDs in the registry. Returns paginated results (20 per page).",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Default 1.",
                },
            },
            "required": [],
        },
    )
    def list_parcel_ids(self, page: int = 1) -> dict:
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query("SELECT parcel_id FROM parcels ORDER BY parcel_id", conn)
        conn.close()
        page_size = 20
        total = len(df)
        total_pages = max(1, (total + page_size - 1) // page_size)
        start = (page - 1) * page_size
        page_data = df.iloc[start: start + page_size]
        return {
            "parcel_ids": page_data["parcel_id"].tolist(),
            "page": int(page),
            "total_pages": int(total_pages),
            "total_parcels": int(total),
        }

    # =================================================================
    # GROUND-TRUTH COMPUTATION (used by step and verify)
    # =================================================================

    def _compute_ground_truth(self) -> pd.DataFrame:
        """Compute the expected incident dossier from DB + workspace files."""
        # --- Read workspace config ---
        with open(os.path.join(self.workspace, "deforestation_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        conf_threshold = policy["confidence_threshold"]
        types_of_interest = policy["change_types_of_interest"]
        area_tol_pct = policy["area_tolerance_pct"]
        min_cons_priority = policy["min_conservation_priority_for_critical"]
        min_bio_idx = policy["min_biodiversity_index_for_critical"]

        with open(os.path.join(self.workspace, "protected_species_list.json")) as f:
            protected_list = json.load(f)
        protected_names = {s["species_name"] for s in protected_list}

        severity_df = pd.read_csv(os.path.join(self.workspace, "severity_matrix.csv"))
        severity_order = {
            row["severity_tier"]: row["priority_order"]
            for _, row in severity_df.iterrows()
        }
        recommended_actions = {
            row["severity_tier"]: row["recommended_action"]
            for _, row in severity_df.iterrows()
        }

        # --- Read field inspections ---
        field_verifications: Dict[str, str] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("field_inspection_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for insp in json.load(f):
                        field_verifications[insp["change_id"]] = insp["verification_status"]

        # --- Read species surveys ---
        parcel_species: Dict[str, set] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("species_survey_") and fname.endswith(".csv"):
                survey = pd.read_csv(os.path.join(self.workspace, fname))
                for _, row in survey.iterrows():
                    pid = row["parcel_id"]
                    if pid not in parcel_species:
                        parcel_species[pid] = set()
                    parcel_species[pid].add(row["species_name"])

        # --- Query DB directly ---
        conn = sqlite3.connect(self.db_path)
        placeholders = ",".join("?" for _ in types_of_interest)
        changes = pd.read_sql_query(
            f"SELECT * FROM satellite_changes WHERE change_type IN ({placeholders}) "
            f"AND confidence_score >= ? ORDER BY change_id",
            conn,
            params=list(types_of_interest) + [conf_threshold],
        )

        priority_levels = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        min_priority_val = priority_levels.get(min_cons_priority, 3)

        incidents = []
        for _, c in changes.iterrows():
            cid = c["change_id"]
            # Field verification filter
            if cid in field_verifications and field_verifications[cid] == "false_positive":
                continue

            pid = c["parcel_id"]
            det_date = c["detection_date"]
            affected_area = c["affected_area_hectares"]

            # Ownership
            own_df = pd.read_sql_query(
                "SELECT * FROM land_ownership WHERE parcel_id = ? AND is_current = 1",
                conn, params=[pid],
            )
            owner_name = own_df.iloc[0]["owner_name"] if not own_df.empty else "Unknown"
            owner_type = own_df.iloc[0]["owner_type"] if not own_df.empty else "Unknown"

            # Concessions
            conc_df = pd.read_sql_query(
                "SELECT * FROM logging_concessions WHERE parcel_id = ?",
                conn, params=[pid],
            )

            violations: List[Tuple[str, str]] = []

            if conc_df.empty:
                violations.append(("no_permit", "HIGH"))
            else:
                valid_concession = None
                for _, con in conc_df.iterrows():
                    if (con["granted_date"] <= det_date <= con["expiry_date"]
                            and con["status"] not in ("suspended", "revoked")):
                        valid_concession = con
                        break
                if valid_concession is None:
                    violations.append(("expired_permit", "LOW"))
                else:
                    max_allowed = valid_concession["permitted_hectares"] * (1 + area_tol_pct / 100)
                    if affected_area > max_allowed:
                        violations.append(("area_exceeded", "MEDIUM"))

            # Conservation check
            cons_df = pd.read_sql_query(
                "SELECT * FROM conservation_reports WHERE parcel_id = ?",
                conn, params=[pid],
            )
            has_conservation_issue = False
            for _, rep in cons_df.iterrows():
                if (priority_levels.get(rep["conservation_priority"], 0) >= min_priority_val
                        and rep["biodiversity_index"] >= min_bio_idx):
                    has_conservation_issue = True
                    break
            if has_conservation_issue:
                species_at_parcel = parcel_species.get(pid, set())
                if species_at_parcel & protected_names:
                    violations.append(("conservation_violation", "CRITICAL"))

            if not violations:
                continue  # legal activity

            best = min(violations, key=lambda v: severity_order.get(v[1], 99))
            violation_type = best[0]
            severity_tier = best[1]
            field_verified = (cid in field_verifications
                              and field_verifications[cid] == "confirmed")

            incidents.append({
                "change_id": cid,
                "parcel_id": pid,
                "owner_name": owner_name,
                "owner_type": owner_type,
                "detection_date": det_date,
                "change_type": c["change_type"],
                "affected_area_hectares": float(affected_area),
                "violation_type": violation_type,
                "severity_tier": severity_tier,
                "field_verified": field_verified,
                "recommended_action": recommended_actions.get(severity_tier, "unknown"),
            })

        conn.close()

        # Sort: severity tier (most severe first), then affected area desc
        incidents.sort(
            key=lambda x: (severity_order.get(x["severity_tier"], 99),
                           -x["affected_area_hectares"])
        )
        for i, inc in enumerate(incidents):
            inc["incident_id"] = f"INC-{i+1:04d}"

        columns = [
            "incident_id", "change_id", "parcel_id", "owner_name", "owner_type",
            "detection_date", "change_type", "affected_area_hectares",
            "violation_type", "severity_tier", "field_verified", "recommended_action",
        ]
        if incidents:
            return pd.DataFrame(incidents)[columns]
        return pd.DataFrame(columns=columns)

    # =================================================================
    # STEP — evaluation
    # =================================================================

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
        criteria: Dict[str, Dict[str, Any]] = {}

        # ----------------------------------------------------------
        # 1. DOSSIER FILE EXISTS & HAS CORRECT COLUMNS  (10 pts)
        # ----------------------------------------------------------
        dossier_path = os.path.join(self.workspace, "incident_dossier.csv")
        expected_cols = [
            "incident_id", "change_id", "parcel_id", "owner_name", "owner_type",
            "detection_date", "change_type", "affected_area_hectares",
            "violation_type", "severity_tier", "field_verified", "recommended_action",
        ]
        dossier_ok = False
        agent_df = pd.DataFrame()
        if os.path.exists(dossier_path):
            try:
                agent_df = pd.read_csv(dossier_path)
                if list(agent_df.columns) == expected_cols:
                    dossier_ok = True
                    reason = ""
                else:
                    reason = f"Column mismatch. Expected {expected_cols}, got {list(agent_df.columns)}"
            except Exception as e:
                reason = f"Failed to read CSV: {e}"
        else:
            reason = "incident_dossier.csv not found"
        criteria["dossier_file"] = {
            "passed": dossier_ok,
            "score": 10 if dossier_ok else 0,
            "max_score": 10,
            "reason": reason if not dossier_ok else "",
        }

        # ----------------------------------------------------------
        # 2. INCIDENT IDENTIFICATION  (20 pts)
        # ----------------------------------------------------------
        if dossier_ok and not agent_df.empty:
            gt_ids = set(gt["change_id"].tolist())
            agent_ids = set(agent_df["change_id"].tolist())
            tp = len(gt_ids & agent_ids)
            precision = tp / len(agent_ids) if agent_ids else 0
            recall = tp / len(gt_ids) if gt_ids else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
            id_score = round(f1 * 20)
            id_passed = f1 == 1.0
            id_reason = "" if id_passed else f"P={precision:.2f} R={recall:.2f} F1={f1:.2f}"
        else:
            id_score = 0
            id_passed = False
            id_reason = "No valid dossier to evaluate"
        criteria["incident_identification"] = {
            "passed": id_passed,
            "score": id_score,
            "max_score": 20,
            "reason": id_reason,
        }

        # ----------------------------------------------------------
        # 3. SEVERITY CLASSIFICATION  (20 pts)
        # ----------------------------------------------------------
        if dossier_ok and not agent_df.empty and not gt.empty:
            merged = agent_df[["change_id", "severity_tier"]].merge(
                gt[["change_id", "severity_tier"]],
                on="change_id", suffixes=("_agent", "_gt"),
            )
            if len(merged):
                correct = (merged["severity_tier_agent"] == merged["severity_tier_gt"]).sum()
                sev_ratio = correct / len(merged)
            else:
                sev_ratio = 0
            sev_score = round(sev_ratio * 20)
            sev_passed = sev_ratio == 1.0
            sev_reason = "" if sev_passed else f"{correct}/{len(merged)} correct"
        else:
            sev_score = 0
            sev_passed = False
            sev_reason = "No data to compare"
        criteria["severity_classification"] = {
            "passed": sev_passed,
            "score": sev_score,
            "max_score": 20,
            "reason": sev_reason,
        }

        # ----------------------------------------------------------
        # 4. VIOLATION TYPES  (15 pts)
        # ----------------------------------------------------------
        if dossier_ok and not agent_df.empty and not gt.empty:
            merged_v = agent_df[["change_id", "violation_type"]].merge(
                gt[["change_id", "violation_type"]],
                on="change_id", suffixes=("_agent", "_gt"),
            )
            if len(merged_v):
                correct_v = (merged_v["violation_type_agent"] == merged_v["violation_type_gt"]).sum()
                vio_ratio = correct_v / len(merged_v)
            else:
                vio_ratio = 0
            vio_score = round(vio_ratio * 15)
            vio_passed = vio_ratio == 1.0
            vio_reason = "" if vio_passed else f"{correct_v}/{len(merged_v)} correct"
        else:
            vio_score = 0
            vio_passed = False
            vio_reason = "No data to compare"
        criteria["violation_types"] = {
            "passed": vio_passed,
            "score": vio_score,
            "max_score": 15,
            "reason": vio_reason,
        }

        # ----------------------------------------------------------
        # 5. SORT ORDER  (10 pts)
        # ----------------------------------------------------------
        severity_rank = {"CRITICAL": 1, "HIGH": 2, "MEDIUM": 3, "LOW": 4}
        if dossier_ok and len(agent_df) > 1:
            prev_key = None
            sort_ok = True
            for _, row in agent_df.iterrows():
                cur_key = (severity_rank.get(row["severity_tier"], 99),
                           -row["affected_area_hectares"])
                if prev_key is not None and cur_key < prev_key:
                    sort_ok = False
                    break
                prev_key = cur_key
            sort_score = 10 if sort_ok else 0
            sort_reason = "" if sort_ok else "Rows not in expected sort order"
        elif dossier_ok and len(agent_df) <= 1:
            sort_ok = True
            sort_score = 10
            sort_reason = ""
        else:
            sort_ok = False
            sort_score = 0
            sort_reason = "No dossier"
        criteria["sort_order"] = {
            "passed": sort_ok,
            "score": sort_score,
            "max_score": 10,
            "reason": sort_reason,
        }

        # ----------------------------------------------------------
        # 6. ENFORCEMENT SUMMARY FILE  (10 pts)
        # ----------------------------------------------------------
        summary_path = os.path.join(self.workspace, "enforcement_summary.md")
        summary_ok = False
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    summary_text = f.read()
                expected_total = len(gt)
                total_area_gt = round(gt["affected_area_hectares"].sum(), 2) if not gt.empty else 0.0
                # Check key numbers appear
                has_total = str(expected_total) in summary_text
                has_area = f"{total_area_gt:.2f}" in summary_text
                if has_total and has_area:
                    summary_ok = True
                    sum_reason = ""
                else:
                    missing = []
                    if not has_total:
                        missing.append(f"total count {expected_total}")
                    if not has_area:
                        missing.append(f"total area {total_area_gt:.2f}")
                    sum_reason = "Missing: " + ", ".join(missing)
            except Exception as e:
                sum_reason = str(e)
        else:
            sum_reason = "enforcement_summary.md not found"
        criteria["enforcement_summary"] = {
            "passed": summary_ok,
            "score": 10 if summary_ok else 0,
            "max_score": 10,
            "reason": sum_reason if not summary_ok else "",
        }

        # ----------------------------------------------------------
        # 7. RESPONSE ACCURACY  (15 pts)
        # ----------------------------------------------------------
        resp_score = 0
        resp_reasons = []
        expected_total = len(gt)
        total_area_gt = round(gt["affected_area_hectares"].sum(), 2) if not gt.empty else 0.0
        sev_counts_gt = gt["severity_tier"].value_counts().to_dict() if not gt.empty else {}
        n_critical_gt = sev_counts_gt.get("CRITICAL", 0)
        largest_parcel_gt = (
            gt.loc[gt["affected_area_hectares"].idxmax(), "parcel_id"]
            if not gt.empty else ""
        )

        action_lower = action.lower() if action else ""
        # total incidents (5 pts)
        if str(expected_total) in (action or ""):
            resp_score += 5
        else:
            resp_reasons.append(f"Expected total incidents {expected_total}")
        # total area (4 pts)
        if f"{total_area_gt:.2f}" in (action or ""):
            resp_score += 4
        else:
            resp_reasons.append(f"Expected total area {total_area_gt:.2f}")
        # critical count (3 pts)
        if str(n_critical_gt) in (action or ""):
            resp_score += 3
        else:
            resp_reasons.append(f"Expected CRITICAL count {n_critical_gt}")
        # largest parcel (3 pts)
        if largest_parcel_gt and largest_parcel_gt in (action or ""):
            resp_score += 3
        else:
            resp_reasons.append(f"Expected largest parcel {largest_parcel_gt}")

        criteria["response_accuracy"] = {
            "passed": resp_score == 15,
            "score": resp_score,
            "max_score": 15,
            "reason": "; ".join(resp_reasons) if resp_reasons else "",
        }

        # ----------------------------------------------------------
        # AGGREGATE
        # ----------------------------------------------------------
        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    # =================================================================
    # VERIFY — self-test using only tools + workspace files
    # =================================================================

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
        # --- Read workspace configuration files ---
        with open(os.path.join(self.workspace, "deforestation_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        conf_threshold = policy["confidence_threshold"]
        types_of_interest = policy["change_types_of_interest"]
        area_tol_pct = policy["area_tolerance_pct"]
        min_cons_priority = policy["min_conservation_priority_for_critical"]
        min_bio_idx = policy["min_biodiversity_index_for_critical"]

        with open(os.path.join(self.workspace, "protected_species_list.json")) as f:
            protected_list = json.load(f)
        protected_names = {s["species_name"] for s in protected_list}

        severity_df = pd.read_csv(os.path.join(self.workspace, "severity_matrix.csv"))
        severity_order = {
            row["severity_tier"]: row["priority_order"]
            for _, row in severity_df.iterrows()
        }
        recommended_actions = {
            row["severity_tier"]: row["recommended_action"]
            for _, row in severity_df.iterrows()
        }

        # --- Read field inspection files ---
        field_verifications: Dict[str, str] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("field_inspection_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for insp in json.load(f):
                        field_verifications[insp["change_id"]] = insp["verification_status"]

        # --- Read species survey files ---
        parcel_species: Dict[str, set] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("species_survey_") and fname.endswith(".csv"):
                survey = pd.read_csv(os.path.join(self.workspace, fname))
                for _, row in survey.iterrows():
                    pid = row["parcel_id"]
                    if pid not in parcel_species:
                        parcel_species[pid] = set()
                    parcel_species[pid].add(row["species_name"])

        # --- Gather satellite changes via tools ---
        tool_call_count = 0
        all_changes = []
        for ctype in types_of_interest:
            page = 1
            while True:
                result = self.tools["search_satellite_changes"](
                    change_type=ctype, min_confidence=conf_threshold, page=page
                )
                tool_call_count += 1
                all_changes.extend(result["results"])
                if page >= result["total_pages"]:
                    break
                page += 1

        # --- Filter by field verification ---
        candidate_changes = []
        for c in all_changes:
            cid = c["change_id"]
            if cid in field_verifications and field_verifications[cid] == "false_positive":
                continue
            candidate_changes.append(c)

        # --- For each candidate, gather ownership / concession / conservation via tools ---
        unique_parcels = sorted(set(c["parcel_id"] for c in candidate_changes))
        ownership_cache: Dict[str, dict] = {}
        concession_cache: Dict[str, dict] = {}
        conservation_cache: Dict[str, dict] = {}

        for pid in unique_parcels:
            ownership_cache[pid] = self.tools["get_ownership_info"](parcel_id=pid)
            tool_call_count += 1
            concession_cache[pid] = self.tools["get_concessions_for_parcel"](parcel_id=pid)
            tool_call_count += 1
            conservation_cache[pid] = self.tools["get_conservation_reports"](parcel_id=pid)
            tool_call_count += 1

        priority_levels = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        min_priority_val = priority_levels.get(min_cons_priority, 3)

        # --- Classify violations ---
        incidents = []
        for c in candidate_changes:
            pid = c["parcel_id"]
            det_date = c["detection_date"]
            affected_area = c["affected_area_hectares"]

            ownership = ownership_cache[pid]
            owner_name = ownership.get("owner_name", "Unknown")
            owner_type = ownership.get("owner_type", "Unknown")

            concessions = concession_cache[pid].get("concessions", [])
            reports = conservation_cache[pid].get("reports", [])

            violations = []

            # Concession check
            if not concessions:
                violations.append(("no_permit", "HIGH"))
            else:
                valid_concession = None
                for con in concessions:
                    if (con["granted_date"] <= det_date <= con["expiry_date"]
                            and con["status"] not in ("suspended", "revoked")):
                        valid_concession = con
                        break
                if valid_concession is None:
                    violations.append(("expired_permit", "LOW"))
                else:
                    max_allowed = valid_concession["permitted_hectares"] * (1 + area_tol_pct / 100)
                    if affected_area > max_allowed:
                        violations.append(("area_exceeded", "MEDIUM"))

            # Conservation check
            has_conservation_issue = False
            for rep in reports:
                if (priority_levels.get(rep["conservation_priority"], 0) >= min_priority_val
                        and rep["biodiversity_index"] >= min_bio_idx):
                    has_conservation_issue = True
                    break
            if has_conservation_issue:
                species_at_parcel = parcel_species.get(pid, set())
                if species_at_parcel & protected_names:
                    violations.append(("conservation_violation", "CRITICAL"))

            if not violations:
                continue

            best = min(violations, key=lambda v: severity_order.get(v[1], 99))
            violation_type = best[0]
            severity_tier = best[1]
            field_verified = (c["change_id"] in field_verifications
                              and field_verifications[c["change_id"]] == "confirmed")

            incidents.append({
                "change_id": c["change_id"],
                "parcel_id": pid,
                "owner_name": owner_name,
                "owner_type": owner_type,
                "detection_date": det_date,
                "change_type": c["change_type"],
                "affected_area_hectares": float(affected_area),
                "violation_type": violation_type,
                "severity_tier": severity_tier,
                "field_verified": field_verified,
                "recommended_action": recommended_actions.get(severity_tier, "unknown"),
            })

        # --- Sort and assign IDs ---
        incidents.sort(
            key=lambda x: (severity_order.get(x["severity_tier"], 99),
                           -x["affected_area_hectares"])
        )
        for i, inc in enumerate(incidents):
            inc["incident_id"] = f"INC-{i+1:04d}"

        # --- Write dossier ---
        columns = [
            "incident_id", "change_id", "parcel_id", "owner_name", "owner_type",
            "detection_date", "change_type", "affected_area_hectares",
            "violation_type", "severity_tier", "field_verified", "recommended_action",
        ]
        dossier_df = pd.DataFrame(incidents)[columns] if incidents else pd.DataFrame(columns=columns)
        dossier_df.to_csv(os.path.join(self.workspace, "incident_dossier.csv"), index=False)

        # --- Write enforcement summary ---
        total_incidents = len(incidents)
        total_area = round(sum(inc["affected_area_hectares"] for inc in incidents), 2)
        sev_counts: Dict[str, int] = {}
        vio_counts: Dict[str, int] = {}
        for inc in incidents:
            sev_counts[inc["severity_tier"]] = sev_counts.get(inc["severity_tier"], 0) + 1
            vio_counts[inc["violation_type"]] = vio_counts.get(inc["violation_type"], 0) + 1
        n_critical = sev_counts.get("CRITICAL", 0)
        largest = max(incidents, key=lambda x: x["affected_area_hectares"]) if incidents else None

        lines = [
            "# Enforcement Summary\n",
            f"\nTotal incidents: {total_incidents}\n",
            f"Total affected area: {total_area:.2f} hectares\n",
            "\n## By Severity\n\n",
        ]
        for tier in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            if tier in sev_counts:
                lines.append(f"- {tier}: {sev_counts[tier]}\n")
        lines.append("\n## By Violation Type\n\n")
        for vt in sorted(vio_counts.keys()):
            lines.append(f"- {vt}: {vio_counts[vt]}\n")

        with open(os.path.join(self.workspace, "enforcement_summary.md"), "w") as f:
            f.writelines(lines)

        # --- Build action string ---
        action = (
            f"Total verified illegal deforestation incidents: {total_incidents}. "
            f"Total affected area: {total_area:.2f} hectares. "
            f"CRITICAL-severity incidents: {n_critical}. "
            f"Largest affected area parcel: {largest['parcel_id'] if largest else 'N/A'}."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made; need >= 15"

        return self.step(action)
