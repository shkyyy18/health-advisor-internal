@echo off
setlocal
rem Runs hidden via scripts\run_healthboard.vbs (healthboard:// protocol).
rem The backend exits by itself once the dashboard tab stops sending heartbeats.
set "PROJECT_DIR=%~dp0.."
if not exist "%PROJECT_DIR%\logs" mkdir "%PROJECT_DIR%\logs"
pushd "%PROJECT_DIR%"
start "" pythonw "%PROJECT_DIR%\scripts\open_dashboard.py"
python -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',8000))==0 else 1)"
if %errorlevel%==0 (
    popd
    exit /b 0
)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> "%PROJECT_DIR%\logs\app.out.log" 2>> "%PROJECT_DIR%\logs\app.err.log"
popd
