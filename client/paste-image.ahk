; paste-image.ahk - bind a hotkey to paste-image.ps1 so a clipboard
; screenshot lands on the claudefarm server and its remote path gets
; typed into the focused window. Designed for AutoHotkey v2.
;
; Default hotkey:  Win+Shift+V
;
;   Avoids Ctrl+Alt+V (= AltGr+V = R on UK/intl keyboards) and the
;   terminal's Ctrl+Shift+V paste binding. AHK's k-hook intercepts
;   Win+Shift+V before any default Windows behaviour can fire.
;
; Install AutoHotkey v2 from https://www.autohotkey.com/v2/
; Then double-click this file to load. Drop a shortcut into
; shell:startup (Win+R) so it autoloads on login.
;
; Edit the SCRIPT_PATH below to match where you cloned the claudefarm repo.

#Requires AutoHotkey v2.0

; Resolve the script path relative to THIS .ahk file's directory.
; Works regardless of where you cloned the repo, as long as paste-image.ps1
; sits next to this .ahk.
SCRIPT_PATH := A_ScriptDir . "\paste-image.ps1"
LOG_PATH    := A_Temp . "\claudefarm-paste-image.log"

#+v::  ; Win+Shift+V
{
    ; cmd.exe-style redirect (> + 2>&1) so the `*>` PowerShell shorthand
    ; doesn't get parsed as a positional arg to the .ps1 (it was being
    ; passed in as $ServerHost = "*", which broke ssh hostname resolution).
    ; Output (errors etc.) lands in %TEMP%\claudefarm-paste-image.log
    ; for after-the-fact debugging if anything ever stops working.
    cmd := 'powershell.exe -NoProfile -ExecutionPolicy Bypass'
         . ' -File "' . SCRIPT_PATH . '"'
         . ' > "' . LOG_PATH . '" 2>&1'

    try {
        Run(A_ComSpec . ' /c ' . cmd, , "Hide")
    } catch as e {
        ; Only surface UI on actual failure - silent on success.
        TrayTip "claudefarm: paste-image", "Run() failed: " . e.Message, 5
    }
}
