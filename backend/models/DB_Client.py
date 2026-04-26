import os

from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(supabase_url=os.environ['SUPABASE_PROJECT_URL'], supabase_key=os.environ['SUPABASE_API_KEY'])