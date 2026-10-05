# Source code layout

Run package modules from the repository root with `python -m`. For example:

```powershell
python -m src.cdp_extraction.extract_cdp_org_answers_2014_2024 --help
python -m src.cdp_text_clustering.benchmark_cdp_sections --help
```

| Package | Responsibility |
| --- | --- |
| `dataset_readers/` | Read CDP, FactSet, LSEG, and Trucost data; match companies and assemble cross-source panels |
| `cdp_extraction/` | Extract CDP answers and prepare curated questionnaire datasets |
| `cdp_text_clustering/` | Code, embed, cluster, benchmark, evaluate, and review CDP text |
| `MDP/` | Build state variables for the MDP analysis |

Small tools directly under `src/` are general command-line utilities or shared
helpers rather than part of one analysis pipeline.

Report-generation utilities are in the relevant package: CDP template builders
and audits in `cdp_extraction/`, and the policy inventory builder in `MDP/`.
Run them with the same `python -m src.<package>.<module>` convention.
Their report artifacts are written under `reports/<package>/`.
Analysis outputs are written under `data/outputs/<package>/`.

`data_engine/` is retained as a compatibility package for older imports such
as `data_engine.cdp_read`. New code should import from the category packages.
