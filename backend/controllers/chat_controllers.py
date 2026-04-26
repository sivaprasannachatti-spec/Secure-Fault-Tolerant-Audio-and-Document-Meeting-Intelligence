import sys

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from src.exception import CustomException
from src.logger import logging
from backend.models.DB_Client import supabase
from backend.services.chat_services import createNewChat, createOldChat, generateChatTitle, streamNewChat, streamOldChat, generateMeetingTitle
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
def handleMeetingGeneration(request, audio_bytes, is_department_wide):
    try:
        online = isOnline()
        audio_transformation = DataTransformation()
        cleaned_audio = audio_transformation.preprocess_audio(audio_bytes=audio_bytes)
        
        if(cleaned_audio == None):
            raise HTTPException(status_code=400, detail="Please upload any meeting")
            
        dept_id = request.state.user['dept_id']
        team_id = request.state.user.get('team_id')

        # Run the full AI workflow synchronously (keeping all evaluation/optimization loops)
        meeting_obj = MeetingProcessor()
        meeting_report = meeting_obj.generateMeetingMinutes(target_dept=dept_id, cleaned_audio=cleaned_audio)
        
        # Generate the Meeting Title using the specific prompt
        meeting_title = generateMeetingTitle(prompt=getPrompts()[3], final_report=meeting_report)
        
        if online:
            response = (
                supabase.table("meetings")
                .insert({
                    "target_dept": dept_id, 
                    "team_id": team_id, 
                    "is_department_wide": is_department_wide, 
                    "final_report": meeting_report,
                    "meeting_title": meeting_title
                })
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=500, detail="Failed to create meeting")
            generated_id = response.data[0]['meeting_id']
        else:
            # For offline, we save the full report and title immediately
            from backend.utils.SQlite_utils import save_meeting_offline
            generated_id = save_meeting_offline(dept_id, team_id, is_department_wide, meeting_report, meeting_title)

        return JSONResponse(status_code=201, content={
            "message": "Meeting processed successfully", 
            "meeting_id": generated_id,
            "final_report": meeting_report,
            "meeting_title": meeting_title
        })

    except HTTPException:
        raise
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
                .insert({"chat_title": chat_title, "id": request.state.user['id'], "meeting_id": meeting['meeting_id']})
                .execute()
            )
            chat_id = resp.data[0]['chat_id']
        else:
            chat_id = insertChats(chat_title=chat_title, user_id=request.state.user['id'], meeting_id=meeting_id)

        import json
        def stream_with_title():
            # Send chat_title as first SSE event so frontend can update the sidebar
            yield f"data: {json.dumps({'chat_title': chat_title})}\n\n"
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
                .select("target_dept, team_id, is_department_wide, final_report")
                .eq("meeting_id", meeting_id)
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
            if meeting is None:
                raise HTTPException(status_code=404, detail="No offline meeting found")
            
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

def handleGettingOldChat(chat_id, request):
    try:
        online = isOnline()
        if online:
            response = (
                supabase.table("chats")
                .select("meeting_id", "chat_id")
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
                        
        if request.state.user['dept_id'] != target_dept or (team_id != request.state.user.get('team_id') and not is_department_wide):
            raise HTTPException(status_code=403, detail="You cannot access this chat")
        
        if online:
            chat = (
                supabase.table("messages")
                .select("message, type")
                .eq("chat_id", response.data[0]['chat_id'])
                .execute()
            )
            if not chat.data:
                raise HTTPException(status_code=404, detail="No chat found")
            
            chat_history = chat.data 
        else:
            chat_history = getMessages(chat_id=chat_id) or []
            
        # Get final report from the meeting data object (already fetched above)
        final_report = meeting.data[0]['final_report'] if online else target_dept_info['final_report']

        return JSONResponse(status_code=200, content={
            "message": "Old chat retrieved successfully", 
            "chat": chat_history,
            "final_report": final_report,
            "meeting_id": meeting_id
        })
    except Exception as e:
        raise CustomException(e, sys)

def handleGetAllChats(request):
    try:
        online = isOnline()
        user_id = request.state.user['id']
        
        if online:
            # Check for any pending offline data and sync it
            try:
                sync_offline_data_to_supabase()
            except Exception as sync_e:
                logging.warning(f"Background sync failed: {sync_e}")

            response = (
                supabase.table("chats")
                .select("chat_title, chat_id")
                .eq("id", user_id)
                .execute()
            )
            chats = response.data
        else:
            chats = getChatsByUserId(user_id=user_id)
            
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
            
            response = (
                supabase.table("meetings")
                .select("meeting_id, target_dept, meeting_title, final_report, team_id, is_department_wide")
                .eq("target_dept", dept_id)
                .execute()
            )
            
            # Use STR comparison to avoid type mismatches (int vs string)
            valid_meetings = []
            u_team_id = str(team_id) if team_id is not None else ""
            logging.info(f"🔍 DEBUG: Your Account -> Dept: {dept_id}, Team: {u_team_id}")
            
            for m in response.data:
                m_team_id = str(m.get('team_id')) if m.get('team_id') is not None else ""
                is_wide = m.get('is_department_wide')
                meeting_title = m.get('meeting_title')
                report = m.get('final_report')
                
                # Eligibility: Must have report content AND (be Dept-Wide OR match user Team) 
                # AND must NOT be a placeholder title like "Processing..."
                if report and report != "EMPTY" and report.strip() != "" and "Processing..." not in meeting_title:
                    if is_wide or m_team_id == u_team_id:
                        valid_meetings.append(m)
                        logging.info(f"✅ DEBUG: Meeting '{meeting_title}' APPROVED.")
                    else:
                        logging.info(f"❌ DEBUG: Meeting '{meeting_title}' REJECTED (Team mismatch).")
                else:
                    logging.info(f"❌ DEBUG: Meeting '{meeting_title}' REJECTED (Empty/In-progress report).")

            logging.info(f"✅ FINAL: Found {len(valid_meetings)} valid meetings.")
            return JSONResponse(status_code=200, content={"meetings": valid_meetings})
        else:
            # 4. Fetch the department meetings from the local SQLite DB if offline
            from backend.utils.SQlite_utils import getMeetingsByDept
            meetings = getMeetingsByDept(dept_id=dept_id)
            valid_meetings = []
            for m in meetings:
                report = m.get('final_report')
                m_team_id = str(m.get('team_id')) if m.get('team_id') is not None else ""
                u_team_id = str(team_id) if team_id is not None else ""
                
                if report and report != "EMPTY" and report.strip() != "":
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
