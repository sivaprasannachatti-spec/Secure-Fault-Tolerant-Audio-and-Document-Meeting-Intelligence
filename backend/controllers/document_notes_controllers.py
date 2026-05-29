"""
Document Notes Controllers — Request handlers for the document workflow.

Follows the exact same pattern as audio_chat_controllers.py but uses:
- DocumentProcessor for pipeline orchestration
- document_trees table for tree persistence
- Document provider pool for LLM calls
"""

import sys
from postgrest.exceptions import APIError

import json

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from src.exception import CustomException
from src.logger import logging
from backend.models.DB_Client import supabase
from backend.services.document_notes_services import (
    streamDocumentNewChat, streamDocumentOldChat, 
    generateDocumentMeetingTitle, generateDocumentChatTitle
)
from src.prompts.prompts import getDocumentPrompts
from backend.utils.SQlite_utils import (
    getMeetingData, getMessages, insertChats,
    getChatsByUserId, save_document_tree, get_document_tree,
    save_meeting_offline_document
)
from backend.utils.user_utils import isOnline
from src.components.document_processor import DocumentProcessor


def handleDocumentGeneration(request, file_bytes, file_type, is_department_wide):
    """Orchestrates the complete document processing pipeline with SSE streaming."""
    try:
        online = isOnline()
        dept_id = request.state.user['dept_id']
        team_id = request.state.user.get('team_id')

        def stream_pipeline():
            processor = DocumentProcessor()
            final_report = None
            tree_json = None
            token_count = 0

            # Stream all pipeline stages
            meeting_title = "Untitled Document"
            for event in processor.streamDocumentPipeline(
                file_bytes=file_bytes, file_type=file_type, dept_id=dept_id
            ):
                # Capture the final report and tree from the 'complete' event
                try:
                    event_data = event.replace("data: ", "").strip()
                    parsed = json.loads(event_data)
                    if parsed.get('stage') == 'title' and parsed.get('status') == 'done':
                        meeting_title = parsed.get('final_text', 'Untitled Document')
                    if parsed.get('stage') == 'complete':
                        final_report = parsed.get('final_report', '')
                        tree_json = parsed.get('tree_json', '')
                        token_count = parsed.get('token_count', 0)
                except:
                    pass
                yield event

            # After pipeline completes, save everything to DB
            if final_report:
                yield f"data: {json.dumps({'stage': 'saving', 'status': 'in_progress'})}\n\n"

                if online:
                    meeting_data = {
                        "target_dept": dept_id,
                        "team_id": team_id,
                        "is_department_wide": is_department_wide,
                        "final_report": final_report,
                        "meeting_title": meeting_title,
                        "meeting_type": "document"
                    }
                    try:
                        response = supabase.table("meetings").insert(meeting_data).execute()
                    except APIError as e:
                        if "meeting_type" in str(e):
                            logging.warning("⚠️ Supabase 'meeting_type' column missing. Saving without it.")
                            del meeting_data["meeting_type"]
                            response = supabase.table("meetings").insert(meeting_data).execute()
                        else:
                            raise e
                    generated_id = response.data[0]['meeting_id'] if response.data else None
                else:
                    generated_id = save_meeting_offline_document(
                        dept_id, team_id, is_department_wide, final_report, meeting_title
                    )

                # Save document tree to local SQLite
                if tree_json and generated_id:
                    save_document_tree(
                        meeting_id=generated_id,
                        tree_json=tree_json,
                        file_type=file_type,
                        token_count=token_count
                    )

                yield f"data: {json.dumps({'stage': 'saved', 'meeting_id': generated_id, 'meeting_title': meeting_title, 'final_report': final_report, 'meeting_type': 'document'})}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_pipeline(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)


def handleDocumentNewChat(msg, request):
    """Creates a new chat session for a document-based meeting."""
    try:
        meeting_id = msg.meeting_id
        if meeting_id is None:
            raise HTTPException(status_code=404, detail="Please upload a document first for chatting.")

        online = isOnline()

        if online:
            response = (
                supabase.table("meetings")
                .select("meeting_id, target_dept, team_id, is_department_wide, final_report")
                .eq("meeting_id", meeting_id)
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=404, detail="Please upload a document first for chatting.")
            meeting = response.data[0]
        else:
            meeting = getMeetingData(meeting_id=meeting_id)
            if meeting is None:
                raise HTTPException(status_code=404, detail="Please upload a document first for chatting.")

        # GBAC/RBAC Access Control (same as audio workflow)
        if request.state.user['dept_id'] != meeting['target_dept'] or (
            meeting.get('team_id') != request.state.user.get('team_id') and not meeting.get('is_department_wide')
        ):
            raise HTTPException(status_code=403, detail="You cannot access this meeting")

        # Get document tree for context
        tree_data = get_document_tree(meeting_id=meeting_id)
        document_tree = tree_data['tree_json'] if tree_data else meeting.get('final_report', '')

        if not document_tree:
            raise HTTPException(status_code=404, detail="Document not found. Please upload a document first.")

        # Generate chat title
        doc_prompts = getDocumentPrompts()
        chat_title = generateDocumentChatTitle(prompt=doc_prompts[7], msg=msg)

        if online:
            resp = (
                supabase.table("chats")
                .insert({"chat_title": chat_title, "id": request.state.user['id'], "meeting_id": meeting['meeting_id']})
                .execute()
            )
            chat_id = resp.data[0]['chat_id']
        else:
            chat_id = insertChats(chat_title=chat_title, user_id=request.state.user['id'], meeting_id=meeting_id)

        def stream_with_title():
            yield f"data: {json.dumps({'chat_title': chat_title, 'chat_id': chat_id})}\n\n"
            yield from streamDocumentNewChat(
                msg=msg, chat_id=chat_id, document_tree=document_tree, online=online
            )

        return StreamingResponse(stream_with_title(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)


def handleDocumentOldChat(chat_id, msg, request):
    """Continues an existing chat session for a document-based meeting."""
    try:
        online = isOnline()

        if online:
            response = (
                supabase.table("chats")
                .select("meeting_id, chat_id")
                .eq("chat_id", chat_id)
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=404, detail="No chat found")

            chat_id = response.data[0]['chat_id']
            meeting_id = response.data[0]['meeting_id']

            meeting = (
                supabase.table("meetings")
                .select("target_dept, team_id, is_department_wide, final_report")
                .eq("meeting_id", meeting_id)
                .execute()
            )
            if not meeting.data:
                raise HTTPException(status_code=404, detail="No meeting associated with this chat found")

            target_dept = meeting.data[0]['target_dept']
            team_id = meeting.data[0]['team_id']
            is_department_wide = meeting.data[0]['is_department_wide']
        else:
            from backend.utils.SQlite_utils import getChatData
            chat_info = getChatData(chat_id=chat_id)
            if chat_info is None:
                raise HTTPException(status_code=404, detail="No offline chat found")

            meeting_id = chat_info['meeting_id']
            meeting = getMeetingData(meeting_id=meeting_id)
            if meeting is None:
                raise HTTPException(status_code=404, detail="No offline meeting found")

            target_dept = meeting['target_dept']
            team_id = meeting.get('team_id')
            is_department_wide = meeting.get('is_department_wide')

        # GBAC/RBAC Access Control
        if request.state.user['dept_id'] != target_dept or (
            team_id != request.state.user.get('team_id') and not is_department_wide
        ):
            raise HTTPException(status_code=403, detail="You cannot access this chat")

        # Get document tree
        tree_data = get_document_tree(meeting_id=meeting_id)
        if online:
            document_tree = tree_data['tree_json'] if tree_data else meeting.data[0].get('final_report', '')
        else:
            document_tree = tree_data['tree_json'] if tree_data else meeting.get('final_report', '')

        # Get chat history
        if online:
            chat = (
                supabase.table("messages")
                .select("message, type")
                .eq("chat_id", chat_id)
                .execute()
            )
            chat_history = chat.data
        else:
            chat_history = getMessages(chat_id=chat_id) or []

        return StreamingResponse(
            streamDocumentOldChat(
                msg=msg, chat_history=chat_history, chat_id=chat_id,
                document_tree=document_tree, online=online
            ),
            media_type="text/event-stream"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)


def handleDocumentGetOldChat(chat_id, request, limit=None, before_id=None):
    """Retrieves old chat messages for a document-based meeting."""
    try:
        online = isOnline()

        if online:
            response = (
                supabase.table("chats")
                .select("meeting_id, chat_id")
                .eq("chat_id", chat_id)
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=404, detail="No chat found")

            chat_id = response.data[0]['chat_id']
            meeting_id = response.data[0]['meeting_id']

            meeting = (
                supabase.table("meetings")
                .select("target_dept, team_id, is_department_wide, final_report")
                .eq("meeting_id", meeting_id)
                .execute()
            )
            if not meeting.data:
                raise HTTPException(status_code=404, detail="No meeting found")
            target_dept = meeting.data[0]['target_dept']
            team_id = meeting.data[0]['team_id']
            is_department_wide = meeting.data[0]['is_department_wide']
            final_report = meeting.data[0]['final_report']
        else:
            from backend.utils.SQlite_utils import getChatData
            chat_info = getChatData(chat_id=chat_id)
            if chat_info is None:
                raise HTTPException(status_code=404, detail="No offline chat found")
            chat_id = chat_info['chat_id']
            meeting_id = chat_info['meeting_id']

            target_dept_info = getMeetingData(meeting_id=meeting_id)
            if target_dept_info is None:
                raise HTTPException(status_code=404, detail="No offline meeting found")
            target_dept = target_dept_info['target_dept']
            team_id = target_dept_info.get('team_id')
            is_department_wide = target_dept_info.get('is_department_wide')
            final_report = target_dept_info['final_report']

        # GBAC/RBAC
        if request.state.user['dept_id'] != target_dept or (
            team_id != request.state.user.get('team_id') and not is_department_wide
        ):
            raise HTTPException(status_code=403, detail="You cannot access this chat")

        if online:
            query = (
                supabase.table("messages")
                .select("message_id, message, type")
                .eq("chat_id", chat_id)
            )
            if limit is not None:
                query = query.order("message_id", desc=True)
                if before_id:
                    query = query.lt("message_id", before_id)
                query = query.limit(limit)
                
                chat = query.execute()
                if chat.data:
                    chat_history = list(reversed(chat.data))
                else:
                    chat_history = []
            else:
                query = query.order("message_id", desc=False)
                chat = query.execute()
                chat_history = chat.data if chat.data else []
        else:
            chat_history = getMessages(chat_id=chat_id, limit=limit, before_id=before_id) or []

        # Get document tree for context
        tree_data = get_document_tree(meeting_id=meeting_id)
        document_tree = tree_data['tree_json'] if tree_data else None

        return JSONResponse(status_code=200, content={
            "message": "Old chat retrieved successfully",
            "chat": chat_history,
            "final_report": final_report,
            "meeting_id": meeting_id,
            "document_tree": document_tree,
            "meeting_type": "document"
        })
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)
def handleGetAllDocuments(request):
    """Retrieves only document-type meetings for the current department/team."""
    try:
        online = isOnline()
        dept_id = request.state.user['dept_id']
        team_id = request.state.user.get('team_id')
        
        if online:
            try:
                response = (
                    supabase.table("meetings")
                    .select("meeting_id, target_dept, meeting_title, team_id, is_department_wide, meeting_type")
                    .eq("target_dept", dept_id)
                    .eq("meeting_type", "document")
                    .neq("final_report", "EMPTY")
                    .neq("final_report", "")
                    .execute()
                )
            except APIError as e:
                if "meeting_type" in str(e):
                    logging.warning("⚠️ Supabase 'meeting_type' column missing. Falling back to non-isolated query.")
                    response = (
                        supabase.table("meetings")
                        .select("meeting_id, target_dept, meeting_title, team_id, is_department_wide")
                        .eq("target_dept", dept_id)
                        .neq("final_report", "EMPTY")
                        .neq("final_report", "")
                        .execute()
                    )
                else:
                    raise e
            data = response.data
        else:
            from backend.utils.SQlite_utils import getMeetingsByDept
            data = getMeetingsByDept(dept_id=dept_id, meeting_type='document', exclude_report=True)

        valid_docs = []
        u_team_id = str(team_id) if team_id is not None else ""
        
        for d in data:
            d_team_id = str(d.get('team_id')) if d.get('team_id') is not None else ""
            if d.get('is_department_wide') or d_team_id == u_team_id:
                valid_docs.append(d)

        return JSONResponse(status_code=200, content={"meetings": valid_docs})
    except Exception as e:
        raise CustomException(e, sys)

def handleGetAllDocumentChats(request):
    """Retrieves only chat history associated with document meetings."""
    try:
        online = isOnline()
        user_id = request.state.user['id']
        
        if online:
            try:
                response = (
                    supabase.table("chats")
                    .select("chat_title, chat_id, meetings!inner(meeting_type)")
                    .eq("id", user_id)
                    .eq("meetings.meeting_type", "document")
                    .execute()
                )
            except APIError as e:
                if "meeting_type" in str(e):
                    logging.warning("⚠️ Supabase 'meeting_type' column missing. Falling back to non-isolated query.")
                    response = (
                        supabase.table("chats")
                        .select("chat_title, chat_id, meetings!inner(meeting_id)")
                        .eq("id", user_id)
                        .execute()
                    )
                else:
                    raise e
            chats = response.data
        else:
            chats = getChatsByUserId(user_id=user_id, meeting_type='document')
            
        return JSONResponse(status_code=200, content={"message": "Document chats retrieved successfully", "chats": chats})
    except Exception as e:
        raise CustomException(e, sys)

def handleGetDocumentContent(request, meeting_id):
    """Retrieves specific document meeting content with type-check isolation."""
    try:
        online = isOnline()
        if online:
            try:
                response = (
                    supabase.table("meetings")
                    .select("meeting_id, target_dept, team_id, is_department_wide, final_report, meeting_title, meeting_type")
                    .eq("meeting_id", meeting_id)
                    .eq("meeting_type", "document")
                    .execute()
                )
            except APIError as e:
                if "meeting_type" in str(e):
                    logging.warning("⚠️ Supabase 'meeting_type' column missing. Falling back to non-isolated query.")
                    response = (
                        supabase.table("meetings")
                        .select("meeting_id, target_dept, team_id, is_department_wide, final_report, meeting_title")
                        .eq("meeting_id", meeting_id)
                        .execute()
                    )
                else:
                    raise e
            if not response.data:
                raise HTTPException(status_code=404, detail="Document meeting not found")
            meeting = response.data[0]
        else:
            meeting = getMeetingData(meeting_id=meeting_id)
            if meeting == None or meeting.get('meeting_type') != 'document':
                raise HTTPException(status_code=404, detail="Document meeting not found")
            
        if request.state.user['dept_id'] != meeting['target_dept'] or (meeting.get('team_id') != request.state.user.get('team_id') and not meeting.get('is_department_wide')):
            raise HTTPException(status_code=403, detail="You cannot access this document")
            
        return JSONResponse(status_code=200, content={"message": "Document content retrieved", "meeting_content": meeting})
    except Exception as e:
        raise CustomException(e, sys)
