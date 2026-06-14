"""Shared paths and API settings for visual_server."""
import os

API_KEY = os.environ.get("SINLEX_API_KEY", "")
ACCOUNTS_FILE = "/opt/sinlex/accounts.json"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_ROOT = os.path.join(BASE_DIR, "projects")
CASTING_ROOT = os.path.join(BASE_DIR, "casting")
CDW_DRAWINGS_ROOT = os.path.join(BASE_DIR, "drawings")

os.makedirs(PROJECTS_ROOT, exist_ok=True)
os.makedirs(CASTING_ROOT, exist_ok=True)
os.makedirs(CDW_DRAWINGS_ROOT, exist_ok=True)
