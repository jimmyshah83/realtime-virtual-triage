from typing import Optional, Literal
from datetime import datetime
from dataclasses import dataclass, field
from pydantic import BaseModel, Field


# Session State Models
@dataclass
class IntakeSessionState:
    """In-memory state for an active intake session"""

    session_id: str
    user_language: str
    start_time: datetime
    transcript_chunks: list[str] = field(default_factory=list)
    final_transcript: str = ""
    extracted_symptoms: Optional[dict] = None
    status: Literal["active", "completed", "timeout", "error"] = "active"
    error_message: Optional[str] = None


# API Request/Response Models
class CreateSessionRequest(BaseModel):
    """Request to create a new intake session"""

    user_language: str = Field(
        default="en",
        description="Language code (e.g., 'en', 'es', 'fr', 'zh', 'ar')"
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Optional user identifier for tracking"
    )


class CreateSessionResponse(BaseModel):
    """Response after creating a session"""

    session_id: str
    ice_servers: list[dict] = Field(
        default_factory=lambda: [
            {"urls": ["stun:stun.l.google.com:19302"]},
            {"urls": ["stun:stun1.l.google.com:19302"]},
        ]
    )


class WebRTCOfferRequest(BaseModel):
    """WebRTC SDP offer from frontend"""

    sdp: str


class WebRTCAnswerResponse(BaseModel):
    """WebRTC SDP answer from backend"""

    sdp: str


class ICECandidateRequest(BaseModel):
    """ICE candidate from frontend"""

    candidate: str
    sdp_mid: Optional[str] = None
    sdp_mline_index: Optional[int] = None


class SymptomPayload(BaseModel):
    """Structured symptom data extracted by intake agent"""

    session_id: str
    user_id: Optional[str] = None
    language: str
    transcript: str
    extracted_symptoms: dict = Field(
        default_factory=dict,
        description="Chief complaint, duration, severity, associated symptoms, etc."
    )
    confidence_scores: dict = Field(
        default_factory=dict,
        description="Confidence for each extracted symptom field"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TranscriptChunkEvent(BaseModel):
    """Real-time transcript chunk from GPT-4o Realtime"""

    session_id: str
    chunk: str
    is_final: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class StatusUpdateEvent(BaseModel):
    """Status update during intake conversation"""

    session_id: str
    status: Literal["active", "completed", "timeout", "error"]
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SymptomsCompleteEvent(BaseModel):
    """Event emitted when symptom extraction is complete"""

    session_id: str
    symptom_payload: SymptomPayload
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ErrorEvent(BaseModel):
    """Error event during intake"""

    session_id: str
    error_code: str
    error_message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
