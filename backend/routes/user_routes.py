import sys

from fastapi import APIRouter, Request, Response, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Annotated, List
from src.exception import CustomException
from src.logger import logging
from backend.controllers.user_controllers import handleSignupUser, handleLoginUser, handleLogoutUser, handleAccountDeletion
from backend.middlewares.auth_middleware import verifyJWT

user_router = APIRouter()

class Signup(BaseModel):
    name: Annotated[str, Field(description="The name of the user")]
    email: Annotated[str, Field(description="The email of the user")]
    dept: Annotated[int, Field(description="The department id of the user")]
    team_id: Annotated[int, Field(description="The team id of the user")]

class Login(BaseModel):
    email: Annotated[str, Field(description="The email of the user")]
    dept: Annotated[int, Field(description="The department id of the user")]

class Logout(BaseModel):
    email: Annotated[str, Field(description="The email of the user")]

@user_router.get("/me", dependencies=[Depends(verifyJWT)])
def getMe(request: Request):
    return request.state.user

@user_router.post("/signup")
def signup(user: Signup):
    try:
        return handleSignupUser(user=user)
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)
    
@user_router.post("/login")
def login(user: Login, request: Request):
    try:
        return handleLoginUser(user=user, request=request)
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)
    
@user_router.delete("/logout", dependencies=[Depends(verifyJWT)])
def logout():
    try:
        return handleLogoutUser()
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)
    
@user_router.delete("/delete_account", dependencies=[Depends(verifyJWT)])
def deleteAccount(request: Request):
    try:
        return handleAccountDeletion(request=request)
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)