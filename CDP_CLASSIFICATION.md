# CDP supervised-classification workflow

The active workflow assigns predefined labels to validated CDP text. It does
not discover topics or use learned clusters as outcome categories. Reduction
actions, risks, opportunities, and engagement records are evaluated separately
because their label structures differ.

## Package layout

| Module | Purpose                                                             |
| --- |---------------------------------------------------------------------|
| `src.cdp_classification.detail_output` | Validate and export workbook-format item labels                     |
| `src.cdp_classification.merge_reduction_validation` | Merge the second validated reduction round with the original labels |
| `src.cdp_classification.prepare_reduction_records` | Build the 2020--2022 reduction benchmark sample                     |
| `src.cdp_classification.encode_reduction` | Encode reduction records with the local embedding models            |
| `src.cdp_classification.benchmark_reduction` | Compare supervised reduction classifiers                            |
| `src.cdp_classification.benchmark_other_sections` | Compare risk, opportunity, and engagement classifiers               |
| `src.cdp_classification.evaluate_action_transition` | Test whether classified actions improve transition forecasts        |
| `src.cdp_classification.evaluate_human_validation` | Summarize validation                                                |

Shared encoder configuration is defined once in
`src.cdp_classification.embeddings`.

## Run from PowerShell

Create and activate the benchmark environment, then install both requirement
files:

```powershell
py -3.11 -m venv .venv-benchmark
.\.venv-benchmark\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-cdp-classification.txt
```

Run one task at a time:

```powershell
.\scripts\run_cdp_classification.ps1 -Task prepare-reduction
.\scripts\run_cdp_classification.ps1 -Task encode-reduction -Device cpu -Offline
.\scripts\run_cdp_classification.ps1 -Task benchmark-reduction
.\scripts\run_cdp_classification.ps1 -Task benchmark-other
```

Pass `-Models minilm` for a one-model reduction smoke test. The reduction
encoding and benchmark tasks must receive the same model list.

Use `-Task all` only when every benchmark should be rerun. Encoding can take
substantial time on a CPU. The benchmarks use company-grouped out-of-fold
validation, so records from one company do not appear in both training and
test folds.

The current risk, opportunity, and engagement results are stored under
`data/outputs/cdp_other_sections_hybrid_benchmark_2020_2022`. Existing
reduction artifacts remain under `data/outputs/cdp_text_clustering` to avoid
invalidating cached embeddings; the directory name is retained only for
artifact compatibility.
