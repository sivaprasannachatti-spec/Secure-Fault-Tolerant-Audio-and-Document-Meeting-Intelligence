import sys
import jwt
import socket

from src.exception import CustomException
from src.logger import logging

def createToken(payload, key, algorithm):
    try:
        token = jwt.encode(payload, key, algorithm=algorithm)
        return token
    except Exception as e:
        raise CustomException(e, sys)

def isOnline(host="8.8.8.8", port=53, timeout=2):
    try:
        # Set a very short timeout so the app doesn't freeze for 
        # a long time if the internet is down.
        socket.setdefaulttimeout(timeout)
        
        # Create a tiny socket connection
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # Try to connect. If this fails, it throws a socket.error
        s.connect((host, port))
        
        # Close it immediately to save resources
        s.close()
        
        return True # We touched the internet!
    except socket.error:
        # If it timed out or threw an error, we have no internet
        return False

    except Exception as e:
        raise CustomException(e, sys)
