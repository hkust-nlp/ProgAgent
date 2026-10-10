"""
Cold-chain food safety task — environment definition.
"""
import sqlite3
import os
import json
import csv
import math
import re
from collections import defaultdict
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

    # ── keep this implementation unchanged ───────────────────────
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

    # ═════════════════════════════════════════════════════════════
    #  TOOLS
    # ═════════════════════════════════════════════════════════════

    @tool(
        description=(
            "Retrieve a paginated list of product lots. Returns lot_code, "
            "product_id, facility_id, production_date, and expiry_date for "
            "each lot."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "1-based page number.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Items per page (max 50).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_lots(self, page: int, page_size: int):
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT lot_code, product_id, facility_id, production_date, "
            "expiry_date FROM lots ORDER BY lot_code "
            "LIMIT ? OFFSET ?", (page_size, offset)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM lots").fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size),
            "items": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Retrieve a paginated list of shipments. Returns shipment_id, "
            "lot_code, depart_ts, arrive_ts, reading_count, and max_temp_c "
            "for each shipment."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "1-based page number.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Items per page (max 50).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_shipments(self, page: int, page_size: int):
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT s.shipment_id, s.lot_code, s.depart_ts, s.arrive_ts, "
            "COUNT(t.reading_id) AS reading_count, "
            "MAX(t.temperature_c) AS max_temp_c "
            "FROM shipments s "
            "LEFT JOIN temperature_readings t ON s.shipment_id = t.shipment_id "
            "GROUP BY s.shipment_id "
            "ORDER BY s.shipment_id "
            "LIMIT ? OFFSET ?", (page_size, offset)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size),
            "items": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Retrieve all temperature sensor readings for a single shipment."
        ),
        parameters={
            "type": "object",
            "properties": {
                "shipment_id": {
                    "type": "string",
                    "description": "The shipment identifier (e.g. SHP-0001).",
                },
            },
            "required": ["shipment_id"],
        },
    )
    def get_temperature_readings(self, shipment_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT reading_id, sensor_id, timestamp, temperature_c "
            "FROM temperature_readings "
            "WHERE shipment_id = ? ORDER BY timestamp",
            (shipment_id,),
        ).fetchall()
        conn.close()
        return {"shipment_id": shipment_id, "readings": [dict(r) for r in rows]}

    @tool(
        description=(
            "Return the ingredient genealogy tree for a given lot: each "
            "ingredient lot code, ingredient name, and supplier id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "lot_code": {
                    "type": "string",
                    "description": "The lot identifier (e.g. LOT-0001).",
                },
            },
            "required": ["lot_code"],
        },
    )
    def get_ingredient_tree(self, lot_code: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ingredient_lot_code, ingredient_name, supplier_id "
            "FROM ingredient_lots WHERE lot_code = ? "
            "ORDER BY ingredient_lot_code",
            (lot_code,),
        ).fetchall()
        conn.close()
        return {"lot_code": lot_code, "ingredients": [dict(r) for r in rows]}

    @tool(
        description=(
            "Find all product lots that share a given ingredient lot code."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ingredient_lot_code": {
                    "type": "string",
                    "description": "The ingredient lot code (e.g. ING-0001).",
                },
            },
            "required": ["ingredient_lot_code"],
        },
    )
    def find_lots_sharing_ingredient(self, ingredient_lot_code: str):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT DISTINCT lot_code FROM ingredient_lots "
            "WHERE ingredient_lot_code = ? ORDER BY lot_code",
            (ingredient_lot_code,),
        ).fetchall()
        conn.close()
        return {
            "ingredient_lot_code": ingredient_lot_code,
            "lot_codes": [r[0] for r in rows],
        }

    @tool(
        description=(
            "Return all consumer complaints filed against a specific lot."
        ),
        parameters={
            "type": "object",
            "properties": {
                "lot_code": {
                    "type": "string",
                    "description": "The lot identifier (e.g. LOT-0001).",
                },
            },
            "required": ["lot_code"],
        },
    )
    def search_complaints(self, lot_code: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT complaint_id, complaint_date, reporter_name "
            "FROM complaints WHERE lot_code = ? ORDER BY complaint_id",
            (lot_code,),
        ).fetchall()
        conn.close()
        return {"lot_code": lot_code, "complaints": [dict(r) for r in rows]}

    @tool(
        description=(
            "Return the total complaint count per lot for every lot that has "
            "at least one complaint."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def get_complaint_counts(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT lot_code, COUNT(*) AS total_complaints "
            "FROM complaints GROUP BY lot_code "
            "ORDER BY total_complaints DESC, lot_code"
        ).fetchall()
        conn.close()
        return {"counts": [{"lot_code": r[0], "total_complaints": r[1]}
                           for r in rows]}

    # ═════════════════════════════════════════════════════════════
    #  HELPERS (used by both step and verify)
    # ═════════════════════════════════════════════════════════════

    @staticmethod
    def _read_yaml_simple(path):
        """Minimal YAML parser for the simple structure used here."""
        data = {}
        stack = [data]
        indent_stack = [-1]
        with open(path) as f:
            for line in f:
                stripped = line.rstrip()
                if not stripped or stripped.startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip())
                while indent <= indent_stack[-1]:
                    stack.pop()
                    indent_stack.pop()
                key_val = stripped.split(":", 1)
                key = key_val[0].strip()
                val = key_val[1].strip() if len(key_val) > 1 else ""
                if val == "":
                    new_dict = {}
                    stack[-1][key] = new_dict
                    stack.append(new_dict)
                    indent_stack.append(indent)
                else:
                    try:
                        val = float(val)
                        if val == int(val):
                            val = int(val)
                    except ValueError:
                        pass
                    stack[-1][key] = val
        return data

    def _load_workspace_config(self):
        """Load all workspace reference files. Returns a config dict."""
        ws = self.workspace
        cfg = {}

        # temperature_policy.yaml
        cfg["temp_policy"] = self._read_yaml_simple(
            os.path.join(ws, "temperature_policy.yaml"))

        # product_catalog.csv  -> {product_id: {name, category}}
        prod = {}
        with open(os.path.join(ws, "product_catalog.csv")) as f:
            for row in csv.DictReader(f):
                prod[row["product_id"]] = {
                    "name": row["product_name"],
                    "category": row["storage_category"],
                }
        cfg["products"] = prod

        # facility_registry.csv -> {fac_id: {name, type, ...}}
        fac = {}
        with open(os.path.join(ws, "facility_registry.csv")) as f:
            for row in csv.DictReader(f):
                fac[row["facility_id"]] = {
                    "name": row["facility_name"],
                    "type": row["facility_type"],
                }
        cfg["facilities"] = fac

        # supplier_directory.csv -> {sup_id: {name, status, ...}}
        sup = {}
        with open(os.path.join(ws, "supplier_directory.csv")) as f:
            for row in csv.DictReader(f):
                sup[row["supplier_id"]] = {
                    "name": row["supplier_name"],
                    "status": row["certification_status"],
                }
        cfg["suppliers"] = sup

        # symptom_codes.json -> {code: {name, severity}}
        with open(os.path.join(ws, "symptom_codes.json")) as f:
            cfg["symptoms"] = json.load(f)

        # audit reports  -> list of dicts
        audits = []
        for fn in sorted(os.listdir(ws)):
            if fn.startswith("audit_report_") and fn.endswith(".csv"):
                with open(os.path.join(ws, fn)) as f:
                    audits.extend(list(csv.DictReader(f)))
        cfg["audits"] = audits

        # shipment manifests -> {shipment_id: {origin, dest, ...}}
        manifests = {}
        for fn in sorted(os.listdir(ws)):
            if fn.startswith("shipment_manifest_") and fn.endswith(".json"):
                with open(os.path.join(ws, fn)) as f:
                    for rec in json.load(f):
                        manifests[rec["shipment_id"]] = rec
        cfg["manifests"] = manifests

        # complaint details -> {complaint_id: {symptom_code, ...}}
        comp_details = {}
        for fn in sorted(os.listdir(ws)):
            if fn.startswith("complaint_detail_") and fn.endswith(".json"):
                with open(os.path.join(ws, fn)) as f:
                    for rec in json.load(f):
                        comp_details[rec["complaint_id"]] = rec
        cfg["complaint_details"] = comp_details

        return cfg

    def _compute_ground_truth(self):
        """
        Compute the expected hold set and risk scores from DB + workspace.
        Returns (hold_dict, cfg) where hold_dict maps lot_code -> set of reasons.
        """
        cfg = self._load_workspace_config()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # -- load DB tables --
        lots = {r["lot_code"]: dict(r)
                for r in conn.execute("SELECT * FROM lots ORDER BY lot_code")}
        shipments = conn.execute("SELECT * FROM shipments").fetchall()
        ship_map = {}
        lot_ships = defaultdict(list)
        for r in shipments:
            d = dict(r)
            ship_map[d["shipment_id"]] = d
            lot_ships[d["lot_code"]].append(d)

        readings_by_ship = defaultdict(list)
        for r in conn.execute("SELECT * FROM temperature_readings"):
            readings_by_ship[r["shipment_id"]].append(dict(r))

        ingredients_by_lot = defaultdict(list)
        for r in conn.execute("SELECT * FROM ingredient_lots"):
            ingredients_by_lot[r["lot_code"]].append(dict(r))

        complaints_by_lot = defaultdict(list)
        for r in conn.execute("SELECT * FROM complaints"):
            complaints_by_lot[r["lot_code"]].append(dict(r))

        conn.close()

        temp_policy = cfg["temp_policy"]
        count_thresh = int(temp_policy["excursion_rules"]["count_threshold"])
        single_excess = float(
            temp_policy["excursion_rules"]["single_excess_threshold_c"])

        cat_thresholds = {}
        for cat, info in temp_policy["storage_categories"].items():
            cat_thresholds[cat] = float(info["max_temp_c"])

        # -- Criterion: TEMP_EXCURSION --
        temp_flagged = set()
        for lc, lot in lots.items():
            pid = lot["product_id"]
            cat = cfg["products"].get(pid, {}).get("category", "")
            thresh = cat_thresholds.get(cat)
            if thresh is None:
                continue
            for ship in lot_ships[lc]:
                rds = readings_by_ship[ship["shipment_id"]]
                exceed_count = sum(
                    1 for r in rds if r["temperature_c"] > thresh)
                max_excess = max(
                    (r["temperature_c"] - thresh for r in rds), default=0)
                if exceed_count >= count_thresh or max_excess > single_excess:
                    temp_flagged.add(lc)
                    break

        # -- Criterion: SANITATION --
        # Find facilities with >=2 unresolved critical violations
        fac_crit_unresolved = defaultdict(int)
        for a in cfg["audits"]:
            if a["severity"] == "critical" and a["resolved"] == "no":
                fac_crit_unresolved[a["facility_id"]] += 1
        bad_facs = {f for f, cnt in fac_crit_unresolved.items() if cnt >= 2}

        san_flagged = set()
        for lc, lot in lots.items():
            # production facility
            facs_involved = {lot["facility_id"]}
            # transit facilities from manifests
            for ship in lot_ships[lc]:
                m = cfg["manifests"].get(ship["shipment_id"])
                if m:
                    facs_involved.add(m["origin_facility_id"])
                    facs_involved.add(m["destination_facility_id"])
            if facs_involved & bad_facs:
                san_flagged.add(lc)

        # -- Criterion: COMPLAINT_CLUSTER --
        high_crit_syms = {s for s, d in cfg["symptoms"].items()
                          if d["severity"] in ("high", "critical")}
        cc_flagged = set()
        for lc in lots:
            comps = complaints_by_lot[lc]
            if len(comps) < 3:
                continue
            sym_counts = defaultdict(int)
            for c in comps:
                detail = cfg["complaint_details"].get(c["complaint_id"])
                if detail:
                    sym_counts[detail["symptom_code"]] += 1
            for sym, cnt in sym_counts.items():
                if cnt >= 3 and sym in high_crit_syms:
                    cc_flagged.add(lc)
                    break

        # -- Criterion: INGREDIENT_LINK --
        primary_flagged = temp_flagged | san_flagged | cc_flagged
        bad_sups = {sid for sid, info in cfg["suppliers"].items()
                    if info["status"] in ("suspended", "revoked")}

        # Build ingredient -> lots reverse map from DB
        ing_to_lots = defaultdict(set)
        for lc, ings in ingredients_by_lot.items():
            for ing in ings:
                ing_to_lots[ing["ingredient_lot_code"]].add(lc)

        # Collect bad-supplier ingredients from primary lots
        primary_bad_ings = {}  # ilc -> set of primary lots that have it
        for pf_lc in primary_flagged:
            for ing in ingredients_by_lot[pf_lc]:
                if ing["supplier_id"] in bad_sups:
                    ilc = ing["ingredient_lot_code"]
                    primary_bad_ings.setdefault(ilc, set()).add(pf_lc)

        link_flagged = set()
        for ilc, pf_set in primary_bad_ings.items():
            sharing = ing_to_lots[ilc]
            for lc in sharing:
                # lc gets INGREDIENT_LINK if there is at least one
                # primary-flagged lot OTHER than lc sharing this ingredient
                if pf_set - {lc}:
                    link_flagged.add(lc)

        # -- Assemble hold dict --
        REASON_ORDER = ["TEMP_EXCURSION", "SANITATION",
                        "COMPLAINT_CLUSTER", "INGREDIENT_LINK"]
        POINTS = {"TEMP_EXCURSION": 30, "SANITATION": 25,
                  "COMPLAINT_CLUSTER": 25, "INGREDIENT_LINK": 20}

        all_flagged = temp_flagged | san_flagged | cc_flagged | link_flagged
        hold = {}
        for lc in sorted(all_flagged):
            reasons = set()
            if lc in temp_flagged:
                reasons.add("TEMP_EXCURSION")
            if lc in san_flagged:
                reasons.add("SANITATION")
            if lc in cc_flagged:
                reasons.add("COMPLAINT_CLUSTER")
            if lc in link_flagged:
                reasons.add("INGREDIENT_LINK")
            hold[lc] = reasons

        return hold, cfg, lots, REASON_ORDER, POINTS

    # ═════════════════════════════════════════════════════════════
    #  STEP — evaluation
    # ═════════════════════════════════════════════════════════════

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        hold, cfg, lots, REASON_ORDER, POINTS = self._compute_ground_truth()

        # Build expected hold_report rows
        expected_rows = []
        for lc in hold:
            reasons = hold[lc]
            pid = lots[lc]["product_id"]
            pname = cfg["products"].get(pid, {}).get("name", "")
            fid = lots[lc]["facility_id"]
            fname = cfg["facilities"].get(fid, {}).get("name", "")
            reason_str = "|".join(r for r in REASON_ORDER if r in reasons)
            score = sum(POINTS[r] for r in reasons)
            expected_rows.append({
                "lot_code": lc,
                "product_name": pname,
                "facility_name": fname,
                "hold_reasons": reason_str,
                "risk_score": str(score),
            })
        expected_rows.sort(key=lambda r: (-int(r["risk_score"]), r["lot_code"]))
        expected_lot_set = set(hold.keys())
        expected_lots_sorted = sorted(expected_lot_set)

        # ── Read agent's hold_report.csv ─────────────────────────
        report_path = os.path.join(self.workspace, "hold_report.csv")
        agent_rows = []
        report_exists = os.path.isfile(report_path)
        if report_exists:
            with open(report_path) as f:
                agent_rows = list(csv.DictReader(f))

        # ── Parse agent's action for HOLD_LOTS line ──────────────
        agent_lots_from_action = set()
        m = re.search(r"HOLD_LOTS:\s*(.+)", action or "")
        if m:
            agent_lots_from_action = {
                x.strip() for x in m.group(1).split(",") if x.strip()
            }

        criteria = {}

        # 1. Report structure (10 pts)
        expected_cols = {"lot_code", "product_name", "facility_name",
                         "hold_reasons", "risk_score"}
        if report_exists and agent_rows:
            actual_cols = set(agent_rows[0].keys())
            col_ok = expected_cols.issubset(actual_cols)
        else:
            col_ok = False
        criteria["report_structure"] = {
            "passed": col_ok,
            "score": 10 if col_ok else 0,
            "max_score": 10,
            "reason": "" if col_ok else "hold_report.csv missing or wrong columns",
        }

        # 2. TEMP_EXCURSION lots (20 pts)
        exp_temp = {lc for lc, rs in hold.items() if "TEMP_EXCURSION" in rs}
        got_temp = set()
        for row in agent_rows:
            if "TEMP_EXCURSION" in row.get("hold_reasons", ""):
                got_temp.add(row.get("lot_code", ""))
        if exp_temp:
            temp_score = round(20 * len(exp_temp & got_temp) / len(exp_temp))
            if got_temp - exp_temp:
                temp_score = max(0, temp_score - 5)
        else:
            temp_score = 20 if not got_temp else 15
        criteria["temp_excursion_lots"] = {
            "passed": temp_score == 20,
            "score": temp_score,
            "max_score": 20,
            "reason": f"expected {sorted(exp_temp)}, got {sorted(got_temp)}"
                      if temp_score < 20 else "",
        }

        # 3. SANITATION lots (15 pts)
        exp_san = {lc for lc, rs in hold.items() if "SANITATION" in rs}
        got_san = set()
        for row in agent_rows:
            if "SANITATION" in row.get("hold_reasons", ""):
                got_san.add(row.get("lot_code", ""))
        if exp_san:
            san_score = round(15 * len(exp_san & got_san) / len(exp_san))
            if got_san - exp_san:
                san_score = max(0, san_score - 4)
        else:
            san_score = 15 if not got_san else 10
        criteria["sanitation_lots"] = {
            "passed": san_score == 15,
            "score": san_score,
            "max_score": 15,
            "reason": f"expected {sorted(exp_san)}, got {sorted(got_san)}"
                      if san_score < 15 else "",
        }

        # 4. COMPLAINT_CLUSTER lots (15 pts)
        exp_cc = {lc for lc, rs in hold.items() if "COMPLAINT_CLUSTER" in rs}
        got_cc = set()
        for row in agent_rows:
            if "COMPLAINT_CLUSTER" in row.get("hold_reasons", ""):
                got_cc.add(row.get("lot_code", ""))
        if exp_cc:
            cc_score = round(15 * len(exp_cc & got_cc) / len(exp_cc))
            if got_cc - exp_cc:
                cc_score = max(0, cc_score - 4)
        else:
            cc_score = 15 if not got_cc else 10
        criteria["complaint_cluster_lots"] = {
            "passed": cc_score == 15,
            "score": cc_score,
            "max_score": 15,
            "reason": f"expected {sorted(exp_cc)}, got {sorted(got_cc)}"
                      if cc_score < 15 else "",
        }

        # 5. INGREDIENT_LINK lots (20 pts)
        exp_link = {lc for lc, rs in hold.items() if "INGREDIENT_LINK" in rs}
        got_link = set()
        for row in agent_rows:
            if "INGREDIENT_LINK" in row.get("hold_reasons", ""):
                got_link.add(row.get("lot_code", ""))
        if exp_link:
            link_score = round(20 * len(exp_link & got_link) / len(exp_link))
            if got_link - exp_link:
                link_score = max(0, link_score - 5)
        else:
            link_score = 20 if not got_link else 15
        criteria["ingredient_link_lots"] = {
            "passed": link_score == 20,
            "score": link_score,
            "max_score": 20,
            "reason": f"expected {sorted(exp_link)}, got {sorted(got_link)}"
                      if link_score < 20 else "",
        }

        # 6. Risk scores correct (10 pts)
        score_ok = 0
        if agent_rows and expected_rows:
            agent_score_map = {}
            for row in agent_rows:
                agent_score_map[row.get("lot_code", "")] = row.get(
                    "risk_score", "").strip()
            exp_score_map = {r["lot_code"]: r["risk_score"]
                             for r in expected_rows}
            matches = sum(1 for lc in exp_score_map
                          if agent_score_map.get(lc) == exp_score_map[lc])
            if exp_score_map:
                score_ok = round(10 * matches / len(exp_score_map))
        criteria["risk_scores"] = {
            "passed": score_ok == 10,
            "score": score_ok,
            "max_score": 10,
            "reason": "" if score_ok == 10 else "some risk scores mismatch",
        }

        # 7. Final response lot list (10 pts)
        resp_ok = (agent_lots_from_action == expected_lot_set)
        criteria["final_response"] = {
            "passed": resp_ok,
            "score": 10 if resp_ok else 0,
            "max_score": 10,
            "reason": "" if resp_ok else
                f"expected {expected_lots_sorted}, "
                f"got {sorted(agent_lots_from_action)}",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ═════════════════════════════════════════════════════════════
    #  VERIFY — prove end-to-end solvability using only tools
    # ═════════════════════════════════════════════════════════════

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
        cfg = self._load_workspace_config()

        # ── Thresholds ───────────────────────────────────────────
        tp = cfg["temp_policy"]
        count_thresh = int(tp["excursion_rules"]["count_threshold"])
        single_excess = float(tp["excursion_rules"]["single_excess_threshold_c"])
        cat_thresholds = {
            cat: float(info["max_temp_c"])
            for cat, info in tp["storage_categories"].items()
        }

        # ── Load all lots (paginated) ────────────────────────────
        all_lots = {}
        page = 1
        while True:
            res = self.tools["list_lots"](page=page, page_size=50)
            for item in res["items"]:
                all_lots[item["lot_code"]] = item
            if page >= res["total_pages"]:
                break
            page += 1

        # ── Load all shipments (paginated) ───────────────────────
        all_ships = {}
        lot_ship_ids = defaultdict(list)
        page = 1
        while True:
            res = self.tools["list_shipments"](page=page, page_size=50)
            for item in res["items"]:
                all_ships[item["shipment_id"]] = item
                lot_ship_ids[item["lot_code"]].append(item["shipment_id"])
            if page >= res["total_pages"]:
                break
            page += 1

        # ── TEMP_EXCURSION ───────────────────────────────────────
        temp_flagged = set()
        for lc, lot in all_lots.items():
            pid = lot["product_id"]
            cat = cfg["products"].get(pid, {}).get("category", "")
            thresh = cat_thresholds.get(cat)
            if thresh is None:
                continue
            for sid in lot_ship_ids[lc]:
                ship = all_ships[sid]
                if ship["max_temp_c"] is not None and ship["max_temp_c"] > thresh:
                    # detailed check
                    rdata = self.tools["get_temperature_readings"](
                        shipment_id=sid)
                    rds = rdata["readings"]
                    exceed_count = sum(
                        1 for r in rds if r["temperature_c"] > thresh)
                    max_excess = max(
                        (r["temperature_c"] - thresh for r in rds), default=0)
                    if (exceed_count >= count_thresh
                            or max_excess > single_excess):
                        temp_flagged.add(lc)
                        break

        # ── SANITATION ───────────────────────────────────────────
        # Find facilities with >=2 unresolved critical violations
        fac_crit = defaultdict(int)
        for a in cfg["audits"]:
            if a["severity"] == "critical" and a["resolved"] == "no":
                fac_crit[a["facility_id"]] += 1
        bad_facs = {f for f, c in fac_crit.items() if c >= 2}

        san_flagged = set()
        for lc, lot in all_lots.items():
            facs = {lot["facility_id"]}
            for sid in lot_ship_ids[lc]:
                m = cfg["manifests"].get(sid)
                if m:
                    facs.add(m["origin_facility_id"])
                    facs.add(m["destination_facility_id"])
            if facs & bad_facs:
                san_flagged.add(lc)

        # ── COMPLAINT_CLUSTER ────────────────────────────────────
        high_crit_syms = {s for s, d in cfg["symptoms"].items()
                          if d["severity"] in ("high", "critical")}
        counts_res = self.tools["get_complaint_counts"]()
        candidate_lots = [
            c["lot_code"] for c in counts_res["counts"]
            if c["total_complaints"] >= 3
        ]

        cc_flagged = set()
        for lc in candidate_lots:
            comp_res = self.tools["search_complaints"](lot_code=lc)
            sym_counts = defaultdict(int)
            for c in comp_res["complaints"]:
                detail = cfg["complaint_details"].get(c["complaint_id"])
                if detail:
                    sym_counts[detail["symptom_code"]] += 1
            for sym, cnt in sym_counts.items():
                if cnt >= 3 and sym in high_crit_syms:
                    cc_flagged.add(lc)
                    break

        # ── INGREDIENT_LINK ──────────────────────────────────────
        primary_flagged = temp_flagged | san_flagged | cc_flagged
        bad_sups = {sid for sid, info in cfg["suppliers"].items()
                    if info["status"] in ("suspended", "revoked")}

        # Collect bad-supplier ingredients from primary lots
        primary_bad_ings = {}  # ilc -> set of primary lots that have it
        for pf_lc in sorted(primary_flagged):
            ing_res = self.tools["get_ingredient_tree"](lot_code=pf_lc)
            for ing in ing_res["ingredients"]:
                if ing["supplier_id"] in bad_sups:
                    ilc = ing["ingredient_lot_code"]
                    primary_bad_ings.setdefault(ilc, set()).add(pf_lc)

        link_flagged = set()
        for ilc, pf_set in primary_bad_ings.items():
            share_res = self.tools["find_lots_sharing_ingredient"](
                ingredient_lot_code=ilc)
            sharing = set(share_res["lot_codes"])
            for lc in sharing:
                if pf_set - {lc}:
                    link_flagged.add(lc)

        # ── Assemble hold report ─────────────────────────────────
        REASON_ORDER = ["TEMP_EXCURSION", "SANITATION",
                        "COMPLAINT_CLUSTER", "INGREDIENT_LINK"]
        PTS = {"TEMP_EXCURSION": 30, "SANITATION": 25,
               "COMPLAINT_CLUSTER": 25, "INGREDIENT_LINK": 20}

        all_flagged = temp_flagged | san_flagged | cc_flagged | link_flagged
        rows = []
        for lc in sorted(all_flagged):
            reasons = set()
            if lc in temp_flagged:
                reasons.add("TEMP_EXCURSION")
            if lc in san_flagged:
                reasons.add("SANITATION")
            if lc in cc_flagged:
                reasons.add("COMPLAINT_CLUSTER")
            if lc in link_flagged:
                reasons.add("INGREDIENT_LINK")
            pid = all_lots[lc]["product_id"]
            pname = cfg["products"].get(pid, {}).get("name", "")
            fid = all_lots[lc]["facility_id"]
            fname = cfg["facilities"].get(fid, {}).get("name", "")
            reason_str = "|".join(r for r in REASON_ORDER if r in reasons)
            score = sum(PTS[r] for r in reasons)
            rows.append({
                "lot_code": lc,
                "product_name": pname,
                "facility_name": fname,
                "hold_reasons": reason_str,
                "risk_score": str(score),
            })
        rows.sort(key=lambda r: (-int(r["risk_score"]), r["lot_code"]))

        # Write hold_report.csv
        report_path = os.path.join(ws, "hold_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "lot_code", "product_name", "facility_name",
                "hold_reasons", "risk_score"])
            writer.writeheader()
            writer.writerows(rows)

        # Construct final action
        lots_sorted = sorted(all_flagged)
        action = "HOLD_LOTS: " + ", ".join(lots_sorted)

        return self.step(action)
