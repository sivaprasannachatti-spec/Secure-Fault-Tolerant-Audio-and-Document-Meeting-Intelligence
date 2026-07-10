import sys
from postgrest.exceptions import APIError
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from src.exception import CustomException
from src.logger import logging
from backend.models.DB_Client import supabase
from backend.services.audio_chat_services import createNewChat, createOldChat, generateChatTitle, streamNewChat, streamOldChat, generateMeetingTitle
from src.prompts.prompts import getPrompts
from backend.utils.SQlite_utils import (
    getMeetingandChattingId, getMessages, getMeetingData, insertChats, 
    getChatsByUserId, sync_offline_data_to_supabase, getMeetingContent
)
from backend.utils.user_utils import isOnline
from src.components.data_transformation import DataTransformation
from src.components.meeting_minutes import MeetingProcessor
from backend.utils.SQlite_utils import save_meeting_offline, save_meeting_placeholder, update_meeting
from langchain_ollama import ChatOllama
from langchain_core.output_parsers import StrOutputParser
import asyncio

# Global Semaphore to prevent multiple concurrent heavy AI tasks (Whisper/Diarization)
# This ensures the server remains responsive even under heavy upload load.
TRANSCRIPTION_SEMAPHORE = asyncio.Semaphore(1)

def handleMeetingGeneration(request, audio_bytes, is_department_wide):
    try:
        dept_id = request.state.user['dept_id']
        team_id = request.state.user.get('team_id')
        online = isOnline()

        async def stream_pipeline():
            from fastapi.concurrency import iterate_in_threadpool
            import json
            
            # Start streaming immediately to establish the connection and prevent Render 30s timeout
            yield f"data: {json.dumps({'stage': 'preprocessing', 'status': 'in_progress'})}\n\n"
            
            try:
                # Run preprocessing in a thread pool to avoid blocking the ASGI server
                loop = asyncio.get_running_loop()
                audio_transformation = DataTransformation()
                cleaned_audio = await loop.run_in_executor(
                    None, audio_transformation.preprocess_audio, audio_bytes
                )
            except Exception as e:
                logging.error(f"Error during audio preprocessing: {e}")
                yield f"data: {json.dumps({'stage': 'preprocessing', 'status': 'error', 'error': str(e)})}\n\n"
                yield "data: [DONE]\n\n"
                return

            if cleaned_audio is None:
                yield f"data: {json.dumps({'stage': 'preprocessing', 'status': 'error', 'error': 'Preprocessed audio is empty'})}\n\n"
                yield "data: [DONE]\n\n"
                return

            yield f"data: {json.dumps({'stage': 'preprocessing', 'status': 'done'})}\n\n"

            # Acquire semaphore to prevent CPU/GPU starvation
            async with TRANSCRIPTION_SEMAPHORE:
                meeting_obj = MeetingProcessor()
                final_report = None
                meeting_title = "Untitled Meeting"

                # iterate_in_threadpool runs the synchronous generator in a separate thread
                async for event in iterate_in_threadpool(meeting_obj.streamMeetingMinutes(target_dept=dept_id, cleaned_audio=cleaned_audio)):
                    try:
                        event_data = event.replace("data: ", "").strip()
                        parsed = json.loads(event_data)
                        if parsed.get('stage') == 'title' and parsed.get('status') == 'done':
                            meeting_title = parsed.get('final_text', 'Untitled Meeting')
                        if parsed.get('stage') == 'complete':
                            final_report = parsed.get('final_report', '')
                    except:
                        pass
                    yield event

                # After pipeline completes, save everything to DB
                if final_report:
                    yield f"data: {json.dumps({'stage': 'saving', 'status': 'in_progress'})}\n\n"
                    
                    if online:
                        response = (
                            supabase.table("meetings")
                            .insert({
                                "target_dept": dept_id, 
                                "team_id": team_id, 
                                "is_department_wide": is_department_wide, 
                                "final_report": final_report,
                                "meeting_title": meeting_title
                            })
                            .execute()
                        )
                        generated_id = response.data[0]['meeting_id'] if response.data else None
                    else:
                        from backend.utils.SQlite_utils import save_meeting_offline
                        generated_id = save_meeting_offline(dept_id, team_id, is_department_wide, final_report, meeting_title)

                    yield f"data: {json.dumps({'stage': 'saved', 'meeting_id': generated_id, 'meeting_title': meeting_title, 'final_report': final_report})}\n\n"
                
                yield "data: [DONE]\n\n"

        return StreamingResponse(stream_pipeline(), media_type="text/event-stream")

    except Exception as e:
        raise CustomException(e, sys)

def handleNewChat(msg, request):
    try:
        meeting_id = msg.meeting_id
        if meeting_id is None:
            raise HTTPException(status_code=404, detail="Please upload a meeting first for chatting.")
            
        online = isOnline()
        
        if online:
            response = (
                supabase.table("meetings")
                .select("meeting_id, target_dept, team_id, is_department_wide, final_report")
                .eq("meeting_id", meeting_id)
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=404, detail="Please upload a meeting first for chatting.")
            meeting = response.data[0]
        else:
            meeting = getMeetingData(meeting_id=meeting_id)
            if meeting is None:
                raise HTTPException(status_code=404, detail="Please upload a meeting first for chatting.")

        if request.state.user['dept_id'] != meeting['target_dept'] or (meeting.get('team_id') != request.state.user.get('team_id') and not meeting.get('is_department_wide')):
            raise HTTPException(status_code=403, detail="You cannot access this meeting")
        
        if not meeting.get('final_report'):
            raise HTTPException(status_code=404, detail='Meeting not found. Please upload a meeting first.')
        
        chat_title = generateChatTitle(
            prompt=getPrompts()[4],
            msg=msg
        )
        
        if online:
            resp = (
                supabase.table("chats")
                .insert({"chat_title": chat_title, "user_id": request.state.user['id'], "meeting_id": meeting['meeting_id']})
                .execute()
            )
            chat_id = resp.data[0]['chat_id']
        else:
            chat_id = insertChats(chat_title=chat_title, user_id=request.state.user['id'], meeting_id=meeting_id)

        import json
        def stream_with_title():
            # Send chat_title as first SSE event so frontend can update the sidebar
            yield f"data: {json.dumps({'chat_title': chat_title, 'chat_id': chat_id})}\n\n"
            # Then stream all tokens
            yield from streamNewChat(msg=msg, chat_id=chat_id, final_report=meeting.get('final_report', ''), online=online)

        return StreamingResponse(stream_with_title(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

def handleOldChat(chat_id, msg, request):
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
                .select("target_dept, team_id, is_department_wide, final_report, meeting_type")
                .eq("meeting_id", meeting_id)
                .eq("meeting_type", "audio")
                .execute()
            )
            if not meeting.data:
                raise HTTPException(status_code=404, detail="No meeting associated with this chat found")
            
            target_dept = meeting.data[0]['target_dept']
            team_id = meeting.data[0]['team_id']
            is_department_wide = meeting.data[0]['is_department_wide']
            final_report = meeting.data[0]['final_report']
        
        else:
            # For offline, we likely already have the chat_id from params, 
            # but we need to fetch the associated meeting_id.
            from backend.utils.SQlite_utils import getChatData
            chat_info = getChatData(chat_id=chat_id)
            if chat_info is None:
                raise HTTPException(status_code=404, detail="No offline chat found")
            
            meeting_id = chat_info['meeting_id']
            meeting = getMeetingData(meeting_id=meeting_id)
            if meeting is None or meeting.get('meeting_type') != 'audio':
                raise HTTPException(status_code=404, detail="No offline audio meeting found")
            
            target_dept = meeting['target_dept']
            team_id = meeting.get('team_id')
            is_department_wide = meeting.get('is_department_wide')
            final_report = meeting['final_report']
            
        if request.state.user['dept_id'] != target_dept or (team_id != request.state.user.get('team_id') and not is_department_wide):
            raise HTTPException(status_code=403, detail="You cannot access this chat")
        
        if online:
            chat = (
                supabase.table("messages")
                .select("message, type")
                .eq("chat_id", chat_id)
                .execute()
            )
            chat_history = chat.data 
        else:
            chat_history = getMessages(chat_id=chat_id)

        return StreamingResponse(
            streamOldChat(msg=msg, chat_history=chat_history, chat_id=chat_id, final_report=final_report, online=online),
            media_type="text/event-stream"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

def handleGettingOldChat(chat_id, request, limit=None, before_id=None):
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
                .select("target_dept, team_id, is_department_wide, final_report, meeting_type")
                .eq("meeting_id", meeting_id)
                .eq("meeting_type", "audio")
                .execute()
            )
            if not meeting.data:
                raise HTTPException(status_code=404, detail="No meeting found")
            target_dept = meeting.data[0]['target_dept']
            team_id = meeting.data[0]['team_id']
            is_department_wide = meeting.data[0]['is_department_wide']
        
        else:
            from backend.utils.SQlite_utils import getChatData
            chat_info = getChatData(chat_id=chat_id)
            if chat_info is None:
                raise HTTPException(status_code=404, detail="No offline chat found")
            chat_id = chat_info['chat_id']
            meeting_id = chat_info['meeting_id']
            
            target_dept_info = getMeetingData(meeting_id=meeting_id)
            if target_dept_info is None or target_dept_info.get('meeting_type') != 'audio':
                raise HTTPException(status_code=404, detail="No offline audio meeting found")
            target_dept = target_dept_info['target_dept']
            team_id = target_dept_info.get('team_id')
            is_department_wide = target_dept_info.get('is_department_wide')
                        
        if request.state.user['dept_id'] != target_dept or (team_id != request.state.user.get('team_id') and not is_department_wide):
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
            
        # Get final report from the meeting data object (already fetched above)
        final_report = meeting.data[0]['final_report'] if online else target_dept_info['final_report']

        return JSONResponse(status_code=200, content={
            "message": "Old chat retrieved successfully", 
            "chat": chat_history,
            "final_report": final_report,
            "meeting_id": meeting_id,
            "meeting_type": "audio"
        })
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

def handleGetAllChats(request, background_tasks=None):
    try:
        online = isOnline()
        user_id = request.state.user['id']
        
        if online:
            # Check for any pending offline data and sync it in the background so it doesn't block loading
            if background_tasks:
                background_tasks.add_task(sync_offline_data_to_supabase)
            else:
                try:
                    sync_offline_data_to_supabase()
                except Exception as sync_e:
                    logging.warning(f"Background sync failed: {sync_e}")

            try:
                response = (
                    supabase.table("chats")
                    .select("chat_title, chat_id, meetings!inner(meeting_type)")
                    .eq("user_id", user_id)
                    .eq("meetings.meeting_type", "audio")
                    .execute()
                )
            except APIError as e:
                if "meeting_type" in str(e):
                    logging.warning("⚠️ Supabase 'meeting_type' column missing. Falling back to non-isolated query.")
                    response = (
                        supabase.table("chats")
                        .select("chat_title, chat_id, meetings!inner(meeting_id)")
                        .eq("user_id", user_id)
                        .execute()
                    )
                else:
                    raise e
            chats = response.data
        else:
            chats = getChatsByUserId(user_id=user_id, meeting_type='audio')
            
        return JSONResponse(status_code=200, content={"message": "Chats retrieved successfully", "chats": chats})
    except Exception as e:
        raise CustomException(e, sys)

def handleGetAllMeetings(request):
    try:
        online = isOnline()
        # 1. Look up the department and team the user belongs to
        dept_id = request.state.user['dept_id']
        team_id = request.state.user.get('team_id')
        
        if online:
            # 2. Fetch ALL meetings that belong to this exact department
            logging.info(f"🔍 Fetching meetings for Dept: {dept_id}, User Team: {team_id}")
            
            response = None
            last_err = None
            for attempt in range(3):
                try:
                    response = (
                        supabase.table("meetings")
                        .select("meeting_id, target_dept, meeting_title, team_id, is_department_wide, meeting_type")
                        .eq("target_dept", dept_id)
                        .eq("meeting_type", "audio")
                        .neq("final_report", "EMPTY")
                        .neq("final_report", "")
                        .execute()
                    )
                    break
                except Exception as e:
                    last_err = e
                    if "meeting_type" in str(e):
                        logging.warning("⚠️ Supabase 'meeting_type' column missing in meetings table. Falling back to non-isolated query.")
                        try:
                            response = (
                                supabase.table("meetings")
                                .select("meeting_id, target_dept, meeting_title, team_id, is_department_wide")
                                .eq("target_dept", dept_id)
                                .neq("final_report", "EMPTY")
                                .neq("final_report", "")
                                .execute()
                            )
                            break
                        except: pass
                    logging.warning(f"🔄 Supabase fetch attempt {attempt+1} failed: {e}. Retrying...")
                    import time
                    time.sleep(1) # Brief pause before retry

            if not response:
                raise last_err if last_err else Exception("Failed to fetch meetings after retries")
            
            # Use STR comparison to avoid type mismatches (int vs string)
            valid_meetings = []
            u_team_id = str(team_id) if team_id is not None else ""
            logging.info(f"🔍 DEBUG: Your Account -> Dept: {dept_id}, Team: {u_team_id}")
            
            for m in response.data:
                m_team_id = str(m.get('team_id')) if m.get('team_id') is not None else ""
                is_wide = m.get('is_department_wide')
                meeting_title = m.get('meeting_title')
                
                # Eligibility: be Dept-Wide OR match user Team
                if is_wide or m_team_id == u_team_id:
                    valid_meetings.append(m)
                    logging.info(f"✅ DEBUG: Meeting '{meeting_title}' APPROVED.")
                else:
                    logging.info(f"❌ DEBUG: Meeting '{meeting_title}' REJECTED (Team mismatch).")

            logging.info(f"✅ FINAL: Found {len(valid_meetings)} valid meetings.")
            return JSONResponse(status_code=200, content={"meetings": valid_meetings})
        else:
            # 4. Fetch the department meetings from the local SQLite DB if offline
            from backend.utils.SQlite_utils import getMeetingsByDept
            meetings = getMeetingsByDept(dept_id=dept_id, meeting_type='audio', exclude_report=True)
            valid_meetings = []
            for m in meetings:
                m_team_id = str(m.get('team_id')) if m.get('team_id') is not None else ""
                u_team_id = str(team_id) if team_id is not None else ""
                if m.get('is_department_wide') or m_team_id == u_team_id:
                    valid_meetings.append(m)
            
            return JSONResponse(status_code=200, content={"meetings": valid_meetings})
            
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

def handleGetMeetingContent(request, meeting_id):
    try:
        online = isOnline()
        if online:
            response = (
                supabase.table("meetings")
                .select("meeting_id, target_dept, team_id, is_department_wide, final_report, meeting_title")
                .eq("meeting_id", meeting_id)
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=404, detail="No meeting found")
            meeting = response.data[0]
        else:
            meeting = getMeetingData(meeting_id=meeting_id)
            if meeting == None:
                raise HTTPException(status_code=404, detail="No meeting found")
            
        if request.state.user['dept_id'] != meeting['target_dept'] or (meeting.get('team_id') != request.state.user.get('team_id') and not meeting.get('is_department_wide')):
            raise HTTPException(status_code=403, detail="You cannot access this meeting")
            
        return JSONResponse(status_code=200, content={"message": "Meeting content retrieved", "meeting_content": meeting})
    except Exception as e:
        raise CustomException(e, sys)
