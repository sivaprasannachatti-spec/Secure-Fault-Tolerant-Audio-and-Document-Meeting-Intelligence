import sqlite3
import sys
import os

from backend.models.DB_Client import supabase
from backend.utils.user_utils import isOnline
from src.exception import CustomException
from src.logger import logging

# Use environment variable for DB file to allow dual-server isolation
DB_FILE = os.getenv("DB_FILE", "offline_queue.db").strip()

def setup_offline_database():
    try:
        # Crucial: Use the environment-specific DB file
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Enable Foreign Key enforcement in SQLite
        cursor.execute("PRAGMA foreign_keys = ON")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                dept_id INTEGER PRIMARY KEY,
                dept_name TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT,
                email TEXT UNIQUE,
                dept_id INTEGER,
                team_id INTEGER,
                synced INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            chat_title TEXT,
            user_id TEXT,
            meeting_id INTEGER,
            synced INTEGER DEFAULT 0
        )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                type TEXT,
                message TEXT,
                synced INTEGER DEFAULT 0
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meetings (
                meeting_id INTEGER PRIMARY KEY,
                target_dept INTEGER,
                team_id INTEGER,
                is_department_wide INTEGER DEFAULT 0,
                final_report TEXT,
                meeting_title TEXT,
                meeting_type TEXT DEFAULT 'audio',
                synced INTEGER DEFAULT 0,
                FOREIGN KEY (target_dept) REFERENCES departments(dept_id)
            )
        """)
        
        # Document Trees table for Vectorless RAG (NOT synced to Supabase)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_trees (
                tree_id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_id INTEGER UNIQUE,
                tree_json TEXT NOT NULL,
                file_type TEXT,
                token_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (meeting_id) REFERENCES meetings(meeting_id)
            )
        """)

        # Performance Indexes for optimization
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chats_user_id ON chats(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_meetings_target_dept_type ON meetings(target_dept, meeting_type)")

        # Configure SQLite DB journal mode for high performance
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA cache_size = -4000") # 4MB cache
        
        # Migration: Ensure columns exist if they weren't in the original schema
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN team_id INTEGER")
        except: pass
        try:
            cursor.execute("ALTER TABLE meetings ADD COLUMN team_id INTEGER")
        except: pass
        try:
            cursor.execute("ALTER TABLE meetings ADD COLUMN is_department_wide INTEGER DEFAULT 0")
        except: pass
        try:
            cursor.execute("ALTER TABLE meetings ADD COLUMN meeting_type TEXT DEFAULT 'audio'")
        except: pass
        
        # Pre-populate departments
        cursor.execute("INSERT OR IGNORE INTO departments (dept_id, dept_name) VALUES (101, 'Engineering'), (102, 'Sales'), (103, 'Marketing'), (104, 'HR'), (105, 'Operations')")
        
        conn.commit()
        conn.close()

    except Exception as e:
        raise CustomException(e, sys)

def sync_all_users_to_sqlite():
    try:
        if not isOnline():
            print("Starting offline - Skipping user sync. Relying on past SQLite data...")
            return
        response = (supabase.table("users").select("id", "name", "email", "dept_id", "team_id").execute())
        all_users = response.data

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        for user in all_users:
            cursor.execute("""
                INSERT OR REPLACE INTO users (id, name, email, dept_id, team_id) 
                VALUES (?, ?, ?, ?, ?)
            """, (user['id'], user['name'], user['email'], user['dept_id'], user.get('team_id')))
        conn.commit() 
        conn.close()
    except Exception as e:
        raise CustomException(e, sys)
    
def get_user_from_sqlite(email: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row  # Makes it return a Dict-like object
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, name, email, dept_id, team_id FROM users WHERE email = ?", (email,))
        user_row = cursor.fetchone()
        
        conn.close()
        
        if user_row:
             return dict(user_row)
        return None
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        return None