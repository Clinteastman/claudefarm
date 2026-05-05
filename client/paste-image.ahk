; paste-image.ahk - bind a hotkey to paste-image.ps1 so a clipboard
; screenshot lands on the claudefarm server and its remote path gets
; typed into the focused window. Designed for AutoHotkey v2.
;
; Default hotkey:  Ctrl+Shift+Alt+V
;
;   Why three modifiers?  Single + double-modifier combos all clash
;   somewhere on Windows: Ctrl+Alt+V = AltGr+V = R on UK/intl
;   keyboards. Win+V = clipboard history. Win+Shift+V = notification
;   cycling on newer Win11 builds. Ctrl+Shift+V = paste in many apps.
;   Three modifiers + V is unbound everywhere, can't generate a stray
;   character if AHK isn't loaded, and is still one chord to press.
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

^+!v::  ; Ctrl+Shift+Alt+V
{
    ; Quick visual confirmation the hotkey fired (sound + tray tip).
    SoundBeep 1000, 80
    TrayTip "claudefarm: paste-image", "Hotkey fired - shipping image to server...", 2

    ; Run NOT hidden the first time so any PowerShell error is visible.
    ; Once you've confirmed it works end-to-end, change "" to "Hide" below.
    ; cmd.exe-style redirect (> + 2>&1) so the `*>` PowerShell shorthand
    ; doesn't get parsed as a positional arg to the .ps1 (it was being
    ; passed in as $ServerHost = "*", which broke ssh hostname resolution).
    cmd := 'powershell.exe -NoProfile -ExecutionPolicy Bypass'
         . ' -File "' . SCRIPT_PATH . '"'
         . ' > "' . LOG_PATH . '" 2>&1'

    try {
        Run(A_ComSpec . ' /c ' . cmd, , "Hide")
    } catch as e {
        TrayTip "claudefarm: paste-image", "Run() failed: " . e.Message, 5
    }
}
