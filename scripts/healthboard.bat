@echo off
setlocal
rem Hidden launcher target: scripts\run_healthboard.vbs (or the desktop shortcut).
set "PROJECT_DIR=%~dp0.."
if not exist "%PROJECT_DIR%\logs" mkdir "%PROJECT_DIR%\logs"
if not exist "%PROJECT_DIR%\.env" copy /Y "%PROJECT_DIR%\.env.example" "%PROJECT_DIR%\.env" >nul
pushd "%PROJECT_DIR%" || exit /b 1
set "PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "PYTHONW=%PROJECT_DIR%\.venv\Scripts\pythonw.exe"
if not exist "%PYTHON%" set "PYTHON=python.exe"
if not exist "%PYTHONW%" set "PYTHONW=pythonw.exe"
rem Open the browser without a console; it waits for the service and refreshes normally.
start "" "%PYTHONW%" "%PROJECT_DIR%\scripts\open_dashboard.py"
"%PYTHON%" -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',8000))==0 else 1)"
if %errorlevel%==0 (
    popd
    exit /b 0
)
rem Run the backend in this hidden launcher; logs are retained for diagnosis.
"%PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> "%PROJECT_DIR%\logs\app.out.log" 2>> "%PROJECT_DIR%\logs\app.err.log"
set "EXIT_CODE=%errorlevel%"
popd
exit /b %EXIT_CODE%
