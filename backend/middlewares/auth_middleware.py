import sys
import os
import jwt

from src.exception import CustomException
from src.logger import logging
from fastapi import HTTPException
from backend.models.DB_Client import supabase
from fastapi import Request
from backend.utils.user_utils import isOnline
from backend.models.SQlite_db import get_user_from_sqlite

async def verifyJWT(request: Request):
    try:
        token = request.cookies.get("access_token")
        online = isOnline()
        if not token:
            raise HTTPException(status_code=401, detail="Token not found. Please login first")
        
        try:
            decodedToken = jwt.decode(token, os.environ['JWT_SECRET_KEY'], algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Session expired. Please login again.")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid session. Please login again.")
        if online:
            # We have internet: Query Supabase
            response = (
                supabase.table("users")
                .select("id", "name", "email", "dept_id", "team_id")
                .eq("email", decodedToken['email'])
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=404, detail="User not found. Please signup first")
            
            user_data = response.data[0]
        else:
            user_data = get_user_from_sqlite(decodedToken['email'])
            
            if not user_data:
                raise HTTPException(status_code=404, detail="Offline user not found. Please connect to internet to login.")
        request.state.user = user_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise CustomException(e, sys)