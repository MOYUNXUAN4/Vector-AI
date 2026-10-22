@echo off
setlocal
cd /d "%~dp0"
set "VECTORAI_CUE_PYTHON=C:\Users\QIYUXUAN\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%VECTORAI_CUE_PYTHON%" (
    echo [ERROR] Verified Python runtime not found.
    pause
    exit /b 1
)
echo [TEST CUE] Read-only monitor. This does NOT start a second backend.
echo [TEST CUE] Keep Start_Master_With_Proximity_Shadow.cmd running separately.
echo [TEST CUE] Keep this window open. Press Ctrl+C to close the monitor.
"%VECTORAI_CUE_PYTHON%" -u "%~dp0parallel_20261015\shadow_test_cue_luna\shadow_cue.py" --log "%~dp0telemetry_logs\proximity_shadow.jsonl"
set "VECTORAI_CUE_EXIT=%ERRORLEVEL%"
if not "%VECTORAI_CUE_EXIT%"=="0" (
    echo [TEST CUE] Monitor exited with code %VECTORAI_CUE_EXIT%.
    pause
)
exit /b %VECTORAI_CUE_EXIT%
