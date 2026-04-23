# ACC Connector — install script (Windows PowerShell)
#
# Usage:
#   .\install.ps1
#   .\install.ps1 -ExtensionId <ID>
#
# Creates a dedicated venv at %LOCALAPPDATA%\acc-connector\venv, installs the
# package into it, and optionally registers the native messaging host manifests
# for Chrome and Firefox. No system-wide pip install, no elevation needed.

param(
    [string]$ExtensionId = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ------------------------------------------------------------------ Python check
try {
    $pyVersion = python --version 2>&1
    if ($pyVersion -notmatch "Python 3\.(1[0-9]|[2-9]\d)") {
        throw "Python 3.10+ required, found: $pyVersion"
    }
} catch {
    Write-Error "Python 3.10 or later is required. Download from https://python.org"
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $env:LOCALAPPDATA "acc-connector\venv"

# ------------------------------------------------------------------ Create / reuse venv
if (-not (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) {
    Write-Host "Creating venv at $VenvDir..."
    python -m venv $VenvDir
}

# ------------------------------------------------------------------ Install package
Write-Host "Installing acc-connector-host into venv..."
& "$VenvDir\Scripts\pip.exe" install --quiet -e $ScriptDir
Write-Host "Done."
Write-Host ""

# ------------------------------------------------------------------ Register manifests
$SetupExe = "$VenvDir\Scripts\acc-connector-setup.exe"
if ($ExtensionId -ne "") {
    Write-Host "Registering native messaging manifests for extension ID: $ExtensionId"
    & $SetupExe --extension-id $ExtensionId
} else {
    Write-Host "To register native messaging manifests, load the extension in your"
    Write-Host "browser, copy the Extension ID, then run:"
    Write-Host ""
    Write-Host "  $SetupExe --extension-id <YOUR_EXTENSION_ID>"
    Write-Host ""
    Write-Host "Or re-run this script:"
    Write-Host "  .\install.ps1 -ExtensionId <YOUR_EXTENSION_ID>"
}
