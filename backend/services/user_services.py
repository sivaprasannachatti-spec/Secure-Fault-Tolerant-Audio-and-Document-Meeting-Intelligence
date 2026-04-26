import sys

from fastapi import HTTPException
from src.exception import CustomException
from src.logger import logging
from backend.models.DB_Client import supabase

def insertData(user):
    try:
        response = (
            supabase.table("users")
            .insert({
                "name": user.name,
                "email": user.email,
                "dept_id": user.dept,
                "team_id": user.team_id
                })
            .execute()
        )
        return response.data
    except Exception as e:
        raise CustomException(e, sys)