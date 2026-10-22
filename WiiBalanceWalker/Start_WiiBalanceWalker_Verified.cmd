@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0Verify_Deployment.ps1"
if errorlevel 1 (
    echo No application started. Review the deployment mismatch before retrying.
    pause
    exit /b 1
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0Check_WiiInstance.ps1"
if errorlevel 1 (
    echo No application started. Review the instance status above.
    pause
    exit /b 1
)
start "" /D "%~dp0" "%~dp0WiiBalanceWalker.exe"
exit /b 0
