"""
config.py — загрузка настроек из .env файла
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ищем .env рядом с exe или рядом со скриптом
if getattr(sys, 'frozen', False):
    # Running as bundled exe
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    # Running as script
    BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# Google Sheets
SPREADSHEET_ID: str = get("SPREADSHEET_ID")          # ID таблицы из URL
SHEET_MASTER_CV: str = get("SHEET_MASTER_CV", "Master CV")
SHEET_TRACKER: str = get("SHEET_TRACKER", "Tracker")
COL_DESCRIPTION: str = get("COL_DESCRIPTION", "Description")
COL_ADAPTED_CV: str = get("COL_ADAPTED_CV", "Adapted CV")

# OAuth
CLIENT_SECRET_FILE: str = get("CLIENT_SECRET_FILE", "client_secret.json")
TOKEN_FILE: str = get("TOKEN_FILE", "token.json")

# LLM
LLM_PROVIDER: str = get("LLM_PROVIDER", "gemini")   # gemini | openai | groq
GEMINI_API_KEY: str = get("GEMINI_API_KEY")
GEMINI_MODEL: str = get("GEMINI_MODEL", "gemini-1.5-flash")
OPENAI_API_KEY: str = get("OPENAI_API_KEY")
OPENAI_MODEL: str = get("OPENAI_MODEL", "gpt-4o-mini")
GROQ_API_KEY: str = get("GROQ_API_KEY")
GROQ_MODEL: str = get("GROQ_MODEL", "llama3-8b-8192")
