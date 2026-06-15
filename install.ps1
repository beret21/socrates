#Requires -Version 5.1
<#
  Socrates — Windows bootstrap (PowerShell)

  Installs the prerequisites with winget, then hands off to install.sh under
  Git Bash. This exists because the SessionStart hook and install.sh both run
  through bash — if bash is missing, nothing (not even `socrates doctor`) can
  explain why. This script is the one non-bash entry point.

  Usage (from the repo root):
      powershell -ExecutionPolicy Bypass -File install.ps1

  Notes
  - winget itself ships with Windows 10/11 as "App Installer"; if it is missing,
    install that from the Microsoft Store first.
  - winget exposes fzf/jq only as App Execution Alias stubs that Git Bash cannot
    exec; install.sh copies the real .exe onto ~/.local/bin, so that is handled
    on the bash side.
  - Open a NEW terminal after this finishes so PATH / winget changes apply.
#>
$ErrorActionPreference = 'Stop'

function Test-Cmd($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

Write-Host "== Socrates Windows bootstrap =="

if (-not (Test-Cmd 'winget')) {
    Write-Error "winget not found. Install 'App Installer' from the Microsoft Store, then re-run."
    exit 1
}

# Prerequisites. fzf/jq/sqlite3 are portable; git/python use installers.
$pkgs = @(
    @{ id = 'Git.Git';            cmd = 'git'     },
    @{ id = 'junegunn.fzf';       cmd = 'fzf'     },
    @{ id = 'jqlang.jq';          cmd = 'jq'      },
    @{ id = 'Python.Python.3.12'; cmd = 'python'  },
    @{ id = 'SQLite.SQLite';      cmd = 'sqlite3' }   # optional, only for `socrates mem`
)
foreach ($p in $pkgs) {
    if (Test-Cmd $p.cmd) { Write-Host ("  ok   {0} already present" -f $p.cmd); continue }
    Write-Host ("  .... installing {0}" -f $p.id)
    winget install -e --id $p.id --source winget --silent `
        --accept-package-agreements --accept-source-agreements
}

# Locate Git Bash. PATH may not be refreshed in this session, so fall back to
# the default install locations.
$bash = (Get-Command bash -ErrorAction SilentlyContinue).Source
if (-not $bash) {
    foreach ($c in @("$env:ProgramFiles\Git\bin\bash.exe",
                     "${env:ProgramFiles(x86)}\Git\bin\bash.exe")) {
        if (Test-Path $c) { $bash = $c; break }
    }
}
if (-not $bash) {
    Write-Warning "Git Bash not found in this session. Open a NEW terminal, then run: bash install.sh"
    exit 0
}

# Run the bash installer from this script's directory (the repo root).
$root = $PSScriptRoot -replace '\\', '/'
Write-Host "== Running install.sh under Git Bash =="
& $bash -lc "cd '$root' && bash install.sh"

Write-Host ""
Write-Host "Done. Open a NEW Git Bash window so PATH changes apply, then run: socrates help"
