@echo off
setlocal
cd /d "%~dp0"
echo ======================================================================
echo  P0 V2 Clock Offset Session Auditor
echo ======================================================================
if "%~1"=="" (
    echo [INFO] No raw.csv path specified.
    echo Usage: audit_session.cmd ^<path_to_raw.csv^>
    echo (Tip: You can drag and drop a raw.csv directly onto this .cmd file)
    echo.
    echo [RUN] Running demo audit on P01 session:
    python patched\tools\clock_offset_audit.py "..\telemetry_logs\P01\session_20261019_105632_058608\raw.csv"
) else (
    echo [RUN] Auditing: %~1
    python patched\tools\clock_offset_audit.py "%~1"
)
echo.
pause
