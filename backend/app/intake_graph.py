"""LangGraph-based intake agent orchestration"""

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import BaseMessage
from typing import TypedDict, Annotated
import logging

logger = logging.getLogger(__name__)


class IntakeAgentState(TypedDict):
    """State definition for the intake agent graph"""

    session_id: str
    user_language: str
    messages: Annotated[list[BaseMessage], "Chat message history"]
    transcript: str
    extracted_symptoms: dict
    status: str


def intake_conversation_node(state: IntakeAgentState) -> IntakeAgentState:
    """
    Node: Intake Conversation

    Handles the real-time conversation with the patient via GPT-4o Realtime.
    - Streams audio to GPT-4o Realtime
    - Collects transcript chunks
    - Maintains conversation state
    - Triggers symptom extraction when conversation concludes
    """
    logger.info(f"Intake conversation node for session {state['session_id']}")

    # TODO: Implement real intake conversation logic
    # 1. Receive audio from frontend via WebRTC
    # 2. Stream to GPT-4o Realtime
    # 3. Collect transcripts incrementally
    # 4. Detect conversation end (user says "done", timeout, etc.)

    state["status"] = "conversation_in_progress"
    return state


def symptom_extraction_node(state: IntakeAgentState) -> IntakeAgentState:
    """
    Node: Symptom Extraction

    Extracts structured symptoms from the completed transcript.
    - Parses medical information
    - Structures into standardized fields
    - Calculates confidence scores
    """
    logger.info(f"Symptom extraction node for session {state['session_id']}")

    # TODO: Implement symptom extraction
    # 1. Use GPT-4o to parse transcript
    # 2. Extract: chief complaint, duration, severity, associated symptoms, etc.
    # 3. Assign confidence scores to each field

    state["extracted_symptoms"] = {
        "chief_complaint": "",
        "duration": "",
        "severity": {},
        "associated_symptoms": [],
        "medication_history": [],
        "allergies": [],
    }
    state["status"] = "symptoms_extracted"
    return state


def build_intake_graph() -> StateGraph:
    """Build the LangGraph intake agent workflow"""

    graph = StateGraph(IntakeAgentState)

    # Add nodes
    graph.add_node("intake_conversation", intake_conversation_node)
    graph.add_node("symptom_extraction", symptom_extraction_node)

    # Define edges
    graph.add_edge(START, "intake_conversation")
    graph.add_edge("intake_conversation", "symptom_extraction")
    graph.add_edge("symptom_extraction", END)

    return graph.compile()


# Global compiled graph
intake_graph = build_intake_graph()
