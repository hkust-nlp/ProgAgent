"""
Environment for manuscript originality verification task.
Provides tools for querying manuscript data and evaluates plagiarism review output.
"""
import os
import json
import csv
import sqlite3
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
        description=(
            "List manuscripts that are currently pending originality review. "
            "Returns a paginated list of manuscript summaries."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 5, max 20).",
                },
            },
            "required": ["page"],
        },
    )
    def list_pending_manuscripts(self, page: int, page_size: int = 5) -> List[Dict]:
        page_size = max(1, min(int(page_size), 20))
        page = max(1, int(page))
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT manuscript_id, title, discipline, submission_date "
            "FROM manuscripts WHERE status = 'pending_review' "
            "ORDER BY manuscript_id ASC LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @tool(
        description=(
            "Retrieve detailed metadata for a single manuscript by its ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "manuscript_id": {
                    "type": "string",
                    "description": "Manuscript identifier, e.g. MS-0001.",
                },
            },
            "required": ["manuscript_id"],
        },
    )
    def get_manuscript_info(self, manuscript_id: str) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT manuscript_id, title, authors, abstract, discipline, "
            "submission_date, status FROM manuscripts WHERE manuscript_id = ?",
            (manuscript_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Manuscript {manuscript_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Find articles from open-access repositories that have been "
            "identified as similar to a given manuscript. Returns similarity "
            "component scores for each match, sorted by overall similarity "
            "descending. Results are paginated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "manuscript_id": {
                    "type": "string",
                    "description": "Manuscript identifier.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 10, max 20).",
                },
            },
            "required": ["manuscript_id"],
        },
    )
    def find_similar_repository_articles(
        self, manuscript_id: str, page: int = 1, page_size: int = 10
    ) -> List[Dict]:
        page_size = max(1, min(int(page_size), 20))
        page = max(1, int(page))
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT s.article_id, r.title, r.repository, "
            "s.text_similarity, s.citation_overlap, s.structural_similarity "
            "FROM similarity_results s "
            "JOIN repository_articles r ON s.article_id = r.article_id "
            "WHERE s.manuscript_id = ? AND s.source = 'repository' "
            "ORDER BY (s.text_similarity + s.citation_overlap + s.structural_similarity) DESC "
            "LIMIT ? OFFSET ?",
            (manuscript_id, page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @tool(
        description=(
            "Find articles from preprint servers that have been identified as "
            "similar to a given manuscript. Returns similarity component scores "
            "for each match, sorted by overall similarity descending. Results "
            "are paginated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "manuscript_id": {
                    "type": "string",
                    "description": "Manuscript identifier.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 10, max 20).",
                },
            },
            "required": ["manuscript_id"],
        },
    )
    def find_similar_preprint_articles(
        self, manuscript_id: str, page: int = 1, page_size: int = 10
    ) -> List[Dict]:
        page_size = max(1, min(int(page_size), 20))
        page = max(1, int(page))
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT s.article_id, p.title, p.server, "
            "s.text_similarity, s.citation_overlap, s.structural_similarity "
            "FROM similarity_results s "
            "JOIN preprint_articles p ON s.article_id = p.article_id "
            "WHERE s.manuscript_id = ? AND s.source = 'preprint' "
            "ORDER BY (s.text_similarity + s.citation_overlap + s.structural_similarity) DESC "
            "LIMIT ? OFFSET ?",
            (manuscript_id, page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @tool(
        description=(
            "Check whether a specific author name appears on the retraction "
            "watchlist. Returns all matching entries for the given name."
        ),
        parameters={
            "type": "object",
            "properties": {
                "author_name": {
                    "type": "string",
                    "description": "Full name of the author to look up.",
                },
            },
            "required": ["author_name"],
        },
    )
    def check_retraction_watchlist(self, author_name: str) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT author_name, original_paper_title, retraction_date, "
            "reason, severity FROM retraction_watchlist "
            "WHERE author_name = ?",
            (author_name,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @tool(
        description=(
            "Retrieve full metadata for a specific article from either the "
            "open-access repository collection or the preprint server "
            "collection."
        ),
        parameters={
            "type": "object",
            "properties": {
                "article_id": {
                    "type": "string",
                    "description": "Article identifier, e.g. OA-0001 or PP-0015.",
                },
                "source": {
                    "type": "string",
                    "enum": ["repository", "preprint"],
                    "description": "Which collection the article belongs to.",
                },
            },
            "required": ["article_id", "source"],
        },
    )
    def get_article_details(self, article_id: str, source: str) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if source == "repository":
            cur.execute(
                "SELECT * FROM repository_articles WHERE article_id = ?",
                (article_id,),
            )
        elif source == "preprint":
            cur.execute(
                "SELECT * FROM preprint_articles WHERE article_id = ?",
                (article_id,),
            )
        else:
            conn.close()
            return {"error": f"Unknown source '{source}'. Use 'repository' or 'preprint'."}
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Article {article_id} not found in {source}."}
        return dict(row)

    # ------------------------------------------------------------------
    # Ground-truth computation (used by both step and verify)
    # ------------------------------------------------------------------

    def _compute_ground_truth(self) -> List[Dict]:
        """Compute expected results for all pending manuscripts using DB + workspace."""
        import yaml

        # Read config files
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "discipline_adjustments.json")) as f:
            disc_adj = json.load(f)

        w_text = config["weights"]["text_similarity"]
        w_cit = config["weights"]["citation_overlap"]
        w_str = config["weights"]["structural_similarity"]
        threshold = config["flagging_threshold"]
        retract_pen = config["retraction_penalties"]
        max_articles = config["max_articles_considered"]
        discount = config["declared_source_discount"]

        severity_rank = {"high": 3, "medium": 2, "low": 1}

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get all pending manuscripts
        cur = conn.cursor()
        cur.execute(
            "SELECT manuscript_id, title, authors, discipline, submission_date "
            "FROM manuscripts WHERE status = 'pending_review' ORDER BY manuscript_id"
        )
        pending = [dict(r) for r in cur.fetchall()]

        results = []
        for m in pending:
            mid = m["manuscript_id"]
            discipline = m["discipline"]
            authors = [a.strip() for a in m["authors"].split(",")]

            # Read declared sources from submission file
            declared_sources = []
            sub_path = os.path.join(self.workspace, f"submission_{mid}.txt")
            if os.path.exists(sub_path):
                with open(sub_path) as f:
                    for line in f:
                        if line.startswith("DECLARED_SOURCES:"):
                            val = line.split(":", 1)[1].strip()
                            if val != "NONE":
                                declared_sources = [s.strip() for s in val.split(",")]
                            break

            # Get all similarity matches
            cur.execute(
                "SELECT article_id, source, text_similarity, citation_overlap, "
                "structural_similarity FROM similarity_results WHERE manuscript_id = ?",
                (mid,),
            )
            matches = [dict(r) for r in cur.fetchall()]

            # Compute match scores
            scored_matches = []
            for match in matches:
                score = (
                    w_text * match["text_similarity"]
                    + w_cit * match["citation_overlap"]
                    + w_str * match["structural_similarity"]
                )
                if match["article_id"] in declared_sources:
                    score *= discount
                scored_matches.append({
                    "article_id": match["article_id"],
                    "source": match["source"],
                    "match_score": score,
                })

            # Top N
            scored_matches.sort(key=lambda x: x["match_score"], reverse=True)
            top = scored_matches[:max_articles]
            composite_base = sum(x["match_score"] for x in top) / len(top) if top else 0.0
            disc_adjusted = composite_base * disc_adj.get(discipline, 1.0)

            # Retraction penalties
            total_retract = 0.0
            retraction_flags = []
            for author in authors:
                cur.execute(
                    "SELECT severity FROM retraction_watchlist WHERE author_name = ?",
                    (author,),
                )
                entries = cur.fetchall()
                if entries:
                    best = max(entries, key=lambda e: severity_rank.get(e["severity"], 0))
                    pen = retract_pen.get(best["severity"], 0.0)
                    total_retract += pen
                    retraction_flags.append({
                        "author": author,
                        "severity": best["severity"],
                    })

            final_score = min(1.0, disc_adjusted + total_retract)
            flag_status = "FLAGGED" if final_score >= threshold else "CLEAR"

            if flag_status == "FLAGGED":
                if final_score >= 0.85:
                    severity_cat = "Critical"
                elif final_score >= 0.75:
                    severity_cat = "High"
                else:
                    severity_cat = "Moderate"
            else:
                severity_cat = ""

            results.append({
                "manuscript_id": mid,
                "title": m["title"],
                "authors": m["authors"],
                "discipline": discipline,
                "submission_date": m["submission_date"],
                "composite_base_score": round(composite_base, 4),
                "discipline_adjusted_score": round(disc_adjusted, 4),
                "retraction_penalty": round(total_retract, 4),
                "final_risk_score": round(final_score, 4),
                "flag_status": flag_status,
                "severity_category": severity_cat,
                "top_matching_articles": [
                    {
                        "article_id": x["article_id"],
                        "source": x["source"],
                        "match_score": round(x["match_score"], 4),
                    }
                    for x in top
                ],
                "retraction_flags": retraction_flags,
            })

        conn.close()
        return results

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

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
        gt_by_id = {r["manuscript_id"]: r for r in gt}
        gt_flagged = [r for r in gt if r["flag_status"] == "FLAGGED"]
        gt_flagged_sorted = sorted(
            gt_flagged,
            key=lambda x: (-round(x["final_risk_score"], 2), x["submission_date"], x["manuscript_id"]),
        )

        criteria = {}
        score_tol = 0.006  # tolerance for score comparison

        # ---- Criterion 1: originality_report.csv structure (15 pts) ----
        report_path = os.path.join(self.workspace, "originality_report.csv")
        c1_score = 0
        c1_max = 15
        report_rows = []
        expected_cols = [
            "manuscript_id", "title", "discipline", "submission_date",
            "composite_base_score", "discipline_adjusted_score",
            "retraction_penalty", "final_risk_score", "flag_status",
        ]
        c1_reason = ""
        if os.path.exists(report_path):
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    headers = reader.fieldnames or []
                    report_rows = list(reader)
                # Check columns present
                missing_cols = [c for c in expected_cols if c not in headers]
                if not missing_cols:
                    c1_score += 5
                else:
                    c1_reason = f"Missing columns: {missing_cols}"
                # Check row count
                if len(report_rows) == len(gt):
                    c1_score += 5
                else:
                    c1_reason += f" Expected {len(gt)} rows, got {len(report_rows)}."
                # Check all manuscript IDs present
                report_ids = {r.get("manuscript_id", "") for r in report_rows}
                gt_ids = {r["manuscript_id"] for r in gt}
                if report_ids == gt_ids:
                    c1_score += 5
                else:
                    c1_reason += f" ID mismatch."
            except Exception as e:
                c1_reason = f"Error reading CSV: {e}"
        else:
            c1_reason = "originality_report.csv not found."

        criteria["report_structure"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": c1_reason if c1_score < c1_max else "",
        }

        # ---- Criterion 2: Risk score accuracy (25 pts) ----
        c2_score = 0
        c2_max = 25
        c2_reason = ""
        if report_rows:
            report_by_id = {r["manuscript_id"]: r for r in report_rows}
            correct_scores = 0
            total_checked = 0
            for mid, expected in gt_by_id.items():
                if mid in report_by_id:
                    total_checked += 1
                    try:
                        agent_score = float(report_by_id[mid].get("final_risk_score", -1))
                        if abs(agent_score - expected["final_risk_score"]) <= score_tol:
                            correct_scores += 1
                    except (ValueError, TypeError):
                        pass
            if total_checked > 0:
                ratio = correct_scores / total_checked
                c2_score = round(ratio * c2_max)
                if ratio < 1.0:
                    c2_reason = f"{correct_scores}/{total_checked} scores within tolerance."
            else:
                c2_reason = "No matching manuscript IDs found in report."
        else:
            c2_reason = "No report rows to evaluate."

        criteria["risk_score_accuracy"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": c2_reason if c2_score < c2_max else "",
        }

        # ---- Criterion 3: Flag status correctness (20 pts) ----
        c3_score = 0
        c3_max = 20
        c3_reason = ""
        if report_rows:
            report_by_id = {r["manuscript_id"]: r for r in report_rows}
            correct_flags = 0
            total_checked = 0
            for mid, expected in gt_by_id.items():
                if mid in report_by_id:
                    total_checked += 1
                    agent_flag = report_by_id[mid].get("flag_status", "").strip().upper()
                    if agent_flag == expected["flag_status"]:
                        correct_flags += 1
            if total_checked > 0:
                ratio = correct_flags / total_checked
                c3_score = round(ratio * c3_max)
                if ratio < 1.0:
                    c3_reason = f"{correct_flags}/{total_checked} flag statuses correct."
            else:
                c3_reason = "No matching IDs."
        else:
            c3_reason = "No report rows."

        criteria["flag_status_correctness"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": c3_reason if c3_score < c3_max else "",
        }

        # ---- Criterion 4: flagged_cases.json completeness & severity (20 pts) ----
        c4_score = 0
        c4_max = 20
        c4_reason = ""
        flagged_path = os.path.join(self.workspace, "flagged_cases.json")
        flagged_data = []
        if os.path.exists(flagged_path):
            try:
                with open(flagged_path) as f:
                    flagged_data = json.load(f)
                if not isinstance(flagged_data, list):
                    c4_reason = "flagged_cases.json should be a JSON array."
                else:
                    # Check correct set of flagged IDs
                    agent_flagged_ids = {e.get("manuscript_id", "") for e in flagged_data}
                    gt_flagged_ids = {r["manuscript_id"] for r in gt_flagged}
                    if agent_flagged_ids == gt_flagged_ids:
                        c4_score += 10
                    else:
                        missing = gt_flagged_ids - agent_flagged_ids
                        extra = agent_flagged_ids - gt_flagged_ids
                        c4_reason = f"Flagged ID mismatch. Missing: {missing}, Extra: {extra}."
                    # Check severity categories
                    gt_sev = {r["manuscript_id"]: r["severity_category"] for r in gt_flagged}
                    correct_sev = 0
                    for entry in flagged_data:
                        mid = entry.get("manuscript_id", "")
                        if mid in gt_sev and entry.get("severity_category", "") == gt_sev[mid]:
                            correct_sev += 1
                    if len(gt_flagged) > 0:
                        ratio = correct_sev / len(gt_flagged)
                        c4_score += round(ratio * 10)
                        if ratio < 1.0:
                            c4_reason += f" {correct_sev}/{len(gt_flagged)} severity categories correct."
                    else:
                        c4_score += 10  # no flagged, trivially correct
            except Exception as e:
                c4_reason = f"Error reading flagged_cases.json: {e}"
        else:
            c4_reason = "flagged_cases.json not found."

        criteria["flagged_cases_completeness"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": c4_reason if c4_score < c4_max else "",
        }

        # ---- Criterion 5: flagged_cases.json ordering (10 pts) ----
        c5_score = 0
        c5_max = 10
        c5_reason = ""
        if flagged_data and len(flagged_data) > 1:
            agent_order = [e.get("manuscript_id", "") for e in flagged_data]
            gt_order = [r["manuscript_id"] for r in gt_flagged_sorted]
            if agent_order == gt_order:
                c5_score = c5_max
            else:
                c5_reason = f"Expected order {gt_order}, got {agent_order}."
        elif len(gt_flagged) <= 1:
            c5_score = c5_max  # trivially correct
        else:
            c5_reason = "No flagged data to check ordering."

        criteria["flagged_cases_ordering"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": c5_reason if c5_score < c5_max else "",
        }

        # ---- Criterion 6: Response summary (10 pts) ----
        c6_score = 0
        c6_max = 10
        c6_reason = ""
        if action:
            action_upper = action.upper()
            # Check total count
            total_str = str(len(gt))
            if total_str in action:
                c6_score += 3
            else:
                c6_reason += f"Expected total count {total_str} in response. "
            # Check flagged count
            flagged_count_str = str(len(gt_flagged))
            if flagged_count_str in action:
                c6_score += 3
            else:
                c6_reason += f"Expected flagged count {flagged_count_str}. "
            # Check all flagged manuscript IDs appear in response
            all_present = all(r["manuscript_id"] in action for r in gt_flagged)
            if all_present:
                c6_score += 4
            else:
                missing_in_resp = [r["manuscript_id"] for r in gt_flagged if r["manuscript_id"] not in action]
                c6_reason += f"Missing flagged IDs in response: {missing_in_resp}."
        else:
            c6_reason = "Empty response."

        criteria["response_summary"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": c6_reason if c6_score < c6_max else "",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score if max_score > 0 else 0.0, info

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
        import yaml

        # ----- Read workspace config files -----
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "discipline_adjustments.json")) as f:
            disc_adj = json.load(f)

        w_text = config["weights"]["text_similarity"]
        w_cit = config["weights"]["citation_overlap"]
        w_str = config["weights"]["structural_similarity"]
        threshold = config["flagging_threshold"]
        retract_pen = config["retraction_penalties"]
        max_articles = config["max_articles_considered"]
        discount = config["declared_source_discount"]

        severity_rank = {"high": 3, "medium": 2, "low": 1}

        # ----- List all pending manuscripts via tool -----
        all_pending = []
        page = 1
        while True:
            batch = self.tools["list_pending_manuscripts"](page=page, page_size=20)
            if not batch:
                break
            all_pending.extend(batch)
            if len(batch) < 20:
                break
            page += 1

        # ----- Process each manuscript -----
        report_rows = []
        flagged_cases = []
        tool_call_count = 0

        for m_summary in all_pending:
            mid = m_summary["manuscript_id"]

            # Get manuscript details via tool
            info = self.tools["get_manuscript_info"](manuscript_id=mid)
            tool_call_count += 1
            authors = [a.strip() for a in info["authors"].split(",")]
            discipline = info["discipline"]

            # Read submission file for declared sources
            sub_path = os.path.join(self.workspace, f"submission_{mid}.txt")
            declared_sources = []
            if os.path.exists(sub_path):
                with open(sub_path) as f:
                    for line in f:
                        if line.startswith("DECLARED_SOURCES:"):
                            val = line.split(":", 1)[1].strip()
                            if val != "NONE":
                                declared_sources = [s.strip() for s in val.split(",")]
                            break

            # Find similar repository articles via tool
            repo_matches = self.tools["find_similar_repository_articles"](
                manuscript_id=mid, page=1, page_size=20
            )
            tool_call_count += 1

            # Find similar preprint articles via tool
            preprint_matches = self.tools["find_similar_preprint_articles"](
                manuscript_id=mid, page=1, page_size=20
            )
            tool_call_count += 1

            # Compute match scores
            all_scored = []
            for match in (repo_matches or []):
                score = (
                    w_text * match["text_similarity"]
                    + w_cit * match["citation_overlap"]
                    + w_str * match["structural_similarity"]
                )
                if match["article_id"] in declared_sources:
                    score *= discount
                all_scored.append({
                    "article_id": match["article_id"],
                    "source": "repository",
                    "match_score": score,
                })
            for match in (preprint_matches or []):
                score = (
                    w_text * match["text_similarity"]
                    + w_cit * match["citation_overlap"]
                    + w_str * match["structural_similarity"]
                )
                if match["article_id"] in declared_sources:
                    score *= discount
                all_scored.append({
                    "article_id": match["article_id"],
                    "source": "preprint",
                    "match_score": score,
                })

            # Top N articles
            all_scored.sort(key=lambda x: x["match_score"], reverse=True)
            top = all_scored[:max_articles]
            composite_base = sum(x["match_score"] for x in top) / len(top) if top else 0.0
            disc_adjusted = composite_base * disc_adj.get(discipline, 1.0)

            # Check retraction watchlist for each author
            total_retract = 0.0
            retraction_flags = []
            for author in authors:
                entries = self.tools["check_retraction_watchlist"](author_name=author)
                tool_call_count += 1
                if entries:
                    best = max(entries, key=lambda e: severity_rank.get(e["severity"], 0))
                    pen = retract_pen.get(best["severity"], 0.0)
                    total_retract += pen
                    retraction_flags.append({
                        "author": author,
                        "severity": best["severity"],
                    })

            final_score = min(1.0, disc_adjusted + total_retract)
            flag_status = "FLAGGED" if final_score >= threshold else "CLEAR"

            report_rows.append({
                "manuscript_id": mid,
                "title": info["title"],
                "discipline": discipline,
                "submission_date": info["submission_date"],
                "composite_base_score": round(composite_base, 4),
                "discipline_adjusted_score": round(disc_adjusted, 4),
                "retraction_penalty": round(total_retract, 4),
                "final_risk_score": round(final_score, 4),
                "flag_status": flag_status,
            })

            if flag_status == "FLAGGED":
                if final_score >= 0.85:
                    severity_cat = "Critical"
                elif final_score >= 0.75:
                    severity_cat = "High"
                else:
                    severity_cat = "Moderate"

                flagged_cases.append({
                    "manuscript_id": mid,
                    "title": info["title"],
                    "authors": info["authors"],
                    "discipline": discipline,
                    "submission_date": info["submission_date"],
                    "final_risk_score": round(final_score, 4),
                    "severity_category": severity_cat,
                    "top_matching_articles": [
                        {
                            "article_id": x["article_id"],
                            "source": x["source"],
                            "match_score": round(x["match_score"], 4),
                        }
                        for x in top
                    ],
                    "retraction_flags": retraction_flags,
                })

        # tool calls from list_pending_manuscripts
        tool_call_count += page  # pages iterated

        # Sort report by manuscript_id ascending
        report_rows.sort(key=lambda x: x["manuscript_id"])

        # Sort flagged cases: score desc (rounded to 2dp), date asc, id asc
        flagged_cases.sort(
            key=lambda x: (
                -round(x["final_risk_score"], 2),
                x["submission_date"],
                x["manuscript_id"],
            )
        )

        # ----- Write deliverables -----
        csv_path = os.path.join(self.workspace, "originality_report.csv")
        fieldnames = [
            "manuscript_id", "title", "discipline", "submission_date",
            "composite_base_score", "discipline_adjusted_score",
            "retraction_penalty", "final_risk_score", "flag_status",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(report_rows)

        json_path = os.path.join(self.workspace, "flagged_cases.json")
        with open(json_path, "w") as f:
            json.dump(flagged_cases, f, indent=2)

        # ----- Construct response -----
        n_total = len(report_rows)
        n_flagged = len(flagged_cases)
        n_critical = sum(1 for c in flagged_cases if c["severity_category"] == "Critical")
        n_high = sum(1 for c in flagged_cases if c["severity_category"] == "High")
        n_moderate = sum(1 for c in flagged_cases if c["severity_category"] == "Moderate")

        lines = [
            f"Total manuscripts reviewed: {n_total}",
            f"Flagged for review: {n_flagged}",
            f"Critical: {n_critical}, High: {n_high}, Moderate: {n_moderate}",
            "",
            "Flagged manuscripts (sorted by risk score descending):",
        ]
        for c in flagged_cases:
            lines.append(
                f"  {c['manuscript_id']}: {c['final_risk_score']:.4f} ({c['severity_category']})"
            )

        action = "\n".join(lines)
        return self.step(action)
