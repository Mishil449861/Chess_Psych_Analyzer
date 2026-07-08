param(
    [switch]$RealDemo,
    [switch]$TalDemo,
    [switch]$CrossEraDemo,
    [switch]$FullSmoke,
    [switch]$Pytest
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code ${LASTEXITCODE}: $Python $($Arguments -join ' ')"
    }
}

$Python = "python"
$RealPython = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
if (Test-Path $RealPython) {
    $Python = $RealPython
}

$pythonPathParts = @("src")
$BorrowedSitePackages = Join-Path $Root "venv\Lib\site-packages"
if (Test-Path $BorrowedSitePackages) {
    $pythonPathParts += "venv\Lib\site-packages"
}
$env:PYTHONPATH = ($pythonPathParts -join ";")

$Stockfish = Join-Path $Root "vendor\ChessEngine\stockfish-windows-x86-64-sse41-popcnt.exe"
if (Test-Path $Stockfish) {
    $env:STOCKFISH_PATH = $Stockfish
}
$env:STOCKFISH_THREADS = if ($env:STOCKFISH_THREADS) { $env:STOCKFISH_THREADS } else { "1" }
$env:STOCKFISH_HASH_MB = if ($env:STOCKFISH_HASH_MB) { $env:STOCKFISH_HASH_MB } else { "16" }

$AnyDemo = $RealDemo -or $TalDemo -or $CrossEraDemo
$RunSmoke = $FullSmoke -or -not $AnyDemo

Write-Host "== Chess Psych local check =="
Write-Host "Python: $Python"
Write-Host "PYTHONPATH: $env:PYTHONPATH"
if ($env:STOCKFISH_PATH) {
    Write-Host "Stockfish: $env:STOCKFISH_PATH"
    Write-Host "Stockfish memory: Threads=$env:STOCKFISH_THREADS Hash=${env:STOCKFISH_HASH_MB}MB"
}

Write-Host "`n[1/4] Compile Python files"
$files = Get-ChildItem src\chess_psych,apps,scripts,tests -Filter *.py -Recurse | ForEach-Object { $_.FullName }
Invoke-Python -Arguments (@("-m", "py_compile") + $files)

if ($RunSmoke) {
    Write-Host "`n[2/4] CLI import/help"
    Invoke-Python -Arguments @("-m", "chess_psych.cli", "--help")
} else {
    Write-Host "`n[2/4] CLI import/help skipped for quick demo rebuild. Add -FullSmoke to run it."
}

if ($RunSmoke) {
    Write-Host "`n[3/4] Smoke pipeline"
    Invoke-Python -Arguments @("scripts\smoke_test.py")
} else {
    Write-Host "`n[3/4] Smoke pipeline skipped for quick demo rebuild. Add -FullSmoke to run it."
}

if ($Pytest) {
    Write-Host "`n[4/4] Pytest suite"
    Invoke-Python -Arguments @("-m", "pytest", "tests", "-v")
} else {
    Write-Host "`n[4/4] Pytest skipped. Run with -Pytest after installing pytest."
}

if ($RealDemo) {
    Write-Host "`n[extra] Rebuild real-player demo"
    Invoke-Python -Arguments @("tests\test_real_player_same_move_demo.py")
}

if ($TalDemo) {
    Write-Host "`n[extra] Rebuild Tal genius demo"
    Invoke-Python -Arguments @("tests\test_tal_genius_demo.py")
}

if ($CrossEraDemo) {
    Write-Host "`n[extra] Rebuild cross-era genius demo"
    Invoke-Python -Arguments @("tests\test_cross_era_genius_demo.py")
}

Write-Host "`nLocal check complete."
