@echo off
REM Manual run (double-click) — just launches the Python runner, which handles
REM the Hebrew project path reliably. The scheduled task calls python directly.
python "%~dp0run_daily.py"
pause
