import patch_platform
import uvicorn
import os
import sys
from dotenv import load_dotenv

if __name__ == "__main__":
    load_dotenv()
    
    # Allow port to be passed as an argument, default to 8000
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
            
    # Set environment variables for the app if not already set
    if not os.getenv("APP_MODE"):
        os.environ["APP_MODE"] = "AUDIO"
    if not os.getenv("DB_FILE"):
        os.environ["DB_FILE"] = "audio_meeting.db"
        
    print(f"Starting server in {os.getenv('APP_MODE')} mode on port {port}...")
    
    # Import the app object directly to ensure it runs in this process with the monkeypatch
    from backend.app import app
    
    uvicorn.run(app, host="0.0.0.0", port=port)
