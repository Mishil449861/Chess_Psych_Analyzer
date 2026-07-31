param(
    [string]$Username,
    [int]$MaxGames = 80
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot 'venv\Scripts\python.exe'

function Get-BootstrapPython {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @('py', '-3') }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @('python') }
    throw 'Python 3.11 or newer is required. Install Python from python.org, then run this file again.'
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host 'First run: creating a local Python environment...' -ForegroundColor Cyan
    $Bootstrap = Get-BootstrapPython
    $BootstrapArgs = @($Bootstrap | Select-Object -Skip 1) + @('-m', 'venv', (Join-Path $ProjectRoot 'venv'))
    & $Bootstrap[0] @BootstrapArgs
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install dependencies. Check your internet connection and try again.' }
}

if (-not $Username) { $Username = Read-Host 'Enter your public Chess.com username' }
if ($Username -notmatch '^[A-Za-z0-9_-]{1,50}$') { throw 'That username contains unsupported characters.' }
if ($MaxGames -lt 40 -or $MaxGames -gt 300) { throw 'Choose between 40 and 300 games.' }

$SafeName = $Username.ToLowerInvariant() -replace '[^a-z0-9_-]', '_'
$OutputDir = Join-Path $ProjectRoot 'demos\my_results'
$Evidence = Join-Path $OutputDir "${SafeName}_blitz_evidence.json"
$Report = Join-Path $OutputDir "${SafeName}_report.html"
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

Write-Host "Analyzing $Username's public 3- and 5-minute blitz games..." -ForegroundColor Cyan
$env:PYTHONPATH = (Join-Path $ProjectRoot 'src')
& $VenvPython (Join-Path $ProjectRoot 'scripts\build_personal_pattern_demo.py') $Username `
    --max-games $MaxGames --threads 1 --hash-mb 16 --skip-ai-labels --output $Evidence
if ($LASTEXITCODE -ne 0) { throw 'Analysis stopped before results were produced. The messages above identify the failing step.' }

& $VenvPython (Join-Path $ProjectRoot 'scripts\build_personal_report.py') $Evidence --output $Report
if ($LASTEXITCODE -ne 0) { throw 'Analysis succeeded, but the personal report could not be built.' }

Write-Host "Done. Opening $Report" -ForegroundColor Green
Start-Process -FilePath $Report
