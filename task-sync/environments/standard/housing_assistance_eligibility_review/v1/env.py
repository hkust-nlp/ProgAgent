import sqlite3
import os
import json
import csv
import re
import glob as globmod
import yaml
from typing import Tuple, Dict, List, Any


# --- Decorator for tool registration ---
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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description="List tenants with pagination. Returns tenant_id, first_name, last_name, and active status for each tenant.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of tenants per page. Default 20.",
                },
            },
            "required": ["page"],
        },
    )
    def list_tenants(self, page: int, page_size: int = 20) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        offset = (page - 1) * page_size
        c.execute(
            "SELECT tenant_id, first_name, last_name, active FROM tenants ORDER BY tenant_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = c.fetchall()
        c.execute("SELECT COUNT(*) FROM tenants")
        total = c.fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_tenants": total,
            "total_pages": (total + page_size - 1) // page_size,
            "tenants": [
                {"tenant_id": r[0], "first_name": r[1], "last_name": r[2], "active": bool(r[3])}
                for r in rows
            ],
        }

    @tool(
        description="Retrieve full details for a specific tenant by tenant_id.",
        parameters={
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "The tenant identifier, e.g. T0001.",
                },
            },
            "required": ["tenant_id"],
        },
    )
    def get_tenant(self, tenant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": f"Tenant {tenant_id} not found."}
        cols = ["tenant_id", "first_name", "last_name", "property_id",
                "unit_number", "region_code", "bedroom_count",
                "program_type", "enrollment_date", "active"]
        return dict(zip(cols, row))

    @tool(
        description="Retrieve all income certifications for a tenant, ordered by certification_date descending (most recent first).",
        parameters={
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "The tenant identifier.",
                },
            },
            "required": ["tenant_id"],
        },
    )
    def get_income_certifications(self, tenant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """SELECT cert_id, tenant_id, certification_date, annual_income,
                      income_source, household_size, dependents, is_verified
               FROM income_certifications
               WHERE tenant_id = ?
               ORDER BY certification_date DESC""",
            (tenant_id,),
        )
        rows = c.fetchall()
        conn.close()
        cols = ["cert_id", "tenant_id", "certification_date", "annual_income",
                "income_source", "household_size", "dependents", "is_verified"]
        return {"certifications": [dict(zip(cols, r)) for r in rows]}

    @tool(
        description="Retrieve the most recent property inspection for a given property_id.",
        parameters={
            "type": "object",
            "properties": {
                "property_id": {
                    "type": "string",
                    "description": "The property identifier, e.g. P0001.",
                },
            },
            "required": ["property_id"],
        },
    )
    def get_property_inspection(self, property_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """SELECT inspection_id, property_id, inspection_date, overall_score,
                      health_safety_score, maintenance_score, deficiency_count
               FROM inspections
               WHERE property_id = ?
               ORDER BY inspection_date DESC LIMIT 1""",
            (property_id,),
        )
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": f"No inspection found for property {property_id}."}
        cols = ["inspection_id", "property_id", "inspection_date", "overall_score",
                "health_safety_score", "maintenance_score", "deficiency_count"]
        return dict(zip(cols, row))

    @tool(
        description="Look up the Fair Market Rent for a given region and bedroom count. Returns the most recent year's FMR.",
        parameters={
            "type": "object",
            "properties": {
                "region_code": {
                    "type": "string",
                    "description": "Region code, e.g. NE-101.",
                },
                "bedroom_count": {
                    "type": "integer",
                    "description": "Number of bedrooms (0-4).",
                },
            },
            "required": ["region_code", "bedroom_count"],
        },
    )
    def lookup_fmr(self, region_code: str, bedroom_count: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """SELECT monthly_fmr, effective_year
               FROM fair_market_rents
               WHERE region_code = ? AND bedroom_count = ?
               ORDER BY effective_year DESC LIMIT 1""",
            (region_code, bedroom_count),
        )
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": f"No FMR data for region={region_code}, bedrooms={bedroom_count}."}
        return {"monthly_fmr": row[0], "effective_year": row[1]}

    # ------------------------------------------------------------------
    # Ground-truth computation (shared by step and verify)
    # ------------------------------------------------------------------

    def _load_workspace_data(self):
        """Load all workspace data needed for ground-truth computation."""
        ws = self.workspace

        # Policy
        with open(os.path.join(ws, "policy", "eligibility_rules.yaml")) as f:
            policy = yaml.safe_load(f)

        # Utility allowance schedule
        ua_map = {}
        with open(os.path.join(ws, "policy", "utility_allowance_schedule.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ua_map[(row["region_code"], int(row["bedroom_count"]))] = float(row["monthly_allowance"])

        # Current benefits
        benefits = {}
        with open(os.path.join(ws, "current_benefits.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                benefits[row["tenant_id"]] = float(row["current_monthly_benefit"])

        # Household profiles
        profiles = {}
        for fpath in sorted(globmod.glob(os.path.join(ws, "profiles", "*.json"))):
            with open(fpath) as f:
                data = json.load(f)
                profiles.update(data)

        # Compliance rates
        compliance = {}
        for fpath in sorted(globmod.glob(os.path.join(ws, "compliance", "*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    compliance[row["tenant_id"]] = float(row["utility_compliance_rate"])

        # AMI data
        ami_map = {}
        for fpath in sorted(globmod.glob(os.path.join(ws, "ami_data", "*.yaml"))):
            with open(fpath) as f:
                data = yaml.safe_load(f)
                for rec in data.get("ami_records", []):
                    ami_map[(rec["region_code"], rec["household_size"])] = rec["area_median_income"]

        # Inspection critical deficiencies (parse MD files)
        critical_props = set()
        for fpath in sorted(globmod.glob(os.path.join(ws, "inspections", "*.md"))):
            with open(fpath) as f:
                content = f.read()
            # Find all property sections
            sections = re.split(r"^## Property ", content, flags=re.MULTILINE)
            for section in sections:
                if not section.strip():
                    continue
                prop_match = re.match(r"(P\d+)", section)
                if not prop_match:
                    continue
                prop_id = prop_match.group(1)
                if re.search(r"\[CRITICAL\]", section):
                    critical_props.add(prop_id)

        return {
            "policy": policy,
            "ua_map": ua_map,
            "benefits": benefits,
            "profiles": profiles,
            "compliance": compliance,
            "ami_map": ami_map,
            "critical_props": critical_props,
        }

    def _compute_ground_truth(self):
        """Compute the correct case roster from DB + workspace."""
        ws_data = self._load_workspace_data()
        policy = ws_data["policy"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Get all active tenants
        c.execute("SELECT * FROM tenants WHERE active = 1 ORDER BY tenant_id")
        active_tenants = [dict(r) for r in c.fetchall()]

        roster = []
        for t in active_tenants:
            tid = t["tenant_id"]
            region = t["region_code"]
            bedrooms = t["bedroom_count"]
            prop_id = t["property_id"]

            # Latest income cert
            c.execute(
                """SELECT annual_income, household_size FROM income_certifications
                   WHERE tenant_id = ? ORDER BY certification_date DESC LIMIT 1""",
                (tid,),
            )
            cert_row = c.fetchone()
            annual_income = cert_row["annual_income"]

            # Current household size from workspace profiles
            profile = ws_data["profiles"].get(tid, {})
            current_hh_size = profile.get("current_household_size", cert_row["household_size"])

            # Income limit
            ami = ws_data["ami_map"].get((region, current_hh_size), 0)
            income_limit = round(ami * policy["income_threshold_pct"], 2)

            # Utility compliance
            comp_rate = ws_data["compliance"].get(tid, 1.0)

            # Inspection
            c.execute(
                """SELECT overall_score FROM inspections
                   WHERE property_id = ? ORDER BY inspection_date DESC LIMIT 1""",
                (prop_id,),
            )
            insp_row = c.fetchone()
            insp_score = insp_row["overall_score"] if insp_row else 100
            has_critical = prop_id in ws_data["critical_props"]

            # FMR
            c.execute(
                """SELECT monthly_fmr FROM fair_market_rents
                   WHERE region_code = ? AND bedroom_count = ?
                   ORDER BY effective_year DESC LIMIT 1""",
                (region, bedrooms),
            )
            fmr_row = c.fetchone()
            fmr = fmr_row["monthly_fmr"]

            # Utility allowance
            ua = ws_data["ua_map"].get((region, bedrooms), 0)

            # Current benefit
            current_benefit = ws_data["benefits"].get(tid, 0.0)

            # New benefit calculation
            contribution = max(annual_income * policy["rent_burden_ratio"] / 12.0,
                               policy["minimum_rent"])
            new_benefit = round(max(fmr + ua - contribution, 0.0), 2)

            # Determination
            determination = "MAINTAIN"
            if annual_income > income_limit:
                determination = "TERMINATE"
            elif comp_rate < policy["min_utility_compliance"]:
                determination = "TERMINATE"
            elif insp_score < policy["min_inspection_score"] or has_critical:
                determination = "SUSPEND"
            elif new_benefit <= 0:
                determination = "TERMINATE"
            elif current_benefit > 0:
                change_ratio = (new_benefit - current_benefit) / current_benefit
                if change_ratio > policy["adjustment_threshold"]:
                    determination = "ADJUST_UP"
                elif change_ratio < -policy["adjustment_threshold"]:
                    determination = "ADJUST_DOWN"

            tenant_name = f"{t['first_name']} {t['last_name']}"
            roster.append({
                "tenant_id": tid,
                "tenant_name": tenant_name,
                "region_code": region,
                "program_type": t["program_type"],
                "household_size": current_hh_size,
                "annual_income": round(annual_income, 2),
                "income_limit": income_limit,
                "utility_compliance": comp_rate,
                "inspection_score": insp_score,
                "current_benefit": current_benefit,
                "new_benefit": new_benefit,
                "determination": determination,
            })

        conn.close()

        # Sort: determination order, then tenant_id
        det_order = {"TERMINATE": 0, "SUSPEND": 1, "ADJUST_DOWN": 2, "ADJUST_UP": 3, "MAINTAIN": 4}
        roster.sort(key=lambda r: (det_order.get(r["determination"], 9), r["tenant_id"]))

        return roster

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
        gt_roster = self._compute_ground_truth()
        gt_by_id = {r["tenant_id"]: r for r in gt_roster}

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ------ Criterion 1: File existence & structure (10 pts) ------
        c1_max = 10
        max_score += c1_max
        roster_path = os.path.join(self.workspace, "case_roster.csv")
        required_cols = [
            "tenant_id", "tenant_name", "region_code", "program_type",
            "household_size", "annual_income", "income_limit",
            "utility_compliance", "inspection_score", "current_benefit",
            "new_benefit", "determination",
        ]
        agent_rows = []
        if os.path.exists(roster_path):
            try:
                with open(roster_path) as f:
                    reader = csv.DictReader(f)
                    headers = reader.fieldnames or []
                    missing_cols = [c for c in required_cols if c not in headers]
                    if not missing_cols:
                        agent_rows = list(reader)
                        c1_score = c1_max
                        c1_pass = True
                        c1_reason = ""
                    else:
                        c1_score = 3
                        c1_pass = False
                        c1_reason = f"Missing columns: {missing_cols}"
            except Exception as e:
                c1_score = 0
                c1_pass = False
                c1_reason = f"Error reading CSV: {e}"
        else:
            c1_score = 0
            c1_pass = False
            c1_reason = "case_roster.csv not found in workspace."
        total_score += c1_score
        eval_criteria["file_structure"] = {
            "passed": c1_pass, "score": c1_score, "max_score": c1_max,
            **({"reason": c1_reason} if not c1_pass else {}),
        }

        # ------ Criterion 2: Tenant coverage (10 pts) ------
        c2_max = 10
        max_score += c2_max
        agent_ids = {r.get("tenant_id", "").strip() for r in agent_rows}
        gt_ids = set(gt_by_id.keys())
        correct_ids = agent_ids & gt_ids
        if gt_ids:
            c2_score = round(c2_max * len(correct_ids) / len(gt_ids), 2)
        else:
            c2_score = c2_max
        c2_pass = correct_ids == gt_ids
        total_score += c2_score
        eval_criteria["tenant_coverage"] = {
            "passed": c2_pass, "score": c2_score, "max_score": c2_max,
            **({"reason": f"Expected {len(gt_ids)} tenants, found {len(correct_ids)} correct."} if not c2_pass else {}),
        }

        # Build agent lookup
        agent_by_id = {}
        for r in agent_rows:
            tid = r.get("tenant_id", "").strip()
            if tid:
                agent_by_id[tid] = r

        # ------ Criterion 3: Income limit accuracy (20 pts) ------
        c3_max = 20
        max_score += c3_max
        c3_correct = 0
        c3_total = len(gt_roster)
        for gt in gt_roster:
            ar = agent_by_id.get(gt["tenant_id"])
            if ar:
                try:
                    agent_val = float(ar.get("income_limit", -1))
                    if abs(agent_val - gt["income_limit"]) <= 1.0:
                        c3_correct += 1
                except (ValueError, TypeError):
                    pass
        c3_score = round(c3_max * c3_correct / max(c3_total, 1), 2)
        c3_pass = c3_correct == c3_total
        total_score += c3_score
        eval_criteria["income_limit_accuracy"] = {
            "passed": c3_pass, "score": c3_score, "max_score": c3_max,
            **({"reason": f"{c3_correct}/{c3_total} correct."} if not c3_pass else {}),
        }

        # ------ Criterion 4: Utility compliance accuracy (10 pts) ------
        c4_max = 10
        max_score += c4_max
        c4_correct = 0
        for gt in gt_roster:
            ar = agent_by_id.get(gt["tenant_id"])
            if ar:
                try:
                    agent_val = float(ar.get("utility_compliance", -1))
                    if abs(agent_val - gt["utility_compliance"]) <= 0.02:
                        c4_correct += 1
                except (ValueError, TypeError):
                    pass
        c4_score = round(c4_max * c4_correct / max(c3_total, 1), 2)
        c4_pass = c4_correct == c3_total
        total_score += c4_score
        eval_criteria["compliance_accuracy"] = {
            "passed": c4_pass, "score": c4_score, "max_score": c4_max,
            **({"reason": f"{c4_correct}/{c3_total} correct."} if not c4_pass else {}),
        }

        # ------ Criterion 5: Benefit calculation accuracy (15 pts) ------
        c5_max = 15
        max_score += c5_max
        c5_correct = 0
        for gt in gt_roster:
            ar = agent_by_id.get(gt["tenant_id"])
            if ar:
                try:
                    agent_val = float(ar.get("new_benefit", -1))
                    if abs(agent_val - gt["new_benefit"]) <= 1.0:
                        c5_correct += 1
                except (ValueError, TypeError):
                    pass
        c5_score = round(c5_max * c5_correct / max(c3_total, 1), 2)
        c5_pass = c5_correct == c3_total
        total_score += c5_score
        eval_criteria["benefit_calculation"] = {
            "passed": c5_pass, "score": c5_score, "max_score": c5_max,
            **({"reason": f"{c5_correct}/{c3_total} correct."} if not c5_pass else {}),
        }

        # ------ Criterion 6: Determination accuracy (25 pts) ------
        c6_max = 25
        max_score += c6_max
        c6_correct = 0
        for gt in gt_roster:
            ar = agent_by_id.get(gt["tenant_id"])
            if ar:
                agent_det = ar.get("determination", "").strip().upper()
                if agent_det == gt["determination"]:
                    c6_correct += 1
        c6_score = round(c6_max * c6_correct / max(c3_total, 1), 2)
        c6_pass = c6_correct == c3_total
        total_score += c6_score
        eval_criteria["determination_accuracy"] = {
            "passed": c6_pass, "score": c6_score, "max_score": c6_max,
            **({"reason": f"{c6_correct}/{c3_total} correct."} if not c6_pass else {}),
        }

        # ------ Criterion 7: Summary response (10 pts) ------
        c7_max = 10
        max_score += c7_max
        # Count determinations in ground truth
        gt_counts = {}
        for r in gt_roster:
            gt_counts[r["determination"]] = gt_counts.get(r["determination"], 0) + 1

        c7_score = 0
        # Check total count
        total_match = re.search(r"(\d+)\s*(?:cases?|participants?|tenants?)\s*(?:reviewed|processed|evaluated)", action, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r"(?:total|reviewed|processed)[^\d]*(\d+)", action, re.IGNORECASE)
        if total_match and int(total_match.group(1)) == len(gt_roster):
            c7_score += 2

        # Check each determination count
        det_points = 8.0 / max(len(gt_counts), 1)
        for det_name, expected_count in gt_counts.items():
            pattern = rf"(?:TERMINATE|terminate)[^\d]*(\d+)" if det_name == "TERMINATE" else \
                      rf"(?:{det_name}|{det_name.lower()}|{det_name.replace('_', ' ')})[^\d]*(\d+)"
            match = re.search(pattern, action, re.IGNORECASE)
            if not match:
                # Try reverse: number then name
                pattern2 = rf"(\d+)\s*(?:.*?{det_name}|.*?{det_name.lower()})"
                match = re.search(pattern2, action, re.IGNORECASE)
            if match:
                try:
                    if int(match.group(1)) == expected_count:
                        c7_score += det_points
                except (ValueError, IndexError):
                    pass

        c7_score = round(min(c7_score, c7_max), 2)
        c7_pass = c7_score >= c7_max * 0.9
        total_score += c7_score
        eval_criteria["summary_response"] = {
            "passed": c7_pass, "score": c7_score, "max_score": c7_max,
            **({"reason": "Summary counts incomplete or incorrect."} if not c7_pass else {}),
        }

        total_score = round(total_score, 2)
        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ------------------------------------------------------------------
    # Verification
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
        tool_call_count = 0

        # ---- 1. Read workspace files ----
        ws = self.workspace

        # Policy
        with open(os.path.join(ws, "policy", "eligibility_rules.yaml")) as f:
            policy = yaml.safe_load(f)

        # Utility allowance schedule
        ua_map = {}
        with open(os.path.join(ws, "policy", "utility_allowance_schedule.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ua_map[(row["region_code"], int(row["bedroom_count"]))] = float(row["monthly_allowance"])

        # Current benefits
        benefits = {}
        with open(os.path.join(ws, "current_benefits.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                benefits[row["tenant_id"]] = float(row["current_monthly_benefit"])

        # Household profiles
        profiles = {}
        for fpath in sorted(globmod.glob(os.path.join(ws, "profiles", "*.json"))):
            with open(fpath) as f:
                data = json.load(f)
                profiles.update(data)

        # Compliance rates
        compliance = {}
        for fpath in sorted(globmod.glob(os.path.join(ws, "compliance", "*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    compliance[row["tenant_id"]] = float(row["utility_compliance_rate"])

        # AMI data
        ami_map = {}
        for fpath in sorted(globmod.glob(os.path.join(ws, "ami_data", "*.yaml"))):
            with open(fpath) as f:
                data = yaml.safe_load(f)
                for rec in data.get("ami_records", []):
                    ami_map[(rec["region_code"], rec["household_size"])] = rec["area_median_income"]

        # Inspection critical deficiency detection
        critical_props = set()
        for fpath in sorted(globmod.glob(os.path.join(ws, "inspections", "*.md"))):
            with open(fpath) as f:
                content = f.read()
            sections = re.split(r"^## Property ", content, flags=re.MULTILINE)
            for section in sections:
                if not section.strip():
                    continue
                prop_match = re.match(r"(P\d+)", section)
                if not prop_match:
                    continue
                prop_id = prop_match.group(1)
                if re.search(r"\[CRITICAL\]", section):
                    critical_props.add(prop_id)

        # ---- 2. List all tenants via tool ----
        all_tenants = []
        page = 1
        while True:
            result = self.tools["list_tenants"](page=page)
            tool_call_count += 1
            if not result["tenants"]:
                break
            all_tenants.extend(result["tenants"])
            if page >= result["total_pages"]:
                break
            page += 1

        active_tenants = [t for t in all_tenants if t["active"]]

        # ---- 3. Process each active tenant ----
        roster = []
        fmr_cache = {}
        inspection_cache = {}

        for t_basic in active_tenants:
            tid = t_basic["tenant_id"]

            # Get full tenant details
            t_detail = self.tools["get_tenant"](tenant_id=tid)
            tool_call_count += 1

            region = t_detail["region_code"]
            bedrooms = t_detail["bedroom_count"]
            prop_id = t_detail["property_id"]

            # Get income certifications
            cert_result = self.tools["get_income_certifications"](tenant_id=tid)
            tool_call_count += 1
            latest_cert = cert_result["certifications"][0]
            annual_income = latest_cert["annual_income"]

            # Get property inspection (cached by property_id)
            if prop_id not in inspection_cache:
                inspection_cache[prop_id] = self.tools["get_property_inspection"](property_id=prop_id)
                tool_call_count += 1
            insp = inspection_cache[prop_id]
            insp_score = insp.get("overall_score", 100)

            # Get FMR (cached)
            fmr_key = (region, bedrooms)
            if fmr_key not in fmr_cache:
                fmr_cache[fmr_key] = self.tools["lookup_fmr"](region_code=region, bedroom_count=bedrooms)
                tool_call_count += 1
            fmr = fmr_cache[fmr_key]["monthly_fmr"]

            # Current household size from workspace
            profile = profiles.get(tid, {})
            current_hh_size = profile.get("current_household_size", latest_cert["household_size"])

            # Income limit
            ami = ami_map.get((region, current_hh_size), 0)
            income_limit = round(ami * policy["income_threshold_pct"], 2)

            # Utility compliance from workspace
            comp_rate = compliance.get(tid, 1.0)

            # Current benefit from workspace
            current_benefit = benefits.get(tid, 0.0)

            # Utility allowance
            ua = ua_map.get((region, bedrooms), 0)

            # New benefit
            contribution = max(annual_income * policy["rent_burden_ratio"] / 12.0,
                               policy["minimum_rent"])
            new_benefit = round(max(fmr + ua - contribution, 0.0), 2)

            # Has critical deficiency
            has_critical = prop_id in critical_props

            # Determination
            determination = "MAINTAIN"
            if annual_income > income_limit:
                determination = "TERMINATE"
            elif comp_rate < policy["min_utility_compliance"]:
                determination = "TERMINATE"
            elif insp_score < policy["min_inspection_score"] or has_critical:
                determination = "SUSPEND"
            elif new_benefit <= 0:
                determination = "TERMINATE"
            elif current_benefit > 0:
                change_ratio = (new_benefit - current_benefit) / current_benefit
                if change_ratio > policy["adjustment_threshold"]:
                    determination = "ADJUST_UP"
                elif change_ratio < -policy["adjustment_threshold"]:
                    determination = "ADJUST_DOWN"

            tenant_name = f"{t_basic['first_name']} {t_basic['last_name']}"
            roster.append({
                "tenant_id": tid,
                "tenant_name": tenant_name,
                "region_code": region,
                "program_type": t_detail["program_type"],
                "household_size": current_hh_size,
                "annual_income": round(annual_income, 2),
                "income_limit": income_limit,
                "utility_compliance": comp_rate,
                "inspection_score": insp_score,
                "current_benefit": current_benefit,
                "new_benefit": new_benefit,
                "determination": determination,
            })

        # ---- 4. Sort roster ----
        det_order = {"TERMINATE": 0, "SUSPEND": 1, "ADJUST_DOWN": 2, "ADJUST_UP": 3, "MAINTAIN": 4}
        roster.sort(key=lambda r: (det_order.get(r["determination"], 9), r["tenant_id"]))

        # ---- 5. Write case_roster.csv ----
        roster_path = os.path.join(ws, "case_roster.csv")
        fieldnames = [
            "tenant_id", "tenant_name", "region_code", "program_type",
            "household_size", "annual_income", "income_limit",
            "utility_compliance", "inspection_score", "current_benefit",
            "new_benefit", "determination",
        ]
        with open(roster_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in roster:
                writer.writerow({
                    "tenant_id": r["tenant_id"],
                    "tenant_name": r["tenant_name"],
                    "region_code": r["region_code"],
                    "program_type": r["program_type"],
                    "household_size": r["household_size"],
                    "annual_income": f"{r['annual_income']:.2f}",
                    "income_limit": f"{r['income_limit']:.2f}",
                    "utility_compliance": f"{r['utility_compliance']:.2f}",
                    "inspection_score": r["inspection_score"],
                    "current_benefit": f"{r['current_benefit']:.2f}",
                    "new_benefit": f"{r['new_benefit']:.2f}",
                    "determination": r["determination"],
                })

        # ---- 6. Construct summary action ----
        det_counts = {}
        for r in roster:
            det_counts[r["determination"]] = det_counts.get(r["determination"], 0) + 1

        summary_lines = [
            f"Total cases reviewed: {len(roster)} tenants.",
        ]
        for det_name in ["TERMINATE", "SUSPEND", "ADJUST_DOWN", "ADJUST_UP", "MAINTAIN"]:
            cnt = det_counts.get(det_name, 0)
            summary_lines.append(f"{det_name}: {cnt}")

        action = "\n".join(summary_lines)

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need >= 15."

        return self.step(action)
