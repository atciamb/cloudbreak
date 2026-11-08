@echo off
rem Opens the servo bench page in Chrome (or Edge). Both support the Web Serial API it needs.
set "F=%~dp0servo_bench_gui.html"
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
  start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" --new-window "%F%"
) else (
  start "" msedge --new-window "%F%"
)
