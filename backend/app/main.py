"""Simplified FastAPI backend - proxy for agent LLM calls + session management."""

import json
import logging
import os
import time
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4
import threading

import httpx
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, SecretStr
from langchain_openai import ChatOpenAI

# Load environment variables
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_ROOT / ".env", override=False)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

app = FastAPI(
    title="Real-time Virtual Triage",
    description="Real-time virtual triage backend API - Agent Proxy",
    version="0.2.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Token caching for DefaultAzureCredential
cached_token: Optional[str] = None
token_expiry: float = 0
token_lock = threading.Lock()

# System prompts for each agent
AGENT_PROMPTS = {
    "triage": """You are an experienced triage nurse whose job is to collect just enough context for a downstream clinical guidance specialist to make the final severity decision.

Your responsibilities:
1. Gather the key symptom facts (onset, duration, severity, character, location) without getting stuck—capture what's available and note missing details.
2. Identify RED FLAG symptoms that require immediate attention:
   - Chest pain/pressure (possible heart attack/PE)
   - Sudden severe headache (possible stroke/aneurysm)
   - Difficulty breathing/shortness of breath
   - Altered mental status/confusion
   - Severe bleeding or trauma
   - Loss of consciousness/fainting
   - Stroke symptoms (FAST: Face drooping, Arm weakness, Speech difficulty)
   - Suicidal ideation
3. Explicitly document the key vitals you gathered (onset, duration, triggers, relieving factors) in the assessment summary so downstream agents can cite them.
4. Do not render patient-facing medical advice or definitive dispositions—the clinical guidance agent owns the severity recommendation.
5. Assess severity and assign urgency score (1-5):
   - 5: Life-threatening, requires immediate ED (red flags present)
   - 4: Urgent, ED within hours (severe pain, high fever, concerning symptoms)
   - 3: Semi-urgent, Urgent Care or ED same day (moderate symptoms)
   - 2: Non-urgent, Primary Care within days (mild symptoms)
   - 1: Routine, Primary Care scheduling (chronic issues, follow-ups)
6. Generate appropriate SNOMED CT and ICD-10 codes for documented symptoms
7. Create clinical assessment summary

Ask clarifying questions one at a time, with a hard limit of **two** follow-ups per patient issue. Include the **exact** next question you will ask in the `clarifying_question` field whenever more detail is required. If information is still missing after two clarifying attempts, note the gaps in your assessment and proceed with the handoff.

When you have:
- Chief complaint clearly identified
- Symptom details (onset, duration, severity)
- Red flag assessment completed
- Urgency score determined

Set handoff_ready to true in your response. If ANY red flag is present, the urgency score is 4 or 5, or you have already asked two clarifying questions, set handoff_ready to true even if some secondary details are pending.""",
    
    "clinical_guidance": """You are a clinical guidance specialist who interprets triage data and determines the appropriate level of care.

Responsibilities:
1. Review the triage summary (symptoms, red flags, urgency score, medical codes).
2. Decide if a physician referral is required right now.
3. Recommend the best care setting using one of the following labels exactly:
    - Emergency Department
    - Urgent Care
    - Primary Care
    - Self-care
    - Specialist
4. Provide a concise guidance summary explaining the decision.
5. List 2-4 actionable next steps for the patient. If referral is required, include preparation next steps; if not, include monitoring/self-care or follow-up advice.""",
    
    "referral_builder": """You are a medical referral coordinator creating comprehensive referral packages.

Your responsibilities:
1. Compile all patient demographics and contact information
2. Construct detailed history of present illness narrative
3. Document all symptoms with clinical details
4. Include clinical assessment and urgency determination
5. List all red flag symptoms prominently
6. Include all medical codes (SNOMED CT, ICD-10)
7. Recommend appropriate disposition:
   - Emergency Department (ED): Urgency 4-5, red flags, life-threatening
   - Urgent Care: Urgency 3, semi-urgent conditions
   - Primary Care: Urgency 1-2, routine/non-urgent
   - Specialist Referral: Specific conditions requiring specialist
8. Provide clear referral notes for receiving provider

Create a professional, complete referral package that ensures continuity of care."""
}


def _get_required_env(name: str) -> str:
    """Return a required environment variable or raise a helpful error message."""
    value = os.getenv(name)
    if value:
        return value
    raise RuntimeError(f"Missing required environment variable: {name}")


def _build_azure_model() -> ChatOpenAI:
    """Construct the Azure OpenAI client."""
    endpoint = _get_required_env("AZURE_OPENAI_ENDPOINT").rstrip("/")
    base_url = f"{endpoint}/openai/v1"
    model_name = os.getenv("AZURE_OPENAI_AGENT_MODEL", "gpt-4o")

    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=SecretStr(_get_required_env("AZURE_OPENAI_API_KEY")),
        temperature=0,
    )


# Initialize model
model = _build_azure_model()


# Load physicians directory
_PHYSICIANS_PATH = _BACKEND_ROOT / "app" / "data" / "physicians.json"


def _load_physicians() -> list[dict]:
    """Load physician directory from JSON."""
    if not _PHYSICIANS_PATH.exists():
        return []
    with _PHYSICIANS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


PHYSICIANS = _load_physicians()


def get_bearer_token(resource_scope: str) -> str:
    """Get a bearer token using DefaultAzureCredential with caching."""
    global cached_token, token_expiry
    
    current_time = time.time()
    
    with token_lock:
        if cached_token and current_time < (token_expiry - 300):
            return cached_token
    
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


# Pydantic models for structured outputs
class MedicalCodes(BaseModel):
    snomed_codes: list[str] = Field(default_factory=list)
    icd_codes: list[str] = Field(default_factory=list)


class TriageOutput(BaseModel):
    """Structured output from triage agent."""
    symptoms: list[str] = Field(description="List of reported symptoms")
    chief_complaint: str = Field(description="Primary reason for visit")
    urgency_score: int = Field(ge=1, le=5, description="Urgency level 1-5")
    red_flags: list[str] = Field(default_factory=list, description="Critical warning signs")
    assessment: str = Field(description="Clinical assessment summary")
    medical_codes: MedicalCodes = Field(default_factory=MedicalCodes)
    handoff_ready: bool = Field(description="Whether sufficient info for referral")
    clarifying_question: Optional[str] = Field(default=None, description="Next question if more info needed")
    response_text: str = Field(description="Natural language response to the patient")


class ClinicalGuidanceOutput(BaseModel):
    """Structured output from clinical guidance agent."""
    referral_required: bool = Field(description="Whether referral is needed")
    recommended_setting: Literal[
        "Emergency Department", "Urgent Care", "Primary Care", "Self-care", "Specialist"
    ]
    guidance_summary: str = Field(description="High-level decision summary")
    next_steps: list[str] = Field(default_factory=list, description="Actionable next steps")
    response_text: str = Field(description="Natural language response to the patient")


class ReferralOutput(BaseModel):
    """Structured output from referral builder agent."""
    disposition: str = Field(description="Recommended care setting")
    urgency_score: int = Field(ge=1, le=5)
    history_present_illness: str = Field(description="HPI narrative")
    referral_notes: str = Field(description="Notes for receiving provider")
    response_text: str = Field(description="Natural language response to the patient")


# Request/Response models
class AgentInvokeRequest(BaseModel):
    """Request to invoke an agent."""
    agent_type: Literal["triage", "clinical_guidance", "referral_builder"]
    user_message: str
    conversation_history: list[dict] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)


class AgentInvokeResponse(BaseModel):
    """Response from agent invocation."""
    agent_type: str
    response_text: str
    structured_output: dict


class ClientSecret(BaseModel):
    """Ephemeral key payload."""
    value: str
    expires_at: Optional[int] = None


class SessionResponse(BaseModel):
    """Response for session creation."""
    session_id: str
    client_secret: ClientSecret
    model: str
    voice: str
    session_ttl_seconds: int


class PhysicianInfo(BaseModel):
    """Physician info for lookup."""
    id: str
    name: str
    specialty: str
    location: str
    urgency_min: int
    urgency_max: int
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None


# Endpoints

@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Real-time Virtual Triage API - Agent Proxy"}


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
        session_instructions = os.getenv(
            "AZURE_OPENAI_SESSION_INSTRUCTIONS",
            "You are a helpful virtual triage assistant. Listen to the patient and respond naturally."
        )

        azure_resource = os.getenv("AZURE_RESOURCE")
        if not azure_resource:
            endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
            if endpoint:
                resource_part = endpoint.replace("https://", "").replace("http://", "").split("/")[0]
                if ".openai.azure.com" in resource_part:
                    azure_resource = resource_part.split(".openai.azure.com")[0]
                else:
                    azure_resource = resource_part.split(".")[0]
            else:
                raise ValueError("Either AZURE_RESOURCE or AZURE_OPENAI_ENDPOINT must be set")

        bearer_token = get_bearer_token("https://cognitiveservices.azure.com/.default")

        session_url = f"https://{azure_resource}.openai.azure.com/openai/v1/realtime/client_secrets"
        logger.info("Creating Azure Realtime session at %s", session_url)

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
                logger.error("Request failed with status %s: %s", response.status_code, response.text)
                raise HTTPException(
                    status_code=response.status_code,
                    detail={"error": "Failed to create session", "body": response.text},
                )

            session_payload = response.json()
            client_secret_payload = session_payload.get("client_secret") or {}
            secret_value = client_secret_payload.get("value") or session_payload.get("value")

            if not secret_value:
                raise HTTPException(status_code=500, detail="Azure response missing client secret")

            session_id = (
                session_payload.get("session_id")
                or session_payload.get("id")
                or session_payload.get("session", {}).get("id")
                or str(uuid4())
            )

            return SessionResponse(
                session_id=session_id,
                client_secret=ClientSecret(
                    value=secret_value,
                    expires_at=client_secret_payload.get("expires_at"),
                ),
                model=session_payload.get("model", deployment),
                voice=session_payload.get("voice", "alloy"),
                session_ttl_seconds=1800,
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error creating session")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc


@app.post("/agent/invoke", response_model=AgentInvokeResponse)
async def invoke_agent(request: AgentInvokeRequest) -> AgentInvokeResponse:
    """
    Invoke an agent with the given context.
    
    This is a stateless proxy - the frontend manages all state and orchestration.
    """
    agent_type = request.agent_type
    system_prompt = AGENT_PROMPTS.get(agent_type)
    
    if not system_prompt:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {agent_type}")
    
    try:
        # Build conversation for the LLM
        conversation_text = ""
        for msg in request.conversation_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            conversation_text += f"{role}: {content}\n"
        
        # Add context if provided
        context_text = ""
        if request.context:
            context_text = f"\nCurrent Context:\n{json.dumps(request.context, indent=2)}\n"
        
        # Build the full prompt
        if agent_type == "triage":
            user_prompt = f"""{context_text}
Conversation History:
{conversation_text}

Latest Patient Message: {request.user_message}

Analyze the conversation and provide your triage assessment. Include a natural response_text to say back to the patient."""
            
            structured_llm = model.with_structured_output(TriageOutput)
            result: TriageOutput = structured_llm.invoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ])
            
            return AgentInvokeResponse(
                agent_type=agent_type,
                response_text=result.response_text,
                structured_output=result.model_dump()
            )
            
        elif agent_type == "clinical_guidance":
            user_prompt = f"""{context_text}
Based on the triage findings above, determine the appropriate care setting and provide clinical guidance.
Include a natural response_text to communicate the guidance to the patient."""
            
            structured_llm = model.with_structured_output(ClinicalGuidanceOutput)
            result: ClinicalGuidanceOutput = structured_llm.invoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ])
            
            return AgentInvokeResponse(
                agent_type=agent_type,
                response_text=result.response_text,
                structured_output=result.model_dump()
            )
            
        elif agent_type == "referral_builder":
            user_prompt = f"""{context_text}
Create a comprehensive referral package based on the triage and clinical guidance findings.
Include a natural response_text to inform the patient about the referral."""
            
            structured_llm = model.with_structured_output(ReferralOutput)
            result: ReferralOutput = structured_llm.invoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ])
            
            return AgentInvokeResponse(
                agent_type=agent_type,
                response_text=result.response_text,
                structured_output=result.model_dump()
            )
        
        raise HTTPException(status_code=400, detail=f"Unhandled agent type: {agent_type}")
        
    except Exception as e:
        logger.exception("Error invoking agent %s", agent_type)
        raise HTTPException(status_code=500, detail=f"Agent invocation failed: {str(e)}") from e


@app.get("/physicians", response_model=list[PhysicianInfo])
async def get_physicians():
    """Get all available physicians."""
    return [PhysicianInfo(**p) for p in PHYSICIANS]


@app.get("/physicians/match")
async def match_physician(urgency: int, setting: str) -> Optional[PhysicianInfo]:
    """Find a matching physician based on urgency and care setting."""
    preferred_specialty_map = {
        "primary care": "Primary Care",
        "self-care": "Primary Care",
        "urgent care": "Urgent Care",
        "emergency department": "Emergency Medicine",
        "specialist": "Cardiology",
    }
    preferred = preferred_specialty_map.get(setting.lower(), "")
    
    eligible = [
        p for p in PHYSICIANS
        if p["urgency_min"] <= urgency <= p["urgency_max"]
    ]
    
    if preferred:
        for p in eligible:
            if p["specialty"].lower() == preferred.lower():
                return PhysicianInfo(**p)
    
    return PhysicianInfo(**eligible[0]) if eligible else None
