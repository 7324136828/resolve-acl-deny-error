@echo off
setlocal
cd /d "%~dp0"

:: Check for Python 3.9+ using Python launcher or python executable
py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1
if not errorlevel 1 goto use_py

python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1
if not errorlevel 1 goto use_python

python3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1
if not errorlevel 1 goto use_python3

echo [ERROR] Python 3.9 or newer is required to run this utility.
echo Please install Python from https://www.python.org/ or the Microsoft Store.
echo No changes were made.
pause
exit /b 1

:use_py
if "%~1"=="" (
    py -3 "%~dp0repair_acl.py" --gui
) else (
    py -3 "%~dp0repair_acl.py" %*
)
exit /b %errorlevel%

:use_python
if "%~1"=="" (
    python "%~dp0repair_acl.py" --gui
) else (
    python "%~dp0repair_acl.py" %*
)
exit /b %errorlevel%

:use_python3
if "%~1"=="" (
    python3 "%~dp0repair_acl.py" --gui
) else (
    python3 "%~dp0repair_acl.py" %*
)
exit /b %errorlevel%
