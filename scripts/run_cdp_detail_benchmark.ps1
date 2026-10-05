param(
    [Parameter(Mandatory = $true)]
    [string[]]$Models,
    [string]$BaseUrl = "http://localhost:11434/v1",
    [int]$Folds = 5,
    [int]$Examples = 2,
    [switch]$Smoke,
    [switch]$NoResponseFormat
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$benchmarkScript = Join-Path $projectRoot "src\cdp_text_clustering\benchmark_cdp_detail_models.py"
$benchmarkModule = "src.cdp_text_clustering.benchmark_cdp_detail_models"
$answers = Join-Path $projectRoot "data\processed\cdp_section_datasets\cdp_validation_answers.jsonl.gz"
$labels = Join-Path $projectRoot "data\processed\cdp_section_datasets\cdp_validation_detail_labels.jsonl.gz"
$outputName = if ($Smoke) { "cdp_taxonomy_extraction_benchmark_smoke" } else { "cdp_taxonomy_extraction_benchmark" }
$output = Join-Path $projectRoot "data\outputs\cdp_text_clustering\$outputName"

foreach ($required in @($benchmarkScript, $answers, $labels)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required file not found: $required"
    }
}

$benchmarkArgs = @(
    "-m", $benchmarkModule,
    "--base-url", $BaseUrl,
    "--models"
) + $Models + @(
    "--folds", $Folds,
    "--examples", $Examples,
    "--answers", $answers,
    "--labels", $labels,
    "--output", $output
)

if ($Smoke) {
    $benchmarkArgs += @("--limit", "8")
}
if ($NoResponseFormat) {
    $benchmarkArgs += "--no-response-format"
}

Push-Location $projectRoot
try {
    python @benchmarkArgs
}
finally {
    Pop-Location
}
