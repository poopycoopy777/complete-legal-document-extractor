@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Put Windows System32 first so netstat/findstr resolve to the Windows
rem versions even when a Unix toolchain (Git Bash, MSYS) is earlier on PATH.
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%PATH%"

set "API_PORT=8010"
set "WEB_PORT=5173"
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

if not exist "%~dp0web\node_modules" (
    echo [ERROR] Frontend dependencies not installed.
    echo.
    echo Install them with:
    echo   cd web
    echo   npm install
    goto :fail
)

rem uvicorn and vite both exit 0 when they cannot bind, so a port already in
rem use looks like a clean exit and the window just disappears. Check first.
call :check_port %API_PORT% "extraction API" || goto :fail
call :check_port %WEB_PORT% "frontend dev server" || goto :fail

echo Complete Legal Document Extractor
echo.
echo   App:  http://localhost:%WEB_PORT%
echo   API:  http://127.0.0.1:%API_PORT%
echo   Docs: http://127.0.0.1:%API_PORT%/docs
echo.
echo Starting both servers in their own windows.
echo Close this window or run stop.bat to shut everything down.
echo.

start "Extraction API" cmd /k ""%PY%" -m uvicorn server.app:app --host 127.0.0.1 --port %API_PORT%"
start "Frontend" cmd /k "cd /d "%~dp0web" && npm run dev"

rem Wait for the API before opening a browser, so the first page load is not
rem an empty pane against a server that has not finished starting.
echo Waiting for the API...
set "API_UP="
for /l %%i in (1,1,30) do (
    if not defined API_UP (
        >nul 2>&1 powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri 'http://127.0.0.1:%API_PORT%/api/health' -UseBasicParsing -TimeoutSec 2).StatusCode}catch{exit 1}" && set "API_UP=1"
        if not defined API_UP >nul timeout /t 1 /nobreak
    )
)
if not defined API_UP (
    echo [WARN] The API did not answer in time. Check the "Extraction API" window.
)

echo Waiting for the frontend...
set "WEB_UP="
for /l %%i in (1,1,30) do (
    if not defined WEB_UP (
        >nul 2>&1 netstat -ano | findstr /r /c:":%WEB_PORT% .*LISTENING" && set "WEB_UP=1"
        if not defined WEB_UP >nul timeout /t 1 /nobreak
    )
)
if not defined WEB_UP (
    echo [WARN] The frontend did not start in time. Check the "Frontend" window.
    goto :done
)

start "" "http://localhost:%WEB_PORT%"

:done
echo.
echo Running.
endlocal
exit /b 0

:check_port
set "HOLDER="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":%~1 .*LISTENING"') do (
    if not "%%P"=="0" set "HOLDER=%%P"
)
if defined HOLDER (
    echo [ERROR] Port %~1 is already in use by PID %HOLDER% ^(%~2^).
    echo.
    echo This is usually a server left running from an earlier session --
    echo possibly from a different copy of this project, in which case it is
    echo serving stale code.
    echo.
    echo Stop it with:
    echo   stop.bat
    exit /b 1
)
exit /b 0

:fail
if defined KEEP_OPEN (
    echo.
    pause
)
endlocal
exit /b 1
