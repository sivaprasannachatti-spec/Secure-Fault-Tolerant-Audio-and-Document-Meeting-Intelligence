import logging
import os
import sys
from datetime import datetime

LOG_FILE = f"{datetime.now().strftime('%m_%d_%Y_%H_%M_%S')}.log"

if os.environ.get('VERCEL'):
    # Vercel has a read-only filesystem (except /tmp). 
    # Just output logs to console so they show up in Vercel Logs.
    logging.basicConfig(
        stream=sys.stdout,
        format="[ %(asctime)s ] %(lineno)d %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
else:
    # Local environment: save logs to a file
    logs_path = os.path.join(os.getcwd(), "logs", LOG_FILE)
    os.makedirs(logs_path, exist_ok=True)
    
    LOG_FILE_PATH = os.path.join(logs_path, LOG_FILE)
    
    logging.basicConfig(
        filename=LOG_FILE_PATH,
        format="[ %(asctime)s ] %(lineno)d %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )