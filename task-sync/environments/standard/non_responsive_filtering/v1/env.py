"""Environment for non-responsive document exclusion task."""
from typing import Tuple, Dict, List, Any
import sqlite3
import json
import csv
import os
import glob as glob_mod
from datetime import datetime, timedelta
import yaml


def tool(description: str, parameters: dict):
    """Decorator that stores tool metadata on the method."""
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


def _parse_md_table(filepath: str) -> List[Dict[str, str]]:
    """Parse a markdown table file into a list of dicts."""
    rows = []
    with open(filepath) as f:
        lines = f.readlines()
    header = None
    for line in lines:
        line = line.strip()
        if not line or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if not cells:
            continue
        if header is None:
            header = cells
            continue
        # skip separator row
        if all(set(c) <= set("- ") for c in cells):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


class Task_Env:
    PAGE_SIZE = 15

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
    # Tools
    # ------------------------------------------------------------------

    @tool(
        description="List documents with pagination. Returns a page of document records including doc_id, title, custodian_id, date_created, file_type, and bates_prefix. Page size is fixed at 15.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
            },
            "required": ["page"],
        },
    )
    def list_documents(self, page: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        total_pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        offset = (max(1, page) - 1) * self.PAGE_SIZE
        rows = cur.execute(
            "SELECT doc_id, title, custodian_id, date_created, file_type, bates_prefix "
            "FROM documents ORDER BY doc_id LIMIT ? OFFSET ?",
            (self.PAGE_SIZE, offset),
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "total_pages": total_pages,
            "total_documents": total,
            "documents": [dict(r) for r in rows],
        }

    @tool(
        description="Get full details for a single document by its ID, including file_size_kb and source_system.",
        parameters={
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "integer",
                    "description": "The document ID.",
                },
            },
            "required": ["doc_id"],
        },
    )
    def get_document_details(self, doc_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else {"error": f"Document {doc_id} not found"}

    @tool(
        description="List custodians with pagination. Returns custodian_id, full_name, department, email, hire_date, termination_date, data_volume_gb. Page size is fixed at 15.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
            },
            "required": ["page"],
        },
    )
    def list_custodians(self, page: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM custodians").fetchone()[0]
        total_pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        offset = (max(1, page) - 1) * self.PAGE_SIZE
        rows = cur.execute(
            "SELECT * FROM custodians ORDER BY custodian_id LIMIT ? OFFSET ?",
            (self.PAGE_SIZE, offset),
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "total_pages": total_pages,
            "total_custodians": total,
            "custodians": [dict(r) for r in rows],
        }

    @tool(
        description="Get information about a single custodian by their ID.",
        parameters={
            "type": "object",
            "properties": {
                "custodian_id": {
                    "type": "integer",
                    "description": "The custodian ID.",
                },
            },
            "required": ["custodian_id"],
        },
    )
    def get_custodian_info(self, custodian_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM custodians WHERE custodian_id = ?", (custodian_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else {"error": f"Custodian {custodian_id} not found"}

    @tool(
        description="Get all keyword search hits for a specific document. Returns a list of {keyword, hit_count} objects.",
        parameters={
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "integer",
                    "description": "The document ID.",
                },
            },
            "required": ["doc_id"],
        },
    )
    def get_keyword_hits(self, doc_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT keyword, hit_count FROM keyword_hits "
            "WHERE doc_id = ? ORDER BY keyword",
            (doc_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description="List all distinct RFP numbers that appear in the requests for production.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_rfp_numbers(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT DISTINCT rfp_number FROM rfp_criteria ORDER BY rfp_number"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]

    @tool(
        description="Get all criteria rows for a given RFP number. Each row contains criterion_id, rfp_number, subrequest_label, topic_category, criterion_keyword, date_start, and date_end.",
        parameters={
            "type": "object",
            "properties": {
                "rfp_number": {
                    "type": "string",
                    "description": "The RFP number, e.g. 'RFP-001'.",
                },
            },
            "required": ["rfp_number"],
        },
    )
    def get_rfp_criteria(self, rfp_number: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM rfp_criteria WHERE rfp_number = ? ORDER BY criterion_id",
            (rfp_number,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Ground-truth computation (used by step)
    # ------------------------------------------------------------------

    def _load_workspace_data(self):
        """Load all workspace files into lookup structures."""
        ws = self.workspace

        # Exclusion rules
        with open(os.path.join(ws, "exclusion_rules.json")) as f:
            rules = json.load(f)

        # Privilege log
        privileged_ids = set()
        with open(os.path.join(ws, "privilege_log.csv")) as f:
            for row in csv.DictReader(f):
                privileged_ids.add(int(row["doc_id"]))

        # Custodian-RFP scope mappings
        cust_rfp_map: Dict[int, set] = {}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "custodian_rfp_map_*.csv"))):
            with open(fp) as f:
                for row in csv.DictReader(f):
                    cid = int(row["custodian_id"])
                    cust_rfp_map.setdefault(cid, set()).add(row["rfp_number"])

        # Keyword weights: topic -> keyword -> weight
        keyword_weights: Dict[str, Dict[str, float]] = {}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "keyword_weights_*.json"))):
            with open(fp) as f:
                data = json.load(f)
                for topic, kw_dict in data.items():
                    keyword_weights[topic] = {
                        k: float(v) for k, v in kw_dict.items()
                    }

        # Document supplements (markdown tables)
        doc_supplement: Dict[int, Dict[str, str]] = {}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "document_supplement_*.md"))):
            for row in _parse_md_table(fp):
                doc_supplement[int(row["doc_id"])] = row

        # Custodian status (yaml)
        cust_status: Dict[int, dict] = {}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "custodian_status_*.yaml"))):
            with open(fp) as f:
                data = yaml.safe_load(f)
                for entry in data["custodian_statuses"]:
                    cust_status[int(entry["custodian_id"])] = entry

        return {
            "rules": rules,
            "privileged_ids": privileged_ids,
            "cust_rfp_map": cust_rfp_map,
            "keyword_weights": keyword_weights,
            "doc_supplement": doc_supplement,
            "cust_status": cust_status,
        }

    def _compute_ground_truth(self):
        """Compute the ground-truth exclusion list."""
        # Load DB data
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        docs = [dict(r) for r in conn.execute(
            "SELECT * FROM documents ORDER BY doc_id"
        ).fetchall()]
        custodians = {}
        for r in conn.execute("SELECT * FROM custodians").fetchall():
            custodians[r["custodian_id"]] = dict(r)
        kw_hits: Dict[int, List[dict]] = {}
        for r in conn.execute("SELECT doc_id, keyword, hit_count FROM keyword_hits").fetchall():
            kw_hits.setdefault(r["doc_id"], []).append(
                {"keyword": r["keyword"], "hit_count": r["hit_count"]}
            )
        rfp_criteria = [dict(r) for r in conn.execute(
            "SELECT * FROM rfp_criteria"
        ).fetchall()]
        conn.close()

        # Load workspace data
        wd = self._load_workspace_data()
        rules = wd["rules"]
        privileged_ids = wd["privileged_ids"]
        cust_rfp_map = wd["cust_rfp_map"]
        keyword_weights = wd["keyword_weights"]
        doc_supplement = wd["doc_supplement"]
        cust_status = wd["cust_status"]

        excluded_file_types = set(rules.get("excluded_file_types", []))
        protected_levels = set(rules.get("protected_confidentiality_levels", []))
        min_hit_count = rules["min_keyword_hit_count"]
        date_buffer = rules["date_buffer_days"]
        min_relevance = rules["min_weighted_relevance_score"]
        require_hold = rules["require_litigation_hold"]

        exclusion_list = []  # (doc_id, reason)
        responsive_ids = set()

        for doc in docs:
            did = doc["doc_id"]
            cid = doc["custodian_id"]

            # Priority 1: Privileged
            if did in privileged_ids:
                exclusion_list.append((did, "privileged"))
                continue

            # Priority 2: Excluded file type
            if doc["file_type"] in excluded_file_types:
                exclusion_list.append((did, "excluded_file_type"))
                continue

            # Priority 3: Custodian not on litigation hold
            if require_hold:
                status = cust_status.get(cid, {})
                if not status.get("litigation_hold", False):
                    exclusion_list.append((did, "no_litigation_hold"))
                    continue

            # Priority 4: Protected confidentiality → retain
            supp = doc_supplement.get(did, {})
            if supp.get("confidentiality_level") in protected_levels:
                responsive_ids.add(did)
                continue

            # Priority 5: RFP match check
            doc_date = datetime.strptime(doc["date_created"], "%Y-%m-%d")
            doc_hits = kw_hits.get(did, [])
            cust_rfps = cust_rfp_map.get(cid, set())

            matched = False
            for crit in rfp_criteria:
                rfp_num = crit["rfp_number"]
                if rfp_num not in cust_rfps:
                    continue
                crit_start = datetime.strptime(crit["date_start"], "%Y-%m-%d") - timedelta(days=date_buffer)
                crit_end = datetime.strptime(crit["date_end"], "%Y-%m-%d") + timedelta(days=date_buffer)
                if not (crit_start <= doc_date <= crit_end):
                    continue
                topic = crit["topic_category"]
                req_kw = crit["criterion_keyword"]
                tw = keyword_weights.get(topic, {})
                if tw.get(req_kw, 0.0) < min_relevance:
                    continue
                for hit in doc_hits:
                    if hit["keyword"] == req_kw and hit["hit_count"] >= min_hit_count:
                        matched = True
                        break
                if matched:
                    break

            if matched:
                responsive_ids.add(did)
            else:
                exclusion_list.append((did, "no_rfp_match"))

        return {
            "exclusion_list": exclusion_list,
            "responsive_ids": responsive_ids,
            "total_documents": len(docs),
            "docs": {d["doc_id"]: d for d in docs},
            "custodians": custodians,
        }

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
        gt = self._compute_ground_truth()
        gt_excluded = {did: reason for did, reason in gt["exclusion_list"]}
        gt_by_reason: Dict[str, set] = {}
        for did, reason in gt["exclusion_list"]:
            gt_by_reason.setdefault(reason, set()).add(did)

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ---- Criterion 1: CSV format (10 pts) ----
        c1_max = 10
        max_score += c1_max
        csv_path = os.path.join(self.workspace, "exclusion_list.csv")
        csv_ok = False
        agent_excluded: Dict[int, str] = {}
        required_cols = {
            "doc_id", "bates_prefix", "custodian_name",
            "date_created", "file_type", "exclusion_reason",
        }
        if os.path.exists(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    if required_cols.issubset(set(reader.fieldnames or [])):
                        rows_list = list(reader)
                        csv_ok = True
                        for row in rows_list:
                            agent_excluded[int(row["doc_id"])] = row["exclusion_reason"]
                        # Check sort order
                        ids = [int(r["doc_id"]) for r in rows_list]
                        if ids != sorted(ids):
                            csv_ok = False
            except Exception:
                pass

        c1_score = c1_max if csv_ok else 0
        eval_criteria["csv_format"] = {
            "passed": csv_ok,
            "score": c1_score,
            "max_score": c1_max,
            **({"reason": "exclusion_list.csv missing, wrong columns, or not sorted by doc_id"} if not csv_ok else {}),
        }
        total_score += c1_score

        # ---- Criterion 2: Privileged docs (15 pts) ----
        c2_max = 15
        max_score += c2_max
        priv_gt = gt_by_reason.get("privileged", set())
        agent_priv = {did for did, r in agent_excluded.items() if r == "privileged"}
        if priv_gt:
            priv_correct = len(priv_gt & agent_priv)
            c2_score = round(c2_max * priv_correct / len(priv_gt))
        else:
            c2_score = c2_max if not agent_priv else 0
        eval_criteria["privileged_docs"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            **({"reason": f"Identified {len(priv_gt & agent_priv)}/{len(priv_gt)} privileged docs"} if c2_score < c2_max else {}),
        }
        total_score += c2_score

        # ---- Criterion 3: Excluded file types (10 pts) ----
        c3_max = 10
        max_score += c3_max
        ft_gt = gt_by_reason.get("excluded_file_type", set())
        agent_ft = {did for did, r in agent_excluded.items() if r == "excluded_file_type"}
        if ft_gt:
            ft_correct = len(ft_gt & agent_ft)
            c3_score = round(c3_max * ft_correct / len(ft_gt))
        else:
            c3_score = c3_max if not agent_ft else 0
        eval_criteria["excluded_file_types"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            **({"reason": f"Identified {len(ft_gt & agent_ft)}/{len(ft_gt)} excluded file-type docs"} if c3_score < c3_max else {}),
        }
        total_score += c3_score

        # ---- Criterion 4: No litigation hold (15 pts) ----
        c4_max = 15
        max_score += c4_max
        hold_gt = gt_by_reason.get("no_litigation_hold", set())
        agent_hold = {did for did, r in agent_excluded.items() if r == "no_litigation_hold"}
        if hold_gt:
            hold_correct = len(hold_gt & agent_hold)
            c4_score = round(c4_max * hold_correct / len(hold_gt))
        else:
            c4_score = c4_max if not agent_hold else 0
        eval_criteria["no_litigation_hold"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            **({"reason": f"Identified {len(hold_gt & agent_hold)}/{len(hold_gt)} no-hold docs"} if c4_score < c4_max else {}),
        }
        total_score += c4_score

        # ---- Criterion 5: No RFP match (20 pts) ----
        c5_max = 20
        max_score += c5_max
        nrm_gt = gt_by_reason.get("no_rfp_match", set())
        agent_nrm = {did for did, r in agent_excluded.items() if r == "no_rfp_match"}
        if nrm_gt:
            nrm_correct = len(nrm_gt & agent_nrm)
            c5_score = round(c5_max * nrm_correct / len(nrm_gt))
        else:
            c5_score = c5_max if not agent_nrm else 0
        eval_criteria["no_rfp_match"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            **({"reason": f"Identified {len(nrm_gt & agent_nrm)}/{len(nrm_gt)} no-match docs"} if c5_score < c5_max else {}),
        }
        total_score += c5_score

        # ---- Criterion 6: No false exclusions (15 pts) ----
        c6_max = 15
        max_score += c6_max
        false_excl = set(agent_excluded.keys()) - set(gt_excluded.keys())
        if not false_excl:
            c6_score = c6_max
        else:
            ratio = max(0.0, 1.0 - len(false_excl) / max(1, len(gt_excluded)))
            c6_score = round(c6_max * ratio)
        eval_criteria["no_false_exclusions"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            **({"reason": f"{len(false_excl)} false exclusions found"} if c6_score < c6_max else {}),
        }
        total_score += c6_score

        # ---- Criterion 7: Summary JSON (15 pts) ----
        c7_max = 15
        max_score += c7_max
        summary_path = os.path.join(self.workspace, "exclusion_summary.json")
        c7_score = 0
        reason_str = []
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    summary = json.load(f)
                gt_total = gt["total_documents"]
                gt_excl = len(gt_excluded)
                gt_resp = gt_total - gt_excl
                if summary.get("total_documents_reviewed") == gt_total:
                    c7_score += 5
                else:
                    reason_str.append("total_documents_reviewed wrong")
                if summary.get("total_excluded") == gt_excl:
                    c7_score += 5
                else:
                    reason_str.append("total_excluded wrong")
                if summary.get("total_responsive") == gt_resp:
                    c7_score += 5
                else:
                    reason_str.append("total_responsive wrong")
            except Exception:
                reason_str.append("Could not parse exclusion_summary.json")
        else:
            reason_str.append("exclusion_summary.json missing")
        eval_criteria["summary_json"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            **({"reason": "; ".join(reason_str)} if c7_score < c7_max else {}),
        }
        total_score += c7_score

        reward = total_score / max_score if max_score > 0 else 0.0

        return reward, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------
    # Self-verification
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
        ws = self.workspace

        # ── Step 1: Get all documents via paginated tool calls ──
        all_docs = []
        page = 1
        while True:
            result = self.tools["list_documents"](page=page)
            all_docs.extend(result["documents"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ── Step 2: Get all custodians via paginated tool calls ──
        cust_map = {}  # custodian_id -> full record
        page = 1
        while True:
            result = self.tools["list_custodians"](page=page)
            for c in result["custodians"]:
                cust_map[c["custodian_id"]] = c
            if page >= result["total_pages"]:
                break
            page += 1

        # ── Step 3: Get all RFP criteria ──
        rfp_numbers = self.tools["list_rfp_numbers"]()
        all_criteria = []
        for rfp_num in rfp_numbers:
            criteria = self.tools["get_rfp_criteria"](rfp_number=rfp_num)
            all_criteria.extend(criteria)

        # ── Step 4: Get keyword hits for each document ──
        doc_kw_hits = {}
        for doc in all_docs:
            hits = self.tools["get_keyword_hits"](doc_id=doc["doc_id"])
            doc_kw_hits[doc["doc_id"]] = hits

        # ── Step 5: Read workspace files ──

        # Exclusion rules
        with open(os.path.join(ws, "exclusion_rules.json")) as f:
            rules = json.load(f)

        # Privilege log
        privileged_ids = set()
        with open(os.path.join(ws, "privilege_log.csv")) as f:
            for row in csv.DictReader(f):
                privileged_ids.add(int(row["doc_id"]))

        # Custodian-RFP scope
        cust_rfp_scope: Dict[int, set] = {}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "custodian_rfp_map_*.csv"))):
            with open(fp) as f:
                for row in csv.DictReader(f):
                    cid = int(row["custodian_id"])
                    cust_rfp_scope.setdefault(cid, set()).add(row["rfp_number"])

        # Keyword weights
        keyword_weights: Dict[str, Dict[str, float]] = {}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "keyword_weights_*.json"))):
            with open(fp) as f:
                data = json.load(f)
                for topic, kw_dict in data.items():
                    keyword_weights[topic] = {k: float(v) for k, v in kw_dict.items()}

        # Document supplements (markdown tables)
        doc_supplement: Dict[int, Dict[str, str]] = {}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "document_supplement_*.md"))):
            for row in _parse_md_table(fp):
                doc_supplement[int(row["doc_id"])] = row

        # Custodian status
        cust_status: Dict[int, dict] = {}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "custodian_status_*.yaml"))):
            with open(fp) as f:
                data = yaml.safe_load(f)
                for entry in data["custodian_statuses"]:
                    cust_status[int(entry["custodian_id"])] = entry

        # ── Step 6: Apply exclusion logic ──
        excluded_ft = set(rules.get("excluded_file_types", []))
        protected_levels = set(rules.get("protected_confidentiality_levels", []))
        min_hit = rules["min_keyword_hit_count"]
        buffer_days = rules["date_buffer_days"]
        min_rel = rules["min_weighted_relevance_score"]
        require_hold = rules["require_litigation_hold"]

        exclusion_rows = []
        reason_counts = {
            "privileged": 0,
            "excluded_file_type": 0,
            "no_litigation_hold": 0,
            "no_rfp_match": 0,
        }
        responsive_count = 0

        for doc in all_docs:
            did = doc["doc_id"]
            cid = doc["custodian_id"]
            cust_name = cust_map[cid]["full_name"]
            reason = None

            # Priority 1: Privileged
            if did in privileged_ids:
                reason = "privileged"

            # Priority 2: Excluded file type
            if reason is None and doc["file_type"] in excluded_ft:
                reason = "excluded_file_type"

            # Priority 3: No litigation hold
            if reason is None and require_hold:
                st = cust_status.get(cid, {})
                if not st.get("litigation_hold", False):
                    reason = "no_litigation_hold"

            # Priority 4: Protected confidentiality → retain
            if reason is None:
                supp = doc_supplement.get(did, {})
                if supp.get("confidentiality_level") in protected_levels:
                    responsive_count += 1
                    continue

            # Priority 5: RFP match
            if reason is None:
                doc_date = datetime.strptime(doc["date_created"], "%Y-%m-%d")
                hits = doc_kw_hits.get(did, [])
                cust_rfps = cust_rfp_scope.get(cid, set())

                matched = False
                for crit in all_criteria:
                    if crit["rfp_number"] not in cust_rfps:
                        continue
                    cs = datetime.strptime(crit["date_start"], "%Y-%m-%d") - timedelta(days=buffer_days)
                    ce = datetime.strptime(crit["date_end"], "%Y-%m-%d") + timedelta(days=buffer_days)
                    if not (cs <= doc_date <= ce):
                        continue
                    topic = crit["topic_category"]
                    req_kw = crit["criterion_keyword"]
                    tw = keyword_weights.get(topic, {})
                    if tw.get(req_kw, 0.0) < min_rel:
                        continue
                    for hit in hits:
                        if hit["keyword"] == req_kw and hit["hit_count"] >= min_hit:
                            matched = True
                            break
                    if matched:
                        break

                if not matched:
                    reason = "no_rfp_match"

            if reason:
                exclusion_rows.append({
                    "doc_id": did,
                    "bates_prefix": doc["bates_prefix"],
                    "custodian_name": cust_name,
                    "date_created": doc["date_created"],
                    "file_type": doc["file_type"],
                    "exclusion_reason": reason,
                })
                reason_counts[reason] += 1
            else:
                responsive_count += 1

        # Sort by doc_id
        exclusion_rows.sort(key=lambda x: x["doc_id"])

        # ── Step 7: Write deliverables ──
        with open(os.path.join(ws, "exclusion_list.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "doc_id", "bates_prefix", "custodian_name",
                "date_created", "file_type", "exclusion_reason",
            ])
            writer.writeheader()
            writer.writerows(exclusion_rows)

        total_docs = len(all_docs)
        total_excluded = len(exclusion_rows)
        summary = {
            "total_documents_reviewed": total_docs,
            "total_excluded": total_excluded,
            "total_responsive": total_docs - total_excluded,
            "exclusion_breakdown": reason_counts,
        }
        with open(os.path.join(ws, "exclusion_summary.json"), "w") as f:
            json.dump(summary, f, indent=2)

        action = f"EXCLUSION TOTAL: {total_excluded}/{total_docs}"

        return self.step(action)
