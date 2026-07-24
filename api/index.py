import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import app  # DATABASE_URL and ADMIN_KEY come from Vercel env vars
