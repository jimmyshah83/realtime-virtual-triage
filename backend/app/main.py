"""Main FastAPI application entry point."""

import json
import os
from typing import Any, Dict

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage

from .agents import triage_graph, TriageAgentState, PatientInfo, MedicalCodes

# Load environment variables from .env file
load_dotenv()

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

# In-memory session storage (use Redis/DB for production)
sessions: Dict[str, TriageAgentState] = {}

# Request/Response models
class ChatRequest(BaseModel):
    """Chat request model."""
    message: str

class ChatResponse(BaseModel):
    """Chat response model."""
    current_agent: str
    response: str
    urgency: int = 0
    red_flags: list[str] = []
    handoff_ready: bool = False
    referral_complete: bool = False


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Real-time Virtual Triage API"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/session")
async def create_session() -> Response:
    """Generate an ephemeral key for Azure OpenAI Realtime session."""
    try:
        api_key = os.environ["AZURE_OPENAI_API_KEY"]
        resource_name = os.environ["AZURE_OPENAI_RESOURCE_NAME"]
        api_version = os.environ["AZURE_OPENAI_API_VERSION"]
        deployment = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]

        session_url = f"https://{resource_name}.openai.azure.com/openai/realtimeapi/sessions?api-version={api_version}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                session_url,
                json={
                    "model": deployment,
                    "voice": "alloy"
                },
                headers={
                    "api-key": api_key,
                    "Content-Type": "application/json"
                }
            )

            if response.status_code != 200:
                return Response(
                    content=json.dumps(
                        {
                            "error": "Failed to create session",
                            "details": response.text
                        }
                    ),
                    status_code=response.status_code,
                    media_type="application/json"
                )

            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type="application/json"
            )

    except Exception as e:
        return Response(
            content=json.dumps({"error": str(e)}),
            status_code=500,
            media_type="application/json"
        )


@app.post("/chat/{session_id}")
async def chat(session_id: str, chat_request: ChatRequest) -> ChatResponse:
    """Process chat message through the triage agent workflow.
    
    Args:
        session_id: Unique session identifier
        chat_request: Chat message from user
        
    Returns:
        ChatResponse with agent response and current state
    """
    # Initialize or retrieve session state
    if session_id not in sessions:
        sessions[session_id] = {  
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
            "assessment": ""
        }
    
    state = sessions[session_id]
    
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
            referral_complete=result.get("referral_package") is not None
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}") from e


@app.delete("/chat/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session."""
    if session_id in sessions:
        del sessions[session_id]
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
        "referral_complete": state.get("referral_package") is not None
    }