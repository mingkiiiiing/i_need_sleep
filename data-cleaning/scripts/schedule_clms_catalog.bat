@echo off
rem A23 CLMS LWQ catalogue daily refresh (official Copernicus catalogue discovery only).
rem Registered via: schtasks /create /tn "A23-clms-lwq-catalog" /sc daily /st 08:40 /tr "<this file>" /f
rem Real fetch only: no opener injection, truth gate writes data_truth=real_official_catalogue.
setlocal
set PKG_ROOT=%~dp0..
if not exist "%PKG_ROOT%\storage\logs" mkdir "%PKG_ROOT%\storage\logs"
cd /d "%PKG_ROOT%"
"C:\Anaconda\python.exe" -m pipeline.cli clms-lwq >> "%PKG_ROOT%\storage\logs\clms_lwq_catalog.log" 2>&1
endlocal
