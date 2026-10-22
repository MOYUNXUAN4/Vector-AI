@echo off
setlocal
cd /d "%~dp0"
set "VECTORAI_TIMEOUT_PYTHON=C:\Users\QIYUXUAN\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%VECTORAI_TIMEOUT_PYTHON%" (
    echo [ERROR] Verified Python runtime not found.
    pause
    exit /b 1
)
echo [ISOLATED TEST] Synthetic input into a dedicated shadow instance only.
echo [ISOLATED TEST] No network, Unity control, trained model loading or live-log writes.
echo [ISOLATED TEST] Wall-clock mode will deliberately stop test input for about 2 seconds.
"%VECTORAI_TIMEOUT_PYTHON%" -u "%~dp0parallel_20261015\controlled_timeout_luna\run_controlled_timeout.py" --mode wall
set "VECTORAI_TIMEOUT_EXIT=%ERRORLEVEL%"
if "%VECTORAI_TIMEOUT_EXIT%"=="0" (
    echo [ISOLATED TEST] PASS. This is NOT Unity UDP end-to-end acceptance.
) else (
    echo [ISOLATED TEST] FAILED, code %VECTORAI_TIMEOUT_EXIT%. Keep the output for review.
)
pause
exit /b %VECTORAI_TIMEOUT_EXIT%
