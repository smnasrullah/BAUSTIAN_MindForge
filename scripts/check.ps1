# Checks, inside Docker (no local node/python needed). One line per step; failures only.
# Usage: scripts\check.ps1 [-Backend] [-Frontend] [-E2E] [-Slow] [-Full] [-Up]
#   (none)     FAST tier: ruff, pytest -m "not slow", tsc, eslint, vitest
#   -Backend   ruff + fast pytest        -Frontend  tsc + eslint + vitest
#   -Slow      pytest -m slow (model training, full synthetic set, ML gate)
#   -E2E       Playwright smoke against the running stack (start it with -Up)
#   -Up        rebuild app images with the /dev/kit route and start the stack
#   -Full      everything: ruff, all pytest, tsc, eslint, vitest, -Up, e2e
#   -E2ETimeout <sec>  Playwright step limit (else env CHECK_E2E_TIMEOUT, else 900; suite ~7-8 min)
#   -PytestTimeout <sec>  pytest step limit (else env CHECK_PYTEST_TIMEOUT, else 300; -Slow/-Full steps keep 1200 unless set)
param([switch]$Backend, [switch]$Frontend, [switch]$E2E, [switch]$Slow, [switch]$Full,
      [switch]$Up, [int]$E2ETimeout = 0, [int]$PytestTimeout = 0)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$runBackend = $Full -or $Backend -or -not ($Frontend -or $E2E -or $Slow -or $Up)
$runFrontend = $Full -or $Frontend -or -not ($Backend -or $E2E -or $Slow -or $Up)
$runSlow = $Full -or $Slow
$runUp = $Full -or $Up
$runE2E = $Full -or $E2E
if ($E2ETimeout -le 0) { $E2ETimeout = if ($env:CHECK_E2E_TIMEOUT -match '^\d+$') { [int]$env:CHECK_E2E_TIMEOUT } else { 900 } }
$pytestSet = $PytestTimeout -gt 0 -or $env:CHECK_PYTEST_TIMEOUT -match '^\d+$'
if ($PytestTimeout -le 0) { $PytestTimeout = if ($env:CHECK_PYTEST_TIMEOUT -match '^\d+$') { [int]$env:CHECK_PYTEST_TIMEOUT } else { 300 } }
$pytestLongTimeout = if ($pytestSet) { $PytestTimeout } else { 1200 }

# --- concurrency lock ------------------------------------------------------------------------
$lock = Join-Path $PSScriptRoot '.check.lock'
if (Test-Path $lock) {
  $holder = (Get-Content $lock -ErrorAction SilentlyContinue | Select-Object -First 1)
  $age = (Get-Date) - (Get-Item $lock).LastWriteTime
  $alive = $holder -match '^\d+$' -and (Get-Process -Id ([int]$holder) -ErrorAction SilentlyContinue)
  if ($alive -and $age.TotalMinutes -lt 30) {
    Write-Host "BUSY  another check is running (pid $holder). Lock: scripts/.check.lock"
    exit 2
  }
  Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
try { $fs = [IO.File]::Open($lock, 'CreateNew', 'Write', 'Read') } catch {
  Write-Host 'BUSY  another check just started. Lock: scripts/.check.lock'; exit 2
}
$w = New-Object IO.StreamWriter($fs); $w.WriteLine($PID); $w.Flush()

$failed = 0
$tag = "agentpulse-check-$PID"
# Image name prefix = compose project. Set COMPOSE_PROJECT_NAME=agentpulse-verify (with
# COMPOSE_FILE=<absolute path>\docker-compose.yml;<absolute path>\docker-compose.verify.yml) to run
# -Up / -E2E on the isolated stack.
$proj = if ($env:COMPOSE_PROJECT_NAME) { $env:COMPOSE_PROJECT_NAME } else { 'agentpulse' }

function Remove-StaleContainers {
  $rows = docker ps -a --filter 'name=agentpulse-check-' --format '{{.Names}}|{{.RunningFor}}' 2>$null
  foreach ($r in $rows) {
    $name, $for = $r -split '\|', 2
    $old = ($for -match 'hour|day|week|month|year') -or
           (($for -match '^(\d+) minutes') -and [int]$Matches[1] -ge 15)
    if ($old) { docker rm -f $name 2>$null | Out-Null; Write-Host "      removed stale $name" }
  }
}

# Filter applied to a failing step's output; falls back to its last 15 lines.
$failPattern = '^(FAILED|ERROR)\s|error TS\d+|^\s*\d+:\d+\s+error|:\d+:\d+: [A-Z]+\d+|' +
  '\bFAIL\b|^\s*[x' + [char]0xd7 + [char]0x2718 + ']\s|^\s*\d+\) |Error:|AssertionError|' +
  'exit code|BUSY|not ready'

function Invoke-Step([string]$Name, [int]$TimeoutSec, [string[]]$Cmd, [string]$Container = '') {
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $psi = New-Object Diagnostics.ProcessStartInfo('docker')
  $psi.Arguments = ($Cmd | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' '
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $p = [Diagnostics.Process]::Start($psi)
  $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
  $timedOut = -not $p.WaitForExit($TimeoutSec * 1000)
  if ($timedOut) {
    try { $p.Kill() } catch { }
    if ($Container) { docker rm -f $Container 2>$null | Out-Null }
    $code = 124
  } else { $p.WaitForExit(); $code = $p.ExitCode }
  $t = '{0,6:N1}s' -f $sw.Elapsed.TotalSeconds
  if ($code -eq 0) { Write-Host ("PASS  {0,-12} {1}" -f $Name, $t); return }
  $why = if ($timedOut) { "timeout ${TimeoutSec}s" } else { "exit $code" }
  Write-Host ("FAIL  {0,-12} {1}  ({2})" -f $Name, $t, $why)
  $lines = ((($so.Result + "`n" + $se.Result) -replace "\x1b\[[0-9;]*m", '') -split "`r?`n") |
    Where-Object { $_ -and $_ -notmatch '^\s*(Container|Network|Volume) \S+ |RemoteException$' }
  $hits = @($lines | Where-Object { $_ -match $failPattern })
  if (-not $hits) { $hits = @($lines | Select-Object -Last 15) }
  $hits | Select-Object -First 30 | ForEach-Object { Write-Host "      $_" }
  $script:failed++
}

function Invoke-Tool([string]$Name, [int]$TimeoutSec, [string]$Service, [string[]]$ToolCmd) {
  $c = "$tag-$Name"
  Invoke-Step $Name $TimeoutSec (@('compose', '--profile', 'tools', '--profile', 'e2e', 'run',
    '--rm', '--no-deps', '-T', '--name', $c, $Service) + $ToolCmd) $c
}

# No secret in git: no tracked .env, no known key shapes, and none of this machine's .env secret
# values in any tracked file. Prints file names only, never a value.
$secretShapes = 'sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-)?[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16}|' +
  'gh[pousr]_[A-Za-z0-9]{36}|xox[abprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
function Test-Secrets {
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $git = (Get-Command git.exe, git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
  if (-not $git) { Write-Host 'SKIP  secrets      git not found'; return }
  $files = @(& $git ls-files)
  if ($LASTEXITCODE -ne 0) { $files = @(); $bad = @('git ls-files failed') } else { $bad = @() }
  $bad += @($files | Where-Object { $_ -match '(^|/)\.env(\.|$)' -and $_ -notmatch '\.example$' } |
    ForEach-Object { "tracked env file: $_" })
  $bad += @(& $git grep -I -l -E $secretShapes 2>$null | ForEach-Object { "key-shaped string: $_" })
  $secretKeys = '^\s*(JWT_SECRET|LLM_API_KEY|POSTGRES_PASSWORD|DEMO_\w+_PASSWORD)\s*=\s*(.+?)\s*$'
  $published = @{}
  if (Test-Path .env.example) {
    foreach ($line in Get-Content .env.example) { if ($line -match $secretKeys) { $published[$Matches[1]] = $Matches[2] } }
  }
  if (Test-Path .env) {
    foreach ($line in Get-Content .env) {
      if ($line -match $secretKeys) {
        $key = $Matches[1]; $value = $Matches[2].Trim('"', "'")
        # Short values and the published .env.example defaults (demo passwords) are not secrets.
        if ($value.Length -lt 16 -or $value -eq $published[$key]) { continue }
        $bad += @(& $git grep -I -l -F -e $value 2>$null | ForEach-Object { "value of ${key}: $_" })
      }
    }
  }
  $t = '{0,6:N1}s' -f $sw.Elapsed.TotalSeconds
  if (-not $bad) { Write-Host ("PASS  {0,-12} {1}" -f 'secrets', $t); return }
  Write-Host ("FAIL  {0,-12} {1}  (exit 1)" -f 'secrets', $t)
  $bad | Select-Object -First 30 | ForEach-Object { Write-Host "      $_" }
  $script:failed++
}

# Rebuild an image only when it is missing or its Dockerfile / dependency files changed.
function Update-Images([string]$ProfileName, [string[]]$Services, [string[]]$Inputs) {
  $files = $Inputs | ForEach-Object { Get-ChildItem $_ -ErrorAction SilentlyContinue } | Sort-Object FullName
  $sig = ($files | ForEach-Object { (Get-FileHash $_.FullName -Algorithm SHA256).Hash }) -join ''
  $stamp = Join-Path $PSScriptRoot (".check-build-" + ($Services -join '_') + '.stamp')
  $missing = $Services | Where-Object { -not (docker image ls -q "$proj-$_" 2>$null) }
  $prev = if (Test-Path $stamp) { Get-Content $stamp -Raw } else { '' }
  if (-not $missing -and $prev.Trim() -eq $sig) { return }
  Invoke-Step ('build:' + ($Services -join ',')) 900 (@('compose', '--profile', $ProfileName, 'build', '-q') + $Services)
  if (-not $script:failed) { Set-Content -Path $stamp -Value $sig -Encoding ascii -NoNewline }
}

try {
  Remove-StaleContainers
  if ($runBackend -or $runE2E) { Test-Secrets }
  if ($runBackend -or $runSlow) {
    Update-Images 'tools' @('backend-tools') @('backend/Dockerfile', 'backend/requirements*.txt')
  }
  if ($runFrontend) {
    Update-Images 'tools' @('frontend-tools') @('frontend/Dockerfile', 'frontend/package.json', 'frontend/package-lock.json')
  }
  if ($runE2E) {
    Update-Images 'e2e' @('e2e') @('e2e/Dockerfile', 'e2e/package.json', 'e2e/package-lock.json')
  }
  if ($failed) { exit 1 }

  $pytest = @('pytest', '-q', '-p', 'no:cacheprovider', '--tb=line', '-rfE')
  if ($runBackend) {
    Invoke-Tool 'ruff' 60 'backend-tools' @('ruff', 'check', '.')
    if ($Full) { Invoke-Tool 'pytest-all' $pytestLongTimeout 'backend-tools' $pytest }
    else { Invoke-Tool 'pytest' $PytestTimeout 'backend-tools' ($pytest + @('-m', 'not slow')) }
  }
  if ($runSlow -and -not $Full) { Invoke-Tool 'pytest-slow' $pytestLongTimeout 'backend-tools' ($pytest + @('-m', 'slow')) }
  if ($runFrontend) {
    Invoke-Tool 'typecheck' 180 'frontend-tools' @('npm', 'run', '-s', 'typecheck')
    Invoke-Tool 'eslint' 180 'frontend-tools' @('npm', 'run', '-s', 'lint')
    Invoke-Tool 'vitest' 240 'frontend-tools' @('npm', 'run', '-s', 'test')
  }
  if ($runUp) {
    # App images built from the working tree, with the dev-only /dev/kit route e2e visits.
    $env:VITE_DEV_KIT = 'true'
    Invoke-Step 'up' 900 @('compose', 'up', '-d', '--build', '--wait', 'db', 'backend', 'frontend')
    Remove-Item Env:VITE_DEV_KIT -ErrorAction SilentlyContinue
  }
  if ($runE2E) {
    $port = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { '5173' }
    # `up --wait` returns once /health answers; bootstrap (migrate, precompute) may still run.
    $ready = $false
    $until = (Get-Date).AddSeconds(600)
    while ($true) {
      try { $ready = (Invoke-RestMethod "http://localhost:$port/api/v1/system/status" -TimeoutSec 5).ready } catch { }
      if ($ready -or (Get-Date) -gt $until) { break }
      Start-Sleep -Seconds 3
    }
    $kit = $null
    try {
      $kit = (docker image inspect "$proj-frontend" --format '{{json .Config.Labels}}' 2>$null |
        ConvertFrom-Json).'agentpulse.devkit'
    } catch { }
    if (-not $ready) {
      Write-Host 'FAIL  e2e          stack not ready; start it with: scripts\check.ps1 -Up'; $failed++
    } elseif ($kit -ne 'true') {
      Write-Host 'FAIL  e2e          frontend built without /dev/kit; rebuild with: scripts\check.ps1 -Up'; $failed++
    } else {
      # Known state for reruns without a DB reset (bootstrap.py e2e-fixtures: inbox, lockout).
      $before = $failed
      Invoke-Step 'e2e-seed' 60 @('compose', 'exec', '-T', 'backend', 'python', 'bootstrap.py', 'e2e-fixtures')
      if ($failed -eq $before) { Invoke-Tool 'e2e' $E2ETimeout 'e2e' @() }
    }
  }
} finally {
  $w.Dispose(); $fs.Dispose()
  Remove-Item $lock -Force -ErrorAction SilentlyContinue
}

if ($failed) { Write-Host "$failed check(s) failed"; exit 1 }
Write-Host 'All checks passed'
exit 0
