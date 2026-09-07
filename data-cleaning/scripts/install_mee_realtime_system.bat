@echo off
rem Run this file from an elevated Command Prompt to install the SYSTEM task.
setlocal
set DATA_CLEANING_ROOT=%~dp0..
if not exist "%DATA_CLEANING_ROOT%\storage\logs" mkdir "%DATA_CLEANING_ROOT%\storage\logs"
wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true > "%DATA_CLEANING_ROOT%\storage\logs\mee_system_task_install.log" 2>&1
"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_mee_realtime_task.ps1" -RunAsSystem >> "%DATA_CLEANING_ROOT%\storage\logs\mee_system_task_install.log" 2>&1
set EXIT_CODE=%ERRORLEVEL%
echo [%date% %time%] SYSTEM task installer exit_code=%EXIT_CODE%>> "%DATA_CLEANING_ROOT%\storage\logs\mee_system_task_install.log"
endlocal & exit /b %EXIT_CODE%
