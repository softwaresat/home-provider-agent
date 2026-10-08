"""Load environment variables. Keys stay in backend/.env, never the frontend."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
DEFAULT_LOCATION = os.getenv("DEFAULT_LOCATION", "Austin, TX").strip() or "Austin, TX"


def deepseek_configured() -> bool:
    return bool(DEEPSEEK_API_KEY)


def places_configured() -> bool:
    return bool(GOOGLE_PLACES_API_KEY)


def search_mode() -> str:
    return "live" if places_configured() else "fallback"
