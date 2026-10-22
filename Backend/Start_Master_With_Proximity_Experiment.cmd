@echo off
setlocal
cd /d "%~dp0"
set "PROXIMITY_SHADOW_ENABLED=1"
set "PROXIMITY_REPLY_ENABLED=1"
echo [EXPERIMENTAL] Adds an independent TTE proximity_warning field to realtime replies.
echo [EXPERIMENTAL] This is NOT a model probability or a validated player-benefit claim.
echo [EXPERIMENTAL] Use only after the Unity independent receiver is implemented.
call "%~dp0Start_Master_With_Model.cmd"
exit /b %ERRORLEVEL%
