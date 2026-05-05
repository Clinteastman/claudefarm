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

SCRIPT_PATH := A_MyDocuments . "\..\github\claudefarm\client\paste-image.ps1"

^+!v::  ; Ctrl+Shift+Alt+V
{
    ; Run hidden so we don't get a flashing PowerShell window
    Run('powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' . SCRIPT_PATH . '"', , "Hide")
}
