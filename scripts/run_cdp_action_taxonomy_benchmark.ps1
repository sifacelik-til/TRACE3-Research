param(
    [ValidateSet("prepare", "encode", "evaluate", "verify", "all")]
    [string]$Stage = "all",
    [string[]]$Models = @(
        "minilm", "e5_base", "bge_m3", "qwen3_06b",
        "gte_multilingual", "jina_v3", "e5_large_instruct"
    ),
    [ValidateSet("cpu", "cuda", "mps")]
    [string]$Device = "cpu",
    [int]$BatchSize = 16,
    [switch]$Offline,
    [switch]$IncludeQwen4B
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$benchmarkModule = "src.cdp_text_clustering.benchmark_cdp_action_taxonomy"
$output = Join-Path $projectRoot "data\outputs\cdp_text_clustering\cdp_action_taxonomy_benchmark_20261002"
if ($IncludeQwen4B -and $Models -notcontains "qwen3_4b") {
    $Models += "qwen3_4b"
}
$arguments = @(
    "-m", $benchmarkModule, "--stage", $Stage, "--models"
) + $Models + @(
    "--output", $output, "--device", $Device, "--batch-size", $BatchSize
)
if ($Offline) { $arguments += "--offline" }

Push-Location $projectRoot
try {
    python @arguments
}
finally {
    Pop-Location
}
