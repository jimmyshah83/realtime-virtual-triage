"""WebRTC signaling endpoints for intake sessions"""

import logging
from fastapi import APIRouter, HTTPException, WebSocketException
from fastapi.websockets import WebSocket

from app.models import (
    CreateSessionRequest,
    CreateSessionResponse,
    WebRTCOfferRequest,
    WebRTCAnswerResponse,
    ICECandidateRequest,
    TranscriptChunkEvent,
)
from app.session_store import session_store
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/intake", tags=["intake"])


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest):
    """
    Create a new intake session.

    Returns session ID and WebRTC server configuration (STUN/TURN servers).
    """
    try:
        session = await session_store.create_session(
            user_language=request.user_language,
            user_id=request.user_id,
        )

        return CreateSessionResponse(
            session_id=session.session_id,
            ice_servers=[{"urls": settings.stun_servers}],
        )
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create session")


@router.post("/sessions/{session_id}/offer", response_model=WebRTCAnswerResponse)
async def handle_webrtc_offer(session_id: str, request: WebRTCOfferRequest):
    """
    Handle WebRTC SDP offer from frontend.

    Returns SDP answer to establish peer connection.
    """
    session = await session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        # TODO: Process WebRTC offer and generate answer
        # 1. Use aiortc to handle SDP negotiation
        # 2. Set up data channels for audio/transcript
        # 3. Return SDP answer

        logger.info(f"WebRTC offer received for session {session_id}")

        # Placeholder answer
        return WebRTCAnswerResponse(sdp="")
    except Exception as e:
        logger.error(f"Error handling WebRTC offer: {e}")
        raise HTTPException(status_code=500, detail="Failed to process offer")


@router.post("/sessions/{session_id}/candidates")
async def handle_ice_candidates(session_id: str, candidates: list[ICECandidateRequest]):
    """Handle ICE candidates from frontend."""
    session = await session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        # TODO: Add ICE candidates to the peer connection
        logger.info(f"Received {len(candidates)} ICE candidates for session {session_id}")

        return {"ack": True}
    except Exception as e:
        logger.error(f"Error handling ICE candidates: {e}")
        raise HTTPException(status_code=500, detail="Failed to process candidates")


@router.websocket("/ws/{session_id}/events")
async def websocket_events(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time events during intake conversation.

    Emits events like:
    - transcript_chunk: Real-time transcript updates
    - status_update: Session status changes
    - symptom_complete: Symptoms extracted and ready
    - error: Error events
    """
    session = await session_store.get_session(session_id)
    if not session:
        await websocket.close(code=1008, reason="Session not found")
        return

    await websocket.accept()
    logger.info(f"WebSocket connected for session {session_id}")

    try:
        # TODO: Implement event streaming
        # 1. Listen for transcript chunks from GPT-4o Realtime
        # 2. Broadcast to connected WebSocket clients
        # 3. Send final symptom payload when extraction is complete

        while True:
            # Placeholder: keep connection open
            data = await websocket.receive_text()
            logger.debug(f"WebSocket message from {session_id}: {data}")

    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {e}")
    finally:
        await websocket.close()
        logger.info(f"WebSocket disconnected for session {session_id}")


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get current session state"""
    session = await session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session.session_id,
        "status": session.status,
        "language": session.user_language,
        "start_time": session.start_time,
        "transcript_length": len(session.final_transcript),
        "extracted_symptoms": session.extracted_symptoms,
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session"""
    success = await session_store.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"deleted": True}
