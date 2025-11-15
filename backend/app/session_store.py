"""In-memory session store for active intake sessions"""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Optional
import logging

from app.models import IntakeSessionState
from app.config import settings

logger = logging.getLogger(__name__)


class SessionStore:
    """Thread-safe in-memory store for intake sessions"""

    def __init__(self, ttl_hours: int = 24):
        self._sessions: dict[str, IntakeSessionState] = {}
        self._ttl = timedelta(hours=ttl_hours)
        self._lock = asyncio.Lock()

    async def create_session(
        self, user_language: str, user_id: Optional[str] = None
    ) -> IntakeSessionState:
        """Create a new intake session"""
        session_id = str(uuid.uuid4())
        session = IntakeSessionState(
            session_id=session_id,
            user_language=user_language,
            start_time=datetime.utcnow(),
        )

        async with self._lock:
            self._sessions[session_id] = session
            logger.info(
                f"Created session {session_id} for user {user_id} (lang: {user_language})"
            )

        return session

    async def get_session(self, session_id: str) -> Optional[IntakeSessionState]:
        """Retrieve an active session by ID"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session and self._is_expired(session):
                del self._sessions[session_id]
                logger.info(f"Session {session_id} expired and removed")
                return None
            return session

    async def update_session(self, session_id: str, **updates) -> Optional[IntakeSessionState]:
        """Update session fields"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None

            for key, value in updates.items():
                if hasattr(session, key):
                    setattr(session, key, value)

            return session

    async def add_transcript_chunk(self, session_id: str, chunk: str) -> bool:
        """Append a transcript chunk to session"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                logger.warning(f"Session {session_id} not found for transcript chunk")
                return False

            session.transcript_chunks.append(chunk)
            return True

    async def mark_completed(
        self,
        session_id: str,
        final_transcript: str,
        extracted_symptoms: dict,
    ) -> bool:
        """Mark a session as completed with extracted symptoms"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False

            session.status = "completed"
            session.final_transcript = final_transcript
            session.extracted_symptoms = extracted_symptoms
            logger.info(f"Session {session_id} marked as completed")
            return True

    async def mark_error(self, session_id: str, error_message: str) -> bool:
        """Mark a session as errored"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False

            session.status = "error"
            session.error_message = error_message
            logger.error(f"Session {session_id} marked as error: {error_message}")
            return True

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session"""
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"Session {session_id} deleted")
                return True
            return False

    async def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions and return count"""
        async with self._lock:
            expired_ids = [
                sid for sid, session in self._sessions.items()
                if self._is_expired(session)
            ]
            for sid in expired_ids:
                del self._sessions[sid]

            if expired_ids:
                logger.info(f"Cleaned up {len(expired_ids)} expired sessions")
            return len(expired_ids)

    def _is_expired(self, session: IntakeSessionState) -> bool:
        """Check if session is expired"""
        return datetime.utcnow() - session.start_time > self._ttl

    async def get_active_session_count(self) -> int:
        """Get count of active sessions"""
        async with self._lock:
            return len(
                [
                    s for s in self._sessions.values()
                    if s.status == "active" and not self._is_expired(s)
                ]
            )


# Global session store instance
session_store = SessionStore(ttl_hours=settings.session_ttl_hours)
