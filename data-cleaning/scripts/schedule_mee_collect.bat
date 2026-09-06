@echo off
rem A23 MEE realtime collector.
rem Registered via: schtasks /create /tn "A23-mee-realtime-collect" /sc hourly /mo 4 /tr "<this file>" /f
rem Status JSON: storage\runs\data_factory\mvp_meiliangwan_2024\realtime\mee_collection_status.json
setlocal
set PKG_ROOT=%~dp0..
if not exist "%PKG_ROOT%\storage\logs" mkdir "%PKG_ROOT%\storage\logs"
cd /d "%PKG_ROOT%"
"C:\Anaconda\python.exe" -m data_factory collect-realtime --source mee >> "%PKG_ROOT%\storage\logs\mee_collect.log" 2>&1
endlocal
