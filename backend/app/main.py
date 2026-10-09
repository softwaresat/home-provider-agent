"""FastAPI entrypoint. Conversation logic lives in agent.py; this file is HTTP only."""

from __future__ import annotations

import json
import threading
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import agent, config, lead
from app.models import (
    ContactInfo,
    HealthResponse,
    LocationRequest,
    MessageRequest,
    SearchRequest,
    SelectRequest,
    SessionState,
    TurnResponse,
)

app = FastAPI(title="Home-services lead agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS: dict[str, SessionState] = {}
STORE_PATH = config.BACKEND_ROOT / "data" / "sessions.json"
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_STORE_LOCK = threading.Lock()


def _session_lock(session_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(session_id, threading.Lock())


def _load_sessions() -> None:
    if not STORE_PATH.exists():
        return
    try:
        payload = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    for session_id, raw in payload.items():
        try:
            SESSIONS[session_id] = SessionState.model_validate(raw)
        except Exception:  # noqa: BLE001
            continue


def _save_sessions() -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _STORE_LOCK:
        payload = {key: session.model_dump(mode="json") for key, session in SESSIONS.items()}
        STORE_PATH.write_text(json.dumps(payload), encoding="utf-8")


_load_sessions()


def _get_session(session_id: str) -> SessionState:
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session")
    return session


def _turn(session: SessionState) -> TurnResponse:
    assistant = ""
    for message in reversed(session.messages):
        if message.role == "assistant":
            assistant = message.content
            break
    _save_sessions()
    return TurnResponse(
        assistant_message=assistant,
        stage=session.stage,
        analysis=session.analysis,
        safety_advice=session.safety_advice,
        providers=session.providers,
        lead=session.lead,
        email=session.email,
        llm_fallback_used=session.llm_fallback_used,
        state=session,
    )


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        deepseek_configured=config.llm_configured(),
        google_places_configured=config.places_configured(),
        search_mode=config.search_mode(),
        model=config.active_model(),
    )


@app.post("/api/sessions", response_model=TurnResponse)
def create_session() -> TurnResponse:
    session_id = str(uuid.uuid4())
    session = agent.create_session(session_id)
    SESSIONS[session_id] = session
    return _turn(session)


@app.get("/api/sessions/{session_id}", response_model=SessionState)
def get_session(session_id: str) -> SessionState:
    with _session_lock(session_id):
        session = _get_session(session_id)
        if session.lead is not None:
            lead.apply_lead(session)
        else:
            lead.refresh_email(session)
        _save_sessions()
        return session


@app.post("/api/sessions/{session_id}/messages", response_model=TurnResponse)
def post_message(session_id: str, body: MessageRequest) -> TurnResponse:
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message text is required")
    with _session_lock(session_id):
        session = _get_session(session_id)
        agent.handle_user_message(session, text)
        return _turn(session)


@app.post("/api/sessions/{session_id}/location", response_model=TurnResponse)
def set_location(session_id: str, body: LocationRequest) -> TurnResponse:
    text = (body.location or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Location is required")
    with _session_lock(session_id):
        session = _get_session(session_id)
        agent.handle_location(session, text)
        return _turn(session)


@app.post("/api/sessions/{session_id}/providers/search", response_model=TurnResponse)
def search_providers(session_id: str, body: Optional[SearchRequest] = None) -> TurnResponse:
    with _session_lock(session_id):
        session = _get_session(session_id)
        payload = body or SearchRequest()
        agent.handle_search(session, category=payload.category, location=payload.location)
        return _turn(session)


@app.post("/api/sessions/{session_id}/select", response_model=TurnResponse)
def select_provider(session_id: str, body: SelectRequest) -> TurnResponse:
    with _session_lock(session_id):
        session = _get_session(session_id)
        try:
            agent.handle_select(session, body.place_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _turn(session)


@app.post("/api/sessions/{session_id}/contact", response_model=TurnResponse)
def submit_contact(session_id: str, body: ContactInfo) -> TurnResponse:
    if not (body.service_address or "").strip():
        raise HTTPException(status_code=400, detail="Service address is required")
    with _session_lock(session_id):
        session = _get_session(session_id)
        agent.handle_contact(session, body)
        return _turn(session)
