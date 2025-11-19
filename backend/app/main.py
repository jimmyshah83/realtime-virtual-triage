"""Main FastAPI application entry point."""

import json
import os
from typing import Any, Dict

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

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

# Function definitions for Realtime API
TRIAGE_FUNCTIONS = [
    {
        "type": "function",
        "name": "perform_triage_assessment",
        "description": "Perform clinical triage assessment when you have collected sufficient patient information including: chief complaint, symptoms with onset/duration/severity details, and relevant medical history. This will analyze urgency and detect any red flag symptoms.",
        "parameters": {
            "type": "object",
            "properties": {
                "chief_complaint": {
                    "type": "string",
                    "description": "The patient's primary reason for seeking care"
                },
                "symptoms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of all reported symptoms"
                },
                "symptom_details": {
                    "type": "string",
                    "description": "Comprehensive details about symptoms including onset time, duration, severity (1-10), character/quality, location, and any aggravating or relieving factors"
                },
                "medical_history": {
                    "type": "string",
                    "description": "Relevant medical history including chronic conditions, current medications, allergies, and recent hospitalizations"
                },
                "patient_name": {
                    "type": "string",
                    "description": "Patient's name if provided"
                },
                "patient_age": {
                    "type": "integer",
                    "description": "Patient's age if provided"
                },
                "patient_gender": {
                    "type": "string",
                    "description": "Patient's gender if provided"
                }
            },
            "required": ["chief_complaint", "symptoms", "symptom_details"]
        }
    },
    {
        "type": "function",
        "name": "build_referral_package",
        "description": "Create a comprehensive referral package after triage assessment is complete. This generates a detailed medical referral with all patient information, assessment, codes, and disposition recommendation. Only call this after perform_triage_assessment has been successfully executed.",
        "parameters": {
            "type": "object",
            "properties": {
                "include_full_details": {
                    "type": "boolean",
                    "description": "Whether to include full clinical details in the referral package",
                    "default": True
                }
            }
        }
    }
]

REALTIME_INSTRUCTIONS = """
You are a compassionate and professional triage nurse conducting a clinical assessment.

Your responsibilities:
1. Warmly greet the patient and gather their chief complaint
2. Ask focused questions one at a time about:
   - Symptom onset (when did it start?)
   - Duration (how long has it been happening?)
   - Severity (on a scale of 1-10, how bad is it?)
   - Character (describe what it feels like)
   - Location (where exactly?)
   - Associated symptoms
   - What makes it better or worse?
3. Collect relevant medical history, current medications, and allergies
4. Listen carefully for RED FLAG symptoms that need immediate attention

When you have gathered:
- Clear chief complaint
- Detailed symptom information (onset, duration, severity, character)
- Relevant medical history

CALL the perform_triage_assessment function to get the clinical analysis.

After receiving the triage results, explain the urgency level and any red flags to the patient in clear, reassuring language. Then ask if they would like you to prepare a referral package, and if yes, call the build_referral_package function.

Be empathetic, clear, and professional throughout the conversation."""

# Request/Response models
class FunctionCallRequest(BaseModel):
    """Function call request from Realtime API."""
    call_id: str
    name: str
    arguments: str  # JSON string

class TriageAssessmentArgs(BaseModel):
    """Arguments for perform_triage_assessment function."""
    chief_complaint: str
    symptoms: list[str]
    symptom_details: str
    medical_history: str = ""
    patient_name: str | None = None
    patient_age: int | None = None
    patient_gender: str | None = None

class ReferralPackageArgs(BaseModel):
    """Arguments for build_referral_package function."""
    include_full_details: bool = True


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
    """Generate an ephemeral key for Azure OpenAI Realtime session with function tools."""
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
                    "voice": "alloy",
                    "instructions": REALTIME_INSTRUCTIONS,
                    "tools": TRIAGE_FUNCTIONS,
                    "tool_choice": "auto"
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

    except Exception as e:  # noqa: BLE001
        return Response(
            content=json.dumps({"error": str(e)}),
            status_code=500,
            media_type="application/json"
        )


@app.post("/function/{session_id}")
async def execute_function(session_id: str, function_call: FunctionCallRequest):
    """Execute function called by Realtime API and return structured results.
    
    Args:
        session_id: Unique session identifier
        function_call: Function call details from Realtime API
        
    Returns:
        Function execution result with call_id and output
    """
    # Initialize or retrieve session state
    if session_id not in sessions:
        sessions[session_id] = {  # type: ignore[typeddict-item]
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
    
    try:
        if function_call.name == "perform_triage_assessment":
            # Parse function arguments
            args_dict = json.loads(function_call.arguments)
            args = TriageAssessmentArgs(**args_dict)
            
            # Update patient info if provided
            if args.patient_name or args.patient_age or args.patient_gender:
                state["patient_info"] = PatientInfo(
                    name=args.patient_name,
                    age=args.patient_age,
                    gender=args.patient_gender
                )
            
            # Build conversation context for triage agent
            context = f"""Patient Triage Information:
            
Chief Complaint: {args.chief_complaint}

Symptoms: {', '.join(args.symptoms)}

Symptom Details: {args.symptom_details}

Medical History: {args.medical_history or 'None provided'}
            """
            
            state["messages"].append(HumanMessage(content=context))
            state["chief_complaint"] = args.chief_complaint
            
            # Invoke triage agent through LangGraph
            result: Any = triage_graph.invoke(state)
            sessions[session_id] = result  # type: ignore[typeddict-item]
            
            # Build structured output for Realtime API
            urgency_labels = ["Routine", "Low Priority", "Moderate", "Urgent", "Critical/Emergency"]
            urgency_score = result.get("urgency_score", 1)
            
            output_data = {
                "success": True,
                "urgency_score": urgency_score,
                "urgency_level": urgency_labels[min(urgency_score - 1, 4)],
                "red_flags": result.get("red_flags", []),
                "red_flags_detected": len(result.get("red_flags", [])) > 0,
                "assessment_summary": result.get("assessment", ""),
                "symptoms_documented": result.get("symptoms", []),
                "medical_codes": {
                    "icd10": result.get("medical_codes", MedicalCodes()).icd_codes,
                    "snomed": result.get("medical_codes", MedicalCodes()).snomed_codes
                },
                "recommendation": "Speak the urgency level and any red flags to the patient. Ask if they would like a referral package prepared."
            }
            
            return {
                "call_id": function_call.call_id,
                "output": json.dumps(output_data)
            }
        
        elif function_call.name == "build_referral_package":
            # Parse arguments (if any)
            args_dict = json.loads(function_call.arguments) if function_call.arguments else {}
            
            # Ensure triage was completed first
            if not state.get("handoff_ready") or state.get("urgency_score", 0) == 0:
                return {
                    "call_id": function_call.call_id,
                    "output": json.dumps({
                        "success": False,
                        "error": "Triage assessment must be completed before building referral package"
                    })
                }
            
            # Invoke referral builder through LangGraph
            referral_result: Any = triage_graph.invoke(state)
            sessions[session_id] = referral_result  # type: ignore[typeddict-item]
            
            referral = referral_result.get("referral_package")
            
            if referral:
                output_data = {
                    "success": True,
                    "referral_complete": True,
                    "disposition": referral.disposition,
                    "urgency_score": referral.urgency_score,
                    "patient_name": referral.demographics.name,
                    "chief_complaint": referral.chief_complaint,
                    "red_flags": referral.red_flags,
                    "referral_summary": referral.referral_notes,
                    "recommendation": "Inform the patient that their referral package has been created and will be sent to the appropriate care facility."
                }
            else:
                output_data = {
                    "success": False,
                    "error": "Failed to generate referral package"
                }
            
            return {
                "call_id": function_call.call_id,
                "output": json.dumps(output_data)
            }
        
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown function: {function_call.name}"
            )
    
    except Exception as e:  # noqa: BLE001
        return {
            "call_id": function_call.call_id,
            "output": json.dumps({
                "success": False,
                "error": f"Function execution error: {str(e)}"
            })
        }


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