"""
Document Notes Services — Business logic for document-based chat and title generation.

Follows the exact same pattern as audio_chat_services.py but uses
DocumentChat and the Document provider pool.
"""

import sys
import json

from fastapi import HTTPException
from src.exception import CustomException
from src.logger import logging
from src.components.document_chat import DocumentChat
from backend.models.DB_Client import supabase
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage
from backend.utils.user_utils import isOnline
from backend.utils.SQlite_utils import insertMessages, getMessages


def streamDocumentNewChat(msg, chat_id, document_tree, online):
    """Generator that streams document Q&A tokens and saves full response to DB after completion."""
    # Insert user message before streaming starts
    if online:
        supabase.table("messages").insert({
            "chat_id": chat_id, "type": "user", "message": msg.query
        }).execute()
    else:
        insertMessages(chat_id=chat_id, type="user", message=msg.query)

    doc_chat = DocumentChat()
    logging.info(f"📄 [AI] Preparing document context for Chat ID: {chat_id}...")
    token_stream = doc_chat.streamNewDocumentChat(query=msg.query, document_tree=document_tree)

    full_response = ""
    started = False
    for chunk in token_stream:
        if not started:
            logging.info("⚡ [AI] Started generating document response tokens!")
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


def streamDocumentOldChat(msg, chat_history, chat_id, document_tree, online):
    """Generator that streams old document Q&A tokens and saves full response to DB after completion."""
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

    doc_chat = DocumentChat()
    logging.info(f"📄 [AI] Fetching document memory for Chat ID: {chat_id}...")
    token_stream = doc_chat.streamOldDocumentChat(
        query=msg.query, chat_history=formatted_history, document_tree=document_tree
    )

    full_response = ""
    started = False
    for chunk in token_stream:
        if not started:
            logging.info("⚡ [AI] Started streaming document history-based response!")
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


def generateDocumentMeetingTitle(prompt, document_tree):
    """Generates a meeting title from the document tree using the Document Chat pool."""
    try:
        from src.providers.llm_service import invoke_document_chat
        result = invoke_document_chat(
            chain_builder=lambda llm: prompt | llm | StrOutputParser(),
            invoke_args={"document_tree": document_tree}
        )
        return result
    except Exception as e:
        raise CustomException(e, sys)


def generateDocumentChatTitle(prompt, msg):
    """Generates a chat title from the user's opening message. Uses the Document Chat pool."""
    try:
        from src.providers.llm_service import invoke_document_chat
        result = invoke_document_chat(
            chain_builder=lambda llm: prompt | llm | StrOutputParser(),
            invoke_args={"user_prompt": msg.query}
        )
        return result
    except Exception as e:
        raise CustomException(e, sys)
