@echo off
setlocal
cd /d "%~dp0"
set "PROXIMITY_SHADOW_ENABLED=1"
echo [SHADOW] Recording the frozen TTE proximity rule locally only.
echo [SHADOW] Existing model warnings and Unity displays are unchanged.
call "%~dp0Start_Master_With_Model.cmd"
exit /b %ERRORLEVEL%
