@echo off
setlocal
cd /d "%~dp0"
py -3.14 -c "import platform, struct; assert platform.python_implementation() == 'CPython' and struct.calcsize('P') == 8 and platform.machine().upper() in ('AMD64', 'X86_64')"
if errorlevel 1 goto python_missing
if not exist ".venv\Scripts\python.exe" py -3.14 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --no-index --find-links wheelhouse -r requirements-client.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" client.py setup
if errorlevel 1 goto failed
echo.
echo Installation complete. Open Start.cmd to launch Credit Manager.
pause
exit /b 0
:python_missing
echo Install 64-bit Python 3.14 with the Python launcher, then run Install.cmd again.
goto failed
:failed
echo Setup did not complete. See the message above.
pause
exit /b 1
