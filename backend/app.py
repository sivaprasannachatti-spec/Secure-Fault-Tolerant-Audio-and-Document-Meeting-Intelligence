import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from backend.routes.user_routes import user_router
from backend.routes.chat_routes import chat_router
from backend.models.SQlite_db import setup_offline_database, sync_all_users_to_sqlite
from backend.utils.SQlite_utils import sync_offline_data_to_supabase

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup and sync the offline SQLite DB when the server starts
    setup_offline_database()
    sync_all_users_to_sqlite()
    sync_offline_data_to_supabase()
    
    # Warmup: Pre-load LLM models into Ollama's memory so the first user request is fast
    print("🔥 Warming up AI models...")
    try:
        from src.utils import LLAMA_MODEL, QWEN_MODEL
        LLAMA_MODEL.invoke("hi")  # Forces Ollama to load llama3.2:3b into memory
        print("  ✅ Chat model (llama3.2:3b) loaded")
        QWEN_MODEL.invoke("hi")   # Forces Ollama to load qwen3:8b into memory
        print("  ✅ Generation model (qwen3:8b) loaded")
    except Exception as e:
        print(f"  ⚠️ Model warmup failed (non-critical): {e}")
    print("🚀 Server ready! All models pre-loaded.")
    
    yield

app = FastAPI(lifespan=lifespan)

# Enable CORS for frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5500"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router=user_router, prefix="/api/user")
app.include_router(router=chat_router, prefix="/api/chat")

# Serve the frontend files statically
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_path = os.path.join(BASE_DIR, "frontend")

@app.get("/")
async def root():
    return FileResponse(os.path.join(frontend_path, "index.html"))

app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
