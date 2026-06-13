# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install the Blender MCP plugin on native Windows - no make, no host
# Python, and NO PowerShell execution-policy changes required.
#
# One-liner (recommended - copy/paste into PowerShell, nothing to clone):
#
#   irm https://raw.githubusercontent.com/hotspoons/blender-agent/main/scripts/install.ps1 | iex
#
# Execution policy never applies to code piped into `iex`, so this needs
# no admin rights and no `Set-ExecutionPolicy`. The script fetches the
# repo zip into %LOCALAPPDATA%\blender-agent and installs from there.
#
# To pass options through the one-liner, wrap it in a scriptblock:
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/hotspoons/blender-agent/main/scripts/install.ps1))) -Uninstall
#
# From a local checkout (uses the files on disk, no download):
#
#   scripts\install.cmd                 (double-click friendly; no policy change)
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#
# Options: -Uninstall  -PackagesOnly  -ExtensionOnly
#          -BlenderBin <path>   pin blender.exe (else: registry + PATH discovery)
#          -Ref <branch|tag>    which revision to fetch when bootstrapping (default: main)
#
# Two halves, both idempotent:
#   1. pip-install mcp/ + agent/ + mcp_ext/ into Blender's BUNDLED
#      Python ($env:BLENDER_PYTHON overrides discovery).
#   2. Build the add-on as a Blender extension and install+enable it
#      into the user_default repository via Blender's own extension CLI.

param(
    [switch]$Uninstall,
    [switch]$PackagesOnly,
    [switch]$ExtensionOnly,
    [string]$BlenderBin,
    [string]$Ref = "main",
    [string]$RepoUrl = "https://github.com/hotspoons/blender-agent"
)

$ErrorActionPreference = "Stop"

function Note($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "error: $msg" -ForegroundColor Red; exit 1 }

# --- Locate the repo: a local checkout, or fetch it (one-liner case) --------
# Under `irm | iex` there is no script file on disk, so $PSScriptRoot is
# empty and we download the source. From a real checkout we use it as-is.
function Resolve-RepoDir {
    if ($PSScriptRoot) {
        $local = Split-Path -Parent $PSScriptRoot
        if (Test-Path (Join-Path $local "addon\blender_mcp_addon")) {
            Note "Using local checkout: $local"
            return $local
        }
    }

    [Net.ServicePointManager]::SecurityProtocol = `
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = "SilentlyContinue"

    $base = Join-Path $env:LOCALAPPDATA "blender-agent"
    $zip = Join-Path $base "src.zip"
    $extract = Join-Path $base "src"
    New-Item -ItemType Directory -Force -Path $base | Out-Null
    if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }

    $url = "$RepoUrl/archive/$Ref.zip"
    Note "Fetching $url"
    try {
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    } catch {
        Fail "download failed ($url): $($_.Exception.Message)"
    }
    # .NET's extractor is many times faster than Expand-Archive on an
    # archive of thousands of small files (the bundled API/manual docs).
    Note "Extracting"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $extract)
    Remove-Item -Force $zip

    # GitHub wraps everything in a single <repo>-<ref> directory.
    $root = Get-ChildItem -LiteralPath $extract -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName "addon\blender_mcp_addon") } |
        Select-Object -First 1
    if (-not $root) { Fail "fetched archive has no addon/ - wrong repo or ref?" }
    Note "Fetched source: $($root.FullName)"
    return $root.FullName
}

# --- Locate the Blender binary, the way Windows actually records it ---------
# Priority: explicit override -> App Paths -> Uninstall InstallLocation ->
# the handler registered for .blend files -> PATH -> Store (Appx) -> a few
# well-known dirs. Every probe is a read-only query; none need admin.
function Test-BlenderExe($p) {
    return $p -and ($p -match 'blender\.exe"?$') -and (Test-Path -LiteralPath ($p.Trim('"')) -PathType Leaf)
}

function Get-FromAppPaths {
    foreach ($hive in 'HKLM:', 'HKCU:') {
        foreach ($wow in '', '\WOW6432Node') {
            $key = "$hive\SOFTWARE$wow\Microsoft\Windows\CurrentVersion\App Paths\blender.exe"
            try {
                $v = (Get-ItemProperty -LiteralPath $key -ErrorAction Stop).'(default)'
                if (Test-BlenderExe $v) { return $v.Trim('"') }
            } catch {}
        }
    }
    return $null
}

function Get-FromUninstall {
    $hits = @()
    $roots = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    foreach ($r in $roots) {
        Get-ItemProperty $r -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like 'Blender*' -and $_.InstallLocation } |
            ForEach-Object {
                $exe = Join-Path $_.InstallLocation 'blender.exe'
                if (Test-BlenderExe $exe) {
                    $hits += [pscustomobject]@{ Path = $exe; Ver = [string]$_.DisplayVersion }
                }
            }
    }
    if ($hits) {
        # Highest version wins when several are installed.
        return ($hits | Sort-Object { try { [version]$_.Ver } catch { [version]"0.0" } } -Descending |
            Select-Object -First 1).Path
    }
    return $null
}

function Get-FromBlendAssoc {
    # Whatever opens .blend files is, by definition, the user's Blender.
    $progids = @('blendfile')
    try {
        $uc = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.blend\UserChoice' -ErrorAction Stop).ProgId
        if ($uc) { $progids = @($uc) + $progids }
    } catch {}
    foreach ($id in $progids) {
        try {
            $cmd = (Get-ItemProperty "Registry::HKEY_CLASSES_ROOT\$id\shell\open\command" -ErrorAction Stop).'(default)'
            if ($cmd -match '"?([A-Za-z]:\\[^"]*?blender\.exe)"?') {
                if (Test-BlenderExe $matches[1]) { return $matches[1] }
            }
        } catch {}
    }
    return $null
}

function Get-FromAppx {
    try {
        $pkg = Get-AppxPackage -Name '*BlenderFoundation*' -ErrorAction SilentlyContinue |
            Sort-Object Version -Descending | Select-Object -First 1
        if ($pkg) {
            $hit = Get-ChildItem -LiteralPath $pkg.InstallLocation -Filter blender.exe -Recurse -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($hit) { return $hit.FullName }
        }
    } catch {}
    return $null
}

function Get-FromKnownDirs {
    $globs = @(
        "$env:ProgramFiles\Blender Foundation\*\blender.exe",
        "${env:ProgramFiles(x86)}\Blender Foundation\*\blender.exe",
        "$env:LOCALAPPDATA\Programs\Blender Foundation\*\blender.exe",
        "$env:ProgramFiles\Steam\steamapps\common\Blender\blender.exe",
        "${env:ProgramFiles(x86)}\Steam\steamapps\common\Blender\blender.exe",
        "$env:USERPROFILE\scoop\apps\blender\current\blender.exe"
    )
    $found = foreach ($g in $globs) {
        Get-ChildItem $g -ErrorAction SilentlyContinue
    }
    if ($found) { return ($found | Sort-Object FullName -Descending | Select-Object -First 1).FullName }
    return $null
}

function Find-Blender {
    if ($BlenderBin -and (Test-Path -LiteralPath $BlenderBin)) { return $BlenderBin }
    if ($env:BLENDER_BIN -and (Test-Path -LiteralPath $env:BLENDER_BIN)) { return $env:BLENDER_BIN }

    foreach ($probe in 'Get-FromAppPaths', 'Get-FromUninstall', 'Get-FromBlendAssoc', 'Get-FromAppx', 'Get-FromKnownDirs') {
        $hit = & $probe
        if ($hit) {
            Note ("Found Blender via {0}" -f ($probe -replace '^Get-From', ''))
            return $hit
        }
    }
    $onPath = Get-Command blender -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }

    Fail "could not find blender.exe - pass -BlenderBin <path> or set `$env:BLENDER_BIN"
}

# --- Locate Blender's bundled Python ----------------------------------------
function Find-BlenderPython($blender) {
    if ($env:BLENDER_PYTHON -and (Test-Path -LiteralPath $env:BLENDER_PYTHON)) { return $env:BLENDER_PYTHON }

    # Blender ships its interpreter next to blender.exe, under the versioned
    # folder: <blender dir>\<version>\python\bin\python.exe. Find it on disk -
    # no need to launch Blender (and no --python-expr arg-quoting headaches).
    $bdir = Split-Path -Parent $blender
    $globs = @(
        (Join-Path $bdir "*\python\bin\python.exe"),
        (Join-Path $bdir "python\bin\python.exe")
    )
    foreach ($g in $globs) {
        $hit = Get-ChildItem $g -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }

    # Fallback for unusual layouts: ask Blender, via a temp script file so no
    # quoting survives the PowerShell -> native-exe arg boundary.
    $tmp = Join-Path $env:TEMP "blpy_probe.py"
    @'
import sys, os, glob
cand = sorted(glob.glob(os.path.join(sys.prefix, "bin", "python*")))
print("BLPY=" + (cand[-1] if cand else ""))
'@ | Set-Content -LiteralPath $tmp -Encoding ASCII
    try {
        $out = & $blender --background --factory-startup --python $tmp 2>$null |
            Select-String -Pattern "^BLPY=(.+)$"
    } finally {
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
    }
    if ($out) {
        $path = $out.Matches[0].Groups[1].Value.Trim()
        if (Test-Path -LiteralPath $path) { return $path }
    }
    Fail "could not locate Blender's bundled python.exe - set `$env:BLENDER_PYTHON"
}

# --- Go ----------------------------------------------------------------------
$RepoDir = Resolve-RepoDir
$AddonDir = Join-Path $RepoDir "addon\blender_mcp_addon"
$DistDir = Join-Path $RepoDir "dist"

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
        if ($LASTEXITCODE -ne 0) {
            Fail ("pip install failed. If Blender lives under Program Files its bundled " +
                  "Python is write-protected - re-run this from an Administrator PowerShell, " +
                  "or install Blender somewhere user-writable.")
        }
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
