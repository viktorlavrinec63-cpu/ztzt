@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel% neq 0 (
  echo pythonw.exe not found in PATH. Trying pythonw from default install...
)
start "" /min pythonw.exe "%~dp0launcher_api_gui.pyw"
exit
