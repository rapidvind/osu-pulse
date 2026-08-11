@echo off
:: Double-click this file to start everything: tosu (hidden), the key hook,
:: and the dashboard. Needs Administrator so the key hook can see keypresses
:: while osu! has focus - this re-launches itself elevated if needed.

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting Administrator permission...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
echo Starting osu!Pulse...
echo Dashboard will open in your browser shortly.
echo Close this window to stop the app.
echo.
python src\app.py

pause
