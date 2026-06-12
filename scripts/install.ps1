# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install the Blender MCP plugin on native Windows - no make, no host
# Python required. (From WSL2, use scripts/install.sh instead.)
#
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#   ... -Uninstall          remove everything again
#   ... -PackagesOnly       pip packages, skip the add-on
#   ... -ExtensionOnly      add-on, skip the pip packages
#
# Two halves, both idempotent:
#   1. pip-install mcp/ + agent/ + mcp_ext/ into Blender's BUNDLED
#      Python ($env:BLENDER_PYTHON overrides discovery).
#   2. Build the add-on as a Blender extension and install+enable it
#      into the user_default repository via Blender's own extension CLI
#      ($env:BLENDER_BIN overrides binary discovery).

param(
    [switch]$Uninstall,
    [switch]$PackagesOnly,
    [switch]$ExtensionOnly
)

$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $PSScriptRoot
$AddonDir = Join-Path $RepoDir "addon\blender_mcp_addon"
$DistDir = Join-Path $RepoDir "dist"

function Note($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "error: $msg" -ForegroundColor Red; exit 1 }

# --- Locate the Blender binary ----------------------------------------------
function Find-Blender {
    if ($env:BLENDER_BIN -and (Test-Path $env:BLENDER_BIN)) { return $env:BLENDER_BIN }
    $onPath = Get-Command blender -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $candidates = Get-ChildItem "C:\Program Files\Blender Foundation\*\blender.exe" `
        -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    if ($candidates) { return $candidates[0].FullName }
    Fail "could not find blender.exe - set `$env:BLENDER_BIN to its path"
}

# --- Locate Blender's bundled Python ----------------------------------------
function Find-BlenderPython($blender) {
    if ($env:BLENDER_PYTHON -and (Test-Path $env:BLENDER_PYTHON)) { return $env:BLENDER_PYTHON }
    $expr = 'import sys,glob,os; b=os.path.join(sys.prefix,"bin"); ' +
            'c=sorted(glob.glob(os.path.join(b,"python.exe"))); ' +
            'print("BLPY="+(c[-1] if c else ""))'
    $out = & $blender --background --factory-startup --python-expr $expr 2>$null |
        Select-String -Pattern "^BLPY=(.+)$"
    if ($out) {
        $path = $out.Matches[0].Groups[1].Value.Trim()
        if (Test-Path $path) { return $path }
    }
    Fail "could not locate Blender's bundled python.exe - set `$env:BLENDER_PYTHON"
}

$Blender = Find-Blender
Note "Blender: $Blender"

# --- 1. Python packages into Blender's bundled interpreter ------------------
if (-not $ExtensionOnly) {
    $BlPy = Find-BlenderPython $Blender
    Note "Blender Python: $BlPy"
    if ($Uninstall) {
        Note "Removing python packages"
        & $BlPy -m pip uninstall -y blender-mcp-extensions blender-mcp-agent blender-mcp
    } else {
        Note "Installing python packages (mcp, agent, mcp_ext)"
        & $BlPy -m ensurepip --upgrade 2>$null | Out-Null
        & $BlPy -m pip install --upgrade `
            (Join-Path $RepoDir "mcp") (Join-Path $RepoDir "agent") (Join-Path $RepoDir "mcp_ext")
        if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }
    }
}

# --- 2. The add-on, as a Blender extension ----------------------------------
if (-not $PackagesOnly) {
    if ($Uninstall) {
        Note "Removing the add-on extension"
        & $Blender --command extension remove user_default.mcp
        if ($LASTEXITCODE -ne 0) { Fail "extension removal failed (was it installed?)" }
    } else {
        Note "Building the add-on extension"
        New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
        & $Blender --command extension build --source-dir $AddonDir --output-dir $DistDir
        if ($LASTEXITCODE -ne 0) { Fail "extension build failed" }
        $zip = Get-ChildItem (Join-Path $DistDir "*.zip") |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $zip) { Fail "no extension zip produced in $DistDir" }
        Note "Installing $($zip.Name) into Blender (user_default, enabled)"
        & $Blender --command extension install-file -r user_default -e $zip.FullName
        if ($LASTEXITCODE -ne 0) { Fail "extension install failed" }
    }
}

if ($Uninstall) {
    Note "Done. Restart Blender to drop any already-loaded modules."
} else {
    Note "Done. Start Blender - the MCP bridge starts automatically"
    Note "(Edit > Preferences > Add-ons > MCP to configure ports, agent, skills)."
}
