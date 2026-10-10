import os
import re
import csv
import json
import sqlite3
from typing import Tuple, Dict, List, Any

import yaml


# ──────────────────────────────────────────────────────────────
#  Tool decorator (keep unchanged)
# ──────────────────────────────────────────────────────────────
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

    # ── keep this implementation unchanged ──
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

    # ──────────────────────────────────────────────────────────
    #  Tool methods
    # ──────────────────────────────────────────────────────────

    @tool(
        description=(
            "Look up basic applicant information from the bank's records. "
            "Accepts a comma-separated string of application IDs (max 10 per call). "
            "Returns a list of records with fields: app_id, applicant_name, ssn_last4, "
            "email, phone, verified_annual_income, employment_status, employer_name, "
            "state, zip_code, requested_credit_limit, applied_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "app_ids": {
                    "type": "string",
                    "description": "Comma-separated application IDs, e.g. 'APP-0001,APP-0002'. Max 10.",
                },
            },
            "required": ["app_ids"],
        },
    )
    def batch_applicant_lookup(self, app_ids: str) -> dict:
        ids = [x.strip() for x in app_ids.split(",") if x.strip()]
        if len(ids) > 10:
            return {"error": "Maximum 10 IDs per call."}
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in ids)
        cur.execute(
            f"SELECT app_id, applicant_name, ssn_last4, email, phone, "
            f"verified_annual_income, employment_status, employer_name, "
            f"state, zip_code, requested_credit_limit, applied_date "
            f"FROM applications WHERE app_id IN ({placeholders})",
            ids,
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"results": rows}

    @tool(
        description=(
            "Retrieve credit bureau data for the given applications. "
            "Accepts a comma-separated string of application IDs (max 10 per call). "
            "Returns credit_score, open_trade_lines, delinquent_trade_lines, "
            "total_delinquency_amount, credit_history_years, total_outstanding_debt, "
            "bankruptcy_flag, hard_inquiries_6mo for each."
        ),
        parameters={
            "type": "object",
            "properties": {
                "app_ids": {
                    "type": "string",
                    "description": "Comma-separated application IDs. Max 10.",
                },
            },
            "required": ["app_ids"],
        },
    )
    def batch_credit_lookup(self, app_ids: str) -> dict:
        ids = [x.strip() for x in app_ids.split(",") if x.strip()]
        if len(ids) > 10:
            return {"error": "Maximum 10 IDs per call."}
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        ph = ",".join("?" for _ in ids)
        cur.execute(f"SELECT * FROM credit_bureau WHERE app_id IN ({ph})", ids)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"results": rows}

    @tool(
        description=(
            "Retrieve device fingerprint data for the given applications. "
            "Accepts a comma-separated string of application IDs (max 10 per call). "
            "Returns device_hash, ip_address, ip_country, vpn_detected, proxy_detected, "
            "browser, os_name, session_duration_sec for each."
        ),
        parameters={
            "type": "object",
            "properties": {
                "app_ids": {
                    "type": "string",
                    "description": "Comma-separated application IDs. Max 10.",
                },
            },
            "required": ["app_ids"],
        },
    )
    def batch_device_lookup(self, app_ids: str) -> dict:
        ids = [x.strip() for x in app_ids.split(",") if x.strip()]
        if len(ids) > 10:
            return {"error": "Maximum 10 IDs per call."}
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        ph = ",".join("?" for _ in ids)
        cur.execute(f"SELECT * FROM device_fingerprints WHERE app_id IN ({ph})", ids)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"results": rows}

    @tool(
        description=(
            "Screen a batch of applications against the known-fraudster database. "
            "For each application the system checks the applicant's SSN last-4, "
            "email domain, and phone prefix against all known-fraudster records. "
            "Accepts a comma-separated string of application IDs (max 10 per call). "
            "Returns a list of matches (may be empty) with fraudster_id, match_field, "
            "match_value, fraud_type, severity, and the matched app_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "app_ids": {
                    "type": "string",
                    "description": "Comma-separated application IDs. Max 10.",
                },
            },
            "required": ["app_ids"],
        },
    )
    def batch_fraud_screen(self, app_ids: str) -> dict:
        ids = [x.strip() for x in app_ids.split(",") if x.strip()]
        if len(ids) > 10:
            return {"error": "Maximum 10 IDs per call."}
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Get applicant data for the requested IDs
        ph = ",".join("?" for _ in ids)
        cur.execute(
            f"SELECT app_id, ssn_last4, email, phone FROM applications WHERE app_id IN ({ph})",
            ids,
        )
        app_rows = cur.fetchall()

        # Get all fraudsters
        cur.execute("SELECT * FROM known_fraudsters")
        fraudsters = [dict(r) for r in cur.fetchall()]
        conn.close()

        matches = []
        for ar in app_rows:
            app_id = ar["app_id"]
            ssn4 = ar["ssn_last4"]
            email_domain = ar["email"].split("@")[1] if "@" in ar["email"] else ""
            phone_prefix = ar["phone"][:3]
            for f in fraudsters:
                hit = False
                if f["match_field"] == "ssn_last4" and f["match_value"] == ssn4:
                    hit = True
                elif f["match_field"] == "email_domain" and f["match_value"] == email_domain:
                    hit = True
                elif f["match_field"] == "phone_prefix" and f["match_value"] == phone_prefix:
                    hit = True
                if hit:
                    matches.append({
                        "app_id": app_id,
                        "fraudster_id": f["fraudster_id"],
                        "match_field": f["match_field"],
                        "match_value": f["match_value"],
                        "fraud_type": f["fraud_type"],
                        "severity": f["severity"],
                    })
        return {"matches": matches}

    @tool(
        description=(
            "Check the application velocity for a single application. "
            "Returns the number of OTHER applications that share the same "
            "device_hash or ip_address as the given application."
        ),
        parameters={
            "type": "object",
            "properties": {
                "app_id": {
                    "type": "string",
                    "description": "The application ID to check, e.g. 'APP-0001'.",
                },
            },
            "required": ["app_id"],
        },
    )
    def check_application_velocity(self, app_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT device_hash, ip_address FROM device_fingerprints WHERE app_id = ?",
            (app_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"error": f"No device record for {app_id}"}
        dh = row["device_hash"]
        ip = row["ip_address"]
        cur.execute(
            "SELECT COUNT(*) as cnt FROM device_fingerprints "
            "WHERE (device_hash = ? OR ip_address = ?) AND app_id != ?",
            (dh, ip, app_id),
        )
        cnt = cur.fetchone()["cnt"]
        conn.close()
        return {"app_id": app_id, "shared_device_or_ip_count": cnt}

    # ──────────────────────────────────────────────────────────
    #  Ground-truth computation (used by step and verify)
    # ──────────────────────────────────────────────────────────

    def _load_workspace_data(self):
        """Read workspace config and batch files.  Returns structured dicts."""
        ws = self.workspace

        with open(os.path.join(ws, "scoring_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(ws, "fraud_rules.json")) as f:
            fraud_rules = json.load(f)

        with open(os.path.join(ws, "regional_risk_map.json")) as f:
            region_map = json.load(f)

        # Read all batch CSVs
        batch_data = {}  # app_id -> row dict
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("application_batch_") and fname.endswith(".csv"):
                with open(os.path.join(ws, fname), newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        batch_data[row["app_id"]] = row

        return policy, fraud_rules, region_map, batch_data

    def _compute_ground_truth(self):
        """Compute the expected rejection roster using direct DB access."""
        policy, fraud_rules, region_map, batch_data = self._load_workspace_data()
        rf = policy["risk_factors"]
        threshold = policy["risk_threshold"]
        sus_prefixes = fraud_rules["suspicious_referral_prefixes"]
        sus_domains = fraud_rules["suspicious_email_domains"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        app_ids = sorted(batch_data.keys())
        results = []

        for aid in app_ids:
            bd = batch_data[aid]
            cur = conn.cursor()

            # Applicant record
            cur.execute("SELECT * FROM applications WHERE app_id = ?", (aid,))
            app = dict(cur.fetchone())

            # Credit
            cur.execute("SELECT * FROM credit_bureau WHERE app_id = ?", (aid,))
            credit = dict(cur.fetchone())

            # Device
            cur.execute("SELECT * FROM device_fingerprints WHERE app_id = ?", (aid,))
            device = dict(cur.fetchone())

            # Fraud matches
            ssn4 = app["ssn_last4"]
            email_domain = app["email"].split("@")[1] if "@" in app["email"] else ""
            phone_prefix = app["phone"][:3]
            cur.execute("SELECT * FROM known_fraudsters")
            all_fraudsters = [dict(r) for r in cur.fetchall()]
            fraud_matches = []
            for fr in all_fraudsters:
                if (fr["match_field"] == "ssn_last4" and fr["match_value"] == ssn4) or \
                   (fr["match_field"] == "email_domain" and fr["match_value"] == email_domain) or \
                   (fr["match_field"] == "phone_prefix" and fr["match_value"] == phone_prefix):
                    fraud_matches.append(fr)

            # Velocity
            cur.execute(
                "SELECT COUNT(*) as cnt FROM device_fingerprints "
                "WHERE (device_hash = ? OR ip_address = ?) AND app_id != ?",
                (device["device_hash"], device["ip_address"], aid),
            )
            velocity = cur.fetchone()["cnt"]

            # ── Compute risk score ──
            reasons = []

            # R01
            if credit["credit_score"] < rf["R01"]["credit_score_threshold"]:
                reasons.append(("R01", rf["R01"]["points"]))

            # R02
            self_rep = int(bd["self_reported_annual_income"])
            verified = app["verified_annual_income"]
            if verified > 0 and (self_rep - verified) / verified > rf["R02"]["discrepancy_threshold"]:
                reasons.append(("R02", rf["R02"]["points"]))

            # R03
            if (device["vpn_detected"] or device["proxy_detected"]) and \
               app["requested_credit_limit"] >= rf["R03"]["limit_threshold"]:
                reasons.append(("R03", rf["R03"]["points"]))

            # R04 – take highest severity among matches
            if fraud_matches:
                sev_order = {"high": 3, "medium": 2, "low": 1}
                best = max(fraud_matches, key=lambda m: sev_order.get(m["severity"], 0))
                pts = rf["R04"]["points_by_severity"].get(best["severity"], 0)
                reasons.append(("R04", pts))

            # R05
            if velocity >= rf["R05"]["velocity_threshold"]:
                reasons.append(("R05", rf["R05"]["points"]))

            # R06
            if bd["document_status"] == "failed":
                reasons.append(("R06", rf["R06"]["points"]))

            # R07
            if credit["bankruptcy_flag"] and \
               app["requested_credit_limit"] >= rf["R07"]["limit_threshold"]:
                reasons.append(("R07", rf["R07"]["points"]))

            # R08
            state_risk = region_map.get(app["state"], "low")
            if state_risk == "high" and credit["credit_score"] < rf["R08"]["credit_score_threshold"]:
                reasons.append(("R08", rf["R08"]["points"]))

            # R09
            ref_code = bd.get("referral_code", "")
            if ref_code:
                for pfx in sus_prefixes:
                    if ref_code.startswith(pfx):
                        reasons.append(("R09", rf["R09"]["points"]))
                        break

            # R10
            if email_domain in sus_domains:
                reasons.append(("R10", rf["R10"]["points"]))

            risk_score = sum(p for _, p in reasons)
            if risk_score >= threshold:
                reason_codes = sorted(set(r for r, _ in reasons))
                results.append({
                    "app_id": aid,
                    "applicant_name": app["applicant_name"],
                    "risk_score": risk_score,
                    "reason_codes": ";".join(reason_codes),
                    "decision": "REJECT",
                })

        conn.close()

        # Sort: risk_score desc, app_id asc
        results.sort(key=lambda r: (-r["risk_score"], r["app_id"]))
        return results, len(app_ids)

    # ──────────────────────────────────────────────────────────
    #  Step
    # ──────────────────────────────────────────────────────────

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
        expected, total_reviewed = self._compute_ground_truth()
        criteria = {}

        # ── C1: roster file exists with correct columns (10 pts) ──
        roster_path = os.path.join(self.workspace, "rejection_roster.csv")
        c1_pass = False
        agent_rows = []
        expected_cols = {"app_id", "applicant_name", "risk_score", "reason_codes", "decision"}
        if os.path.exists(roster_path):
            with open(roster_path, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and expected_cols.issubset(set(reader.fieldnames)):
                    agent_rows = list(reader)
                    c1_pass = True
        criteria["roster_format"] = {
            "passed": c1_pass,
            "score": 10 if c1_pass else 0,
            "max_score": 10,
            "reason": "" if c1_pass else "rejection_roster.csv missing or has wrong columns",
        }

        if not c1_pass:
            # Can't evaluate further
            for name, mx in [
                ("correct_app_ids", 25), ("correct_risk_scores", 15),
                ("correct_reason_codes", 20), ("correct_sorting", 10),
                ("response_rejection_count", 10), ("response_rejection_rate", 10),
            ]:
                criteria[name] = {"passed": False, "score": 0, "max_score": mx,
                                  "reason": "Roster file not readable"}
            total = sum(c["score"] for c in criteria.values())
            mx = sum(c["max_score"] for c in criteria.values())
            return total / mx, {"eval_criteria": criteria, "total_score": total, "max_score": mx}

        # ── C2: correct rejected app_ids (25 pts) ──
        expected_ids = {r["app_id"] for r in expected}
        agent_ids = {r["app_id"] for r in agent_rows}
        if expected_ids or agent_ids:
            jaccard = len(expected_ids & agent_ids) / len(expected_ids | agent_ids)
        else:
            jaccard = 1.0
        c2_score = round(25 * jaccard)
        criteria["correct_app_ids"] = {
            "passed": jaccard == 1.0,
            "score": c2_score,
            "max_score": 25,
            "reason": "" if jaccard == 1.0 else f"Jaccard={jaccard:.2f}, missing={expected_ids - agent_ids}, extra={agent_ids - expected_ids}",
        }

        # Build lookup for agent rows
        agent_map = {r["app_id"]: r for r in agent_rows}
        expected_map = {r["app_id"]: r for r in expected}
        common_ids = expected_ids & agent_ids

        # ── C3: correct risk_scores (15 pts) ──
        score_matches = 0
        for aid in common_ids:
            try:
                if int(agent_map[aid]["risk_score"]) == expected_map[aid]["risk_score"]:
                    score_matches += 1
            except (ValueError, KeyError):
                pass
        c3_ratio = score_matches / len(expected) if expected else 1.0
        c3_score = round(15 * c3_ratio)
        criteria["correct_risk_scores"] = {
            "passed": c3_ratio == 1.0,
            "score": c3_score,
            "max_score": 15,
            "reason": "" if c3_ratio == 1.0 else f"{score_matches}/{len(expected)} scores correct",
        }

        # ── C4: correct reason_codes (20 pts) ──
        code_matches = 0
        for aid in common_ids:
            agent_codes = agent_map[aid].get("reason_codes", "")
            expected_codes = expected_map[aid]["reason_codes"]
            if agent_codes == expected_codes:
                code_matches += 1
        c4_ratio = code_matches / len(expected) if expected else 1.0
        c4_score = round(20 * c4_ratio)
        criteria["correct_reason_codes"] = {
            "passed": c4_ratio == 1.0,
            "score": c4_score,
            "max_score": 20,
            "reason": "" if c4_ratio == 1.0 else f"{code_matches}/{len(expected)} reason codes correct",
        }

        # ── C5: correct sorting (10 pts) ──
        agent_order = [r["app_id"] for r in agent_rows]
        expected_order = [r["app_id"] for r in expected]
        c5_pass = agent_order == expected_order
        criteria["correct_sorting"] = {
            "passed": c5_pass,
            "score": 10 if c5_pass else 0,
            "max_score": 10,
            "reason": "" if c5_pass else "Rows not sorted by risk_score desc then app_id asc",
        }

        # ── C6: response contains correct rejection count (10 pts) ──
        expected_count = len(expected)
        c6_pass = str(expected_count) in action
        criteria["response_rejection_count"] = {
            "passed": c6_pass,
            "score": 10 if c6_pass else 0,
            "max_score": 10,
            "reason": "" if c6_pass else f"Expected '{expected_count}' in response",
        }

        # ── C7: response contains correct rejection rate (10 pts) ──
        if total_reviewed > 0:
            rate = round(100 * expected_count / total_reviewed, 1)
        else:
            rate = 0.0
        # Accept both "32.0%" and "32%" forms
        rate_str1 = f"{rate}%"
        rate_str2 = f"{rate:.1f}%"
        rate_str3 = f"{int(rate)}%" if rate == int(rate) else ""
        c7_pass = rate_str1 in action or rate_str2 in action or (rate_str3 and rate_str3 in action)
        criteria["response_rejection_rate"] = {
            "passed": c7_pass,
            "score": 10 if c7_pass else 0,
            "max_score": 10,
            "reason": "" if c7_pass else f"Expected rejection rate '{rate_str1}' in response",
        }

        total = sum(c["score"] for c in criteria.values())
        mx = sum(c["max_score"] for c in criteria.values())
        return total / mx, {
            "eval_criteria": criteria,
            "total_score": total,
            "max_score": mx,
        }

    # ──────────────────────────────────────────────────────────
    #  Verify
    # ──────────────────────────────────────────────────────────

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
        ws = self.workspace

        # 1. Read config files
        with open(os.path.join(ws, "scoring_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(ws, "fraud_rules.json")) as f:
            fraud_rules = json.load(f)
        with open(os.path.join(ws, "regional_risk_map.json")) as f:
            region_map = json.load(f)

        rf = policy["risk_factors"]
        threshold = policy["risk_threshold"]
        sus_prefixes = fraud_rules["suspicious_referral_prefixes"]
        sus_domains = fraud_rules["suspicious_email_domains"]

        # 2. Read all batch CSVs
        batch_data = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("application_batch_") and fname.endswith(".csv"):
                with open(os.path.join(ws, fname), newline="") as f:
                    for row in csv.DictReader(f):
                        batch_data[row["app_id"]] = row

        all_ids = sorted(batch_data.keys())

        # 3. Fetch data via tools (batches of 10)
        applicant_data = {}
        credit_data = {}
        device_data = {}
        fraud_matches_by_app = {}  # app_id -> list of matches

        for i in range(0, len(all_ids), 10):
            chunk = all_ids[i:i+10]
            ids_str = ",".join(chunk)

            res = self.tools["batch_applicant_lookup"](app_ids=ids_str)
            for r in res["results"]:
                applicant_data[r["app_id"]] = r

            res = self.tools["batch_credit_lookup"](app_ids=ids_str)
            for r in res["results"]:
                credit_data[r["app_id"]] = r

            res = self.tools["batch_device_lookup"](app_ids=ids_str)
            for r in res["results"]:
                device_data[r["app_id"]] = r

            res = self.tools["batch_fraud_screen"](app_ids=ids_str)
            for m in res["matches"]:
                fraud_matches_by_app.setdefault(m["app_id"], []).append(m)

        # 4. Check velocity for apps with potential shared devices
        # First identify device hashes that appear more than once
        hash_to_apps = {}
        ip_to_apps = {}
        for aid, dd in device_data.items():
            hash_to_apps.setdefault(dd["device_hash"], []).append(aid)
            ip_to_apps.setdefault(dd["ip_address"], []).append(aid)

        velocity_check_ids = set()
        for h, aids_list in hash_to_apps.items():
            if len(aids_list) > 1:
                velocity_check_ids.update(aids_list)
        for ip, aids_list in ip_to_apps.items():
            if len(aids_list) > 1:
                velocity_check_ids.update(aids_list)

        velocity_counts = {}
        for aid in sorted(velocity_check_ids):
            res = self.tools["check_application_velocity"](app_id=aid)
            velocity_counts[aid] = res.get("shared_device_or_ip_count", 0)

        # 5. Score each application
        results = []
        for aid in all_ids:
            bd = batch_data[aid]
            app = applicant_data.get(aid, {})
            credit = credit_data.get(aid, {})
            device = device_data.get(aid, {})
            fmatches = fraud_matches_by_app.get(aid, [])
            vel = velocity_counts.get(aid, 0)

            reasons = []

            # R01
            if credit.get("credit_score", 999) < rf["R01"]["credit_score_threshold"]:
                reasons.append(("R01", rf["R01"]["points"]))

            # R02
            self_rep = int(bd["self_reported_annual_income"])
            verified = app.get("verified_annual_income", 0)
            if verified > 0 and (self_rep - verified) / verified > rf["R02"]["discrepancy_threshold"]:
                reasons.append(("R02", rf["R02"]["points"]))

            # R03
            if (device.get("vpn_detected") or device.get("proxy_detected")) and \
               app.get("requested_credit_limit", 0) >= rf["R03"]["limit_threshold"]:
                reasons.append(("R03", rf["R03"]["points"]))

            # R04
            if fmatches:
                sev_order = {"high": 3, "medium": 2, "low": 1}
                best = max(fmatches, key=lambda m: sev_order.get(m["severity"], 0))
                pts = rf["R04"]["points_by_severity"].get(best["severity"], 0)
                reasons.append(("R04", pts))

            # R05
            if vel >= rf["R05"]["velocity_threshold"]:
                reasons.append(("R05", rf["R05"]["points"]))

            # R06
            if bd.get("document_status") == "failed":
                reasons.append(("R06", rf["R06"]["points"]))

            # R07
            if credit.get("bankruptcy_flag") and \
               app.get("requested_credit_limit", 0) >= rf["R07"]["limit_threshold"]:
                reasons.append(("R07", rf["R07"]["points"]))

            # R08
            state_risk = region_map.get(app.get("state", ""), "low")
            if state_risk == "high" and credit.get("credit_score", 999) < rf["R08"]["credit_score_threshold"]:
                reasons.append(("R08", rf["R08"]["points"]))

            # R09
            ref_code = bd.get("referral_code", "")
            if ref_code:
                for pfx in sus_prefixes:
                    if ref_code.startswith(pfx):
                        reasons.append(("R09", rf["R09"]["points"]))
                        break

            # R10
            email_domain = app.get("email", "").split("@")[1] if "@" in app.get("email", "") else ""
            if email_domain in sus_domains:
                reasons.append(("R10", rf["R10"]["points"]))

            risk_score = sum(p for _, p in reasons)
            if risk_score >= threshold:
                reason_codes = sorted(set(r for r, _ in reasons))
                results.append({
                    "app_id": aid,
                    "applicant_name": app.get("applicant_name", ""),
                    "risk_score": risk_score,
                    "reason_codes": ";".join(reason_codes),
                    "decision": "REJECT",
                })

        # Sort: risk_score desc, app_id asc
        results.sort(key=lambda r: (-r["risk_score"], r["app_id"]))

        # 6. Write rejection_roster.csv
        roster_path = os.path.join(ws, "rejection_roster.csv")
        with open(roster_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["app_id", "applicant_name", "risk_score", "reason_codes", "decision"])
            writer.writeheader()
            writer.writerows(results)

        # 7. Build response text
        total_reviewed = len(all_ids)
        total_rejected = len(results)
        rate = round(100 * total_rejected / total_reviewed, 1) if total_reviewed else 0.0

        # Compute top 3 reason codes
        code_counter = {}
        for r in results:
            for c in r["reason_codes"].split(";"):
                code_counter[c] = code_counter.get(c, 0) + 1
        top_codes = sorted(code_counter.items(), key=lambda x: (-x[1], x[0]))[:3]

        action_lines = [
            f"Fraud screening complete.",
            f"Total applications reviewed: {total_reviewed}",
            f"Total applications rejected: {total_rejected}",
            f"Rejection rate: {rate}%",
            "Top reason codes:",
        ]
        for code, cnt in top_codes:
            action_lines.append(f"  {code}: {cnt} occurrences")

        action = "\n".join(action_lines)
        return self.step(action)
