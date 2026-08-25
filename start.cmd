@echo off
rem Thin wrapper for Windows. The launcher itself is start.py — ONE
rem implementation for every OS (macOS/Linux use start.sh).
rem
rem   start.cmd            React UI on 8503, Python API on 8787 behind it
rem   start.cmd status     which ports are held, and whether the API answers
rem   start.cmd stop       free both ports by PID, never by name
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%ROOT%start.py" %*
endlocal
