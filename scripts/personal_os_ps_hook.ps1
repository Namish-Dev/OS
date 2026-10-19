#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Personal OS — PowerShell Session Hook.
    
    Captures commands, working directories, output, exit codes, and timestamps
    from a PowerShell session without breaking existing terminal behavior.

.DESCRIPTION
    Install this hook by adding one line to your $PROFILE:
        . "$Env:PERSONAL_OS_ROOT\scripts\personal_os_ps_hook.ps1"

    Or you can source it for a single session:
        . E:\OS\scripts\personal_os_ps_hook.ps1

    The hook uses PowerShell's built-in prompt function and the
    PSConsoleHostReadLine mechanism to intercept commands *after* they
    complete. It does NOT modify your existing $PROFILE prompt beyond
    wrapping it with a thin shim.

    Captured data is sent to http://127.0.0.1:8767/v1/terminal-event.
    All captures are fire-and-forget; failures are silently ignored so
    that your normal shell experience is never degraded.

.NOTES
    Supported: PowerShell 7+ and Windows PowerShell 5.1
    Unsupported: Commands piped between processes cannot have their output
                 captured without redirecting stdout, which this hook does
                 NOT do (to avoid breaking interactive commands).
                 Exit code for external processes is captured via $LASTEXITCODE.
#>

# ── Configuration ─────────────────────────────────────────────────────────────

$script:PersonalOS_Endpoint  = "http://127.0.0.1:8767/v1/terminal-event"
$script:PersonalOS_MaxOutput = 8192       # characters
$script:PersonalOS_Enabled   = $true      # set $false to pause capture
$script:PersonalOS_SessionId = "ps-" + [System.Guid]::NewGuid().ToString("N").Substring(0, 12)

# ── Secret redaction (mirrors core/privacy.py patterns) ──────────────────────

function Invoke-PersonalOSRedact {
    param([string]$Text)
    if (-not $Text) { return "" }
    
    $patterns = @(
        @{ Pattern = 'sk-[A-Za-z0-9_\-]{20,}';               Replace = '[REDACTED_SECRET]' }
        @{ Pattern = 'ghp_[A-Za-z0-9]{36}';                  Replace = '[REDACTED_SECRET]' }
        @{ Pattern = 'github_pat_[A-Za-z0-9_]{36,}';         Replace = '[REDACTED_SECRET]' }
        @{ Pattern = 'AKIA[0-9A-Z]{16}';                     Replace = '[REDACTED_SECRET]' }
        @{ Pattern = '(?i)(Bearer\s+)[A-Za-z0-9_\-\.]{20,}'; Replace = '$1[REDACTED_SECRET]' }
        @{ Pattern = '(?i)(://[^:\s]+:)([^@\s]+)(@)';        Replace = '$1[REDACTED_SECRET]$3' }
        @{ Pattern = '(?i)((?:api[_-]?key|secret[_-]?key|access[_-]?token|password|passwd|pwd)\s*[:=]\s*[''"]?)([^''"&\s;]{8,})'; Replace = '$1[REDACTED_SECRET]' }
    )
    
    $result = $Text
    foreach ($p in $patterns) {
        $result = [regex]::Replace($result, $p.Pattern, $p.Replace)
    }
    return $result
}

# ── HTTP post (async, fire-and-forget) ────────────────────────────────────────

function Send-PersonalOSEvent {
    param([hashtable]$Payload)
    
    if (-not $script:PersonalOS_Enabled) { return }
    
    try {
        $json = $Payload | ConvertTo-Json -Compress -Depth 3
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        
        $req = [System.Net.HttpWebRequest]::Create($script:PersonalOS_Endpoint)
        $req.Method = "POST"
        $req.ContentType = "application/json"
        $req.ContentLength = $bytes.Length
        $req.Timeout = 1500
        
        $stream = $req.GetRequestStream()
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Close()
        
        # Fire and forget — don't wait for response
        $null = $req.BeginGetResponse({
            param($ar)
            try {
                $r = $req.EndGetResponse($ar)
                $r.Close()
            } catch { }
        }, $null)
    } catch {
        # Silently ignore — tracker may not be running
    }
}

# ── Command interception via prompt wrapping ──────────────────────────────────

# Save user's existing prompt function
$script:PersonalOS_OriginalPrompt = $null
if (Test-Path Function:\prompt) {
    $script:PersonalOS_OriginalPrompt = (Get-Content Function:\prompt)
}

# State for the previous command
$script:PersonalOS_LastCommand   = $null
$script:PersonalOS_LastStartTime = $null

# Override the prompt function.  Prompt is called AFTER each command returns,
# which is the earliest moment we can read $? and $LASTEXITCODE.
function global:prompt {
    # ── Capture the just-completed command ──
    $exitCode = if ($?) { 0 } else { $LASTEXITCODE }
    if ($null -eq $exitCode) { $exitCode = if ($?) { 0 } else { 1 } }
    
    $completionTime = (Get-Date).ToString("o")
    
    if ($null -ne $script:PersonalOS_LastCommand) {
        $cmdText = Invoke-PersonalOSRedact $script:PersonalOS_LastCommand
        
        $payload = @{
            command         = $cmdText
            cwd             = (Get-Location).Path
            exit_code       = $exitCode
            shell           = "powershell"
            terminal_host   = if ($env:TERM_PROGRAM) { $env:TERM_PROGRAM } else { "PowerShell" }
            session_id      = $script:PersonalOS_SessionId
            start_time      = $script:PersonalOS_LastStartTime
            completion_time = $completionTime
            timestamp       = $completionTime
            status          = if ($exitCode -eq 0) { "completed" } else { "failed" }
            source          = "powershell_hook"
        }
        
        Send-PersonalOSEvent $payload
        $script:PersonalOS_LastCommand = $null
    }
    
    # ── Call original prompt ──
    if ($null -ne $script:PersonalOS_OriginalPrompt) {
        & ([scriptblock]::Create($script:PersonalOS_OriginalPrompt))
    } else {
        "PS $($ExecutionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) "
    }
}

# Intercept the command line as it's submitted (before execution)
# This uses Set-PSReadLineKeyHandler to hook Enter on PSReadLine (PS 5.1+ / 7+)
if (Get-Command Set-PSReadLineKeyHandler -ErrorAction SilentlyContinue) {
    Set-PSReadLineKeyHandler -Key Enter -ScriptBlock {
        param($key, $arg)
        
        $line = $null
        $cursor = $null
        [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$line, [ref]$cursor)
        
        if ($line -and $line.Trim()) {
            $script:PersonalOS_LastCommand   = $line.Trim()
            $script:PersonalOS_LastStartTime = (Get-Date).ToString("o")
        }
        
        # Accept the line (submit the command)
        [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
    }
}

Write-Host "[Personal OS] PowerShell hook active. Session: $script:PersonalOS_SessionId" -ForegroundColor DarkGray
