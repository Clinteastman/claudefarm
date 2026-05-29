<#
.SYNOPSIS
    Take whatever is on the Windows clipboard (a screenshot OR one or more
    files copied from Explorer) and ship it to a claudefarm server via SCP,
    then type the resulting remote path(s) into the focused window. Designed
    to be bound to a hotkey so a remote Claude over SSH can see anything you
    drag onto your local clipboard.

.DESCRIPTION
    Workflow A - screenshot:
      1. Win+Shift+S → snip stays on clipboard
      2. Press the hotkey
      3. /data/dev/_paste/<timestamp>.png types into the focused window
      4. Hit Enter, ask Claude to look at it

    Workflow B - file(s) from Explorer:
      1. Select file(s) in Explorer, Ctrl+C
      2. Press the hotkey
      3. /data/dev/_paste/<timestamp>-<filename> types in (one path per file,
         space-separated)
      4. Hit Enter

    Path(s) also land on your clipboard as a fallback in case SendKeys lost
    focus while typing.

.PARAMETER ServerHost
    SSH host of the claudefarm server. Default: 192.168.50.62 (K12 LXC 105).

.PARAMETER ServerUser
    SSH user. Default: root.

.PARAMETER RemoteDir
    Directory on the server to SCP into. Default: /data/dev/_paste

.NOTES
    Bind via AutoHotkey, PowerToys Keyboard Manager, or a Windows shortcut
    .lnk hotkey. See client/README.md.
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

function Toast($title, $msg, $icon = "Information") {
    [System.Windows.Forms.MessageBox]::Show(
        $msg, $title,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::$icon
    ) | Out-Null
}

function Send-Path-To-Server($localPath, $remoteName) {
    $remotePath = "$RemoteDir/$remoteName"
    $null = & ssh -o BatchMode=yes "${ServerUser}@${ServerHost}" "mkdir -p '$RemoteDir'" 2>&1
    & scp -q -o BatchMode=yes $localPath "${ServerUser}@${ServerHost}:$remotePath" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Toast "claudefarm: paste-image" `
              "SCP to ${ServerUser}@${ServerHost} failed (exit $LASTEXITCODE).`nLocal: $localPath" `
              "Error"
        exit 1
    }
    return $remotePath
}

# ---- Decide what's on the clipboard ----------------------------------------

$clip = [System.Windows.Forms.Clipboard]
$ts   = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$remotePaths = @()

if ($clip::ContainsFileDropList()) {
    # Files copied from Explorer (Ctrl+C) - upload each one preserving its name
    $files = $clip::GetFileDropList()
    $i = 0
    foreach ($f in $files) {
        if (-not (Test-Path $f -PathType Leaf)) { continue }   # skip dirs for now
        $i++
        # Sanitise the filename so it can't inject into the remote scp path
        # (legacy-rcp CVE-2020-15778 class); Windows allows ; $ ` spaces ( ) in names.
        $stem = ([System.IO.Path]::GetFileName($f)) -replace '[^A-Za-z0-9._-]','_'
        $remoteName = "$ts-$i-$stem"
        $remotePaths += (Send-Path-To-Server $f $remoteName)
    }
    if ($remotePaths.Count -eq 0) {
        Toast "claudefarm: paste-image" `
              "Clipboard has files but none are readable. (Folders are skipped.)"
        exit 1
    }
} elseif ($clip::ContainsImage()) {
    # Screenshot on clipboard - save to PNG then upload
    $img       = $clip::GetImage()
    $localPath = Join-Path $env:TEMP "claude-paste-$ts.png"
    $img.Save($localPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $img.Dispose()
    $remotePaths += (Send-Path-To-Server $localPath "$ts.png")
    Remove-Item -Force $localPath -ErrorAction SilentlyContinue
} else {
    Toast "claudefarm: paste-image" `
          "Nothing on the clipboard. Take a screenshot (Win+Shift+S) or copy a file in Explorer first."
    exit 1
}

# ---- Hand the path(s) back to the user -------------------------------------

$pathsJoined = $remotePaths -join ' '

# Clipboard fallback (so Ctrl+V still works if SendKeys lost focus)
Set-Clipboard -Value $pathsJoined

# Escape SendKeys-special chars: { } ( ) + ^ % ~
$escaped = $pathsJoined -replace '([+^%~(){}])', '{$1}'
try {
    [System.Windows.Forms.SendKeys]::SendWait($escaped)
} catch {
    Toast "claudefarm: paste-image" `
          "Path(s) copied to clipboard. Ctrl+V to paste.`n`n$pathsJoined"
}
