@echo off
rem A23 MEE realtime collector.
rem Register or repair the task with register_mee_realtime_task.ps1.
rem Status JSON: storage\runs\data_factory\mvp_meiliangwan_2024\realtime\mee_collection_status.json
setlocal
set PKG_ROOT=%~dp0..
if not exist "%PKG_ROOT%\storage\logs" mkdir "%PKG_ROOT%\storage\logs"
cd /d "%PKG_ROOT%"
echo [%date% %time%] MEE collector starting (user=%USERNAME%, cwd=%CD%)>> "%PKG_ROOT%\storage\logs\mee_collect.log"
"C:\Anaconda\python.exe" -m data_factory collect-realtime --source mee >> "%PKG_ROOT%\storage\logs\mee_collect.log" 2>&1
set EXIT_CODE=%ERRORLEVEL%
echo [%date% %time%] MEE collector finished (exit_code=%EXIT_CODE%)>> "%PKG_ROOT%\storage\logs\mee_collect.log"
endlocal & exit /b %EXIT_CODE%
