$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js 22.12+ (24 recommended), then reopen the terminal.'
}
& node -e "const [a,b]=process.versions.node.split('.').map(Number);if(a<22||(a===22&&b<12))process.exit(1)"
if ($LASTEXITCODE -ne 0) { throw 'Node.js 22.12+ is required.' }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.13 -m venv .venv
    } else {
        & python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create the project Python environment.' }
}
& .\.venv\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3, 13), 'Use Python 3.13 for the pinned dependencies.'"
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.13 and recreate only the new checkout virtual environment.' }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
if (-not (Test-Path -LiteralPath 'data\reports\demo.json')) {
    & .\.venv\Scripts\python.exe scripts\build_demo.py
    if ($LASTEXITCODE -ne 0) { throw 'Demo report generation failed.' }
}
Push-Location -LiteralPath frontend
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Node dependency installation failed.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally {
    Pop-Location
}
Write-Host 'Existing reports and tribute records have been preserved. No climate data is downloaded during preparation.'
