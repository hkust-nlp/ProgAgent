"""
Content Piracy Detection - Environment (hardened tool surface)

Hardened surface (M0 + M5 + M2):
  - M5: export_platform_activity returns every access-log event and every
    download event (joined with student tier and lecture access tier) in ONE
    JSON-string response with NO pagination. At larger data scales this
    single response is far bigger than a model's context budget; it is only
    safe to consume inside a programmatic sandbox that filters before
    printing. Paginated / per-entity tools remain available.
  - M2: the remaining tools return a mix of shapes: native dicts,
    JSON-encoded strings, MCP-style envelopes, plain key:value text, and
    Python-repr strings. Error responses use a different object shape than
    successes and share no keys with them. Tools never raise.
  - M0 lives in prompt.md / data.py (de-proceduralized prompt + additive
    detection_methodology.md workspace document).
Task semantics, data generation, deliverables, and step() scoring are
unchanged from the base environment.
"""

import ast
import csv
import glob
import hashlib
import io
import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


# --- Define this decorator at the top of env.py, keep unchanged ---
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# --- Hardened tool-surface helpers ---

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


def _int_or_none(value):
    """Return an int if value is int-like (not bool), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


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

    # ──────────────────────────────────────────
    # Tool methods
    # ──────────────────────────────────────────

    @tool(
        description=(
            "Retrieve a single student record by student_id, including name, "
            "email, subscription tier, join date, and active status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "student_id": {
                    "type": "integer",
                    "description": "The unique student identifier.",
                },
            },
            "required": ["student_id"],
        },
    )
    def get_student(self, student_id: Any = None):
        sid = _int_or_none(student_id)
        if sid is None:
            return _error(
                400, "validation_error",
                f"body.student_id should be an integer, instead was {_shape(student_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM students WHERE student_id = ?", (sid,)
        ).fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find student with ID: {sid}.",
            )
        fields = dict(row)
        return "\n".join(f"{k}: {v}" for k, v in fields.items())

    @tool(
        description=(
            "Search students with optional filters. Returns a paginated list. "
            "Page numbering starts at 1. Default page_size is 20."
        ),
        parameters={
            "type": "object",
            "properties": {
                "subscription_tier": {
                    "type": "string",
                    "enum": ["free", "basic", "premium", "enterprise"],
                    "description": "Filter by subscription tier.",
                },
                "is_active": {
                    "type": "boolean",
                    "description": "Filter by active status.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_students(
        self,
        subscription_tier: Any = None,
        is_active: Any = None,
        page: Any = 1,
        page_size: Any = 20,
    ):
        pg = _int_or_none(page)
        ps = _int_or_none(page_size)
        if pg is None:
            return _error(
                400, "validation_error",
                f"body.page should be an integer, instead was {_shape(page)}.",
            )
        if ps is None or ps < 1:
            return _error(
                400, "validation_error",
                f"body.page_size should be a positive integer, instead was {_shape(page_size)}.",
            )
        if subscription_tier is not None and not isinstance(subscription_tier, str):
            return _error(
                400, "validation_error",
                f"body.subscription_tier should be a string, instead was {_shape(subscription_tier)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        clauses, params = [], []
        if subscription_tier:
            clauses.append("subscription_tier = ?")
            params.append(subscription_tier)
        if is_active is not None:
            clauses.append("is_active = ?")
            params.append(int(bool(is_active)))
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM students {where}", params
        ).fetchone()[0]
        offset = (max(1, pg) - 1) * ps
        rows = conn.execute(
            f"SELECT * FROM students {where} ORDER BY student_id LIMIT ? OFFSET ?",
            params + [ps, offset],
        ).fetchall()
        conn.close()
        return {
            "students": [dict(r) for r in rows],
            "total": total,
            "page": pg,
            "page_size": ps,
        }

    @tool(
        description=(
            "Retrieve a single course record by course_id, including title, "
            "instructor, category, and minimum subscription tier."
        ),
        parameters={
            "type": "object",
            "properties": {
                "course_id": {
                    "type": "integer",
                    "description": "The unique course identifier.",
                },
            },
            "required": ["course_id"],
        },
    )
    def get_course(self, course_id: Any = None):
        cid = _int_or_none(course_id)
        if cid is None:
            return _error(
                400, "validation_error",
                f"body.course_id should be an integer, instead was {_shape(course_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM courses WHERE course_id = ?", (cid,)
        ).fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find course with ID: {cid}.",
            )
        return repr(dict(row))

    @tool(
        description=(
            "Retrieve a single lecture record by lecture_id, including course "
            "association, title, content hash, duration, and access tier."
        ),
        parameters={
            "type": "object",
            "properties": {
                "lecture_id": {
                    "type": "integer",
                    "description": "The unique lecture identifier.",
                },
            },
            "required": ["lecture_id"],
        },
    )
    def get_lecture(self, lecture_id: Any = None):
        lid = _int_or_none(lecture_id)
        if lid is None:
            return _error(
                400, "validation_error",
                f"body.lecture_id should be an integer, instead was {_shape(lecture_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM lectures WHERE lecture_id = ?", (lid,)
        ).fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find lecture with ID: {lid}.",
            )
        return dict(row)

    @tool(
        description=(
            "Find the lecture whose content_hash matches the given fingerprint. "
            "Returns the full lecture record when a match exists."
        ),
        parameters={
            "type": "object",
            "properties": {
                "content_hash": {
                    "type": "string",
                    "description": "The 16-character hex content fingerprint.",
                },
            },
            "required": ["content_hash"],
        },
    )
    def find_lecture_by_hash(self, content_hash: Any = None):
        if not isinstance(content_hash, str) or not content_hash:
            return _error(
                400, "validation_error",
                f"body.content_hash should be a non-empty string, instead was {_shape(content_hash)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM lectures WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find lecture with content_hash: {content_hash}.",
            )
        return _envelope({"match": dict(row)})

    @tool(
        description=(
            "Query access logs with optional filters on student_id, lecture_id, "
            "or ip_address. Returns paginated results. Default page_size is 20."
        ),
        parameters={
            "type": "object",
            "properties": {
                "student_id": {
                    "type": "integer",
                    "description": "Filter by student_id.",
                },
                "lecture_id": {
                    "type": "integer",
                    "description": "Filter by lecture_id.",
                },
                "ip_address": {
                    "type": "string",
                    "description": "Filter by exact IP address.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 20.",
                },
            },
            "required": [],
        },
    )
    def query_access_logs(
        self,
        student_id: Any = None,
        lecture_id: Any = None,
        ip_address: Any = None,
        page: Any = 1,
        page_size: Any = 20,
    ):
        pg = _int_or_none(page)
        ps = _int_or_none(page_size)
        if pg is None:
            return json.dumps(_error(
                400, "validation_error",
                f"body.page should be an integer, instead was {_shape(page)}.",
            ), ensure_ascii=False)
        if ps is None or ps < 1:
            return json.dumps(_error(
                400, "validation_error",
                f"body.page_size should be a positive integer, instead was {_shape(page_size)}.",
            ), ensure_ascii=False)
        if student_id is not None and _int_or_none(student_id) is None:
            return json.dumps(_error(
                400, "validation_error",
                f"body.student_id should be an integer, instead was {_shape(student_id)}.",
            ), ensure_ascii=False)
        if lecture_id is not None and _int_or_none(lecture_id) is None:
            return json.dumps(_error(
                400, "validation_error",
                f"body.lecture_id should be an integer, instead was {_shape(lecture_id)}.",
            ), ensure_ascii=False)
        if ip_address is not None and not isinstance(ip_address, str):
            return json.dumps(_error(
                400, "validation_error",
                f"body.ip_address should be a string, instead was {_shape(ip_address)}.",
            ), ensure_ascii=False)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        clauses, params = [], []
        if student_id is not None:
            clauses.append("student_id = ?")
            params.append(_int_or_none(student_id))
        if lecture_id is not None:
            clauses.append("lecture_id = ?")
            params.append(_int_or_none(lecture_id))
        if ip_address is not None:
            clauses.append("ip_address = ?")
            params.append(ip_address)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM access_logs {where}", params
        ).fetchone()[0]
        offset = (max(1, pg) - 1) * ps
        rows = conn.execute(
            f"SELECT * FROM access_logs {where} ORDER BY log_id LIMIT ? OFFSET ?",
            params + [ps, offset],
        ).fetchall()
        conn.close()
        return json.dumps({
            "logs": [dict(r) for r in rows],
            "total": total,
            "page": pg,
            "page_size": ps,
        }, ensure_ascii=False)

    @tool(
        description=(
            "Query download records with optional filters on student_id, lecture_id, "
            "or ip_address. Returns paginated results. Default page_size is 20."
        ),
        parameters={
            "type": "object",
            "properties": {
                "student_id": {
                    "type": "integer",
                    "description": "Filter by student_id.",
                },
                "lecture_id": {
                    "type": "integer",
                    "description": "Filter by lecture_id.",
                },
                "ip_address": {
                    "type": "string",
                    "description": "Filter by exact IP address.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 20.",
                },
            },
            "required": [],
        },
    )
    def query_downloads(
        self,
        student_id: Any = None,
        lecture_id: Any = None,
        ip_address: Any = None,
        page: Any = 1,
        page_size: Any = 20,
    ):
        pg = _int_or_none(page)
        ps = _int_or_none(page_size)
        if pg is None:
            return _error(
                400, "validation_error",
                f"body.page should be an integer, instead was {_shape(page)}.",
            )
        if ps is None or ps < 1:
            return _error(
                400, "validation_error",
                f"body.page_size should be a positive integer, instead was {_shape(page_size)}.",
            )
        if student_id is not None and _int_or_none(student_id) is None:
            return _error(
                400, "validation_error",
                f"body.student_id should be an integer, instead was {_shape(student_id)}.",
            )
        if lecture_id is not None and _int_or_none(lecture_id) is None:
            return _error(
                400, "validation_error",
                f"body.lecture_id should be an integer, instead was {_shape(lecture_id)}.",
            )
        if ip_address is not None and not isinstance(ip_address, str):
            return _error(
                400, "validation_error",
                f"body.ip_address should be a string, instead was {_shape(ip_address)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        clauses, params = [], []
        if student_id is not None:
            clauses.append("student_id = ?")
            params.append(_int_or_none(student_id))
        if lecture_id is not None:
            clauses.append("lecture_id = ?")
            params.append(_int_or_none(lecture_id))
        if ip_address is not None:
            clauses.append("ip_address = ?")
            params.append(ip_address)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM download_records {where}", params
        ).fetchone()[0]
        offset = (max(1, pg) - 1) * ps
        rows = conn.execute(
            f"SELECT * FROM download_records {where} ORDER BY download_id LIMIT ? OFFSET ?",
            params + [ps, offset],
        ).fetchall()
        conn.close()
        return _envelope({
            "downloads": [dict(r) for r in rows],
            "total": total,
            "page": pg,
            "page_size": ps,
        })

    @tool(
        description=(
            "List all lectures belonging to a given course."
        ),
        parameters={
            "type": "object",
            "properties": {
                "course_id": {
                    "type": "integer",
                    "description": "The course identifier.",
                },
            },
            "required": ["course_id"],
        },
    )
    def get_lectures_for_course(self, course_id: Any = None):
        cid = _int_or_none(course_id)
        if cid is None:
            return _error(
                400, "validation_error",
                f"body.course_id should be an integer, instead was {_shape(course_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM lectures WHERE course_id = ? ORDER BY lecture_id",
            (cid,),
        ).fetchall()
        conn.close()
        return {"lectures": [dict(r) for r in rows]}

    @tool(
        description=(
            "Export the complete platform activity dataset in a single "
            "response: every access-log event and every download event across "
            "all lectures and students, each joined with the accessing "
            "student's subscription tier, the lecture's access tier, and the "
            "event's IP address. No pagination required."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def export_platform_activity(self) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.lecture_id, s.subscription_tier AS tier,
                   l.access_tier, a.ip_address AS ip
            FROM access_logs a
            JOIN students s ON s.student_id = a.student_id
            JOIN lectures l ON l.lecture_id = a.lecture_id
            ORDER BY a.log_id
            """
        )
        events = [dict(r, kind="access") for r in cur.fetchall()]
        cur.execute(
            """
            SELECT d.lecture_id, s.subscription_tier AS tier,
                   l.access_tier, d.ip_address AS ip
            FROM download_records d
            JOIN students s ON s.student_id = d.student_id
            JOIN lectures l ON l.lecture_id = d.lecture_id
            ORDER BY d.download_id
            """
        )
        events.extend(dict(r, kind="download") for r in cur.fetchall())
        conn.close()
        return json.dumps(
            {"event_count": len(events), "events": events}, ensure_ascii=False
        )

    # ──────────────────────────────────────────
    # Ground-truth computation (shared by step and verify)
    # ──────────────────────────────────────────

    def _compute_ground_truth(self) -> list[dict]:
        """
        Derive the authoritative takedown list from workspace files + database.
        Returns a list of dicts sorted by piracy_score desc, lecture_id asc.
        Only lectures meeting the min score threshold are included.
        """
        ws = self.workspace

        # ── Load config ──
        with open(os.path.join(ws, "piracy_policy.yaml")) as f:
            policy = yaml.safe_load(f)["scoring"]
        with open(os.path.join(ws, "tier_access_rules.json")) as f:
            tier_rules = json.load(f)

        weights = policy["weights"]
        w_ext = weights["external_source"]
        w_unauth = weights["unauthorized_access"]
        w_ip = weights["watchlist_ip_hit"]
        tier_mult = policy["tier_multipliers"]
        pri_thresh = policy["priority_thresholds"]
        pri_actions = policy["priority_actions"]
        min_score = policy["min_piracy_score"]

        # ── Collect all fingerprints + external URLs from scan reports ──
        # hash -> set of external URLs
        hash_urls: dict[str, set[str]] = {}
        for fp in sorted(glob.glob(os.path.join(ws, "scan_report_*.json"))):
            with open(fp) as f:
                report = json.load(f)
            for finding in report.get("findings", []):
                h = finding["content_fingerprint"]
                url = finding["external_url"]
                hash_urls.setdefault(h, set()).add(url)

        # ── Collect fingerprints + URLs from DMCA complaints ──
        for fp in sorted(glob.glob(os.path.join(ws, "dmca_complaint_*.txt"))):
            with open(fp) as f:
                text = f.read()
            for block in re.split(r"=== DMCA Notice .+? ===", text):
                block = block.strip()
                if not block:
                    continue
                h_m = re.search(r"Content Hash:\s*(\S+)", block)
                u_m = re.search(r"Infringing URL:\s*(\S+)", block)
                if h_m:
                    h = h_m.group(1)
                    url = u_m.group(1) if u_m else ""
                    hash_urls.setdefault(h, set())
                    if url:
                        hash_urls[h].add(url)

        # ── Collect watchlist IPs ──
        watchlist_ips: set[str] = set()
        for fp in sorted(glob.glob(os.path.join(ws, "ip_watchlist_*.csv"))):
            with open(fp) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    watchlist_ips.add(row["ip_address"])

        # ── Match fingerprints to lectures in DB ──
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        results = []
        for h, urls in hash_urls.items():
            row = conn.execute(
                "SELECT * FROM lectures WHERE content_hash = ?", (h,)
            ).fetchone()
            if row is None:
                continue  # noise hash
            lec = dict(row)
            lid = lec["lecture_id"]
            access_tier = lec["access_tier"]

            # Get course info
            course_row = conn.execute(
                "SELECT * FROM courses WHERE course_id = ?", (lec["course_id"],)
            ).fetchone()
            course_title = dict(course_row)["title"] if course_row else "Unknown"

            # Count unauthorized accesses
            access_rows = conn.execute(
                "SELECT a.ip_address, s.subscription_tier "
                "FROM access_logs a JOIN students s ON a.student_id = s.student_id "
                "WHERE a.lecture_id = ?",
                (lid,),
            ).fetchall()
            unauth_count = 0
            ip_hit_set: set[str] = set()
            for ar in access_rows:
                stu_tier = ar["subscription_tier"]
                if access_tier not in tier_rules.get(stu_tier, []):
                    unauth_count += 1
                if ar["ip_address"] in watchlist_ips:
                    ip_hit_set.add(ar["ip_address"])

            # Also count watchlist IPs from download records
            dl_rows = conn.execute(
                "SELECT ip_address FROM download_records WHERE lecture_id = ?",
                (lid,),
            ).fetchall()
            for dr in dl_rows:
                if dr["ip_address"] in watchlist_ips:
                    ip_hit_set.add(dr["ip_address"])

            ip_hits = len(ip_hit_set)
            num_ext = len(urls)
            raw = num_ext * w_ext + unauth_count * w_unauth + ip_hits * w_ip
            mult = tier_mult.get(access_tier, 1.0)
            score = round(raw * mult, 2)

            if score < min_score:
                continue

            # Determine priority
            if score >= pri_thresh["critical"]:
                pri = "critical"
            elif score >= pri_thresh["high"]:
                pri = "high"
            else:
                pri = "medium"

            results.append({
                "lecture_id": lid,
                "lecture_title": lec["title"],
                "course_title": course_title,
                "access_tier": access_tier,
                "piracy_score": score,
                "priority_level": pri,
                "num_external_sources": num_ext,
                "external_urls": ";".join(sorted(urls)),
                "unauthorized_access_count": unauth_count,
                "watchlist_ip_hits": ip_hits,
                "recommended_action": pri_actions[pri],
            })

        conn.close()

        # Sort: piracy_score desc, lecture_id asc
        results.sort(key=lambda r: (-r["piracy_score"], r["lecture_id"]))
        # Assign ranks
        for i, r in enumerate(results, start=1):
            r["rank"] = i
        return results

    # ──────────────────────────────────────────
    # step — evaluation
    # ──────────────────────────────────────────

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        gt = self._compute_ground_truth()
        gt_ids = {r["lecture_id"] for r in gt}
        gt_map = {r["lecture_id"]: r for r in gt}

        criteria: dict[str, dict] = {}
        max_total = 0

        # ── Criterion 1: takedown_list.csv exists with correct columns (10 pts) ──
        csv_path = os.path.join(self.workspace, "takedown_list.csv")
        expected_cols = [
            "rank", "lecture_id", "lecture_title", "course_title", "access_tier",
            "piracy_score", "priority_level", "num_external_sources",
            "external_urls", "unauthorized_access_count", "watchlist_ip_hits",
            "recommended_action",
        ]
        c1_max = 10
        max_total += c1_max
        agent_rows = []
        if os.path.isfile(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    actual_cols = reader.fieldnames or []
                    agent_rows = list(reader)
                if set(expected_cols).issubset(set(actual_cols)):
                    criteria["file_format"] = {"passed": True, "score": c1_max, "max_score": c1_max}
                else:
                    missing = set(expected_cols) - set(actual_cols)
                    criteria["file_format"] = {
                        "passed": False, "score": 4, "max_score": c1_max,
                        "reason": f"Missing columns: {missing}",
                    }
            except Exception as e:
                criteria["file_format"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"CSV parse error: {e}",
                }
        else:
            criteria["file_format"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "takedown_list.csv not found",
            }

        # Parse agent rows into a dict keyed by lecture_id
        agent_map: dict[int, dict] = {}
        for ar in agent_rows:
            try:
                lid = int(ar.get("lecture_id", -1))
                agent_map[lid] = ar
            except (ValueError, TypeError):
                pass
        agent_ids = set(agent_map.keys())

        # ── Criterion 2: Correct set of lecture IDs (20 pts) ──
        c2_max = 20
        max_total += c2_max
        if gt_ids and agent_ids:
            jaccard = len(gt_ids & agent_ids) / len(gt_ids | agent_ids)
            c2_score = round(c2_max * jaccard, 1)
            criteria["lecture_ids"] = {
                "passed": jaccard == 1.0,
                "score": c2_score,
                "max_score": c2_max,
                "reason": (
                    None if jaccard == 1.0
                    else f"Missing {gt_ids - agent_ids}, extra {agent_ids - gt_ids}"
                ),
            }
        elif not gt_ids and not agent_ids:
            criteria["lecture_ids"] = {"passed": True, "score": c2_max, "max_score": c2_max}
        else:
            criteria["lecture_ids"] = {
                "passed": False, "score": 0, "max_score": c2_max,
                "reason": f"Expected {len(gt_ids)} lectures, got {len(agent_ids)}",
            }

        # ── Criterion 3: Piracy scores accuracy (20 pts) ──
        c3_max = 20
        max_total += c3_max
        if gt_ids:
            common = gt_ids & agent_ids
            correct = 0
            for lid in common:
                try:
                    agent_score = float(agent_map[lid].get("piracy_score", -1))
                except (ValueError, TypeError):
                    continue
                if abs(agent_score - gt_map[lid]["piracy_score"]) < 0.01:
                    correct += 1
            ratio = correct / len(gt_ids) if gt_ids else 0
            c3_score = round(c3_max * ratio, 1)
            criteria["piracy_scores"] = {
                "passed": ratio == 1.0,
                "score": c3_score,
                "max_score": c3_max,
                "reason": None if ratio == 1.0 else f"{correct}/{len(gt_ids)} scores correct",
            }
        else:
            criteria["piracy_scores"] = {"passed": True, "score": c3_max, "max_score": c3_max}

        # ── Criterion 4: Correct ranking order (15 pts) ──
        c4_max = 15
        max_total += c4_max
        if agent_rows and gt:
            agent_order = []
            for ar in agent_rows:
                try:
                    agent_order.append(int(ar.get("lecture_id", -1)))
                except (ValueError, TypeError):
                    agent_order.append(-1)
            gt_order = [r["lecture_id"] for r in gt]
            if agent_order == gt_order:
                criteria["ranking_order"] = {"passed": True, "score": c4_max, "max_score": c4_max}
            else:
                # partial credit: Kendall tau-like measure
                matched = [lid for lid in agent_order if lid in gt_ids]
                if len(matched) >= 2:
                    gt_rank = {lid: i for i, lid in enumerate(gt_order)}
                    concordant = 0
                    total_pairs = 0
                    for i in range(len(matched)):
                        for j in range(i + 1, len(matched)):
                            total_pairs += 1
                            if (gt_rank.get(matched[i], 0) < gt_rank.get(matched[j], 0)):
                                concordant += 1
                    ratio = concordant / total_pairs if total_pairs else 0
                    c4_score = round(c4_max * ratio, 1)
                else:
                    c4_score = 0
                criteria["ranking_order"] = {
                    "passed": False,
                    "score": c4_score,
                    "max_score": c4_max,
                    "reason": "Incorrect ranking order",
                }
        else:
            criteria["ranking_order"] = {
                "passed": False, "score": 0, "max_score": c4_max,
                "reason": "No rows to compare",
            }

        # ── Criterion 5: Correct priority levels (10 pts) ──
        c5_max = 10
        max_total += c5_max
        if gt_ids:
            common = gt_ids & agent_ids
            correct = sum(
                1
                for lid in common
                if agent_map[lid].get("priority_level", "").strip() == gt_map[lid]["priority_level"]
            )
            ratio = correct / len(gt_ids) if gt_ids else 0
            c5_score = round(c5_max * ratio, 1)
            criteria["priority_levels"] = {
                "passed": ratio == 1.0,
                "score": c5_score,
                "max_score": c5_max,
                "reason": None if ratio == 1.0 else f"{correct}/{len(gt_ids)} correct",
            }
        else:
            criteria["priority_levels"] = {"passed": True, "score": c5_max, "max_score": c5_max}

        # ── Criterion 6: Correct unauthorized access counts (15 pts) ──
        c6_max = 15
        max_total += c6_max
        if gt_ids:
            common = gt_ids & agent_ids
            correct = 0
            for lid in common:
                try:
                    agent_val = int(agent_map[lid].get("unauthorized_access_count", -1))
                except (ValueError, TypeError):
                    continue
                if agent_val == gt_map[lid]["unauthorized_access_count"]:
                    correct += 1
            ratio = correct / len(gt_ids) if gt_ids else 0
            c6_score = round(c6_max * ratio, 1)
            criteria["unauthorized_counts"] = {
                "passed": ratio == 1.0,
                "score": c6_score,
                "max_score": c6_max,
                "reason": None if ratio == 1.0 else f"{correct}/{len(gt_ids)} correct",
            }
        else:
            criteria["unauthorized_counts"] = {"passed": True, "score": c6_max, "max_score": c6_max}

        # ── Criterion 7: Response summary accuracy (10 pts) ──
        c7_max = 10
        max_total += c7_max
        gt_total = len(gt)
        gt_critical = sum(1 for r in gt if r["priority_level"] == "critical")
        gt_high = sum(1 for r in gt if r["priority_level"] == "high")
        gt_medium = sum(1 for r in gt if r["priority_level"] == "medium")

        c7_score = 0
        # Check for total count in response
        total_pat = re.search(r"Total pirated lectures requiring action:\s*(\d+)", action)
        if total_pat and int(total_pat.group(1)) == gt_total:
            c7_score += 4
        crit_pat = re.search(r"Critical priority:\s*(\d+)", action)
        if crit_pat and int(crit_pat.group(1)) == gt_critical:
            c7_score += 2
        high_pat = re.search(r"High priority:\s*(\d+)", action)
        if high_pat and int(high_pat.group(1)) == gt_high:
            c7_score += 2
        med_pat = re.search(r"Medium priority:\s*(\d+)", action)
        if med_pat and int(med_pat.group(1)) == gt_medium:
            c7_score += 2
        criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": None if c7_score == c7_max else "Some summary counts missing or incorrect",
        }

        # ── Criterion 8: external_urls are unique, joined by semicolons, sorted
        #    alphabetically (10 pts).  prompt.md specifies this format explicitly. ──
        c8_max = 10
        max_total += c8_max
        if gt_ids and agent_ids:
            common = gt_ids & agent_ids
            correct = 0
            for lid in common:
                gt_urls = gt_map[lid]["external_urls"]   # already sorted in ground truth
                agent_urls = agent_map[lid].get("external_urls", "")
                if agent_urls.strip() == gt_urls:
                    correct += 1
            ratio = correct / len(gt_ids) if gt_ids else 0
            c8_score = round(c8_max * ratio, 1)
            criteria["external_urls"] = {
                "passed": ratio == 1.0,
                "score": c8_score,
                "max_score": c8_max,
                "reason": None if ratio == 1.0 else f"{correct}/{len(gt_ids)} rows have correct sorted URLs",
            }
        elif not gt_ids and not agent_ids:
            criteria["external_urls"] = {"passed": True, "score": c8_max, "max_score": c8_max}
        else:
            criteria["external_urls"] = {
                "passed": False, "score": 0, "max_score": c8_max,
                "reason": "No matching lecture rows to compare",
            }

        total_score = sum(c["score"] for c in criteria.values())
        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_total,
        }
        return total_score / max_total if max_total > 0 else 0.0, info

    # ──────────────────────────────────────────
    # verify — self-test using only tools + workspace
    # ──────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        The hardened surface returns mixed shapes; this solver unwraps MCP
        envelopes, parses JSON strings, repr strings, and key:value text, and
        consumes the unbounded bulk export once, in memory (filtering rather
        than echoing it).
        """
        ws = self.workspace
        tool_calls = 0

        def _is_error(resp) -> bool:
            return isinstance(resp, dict) and resp.get("object") == "error"

        def _kv_parse(text: str) -> dict:
            out = {}
            for line in text.splitlines():
                k, _, v = line.partition(": ")
                try:
                    out[k] = int(v)
                except ValueError:
                    try:
                        out[k] = float(v)
                    except ValueError:
                        out[k] = v
            return out

        # ── 1. Load config files ──
        with open(os.path.join(ws, "piracy_policy.yaml")) as f:
            policy = yaml.safe_load(f)["scoring"]
        with open(os.path.join(ws, "tier_access_rules.json")) as f:
            tier_rules = json.load(f)

        weights = policy["weights"]
        w_ext = weights["external_source"]
        w_unauth = weights["unauthorized_access"]
        w_ip = weights["watchlist_ip_hit"]
        tier_mult = policy["tier_multipliers"]
        pri_thresh = policy["priority_thresholds"]
        pri_actions = policy["priority_actions"]
        min_score = policy["min_piracy_score"]

        # ── 2. Collect fingerprints + external URLs from scan reports ──
        hash_urls: dict[str, set[str]] = {}
        for fp in sorted(glob.glob(os.path.join(ws, "scan_report_*.json"))):
            with open(fp) as f:
                report = json.load(f)
            for finding in report.get("findings", []):
                h = finding["content_fingerprint"]
                url = finding["external_url"]
                hash_urls.setdefault(h, set()).add(url)

        # ── 3. Collect fingerprints + URLs from DMCA complaints ──
        for fp in sorted(glob.glob(os.path.join(ws, "dmca_complaint_*.txt"))):
            with open(fp) as f:
                text = f.read()
            for block in re.split(r"=== DMCA Notice .+? ===", text):
                block = block.strip()
                if not block:
                    continue
                h_m = re.search(r"Content Hash:\s*(\S+)", block)
                u_m = re.search(r"Infringing URL:\s*(\S+)", block)
                if h_m:
                    h = h_m.group(1)
                    url = u_m.group(1) if u_m else ""
                    hash_urls.setdefault(h, set())
                    if url:
                        hash_urls[h].add(url)

        # ── 4. Collect watchlist IPs ──
        watchlist_ips: set[str] = set()
        for fp in sorted(glob.glob(os.path.join(ws, "ip_watchlist_*.csv"))):
            with open(fp) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    watchlist_ips.add(row["ip_address"])

        # ── 5. Match fingerprints to lectures via tools ──
        # find_lecture_by_hash returns an MCP envelope on success and an
        # error object (404) for noise hashes.
        lecture_data: dict[int, dict] = {}  # lecture_id -> lecture record
        hash_to_lid: dict[str, int] = {}
        for h in hash_urls:
            resp = self.tools["find_lecture_by_hash"](content_hash=h)
            tool_calls += 1
            if _is_error(resp):
                continue  # noise hash — no matching lecture
            match = json.loads(resp["content"][0]["text"])["match"]
            lid = match["lecture_id"]
            lecture_data[lid] = match
            hash_to_lid[h] = lid

        # ── 6. Aggregate external URLs per lecture ──
        lecture_urls: dict[int, set[str]] = {}
        for h, urls in hash_urls.items():
            lid = hash_to_lid.get(h)
            if lid is None:
                continue
            lecture_urls.setdefault(lid, set()).update(urls)

        # ── 7. Pull the bulk activity export ONCE and index it in memory.
        # This response is far too large to echo at scale; consume it
        # programmatically and keep only per-lecture aggregates. ──
        raw = self.tools["export_platform_activity"]()
        tool_calls += 1
        export = json.loads(raw)
        access_by_lecture: dict[int, list[dict]] = {}
        downloads_by_lecture: dict[int, list[dict]] = {}
        for ev in export["events"]:
            if ev["kind"] == "access":
                access_by_lecture.setdefault(ev["lecture_id"], []).append(ev)
            else:
                downloads_by_lecture.setdefault(ev["lecture_id"], []).append(ev)

        # Cross-check the export against per-entity tools on one sample
        # lecture: paginated access logs (JSON string) + downloads (envelope)
        # + one student record (key:value text).
        if lecture_data:
            sample_lid = sorted(lecture_data.keys())[0]
            sample_logs = []
            page = 1
            while True:
                resp_raw = self.tools["query_access_logs"](
                    lecture_id=sample_lid, page=page, page_size=50
                )
                tool_calls += 1
                resp = json.loads(resp_raw)
                sample_logs.extend(resp["logs"])
                if page * 50 >= resp["total"]:
                    break
                page += 1
            assert len(sample_logs) == len(access_by_lecture.get(sample_lid, []))

            dl_env = self.tools["query_downloads"](
                lecture_id=sample_lid, page=1, page_size=50
            )
            tool_calls += 1
            dl_payload = json.loads(dl_env["content"][0]["text"])
            assert dl_payload["total"] == len(downloads_by_lecture.get(sample_lid, []))

            if sample_logs:
                stu_text = self.tools["get_student"](
                    student_id=sample_logs[0]["student_id"]
                )
                tool_calls += 1
                stu = _kv_parse(stu_text)
                assert stu["student_id"] == sample_logs[0]["student_id"]

        # ── 8. For each pirated lecture, compute signals from the export ──
        course_cache: dict[int, dict] = {}

        results = []
        for lid in sorted(lecture_data.keys()):
            lec = lecture_data[lid]
            access_tier = lec["access_tier"]
            course_id = lec["course_id"]

            # Get course title (Python-repr string return)
            if course_id not in course_cache:
                course_raw = self.tools["get_course"](course_id=course_id)
                tool_calls += 1
                course_cache[course_id] = (
                    {} if _is_error(course_raw) else ast.literal_eval(course_raw)
                )
            course_title = course_cache[course_id].get("title", "Unknown")

            # Count unauthorized accesses + watchlist IPs from the export
            unauth_count = 0
            ip_hits: set[str] = set()
            for ev in access_by_lecture.get(lid, []):
                allowed = tier_rules.get(ev["tier"], [])
                if access_tier not in allowed:
                    unauth_count += 1
                if ev["ip"] in watchlist_ips:
                    ip_hits.add(ev["ip"])
            for ev in downloads_by_lecture.get(lid, []):
                if ev["ip"] in watchlist_ips:
                    ip_hits.add(ev["ip"])

            ip_hit_count = len(ip_hits)
            num_ext = len(lecture_urls.get(lid, set()))
            raw_score = num_ext * w_ext + unauth_count * w_unauth + ip_hit_count * w_ip
            mult = tier_mult.get(access_tier, 1.0)
            score = round(raw_score * mult, 2)

            if score < min_score:
                continue

            if score >= pri_thresh["critical"]:
                pri = "critical"
            elif score >= pri_thresh["high"]:
                pri = "high"
            else:
                pri = "medium"

            results.append({
                "lecture_id": lid,
                "lecture_title": lec["title"],
                "course_title": course_title,
                "access_tier": access_tier,
                "piracy_score": score,
                "priority_level": pri,
                "num_external_sources": num_ext,
                "external_urls": ";".join(sorted(lecture_urls.get(lid, set()))),
                "unauthorized_access_count": unauth_count,
                "watchlist_ip_hits": ip_hit_count,
                "recommended_action": pri_actions[pri],
            })

        # Sort: piracy_score desc, lecture_id asc
        results.sort(key=lambda r: (-r["piracy_score"], r["lecture_id"]))
        for i, r in enumerate(results, start=1):
            r["rank"] = i

        # ── 9. Write takedown_list.csv ──
        csv_path = os.path.join(ws, "takedown_list.csv")
        fieldnames = [
            "rank", "lecture_id", "lecture_title", "course_title", "access_tier",
            "piracy_score", "priority_level", "num_external_sources",
            "external_urls", "unauthorized_access_count", "watchlist_ip_hits",
            "recommended_action",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow({k: r[k] for k in fieldnames})

        # ── 10. Build response string ──
        n_crit = sum(1 for r in results if r["priority_level"] == "critical")
        n_high = sum(1 for r in results if r["priority_level"] == "high")
        n_med = sum(1 for r in results if r["priority_level"] == "medium")
        action = (
            f"Total pirated lectures requiring action: {len(results)}\n"
            f"Critical priority: {n_crit}\n"
            f"High priority: {n_high}\n"
            f"Medium priority: {n_med}\n"
        )

        print(f"[verify] tool_calls={tool_calls}")
        return self.step(action)
