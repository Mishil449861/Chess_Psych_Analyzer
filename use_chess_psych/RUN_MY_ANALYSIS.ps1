param(
    [string]$Username,
    [ValidateSet('Ask', 'Blitz', 'Bullet', 'Rapid', 'Custom')]
    [string]$Format = 'Ask',
    [string]$AllowedTimeControls,
    [int]$MaxGames = 120,
    [ValidateRange(6, 18)]
    [int]$ScreenDepth = 8,
    [ValidateRange(8, 22)]
    [int]$ConfirmDepth = 14
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

function Choose-Format {
    param([string]$RequestedFormat, [string]$RequestedControls)

    if ($RequestedFormat -eq 'Ask') {
        Write-Host ''
        Write-Host 'Choose games to analyze:' -ForegroundColor Cyan
        Write-Host '  1. Blitz: 3 and 5 minutes (recommended)'
        Write-Host '  2. Bullet: all recent rated bullet games'
        Write-Host '  3. Rapid: all recent rated rapid games'
        Write-Host '  4. Custom: choose an exact time control'
        $choice = Read-Host 'Enter 1, 2, 3, or 4 (default 1)'
        switch ($choice) {
            '2' { $RequestedFormat = 'Bullet' }
            '3' { $RequestedFormat = 'Rapid' }
            '4' { $RequestedFormat = 'Custom' }
            default { $RequestedFormat = 'Blitz' }
        }
    }

    switch ($RequestedFormat) {
        'Blitz'  { return @{ TimeClass = 'blitz'; Controls = if ($RequestedControls) { $RequestedControls } else { '180,300' }; Name = '3- and 5-minute blitz' } }
        'Bullet' { return @{ TimeClass = 'bullet'; Controls = if ($RequestedControls) { $RequestedControls } else { 'any' }; Name = 'rated bullet' } }
        'Rapid'  { return @{ TimeClass = 'rapid'; Controls = if ($RequestedControls) { $RequestedControls } else { 'any' }; Name = 'rated rapid' } }
        'Custom' {
            $class = Read-Host 'Game type: bullet, blitz, or rapid'
            $class = $class.Trim().ToLowerInvariant()
            if ($class -notin @('bullet', 'blitz', 'rapid')) {
                throw 'Choose bullet, blitz, or rapid for a custom run.'
            }
            $controls = if ($RequestedControls) { $RequestedControls } else { Read-Host 'Exact control, for example 180, 300, or 180+2' }
            if ([string]::IsNullOrWhiteSpace($controls)) {
                throw 'Enter an exact time control, or choose Bullet, Blitz, or Rapid to use all available controls.'
            }
            return @{ TimeClass = $class; Controls = $controls.Trim(); Name = "$class games with control $controls" }
        }
    }
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
$Selection = Choose-Format $Format $AllowedTimeControls

$SafeName = $Username.ToLowerInvariant() -replace '[^a-z0-9_-]', '_'
$OutputDir = Join-Path $ProjectRoot 'demos\my_results'
$ControlSlug = $Selection.Controls.ToLowerInvariant() -replace '[^a-z0-9+,_-]', '_' -replace '\+', 'p' -replace ',', '_'
$Evidence = Join-Path $OutputDir "${SafeName}_$($Selection.TimeClass)_${ControlSlug}_evidence.json"
$Report = Join-Path $OutputDir "${SafeName}_$($Selection.TimeClass)_${ControlSlug}_report.html"
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

Write-Host "Analyzing $Username's public $($Selection.Name) games..." -ForegroundColor Cyan
$env:PYTHONPATH = (Join-Path $ProjectRoot 'src')
$StockfishPath = & $VenvPython -c "from chess_psych.stockfish_pool import get_stockfish_path; print(get_stockfish_path())"
if ($LASTEXITCODE -ne 0) { throw 'Could not check for Stockfish. See use_chess_psych\INSTALL_STOCKFISH.md.' }
if ($StockfishPath -eq 'stockfish') {
    $StockfishCommand = Get-Command stockfish -ErrorAction SilentlyContinue
    if (-not $StockfishCommand) {
        throw 'Stockfish is required but was not found. Follow use_chess_psych\INSTALL_STOCKFISH.md, then run this again.'
    }
} elseif (-not (Test-Path -LiteralPath $StockfishPath)) {
    throw 'Stockfish is required but the configured executable was not found. Follow use_chess_psych\INSTALL_STOCKFISH.md.'
}
$env:STOCKFISH_PATH = $StockfishPath
& $VenvPython (Join-Path $ProjectRoot 'scripts\build_personal_pattern_demo.py') $Username `
    --time-class $Selection.TimeClass --allowed-time-controls $Selection.Controls --max-games $MaxGames `
    --screen-depth $ScreenDepth --confirm-depth $ConfirmDepth `
    --threads 1 --hash-mb 16 --refresh-games --skip-ai-labels --output $Evidence
if ($LASTEXITCODE -ne 0) { throw 'Analysis stopped before results were produced. The messages above identify the failing step.' }

& $VenvPython (Join-Path $ProjectRoot 'scripts\build_personal_report.py') $Evidence --output $Report
if ($LASTEXITCODE -ne 0) { throw 'Analysis succeeded, but the personal report could not be built.' }

Write-Host "Done. Opening $Report" -ForegroundColor Green
Start-Process -FilePath $Report
