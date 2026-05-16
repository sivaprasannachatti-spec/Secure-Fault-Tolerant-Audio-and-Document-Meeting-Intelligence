@echo off
echo 🚀 Starting MeetingAI Dual-Server Architecture...

:: Start Audio Server on Port 8000
start "MeetingAI: Audio Server (Port 8000)" cmd /k "set APP_MODE=AUDIO&& set DB_FILE=audio_meeting.db&& uvicorn backend.app:app --port 8000"

:: Start Document Server on Port 8001
start "MeetingAI: Document Server (Port 8001)" cmd /k "set APP_MODE=DOCS&& set DB_FILE=document_meeting.db&& uvicorn backend.app:app --port 8001"

echo ✅ Both servers are spinning up in separate windows.
echo 🎙️ Audio: http://localhost:8000
echo 📄 Docs:  http://localhost:8001
pause
