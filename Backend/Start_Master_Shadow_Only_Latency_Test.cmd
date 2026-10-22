@echo off
setlocal
cd /d "%~dp0"
set "PROXIMITY_SHADOW_ENABLED=1"
set "FALLING_WARNING_MODEL_ENABLED=0"
echo [DIAGNOSTIC B] Existing model and its geometry replies are disabled in this process.
echo [DIAGNOSTIC B] Frozen TTE shadow remains local-only. No Unity rule changes.
echo [DIAGNOSTIC B] This is a latency control, NOT the normal gameplay launcher.
call "%~dp0Start_Master_With_Model.cmd"
exit /b %ERRORLEVEL%
