@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv
    if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -c "import PySide6.QtWidgets, paramiko, importlib.util; assert importlib.util.find_spec('libarchive')" >nul 2>&1
if errorlevel 1 (
    .venv\Scripts\python.exe -m pip install -e .
    if errorlevel 1 goto failed
)
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
.venv\Scripts\python.exe -m soovee_commander %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. Verify that Python 3.13 or newer is installed.
pause
exit /b 1
