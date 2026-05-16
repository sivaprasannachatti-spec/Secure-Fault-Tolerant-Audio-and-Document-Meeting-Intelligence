import os
import sys
import time

print("Starting Diagnostic...")
sys.stdout.flush()

print("Importing backend.models.SQlite_db...")
sys.stdout.flush()
from backend.models.SQlite_db import setup_offline_database, sync_all_users_to_sqlite

print("Importing backend.utils.SQlite_utils...")
sys.stdout.flush()
from backend.utils.SQlite_utils import sync_offline_data_to_supabase

print("1. DB Setup")
sys.stdout.flush()
setup_offline_database()

print("2. Sync Users")
sys.stdout.flush()
sync_all_users_to_sqlite()

print("3. Sync Offline")
sys.stdout.flush()
sync_offline_data_to_supabase()

print("4. Mode Detection")
sys.stdout.flush()
mode = os.getenv('APP_MODE', 'AUDIO')
print(f"Mode: {mode}")
sys.stdout.flush()

print("Importing src.utils...")
sys.stdout.flush()
from src.utils import LLAMA_MODEL, QWEN_MODEL

print("5. Warmup Llama")
sys.stdout.flush()
# LLAMA_MODEL.invoke('hi')
print("   Skipped invoke for speed")

print("Success")
sys.stdout.flush()
