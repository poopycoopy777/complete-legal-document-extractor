@echo off
rem Launch the IVFFlat index build. Administrative, manual, runs for hours.
rem Logs to logs\ivfflat_build.log. Reads stay available throughout.
setlocal EnableExtensions
cd /d "%~dp0.."

rem The database URL comes from VERIFIER_DATABASE_URL (persisted at user level)
rem or a VERIFIER_ENV_FILE the operator sets. There is no fallback path.

if not exist "logs" mkdir "logs"

"%~dp0..\.venv\Scripts\python.exe" "%~dp0build_ivfflat_index.py" %* >> "logs\ivfflat_build.log" 2>&1
endlocal
