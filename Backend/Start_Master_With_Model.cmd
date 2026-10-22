@echo off
setlocal
cd /d "%~dp0"
set "VECTORAI_TASK_PYTHON=C:\Users\QIYUXUAN\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%VECTORAI_TASK_PYTHON%" (
    echo [ERROR] The verified Python runtime was not found.
    echo Please check the Python path in this launcher.
    pause
    exit /b 1
)
echo [INFO] Starting the existing master server with its experimental model defaults.
echo [INFO] Explicit FALLING_WARNING environment overrides are respected.
"%VECTORAI_TASK_PYTHON%" "%~dp0master_server.py"
set "VECTORAI_TASK_EXIT=%ERRORLEVEL%"
if not "%VECTORAI_TASK_EXIT%"=="0" (
    echo [ERROR] Master server exited with code %VECTORAI_TASK_EXIT%.
    pause
)
exit /b %VECTORAI_TASK_EXIT%
