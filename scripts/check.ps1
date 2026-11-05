$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Create .venv and install the project with its dev extra before running checks.'
}
Push-Location (Join-Path $PSScriptRoot '..')
$coverageFile = Join-Path ([System.IO.Path]::GetTempPath()) ("docgen-coverage-" + [guid]::NewGuid() + ".json")
try {
    & $python -m pytest --cov=docgen --cov-report=term-missing "--cov-report=json:$coverageFile" @args
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    $coverage = Get-Content -Raw -LiteralPath $coverageFile | ConvertFrom-Json -AsHashtable
    if ($coverage.totals.covered_branches -lt (0.85 * $coverage.totals.num_branches)) {
        throw 'Overall branch coverage is below 85%.'
    }
    $critical = $coverage.files.GetEnumerator() |
        Where-Object { $_.Key -match '(allocation|persistence|store|recovery|quality|uniqueness)\.py$' }
    $covered = ($critical | ForEach-Object { $_.Value.summary.covered_branches } | Measure-Object -Sum).Sum
    $branches = ($critical | ForEach-Object { $_.Value.summary.num_branches } | Measure-Object -Sum).Sum
    if ($branches -gt 0 -and $covered -lt (0.95 * $branches)) {
        throw 'Critical allocation/persistence/recovery/quality branch coverage is below 95%.'
    }
    & $python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw 'Lint failed.' }
    & $python -m mypy
    if ($LASTEXITCODE -ne 0) { throw 'Type checks failed.' }
    & $python -m build --no-isolation
    if ($LASTEXITCODE -ne 0) { throw 'Package build failed.' }
} finally {
    if (Test-Path -LiteralPath $coverageFile) { Remove-Item -LiteralPath $coverageFile -Force }
    Pop-Location
}
