"""
env.py – Task environment for researcher-grant matching.
"""

import os
import json
import csv
import math
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

    # ── Tool methods ──────────────────────────────────────────────

    @tool(
        description="Lists researchers with pagination. Returns a page of researcher summaries.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 10).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_researchers(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 10)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM researchers")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT id, name, institution_id, department, career_stage, primary_field, secondary_field, h_index "
            "FROM researchers ORDER BY id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "researchers": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description="Retrieves full details for a single researcher by ID.",
        parameters={
            "type": "object",
            "properties": {
                "researcher_id": {
                    "type": "integer",
                    "description": "The researcher's unique ID.",
                },
            },
            "required": ["researcher_id"],
        },
    )
    def get_researcher_details(self, researcher_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM researchers WHERE id = ?", (researcher_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Researcher {researcher_id} not found."}
        return dict(row)

    @tool(
        description="Searches funding calls with optional filters and pagination.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 10).",
                },
                "field": {
                    "type": "string",
                    "description": "Filter by primary_focus field (exact match). Optional.",
                },
                "agency": {
                    "type": "string",
                    "description": "Filter by agency name (exact match). Optional.",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def search_funding_calls(self, page: int, page_size: int, field: str = None, agency: str = None) -> dict:
        page_size = min(page_size, 10)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        where_parts = []
        params: list = []
        if field:
            where_parts.append("primary_focus = ?")
            params.append(field)
        if agency:
            where_parts.append("agency = ?")
            params.append(agency)
        where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        cur.execute(f"SELECT COUNT(*) FROM funding_calls {where}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"SELECT id, title, agency, max_award, deadline, primary_focus, secondary_focus, "
            f"min_h_index, eligible_stages, requires_collaboration, min_team_size "
            f"FROM funding_calls {where} ORDER BY id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "calls": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description="Retrieves full details for a single funding call by ID.",
        parameters={
            "type": "object",
            "properties": {
                "call_id": {
                    "type": "integer",
                    "description": "The funding call's unique ID.",
                },
            },
            "required": ["call_id"],
        },
    )
    def get_funding_call_details(self, call_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM funding_calls WHERE id = ?", (call_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Funding call {call_id} not found."}
        return dict(row)

    @tool(
        description="Retrieves publications for a given researcher. Optionally filter by minimum year.",
        parameters={
            "type": "object",
            "properties": {
                "researcher_id": {
                    "type": "integer",
                    "description": "The researcher's unique ID.",
                },
                "min_year": {
                    "type": "integer",
                    "description": "Only return publications from this year onward. Optional.",
                },
            },
            "required": ["researcher_id"],
        },
    )
    def get_researcher_publications(self, researcher_id: int, min_year: int = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if min_year is not None:
            cur.execute(
                "SELECT * FROM publications WHERE researcher_id = ? AND year >= ? ORDER BY year DESC",
                (researcher_id, min_year),
            )
        else:
            cur.execute(
                "SELECT * FROM publications WHERE researcher_id = ? ORDER BY year DESC",
                (researcher_id,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"publications": rows, "count": len(rows)}

    @tool(
        description="Retrieves expenditure records for a given institution and department.",
        parameters={
            "type": "object",
            "properties": {
                "institution_id": {
                    "type": "integer",
                    "description": "The institution's unique ID.",
                },
                "department": {
                    "type": "string",
                    "description": "Department name (exact match).",
                },
            },
            "required": ["institution_id", "department"],
        },
    )
    def get_institution_expenditure(self, institution_id: int, department: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM expenditures WHERE institution_id = ? AND department = ? ORDER BY fiscal_year DESC",
            (institution_id, department),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"expenditures": rows, "count": len(rows)}

    @tool(
        description="Retrieves the collaborator network for a given researcher, listing all collaborators and shared fields.",
        parameters={
            "type": "object",
            "properties": {
                "researcher_id": {
                    "type": "integer",
                    "description": "The researcher's unique ID.",
                },
            },
            "required": ["researcher_id"],
        },
    )
    def get_collaborator_network(self, researcher_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM collaborations WHERE researcher_a_id = ? OR researcher_b_id = ? ORDER BY id",
            (researcher_id, researcher_id),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        collaborators = []
        for r in rows:
            partner_id = r["researcher_b_id"] if r["researcher_a_id"] == researcher_id else r["researcher_a_id"]
            collaborators.append({
                "partner_id": partner_id,
                "joint_publications": r["joint_publications"],
                "shared_field": r["shared_field"],
                "last_collab_year": r["last_collab_year"],
            })
        return {"researcher_id": researcher_id, "collaborators": collaborators, "count": len(collaborators)}

    # ── Scoring helpers (used by step & verify) ──────────────────

    def _load_config(self):
        """Load all workspace config files. Used by step() and verify()."""
        import yaml

        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "field_taxonomy.json")) as f:
            taxonomy = json.load(f)
        with open(os.path.join(self.workspace, "eligibility_rules.json")) as f:
            elig_rules = json.load(f)

        institutions = {}
        with open(os.path.join(self.workspace, "institution_registry.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                institutions[int(row["institution_id"])] = {
                    "name": row["name"],
                    "tier": int(row["tier"]),
                    "country": row["country"],
                }

        dossiers = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("researcher_dossier_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    for entry in data:
                        dossiers[entry["researcher_id"]] = entry

        return config, taxonomy, elig_rules, institutions, dossiers

    def _compute_ground_truth(self):
        """Compute the full ground-truth result set using direct DB access + workspace files."""
        config, taxonomy, elig_rules, institutions, dossiers = self._load_config()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        researchers = [dict(r) for r in conn.execute("SELECT * FROM researchers ORDER BY id").fetchall()]
        grants = [dict(r) for r in conn.execute("SELECT * FROM funding_calls ORDER BY id").fetchall()]
        pubs_all = [dict(r) for r in conn.execute("SELECT * FROM publications").fetchall()]
        exp_all = [dict(r) for r in conn.execute("SELECT * FROM expenditures").fetchall()]
        collab_all = [dict(r) for r in conn.execute("SELECT * FROM collaborations").fetchall()]
        conn.close()

        # Index publications by researcher
        pubs_by_r = {}
        for p in pubs_all:
            pubs_by_r.setdefault(p["researcher_id"], []).append(p)

        # Index collaborations by researcher
        collabs_by_r = {}
        for c in collab_all:
            for rid in [c["researcher_a_id"], c["researcher_b_id"]]:
                partner = c["researcher_b_id"] if rid == c["researcher_a_id"] else c["researcher_a_id"]
                collabs_by_r.setdefault(rid, []).append({
                    "partner_id": partner,
                    "shared_field": c["shared_field"],
                    "joint_publications": c["joint_publications"],
                    "last_collab_year": c["last_collab_year"],
                })

        # Index expenditures: most recent year per (inst, dept)
        exp_latest = {}
        for e in exp_all:
            key = (e["institution_id"], e["department"])
            if key not in exp_latest or e["fiscal_year"] > exp_latest[key]["fiscal_year"]:
                exp_latest[key] = e

        weights = config["weights"]
        thresholds = config["thresholds"]
        pub_m = config["publication_metrics"]
        exp_m = config["expenditure_metrics"]
        collab_m = config["collaboration_metrics"]
        frt = collab_m["field_relevance_threshold"]
        min_fit = thresholds["min_fit_score"]
        top_n = thresholds["top_n_per_researcher"]

        def compat(f1, f2):
            return taxonomy.get(f1, {}).get(f2, 0.0)

        results = []
        for r in researchers:
            rid = r["id"]
            inst_id = r["institution_id"]
            dept = r["department"]
            inst_info = institutions.get(inst_id, {"tier": 3})
            dossier = dossiers.get(rid, {"research_keywords": [], "certifications": [], "past_grant_count": 0})

            # Expenditure check data
            exp_rec = exp_latest.get((inst_id, dept))
            if exp_rec:
                ext_ratio = exp_rec["external_funding"] / exp_rec["total_budget"] if exp_rec["total_budget"] > 0 else 0.0
            else:
                ext_ratio = 0.0

            # Pre-check: min expenditure ratio eligibility
            min_exp_ratio = elig_rules.get("min_expenditure_external_ratio", 0.0)
            if ext_ratio < min_exp_ratio:
                continue

            r_pubs = pubs_by_r.get(rid, [])
            r_collabs = collabs_by_r.get(rid, [])

            for g in grants:
                # ── Eligibility ──
                # 1. Career stage
                elig_stages = set(g["eligible_stages"].split(","))
                if r["career_stage"] not in elig_stages:
                    continue
                # 2. H-index
                if r["h_index"] < g["min_h_index"]:
                    continue
                # 3. Institution tier
                agency = g["agency"]
                max_tier = elig_rules.get("agency_tier_requirements", {}).get(agency, 3)
                if inst_info["tier"] > max_tier:
                    continue
                # 4. Certifications
                req_certs = elig_rules.get("agency_certification_requirements", {}).get(agency, [])
                r_certs = set(dossier.get("certifications", []))
                if not all(c in r_certs for c in req_certs):
                    continue

                # ── Scoring ──
                # 1. Field alignment
                fa = max(
                    compat(r["primary_field"], g["primary_focus"]),
                    compat(r["primary_field"], g["secondary_focus"]),
                    compat(r["secondary_field"], g["primary_focus"]),
                    compat(r["secondary_field"], g["secondary_focus"]),
                )

                # 2. Publication strength
                recent = [p for p in r_pubs if p["year"] >= pub_m["recent_year_cutoff"]]
                relevant = [p for p in recent if compat(p["field"], g["primary_focus"]) >= frt]
                count_score = min(1.0, len(relevant) / pub_m["max_relevant_pubs"])
                if relevant:
                    avg_cit = sum(p["citations"] for p in relevant) / len(relevant)
                    cit_score = min(1.0, avg_cit / pub_m["citation_normalization"])
                else:
                    cit_score = 0.0
                ps = 0.6 * count_score + 0.4 * cit_score

                # 3. Expenditure fit
                ef = min(1.0, ext_ratio / exp_m["target_external_ratio"]) if exp_m["target_external_ratio"] > 0 else 0.0

                # 4. Collaboration score
                if g["requires_collaboration"]:
                    rel_collabs = [c for c in r_collabs if compat(c["shared_field"], g["primary_focus"]) >= frt]
                    denom = g["min_team_size"] - 1
                    if denom > 0:
                        cs = min(1.0, len(rel_collabs) / denom)
                    else:
                        cs = 1.0 if rel_collabs else 0.0
                else:
                    cs = min(1.0, len(r_collabs) / 5)

                # 5. Keyword match
                keywords = dossier.get("research_keywords", [])
                if keywords:
                    matching = sum(1 for k in keywords if compat(k, g["primary_focus"]) >= frt)
                    km = matching / len(keywords)
                else:
                    km = 0.0

                fit = round(
                    weights["field_alignment"] * fa
                    + weights["publication_strength"] * ps
                    + weights["expenditure_fit"] * ef
                    + weights["collaboration_score"] * cs
                    + weights["keyword_match"] * km,
                    2,
                )

                if fit >= min_fit:
                    results.append({
                        "researcher_id": rid,
                        "researcher_name": r["name"],
                        "grant_id": g["id"],
                        "grant_title": g["title"],
                        "fit_score": fit,
                    })

        # Rank per researcher, top N
        from collections import defaultdict
        by_r = defaultdict(list)
        for entry in results:
            by_r[entry["researcher_id"]].append(entry)

        final = []
        for rid in sorted(by_r.keys()):
            entries = sorted(by_r[rid], key=lambda x: (-x["fit_score"], x["grant_id"]))
            for rank, e in enumerate(entries[:top_n], 1):
                e["rank"] = rank
                final.append(e)

        return final

    # ── step ─────────────────────────────────────────────────────

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
        ground_truth = self._compute_ground_truth()
        criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: Output file format (10 pts) ──
        output_path = os.path.join(self.workspace, "ranked_matches.csv")
        expected_cols = ["researcher_id", "researcher_name", "grant_id", "grant_title", "fit_score", "rank"]
        format_ok = False
        agent_rows = []
        try:
            with open(output_path, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and set(expected_cols).issubset(set(reader.fieldnames)):
                    agent_rows = list(reader)
                    format_ok = True
        except Exception:
            pass

        fmt_score = 10 if format_ok else 0
        criteria["output_format"] = {
            "passed": format_ok,
            "score": fmt_score,
            "max_score": 10,
            "reason": "" if format_ok else "ranked_matches.csv missing or has wrong columns",
        }
        total_score += fmt_score
        max_score += 10

        if not format_ok:
            # Can't evaluate further
            for cname, mx in [("pair_coverage", 20), ("score_accuracy", 25), ("rank_correctness", 20), ("top_n_filtering", 15), ("response_summary", 15)]:
                criteria[cname] = {"passed": False, "score": 0, "max_score": mx, "reason": "Cannot evaluate – output file missing or malformed"}
                max_score += mx
            info = {"eval_criteria": criteria, "total_score": total_score, "max_score": max_score}
            return total_score / max_score if max_score > 0 else 0.0, info

        # Parse agent rows
        agent_pairs = {}
        for row in agent_rows:
            try:
                key = (int(row["researcher_id"]), int(row["grant_id"]))
                agent_pairs[key] = {
                    "fit_score": float(row["fit_score"]),
                    "rank": int(row["rank"]),
                    "researcher_name": row["researcher_name"],
                    "grant_title": row["grant_title"],
                }
            except (ValueError, KeyError):
                continue

        # Ground truth pairs
        gt_pairs = {}
        for entry in ground_truth:
            key = (entry["researcher_id"], entry["grant_id"])
            gt_pairs[key] = entry

        # ── Criterion 2: Pair coverage (20 pts) ──
        if gt_pairs:
            gt_set = set(gt_pairs.keys())
            agent_set = set(agent_pairs.keys())
            recall = len(gt_set & agent_set) / len(gt_set)
            precision = len(gt_set & agent_set) / len(agent_set) if agent_set else 0.0
            coverage_score = round(recall * 0.7 + precision * 0.3, 4)
            pair_pts = round(coverage_score * 20, 1)
        else:
            pair_pts = 20.0 if not agent_pairs else 0.0
            coverage_score = 1.0 if not agent_pairs else 0.0

        criteria["pair_coverage"] = {
            "passed": pair_pts >= 18,
            "score": pair_pts,
            "max_score": 20,
            "reason": "" if pair_pts >= 18 else f"coverage={coverage_score:.3f}, gt={len(gt_pairs)}, agent={len(agent_pairs)}",
        }
        total_score += pair_pts
        max_score += 20

        # ── Criterion 3: Score accuracy (25 pts) ──
        common = set(gt_pairs.keys()) & set(agent_pairs.keys())
        if common:
            correct = sum(1 for k in common if abs(agent_pairs[k]["fit_score"] - gt_pairs[k]["fit_score"]) <= 0.051)
            accuracy = correct / len(common)
            score_pts = round(accuracy * 25, 1)
        else:
            accuracy = 0.0
            score_pts = 0.0

        criteria["score_accuracy"] = {
            "passed": score_pts >= 22,
            "score": score_pts,
            "max_score": 25,
            "reason": "" if score_pts >= 22 else f"accuracy={accuracy:.3f}, common={len(common)}",
        }
        total_score += score_pts
        max_score += 25

        # ── Criterion 4: Rank correctness (20 pts) ──
        # Check per-researcher ranking order matches ground truth
        from collections import defaultdict
        gt_by_r = defaultdict(list)
        ag_by_r = defaultdict(list)
        for k, v in gt_pairs.items():
            gt_by_r[k[0]].append(v)
        for k, v in agent_pairs.items():
            entry = dict(v)
            entry["grant_id"] = k[1]
            ag_by_r[k[0]].append(entry)

        n_researchers_checked = 0
        n_correct_order = 0
        for rid in gt_by_r:
            if rid not in ag_by_r:
                continue
            n_researchers_checked += 1
            gt_order = [e["grant_id"] for e in sorted(gt_by_r[rid], key=lambda x: (-x["fit_score"], x["grant_id"]))]
            ag_order = [e["grant_id"] for e in sorted(ag_by_r[rid], key=lambda x: (x["rank"], x["grant_id"]))]
            if gt_order == ag_order:
                n_correct_order += 1

        if n_researchers_checked > 0:
            rank_acc = n_correct_order / n_researchers_checked
            rank_pts = round(rank_acc * 20, 1)
        else:
            rank_acc = 0.0
            rank_pts = 0.0

        criteria["rank_correctness"] = {
            "passed": rank_pts >= 16,
            "score": rank_pts,
            "max_score": 20,
            "reason": "" if rank_pts >= 16 else f"rank_accuracy={rank_acc:.3f}, checked={n_researchers_checked}",
        }
        total_score += rank_pts
        max_score += 20

        # ── Criterion 5: Top-N filtering (15 pts) ──
        config, _, _, _, _ = self._load_config()
        top_n = config["thresholds"]["top_n_per_researcher"]
        min_fit = config["thresholds"]["min_fit_score"]

        filtering_ok = True
        filter_reasons = []
        for rid, entries in ag_by_r.items():
            if len(entries) > top_n:
                filtering_ok = False
                filter_reasons.append(f"Researcher {rid} has {len(entries)} entries (max {top_n})")
                break
        # Check min score
        for k, v in agent_pairs.items():
            if v["fit_score"] < min_fit - 0.011:
                filtering_ok = False
                filter_reasons.append(f"Pair {k} has score {v['fit_score']} < min {min_fit}")
                break

        filter_pts = 15 if filtering_ok else 0
        criteria["top_n_filtering"] = {
            "passed": filtering_ok,
            "score": filter_pts,
            "max_score": 15,
            "reason": "" if filtering_ok else "; ".join(filter_reasons[:3]),
        }
        total_score += filter_pts
        max_score += 15

        # ── Criterion 6: Response summary (15 pts) ──
        # Check that the response mentions each researcher's top grant
        gt_top = {}
        for rid, entries in gt_by_r.items():
            best = sorted(entries, key=lambda x: (-x["fit_score"], x["grant_id"]))[0]
            gt_top[rid] = best

        if gt_top:
            mentioned = 0
            for rid, best in gt_top.items():
                r_name = best["researcher_name"]
                g_title = best["grant_title"]
                # Check if at least partial match of both researcher name and grant title
                name_parts = r_name.lower().split()
                title_words = g_title.lower().split()
                action_lower = action.lower()
                name_found = any(part in action_lower for part in name_parts if len(part) > 2)
                title_found = any(w in action_lower for w in title_words if len(w) > 3)
                if name_found and title_found:
                    mentioned += 1
            summary_ratio = mentioned / len(gt_top)
            summary_pts = round(summary_ratio * 15, 1)
        else:
            summary_pts = 15.0

        criteria["response_summary"] = {
            "passed": summary_pts >= 12,
            "score": summary_pts,
            "max_score": 15,
            "reason": "" if summary_pts >= 12 else f"Only {mentioned}/{len(gt_top)} researchers' top grants mentioned in response",
        }
        total_score += summary_pts
        max_score += 15

        info = {
            "eval_criteria": criteria,
            "total_score": round(total_score, 1),
            "max_score": max_score,
        }
        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0
        return reward, info

    # ── verify ───────────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml

        # ── Read workspace config files ──
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "field_taxonomy.json")) as f:
            taxonomy = json.load(f)
        with open(os.path.join(self.workspace, "eligibility_rules.json")) as f:
            elig_rules = json.load(f)

        institutions = {}
        with open(os.path.join(self.workspace, "institution_registry.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                institutions[int(row["institution_id"])] = {
                    "name": row["name"],
                    "tier": int(row["tier"]),
                    "country": row["country"],
                }

        # Read scoring guide
        with open(os.path.join(self.workspace, "scoring_guide.md")) as f:
            _ = f.read()

        # Read all dossier files
        dossiers = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("researcher_dossier_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    for entry in data:
                        dossiers[entry["researcher_id"]] = entry

        weights = config["weights"]
        thresholds = config["thresholds"]
        pub_m = config["publication_metrics"]
        exp_m = config["expenditure_metrics"]
        collab_m = config["collaboration_metrics"]
        frt = collab_m["field_relevance_threshold"]
        min_fit = thresholds["min_fit_score"]
        top_n = thresholds["top_n_per_researcher"]

        def compat(f1, f2):
            return taxonomy.get(f1, {}).get(f2, 0.0)

        # ── Gather all researchers via tools ──
        tool_call_count = 0
        researchers = []
        page = 1
        while True:
            result = self.tools["list_researchers"](page=page, page_size=10)
            tool_call_count += 1
            researchers.extend(result["researchers"])
            if not result["has_more"]:
                break
            page += 1

        # ── Gather all funding calls via tools ──
        grants = []
        page = 1
        while True:
            result = self.tools["search_funding_calls"](page=page, page_size=10)
            tool_call_count += 1
            grants.extend(result["calls"])
            if not result["has_more"]:
                break
            page += 1

        # ── For each researcher, gather pubs, collabs, expenditure ──
        researcher_data = {}
        for r in researchers:
            rid = r["id"]
            pubs_result = self.tools["get_researcher_publications"](researcher_id=rid)
            tool_call_count += 1
            collabs_result = self.tools["get_collaborator_network"](researcher_id=rid)
            tool_call_count += 1
            exp_result = self.tools["get_institution_expenditure"](
                institution_id=r["institution_id"], department=r["department"]
            )
            tool_call_count += 1
            researcher_data[rid] = {
                "info": r,
                "publications": pubs_result["publications"],
                "collaborators": collabs_result["collaborators"],
                "expenditure": exp_result["expenditures"],
                "dossier": dossiers.get(rid, {"research_keywords": [], "certifications": [], "past_grant_count": 0}),
                "institution_tier": institutions.get(r["institution_id"], {"tier": 3})["tier"],
            }

        # ── Compute eligibility & scores ──
        results = []
        for r in researchers:
            rid = r["id"]
            rd = researcher_data[rid]

            # Expenditure: most recent year
            exp_recs = rd["expenditure"]
            if exp_recs:
                latest_exp = max(exp_recs, key=lambda x: x["fiscal_year"])
                ext_ratio = latest_exp["external_funding"] / latest_exp["total_budget"] if latest_exp["total_budget"] > 0 else 0.0
            else:
                ext_ratio = 0.0

            # Pre-check expenditure eligibility
            min_exp_ratio = elig_rules.get("min_expenditure_external_ratio", 0.0)
            if ext_ratio < min_exp_ratio:
                continue

            for g in grants:
                # Eligibility checks
                elig_stages = set(g["eligible_stages"].split(","))
                if r["career_stage"] not in elig_stages:
                    continue
                if r["h_index"] < g["min_h_index"]:
                    continue
                agency = g["agency"]
                max_tier = elig_rules.get("agency_tier_requirements", {}).get(agency, 3)
                if rd["institution_tier"] > max_tier:
                    continue
                req_certs = elig_rules.get("agency_certification_requirements", {}).get(agency, [])
                r_certs = set(rd["dossier"].get("certifications", []))
                if not all(c in r_certs for c in req_certs):
                    continue

                # Scoring
                fa = max(
                    compat(r["primary_field"], g["primary_focus"]),
                    compat(r["primary_field"], g["secondary_focus"]),
                    compat(r["secondary_field"], g["primary_focus"]),
                    compat(r["secondary_field"], g["secondary_focus"]),
                )

                recent = [p for p in rd["publications"] if p["year"] >= pub_m["recent_year_cutoff"]]
                relevant = [p for p in recent if compat(p["field"], g["primary_focus"]) >= frt]
                count_score = min(1.0, len(relevant) / pub_m["max_relevant_pubs"])
                if relevant:
                    avg_cit = sum(p["citations"] for p in relevant) / len(relevant)
                    cit_score = min(1.0, avg_cit / pub_m["citation_normalization"])
                else:
                    cit_score = 0.0
                ps = 0.6 * count_score + 0.4 * cit_score

                ef = min(1.0, ext_ratio / exp_m["target_external_ratio"]) if exp_m["target_external_ratio"] > 0 else 0.0

                if g["requires_collaboration"]:
                    rel_collabs = [c for c in rd["collaborators"] if compat(c["shared_field"], g["primary_focus"]) >= frt]
                    denom = g["min_team_size"] - 1
                    if denom > 0:
                        collab_s = min(1.0, len(rel_collabs) / denom)
                    else:
                        collab_s = 1.0 if rel_collabs else 0.0
                else:
                    collab_s = min(1.0, len(rd["collaborators"]) / 5)

                keywords = rd["dossier"].get("research_keywords", [])
                if keywords:
                    matching_kw = sum(1 for k in keywords if compat(k, g["primary_focus"]) >= frt)
                    km = matching_kw / len(keywords)
                else:
                    km = 0.0

                fit = round(
                    weights["field_alignment"] * fa
                    + weights["publication_strength"] * ps
                    + weights["expenditure_fit"] * ef
                    + weights["collaboration_score"] * collab_s
                    + weights["keyword_match"] * km,
                    2,
                )

                if fit >= min_fit:
                    results.append({
                        "researcher_id": rid,
                        "researcher_name": r["name"],
                        "grant_id": g["id"],
                        "grant_title": g["title"],
                        "fit_score": fit,
                    })

        # Rank per researcher, top N
        from collections import defaultdict
        by_r = defaultdict(list)
        for entry in results:
            by_r[entry["researcher_id"]].append(entry)

        final = []
        for rid in sorted(by_r.keys()):
            entries = sorted(by_r[rid], key=lambda x: (-x["fit_score"], x["grant_id"]))
            for rank, e in enumerate(entries[:top_n], 1):
                e["rank"] = rank
                final.append(e)

        # Write output CSV
        output_path = os.path.join(self.workspace, "ranked_matches.csv")
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["researcher_id", "researcher_name", "grant_id", "grant_title", "fit_score", "rank"])
            writer.writeheader()
            for entry in final:
                writer.writerow(entry)

        # Build response summary
        action_lines = ["Ranked grant matches have been saved to ranked_matches.csv.", "", "Summary of top matches per researcher:"]
        for rid in sorted(by_r.keys()):
            entries = sorted(by_r[rid], key=lambda x: (-x["fit_score"], x["grant_id"]))
            if entries:
                best = entries[0]
                action_lines.append(
                    f"Researcher {best['researcher_name']} (ID {rid}): top match is \"{best['grant_title']}\" with fit score {best['fit_score']:.2f}"
                )
        action = "\n".join(action_lines)

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made; need at least 15"

        return self.step(action)
