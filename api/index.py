import traceback
import os
import sys
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Ensure the project root is in the Python path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    # Import the FastAPI app from backend.app
    from backend.app import app
except Exception as e:
    tb = traceback.format_exc()
    # Create a dummy app so Vercel can boot, but returns the boot error traceback
    app = FastAPI()
    
    @app.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"])
    async def boot_error_handler(path_name: str):
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Serverless Function Boot Error: {str(e)}",
                "traceback": tb
            }
        )
