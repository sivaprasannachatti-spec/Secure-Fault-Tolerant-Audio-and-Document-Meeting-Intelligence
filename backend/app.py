import patch_platform
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from backend.routes.user_routes import user_router
from backend.routes.audio_chat_routes import chat_router
from backend.routes.document_notes_routes import document_notes_router
from backend.models.SQlite_db import setup_offline_database, sync_all_users_to_sqlite
from backend.utils.SQlite_utils import sync_offline_data_to_supabase
from fastapi.middleware.cors import CORSMiddleware
import psutil

app = FastAPI(
    title="Meeting Assistant API",
    description="Backend API for Audio and Document Intelligence",
    version="2.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Exception Handler to bubble up error trace details to the frontend
from fastapi import Request
from fastapi.responses import JSONResponse
import traceback

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_msg = str(exc)
    if hasattr(exc, 'error_message'):
        error_msg = exc.error_message
    print(f"ERROR: Global exception caught: {error_msg}")
    return JSONResponse(
        status_code=500,
        content={"detail": error_msg}
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Initializing Server Lifespan...")
    # Setup and sync the offline SQLite DB when the server starts
    setup_offline_database()
    
    # Sync in background to prevent startup hang
    # sync_all_users_to_sqlite()
    # sync_offline_data_to_supabase()
    
    # Robust mode detection
    mode = os.getenv("APP_MODE", "AUDIO").strip().upper()
    print(f"Detected APP_MODE: {mode}")
    
    # Start Health Monitor
    print("Starting Health Monitor...")
    from src.providers.health_monitor import health_monitor
    from src.providers.provider_manager import provider_manager as asr_manager
    from src.providers.llm_service import generation_provider_manager, chat_provider_manager, document_provider_manager

    # Register managers for health monitoring
    health_monitor.register_manager(asr_manager)
    health_monitor.register_manager(generation_provider_manager)
    health_monitor.register_manager(chat_provider_manager)
    health_monitor.register_manager(document_provider_manager)

    # Start the monitor task
    import asyncio
    asyncio.create_task(health_monitor.start())
    
    # Verify and Log All Registered Routes (User Requirement)
    print("\n========= REGISTERED ROUTES =========")
    for route in app.routes:
        methods = getattr(route, "methods", {"GET"})
        print(f"{list(methods)} {route.path}")
    print("=====================================\n")

    yield
    print("Stopping Health Monitor...")
    await health_monitor.stop()

app.router.lifespan_context = lifespan

# Robust mode detection
mode = os.getenv("APP_MODE", "AUDIO").strip().upper()

# Include routes
# Authentication routes are SHARED and must always be present
# Frontend expects /api/user prefix (singular)
app.include_router(user_router, prefix="/api/user", tags=["Users"])

# Include both Document and Audio intelligence workspaces on a single port for production deployment
app.include_router(document_notes_router, prefix="/api/documents", tags=["Document Notes"])
app.include_router(chat_router, prefix="/api/chat", tags=["Audio Chat"])

@app.get("/api/health")
def health_check():
    mode = os.getenv("APP_MODE", "AUDIO").strip().upper()
    return {
        "status": "healthy",
        "mode": mode,
        "memory_usage_mb": psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024,
        "cpu_usage_percent": psutil.cpu_percent()
    }

@app.get("/api/providers/status")
async def provider_status():
    from src.providers.provider_manager import provider_manager as asr_mgr
    from src.providers.llm_service import generation_provider_manager, chat_provider_manager, document_provider_manager
    return {
        "asr": asr_mgr.get_status_report(),
        "generation": generation_provider_manager.get_status_report(),
        "chat": chat_provider_manager.get_status_report(),
        "document": document_provider_manager.get_status_report(),
    }

# Serve the frontend files statically
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_path = os.path.join(BASE_DIR, "frontend")

@app.get("/")
async def root():
    return FileResponse(os.path.join(frontend_path, "index.html"))

app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
