import os
import httpx
from supabase import create_client, ClientOptions
from dotenv import load_dotenv
import sys

load_dotenv()

print("Testing Supabase connection...")
sys.stdout.flush()

url = os.environ.get('SUPABASE_PROJECT_URL')
key = os.environ.get('SUPABASE_API_KEY')

print(f"URL: {url}")
sys.stdout.flush()

try:
    print("Initializing client...")
    sys.stdout.flush()
    # Test WITHOUT custom httpx client first
    supabase = create_client(url, key)
    print("Client initialized!")
    sys.stdout.flush()
    
    print("Fetching one user...")
    sys.stdout.flush()
    res = supabase.table("users").select("id").limit(1).execute()
    print(f"Result: {res.data}")
    sys.stdout.flush()

except Exception as e:
    print(f"Error: {e}")
    sys.stdout.flush()
