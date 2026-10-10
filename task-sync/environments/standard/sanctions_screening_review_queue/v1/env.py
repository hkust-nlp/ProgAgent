#!/usr/bin/env python3
"""Environment for sanctions screening task."""

import sqlite3
import os
import json
import csv
import re
import glob
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

    # -----------------------------------------------------------------------
    # Helper: name similarity (word-level Jaccard)
    # -----------------------------------------------------------------------
    @staticmethod
    def _name_similarity(name1: str, name2: str) -> float:
        w1 = set(re.sub(r"[^a-z\s]", "", name1.lower()).split())
        w2 = set(re.sub(r"[^a-z\s]", "", name2.lower()).split())
        if not w1 or not w2:
            return 0.0
        return len(w1 & w2) / len(w1 | w2)

    # -----------------------------------------------------------------------
    # Tools
    # -----------------------------------------------------------------------
    @tool(
        description="List customers with pending screening status. Returns a paginated list of customers awaiting sanctions screening. Each entry includes the customer ID, full name, customer type, nationality, and registration date.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20, default 10)"
                }
            },
            "required": ["page"]
        }
    )
    def list_pending_customers(self, page: int, page_size: int = 10) -> dict:
        page_size = min(page_size, 20)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        total = c.execute("SELECT COUNT(*) FROM customers WHERE screening_status='pending'").fetchone()[0]
        offset = (page - 1) * page_size
        rows = c.execute(
            "SELECT customer_id, full_name, customer_type, nationality, registration_date "
            "FROM customers WHERE screening_status='pending' "
            "ORDER BY customer_id LIMIT ? OFFSET ?",
            (page_size, offset)
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_customers": total,
            "total_pages": (total + page_size - 1) // page_size,
            "customers": [dict(r) for r in rows],
        }

    @tool(
        description="Get detailed information for a specific customer by their ID. Returns the full customer record including date of birth, nationality, country of residence, customer type, and screening status.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer identifier, e.g. CUST-0001"
                }
            },
            "required": ["customer_id"]
        }
    )
    def get_customer_details(self, customer_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Customer {customer_id} not found"}
        return dict(row)

    @tool(
        description="Search sanctions lists by name. Computes word-level similarity between the query and all sanctions entry names and their known aliases. Returns entries whose similarity score meets a minimum internal threshold of 0.3, along with the computed similarity score. Optionally filter by sanctions list source.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Name to search against sanctions entries"
                },
                "list_source": {
                    "type": "string",
                    "enum": ["OFAC", "EU", "UN"],
                    "description": "Optional: filter results to a specific sanctions list"
                }
            },
            "required": ["query"]
        }
    )
    def search_sanctions(self, query: str, list_source: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        if list_source:
            entries = c.execute(
                "SELECT * FROM sanctions_entries WHERE list_source = ?", (list_source,)
            ).fetchall()
        else:
            entries = c.execute("SELECT * FROM sanctions_entries").fetchall()

        # Also load aliases
        aliases = {}
        for row in c.execute("SELECT entry_id, alias_name FROM sanctions_aliases").fetchall():
            aliases.setdefault(row["entry_id"], []).append(row["alias_name"])

        conn.close()
        results = []
        for entry in entries:
            eid = entry["entry_id"]
            # Check main name
            sim = self._name_similarity(query, entry["entity_name"])
            # Check aliases
            for alias in aliases.get(eid, []):
                alias_sim = self._name_similarity(query, alias)
                sim = max(sim, alias_sim)

            if sim >= 0.3:
                results.append({
                    "entry_id": eid,
                    "entity_name": entry["entity_name"],
                    "list_source": entry["list_source"],
                    "entity_type": entry["entity_type"],
                    "similarity_score": round(sim, 4),
                })

        results.sort(key=lambda x: -x["similarity_score"])
        return {"query": query, "matches": results[:20]}

    @tool(
        description="Get full details of a sanctions entry by its ID. Returns the complete record including entity name, list source, date of birth, nationalities, country, program, remarks, and known aliases.",
        parameters={
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "string",
                    "description": "The sanctions entry identifier, e.g. SAN-0001"
                }
            },
            "required": ["entry_id"]
        }
    )
    def get_sanctions_entry(self, entry_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM sanctions_entries WHERE entry_id = ?", (entry_id,)
        ).fetchone()
        aliases = [r["alias_name"] for r in conn.execute(
            "SELECT alias_name FROM sanctions_aliases WHERE entry_id = ?", (entry_id,)
        ).fetchall()]
        conn.close()
        if row is None:
            return {"error": f"Entry {entry_id} not found"}
        result = dict(row)
        result["aliases"] = aliases
        return result

    @tool(
        description="Get all payment intermediaries associated with a customer. Returns the list of intermediaries including name, country, type, transaction amount, currency, and date.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer identifier"
                }
            },
            "required": ["customer_id"]
        }
    )
    def get_payment_intermediaries(self, customer_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM payment_intermediaries WHERE customer_id = ? ORDER BY intermediary_id",
            (customer_id,)
        ).fetchall()
        conn.close()
        return {
            "customer_id": customer_id,
            "intermediaries": [dict(r) for r in rows],
        }

    @tool(
        description="Get the ultimate beneficial ownership structure for a customer. Returns all UBO records including entity name, ownership percentage, beneficial owner name, nationality, date of birth, and control type.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer identifier"
                }
            },
            "required": ["customer_id"]
        }
    )
    def get_ubo_structure(self, customer_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM ubo_structures WHERE customer_id = ? ORDER BY ubo_record_id",
            (customer_id,)
        ).fetchall()
        conn.close()
        return {
            "customer_id": customer_id,
            "ubo_records": [dict(r) for r in rows],
        }

    @tool(
        description="Get the risk tier for a specific country from the country risk matrix stored in the workspace. Returns the country name, risk tier (1-5), and whether an active sanctions regime applies.",
        parameters={
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "Country name to look up"
                }
            },
            "required": ["country"]
        }
    )
    def get_country_risk(self, country: str) -> dict:
        filepath = os.path.join(self.workspace, "country_risk_matrix.csv")
        if not os.path.exists(filepath):
            return {"error": "Country risk matrix not found"}
        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["country"].strip().lower() == country.strip().lower():
                    return {
                        "country": row["country"],
                        "risk_tier": int(row["risk_tier"]),
                        "sanctions_regime": row["sanctions_regime"],
                    }
        return {"country": country, "risk_tier": 2, "sanctions_regime": "no",
                "note": "Country not found in matrix, default tier 2 assigned"}

    # -----------------------------------------------------------------------
    # Ground-truth computation (used by step and verify)
    # -----------------------------------------------------------------------
    def _load_config(self) -> dict:
        """Load screening config from workspace."""
        import yaml
        filepath = os.path.join(self.workspace, "screening_config.yaml")
        with open(filepath) as f:
            return yaml.safe_load(f)

    def _load_country_risk(self) -> dict:
        """Load country risk matrix from workspace."""
        filepath = os.path.join(self.workspace, "country_risk_matrix.csv")
        risk = {}
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                risk[row["country"].strip()] = int(row["risk_tier"])
        return risk

    def _load_customer_aliases(self) -> dict:
        """Load customer aliases from workspace JSON files."""
        aliases = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "customer_batch_*.json"))):
            with open(fp) as f:
                for rec in json.load(f):
                    aliases[rec["customer_id"]] = rec.get("aliases", [])
        return aliases

    def _load_pep_info(self) -> dict:
        """Load PEP info from workspace YAML files. Returns {customer_id: [{owner, pep_country}]}."""
        import yaml
        pep_info = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "ubo_batch_*.yaml"))):
            with open(fp) as f:
                declarations = yaml.safe_load(f)
            if not declarations:
                continue
            for decl in declarations:
                cid = decl["customer_id"]
                pep_owners = []
                for bo in decl.get("beneficial_owners", []):
                    if bo.get("pep_status"):
                        pep_owners.append({
                            "beneficial_owner": bo["beneficial_owner"],
                            "pep_country": bo.get("pep_country"),
                        })
                if pep_owners:
                    pep_info[cid] = pep_owners
        return pep_info

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the expected screening results for all customers."""
        config = self._load_config()
        country_risk = self._load_country_risk()
        customer_aliases = self._load_customer_aliases()
        pep_info = self._load_pep_info()

        threshold = config["name_match_threshold"]
        ubo_own_threshold = config["ubo_ownership_screening_threshold"]
        country_tier_threshold = config["country_risk_tier_flag_threshold"]
        weights = config["risk_score_weights"]
        priority_thresholds = config["priority_thresholds"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        customers = conn.execute(
            "SELECT * FROM customers WHERE screening_status='pending' ORDER BY customer_id"
        ).fetchall()

        sanctions = conn.execute("SELECT * FROM sanctions_entries").fetchall()
        alias_rows = conn.execute("SELECT entry_id, alias_name FROM sanctions_aliases").fetchall()
        san_aliases = {}
        for r in alias_rows:
            san_aliases.setdefault(r["entry_id"], []).append(r["alias_name"])

        intermediaries = {}
        for r in conn.execute("SELECT * FROM payment_intermediaries").fetchall():
            intermediaries.setdefault(r["customer_id"], []).append(dict(r))

        ubos = {}
        for r in conn.execute("SELECT * FROM ubo_structures").fetchall():
            ubos.setdefault(r["customer_id"], []).append(dict(r))

        conn.close()

        def find_matches(query_name):
            """Find sanctions entries matching a name above threshold."""
            matched = []
            for san in sanctions:
                sim = self._name_similarity(query_name, san["entity_name"])
                for alias in san_aliases.get(san["entry_id"], []):
                    alias_sim = self._name_similarity(query_name, alias)
                    sim = max(sim, alias_sim)
                if sim >= threshold:
                    matched.append(san["entry_id"])
            return matched

        results = []
        for cust in customers:
            cid = cust["customer_id"]
            flags = set()
            matched_san_ids = set()

            # 1. Direct name match
            name_matches = find_matches(cust["full_name"])
            if name_matches:
                flags.add("direct_name_match")
                matched_san_ids.update(name_matches)

            # 2. Alias matches
            for alias in customer_aliases.get(cid, []):
                alias_matches = find_matches(alias)
                if alias_matches:
                    flags.add("alias_match")
                    matched_san_ids.update(alias_matches)

            # 3. Intermediary screening
            for intm in intermediaries.get(cid, []):
                # Check intermediary name against sanctions
                intm_matches = find_matches(intm["intermediary_name"])
                if intm_matches:
                    flags.add("intermediary_sanctions_match")
                    matched_san_ids.update(intm_matches)

                # Check intermediary country
                tier = country_risk.get(intm["intermediary_country"], 2)
                if tier >= country_tier_threshold:
                    flags.add("high_risk_country_intermediary")

            # 4. UBO screening
            for ubo in ubos.get(cid, []):
                if ubo["ownership_percentage"] >= ubo_own_threshold:
                    ubo_matches = find_matches(ubo["beneficial_owner_name"])
                    if ubo_matches:
                        flags.add("ubo_sanctions_match")
                        matched_san_ids.update(ubo_matches)

            # 5. PEP in high-risk country
            for pep_rec in pep_info.get(cid, []):
                pep_country = pep_rec.get("pep_country")
                if pep_country:
                    tier = country_risk.get(pep_country, 2)
                    if tier >= country_tier_threshold:
                        flags.add("pep_high_risk_country")

            # Compute risk score
            risk_score = sum(weights.get(f, 0) for f in flags)

            # Priority
            if risk_score >= priority_thresholds["critical"]:
                priority = "CRITICAL"
            elif risk_score >= priority_thresholds["high"]:
                priority = "HIGH"
            elif risk_score >= priority_thresholds["medium"]:
                priority = "MEDIUM"
            elif risk_score > 0:
                priority = "LOW"
            else:
                priority = "CLEAR"

            results.append({
                "customer_id": cid,
                "customer_name": cust["full_name"],
                "risk_score": risk_score,
                "flagged": risk_score > 0,
                "flag_reasons": sorted(flags),
                "matched_sanctions_ids": sorted(matched_san_ids),
                "review_priority": priority,
            })

        # Sort by risk_score desc, then customer_id asc
        results.sort(key=lambda x: (-x["risk_score"], x["customer_id"]))
        return results

    # -----------------------------------------------------------------------
    # Step: evaluate
    # -----------------------------------------------------------------------
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
        gt_by_id = {r["customer_id"]: r for r in ground_truth}

        criteria = {}

        # --- Criterion 1: File existence and format (10 pts) ---
        csv_path = os.path.join(self.workspace, "screening_results.csv")
        expected_cols = {"customer_id", "customer_name", "risk_score", "flagged",
                         "flag_reasons", "matched_sanctions_ids", "review_priority"}
        file_ok = False
        agent_rows = []
        if os.path.exists(csv_path):
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and expected_cols.issubset(set(reader.fieldnames)):
                    file_ok = True
                    for row in reader:
                        agent_rows.append(row)
        criteria["file_format"] = {
            "passed": file_ok,
            "score": 10 if file_ok else 0,
            "max_score": 10,
            "reason": "" if file_ok else "screening_results.csv missing or has wrong columns",
        }

        # --- Criterion 2: Customer completeness (15 pts) ---
        agent_ids = {r["customer_id"] for r in agent_rows}
        gt_ids = {r["customer_id"] for r in ground_truth}
        coverage = len(agent_ids & gt_ids) / len(gt_ids) if gt_ids else 0
        comp_score = round(coverage * 15)
        criteria["customer_completeness"] = {
            "passed": coverage == 1.0,
            "score": comp_score,
            "max_score": 15,
            "reason": "" if coverage == 1.0 else f"Coverage {coverage:.2%}, missing {len(gt_ids - agent_ids)} customers",
        }

        # --- Criterion 3: Flagged customer accuracy (25 pts) ---
        gt_flagged = {r["customer_id"] for r in ground_truth if r["flagged"]}
        agent_flagged = set()
        for r in agent_rows:
            val = r.get("flagged", "").strip().lower()
            if val in ("true", "yes", "1"):
                agent_flagged.add(r["customer_id"])

        tp = len(gt_flagged & agent_flagged)
        fp = len(agent_flagged - gt_flagged)
        fn = len(gt_flagged - agent_flagged)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        flag_score = round(f1 * 25)
        criteria["flagged_accuracy"] = {
            "passed": f1 >= 0.95,
            "score": flag_score,
            "max_score": 25,
            "reason": "" if f1 >= 0.95 else f"F1={f1:.3f} (P={precision:.3f}, R={recall:.3f}), TP={tp}, FP={fp}, FN={fn}",
        }

        # --- Criterion 4: Risk score accuracy (15 pts) ---
        score_correct = 0
        score_total = 0
        for r in agent_rows:
            cid = r.get("customer_id", "")
            if cid in gt_by_id:
                score_total += 1
                try:
                    agent_score = int(float(r.get("risk_score", "0")))
                    if agent_score == gt_by_id[cid]["risk_score"]:
                        score_correct += 1
                except (ValueError, TypeError):
                    pass
        score_acc = score_correct / score_total if score_total > 0 else 0
        risk_pts = round(score_acc * 15)
        criteria["risk_score_accuracy"] = {
            "passed": score_acc >= 0.95,
            "score": risk_pts,
            "max_score": 15,
            "reason": "" if score_acc >= 0.95 else f"Accuracy {score_acc:.2%} ({score_correct}/{score_total})",
        }

        # --- Criterion 5: Flag reasons correctness (15 pts) ---
        reason_correct = 0
        reason_total = 0
        for r in agent_rows:
            cid = r.get("customer_id", "")
            if cid in gt_by_id:
                reason_total += 1
                gt_reasons = gt_by_id[cid]["flag_reasons"]
                agent_reasons_raw = r.get("flag_reasons", "").strip()
                if agent_reasons_raw:
                    agent_reasons = sorted([x.strip() for x in agent_reasons_raw.split(";")])
                else:
                    agent_reasons = []
                if agent_reasons == gt_reasons:
                    reason_correct += 1
        reason_acc = reason_correct / reason_total if reason_total > 0 else 0
        reason_pts = round(reason_acc * 15)
        criteria["flag_reasons"] = {
            "passed": reason_acc >= 0.95,
            "score": reason_pts,
            "max_score": 15,
            "reason": "" if reason_acc >= 0.95 else f"Accuracy {reason_acc:.2%} ({reason_correct}/{reason_total})",
        }

        # --- Criterion 6: Matched sanctions IDs (10 pts) ---
        san_correct = 0
        san_total = 0
        for r in agent_rows:
            cid = r.get("customer_id", "")
            if cid in gt_by_id:
                san_total += 1
                gt_sids = gt_by_id[cid]["matched_sanctions_ids"]
                agent_sids_raw = r.get("matched_sanctions_ids", "").strip()
                if agent_sids_raw:
                    agent_sids = sorted([x.strip() for x in agent_sids_raw.split(";")])
                else:
                    agent_sids = []
                if agent_sids == gt_sids:
                    san_correct += 1
        san_acc = san_correct / san_total if san_total > 0 else 0
        san_pts = round(san_acc * 10)
        criteria["sanctions_ids"] = {
            "passed": san_acc >= 0.95,
            "score": san_pts,
            "max_score": 10,
            "reason": "" if san_acc >= 0.95 else f"Accuracy {san_acc:.2%} ({san_correct}/{san_total})",
        }

        # --- Criterion 7: Review priority (10 pts) ---
        pri_correct = 0
        pri_total = 0
        for r in agent_rows:
            cid = r.get("customer_id", "")
            if cid in gt_by_id:
                pri_total += 1
                if r.get("review_priority", "").strip().upper() == gt_by_id[cid]["review_priority"]:
                    pri_correct += 1
        pri_acc = pri_correct / pri_total if pri_total > 0 else 0
        pri_pts = round(pri_acc * 10)
        criteria["review_priority"] = {
            "passed": pri_acc >= 0.95,
            "score": pri_pts,
            "max_score": 10,
            "reason": "" if pri_acc >= 0.95 else f"Accuracy {pri_acc:.2%} ({pri_correct}/{pri_total})",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # -----------------------------------------------------------------------
    # Verify: self-solve using only tools and workspace
    # -----------------------------------------------------------------------
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
        import yaml

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # 1. Load config from workspace
        with open(os.path.join(self.workspace, "screening_config.yaml")) as f:
            config = yaml.safe_load(f)
        threshold = config["name_match_threshold"]
        ubo_own_threshold = config["ubo_ownership_screening_threshold"]
        country_tier_threshold = config["country_risk_tier_flag_threshold"]
        weights = config["risk_score_weights"]
        priority_thresholds = config["priority_thresholds"]

        # 2. Load country risk from workspace
        country_risk = {}
        with open(os.path.join(self.workspace, "country_risk_matrix.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                country_risk[row["country"].strip()] = int(row["risk_tier"])

        # 3. Load customer aliases from workspace JSON
        customer_aliases = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "customer_batch_*.json"))):
            with open(fp) as f:
                for rec in json.load(f):
                    customer_aliases[rec["customer_id"]] = rec.get("aliases", [])

        # 4. Load PEP info from workspace YAML
        pep_info = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "ubo_batch_*.yaml"))):
            with open(fp) as f:
                declarations = yaml.safe_load(f)
            if not declarations:
                continue
            for decl in declarations:
                cid = decl["customer_id"]
                for bo in decl.get("beneficial_owners", []):
                    if bo.get("pep_status"):
                        pep_info.setdefault(cid, []).append({
                            "beneficial_owner": bo["beneficial_owner"],
                            "pep_country": bo.get("pep_country"),
                        })

        # 5. List all pending customers via tool (paginated)
        all_customers = []
        page = 1
        while True:
            result = call_tool("list_pending_customers", page=page, page_size=10)
            all_customers.extend(result["customers"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 6. Screen each customer
        screening_results = []
        for cust in all_customers:
            cid = cust["customer_id"]
            cname = cust["full_name"]
            flags = set()
            matched_san_ids = set()

            # 6a. Search customer name against sanctions
            search_result = call_tool("search_sanctions", query=cname)
            for m in search_result["matches"]:
                if m["similarity_score"] >= threshold:
                    flags.add("direct_name_match")
                    matched_san_ids.add(m["entry_id"])

            # 6b. Search aliases
            for alias in customer_aliases.get(cid, []):
                alias_result = call_tool("search_sanctions", query=alias)
                for m in alias_result["matches"]:
                    if m["similarity_score"] >= threshold:
                        flags.add("alias_match")
                        matched_san_ids.add(m["entry_id"])

            # 6c. Check payment intermediaries
            intm_result = call_tool("get_payment_intermediaries", customer_id=cid)
            for intm in intm_result["intermediaries"]:
                # Check intermediary name against sanctions
                intm_search = call_tool("search_sanctions", query=intm["intermediary_name"])
                for m in intm_search["matches"]:
                    if m["similarity_score"] >= threshold:
                        flags.add("intermediary_sanctions_match")
                        matched_san_ids.add(m["entry_id"])

                # Check intermediary country risk
                tier = country_risk.get(intm["intermediary_country"], 2)
                if tier >= country_tier_threshold:
                    flags.add("high_risk_country_intermediary")

            # 6d. Check UBO structure
            ubo_result = call_tool("get_ubo_structure", customer_id=cid)
            for ubo in ubo_result["ubo_records"]:
                if ubo["ownership_percentage"] >= ubo_own_threshold:
                    ubo_search = call_tool("search_sanctions", query=ubo["beneficial_owner_name"])
                    for m in ubo_search["matches"]:
                        if m["similarity_score"] >= threshold:
                            flags.add("ubo_sanctions_match")
                            matched_san_ids.add(m["entry_id"])

            # 6e. Check PEP in high-risk country
            for pep_rec in pep_info.get(cid, []):
                pep_country = pep_rec.get("pep_country")
                if pep_country:
                    tier = country_risk.get(pep_country, 2)
                    if tier >= country_tier_threshold:
                        flags.add("pep_high_risk_country")

            # Compute risk score
            risk_score = sum(weights.get(f, 0) for f in flags)

            # Priority
            if risk_score >= priority_thresholds["critical"]:
                priority = "CRITICAL"
            elif risk_score >= priority_thresholds["high"]:
                priority = "HIGH"
            elif risk_score >= priority_thresholds["medium"]:
                priority = "MEDIUM"
            elif risk_score > 0:
                priority = "LOW"
            else:
                priority = "CLEAR"

            screening_results.append({
                "customer_id": cid,
                "customer_name": cname,
                "risk_score": risk_score,
                "flagged": risk_score > 0,
                "flag_reasons": ";".join(sorted(flags)),
                "matched_sanctions_ids": ";".join(sorted(matched_san_ids)),
                "review_priority": priority,
            })

        # Sort by risk_score desc, customer_id asc
        screening_results.sort(key=lambda x: (-x["risk_score"], x["customer_id"]))

        # 7. Write screening_results.csv
        csv_path = os.path.join(self.workspace, "screening_results.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "customer_id", "customer_name", "risk_score", "flagged",
                "flag_reasons", "matched_sanctions_ids", "review_priority"
            ])
            writer.writeheader()
            for r in screening_results:
                writer.writerow(r)

        # 8. Build action string with summary
        total = len(screening_results)
        flagged = sum(1 for r in screening_results if r["flagged"])
        critical = sum(1 for r in screening_results if r["review_priority"] == "CRITICAL")
        high = sum(1 for r in screening_results if r["review_priority"] == "HIGH")
        medium = sum(1 for r in screening_results if r["review_priority"] == "MEDIUM")
        low = sum(1 for r in screening_results if r["review_priority"] == "LOW")
        clear = sum(1 for r in screening_results if r["review_priority"] == "CLEAR")

        critical_list = [r for r in screening_results if r["review_priority"] == "CRITICAL"]

        action = (
            f"Screening complete. Total customers screened: {total}. "
            f"Flagged: {flagged}. Clear: {clear}. "
            f"Priority breakdown - CRITICAL: {critical}, HIGH: {high}, MEDIUM: {medium}, LOW: {low}. "
        )
        if critical_list:
            action += "CRITICAL priority customers: "
            action += ", ".join(
                f"{r['customer_id']} ({r['customer_name']}, score={r['risk_score']})"
                for r in critical_list
            )
            action += ". "
        action += "Results saved to screening_results.csv."

        print(f"[verify] Tool calls made: {tool_call_count}")
        return self.step(action)
