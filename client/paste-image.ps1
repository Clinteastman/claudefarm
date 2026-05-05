<#
.SYNOPSIS
    Take whatever image is on the Windows clipboard, ship it to a claudefarm
    server via SCP, then type the resulting remote path into the focused
    window. Designed to be bound to a hotkey so you can paste screenshots
    into a remote Claude Code session over SSH.

.DESCRIPTION
    Workflow:
      1. Win+Shift+S (or any other screenshot tool) puts the image on your
         Windows clipboard.
      2. Press the hotkey you bound to this script.
      3. ~2 seconds later, "/data/dev/_paste/<timestamp>.png" appears in
         the focused window (the Claude Code SSH session in tmux).
      4. Hit Enter, ask Claude to look at it.

    The path is also copied to your clipboard as a fallback in case
    SendKeys lost focus.

.PARAMETER ServerHost
    SSH host of the claudefarm server. Default: 192.168.50.62 (K12 LXC 105).

.PARAMETER ServerUser
    SSH user. Default: root.

.PARAMETER RemoteDir
    Directory on the server to SCP the image to. Must be writable by ServerUser
    and pre-created. Default: /data/dev/_paste

.EXAMPLE
    .\paste-image.ps1
    # uses defaults (K12)

.EXAMPLE
    .\paste-image.ps1 -ServerHost 10.0.0.5 -ServerUser pi -RemoteDir /tmp/paste

.NOTES
    Bind via PowerToys Keyboard Manager OR AutoHotkey OR a Windows shortcut
    .lnk with a hotkey set in its properties. See client/README.md.
#>
[CmdletBinding()]
param(
    [string]$ServerHost = "192.168.50.62",
    [string]$ServerUser = "root",
    [string]$RemoteDir  = "/data/dev/_paste"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ---- 1. Grab clipboard image -----------------------------------------------

$img = [System.Windows.Forms.Clipboard]::GetImage()
if ($null -eq $img) {
    [System.Windows.Forms.MessageBox]::Show(
        "No image on the clipboard. Take a screenshot (Win+Shift+S) first.",
        "claudefarm: paste-image",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
    exit 1
}

# ---- 2. Save locally to temp ------------------------------------------------

$ts        = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$localPath = Join-Path $env:TEMP "claude-paste-$ts.png"
$img.Save($localPath, [System.Drawing.Imaging.ImageFormat]::Png)
$img.Dispose()

# ---- 3. SCP to remote -------------------------------------------------------

$remoteName = "$ts.png"
$remotePath = "$RemoteDir/$remoteName"

# Ensure remote dir exists (cheap, idempotent)
$null = & ssh -o BatchMode=yes "${ServerUser}@${ServerHost}" "mkdir -p '$RemoteDir'" 2>&1
& scp -q -o BatchMode=yes $localPath "${ServerUser}@${ServerHost}:$remotePath" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    [System.Windows.Forms.MessageBox]::Show(
        "SCP to ${ServerUser}@${ServerHost} failed (exit $LASTEXITCODE).`nLocal: $localPath",
        "claudefarm: paste-image",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 1
}

# Local copy no longer needed
Remove-Item -Force $localPath -ErrorAction SilentlyContinue

# ---- 4. Hand the path back to the user --------------------------------------

# Clipboard fallback (so Ctrl+V still works if SendKeys lost focus)
Set-Clipboard -Value $remotePath

# Type into the focused window. SendKeys.SendWait blocks until the keystrokes
# have been processed, which avoids race conditions with the active window.
# Escape special chars: { } ( ) + ^ % ~ all have meanings in SendKeys syntax.
$escaped = $remotePath -replace '([+^%~(){}])', '{$1}'
try {
    [System.Windows.Forms.SendKeys]::SendWait($escaped)
} catch {
    # Focus might have been on a non-typeable surface - the clipboard fallback
    # has it covered. Show a quick toast so the user knows they can Ctrl+V.
    [System.Windows.Forms.MessageBox]::Show(
        "Path copied to clipboard. Ctrl+V to paste.`n`n$remotePath",
        "claudefarm: paste-image",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
}
