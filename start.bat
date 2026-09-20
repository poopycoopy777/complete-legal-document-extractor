@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Put Windows System32 first so netstat/findstr resolve to the Windows
rem versions even when a Unix toolchain (Git Bash, MSYS) is earlier on PATH.
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%PATH%"

set "API_PORT=8010"
set "PY=%~dp0.venv\Scripts\python.exe"

rem Launched by double-click rather than from an existing console? Then the
rem window closes the moment this script ends, taking any error with it.
set "KEEP_OPEN="
echo %cmdcmdline% | findstr /i /c:"/c" >nul 2>&1 && set "KEEP_OPEN=1"

if not exist "%PY%" (
    echo [ERROR] Python environment not found at %PY%
    echo.
    echo Create it with:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    goto :fail
)

rem uvicorn exits with code 0 even when it cannot bind, so a port already in
rem use looks like a clean exit and the window just disappears. Check first.
set "HOLDER="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":%API_PORT% .*LISTENING"') do (
    if not "%%P"=="0" set "HOLDER=%%P"
)
if defined HOLDER (
    echo [ERROR] Port %API_PORT% is already in use by PID %HOLDER%.
    echo.
    echo This is usually an extraction API left running from an earlier
    echo session -- possibly from a different copy of this project, in which
    echo case it is serving stale code.
    echo.
    echo Stop it with:
    echo   stop.bat
    goto :fail
)

echo Complete Legal Document Extractor
echo API:  http://127.0.0.1:%API_PORT%
echo Docs: http://127.0.0.1:%API_PORT%/docs
echo Press Ctrl+C to stop.
echo.

"%PY%" -m uvicorn server.app:app --host 127.0.0.1 --port %API_PORT%
set "RC=%ERRORLEVEL%"

rem A server that stops within a second of starting did not really start.
if not "%RC%"=="0" (
    echo.
    echo [ERROR] The API exited with code %RC%.
    goto :fail
)
endlocal
exit /b 0

:fail
if defined KEEP_OPEN (
    echo.
    pause
)
endlocal
exit /b 1
