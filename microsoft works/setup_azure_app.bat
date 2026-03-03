@echo off
echo ============================================================
echo   Azure App Setup - Starting...
echo ============================================================
echo.

:: Run PowerShell script
powershell -ExecutionPolicy Bypass -File "%~dp0setup_azure_app.ps1"

echo.
pause

