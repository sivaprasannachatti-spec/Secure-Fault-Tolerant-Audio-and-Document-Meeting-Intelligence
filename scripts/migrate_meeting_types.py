import os
import sqlite3
import sys

# Ensure we can import backend components
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.models.DB_Client import supabase

def migrate_sqlite(db_file):
    if not os.path.exists(db_file):
        print(f"Skipping {db_file} (not found)")
        return
    print(f"Migrating {db_file}...")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("UPDATE meetings SET meeting_type = 'audio' WHERE meeting_type IS NULL OR meeting_type = ''")
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    print(f"  -> Updated {rows_affected} records in {db_file}")

def migrate_supabase():
    print("Migrating Supabase...")
    try:
        # The python supabase client uses `is_` for IS NULL
        response = supabase.table("meetings").update({"meeting_type": "audio"}).is_("meeting_type", "null").execute()
        print(f"  -> Updated {len(response.data)} records in Supabase")
    except Exception as e:
        print(f"  -> Error migrating Supabase: {e}")

if __name__ == "__main__":
    print("Starting Migration...")
    migrate_sqlite("audio_meeting.db")
    migrate_sqlite("document_meeting.db")
    migrate_supabase()
    print("Migration Complete!")
