import os
import sys

# Ensure project root is in sys.path for Vercel Serverless environment
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Set VERCEL flag to ensure serverless optimizations are applied
os.environ["VERCEL"] = "1"

from src.web_server import app

# Vercel WSGI entrypoint
# Exposes 'app' for serverless Python execution
