## Task Topic

Monitor patient safety by cross-referencing pharmacy dispensing records, electronic health records (EHR) for active diagnoses, known drug interaction databases, and lab test results to generate a daily alert list of patients requiring pharmacist intervention for potential adverse interactions.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 60             | 8                   |
| v1      | 120            | 16                  |
| v2      | 240            | 24                  |
| v3      | 480            | 32                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N=8.

**Structural dimensions used:**

- **Information Scattering**: Drug interactions and lab results are in the database (accessible only via tools), while contraindication rules, alert thresholds, allergy records, ward assignments, and monitoring levels reside in workspace files across CSV, JSON, YAML, and Markdown formats. Solving the task requires combining both sources.
- **Conditional Constraints**: Alert inclusion depends on the patient's monitoring level (standard/enhanced/intensive), which determines which severity levels pass through to the final report. Thresholds for lab-based alerts are defined in workspace configuration files, not in the prompt.
- **Multi-Hop Reasoning**: Generating a lab alert requires: (1) retrieve patient medications via tool, (2) match medications against relevant-drug lists in the YAML threshold config, (3) retrieve patient lab results via tool, (4) compare values against threshold bands, (5) check patient monitoring level from ward roster CSV, (6) apply severity filtering. Drug-allergy alerts require cross-referencing tool-provided dispensing records with workspace allergy JSON files.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 (file_structure 10, drug_interaction_alerts 20, contraindication_alerts 20, lab_value_alerts 15, drug_allergy_alerts 15, sorting_and_format 10, response_summary 10).
- Section 1 (structural integrity): all four versions contain only data.py / env.py / prompt.md; env.py and prompt.md are byte-identical across v0..v3; data.py differs only in the SCALE block. SCALE follows the 1x/2x/4x/8x rows and base+0/N/2N/3N files convention.
- Section 2 (solvability at v3): solved with a /tmp solver using only prompt.md and `Task_Env.get_assistant_tools()`, achieved reward 1.0 on first run; env.py was not opened during solving.
- Section 3 (env quality): all seven step criteria correspond to prompt requirements; ground truth is computed from the live DB and workspace files (no hard-coded counts). Note: alert matching keys on (patient_id, alert_type, frozenset(drugs)), so descriptions are not compared directly which keeps scoring resilient to harmless wording variants in the agent's drug_allergy description.
- Section 4 (prompt quality): no title or bold headers, deliverables woven into prose, no source filenames or tool names leaked, column names and sort order explicit, scale-invariant wording.
- Issues found: none. No edits were made; environment passes verification as authored.
- Cleanup: data.db, workspace/, __pycache__, and the /tmp solver were removed; top-level layout is README.md + v0..v3.
