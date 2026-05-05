; paste-image.ahk - bind a hotkey to paste-image.ps1 so a clipboard
; screenshot lands on the claudefarm server and its remote path gets
; typed into the focused window. Designed for AutoHotkey v2.
;
; Default hotkey:  Win+Shift+V
;
;   Why not Ctrl+Alt+V?  On UK / international keyboards, Windows
;   treats Ctrl+Alt as AltGr, and AltGr+V types ® (registered
;   trademark). If AHK ever fails to intercept, you'd accidentally
;   spam ® into your terminal. Win+Shift+V has no default OS binding,
;   so it's safe even if this script isn't loaded.
;
; Install AutoHotkey v2 from https://www.autohotkey.com/v2/
; Then double-click this file to load. Drop a shortcut into
; shell:startup (Win+R) so it autoloads on login.
;
; Edit the SCRIPT_PATH below to match where you cloned the claudefarm repo.

#Requires AutoHotkey v2.0

SCRIPT_PATH := A_MyDocuments . "\..\github\claudefarm\client\paste-image.ps1"

#+v::  ; Win+Shift+V
{
    ; Run hidden so we don't get a flashing PowerShell window
    Run('powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' . SCRIPT_PATH . '"', , "Hide")
}
