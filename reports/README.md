# Reports

| Folder | Contents |
| --- | --- |
| `dataset_readers/` | Missing-data audits and company/supplier analysis reports |
| `cdp_extraction/` | Questionnaire mappings, field dictionaries, and annual review templates |
| `cdp_text_clustering/` | Encoder, clustering, coding, and benchmark methodology/results |
| `MDP/` | Climate-policy inventories and timelines supporting the decision model |
| `literature_review/` | Existing Word literature review; left in place because it was locked during migration |

Report generators live in `src/`, alongside the relevant analysis code.
Machine-readable analysis outputs and model results are under
`data/outputs/<category>/`. Human-reviewed workbook exports are under
`data/outputs/cdp_extraction/workbooks/`.

For the section-encoder manuscripts, compile from `reports/cdp_text_clustering/`;
their figure paths are relative to that folder. The supplier manuscript and the
defined-taxonomy methodology use repository-root-relative figure paths, so
compile those from the repository root.
