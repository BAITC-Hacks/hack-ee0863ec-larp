@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo HackAlem AI console
if exist ".venv\Scripts\python.exe" goto check_python
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 -m venv .venv
if errorlevel 1 goto failed
goto check_python
:use_python
python -m venv .venv
if errorlevel 1 goto failed
:check_python
.venv\Scripts\python.exe -c "import sys,struct; assert (3,11) <= sys.version_info[:2] <= (3,13) and struct.calcsize('P')*8 == 64, 'Python 3.11-3.13 64-bit required'"
if errorlevel 1 goto failed
if exist ".venv\.hackalem-deps-v1" goto prepare
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
type nul > ".venv\.hackalem-deps-v1"
:prepare
.venv\Scripts\python.exe main.py --prepare
if errorlevel 1 goto failed
.venv\Scripts\python.exe main.py --offline
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo.
echo Setup or execution failed. See the error above and README.md.
echo Python 3.11-3.13 64-bit is required. First setup needs internet access.
pause
exit /b 1
