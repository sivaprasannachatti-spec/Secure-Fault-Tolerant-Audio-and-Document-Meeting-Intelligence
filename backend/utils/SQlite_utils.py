import sqlite3
import sys
import os
import time

from src.exception import CustomException
from src.logger import logging

from backend.models.DB_Client import supabase
from backend.utils.user_utils import isOnline

def getMeetingData(meeting_id: int):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        conn.row_factory = sqlite3.Row  
        cursor = conn.cursor()

        cursor.execute(
            "select target_dept, team_id, is_department_wide, final_report from meetings where meeting_id = ?",(meeting_id,)
        )
        meeting_data = cursor.fetchone()
        conn.close()

        if meeting_data:
            return dict(meeting_data)
        return None
    except Exception as e:
        raise CustomException(e, sys)

def getMeetingandChattingId(chat_title: str):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        conn.row_factory = sqlite3.Row  
        cursor = conn.cursor()

        cursor.execute(
            "select meeting_id, chat_id from chats where chat_title = ?",(chat_title,)
        )
        response = cursor.fetchone()
        conn.close()
        if response:
            return dict(response)
        return None
    except Exception as e:
        raise CustomException(e, sys)

def getChatData(chat_id: int):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        conn.row_factory = sqlite3.Row  
        cursor = conn.cursor()

        cursor.execute(
            "select chat_id, chat_title, meeting_id, user_id from chats where chat_id = ?",(chat_id,)
        )
        response = cursor.fetchone()
        conn.close()
        if response:
            return dict(response)
        return None
    except Exception as e:
        raise CustomException(e, sys)

def getMessages(chat_id: int):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        conn.row_factory = sqlite3.Row  
        cursor = conn.cursor()

        cursor.execute(
            "select message, type from messages where chat_id = ? ",(chat_id,)
        )
        messages = cursor.fetchall()
        conn.close()
        if messages:
            return [dict(msg) for msg in messages]
        return None
    except Exception as e:
        raise CustomException(e, sys)

def insertChats(chat_title, user_id, meeting_id):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        conn.row_factory = sqlite3.Row  
        cursor = conn.cursor()

        chat_id = -int(time.time() * 1000)

        cursor.execute(
            "insert into chats (chat_id, chat_title, user_id, meeting_id) values(?, ?, ?, ?)",(chat_id, chat_title, user_id, meeting_id,)
        )
        conn.commit()
        conn.close()
        return chat_id
    except Exception as e:
        raise CustomException(e, sys)

def insertMessages(chat_id: int, type: str, message: str):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        cursor = conn.cursor()

        message_id = -int(time.time() * 1000)

        cursor.execute(
            "insert into messages (message_id, chat_id, type, message) values(?, ?, ?, ?)",(message_id, chat_id, type, message)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        raise CustomException(e, sys)

def sync_offline_data_to_supabase():
    try:
        if not isOnline():
            return
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # STEP 1: Sync Meetings (Crucial for report persistence)
        cursor.execute("SELECT * FROM meetings WHERE synced = 0")
        offline_meetings = cursor.fetchall()
        for mtg in offline_meetings:
            try:
                # Push meeting to Supabase
                # Note: If meeting_id is native to your DB, you might need to handle ID generation
                supabase.table("meetings").insert({
                    "meeting_id": mtg['meeting_id'],
                    "target_dept": mtg['target_dept'],
                    "team_id": mtg['team_id'],
                    "is_department_wide": mtg['is_department_wide'],
                    "final_report": mtg['final_report'],
                    "meeting_title": mtg['meeting_title']
                }).execute()
                
                cursor.execute("UPDATE meetings SET synced = 1 WHERE meeting_id = ?", (mtg['meeting_id'],))
                conn.commit()
            except Exception as e:
                logging.error(f"Failed to sync meeting {mtg['meeting_id']}: {e}")
                continue

        # STEP 2: Sync Chats
        cursor.execute("SELECT * FROM chats WHERE synced = 0")
        offline_chats = cursor.fetchall()

        for chat in offline_chats:
            try:
                negative_chat_id = chat['chat_id']
                
                # Push to Supabase
                response = supabase.table("chats").insert({
                    "chat_title": chat['chat_title'],
                    "id": chat['user_id'],          
                    "meeting_id": chat['meeting_id']
                }).execute()
                
                if response.data:
                    real_chat_id = response.data[0]['chat_id']
                    
                    # Update messages to the real ID and mark chat as synced immediately
                    cursor.execute(
                        "UPDATE messages SET chat_id = ? WHERE chat_id = ?",
                        (real_chat_id, negative_chat_id)
                    )
                    cursor.execute(
                        "UPDATE chats SET chat_id = ?, synced = 1 WHERE chat_id = ?",
                        (real_chat_id, negative_chat_id)
                    )
                    conn.commit() 
            except Exception as e:
                logging.error(f"Failed to sync chat {chat['chat_id']}: {e}")
                continue

        # STEP 3: Sync Messages
        cursor.execute("SELECT * FROM messages WHERE synced = 0 AND chat_id > 0")
        offline_messages = cursor.fetchall()
        
        for msg in offline_messages:
            try:
                local_message_id = msg['message_id']
                
                supabase.table("messages").insert({
                    "chat_id": msg['chat_id'],
                    "type": msg['type'],
                    "message": msg['message']
                }).execute()

                cursor.execute(
                    "UPDATE messages SET synced = 1 WHERE message_id = ?",
                    (local_message_id,)
                )
                conn.commit() 
            except Exception as e:
                logging.error(f"Failed to sync message {msg['message_id']}: {e}")
                continue

        conn.close()
        print("Successfully synced all offline data to Supabase!")
    except Exception as e:
        raise CustomException(e, sys)

def save_meeting_offline(target_dept, team_id, is_department_wide, final_report, meeting_title):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        meeting_id = -int(time.time() * 1000)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO meetings (meeting_id, target_dept, team_id, is_department_wide, final_report, meeting_title, synced) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (meeting_id, target_dept, team_id, is_department_wide, final_report, meeting_title)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        raise CustomException(e, sys)

def save_meeting_placeholder(target_dept, team_id, is_department_wide, meeting_title="Processing..."):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        meeting_id = -int(time.time() * 1000)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO meetings (meeting_id, target_dept, team_id, is_department_wide, final_report, meeting_title, synced) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (meeting_id, target_dept, team_id, is_department_wide, "", meeting_title)
        )
        conn.commit()
        conn.close()
        return meeting_id
    except Exception as e:
        raise CustomException(e, sys)

def update_meeting(meeting_id, final_report, meeting_title):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE meetings SET final_report = ?, meeting_title = ?, synced = 0 WHERE meeting_id = ?",
            (final_report, meeting_title, meeting_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        raise CustomException(e, sys)

def insertMeeting(target_dept_id: int, team_id: int, is_department_wide: bool, final_report: str):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        cursor = conn.cursor()

        # Generate a temporary negative ID for offline syncing, matching your insertChats pattern
        meeting_id = -int(time.time() * 1000)

        cursor.execute(
            "insert into meetings (meeting_id, target_dept, team_id, is_department_wide, final_report, synced) values(?, ?, ?, ?, ?, 0)",
            (meeting_id, target_dept_id, team_id, is_department_wide, final_report)
        )
        conn.commit()
        conn.close()
        return meeting_id
    except Exception as e:
        raise CustomException(e, sys)

def getChatsByUserId(user_id: str):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        conn.row_factory = sqlite3.Row  
        cursor = conn.cursor()

        cursor.execute(
            "select chat_title, chat_id from chats where user_id = ?",(user_id,)
        )
        response = cursor.fetchall()
        conn.close()
        if response:
            return [dict(chat) for chat in response]
        return []
    except Exception as e:
        raise CustomException(e, sys)

def getMeetingContent(meeting_id: int):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        conn.row_factory = sqlite3.Row  
        cursor = conn.cursor()

        cursor.execute(
            "select meeting_id, target_dept, team_id, is_department_wide, final_report, meeting_title from meetings where meeting_id = ?",(meeting_id,)
        )
        response = cursor.fetchone()
        conn.close()
        if response:
            return dict(response)
        return None
    except Exception as e:
        raise CustomException(e, sys)

def getMeetingsByDept(dept_id: int):
    try:
        conn = sqlite3.connect(database=os.environ['DB_FILE'])
        conn.row_factory = sqlite3.Row  
        cursor = conn.cursor()

        cursor.execute(
            "select meeting_id, target_dept, meeting_title, final_report, team_id, is_department_wide from meetings where target_dept = ?",(dept_id,)
        )
        response = cursor.fetchall()
        conn.close()
        return [dict(row) for row in response]
    except Exception as e:
        raise CustomException(e, sys)