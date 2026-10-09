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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/",
).strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
DEFAULT_LOCATION = os.getenv("DEFAULT_LOCATION", "Austin, TX").strip() or "Austin, TX"


def gemini_configured() -> bool:
    return bool(GEMINI_API_KEY)


def deepseek_configured() -> bool:
    return bool(DEEPSEEK_API_KEY)


def llm_configured() -> bool:
    return gemini_configured() or deepseek_configured()


def active_llm() -> tuple[str, str, str] | None:
    """(api_key, base_url, model). Gemini wins when its key is set."""
    if gemini_configured():
        return GEMINI_API_KEY, GEMINI_BASE_URL, GEMINI_MODEL
    if deepseek_configured():
        return DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
    return None


def active_model() -> str:
    chosen = active_llm()
    if chosen is None:
        return GEMINI_MODEL
    return chosen[2]


def places_configured() -> bool:
    return bool(GOOGLE_PLACES_API_KEY)


def search_mode() -> str:
    return "live" if places_configured() else "fallback"
