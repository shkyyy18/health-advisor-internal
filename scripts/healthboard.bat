@echo off
rem Runs hidden via scripts\run_healthboard.vbs (healthboard:// protocol).
rem The backend exits by itself once the dashboard tab stops sending heartbeats.
cd /d D:\AIWorkspace\projects\health_assistant
start "" pythonw scripts\open_dashboard.py
python -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',8000))==0 else 1)"
if %errorlevel%==0 exit /b 0
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> logs\app.out.log 2>> logs\app.err.log
