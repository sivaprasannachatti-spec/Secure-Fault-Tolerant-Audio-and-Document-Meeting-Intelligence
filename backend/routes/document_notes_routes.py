"""
Document Notes Routes — FastAPI routes for the document workflow.

Completely separate from audio_chat_routes.py.
Mounted at /api/documents in app.py.
"""

import sys
import os

from fastapi import APIRouter, Request, Response, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import Annotated, Optional
from src.exception import CustomException
from src.logger import logging
from backend.middlewares.auth_middleware import verifyJWT
from backend.controllers.document_notes_controllers import (
    handleDocumentGeneration, handleDocumentNewChat,
    handleDocumentOldChat, handleDocumentGetOldChat,
    handleGetAllDocuments, handleGetAllDocumentChats,
    handleGetDocumentContent
)

document_notes_router = APIRouter()

# --- File Validation Constants ---
ALLOWED_DOCUMENT_EXTENSIONS = {'.pdf', '.docx', '.txt', '.md'}
ALLOWED_DOCUMENT_MIMES = {
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain',
    'text/markdown',
    'application/octet-stream',  # Some browsers send this for .md files
}


class DocumentNewChat(BaseModel):
    query: Annotated[str, Field(description="The query of the user")]
    meeting_id: Annotated[Optional[int], Field(description="The id of the meeting")] = None

class DocumentChat(BaseModel):
    query: Annotated[str, Field(description="The query of the user")]

import uuid
from backend.models.DB_Client import supabase

class DocumentUploadRequest(BaseModel):
    file_path: str
    is_department_wide: bool


def _get_file_extension(filename: str) -> str:
    """Extracts and validates the file extension."""
    _, ext = os.path.splitext(filename)
    return ext.lower()


@document_notes_router.get("/getUploadUrl", dependencies=[Depends(verifyJWT)])
def getUploadUrl(filename: str):
    try:
        path = f"documents/{uuid.uuid4()}-{filename}"
        res = supabase.storage.from_("workspace-files").create_signed_upload_url(path)
        return {"signed_url": res.get('signedUrl', res.get('signed_url')), "path": path}
    except Exception as e:
        raise CustomException(e, sys)


@document_notes_router.post("/fileUpload", dependencies=[Depends(verifyJWT)])
def fileUpload(
    request: Request,
    body: DocumentUploadRequest
):
    try:
        return handleDocumentGeneration(request=request, file_path=body.file_path, is_department_wide=body.is_department_wide)
    except Exception as e:
        raise CustomException(e, sys)


@document_notes_router.post("/upload", dependencies=[Depends(verifyJWT)])
def documentUpload(
    request: Request,
    body: DocumentUploadRequest
):
    """
    Accepts document file paths from Supabase and initiates the 
    Vectorless RAG pipeline. Returns an SSE stream.
    """
    try:
        logging.info(f"📄 Document upload received from Supabase: {body.file_path}")
        
        return handleDocumentGeneration(
            request=request,
            file_path=body.file_path,
            is_department_wide=body.is_department_wide
        )
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)


@document_notes_router.post("/chat/new", dependencies=[Depends(verifyJWT)])
def documentNewChat(msg: DocumentNewChat, request: Request):
    """Creates a new chat session for a document-based meeting."""
    try:
        return handleDocumentNewChat(msg=msg, request=request)
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)


@document_notes_router.post("/chat/{chat_id}", dependencies=[Depends(verifyJWT)])
def documentOldChat(chat_id: int, msg: DocumentChat, request: Request):
    """Continues an existing chat session for a document-based meeting."""
    try:
        return handleDocumentOldChat(chat_id=chat_id, msg=msg, request=request)
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)


@document_notes_router.get("/getMeetingContent/{meeting_id}", dependencies=[Depends(verifyJWT)])
def getDocumentContent(request: Request, meeting_id: int):
    """Retrieves specific document meeting content."""
    try:
        return handleGetDocumentContent(request=request, meeting_id=meeting_id)
    except Exception as e:
        raise CustomException(e, sys)


@document_notes_router.get("/chat/{chat_id}", dependencies=[Depends(verifyJWT)])
def documentGetOldChat(chat_id: int, request: Request, limit: Optional[int] = None, before_id: Optional[int] = None):
    """Retrieves old chat messages for a document-based meeting."""
    try:
        return handleDocumentGetOldChat(chat_id=chat_id, request=request, limit=limit, before_id=before_id)
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

@document_notes_router.get("/getOldChat/{chat_id}", dependencies=[Depends(verifyJWT)])
def documentGetOldChatAlias(chat_id: int, request: Request, limit: Optional[int] = None, before_id: Optional[int] = None):
    """Alias for /chat/{chat_id} — matches the frontend's shared URL pattern."""
    try:
        return handleDocumentGetOldChat(chat_id=chat_id, request=request, limit=limit, before_id=before_id)
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

@document_notes_router.get("/getAllMeetings", dependencies=[Depends(verifyJWT)])
def getAllDocuments(request: Request):
    """Retrieves only document-type meetings for the sidebar."""
    try:
        return handleGetAllDocuments(request=request)
    except Exception as e:
        raise CustomException(e, sys)


@document_notes_router.get("/getChats", dependencies=[Depends(verifyJWT)])
def getAllDocumentChats(request: Request):
    """Retrieves only document-related chat history for the sidebar."""
    try:
        return handleGetAllDocumentChats(request=request)
    except Exception as e:
        raise CustomException(e, sys)
