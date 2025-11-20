"""Main FastAPI application entry point."""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Add backend directory to Python path for imports when running as script
_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage

from app.agents import triage_graph, TriageAgentState, PatientInfo, MedicalCodes

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Real-time Virtual Triage",
    description="Real-time virtual triage backend API",
    version="0.1.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session management (use Redis/DB for production)
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "1800"))
sessions: Dict[str, TriageAgentState] = {}
session_activity: Dict[str, float] = {}


def _default_session_state() -> TriageAgentState:
    return {
        "messages": [],
        "symptoms": [],
        "patient_info": PatientInfo(),
        "urgency_score": 0,
        "red_flags": [],
        "medical_codes": MedicalCodes(),
        "referral_package": None,
        "current_agent": "triage",
        "handoff_ready": False,
        "chief_complaint": "",
        "assessment": "",
    }


def _touch_session(session_id: str) -> None:
    session_activity[session_id] = time.time()


def _purge_expired_sessions() -> None:
    if not session_activity:
        return
    now = time.time()
    expired = [sid for sid, last_active in session_activity.items() if now - last_active > SESSION_TTL_SECONDS]
    for sid in expired:
        sessions.pop(sid, None)
        session_activity.pop(sid, None)
        logger.info("Purged inactive session %s", sid)

# Request/Response models
class PatientInfoUpdate(BaseModel):
    """Partial patient info update payload."""

    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    contact: Optional[str] = None
    medical_history: Optional[list[str]] = None
    medications: Optional[list[str]] = None
    allergies: Optional[list[str]] = None


class ChatRequest(BaseModel):
    """Chat request model."""
    message: str
    transcript_id: Optional[str] = None
    latency_ms: Optional[int] = None
    patient_info: Optional[PatientInfoUpdate] = None


class ChatResponse(BaseModel):
    """Chat response model."""
    current_agent: str
    response: str
    urgency: int = 0
    red_flags: list[str] = []
    handoff_ready: bool = False
    referral_complete: bool = False
    symptoms: list[str] = []
    chief_complaint: Optional[str] = None
    assessment: Optional[str] = None
    medical_codes: Optional[MedicalCodes] = None
    patient_info: Optional[PatientInfo] = None


class SessionResponse(BaseModel):
    """Response body for Azure Realtime session creation."""

    session_id: str
    client_secret: Dict[str, Any]
    model: str
    voice: str
    session_ttl_seconds: int


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Real-time Virtual Triage API"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/session", response_model=SessionResponse)
async def create_session() -> SessionResponse:
    """Generate an ephemeral key for Azure OpenAI Realtime session."""
    try:
        api_key = os.environ["AZURE_OPENAI_API_KEY"]
        deployment = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]
        voice = os.getenv("AZURE_OPENAI_REALTIME_VOICE", "alloy") or "alloy"
        session_type = os.getenv("AZURE_OPENAI_SESSION_TYPE", "realtime") or "realtime"
        session_instructions = os.getenv("AZURE_OPENAI_SESSION_INSTRUCTIONS", "You are a helpful assistant.")

        session_url = f"{os.environ['AZURE_OPENAI_ENDPOINT'].rstrip('/')}/openai/v1/realtime/client_secrets"
        logger.info("Creating Azure Realtime session at %s", session_url)
        logger.debug("Realtime session payload: model=%s voice=%s session_type=%s", deployment, voice, session_type)

        payload = {
            "session": {
                "type": session_type,
                "model": deployment,
                "instructions": session_instructions,
                "audio": {
                    "output": {
                        "voice": voice,
                    }
                },
            },
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                session_url,
                json=payload,
                headers={
                    "api-key": api_key,
                    "Content-Type": "application/json"
                }
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail={
                        "error": "Failed to create session",
                        "azure_status": response.status_code,
                        "body": response.text,
                    },
                )

            session_payload = response.json()
            session_id = session_payload.get("id")
            client_secret = session_payload.get("client_secret")

            if not session_id or not client_secret:
                raise HTTPException(status_code=500, detail="Azure response missing session id or client secret")

            sessions.setdefault(session_id, _default_session_state())
            _touch_session(session_id)

            return SessionResponse(
                session_id=session_id,
                client_secret=client_secret,
                model=session_payload.get("model", deployment),
                voice=session_payload.get("voice", "alloy"),
                session_ttl_seconds=SESSION_TTL_SECONDS,
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error creating session")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc


@app.post("/chat/{session_id}")
async def chat(session_id: str, chat_request: ChatRequest) -> ChatResponse:
    """Process chat message through the triage agent workflow.
    
    Args:
        session_id: Unique session identifier
        chat_request: Chat message from user
        
    Returns:
        ChatResponse with agent response and current state
    """
    _purge_expired_sessions()

    # Initialize or retrieve session state
    if session_id not in sessions:
        logger.info("Initializing new session state for %s", session_id)
        sessions[session_id] = _default_session_state()

    state = sessions[session_id]
    _touch_session(session_id)

    # Merge patient info updates if provided
    if chat_request.patient_info:
        existing_info = state.get("patient_info", PatientInfo())
        updates = chat_request.patient_info.model_dump(exclude_none=True)
        state["patient_info"] = existing_info.model_copy(update=updates)
    
    # Add user message to conversation history
    state["messages"].append(HumanMessage(content=chat_request.message))
    
    try:
        # Invoke the agent graph
        result: Any = triage_graph.invoke(state)
        
        # Update session state
        sessions[session_id] = result
        
        # Build response message
        current_agent = result.get("current_agent", "triage")
        
        if current_agent == "triage":
            if result.get("handoff_ready"):
                response_text = "Thank you. I've completed the triage assessment.\n\n"
                response_text += f"Urgency Level: {result.get('urgency_score', 0)}/5\n"
                if result.get("red_flags"):
                    response_text += f"⚠️ Red Flags: {', '.join(result['red_flags'])}\n"
                response_text += "\nI'm now preparing your referral package..."
            else:
                response_text = "I'm gathering your information. "
                if result.get("symptoms"):
                    response_text += f"So far, you've mentioned: {', '.join(result['symptoms'])}. "
                response_text += "Can you tell me more about when these symptoms started and their severity?"
        
        elif current_agent == "referral_builder":
            referral = result.get("referral_package")
            if referral:
                response_text = "✅ Referral package completed!\n\n"
                response_text += f"Disposition: {referral.disposition}\n"
                response_text += f"Urgency: {referral.urgency_score}/5\n"
                if referral.red_flags:
                    response_text += f"⚠️ Red Flags: {', '.join(referral.red_flags)}\n"
                response_text += f"\n{referral.referral_notes}"
            else:
                response_text = "Building your referral package..."
        else:
            response_text = "Processing your request..."
        
        # Add AI response to conversation history
        result["messages"].append(AIMessage(content=response_text))
        sessions[session_id] = result  # type: ignore[typeddict-item]
        
        return ChatResponse(
            current_agent=current_agent,
            response=response_text,
            urgency=result.get("urgency_score", 0),
            red_flags=result.get("red_flags", []),
            handoff_ready=result.get("handoff_ready", False),
            referral_complete=result.get("referral_package") is not None,
            symptoms=result.get("symptoms", []),
            chief_complaint=result.get("chief_complaint"),
            assessment=result.get("assessment"),
            medical_codes=result.get("medical_codes"),
            patient_info=result.get("patient_info"),
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}") from e


@app.delete("/chat/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session."""
    if session_id in sessions:
        del sessions[session_id]
        session_activity.pop(session_id, None)
        return {"message": "Session deleted"}
    raise HTTPException(status_code=404, detail="Session not found")


@app.get("/chat/{session_id}")
async def get_session(session_id: str):
    """Get current session state."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    state = sessions[session_id]
    return {
        "session_id": session_id,
        "current_agent": state.get("current_agent", "triage"),
        "urgency_score": state.get("urgency_score", 0),
        "symptoms": state.get("symptoms", []),
        "red_flags": state.get("red_flags", []),
        "handoff_ready": state.get("handoff_ready", False),
        "referral_complete": state.get("referral_package") is not None,
        "patient_info": state.get("patient_info"),
        "medical_codes": state.get("medical_codes"),
        "last_active": session_activity.get(session_id),
    }