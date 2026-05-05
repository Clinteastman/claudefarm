; paste-image.ahk - bind a hotkey to paste-image.ps1 so a clipboard
; screenshot lands on the claudefarm server and its remote path gets
; typed into the focused window. Designed for AutoHotkey v2.
;
; Default hotkey:  Ctrl+Alt+V  (Alt+V alone conflicts with Claude Code's
;                                local image paste, which doesn't work
;                                over SSH anyway, but no point overlapping)
;
; Install AutoHotkey v2 from https://www.autohotkey.com/v2/
; Then double-click this file to load (or drop in shell:startup for autoload).
;
; Edit the SCRIPT_PATH below to match where you cloned the claudefarm repo.

#Requires AutoHotkey v2.0

SCRIPT_PATH := A_MyDocuments . "\..\github\claudefarm\client\paste-image.ps1"

^!v::  ; Ctrl+Alt+V
{
    ; Run hidden so we don't get a flashing PowerShell window
    Run('powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' . SCRIPT_PATH . '"', , "Hide")
}
