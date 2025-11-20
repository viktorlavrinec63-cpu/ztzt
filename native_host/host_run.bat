@echo off
REM host_run.bat — launches Python native_host.py
set PY_EXE=python
set SCRIPT_DIR=%~dp0
"%PY_EXE%" "%SCRIPT_DIR%native_host.py"
