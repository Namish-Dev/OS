<#
.SYNOPSIS
    Launches Google Chrome with the Chrome DevTools Protocol (CDP) debugging
    port open, so Personal OS's CDPBrowserAdapter can enrich activity events
    with the active tab's URL and domain.

.WHY THIS EXISTS
    Chrome only opens the CDP debugging port (127.0.0.1:9222) if the flag
    --remote-debugging-port is passed at PROCESS LAUNCH. It cannot be turned
    on for an already-running Chrome window, and modern Chrome refuses to
    open the port against your default profile for security reasons.

    This script launches a SEPARATE Chrome instance, using an isolated
    profile directory, so:
        - Your normal Chrome (history, passwords, extensions, sessions)
          is never touched or read by Personal OS.
        - The debug port is reliably available for CDPBrowserAdapter.

.USAGE
    Run this script instead of opening Chrome from the taskbar/desktop
    while you want Personal OS to capture URLs/domains:

        powershell -ExecutionPolicy Bypass -File scripts\launch_chrome_debug.ps1

    Then verify the port is live:

        Invoke-WebRequest http://127.0.0.1:9222/json

    You should get back a JSON array of open tabs. If Chrome was already
    running from a normal shortcut, close ALL Chrome windows first, or the
    new instance will just hand off to the existing one and ignore the flag.

.NOTE
    This is a Phase 1 workaround, not the final architecture. Once
    Personal OS reaches Phase 4/8 (Automatic Research/Productivity),
    the intended long-term solution is a small Chrome extension that
    reports the active tab locally, so URL capture works against the
    user's normal, already-open browser (and translates more cleanly
    to Linux browsers later). See README.md > "Browser URL Capture".
#>

$ErrorActionPreference = "Stop"

# Isolated profile so this never touches your real Chrome data.
$ProfileDir = Join-Path $PSScriptRoot "..\.chrome-debug-profile"

# Resolve Chrome's install location (standard 64-bit path first).
$ChromeCandidates = @(
    "$Env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${Env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$Env:LocalAppData\Google\Chrome\Application\chrome.exe"
)

$ChromePath = $ChromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $ChromePath) {
    Write-Error "Could not find chrome.exe. Edit this script and set `$ChromePath manually."
    exit 1
}

Write-Host "Launching debug-enabled Chrome..."
Write-Host "  Executable : $ChromePath"
Write-Host "  Profile    : $ProfileDir"
Write-Host "  CDP port   : 9222"
Write-Host ""
Write-Host "If Chrome is already running from a normal shortcut, close it first"
Write-Host "or this instance may hand off to the existing one and 9222 will stay closed."
Write-Host ""

Start-Process -FilePath $ChromePath -ArgumentList @(
    "--remote-debugging-port=9222",
    "--user-data-dir=`"$ProfileDir`""
)

Start-Sleep -Seconds 2

try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:9222/json" -UseBasicParsing -TimeoutSec 3
    Write-Host "CDP is live. Open tabs detected: $((($response.Content | ConvertFrom-Json)).Count)"
} catch {
    Write-Warning "CDP endpoint did not respond yet. Give it a moment and re-check with:"
    Write-Warning "  Invoke-WebRequest http://127.0.0.1:9222/json"
}
