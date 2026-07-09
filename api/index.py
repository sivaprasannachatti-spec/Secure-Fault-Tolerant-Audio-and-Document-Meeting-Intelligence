import os
import sys

# Ensure the project root is in the Python path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Import the FastAPI app from backend.app directly at the top-level
from backend.app import app
