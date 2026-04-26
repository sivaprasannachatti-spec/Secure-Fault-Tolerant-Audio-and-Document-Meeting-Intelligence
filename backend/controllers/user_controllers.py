import sys
import datetime
import os

from src.exception import CustomException
from src.logger import logging
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from backend.models.DB_Client import supabase
from backend.services.user_services import insertData
from backend.utils.user_utils import createToken
from backend.utils.user_utils import isOnline

def handleSignupUser(user):
    try:
        if(user.name is None or user.email is None or user.dept is None or user.team_id is None):
            raise HTTPException(status_code=400, detail="Please provide valid details")
        online = isOnline()

        if online:
            response = (
                supabase.table("users")
                .select("email")
                .eq("email", user.email)
                .execute()
            )
            if response.data:
                raise HTTPException(status_code=409, detail="The user already exists")
            
            json_response = insertData(user=user)
            return JSONResponse(status_code=201, content={"message": "User inserted successfully", "data": json_response})
        
        else:
            raise HTTPException(status_code=503, detail="Service Unavailable: You must be connected to the internet.")
        
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

def handleLoginUser(user, request):
    try:
        if(user.email is None or user.dept is None):
            raise HTTPException(status_code=400, detail="Please enter valid details")
        online = isOnline()

        if online:
            response = (
                supabase.table("users")
                .select("id", "name", "email", "dept_id", "team_id")
                .eq("email", user.email)
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=404, detail="User not found. Please signup first")
            db_user = response.data[0]
            ## storing data in payload
            payload = {
                "id": db_user['id'],
                "email": db_user['email'],
                "dept_id": db_user['dept_id'],
                "team_id": db_user['team_id'],
                "exp": datetime.datetime.utcnow() + datetime.timedelta(days=36500)
            }
            token = createToken(payload=payload, key=os.environ['JWT_SECRET_KEY'], algorithm="HS256")
            json_response = JSONResponse(status_code=200, content={"message": "User logged in successfully", "name": db_user['name']})
            json_response.set_cookie(
                key='access_token',
                value=token,httponly=True,
                max_age=30 * 24 * 60 * 60,  # 30 days in seconds
                samesite="lax",
                path="/"
            )
            return json_response
        else:
            # Offline: Check if user already has a valid token cookie
            token = request.cookies.get("access_token")
            if token is None:
                # No token + offline = they MUST go online to log in first
                raise HTTPException(status_code=503, detail="Service Unavailable: You must be connected to the internet.")
            
            # Token exists! They are already authenticated, just let them through
            return JSONResponse(status_code=200, content={"message": "User logged in successfully"})
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)

def handleLogoutUser():
    try:
        # Logout only needs to clear the cookie — no Supabase call needed, works online AND offline!
        json_response = JSONResponse(status_code=200, content={"message": "User logged out successfully"})
        json_response.delete_cookie(key="access_token")
        return json_response
    except Exception as e:
        raise CustomException(e, sys)

def handleAccountDeletion(request):
    try:
        online = isOnline()
        
        if online:
            response = (
                supabase.table("users")
                .delete()
                .eq("email", request.state.user['email'])
                .execute()
                )
            json_response = JSONResponse(status_code=200, content={"message": "User account deleted successfully"})
            json_response.delete_cookie(key="access_token")
            return json_response
        
        else:
            raise HTTPException(status_code=503, detail="Service Unavailable: You must be connected to the internet.")
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)