@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
echo HackAlem AI console
if exist ".venv\Scripts\python.exe" goto check_python
where py >nul 2>nul
if errorlevel 1 goto use_python
for %%V in (3.13 3.12 3.11) do (
    py -%%V -c "import struct; assert struct.calcsize('P') == 8" >nul 2>nul
    if not errorlevel 1 (
        py -%%V -m venv .venv
        if errorlevel 1 goto failed
        goto check_python
    )
)
:use_python
python -c "import sys,struct; assert (3,11) <= sys.version_info[:2] <= (3,13) and struct.calcsize('P') == 8"
if errorlevel 1 goto failed
python -m venv .venv
if errorlevel 1 goto failed
:check_python
.venv\Scripts\python.exe -c "import sys,struct; assert (3,11) <= sys.version_info[:2] <= (3,13) and struct.calcsize('P')*8 == 64, 'Python 3.11-3.13 64-bit required'"
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip --version >nul 2>nul
if errorlevel 1 .venv\Scripts\python.exe -m ensurepip --upgrade
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
:prepare
.venv\Scripts\python.exe main.py --prepare
if errorlevel 1 goto failed
.venv\Scripts\python.exe main.py --offline
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo.
echo Setup or execution failed. See the error above. Install Python 3.13 64-bit if needed. See README.md.
echo Python 3.11-3.13 64-bit is required. First setup needs internet access.
pause
exit /b 1
