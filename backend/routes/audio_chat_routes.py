import sys

from fastapi import APIRouter, Request, Response, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Annotated
from src.exception import CustomException
from src.logger import logging
from backend.middlewares.auth_middleware import verifyJWT
from backend.controllers.audio_chat_controllers import handleNewChat, handleOldChat, handleGettingOldChat, handleGetAllChats, handleMeetingGeneration, handleGetAllMeetings, handleGetMeetingContent

chat_router = APIRouter()

from typing import Annotated, Optional

class NewChat(BaseModel):
    query: Annotated[str, Field(description="The query of the user")]
    meeting_id: Annotated[Optional[int], Field(description="The id of the meeting")] = None
    
class Chat(BaseModel):
    query: Annotated[str, Field(description="The query of the user")]

@chat_router.post("/fileUpload", dependencies=[Depends(verifyJWT)])
def fileUpload(
    request: Request,
    file: UploadFile = File(...),
    is_department_wide: bool = Form(False)
):
    try:
        # Strict validation: Only audio files allowed in this workspace
        if not file.content_type.startswith("audio/"):
            # Check if it's a document being uploaded in the wrong workspace
            doc_exts = {'.pdf', '.docx', '.txt', '.md'}
            import os
            _, ext = os.path.splitext(file.filename)
            if ext.lower() in doc_exts:
                raise HTTPException(
                    status_code=400, 
                    detail="Documents cannot be uploaded in the Audio workspace. Please use the 'Meeting Notes' workspace."
                )
            raise HTTPException(status_code=400, detail="Only audio files (MP3, WAV, M4A) are allowed in this workspace.")
        audio_bytes = file.file.read()
        return handleMeetingGeneration(request=request, audio_bytes=audio_bytes, is_department_wide=is_department_wide)
    except Exception as e:
        raise CustomException(e, sys)

@chat_router.post("/newChat", dependencies=[Depends(verifyJWT)])
def newChat(msg: NewChat, request: Request):
    try:
        return handleNewChat(msg=msg, request=request)
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

@chat_router.post("/oldChat/{chat_id}", dependencies=[Depends(verifyJWT)])
def oldChat(chat_id: int, msg: Chat, request: Request):
    try:
        return handleOldChat(chat_id=chat_id, msg=msg, request=request)
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

@chat_router.get("/getOldChat/{chat_id}", dependencies=[Depends(verifyJWT)])
def getOldChat(chat_id: int, request: Request):
    try:
        return handleGettingOldChat(chat_id=chat_id, request=request)
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

@chat_router.get("/getChats", dependencies=[Depends(verifyJWT)])
def getChats(request: Request):
    try:
        return handleGetAllChats(request=request)
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

@chat_router.post("/sync", dependencies=[Depends(verifyJWT)])
def sync_data():
    try:
        from backend.utils.SQlite_utils import sync_offline_data_to_supabase
        sync_offline_data_to_supabase()
        return {"message": "All offline data has been synced to the cloud!"}
    except Exception as e:
        raise CustomException(e, sys)

@chat_router.get("/getAllMeetings", dependencies=[Depends(verifyJWT)])
def getAllMeetings(request: Request):
    try:
        return handleGetAllMeetings(request=request)
    except Exception as e:
        raise CustomException(e, sys)

@chat_router.get("/getMeetingContent/{meeting_id}", dependencies=[Depends(verifyJWT)])
def getMeetingContent(request: Request, meeting_id: int):
    try:
        return handleGetMeetingContent(request=request, meeting_id=meeting_id)
    except Exception as e:
        raise CustomException(e, sys)