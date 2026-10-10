"""
Clinical Trial Safety Protocol Compliance - Task Environment (hardened tool surface)

Provides tools for querying clinical trial data and evaluates
the agent's compliance action plan output.

Hardened surface (M2 + M3): tools return a mix of shapes — deeply nested
record objects, JSON-encoded strings, MCP-style envelopes, plain key:value
text, and Python-repr strings. Error responses use a different object shape
than success responses. Task semantics, data, scoring, and ground truth are
unchanged from the base environment.
"""

import ast
import csv
import hashlib
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple


# --- Define this decorator at the top of env.py, keep unchanged ---
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ─── Hardened tool-surface helpers ───

def _request_id(message: str) -> str:
    return "req_" + hashlib.md5(message.encode("utf-8")).hexdigest()[:12]


def _error(status: int, code: str, message: str) -> dict:
    """Error responses share NO keys with success responses."""
    return {
        "status": status,
        "object": "error",
        "code": code,
        "message": message,
        "request_id": _request_id(f"{status}:{code}:{message}"),
    }


def _envelope(payload) -> dict:
    """MCP-style envelope: payload is JSON-encoded into a text content block."""
    return {
        "meta": None,
        "content": [
            {"type": "text",
             "text": json.dumps(payload, ensure_ascii=False, default=str)}
        ],
        "isError": False,
    }


def _shape(value) -> str:
    """Short rendering of a wrong-typed value for error text."""
    if value is None:
        return "'undefined'"
    r = repr(value)
    if len(r) > 60:
        r = r[:57] + "..."
    return f"'{r}'"


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _number(value):
    return {"type": "number", "number": value}


def _title(text):
    return {"type": "title", "title": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _relation(*ids):
    return {"type": "relation", "relation": [{"id": i} for i in ids]}


def _rich_text(text):
    return {"type": "rich_text", "rich_text": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _date(start):
    return {"type": "date", "date": {"start": start} if start else None}


def _checkbox(value):
    return {"type": "checkbox", "checkbox": bool(value)}


def _coerce_page(page, page_size):
    """Validate pagination inputs. Returns (page, page_size, error_or_None)."""
    try:
        page = 1 if page is None else int(page)
    except (TypeError, ValueError):
        return None, None, _error(
            400, "validation_error",
            f"body.page should be an integer, instead was {_shape(page)}.")
    try:
        page_size = 10 if page_size is None else int(page_size)
    except (TypeError, ValueError):
        return None, None, _error(
            400, "validation_error",
            f"body.page_size should be an integer, instead was {_shape(page_size)}.")
    if page < 1:
        return None, None, _error(
            400, "validation_error",
            f"body.page should be a positive integer, instead was {_shape(page)}.")
    page_size = max(1, min(page_size, 10))
    return page, page_size, None


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

    def _exists(self, table: str, id_col: str, id_val) -> bool:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM {table} WHERE {id_col} = ?", (id_val,))
        found = cur.fetchone() is not None
        conn.close()
        return found

    # ── Tool Methods ────────────────────────────────────────────────

    @tool(
        description=(
            "List clinical trial records with optional filters on status, phase, "
            "and therapeutic area. Each record includes the trial name, phase, "
            "status, site, and therapeutic area. Results are paginated; use the "
            "cursor to fetch subsequent pages."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by trial status (e.g., 'active', 'suspended', 'completed', 'terminated')",
                },
                "phase": {
                    "type": "integer",
                    "description": "Filter by trial phase (1, 2, 3, or 4)",
                },
                "therapeutic_area": {
                    "type": "string",
                    "description": "Filter by therapeutic area (e.g., 'oncology', 'cardiology')",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1. Default is 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Maximum 10. Default is 10.",
                },
            },
            "required": [],
        },
    )
    def list_trials(
        self,
        status: Any = None,
        phase: Any = None,
        therapeutic_area: Any = None,
        page: Any = 1,
        page_size: Any = 10,
    ) -> dict:
        page, page_size, err = _coerce_page(page, page_size)
        if err:
            return err
        if phase is not None:
            try:
                phase = int(phase)
            except (TypeError, ValueError):
                return _error(
                    400, "validation_error",
                    f"body.phase should be an integer, instead was {_shape(phase)}.")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        query = "SELECT trial_id, trial_name, phase, status, site_id, therapeutic_area FROM clinical_trials WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if phase is not None:
            query += " AND phase = ?"
            params.append(int(phase))
        if therapeutic_area:
            query += " AND therapeutic_area = ?"
            params.append(therapeutic_area)

        query += " ORDER BY trial_id"

        c.execute(query, params)
        all_rows = [dict(r) for r in c.fetchall()]
        conn.close()

        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size

        results = [
            {
                "object": "trial",
                "id": r["trial_id"],
                "properties": {
                    "Name": _title(r["trial_name"]),
                    "Phase": _number(r["phase"]),
                    "Status": _select(r["status"]),
                    "Site": _relation(r["site_id"]),
                    "Therapeutic Area": _select(r["therapeutic_area"]),
                },
            }
            for r in all_rows[start:end]
        ]
        has_more = end < total
        return {
            "object": "list",
            "results": results,
            "has_more": has_more,
            "next_cursor": page + 1 if has_more else None,
        }

    @tool(
        description=(
            "Get the full record for a specific clinical trial, including its "
            "name, phase, status, site, sponsor, start date, protocol version, "
            "and therapeutic area."
        ),
        parameters={
            "type": "object",
            "properties": {
                "trial_id": {
                    "type": "string",
                    "description": "The trial identifier (e.g., 'CT-0001')",
                },
            },
            "required": ["trial_id"],
        },
    )
    def get_trial_details(self, trial_id: Any = None) -> str:
        if not isinstance(trial_id, str) or not trial_id:
            return json.dumps(_error(
                400, "validation_error",
                f"body.trial_id should be a non-empty string, instead was {_shape(trial_id)}."))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM clinical_trials WHERE trial_id = ?", (trial_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return json.dumps(_error(
                404, "object_not_found",
                f"Could not find trial with ID: {trial_id}."))
        r = dict(row)
        payload = {
            "object": "trial",
            "id": r["trial_id"],
            "properties": {
                "Name": _title(r["trial_name"]),
                "Phase": _number(r["phase"]),
                "Status": _select(r["status"]),
                "Site": _relation(r["site_id"]),
                "Sponsor": _rich_text(r["sponsor"]),
                "Start Date": _date(r["start_date"]),
                "Protocol Version": _rich_text(r["protocol_version"]),
                "Therapeutic Area": _select(r["therapeutic_area"]),
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    @tool(
        description=(
            "Get the consent form records attached to a specific trial. Each "
            "record includes the form version, language, approval date, expiry "
            "date, status, and whether it covers genomic data and biobank use."
        ),
        parameters={
            "type": "object",
            "properties": {
                "trial_id": {
                    "type": "string",
                    "description": "The trial identifier (e.g., 'CT-0001')",
                },
            },
            "required": ["trial_id"],
        },
    )
    def get_consent_forms(self, trial_id: Any = None) -> dict:
        if not isinstance(trial_id, str) or not trial_id:
            return _error(
                400, "validation_error",
                f"body.trial_id should be a non-empty string, instead was {_shape(trial_id)}.")
        if not self._exists("clinical_trials", "trial_id", trial_id):
            return _error(
                404, "object_not_found",
                f"Could not find trial with ID: {trial_id}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM consent_forms WHERE trial_id = ? ORDER BY approval_date DESC",
            (trial_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        results = [
            {
                "object": "consent_form",
                "id": r["consent_id"],
                "properties": {
                    "Trial": _relation(r["trial_id"]),
                    "Form Version": _rich_text(r["form_version"]),
                    "Language": _select(r["language"]),
                    "Approval Date": _date(r["approval_date"]),
                    "Expiry Date": _date(r["expiry_date"]),
                    "Status": _select(r["status"]),
                    "Covers Genomic Data": _checkbox(r["covers_genomic_data"]),
                    "Covers Biobank": _checkbox(r["covers_biobank"]),
                },
            }
            for r in rows
        ]
        payload = {
            "object": "list",
            "results": results,
            "has_more": False,
            "next_cursor": None,
        }
        return _envelope(payload)

    @tool(
        description=(
            "Get the audit history for a specific site, optionally filtered by "
            "resolution status. Each record includes the audit date, auditor, "
            "finding category and description, severity, resolution status, and "
            "resolution date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "The site identifier (e.g., 'SITE-0001')",
                },
                "resolution_status": {
                    "type": "string",
                    "description": "Filter by resolution status ('open', 'in_progress', 'resolved', 'overdue')",
                },
            },
            "required": ["site_id"],
        },
    )
    def get_site_audits(self, site_id: Any = None, resolution_status: Any = None) -> dict:
        if not isinstance(site_id, str) or not site_id:
            return _error(
                400, "validation_error",
                f"body.site_id should be a non-empty string, instead was {_shape(site_id)}.")
        if not self._exists("trial_sites", "site_id", site_id):
            return _error(
                404, "object_not_found",
                f"Could not find site with ID: {site_id}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        query = "SELECT * FROM site_audits WHERE site_id = ?"
        params = [site_id]
        if resolution_status:
            query += " AND resolution_status = ?"
            params.append(resolution_status)
        query += " ORDER BY audit_date DESC"

        c.execute(query, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        results = [
            {
                "object": "audit_finding",
                "id": r["audit_id"],
                "properties": {
                    "Site": _relation(r["site_id"]),
                    "Audit Date": _date(r["audit_date"]),
                    "Auditor": _rich_text(r["auditor_name"]),
                    "Finding Category": _select(r["finding_category"]),
                    "Description": _rich_text(r["finding_description"]),
                    "Severity": _select(r["severity"]),
                    "Resolution Status": _select(r["resolution_status"]),
                    "Resolution Date": _date(r["resolution_date"]),
                },
            }
            for r in rows
        ]
        return {
            "object": "list",
            "results": results,
            "has_more": False,
            "next_cursor": None,
        }

    @tool(
        description=(
            "Get the profile of a specific trial site: name, region, country, "
            "certification level, capacity, last inspection date, and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "The site identifier (e.g., 'SITE-0001')",
                },
            },
            "required": ["site_id"],
        },
    )
    def get_site_info(self, site_id: Any = None):
        if not isinstance(site_id, str) or not site_id:
            return _error(
                400, "validation_error",
                f"body.site_id should be a non-empty string, instead was {_shape(site_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM trial_sites WHERE site_id = ?", (site_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return _error(
                404, "object_not_found",
                f"Could not find site with ID: {site_id}.")
        fields = dict(row)
        return "\n".join(f"{k}: {v}" for k, v in fields.items())

    @tool(
        description=(
            "List trial site records with optional filters on region, "
            "certification level, and status. Each record includes the site "
            "name, region, country, certification level, and status. Results "
            "are paginated; use the cursor to fetch subsequent pages."
        ),
        parameters={
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "Filter by region (e.g., 'North America', 'Europe', 'Asia Pacific', 'Latin America')",
                },
                "certification_level": {
                    "type": "string",
                    "description": "Filter by certification level ('A', 'B', or 'C')",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by site status ('active', 'probation', 'suspended')",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1. Default is 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Maximum 10. Default is 10.",
                },
            },
            "required": [],
        },
    )
    def list_sites(
        self,
        region: Any = None,
        certification_level: Any = None,
        status: Any = None,
        page: Any = 1,
        page_size: Any = 10,
    ) -> str:
        page, page_size, err = _coerce_page(page, page_size)
        if err:
            return json.dumps(err)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        query = "SELECT site_id, site_name, region, country, certification_level, status FROM trial_sites WHERE 1=1"
        params = []

        if region:
            query += " AND region = ?"
            params.append(region)
        if certification_level:
            query += " AND certification_level = ?"
            params.append(certification_level)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY site_id"

        c.execute(query, params)
        all_rows = [dict(r) for r in c.fetchall()]
        conn.close()

        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size

        results = [
            {
                "object": "site",
                "id": r["site_id"],
                "properties": {
                    "Name": _title(r["site_name"]),
                    "Region": _select(r["region"]),
                    "Country": _select(r["country"]),
                    "Certification Level": _select(r["certification_level"]),
                    "Status": _select(r["status"]),
                },
            }
            for r in all_rows[start:end]
        ]
        has_more = end < total
        payload = {
            "object": "list",
            "results": results,
            "has_more": has_more,
            "next_cursor": page + 1 if has_more else None,
        }
        return json.dumps(payload, ensure_ascii=False)

    @tool(
        description=(
            "Query the registry of existing safety guidelines, optionally "
            "filtered by category and severity level. Each record includes the "
            "guideline code, category, title, severity level, effective date, "
            "applicable phases and areas, and supersession status. Results are "
            "paginated; use the cursor to fetch subsequent pages."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by guideline category (e.g., 'adverse_event_reporting', 'dosage_monitoring')",
                },
                "severity_level": {
                    "type": "string",
                    "description": "Filter by severity level ('critical', 'major', 'minor')",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1. Default is 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Maximum 10. Default is 10.",
                },
            },
            "required": [],
        },
    )
    def query_guidelines(
        self,
        category: Any = None,
        severity_level: Any = None,
        page: Any = 1,
        page_size: Any = 10,
    ):
        page, page_size, err = _coerce_page(page, page_size)
        if err:
            return err

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        query = "SELECT * FROM safety_guidelines WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)
        if severity_level:
            query += " AND severity_level = ?"
            params.append(severity_level)

        query += " ORDER BY guideline_id"

        c.execute(query, params)
        all_rows = [dict(r) for r in c.fetchall()]
        conn.close()

        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size
        has_more = end < total

        payload = {
            "object": "list",
            "results": all_rows[start:end],
            "has_more": has_more,
            "next_cursor": page + 1 if has_more else None,
        }
        return repr(payload)

    # ── Step (Evaluation) ──────────────────────────────────────────

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
        eval_criteria = {}

        # Criterion 1: compliance_action_plan.csv exists and has correct structure (15 pts)
        cap_score, cap_reason = self._eval_action_plan_structure(ground_truth)
        eval_criteria["action_plan_structure"] = {
            "passed": cap_score == 15,
            "score": cap_score,
            "max_score": 15,
            "reason": cap_reason if cap_score < 15 else "",
        }

        # Criterion 2: correct trial-guideline pairs in action plan (20 pts)
        pairs_score, pairs_reason = self._eval_trial_guideline_pairs(ground_truth)
        eval_criteria["trial_guideline_pairs"] = {
            "passed": pairs_score == 20,
            "score": pairs_score,
            "max_score": 20,
            "reason": pairs_reason if pairs_score < 20 else "",
        }

        # Criterion 3: priority scores computed correctly (20 pts)
        pscore, preason = self._eval_priority_scores(ground_truth)
        eval_criteria["priority_scores"] = {
            "passed": pscore == 20,
            "score": pscore,
            "max_score": 20,
            "reason": preason if pscore < 20 else "",
        }

        # Criterion 4: amendment types assigned correctly (15 pts)
        atscore, atreason = self._eval_amendment_types(ground_truth)
        eval_criteria["amendment_types"] = {
            "passed": atscore == 15,
            "score": atscore,
            "max_score": 15,
            "reason": atreason if atscore < 15 else "",
        }

        # Criterion 5: consent_update_report.json correct (15 pts)
        cscore, creason = self._eval_consent_report(ground_truth)
        eval_criteria["consent_update_report"] = {
            "passed": cscore == 15,
            "score": cscore,
            "max_score": 15,
            "reason": creason if cscore < 15 else "",
        }

        # Criterion 6: action plan sorting and deadline correctness (15 pts)
        sscore, sreason = self._eval_sorting_and_deadlines(ground_truth)
        eval_criteria["sorting_and_deadlines"] = {
            "passed": sscore == 15,
            "score": sscore,
            "max_score": 15,
            "reason": sreason if sscore < 15 else "",
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    def _compute_ground_truth(self) -> dict:
        """Compute the full ground truth for evaluation."""
        import yaml

        # Load configs from workspace
        with open(os.path.join(self.workspace, "new_guidelines_2026.yaml")) as f:
            new_gl_data = yaml.safe_load(f)
        new_guidelines = new_gl_data["new_guidelines"]

        with open(os.path.join(self.workspace, "severity_matrix.json")) as f:
            severity_matrix = json.load(f)

        with open(os.path.join(self.workspace, "amendment_priority_rules.yaml")) as f:
            priority_rules = yaml.safe_load(f)

        phase_req = {}
        with open(os.path.join(self.workspace, "phase_requirements.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                phase_req[int(row["phase"])] = int(row["phase_bonus"])

        # Load site inspection risk scores from workspace
        site_risk_scores = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("site_inspection_") and fname.endswith(".md"):
                site_id = fname.replace("site_inspection_", "").replace(".md", "")
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as f:
                    content = f.read()
                # Extract risk score
                for line in content.split("\n"):
                    if line.startswith("## Overall Risk Score:"):
                        score_str = line.split(":")[-1].strip()
                        site_risk_scores[site_id] = int(score_str)
                        break

        # Load trial dossier deviation counts from workspace
        trial_deviations = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("trial_dossier_") and fname.endswith(".json"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as f:
                    dossier = json.load(f)
                trial_deviations[dossier["trial_id"]] = dossier["protocol_deviation_count"]

        # Query DB for active trials
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        active_trials = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM clinical_trials WHERE status = 'active' ORDER BY trial_id"
            ).fetchall()
        ]

        # Build audit data per site
        site_audits = {}
        for row in conn.execute("SELECT * FROM site_audits").fetchall():
            row = dict(row)
            site_audits.setdefault(row["site_id"], []).append(row)

        # Build consent data per trial
        trial_consents = {}
        for row in conn.execute("SELECT * FROM consent_forms").fetchall():
            row = dict(row)
            trial_consents.setdefault(row["trial_id"], []).append(row)

        conn.close()

        # Compute affected (trial, guideline) pairs
        action_plan_rows = []
        consent_updates = {}

        for gl in new_guidelines:
            gl_phases = gl["applies_to_phases"]
            gl_areas = gl["applies_to_areas"]

            for trial in active_trials:
                if trial["phase"] not in gl_phases:
                    continue
                if trial["therapeutic_area"] not in gl_areas:
                    continue

                # This trial is affected by this guideline
                site_id = trial["site_id"]
                trial_id = trial["trial_id"]

                # 1. Severity weight
                sev_weight = severity_matrix["severity_weights"].get(gl["severity"], 0)

                # 2. Audit penalty
                audits = site_audits.get(site_id, [])
                audit_penalty = 0
                has_open_critical = False
                for audit in audits:
                    res_status = audit["resolution_status"]
                    aud_sev = audit["severity"]
                    if res_status in severity_matrix["audit_finding_penalties"]:
                        penalty = severity_matrix["audit_finding_penalties"][res_status].get(aud_sev, 0)
                        audit_penalty += penalty
                    if res_status in ("open", "overdue") and aud_sev == "critical":
                        has_open_critical = True
                audit_penalty = min(audit_penalty, severity_matrix["audit_penalty_cap"])

                # 3. Consent penalty
                consents = trial_consents.get(trial_id, [])
                if not consents:
                    consent_penalty = severity_matrix["no_consent_penalty"]
                    consent_status_label = "missing"
                else:
                    # Use the most recent consent form
                    latest = max(consents, key=lambda x: x["approval_date"])
                    consent_status_label = latest["status"]
                    consent_penalty = severity_matrix["consent_penalties"].get(
                        latest["status"], 0
                    )

                # 4. Phase bonus
                p_bonus = phase_req.get(trial["phase"], 0)

                # 5. Site risk penalty (from workspace inspection files)
                site_risk_penalty = 0
                if site_id in site_risk_scores:
                    if site_risk_scores[site_id] > severity_matrix["site_risk_score_threshold"]:
                        site_risk_penalty = severity_matrix["site_risk_penalty"]

                # 6. Deviation penalty (from workspace dossier files)
                dev_penalty = 0
                if trial_id in trial_deviations:
                    if trial_deviations[trial_id] > severity_matrix["deviation_count_threshold"]:
                        dev_penalty = severity_matrix["deviation_penalty"]

                priority_score = (
                    sev_weight + audit_penalty + consent_penalty + p_bonus
                    + site_risk_penalty + dev_penalty
                )

                # Determine amendment type
                consent_expired_or_missing = consent_status_label in ("expired", "missing")
                consent_current_or_pending = consent_status_label in ("current", "pending_review")

                if gl["consent_update_required"] and consent_expired_or_missing:
                    amendment_type = "urgent_consent_revision"
                elif gl["consent_update_required"] and consent_current_or_pending:
                    amendment_type = "consent_and_protocol_update"
                elif has_open_critical:
                    amendment_type = "site_remediation_protocol"
                else:
                    amendment_type = "standard_protocol_revision"

                # Determine deadline
                deadline_days = 120
                for bracket in priority_rules["deadline_brackets"]:
                    if priority_score >= bracket["min_priority_score"]:
                        deadline_days = bracket["deadline_days"]
                        break

                row = {
                    "trial_id": trial_id,
                    "trial_name": trial["trial_name"],
                    "site_id": site_id,
                    "guideline_code": gl["code"],
                    "guideline_category": gl["category"],
                    "severity": gl["severity"],
                    "priority_score": priority_score,
                    "amendment_type": amendment_type,
                    "deadline_days": deadline_days,
                }
                action_plan_rows.append(row)

                # Track consent updates
                if gl["consent_update_required"]:
                    if trial_id not in consent_updates:
                        latest_ver = "none"
                        if consents:
                            latest = max(consents, key=lambda x: x["approval_date"])
                            latest_ver = latest["form_version"]
                        consent_updates[trial_id] = {
                            "trial_id": trial_id,
                            "trial_name": trial["trial_name"],
                            "current_form_version": latest_ver,
                            "affected_guideline_codes": [],
                        }
                    consent_updates[trial_id]["affected_guideline_codes"].append(gl["code"])

        # Sort action plan by priority_score descending, then trial_id ascending, then guideline_code ascending
        action_plan_rows.sort(
            key=lambda r: (-r["priority_score"], r["trial_id"], r["guideline_code"])
        )

        # Sort consent updates
        consent_update_list = sorted(consent_updates.values(), key=lambda x: x["trial_id"])
        for entry in consent_update_list:
            entry["affected_guideline_codes"].sort()

        return {
            "action_plan": action_plan_rows,
            "consent_updates": consent_update_list,
        }

    def _read_agent_action_plan(self) -> list:
        """Read the agent's compliance_action_plan.csv from workspace."""
        path = os.path.join(self.workspace, "compliance_action_plan.csv")
        if not os.path.exists(path):
            return None
        rows = []
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows

    def _read_agent_consent_report(self) -> list:
        """Read the agent's consent_update_report.json from workspace."""
        path = os.path.join(self.workspace, "consent_update_report.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def _eval_action_plan_structure(self, gt: dict) -> tuple:
        """Check action plan file exists with correct columns in the specified order."""
        rows = self._read_agent_action_plan()
        if rows is None:
            return 0, "compliance_action_plan.csv not found"

        expected_ordered = [
            "trial_id", "trial_name", "site_id", "guideline_code",
            "guideline_category", "severity", "priority_score",
            "amendment_type", "deadline_days",
        ]
        expected_cols = set(expected_ordered)

        if not rows:
            return 5, "File exists but is empty"

        actual_cols = set(rows[0].keys())
        missing = expected_cols - actual_cols
        if missing:
            if len(missing) <= 2:
                return 10, f"Missing columns: {missing}"
            return 5, f"Missing columns: {missing}"

        # All required columns present — also verify the specified column order
        actual_ordered = list(rows[0].keys())[:len(expected_ordered)]
        if actual_ordered == expected_ordered:
            return 15, ""
        return 12, f"Columns present but not in the specified order (got {actual_ordered})"

    def _eval_trial_guideline_pairs(self, gt: dict) -> tuple:
        """Check that the correct (trial_id, guideline_code) pairs are present."""
        rows = self._read_agent_action_plan()
        if rows is None:
            return 0, "compliance_action_plan.csv not found"

        expected_pairs = {(r["trial_id"], r["guideline_code"]) for r in gt["action_plan"]}
        actual_pairs = set()
        for r in rows:
            tid = r.get("trial_id", "")
            gc = r.get("guideline_code", "")
            if tid and gc:
                actual_pairs.add((tid, gc))

        if not expected_pairs:
            return 20 if not actual_pairs else 0, "No expected pairs"

        correct = expected_pairs & actual_pairs
        precision = len(correct) / len(actual_pairs) if actual_pairs else 0
        recall = len(correct) / len(expected_pairs)
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        score = round(f1 * 20)
        reason = ""
        if score < 20:
            reason = f"F1={f1:.3f}, expected {len(expected_pairs)} pairs, got {len(actual_pairs)}, {len(correct)} correct"
        return score, reason

    def _eval_priority_scores(self, gt: dict) -> tuple:
        """Check priority scores are correctly computed."""
        rows = self._read_agent_action_plan()
        if rows is None:
            return 0, "compliance_action_plan.csv not found"

        gt_map = {
            (r["trial_id"], r["guideline_code"]): r["priority_score"]
            for r in gt["action_plan"]
        }

        if not gt_map:
            return 20, ""

        correct = 0
        total = len(gt_map)
        checked = 0

        for r in rows:
            key = (r.get("trial_id", ""), r.get("guideline_code", ""))
            if key in gt_map:
                checked += 1
                try:
                    agent_score = int(float(r.get("priority_score", -1)))
                    if agent_score == gt_map[key]:
                        correct += 1
                except (ValueError, TypeError):
                    pass

        if checked == 0:
            return 0, "No matching pairs found to evaluate scores"

        ratio = correct / total
        score = round(ratio * 20)
        reason = ""
        if score < 20:
            reason = f"{correct}/{total} priority scores correct"
        return score, reason

    def _eval_amendment_types(self, gt: dict) -> tuple:
        """Check amendment types are correctly assigned."""
        rows = self._read_agent_action_plan()
        if rows is None:
            return 0, "compliance_action_plan.csv not found"

        gt_map = {
            (r["trial_id"], r["guideline_code"]): r["amendment_type"]
            for r in gt["action_plan"]
        }

        if not gt_map:
            return 15, ""

        correct = 0
        total = len(gt_map)

        for r in rows:
            key = (r.get("trial_id", ""), r.get("guideline_code", ""))
            if key in gt_map:
                if r.get("amendment_type", "").strip() == gt_map[key]:
                    correct += 1

        ratio = correct / total
        score = round(ratio * 15)
        reason = ""
        if score < 15:
            reason = f"{correct}/{total} amendment types correct"
        return score, reason

    def _eval_consent_report(self, gt: dict) -> tuple:
        """Check consent_update_report.json correctness."""
        agent_report = self._read_agent_consent_report()
        if agent_report is None:
            return 0, "consent_update_report.json not found"

        expected = gt["consent_updates"]

        if not expected:
            return 15 if not agent_report else 10, ""

        # Check trial IDs match
        expected_ids = {e["trial_id"] for e in expected}
        actual_ids = set()
        for entry in agent_report:
            tid = entry.get("trial_id", "")
            if tid:
                actual_ids.add(tid)

        id_overlap = expected_ids & actual_ids
        if not id_overlap:
            return 0, "No matching trial IDs in consent report"

        # Check guideline codes for matching entries
        expected_map = {e["trial_id"]: e for e in expected}
        codes_correct = 0
        codes_total = 0
        version_correct = 0

        for entry in agent_report:
            tid = entry.get("trial_id", "")
            if tid in expected_map:
                exp = expected_map[tid]
                codes_total += 1

                # Check affected_guideline_codes
                agent_codes = sorted(entry.get("affected_guideline_codes", []))
                exp_codes = sorted(exp["affected_guideline_codes"])
                if agent_codes == exp_codes:
                    codes_correct += 1

                # Check form version
                if entry.get("current_form_version", "") == exp["current_form_version"]:
                    version_correct += 1

        # Score: 7 pts for trial coverage, 5 pts for correct guideline codes, 3 pts for versions
        coverage_score = round(len(id_overlap) / len(expected_ids) * 7) if expected_ids else 7
        codes_score = round(codes_correct / codes_total * 5) if codes_total else 0
        version_score = round(version_correct / codes_total * 3) if codes_total else 0

        total = coverage_score + codes_score + version_score
        reason = ""
        if total < 15:
            reason = f"Coverage: {len(id_overlap)}/{len(expected_ids)}, codes: {codes_correct}/{codes_total}, versions: {version_correct}/{codes_total}"

        # Verify the array is sorted by trial_id ascending, as required
        if len(agent_report) > 1:
            ids = [e.get("trial_id", "") for e in agent_report]
            if ids != sorted(ids):
                total = max(0, total - 2)
                sort_note = "consent_update_report.json not sorted by trial_id ascending"
                reason = f"{reason}; {sort_note}" if reason else sort_note

        return total, reason

    def _eval_sorting_and_deadlines(self, gt: dict) -> tuple:
        """Check sorting order and deadline correctness."""
        rows = self._read_agent_action_plan()
        if rows is None:
            return 0, "compliance_action_plan.csv not found"

        gt_rows = gt["action_plan"]
        if not gt_rows:
            return 15, ""

        # Check sorting (8 pts): should be by priority_score desc, trial_id asc, guideline_code asc
        sort_score = 0
        if len(rows) >= 2:
            correctly_sorted = True
            for i in range(len(rows) - 1):
                try:
                    s1 = int(float(rows[i].get("priority_score", 0)))
                    s2 = int(float(rows[i + 1].get("priority_score", 0)))
                    t1 = rows[i].get("trial_id", "")
                    t2 = rows[i + 1].get("trial_id", "")
                    g1 = rows[i].get("guideline_code", "")
                    g2 = rows[i + 1].get("guideline_code", "")

                    if s1 > s2:
                        continue
                    elif s1 == s2:
                        if t1 < t2:
                            continue
                        elif t1 == t2:
                            if g1 <= g2:
                                continue
                        correctly_sorted = False
                        break
                    else:
                        correctly_sorted = False
                        break
                except (ValueError, TypeError):
                    correctly_sorted = False
                    break

            sort_score = 8 if correctly_sorted else 0
        elif len(rows) == 1:
            sort_score = 8

        # Check deadlines (7 pts)
        gt_map = {
            (r["trial_id"], r["guideline_code"]): r["deadline_days"]
            for r in gt_rows
        }

        correct_dl = 0
        total_dl = len(gt_map)

        for r in rows:
            key = (r.get("trial_id", ""), r.get("guideline_code", ""))
            if key in gt_map:
                try:
                    agent_dl = int(float(r.get("deadline_days", -1)))
                    if agent_dl == gt_map[key]:
                        correct_dl += 1
                except (ValueError, TypeError):
                    pass

        dl_ratio = correct_dl / total_dl if total_dl else 1
        dl_score = round(dl_ratio * 7)

        total = sort_score + dl_score
        reason = ""
        if total < 15:
            parts = []
            if sort_score < 8:
                parts.append("Incorrect sort order")
            if dl_score < 7:
                parts.append(f"{correct_dl}/{total_dl} deadlines correct")
            reason = "; ".join(parts)

        return total, reason

    # ── Verify ─────────────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        Consumes the hardened tool surface: nested record objects, JSON-encoded
        strings, MCP envelopes, key:value text, repr strings, cursor pagination.
        """
        import yaml

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # ── nested-record extraction helpers ──
        def prop_title(rec, key):
            return rec["properties"][key]["title"][0]["plain_text"]

        def prop_select(rec, key):
            return rec["properties"][key]["select"]["name"]

        def prop_number(rec, key):
            return rec["properties"][key]["number"]

        def prop_relation(rec, key):
            return rec["properties"][key]["relation"][0]["id"]

        def prop_rich_text(rec, key):
            return rec["properties"][key]["rich_text"][0]["plain_text"]

        def prop_date(rec, key):
            d = rec["properties"][key]["date"]
            return d["start"] if d else None

        def unwrap_envelope(resp):
            return json.loads(resp["content"][0]["text"])

        def parse_kv_text(text):
            out = {}
            for line in text.split("\n"):
                k, _, v = line.partition(": ")
                out[k] = v
            return out

        # Step 1: Read workspace config files
        with open(os.path.join(self.workspace, "new_guidelines_2026.yaml")) as f:
            new_gl_data = yaml.safe_load(f)
        new_guidelines = new_gl_data["new_guidelines"]

        with open(os.path.join(self.workspace, "severity_matrix.json")) as f:
            severity_matrix = json.load(f)

        with open(os.path.join(self.workspace, "amendment_priority_rules.yaml")) as f:
            priority_rules = yaml.safe_load(f)

        phase_req = {}
        with open(os.path.join(self.workspace, "phase_requirements.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                phase_req[int(row["phase"])] = int(row["phase_bonus"])

        # Load site inspection risk scores
        site_risk_scores = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("site_inspection_") and fname.endswith(".md"):
                site_id = fname.replace("site_inspection_", "").replace(".md", "")
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                for line in content.split("\n"):
                    if line.startswith("## Overall Risk Score:"):
                        site_risk_scores[site_id] = int(line.split(":")[-1].strip())
                        break

        # Load trial dossier deviation counts
        trial_deviations = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("trial_dossier_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    dossier = json.load(f)
                trial_deviations[dossier["trial_id"]] = dossier["protocol_deviation_count"]

        # Step 2: Gather all active trials via cursor-paginated nested list tool
        active_trial_ids = []
        page = 1
        while True:
            result = call_tool("list_trials", status="active", page=page, page_size=10)
            for rec in result["results"]:
                active_trial_ids.append(rec["id"])
            if not result["has_more"]:
                break
            page = result["next_cursor"]

        # Step 3: Get detailed info for each active trial (JSON-encoded string)
        trial_details = {}
        for tid in active_trial_ids:
            raw = call_tool("get_trial_details", trial_id=tid)
            rec = json.loads(raw)
            trial_details[tid] = {
                "trial_id": rec["id"],
                "trial_name": prop_title(rec, "Name"),
                "phase": prop_number(rec, "Phase"),
                "therapeutic_area": prop_select(rec, "Therapeutic Area"),
                "site_id": prop_relation(rec, "Site"),
            }

        # Exercise the remaining surface once: JSON-string site list + repr guideline registry
        raw_sites = call_tool("list_sites", page=1, page_size=10)
        sites_page = json.loads(raw_sites)
        assert sites_page["object"] == "list"
        raw_gl = call_tool("query_guidelines", page=1, page_size=10)
        gl_page = ast.literal_eval(raw_gl)
        assert gl_page["object"] == "list"

        # Step 4: For each guideline, find affected trials and gather data
        action_plan_rows = []
        consent_updates = {}
        site_audit_cache = {}
        site_info_cache = {}
        consent_cache = {}

        for gl in new_guidelines:
            gl_phases = gl["applies_to_phases"]
            gl_areas = gl["applies_to_areas"]

            for tid in active_trial_ids:
                td = trial_details[tid]
                if td["phase"] not in gl_phases:
                    continue
                if td["therapeutic_area"] not in gl_areas:
                    continue

                trial_id = td["trial_id"]
                site_id = td["site_id"]

                # Get consent forms via tool (MCP envelope, nested records; cached)
                if trial_id not in consent_cache:
                    resp = call_tool("get_consent_forms", trial_id=trial_id)
                    consent_page = unwrap_envelope(resp)
                    consent_cache[trial_id] = [
                        {
                            "form_version": prop_rich_text(rec, "Form Version"),
                            "approval_date": prop_date(rec, "Approval Date"),
                            "status": prop_select(rec, "Status"),
                        }
                        for rec in consent_page["results"]
                    ]
                consents = consent_cache[trial_id]

                # Get site audits via tool (native nested list; cached)
                if site_id not in site_audit_cache:
                    audit_page = call_tool("get_site_audits", site_id=site_id)
                    site_audit_cache[site_id] = [
                        {
                            "resolution_status": prop_select(rec, "Resolution Status"),
                            "severity": prop_select(rec, "Severity"),
                        }
                        for rec in audit_page["results"]
                    ]
                audits = site_audit_cache[site_id]

                # Get site info (key:value text; cached)
                if site_id not in site_info_cache:
                    site_info_cache[site_id] = parse_kv_text(
                        call_tool("get_site_info", site_id=site_id)
                    )

                # Compute priority score
                sev_weight = severity_matrix["severity_weights"].get(gl["severity"], 0)

                audit_penalty = 0
                has_open_critical = False
                for audit in audits:
                    res_status = audit["resolution_status"]
                    aud_sev = audit["severity"]
                    if res_status in severity_matrix["audit_finding_penalties"]:
                        penalty = severity_matrix["audit_finding_penalties"][res_status].get(aud_sev, 0)
                        audit_penalty += penalty
                    if res_status in ("open", "overdue") and aud_sev == "critical":
                        has_open_critical = True
                audit_penalty = min(audit_penalty, severity_matrix["audit_penalty_cap"])

                if not consents:
                    consent_penalty = severity_matrix["no_consent_penalty"]
                    consent_status_label = "missing"
                else:
                    latest = max(consents, key=lambda x: x["approval_date"])
                    consent_status_label = latest["status"]
                    consent_penalty = severity_matrix["consent_penalties"].get(
                        latest["status"], 0
                    )

                p_bonus = phase_req.get(td["phase"], 0)

                site_risk_penalty = 0
                if site_id in site_risk_scores:
                    if site_risk_scores[site_id] > severity_matrix["site_risk_score_threshold"]:
                        site_risk_penalty = severity_matrix["site_risk_penalty"]

                dev_penalty = 0
                if trial_id in trial_deviations:
                    if trial_deviations[trial_id] > severity_matrix["deviation_count_threshold"]:
                        dev_penalty = severity_matrix["deviation_penalty"]

                priority_score = (
                    sev_weight + audit_penalty + consent_penalty + p_bonus
                    + site_risk_penalty + dev_penalty
                )

                # Amendment type
                consent_expired_or_missing = consent_status_label in ("expired", "missing")
                consent_current_or_pending = consent_status_label in ("current", "pending_review")

                if gl["consent_update_required"] and consent_expired_or_missing:
                    amendment_type = "urgent_consent_revision"
                elif gl["consent_update_required"] and consent_current_or_pending:
                    amendment_type = "consent_and_protocol_update"
                elif has_open_critical:
                    amendment_type = "site_remediation_protocol"
                else:
                    amendment_type = "standard_protocol_revision"

                # Deadline
                deadline_days = 120
                for bracket in priority_rules["deadline_brackets"]:
                    if priority_score >= bracket["min_priority_score"]:
                        deadline_days = bracket["deadline_days"]
                        break

                action_plan_rows.append({
                    "trial_id": trial_id,
                    "trial_name": td["trial_name"],
                    "site_id": site_id,
                    "guideline_code": gl["code"],
                    "guideline_category": gl["category"],
                    "severity": gl["severity"],
                    "priority_score": priority_score,
                    "amendment_type": amendment_type,
                    "deadline_days": deadline_days,
                })

                # Consent update tracking
                if gl["consent_update_required"]:
                    if trial_id not in consent_updates:
                        latest_ver = "none"
                        if consents:
                            latest = max(consents, key=lambda x: x["approval_date"])
                            latest_ver = latest["form_version"]
                        consent_updates[trial_id] = {
                            "trial_id": trial_id,
                            "trial_name": td["trial_name"],
                            "current_form_version": latest_ver,
                            "affected_guideline_codes": [],
                        }
                    consent_updates[trial_id]["affected_guideline_codes"].append(gl["code"])

        # Sort action plan
        action_plan_rows.sort(
            key=lambda r: (-r["priority_score"], r["trial_id"], r["guideline_code"])
        )

        # Sort consent updates
        consent_update_list = sorted(consent_updates.values(), key=lambda x: x["trial_id"])
        for entry in consent_update_list:
            entry["affected_guideline_codes"].sort()

        # Write compliance_action_plan.csv
        cap_path = os.path.join(self.workspace, "compliance_action_plan.csv")
        fieldnames = [
            "trial_id", "trial_name", "site_id", "guideline_code",
            "guideline_category", "severity", "priority_score",
            "amendment_type", "deadline_days",
        ]
        with open(cap_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(action_plan_rows)

        # Write consent_update_report.json
        cr_path = os.path.join(self.workspace, "consent_update_report.json")
        with open(cr_path, "w") as f:
            json.dump(consent_update_list, f, indent=2)

        # Construct action string
        action = (
            f"Compliance action plan generated with {len(action_plan_rows)} entries "
            f"covering {len(set(r['trial_id'] for r in action_plan_rows))} affected trials "
            f"across {len(set(r['guideline_code'] for r in action_plan_rows))} new guidelines. "
            f"Consent update report identifies {len(consent_update_list)} trials requiring "
            f"consent form revisions. Files saved: compliance_action_plan.csv and "
            f"consent_update_report.json."
        )

        print(f"Verify: {tool_call_count} tool calls made")
        return self.step(action)
