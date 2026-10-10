import sqlite3
import json
import csv
import os
import math
from datetime import datetime
from typing import Tuple, Dict, List, Any

import yaml


# --- Decorator ---
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
        description="List all donors with pagination. Returns donor id, first name, last name, and segment for each donor on the requested page.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of donors per page (max 50). Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def list_donors(self, page: int = 1, page_size: int = 20) -> dict:
        page_size = min(page_size, 50)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM donors")
        total = c.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        c.execute(
            "SELECT id, first_name, last_name, segment FROM donors ORDER BY id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [
            {"donor_id": r["id"], "first_name": r["first_name"],
             "last_name": r["last_name"], "segment": r["segment"]}
            for r in c.fetchall()
        ]
        conn.close()
        return {
            "donors": rows,
            "page": page,
            "total_pages": total_pages,
            "total_donors": total,
            "has_more": page < total_pages,
        }

    @tool(
        description="Get the full profile for a specific donor by their ID, including contact information and demographics.",
        parameters={
            "type": "object",
            "properties": {
                "donor_id": {
                    "type": "integer",
                    "description": "The unique donor ID.",
                },
            },
            "required": ["donor_id"],
        },
    )
    def get_donor_profile(self, donor_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM donors WHERE id = ?", (donor_id,))
        r = c.fetchone()
        conn.close()
        if r is None:
            return {"error": f"Donor {donor_id} not found."}
        return {
            "donor_id": r["id"],
            "first_name": r["first_name"],
            "last_name": r["last_name"],
            "email": r["email"],
            "phone": r["phone"],
            "age": r["age"],
            "income_bracket": r["income_bracket"],
            "zip_code": r["zip_code"],
            "segment": r["segment"],
            "registration_date": r["registration_date"],
        }

    @tool(
        description="Get donation summary statistics for a specific donor including total amount, number of donations, average amount, last donation date, and recurring donation info.",
        parameters={
            "type": "object",
            "properties": {
                "donor_id": {
                    "type": "integer",
                    "description": "The unique donor ID.",
                },
            },
            "required": ["donor_id"],
        },
    )
    def get_donation_summary(self, donor_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            """SELECT COUNT(*) as cnt, SUM(amount) as total,
                      AVG(amount) as avg_amt, MAX(donation_date) as last_date
               FROM donations WHERE donor_id = ?""",
            (donor_id,),
        )
        r = c.fetchone()
        c.execute(
            "SELECT is_recurring, frequency FROM donations WHERE donor_id = ? AND is_recurring = 1 LIMIT 1",
            (donor_id,),
        )
        rec = c.fetchone()
        conn.close()
        if r["cnt"] == 0:
            return {
                "donor_id": donor_id,
                "total_amount": 0,
                "num_donations": 0,
                "avg_amount": 0,
                "last_donation_date": None,
                "has_recurring": False,
                "recurring_frequency": None,
            }
        return {
            "donor_id": donor_id,
            "total_amount": round(r["total"], 2),
            "num_donations": r["cnt"],
            "avg_amount": round(r["avg_amt"], 2),
            "last_donation_date": r["last_date"],
            "has_recurring": rec is not None,
            "recurring_frequency": rec["frequency"] if rec else None,
        }

    @tool(
        description="Get email campaign engagement metrics for a specific donor, including number of campaigns received, opened, clicked, and corresponding rates.",
        parameters={
            "type": "object",
            "properties": {
                "donor_id": {
                    "type": "integer",
                    "description": "The unique donor ID.",
                },
            },
            "required": ["donor_id"],
        },
    )
    def get_email_engagement(self, donor_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """SELECT COUNT(*) as sent,
                      COALESCE(SUM(opened), 0) as opens,
                      COALESCE(SUM(clicked), 0) as clicks
               FROM campaign_interactions WHERE donor_id = ?""",
            (donor_id,),
        )
        r = c.fetchone()
        conn.close()
        sent = r[0]
        opens = r[1]
        clicks = r[2]
        return {
            "donor_id": donor_id,
            "campaigns_received": sent,
            "campaigns_opened": opens,
            "campaigns_clicked": clicks,
            "open_rate": round(opens / max(1, sent), 4),
            "click_rate": round(clicks / max(1, sent), 4),
        }

    @tool(
        description="Get event participation record for a specific donor, including number of events they were invited to (had any RSVP record), number attended, and attendance rate.",
        parameters={
            "type": "object",
            "properties": {
                "donor_id": {
                    "type": "integer",
                    "description": "The unique donor ID.",
                },
            },
            "required": ["donor_id"],
        },
    )
    def get_event_participation(self, donor_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """SELECT COUNT(*) as total,
                      COALESCE(SUM(attended), 0) as att
               FROM event_attendance WHERE donor_id = ?""",
            (donor_id,),
        )
        r = c.fetchone()
        conn.close()
        total = r[0]
        att = r[1]
        return {
            "donor_id": donor_id,
            "events_invited": total,
            "events_attended": att,
            "attendance_rate": round(att / max(1, total), 4),
        }

    @tool(
        description="Find donors whose most recent donation is strictly before a given cutoff date. Returns paginated results with donor id, name, and last donation date.",
        parameters={
            "type": "object",
            "properties": {
                "cutoff_date": {
                    "type": "string",
                    "description": "ISO date string (YYYY-MM-DD). Only donors whose last donation is before this date are returned.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 50). Defaults to 50.",
                },
            },
            "required": ["cutoff_date"],
        },
    )
    def find_lapsed_donors(self, cutoff_date: str, page: int = 1, page_size: int = 50) -> dict:
        page_size = min(page_size, 50)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            """SELECT d.id, d.first_name, d.last_name,
                      MAX(don.donation_date) as last_donation_date
               FROM donors d
               JOIN donations don ON d.id = don.donor_id
               GROUP BY d.id
               HAVING last_donation_date < ?
               ORDER BY d.id""",
            (cutoff_date,),
        )
        all_rows = c.fetchall()
        conn.close()
        total = len(all_rows)
        total_pages = max(1, math.ceil(total / page_size))
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = all_rows[start:end]
        donors_out = [
            {
                "donor_id": r["id"],
                "first_name": r["first_name"],
                "last_name": r["last_name"],
                "last_donation_date": r["last_donation_date"],
            }
            for r in page_rows
        ]
        return {
            "donors": donors_out,
            "page": page,
            "total_pages": total_pages,
            "total_lapsed": total,
            "has_more": page < total_pages,
        }

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute the expected re-engagement list from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load configs
        with open(os.path.join(self.workspace, "reengagement_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "segment_tiers.json")) as f:
            segment_tiers = json.load(f)

        ref_str = policy["reference_date"]
        ref_date = datetime.strptime(ref_str, "%Y-%m-%d")
        thresh_months = policy["lapsed_threshold_months"]

        # cutoff date
        total_m = ref_date.year * 12 + ref_date.month - 1 - thresh_months
        cutoff_year = total_m // 12
        cutoff_month = total_m % 12 + 1
        cutoff_date = f"{cutoff_year:04d}-{cutoff_month:02d}-{ref_date.day:02d}"

        # Lapsed donors
        c = conn.cursor()
        c.execute(
            """SELECT d.*, MAX(don.donation_date) as last_donation_date
               FROM donors d
               JOIN donations don ON d.id = don.donor_id
               GROUP BY d.id
               HAVING last_donation_date < ?
               ORDER BY d.id""",
            (cutoff_date,),
        )
        lapsed = [dict(r) for r in c.fetchall()]

        # DNC + preferred contact
        dnc_set = set()
        pref_contact = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("donor_notes_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    notes = json.load(f)
                for did_str, info in notes.items():
                    if info.get("do_not_contact"):
                        dnc_set.add(int(did_str))
                    pref_contact[int(did_str)] = info.get("preferred_contact_method", "email")

        weights = policy["engagement_scoring"]
        benchmark = policy["giving_benchmark"]
        hp_thresh = policy["high_potential_threshold"]

        expected = []
        for ld in lapsed:
            did = ld["id"]
            if did in dnc_set:
                continue

            # months since last donation
            last_dt = datetime.strptime(ld["last_donation_date"], "%Y-%m-%d")
            months_since = (ref_date.year - last_dt.year) * 12 + (ref_date.month - last_dt.month)

            # email engagement
            c.execute(
                "SELECT COUNT(*) as sent, COALESCE(SUM(opened),0) as opens FROM campaign_interactions WHERE donor_id=?",
                (did,),
            )
            er = c.fetchone()
            email_open_rate = er["opens"] / max(1, er["sent"])

            # event participation
            c.execute(
                "SELECT COUNT(*) as total, COALESCE(SUM(attended),0) as att FROM event_attendance WHERE donor_id=?",
                (did,),
            )
            ev = c.fetchone()
            event_att_rate = ev["att"] / max(1, ev["total"])

            # giving score
            c.execute("SELECT SUM(amount) as total FROM donations WHERE donor_id=?", (did,))
            total_giving = c.fetchone()["total"] or 0
            giving_score = min(1.0, total_giving / benchmark)

            engagement = (
                weights["email_open_weight"] * email_open_rate
                + weights["event_attendance_weight"] * event_att_rate
                + weights["giving_history_weight"] * giving_score
            )

            if engagement < hp_thresh:
                continue

            # Ask amount
            c.execute("SELECT AVG(amount) as avg_amt FROM donations WHERE donor_id=?", (did,))
            avg_don = c.fetchone()["avg_amt"] or 0

            seg = ld["segment"]
            tier = segment_tiers.get(seg, {"multiplier": 1.0, "min_ask": 25, "max_ask": 5000})

            recency_factor = 0.7
            for rt in policy["ask_amount"]["recency_tiers"]:
                if months_since <= rt["max_months_since_last"]:
                    recency_factor = rt["factor"]
                    break

            raw_ask = avg_don * tier["multiplier"] * recency_factor
            rounding = policy["ask_amount"]["rounding"]
            rounded_ask = round(raw_ask / rounding) * rounding
            final_ask = int(max(tier["min_ask"], min(tier["max_ask"], rounded_ask)))

            expected.append({
                "donor_id": did,
                "first_name": ld["first_name"],
                "last_name": ld["last_name"],
                "email": ld["email"],
                "phone": ld["phone"],
                "segment": seg,
                "engagement_score": round(engagement, 4),
                "months_since_last_donation": months_since,
                "suggested_ask_amount": final_ask,
                "preferred_contact_method": pref_contact.get(did, "email"),
            })

        expected.sort(key=lambda x: (-x["engagement_score"], x["donor_id"]))
        conn.close()
        return expected, len(lapsed), dnc_set

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
        expected, total_lapsed, dnc_set = self._compute_ground_truth()
        expected_by_id = {e["donor_id"]: e for e in expected}
        expected_ids = set(expected_by_id.keys())

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- 1. Output file format (15 pts) ---
        output_path = os.path.join(self.workspace, "reengagement_list.csv")
        expected_cols = [
            "donor_id", "first_name", "last_name", "email", "phone", "segment",
            "engagement_score", "months_since_last_donation", "suggested_ask_amount",
            "preferred_contact_method",
        ]
        file_ok = False
        agent_rows = []
        if os.path.exists(output_path):
            try:
                with open(output_path, newline="") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames == expected_cols:
                        agent_rows = list(reader)
                        file_ok = True
            except Exception:
                pass

        # Check sort order
        sort_ok = True
        if file_ok and len(agent_rows) > 1:
            for i in range(len(agent_rows) - 1):
                try:
                    s1 = float(agent_rows[i]["engagement_score"])
                    s2 = float(agent_rows[i + 1]["engagement_score"])
                    id1 = int(agent_rows[i]["donor_id"])
                    id2 = int(agent_rows[i + 1]["donor_id"])
                    if s1 < s2 or (s1 == s2 and id1 > id2):
                        sort_ok = False
                        break
                except (ValueError, KeyError):
                    sort_ok = False
                    break

        c1 = 0
        if file_ok:
            c1 += 8
        if file_ok and sort_ok:
            c1 += 7
        reason1 = ""
        if not file_ok:
            reason1 = "File missing, empty, or has wrong columns"
        elif not sort_ok:
            reason1 = "Rows not sorted correctly"
        eval_criteria["output_file_format"] = {
            "passed": c1 == 15,
            "score": c1,
            "max_score": 15,
            "reason": reason1,
        }
        total_score += c1
        max_score += 15

        # --- 2. Donor identification accuracy (20 pts) ---
        agent_ids = set()
        for r in agent_rows:
            try:
                agent_ids.add(int(r["donor_id"]))
            except (ValueError, KeyError):
                pass

        if expected_ids or agent_ids:
            inter = agent_ids & expected_ids
            precision = len(inter) / max(1, len(agent_ids))
            recall = len(inter) / max(1, len(expected_ids))
            f1 = 2 * precision * recall / max(0.001, precision + recall)
            c2 = round(20 * f1)
        else:
            c2 = 20
            f1 = 1.0

        eval_criteria["donor_identification"] = {
            "passed": c2 >= 18,
            "score": c2,
            "max_score": 20,
            "reason": "" if c2 >= 18 else f"F1={f1:.3f}, expected {len(expected_ids)} donors, got {len(agent_ids)}",
        }
        total_score += c2
        max_score += 20

        # --- 3. Do-not-contact exclusion (15 pts) ---
        dnc_in_list = agent_ids & dnc_set
        c3 = 15 if len(dnc_in_list) == 0 else 0
        eval_criteria["dnc_exclusion"] = {
            "passed": c3 == 15,
            "score": c3,
            "max_score": 15,
            "reason": "" if c3 == 15 else f"Found {len(dnc_in_list)} do-not-contact donor(s) in list",
        }
        total_score += c3
        max_score += 15

        # --- 4. Engagement scores (20 pts) ---
        score_matches = 0
        score_total = 0
        for r in agent_rows:
            try:
                did = int(r["donor_id"])
                if did in expected_by_id:
                    exp_s = expected_by_id[did]["engagement_score"]
                    agt_s = round(float(r["engagement_score"]), 4)
                    if abs(agt_s - exp_s) < 0.002:
                        score_matches += 1
                    score_total += 1
            except (ValueError, KeyError):
                pass
        if score_total > 0:
            c4 = round(20 * score_matches / score_total)
        else:
            c4 = 0 if expected else 20
        eval_criteria["engagement_scores"] = {
            "passed": c4 >= 18,
            "score": c4,
            "max_score": 20,
            "reason": "" if c4 >= 18 else f"Matched {score_matches}/{score_total} engagement scores",
        }
        total_score += c4
        max_score += 20

        # --- 5. Suggested ask amounts (20 pts) ---
        ask_matches = 0
        ask_total = 0
        for r in agent_rows:
            try:
                did = int(r["donor_id"])
                if did in expected_by_id:
                    exp_a = expected_by_id[did]["suggested_ask_amount"]
                    agt_a = int(round(float(r["suggested_ask_amount"])))
                    if agt_a == exp_a:
                        ask_matches += 1
                    ask_total += 1
            except (ValueError, KeyError):
                pass
        if ask_total > 0:
            c5 = round(20 * ask_matches / ask_total)
        else:
            c5 = 0 if expected else 20
        eval_criteria["ask_amounts"] = {
            "passed": c5 >= 18,
            "score": c5,
            "max_score": 20,
            "reason": "" if c5 >= 18 else f"Matched {ask_matches}/{ask_total} ask amounts",
        }
        total_score += c5
        max_score += 20

        # --- 6. Response summary (10 pts) ---
        expected_total_ask = sum(e["suggested_ask_amount"] for e in expected)
        c6 = 0
        # Check final-list count
        if str(len(expected)) in action:
            c6 += 3
        # Check total lapsed count
        if str(total_lapsed) in action:
            c6 += 3
        # Check total ask amount with $ and commas
        fmt_ask = f"${expected_total_ask:,.2f}"
        if fmt_ask in action:
            c6 += 4
        eval_criteria["response_summary"] = {
            "passed": c6 == 10,
            "score": c6,
            "max_score": 10,
            "reason": "" if c6 == 10 else f"Expected list={len(expected)}, lapsed={total_lapsed}, ask={fmt_ask}",
        }
        total_score += c6
        max_score += 10

        reward = total_score / max_score
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

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
        # 1. Read config files
        with open(os.path.join(self.workspace, "reengagement_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "segment_tiers.json")) as f:
            segment_tiers = json.load(f)

        ref_str = policy["reference_date"]
        ref_date = datetime.strptime(ref_str, "%Y-%m-%d")
        thresh_months = policy["lapsed_threshold_months"]

        # Compute cutoff
        total_m = ref_date.year * 12 + ref_date.month - 1 - thresh_months
        cutoff_year = total_m // 12
        cutoff_month = total_m % 12 + 1
        cutoff_date = f"{cutoff_year:04d}-{cutoff_month:02d}-{ref_date.day:02d}"

        # 2. Find lapsed donors via tool (paginated)
        lapsed_donors = []
        page = 1
        while True:
            result = self.tools["find_lapsed_donors"](cutoff_date=cutoff_date, page=page, page_size=50)
            lapsed_donors.extend(result["donors"])
            if not result["has_more"]:
                break
            page += 1
        total_lapsed = len(lapsed_donors)

        # 3. Read donor notes for DNC + preferred contact
        dnc_set = set()
        pref_contact = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("donor_notes_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    notes = json.load(f)
                for did_str, info in notes.items():
                    if info.get("do_not_contact"):
                        dnc_set.add(int(did_str))
                    pref_contact[int(did_str)] = info.get("preferred_contact_method", "email")

        # 4. For each lapsed donor (not DNC), compute engagement score
        weights = policy["engagement_scoring"]
        benchmark = policy["giving_benchmark"]
        hp_thresh = policy["high_potential_threshold"]

        high_potential = []
        tool_call_count = 0

        for ld in lapsed_donors:
            did = ld["donor_id"]
            if did in dnc_set:
                continue

            # months since last donation
            last_dt = datetime.strptime(ld["last_donation_date"], "%Y-%m-%d")
            months_since = (ref_date.year - last_dt.year) * 12 + (ref_date.month - last_dt.month)

            don_summary = self.tools["get_donation_summary"](donor_id=did)
            tool_call_count += 1
            email_eng = self.tools["get_email_engagement"](donor_id=did)
            tool_call_count += 1
            event_part = self.tools["get_event_participation"](donor_id=did)
            tool_call_count += 1

            email_open_rate = email_eng.get("open_rate", 0)
            event_att_rate = event_part.get("attendance_rate", 0)
            total_giving = don_summary.get("total_amount", 0)
            giving_score = min(1.0, total_giving / benchmark)

            engagement = (
                weights["email_open_weight"] * email_open_rate
                + weights["event_attendance_weight"] * event_att_rate
                + weights["giving_history_weight"] * giving_score
            )

            if engagement < hp_thresh:
                continue

            # Get full profile for contact info
            profile = self.tools["get_donor_profile"](donor_id=did)
            tool_call_count += 1

            # Ask amount calculation
            avg_don = don_summary.get("avg_amount", 0)
            seg = profile["segment"]
            tier = segment_tiers.get(seg, {"multiplier": 1.0, "min_ask": 25, "max_ask": 5000})

            recency_factor = 0.7
            for rt in policy["ask_amount"]["recency_tiers"]:
                if months_since <= rt["max_months_since_last"]:
                    recency_factor = rt["factor"]
                    break

            raw_ask = avg_don * tier["multiplier"] * recency_factor
            rounding = policy["ask_amount"]["rounding"]
            rounded_ask = round(raw_ask / rounding) * rounding
            final_ask = int(max(tier["min_ask"], min(tier["max_ask"], rounded_ask)))

            high_potential.append({
                "donor_id": did,
                "first_name": profile["first_name"],
                "last_name": profile["last_name"],
                "email": profile["email"],
                "phone": profile["phone"],
                "segment": seg,
                "engagement_score": f"{round(engagement, 4):.4f}",
                "months_since_last_donation": months_since,
                "suggested_ask_amount": final_ask,
                "preferred_contact_method": pref_contact.get(did, "email"),
            })

        # 5. Sort
        high_potential.sort(key=lambda x: (-float(x["engagement_score"]), x["donor_id"]))

        # 6. Write output CSV
        output_path = os.path.join(self.workspace, "reengagement_list.csv")
        fieldnames = [
            "donor_id", "first_name", "last_name", "email", "phone", "segment",
            "engagement_score", "months_since_last_donation", "suggested_ask_amount",
            "preferred_contact_method",
        ]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(high_potential)

        # 7. Build action string
        total_ask = sum(row["suggested_ask_amount"] for row in high_potential)
        action = (
            f"Re-engagement analysis complete. "
            f"Identified {total_lapsed} lapsed donors total. "
            f"After scoring engagement and excluding do-not-contact donors, "
            f"the final re-engagement list contains {len(high_potential)} high-potential donors. "
            f"Total suggested ask amount: ${total_ask:,.2f}. "
            f"Results saved to reengagement_list.csv."
        )

        return self.step(action)
