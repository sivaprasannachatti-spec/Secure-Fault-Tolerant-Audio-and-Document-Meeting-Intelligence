import sys
import json

from fastapi import HTTPException
from src.exception import CustomException
from src.logger import logging
from src.components.meeting_chat import MeetingChat
from backend.models.DB_Client import supabase
from langchain_ollama import ChatOllama
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage
from backend.utils.user_utils import isOnline
from backend.utils.SQlite_utils import insertMessages, getMessages
from src.utils import QWEN_MODEL, LLAMA_MODEL

def createNewChat(msg, chat_id, final_report):
    try:
        online = isOnline()
        meetingChat = MeetingChat()
        chatResponse = meetingChat.handleNewMeetingChat(query=msg.query, final_report=final_report)
        # Insert user message
        if online:
            supabase.table("messages").insert({
                "chat_id": chat_id, "type": "user", "message": msg.query
            }).execute()
        else:
            insertMessages(chat_id=chat_id, type="user", message=msg.query)
            
        # Insert AI response
        if online:
            response = (
                supabase.table("messages")
                .insert({"chat_id": chat_id, "type": "AI", "message": chatResponse})
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=500, detail="Something went wrong while creating the chat")
            return response.data[0]
        else:
            insertMessages(chat_id=chat_id, type="AI", message=chatResponse)
            return {"chat_id": chat_id, "type": "AI", "message": chatResponse}
            
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

def streamNewChat(msg, chat_id, final_report, online):
    """Generator that streams Q&A tokens and saves full response to DB after completion."""
    # Insert user message before streaming starts
    if online:
        supabase.table("messages").insert({
            "chat_id": chat_id, "type": "user", "message": msg.query
        }).execute()
    else:
        insertMessages(chat_id=chat_id, type="user", message=msg.query)

    meetingChat = MeetingChat()
    logging.info(f"🧠 [AI] Preparing context for Meeting ID: {chat_id}...")
    token_stream = meetingChat.streamNewMeetingChat(query=msg.query, final_report=final_report)

    full_response = ""
    started = False
    for chunk in token_stream:
        if not started:
            logging.info("⚡ [AI] Started generating response tokens!")
            started = True
        full_response += chunk
        yield f"data: {json.dumps({'token': chunk})}\n\n"

    # Save complete AI response to DB after streaming finishes
    if online:
        supabase.table("messages").insert({
            "chat_id": chat_id, "type": "AI", "message": full_response
        }).execute()
    else:
        insertMessages(chat_id=chat_id, type="AI", message=full_response)

    yield "data: [DONE]\n\n"

def generateMeetingTitle(prompt, final_report):
    try:
        llm = QWEN_MODEL
        chain = prompt | llm | StrOutputParser()
        result = chain.invoke({"final_report": final_report})
        return result
    except Exception as e:
        raise CustomException(e, sys)
    
def generateChatTitle(prompt, msg):
    try:
        llm = LLAMA_MODEL
        chain = prompt | llm | StrOutputParser()
        result = chain.invoke({"user_prompt": msg.query})
        return result
    except Exception as e:
        raise CustomException(e, sys)

def createOldChat(msg, chat_history, chat_id, final_report):
    try:
        online = isOnline()
        meeting = MeetingChat()
        # Convert dictionary history to LangChain message objects
        formatted_history = []
        for c in chat_history:
            if c['type'] == 'user':
                formatted_history.append(HumanMessage(content=c['message']))
            else:
                formatted_history.append(AIMessage(content=c['message']))
                
        chatResponse = meeting.handleOldMeetingChat(query=msg.query, chat_history=formatted_history, final_report=final_report)
        # Insert user message
        if online:
            supabase.table("messages").insert({
                "chat_id": chat_id, "type": "user", "message": msg.query
            }).execute()
            # Insert AI response
            response = (
                supabase.table("messages")
                .insert({"chat_id": chat_id, "type": "AI", "message": chatResponse})
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=500, detail="Something went wrong while creating the chat")
            return response.data[0]
        else:
            insertMessages(chat_id=chat_id, type="user", message=msg.query)
            insertMessages(chat_id=chat_id, type="AI", message=chatResponse)
            return {"chat_id": chat_id, "type": "AI", "message": chatResponse}
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

def streamOldChat(msg, chat_history, chat_id, final_report, online):
    """Generator that streams old Q&A tokens and saves full response to DB after completion."""
    # Convert dictionary history to LangChain message objects
    formatted_history = []
    for c in chat_history:
        if c['type'] == 'user':
            formatted_history.append(HumanMessage(content=c['message']))
        else:
            formatted_history.append(AIMessage(content=c['message']))

    # Insert user message before streaming starts
    if online:
        supabase.table("messages").insert({
            "chat_id": chat_id, "type": "user", "message": msg.query
        }).execute()
    else:
        insertMessages(chat_id=chat_id, type="user", message=msg.query)

    meeting = MeetingChat()
    logging.info(f"🧠 [AI] Fetching memory for Chat ID: {chat_id}...")
    token_stream = meeting.streamOldMeetingChat(
        query=msg.query, chat_history=formatted_history, final_report=final_report
    )
    
    full_response = ""
    started = False
    for chunk in token_stream:
        if not started:
            logging.info("⚡ [AI] Started streaming history-based response!")
            started = True
        full_response += chunk
        yield f"data: {json.dumps({'token': chunk})}\n\n"

    # Save complete AI response to DB after streaming finishes
    if online:
        supabase.table("messages").insert({
            "chat_id": chat_id, "type": "AI", "message": full_response
        }).execute()
    else:
        insertMessages(chat_id=chat_id, type="AI", message=full_response)

    yield "data: [DONE]\n\n"