param(
    [ValidateSet(
        "prepare-reduction",
        "encode-reduction",
        "benchmark-reduction",
        "benchmark-other",
        "all"
    )]
    [string]$Task = "all",
    [string[]]$Models = @(
        "minilm", "e5_base", "bge_m3", "qwen3_06b",
        "gte_multilingual", "jina_v3", "e5_large_instruct"
    ),
    [ValidateSet("cpu", "cuda", "mps")]
    [string]$Device = "cpu",
    [int]$BatchSize = 16,
    [switch]$Offline
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv-benchmark\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

function Invoke-Module([string]$Module, [string[]]$Arguments = @()) {
    & $python -m $Module @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Module failed with exit code $LASTEXITCODE"
    }
}

Push-Location $projectRoot
try {
    if ($Task -in @("prepare-reduction", "all")) {
        Invoke-Module "src.cdp_classification.merge_reduction_validation"
        Invoke-Module "src.cdp_classification.prepare_reduction_records"
    }
    if ($Task -in @("encode-reduction", "all")) {
        $arguments = @("--models") + $Models + @("--device", $Device, "--batch-size", $BatchSize)
        if ($Offline) { $arguments += "--offline" }
        Invoke-Module "src.cdp_classification.encode_reduction" $arguments
    }
    if ($Task -in @("benchmark-reduction", "all")) {
        Invoke-Module "src.cdp_classification.benchmark_reduction" (@("--models") + $Models)
    }
    if ($Task -in @("benchmark-other", "all")) {
        Invoke-Module "src.cdp_classification.benchmark_other_sections"
    }
}
finally {
    Pop-Location
}
