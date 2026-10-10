## Task Topic

Optimize container load planning for multi-leg voyages. Process cargo manifests (weight, dimensions), vessel stowage plans, intermediate port discharge sequences, and land transport schedules to output a revised loading plan maximizing capacity utilization and minimizing re-handling.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 30             | 8                   |
| v1      | 60             | 16                  |
| v2      | 120            | 24                  |
| v3      | 240            | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N = 8 (the base file count). Only the `SCALE` dict in `data.py` changes between versions; `env.py` and `prompt.md` are identical across all four.

### Structural Dimensions

- **Information Scattering**: Container physical specifications (weight, type, hazmat class, reefer designation) are accessible only through query tools, while temperature-control requirements for cargo are recorded exclusively in workspace CSV manifests. The voyage port sequence, vessel bay layout, stacking rules, and hazmat separation policies reside in workspace configuration files (JSON, TXT, MD). Solving the task requires combining data from both sources.

- **Conditional Constraints**: Multiple interacting rules govern valid assignments — container type must match cell size, reefer-needing containers (from DB *or* workspace) must occupy reefer-capable cells, different hazmat classes cannot share a bay, stack weight must be non-increasing from bottom to top, individual cell weight limits apply, and aggregate bay weight must stay under the published limit. Thresholds and rules are specified in workspace configuration files rather than in the prompt.

- **Multi-Hop Reasoning**: Determining which containers need reefer slots requires checking both the database reefer flag (via tool) and the workspace cargo manifests (file read). Optimizing discharge ordering requires reading the voyage route (workspace JSON) to learn port visit order, then querying container destinations (tool), then mapping discharge priority to tier assignment while respecting weight constraints from cell specifications (tool) and stacking rules (workspace file).

## Harness Report

- v3 reward: 1.0
- Eval criteria: 7 (file_format, assignment_validity, weight_constraints, reefer_compliance, hazmat_compliance, rehandle_improvement, response_metrics)
- Source-access: clean — solver completed using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no escalation to env.py was required to reach reward 1.0.
- Section 1 (structural integrity): passed — top-level contains only `README.md` + `v0..v3`; each version has only `data.py`/`env.py`/`prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` dict.
- Section 2 (solvability): solved at v3 with a greedy stack-packer; key insight was reserving reefer bays for reefer-needing containers (initial naive bay ordering left 16 reefer-needing containers unassigned, achieving reward 0.99). After biasing non-reefer containers away from reefer bays the solver assigned all 240 containers and reduced re-handles from the current plan.
- Section 3 (env quality): all criteria correspond to prompt requirements; ground truth derived from db/workspace; no hardcoded counts; same criteria across versions (byte-identical env.py).
- Section 4 (prompt quality): no title/headings/bullets/code; output filename and columns specified; constraints unambiguous; scale-invariant wording.
- Issues found and fixed: none. No edits to `v0/` were necessary; v1/v2/v3 already match v0 byte-for-byte and v3 reaches reward 1.0 unmodified.
