@echo off
setlocal
cd /d "%~dp0"
echo ======================================================================
echo  P0 V2 Clock Alignment Patch - Verification Runner
echo ======================================================================
echo [INFO] Running 14 Regression Unit Tests and Real-Session Audit...
python verify_p0_v2.py --csv "..\telemetry_logs\P01\session_20261019_105632_058608\raw.csv"
if errorlevel 1 (
    echo.
    echo [ERROR] Verification failed!
    pause
    exit /b 1
)
echo.
echo [SUCCESS] All 14 tests and real session audit passed!
pause
