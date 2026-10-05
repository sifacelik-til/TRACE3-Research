# CDP action-taxonomy benchmark

This benchmark uses `cdp_classification_all_details.xlsx` as its validation source. The extracted benchmark contains 972 item-level evidence spans from 256 reviewed answers; 250 answers contain at least one labeled item. The four cohorts are reduction, engagement, risk, and opportunity. Each cohort pools industries to produce a stable common taxonomy. Every assignment also receives an `industry_cluster_id`, which combines the common action class with the disclosed industry for sector-specific analysis without fitting clusters to small industry samples.

Each validated item is a separate observation, so an answer with several actions receives several labels. The clustering input removes questionnaire language, company names, dates, and URLs, while the output retains the verbatim evidence and its source context for review. Companies are assigned to disjoint training, model-selection, and verification sets.

## Models

The default comparison includes:

- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- `intfloat/multilingual-e5-base`
- `BAAI/bge-m3`
- `Qwen/Qwen3-Embedding-0.6B`
- `Alibaba-NLP/gte-multilingual-base`
- `jinaai/jina-embeddings-v3`
- `intfloat/multilingual-e5-large-instruct`

`Qwen/Qwen3-Embedding-4B` is an optional scale comparison because it requires substantially more memory.

Jina uses the original checkpoint with `trust_remote_code=True` and the `separation` LoRA task. Its `-hf` variant requires Transformers 5.4 or newer and is incompatible with this benchmark's Transformers 4.57.1 pin, which is retained for GTE's custom architecture. GTE also requires trusted remote code. The first Jina load downloads its checkpoint and referenced architecture code; run online once before using `-Offline`.

## Run in PyCharm

The current PyCharm project file points to `C:\Users\scelik\Desktop\TRACE3Code\.venv`, and PyTorch in that environment fails to load `c10.dll` with `WinError 1114`. Create a clean environment in the current workspace and select its interpreter in **Settings > Project > Python Interpreter**:

```powershell
py -3.11 -m venv .venv-benchmark
.\.venv-benchmark\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --force-reinstall torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r .\requirements.txt -r .\requirements-cdp-action-benchmark.txt
python -c "import torch; print(torch.__version__)"
```

Then open the PyCharm terminal at the project root and run:

```powershell
# Validate and prepare the workbook-derived sample only.
.\scripts\run_cdp_action_taxonomy_benchmark.ps1 -Stage prepare

# Smoke-test one locally cached model.
.\scripts\run_cdp_action_taxonomy_benchmark.ps1 -Stage encode -Models minilm
.\scripts\run_cdp_action_taxonomy_benchmark.ps1 -Stage evaluate -Models minilm
.\scripts\run_cdp_action_taxonomy_benchmark.ps1 -Stage verify -Models minilm

# Run the seven-model comparison. New models download on first use.
.\scripts\run_cdp_action_taxonomy_benchmark.ps1 -Stage all -Device cuda -BatchSize 16

# Optional 4B scale comparison.
.\scripts\run_cdp_action_taxonomy_benchmark.ps1 -Stage all -Device cuda -IncludeQwen4B
```

Use `-Device cpu` when CUDA is unavailable. Add `-Offline` only after every requested model is present in the local cache. If a GPU runs out of memory, reduce `-BatchSize` to 4 or 8.

## Selection and verification

For each disclosure cohort, the benchmark fits character 3--5 gram TF-IDF on training data and combines it with the normalized embedding at semantic weights 0.25, 0.50, 0.75, and 1.00. Spherical k-means uses cosine geometry. A candidate is unsupported if a training cluster has fewer than 10 observations or a selection cluster has fewer than 5 observations. Silhouette is left missing for unsupported partitions; it is never replaced by `-1`.

The encoder must cover at least 75% of the four cohorts. Among eligible encoders, selection-set conditional silhouette determines the winner. The verification set is opened only after this choice. Workbook labels provide independent purity, adjusted Rand index, normalized mutual information, and macro precision, recall, and F1 diagnostics. These measures diagnose semantic validity; silhouette alone does not establish an operational action taxonomy.

## Human review

The selected encoder creates `human_validation_sample.csv` with five observations per cluster and separate columns for two coders. Each coder assesses whether cluster members describe the same operational action, whether the cluster label fits, whether the source contains multiple actions, and whether the text describes implementation rather than intention. After both coders fill the file, run:

```powershell
python -m src.cdp_text_clustering.evaluate_cdp_human_validation `
  .\data\outputs\cdp_text_clustering\cdp_action_taxonomy_benchmark_20261002\human_validation_sample.csv
```

## Three-year Scope 3 forecasting test

The benchmark exports `company_year_multilabel_actions.csv`. The transition test uses industry-specific action identifiers by default; pass `--action-column action_cluster_ids` to test the common cross-sector taxonomy instead. Test whether the indicators add predictive information beyond the proposed MDP state with temporally held-out years:

```powershell
python -m src.cdp_text_clustering.evaluate_cdp_action_transition `
  --actions .\data\outputs\cdp_text_clustering\cdp_action_taxonomy_benchmark_20261002\company_year_multilabel_actions.csv `
  --panel PATH_TO_COMPANY_YEAR_PANEL.csv `
  --output .\data\outputs\cdp_text_clustering\cdp_action_taxonomy_benchmark_20261002\scope3_transition_test.csv `
  --state-columns revenue profit inventory_turnover cogs scope1 scope2
```

The panel must contain `company`, `year`, `upstream_scope3_intensity`, and every state column named in the command. The outcome is the log reduction in upstream Scope 3 intensity over three years. Positive RMSE or MAE improvement means that action clusters improve held-out forecasts relative to the state-only model.
