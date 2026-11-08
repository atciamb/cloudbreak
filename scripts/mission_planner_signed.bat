@echo off
rem Mission Planner on the signed real FC, from this laptop.
rem Starts the signing proxy in its own window (FC on USB is found by itself; or pass --fc tcp:<pi>:14560),
rem then Mission Planner. In Mission Planner: pick UDP at the top right, Connect, port 14550.
rem Do NOT pick the FC's COM port in Mission Planner: the proxy holds it. Close the proxy window to stop.
cd /d "%~dp0.."
start "Cloudbreak signing proxy" .venv\Scripts\python.exe scripts\gcs_proxy.py %*
timeout /t 3 >nul
if exist "%ProgramFiles(x86)%\Mission Planner\MissionPlanner.exe" (
  start "" "%ProgramFiles(x86)%\Mission Planner\MissionPlanner.exe"
) else if exist "%ProgramFiles%\Mission Planner\MissionPlanner.exe" (
  start "" "%ProgramFiles%\Mission Planner\MissionPlanner.exe"
) else (
  echo Mission Planner not found. Any ground station can connect on UDP 14550.
  pause
)
