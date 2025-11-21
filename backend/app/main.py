"""Main FastAPI application entry point."""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4
import threading

from app.agents import (
    triage_graph,
    TriageAgentState,
    PatientInfo,
    MedicalCodes,
    PhysicianInfo,
)

import httpx
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage

# Add backend directory to Python path for imports when running as script
_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

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

# Token caching variables for DefaultAzureCredential
cached_token: Optional[str] = None
token_expiry: float = 0
token_lock = threading.Lock()


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
        "referral_required": False,
        "recommended_setting": "",
        "guidance_summary": "",
        "next_steps": [],
        "selected_physician": None,
        "clarifying_question": "",
        "clarification_attempts": 0,
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


def get_bearer_token(resource_scope: str) -> str:
    """Get a bearer token using DefaultAzureCredential with caching."""
    global cached_token, token_expiry
    
    current_time = time.time()
    
    # Check if we have a valid cached token (with 5 minute buffer before expiry)
    with token_lock:
        if cached_token and current_time < (token_expiry - 300):
            return cached_token
    
    # Get a new token
    try:
        credential = DefaultAzureCredential()
        token = credential.get_token(resource_scope)
        
        with token_lock:
            cached_token = token.token
            token_expiry = token.expires_on
            
        logger.info("Acquired new bearer token, expires at: %s", time.ctime(token_expiry))
        return cached_token
        
    except Exception as e:
        logger.error("Failed to acquire bearer token: %s", e)
        raise


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
    referral_required: bool = False
    symptoms: list[str] = []
    chief_complaint: Optional[str] = None
    assessment: Optional[str] = None
    medical_codes: Optional[MedicalCodes] = None
    patient_info: Optional[PatientInfo] = None
    recommended_setting: Optional[str] = None
    guidance_summary: Optional[str] = None
    next_steps: list[str] = []
    physician: Optional[PhysicianInfo] = None
    clarifying_question: Optional[str] = None


class ClientSecret(BaseModel):
    """Ephemeral key payload returned by Azure OpenAI."""

    value: str
    expires_at: Optional[int] = None


class SessionResponse(BaseModel):
    """Response body for Azure Realtime session creation."""

    session_id: str
    client_secret: ClientSecret
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
        deployment = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]
        voice = os.getenv("AZURE_OPENAI_REALTIME_VOICE", "alloy") or "alloy"
        session_type = os.getenv("AZURE_OPENAI_SESSION_TYPE", "realtime") or "realtime"
        session_instructions = os.getenv("AZURE_OPENAI_SESSION_INSTRUCTIONS", "You are a helpful assistant.")

        # Get Azure resource name - use AZURE_RESOURCE if provided, otherwise extract from endpoint
        azure_resource = os.getenv("AZURE_RESOURCE")
        if not azure_resource:
            # Extract resource name from AZURE_OPENAI_ENDPOINT
            endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
            # Endpoint format: https://{resource}.openai.azure.com
            if endpoint:
                # Remove protocol and path
                resource_part = endpoint.replace("https://", "").replace("http://", "").split("/")[0]
                # Extract resource name (everything before .openai.azure.com)
                if ".openai.azure.com" in resource_part:
                    azure_resource = resource_part.split(".openai.azure.com")[0]
                else:
                    # Fallback: use the whole hostname
                    azure_resource = resource_part.split(".")[0]
            else:
                raise ValueError("Either AZURE_RESOURCE or AZURE_OPENAI_ENDPOINT must be set")

        # Get bearer token using DefaultAzureCredential
        bearer_token = get_bearer_token("https://cognitiveservices.azure.com/.default")

        # Construct the Azure OpenAI endpoint URL
        session_url = f"https://{azure_resource}.openai.azure.com/openai/v1/realtime/client_secrets"
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

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                session_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {bearer_token}",
                    "Content-Type": "application/json"
                }
            )

            if response.status_code != 200:
                logger.error("Request failed with status %s", response.status_code)
                logger.error("Response headers: %s", dict(response.headers))
                logger.error("Response content: %s", response.text)
                raise HTTPException(
                    status_code=response.status_code,
                    detail={
                        "error": "Failed to create session",
                        "azure_status": response.status_code,
                        "body": response.text,
                    },
                )

            session_payload = response.json()
            client_secret_payload = session_payload.get("client_secret") or {}
            secret_value = client_secret_payload.get("value") or session_payload.get("value")

            if not secret_value:
                logger.error("Azure response missing client secret: %s", session_payload)
                raise HTTPException(status_code=500, detail="Azure response missing client secret")

            session_id = (
                session_payload.get("session_id")
                or session_payload.get("id")
                or session_payload.get("session", {}).get("id")
            )

            if not session_id:
                logger.warning("Azure response missing session id, generating fallback id")
                session_id = str(uuid4())

            sessions.setdefault(session_id, _default_session_state())
            _touch_session(session_id)

            return SessionResponse(
                session_id=session_id,
                client_secret=ClientSecret(
                    value=secret_value,
                    expires_at=client_secret_payload.get("expires_at"),
                ),
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
    logger.info(
        "Chat request received | session=%s | text=%s",
        session_id,
        chat_request.message.strip()[:200] if chat_request.message else "",
    )

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
        
        referral_required = result.get("referral_required", False)
        clarifying_question = result.get("clarifying_question")
        if current_agent == "triage":
            if result.get("handoff_ready"):
                response_text = "Thanks for the detailed information. I'm locking in your assessment and moving it to our clinical guidance specialist."
            else:
                question = clarifying_question or "Can you tell me a bit more about your symptoms?"
                response_text = f"I want to understand your situation clearly. {question}"
        elif current_agent == "clinical_guidance":
            summary = result.get("guidance_summary") or "Here's what I recommend."
            response_text = f"🩺 Clinical Guidance\n\n{summary}\n"
            if referral_required:
                response_text += "\nI'll coordinate a referral and share the provider details shortly."
            else:
                next_steps = result.get("next_steps") or []
                if next_steps:
                    response_text += "\nNext steps:\n" + "\n".join(f"• {step}" for step in next_steps)
                else:
                    response_text += "\nNo referral is required right now. Please continue monitoring your symptoms."
        elif current_agent == "referral_builder":
            referral = result.get("referral_package")
            physician = result.get("selected_physician")
            lines = ["✅ Referral package completed!", ""]
            if referral:
                lines.append(f"Disposition: {referral.disposition}")
                lines.append(f"Urgency: {referral.urgency_score}/5")
                if referral.red_flags:
                    lines.append(f"⚠️ Red Flags: {', '.join(referral.red_flags)}")
                lines.append("")
                lines.append(referral.referral_notes)
            if physician:
                lines.append("")
                lines.append(
                    "Assigned Physician: "
                    f"{physician.name} ({physician.specialty}) – {physician.location}"
                )
                if physician.contact_phone:
                    lines.append(f"Phone: {physician.contact_phone}")
                if physician.contact_email:
                    lines.append(f"Email: {physician.contact_email}")
            summary = result.get("guidance_summary")
            if summary:
                lines.append("")
                lines.append(f"Guidance: {summary}")
            next_steps = result.get("next_steps") or []
            if next_steps:
                lines.append("Suggested preparation:")
                lines.extend(f"• {step}" for step in next_steps)
            response_text = "\n".join(lines)
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
            referral_required=referral_required,
            symptoms=result.get("symptoms", []),
            chief_complaint=result.get("chief_complaint"),
            assessment=result.get("assessment"),
            medical_codes=result.get("medical_codes"),
            patient_info=result.get("patient_info"),
            recommended_setting=result.get("recommended_setting"),
            guidance_summary=result.get("guidance_summary"),
            next_steps=result.get("next_steps", []),
            physician=result.get("selected_physician"),
            clarifying_question=clarifying_question,
        )
        
    except Exception as e:
        logger.exception("Chat processing failed for session %s", session_id)
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
        "referral_required": state.get("referral_required", False),
        "recommended_setting": state.get("recommended_setting"),
        "guidance_summary": state.get("guidance_summary"),
        "next_steps": state.get("next_steps", []),
        "physician": state.get("selected_physician"),
        "last_active": session_activity.get(session_id),
    }