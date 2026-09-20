@echo off
rem Launch the IVFFlat index build. Administrative, manual, runs for hours.
rem Logs to logs\ivfflat_build.log. Reads stay available throughout.
setlocal EnableExtensions
cd /d "%~dp0.."

if "%VERIFIER_ENV_FILE%"=="" (
    set "VERIFIER_ENV_FILE=D:\THE FUTURE OF LITIGATION\app_v2\backend\.env"
)

if not exist "logs" mkdir "logs"

"%~dp0..\.venv\Scripts\python.exe" "%~dp0build_ivfflat_index.py" %* >> "logs\ivfflat_build.log" 2>&1
endlocal
