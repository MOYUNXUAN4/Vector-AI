@echo off
setlocal
cd /d "%~dp0"
set "FALLING_WARNING_MODEL_ENABLED=1"
set "FALLING_WARNING_ALLOW_CALIBRATION_GAMEPLAY=1"
set "PROXIMITY_SHADOW_ENABLED=1"
set "PROXIMITY_REPLY_ENABLED=1"
set "VECTORAI_PILOT_PYTHON=C:\Users\QIYUXUAN\AppData\Local\Python\pythoncore-3.14-64\python.exe"
echo [PILOT EXPERIMENTAL] Existing 24-feature LightGBM plus separate TTE rule. NOT a fused deployed predictor.
echo [PILOT EXPERIMENTAL] Startup checks do not constitute runtime or performance acceptance.
if not exist "%VECTORAI_PILOT_PYTHON%" (
    echo [PREFLIGHT BLOCKED] Pinned Python executable is missing.
    pause
    exit /b 1
)
"%VECTORAI_PILOT_PYTHON%" "%~dp0parallel_20261016\pilot_readiness\tools\preflight.py" --receipt-dir "%~dp0parallel_20261016\pilot_readiness\preflight_receipts"
if errorlevel 1 (
    echo [PREFLIGHT BLOCKED] No backend started. Review the message above.
    pause
    exit /b 1
)
call "%~dp0Start_Master_With_Proximity_Experiment.cmd"
exit /b %ERRORLEVEL%
