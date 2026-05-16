import patch_platform
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# Simplified client for stability on Windows with Python 3.14
# Uses patch_platform to prevent initialization hangs
supabase = create_client(
    supabase_url=os.environ['SUPABASE_PROJECT_URL'], 
    supabase_key=os.environ['SUPABASE_API_KEY']
)