@echo off
:: ============================================================
:: HOPEFX — Platform health diagnostic (Windows)
:: Double-click this file, or run `diagnose.bat` from a terminal.
:: It scans backend + frontend + services + config and writes a
:: report to diagnostics\HOPEFX_HEALTH_REPORT.md, then opens it.
:: It changes nothing.
:: ============================================================
cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" call "venv\Scripts\activate.bat"

echo Running HOPEFX platform diagnostic...
python scripts\platform_doctor.py
echo.
echo ------------------------------------------------------------
echo Report saved to: diagnostics\HOPEFX_HEALTH_REPORT.md
echo ------------------------------------------------------------

:: Open the report in the default editor (non-fatal if it fails)
if exist "diagnostics\HOPEFX_HEALTH_REPORT.md" start "" "diagnostics\HOPEFX_HEALTH_REPORT.md"

pause
