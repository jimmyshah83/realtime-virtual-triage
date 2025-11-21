"""Langgraph Orchestration Agents Implementation."""

import json
import os
from pathlib import Path
from typing import Optional, Literal
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import BaseMessage
from pydantic import SecretStr, BaseModel, Field
from typing_extensions import TypedDict
from dotenv import load_dotenv

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_ROOT / ".env", override=False)


def _get_required_env(name: str) -> str:
    """Return a required environment variable or raise a helpful error message."""
    value = os.getenv(name)
    if value:
        return value

    example_hint = (_BACKEND_ROOT / ".env.example").relative_to(_BACKEND_ROOT)
    raise RuntimeError(
        "Missing required Azure OpenAI setting '{name}'. "
        "Create backend/.env (copy backend/{example} to backend/.env) "
        "or export the variable before starting the API.".format(
            name=name,
            example=example_hint,
        )
    )


# Pydantic Models for structured outputs
class PatientInfo(BaseModel):
    """Structured patient information."""
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    contact: Optional[str] = None
    medical_history: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)


class MedicalCodes(BaseModel):
    """Medical coding information."""
    snomed_codes: list[str] = Field(default_factory=list, description="SNOMED CT codes")
    icd_codes: list[str] = Field(default_factory=list, description="ICD-10 codes")


class PhysicianInfo(BaseModel):
    """Directory entry for available physicians."""

    id: str
    name: str
    specialty: str
    location: str
    urgency_min: int
    urgency_max: int
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None


class TriageAgentOutput(BaseModel):
    """Structured output from Triage Agent."""

    symptoms: list[str] = Field(description="List of reported symptoms")
    chief_complaint: str = Field(description="Primary reason for visit")
    urgency_score: int = Field(ge=1, le=5, description="Urgency level 1 (low) to 5 (critical)")
    red_flags: list[str] = Field(default_factory=list, description="Critical warning signs detected")
    assessment: str = Field(description="Clinical assessment summary")
    medical_codes: MedicalCodes = Field(description="SNOMED and ICD codes")
    handoff_ready: bool = Field(description="Whether sufficient info collected for referral")


class ClinicalGuidanceOutput(BaseModel):
    """Decision and guidance from the clinical guidance agent."""

    referral_required: bool = Field(description="Whether a referral to a physician is required")
    recommended_setting: Literal[
        "Emergency Department",
        "Urgent Care",
        "Primary Care",
        "Self-care",
        "Specialist",
    ]
    guidance_summary: str = Field(description="High-level summary of the decision")
    next_steps: list[str] = Field(
        default_factory=list,
        description="Actionable next steps for the patient (self-care or preparation for referral)",
    )


class ReferralPackageOutput(BaseModel):
    """Structured referral package output."""
    demographics: PatientInfo = Field(description="Patient demographic information")
    chief_complaint: str = Field(description="Primary complaint")
    history_present_illness: str = Field(description="Detailed history of present illness")
    symptoms: list[str] = Field(description="List of symptoms")
    assessment: str = Field(description="Clinical assessment")
    urgency_score: int = Field(ge=1, le=5, description="Urgency level")
    red_flags: list[str] = Field(default_factory=list, description="Critical warning signs")
    medical_codes: MedicalCodes = Field(description="Medical coding")
    disposition: str = Field(description="Recommended care setting (ED, Urgent Care, Primary Care, etc.)")
    referral_notes: str = Field(description="Additional notes for receiving provider")


# State definition for LangGraph
class TriageAgentState(TypedDict, total=False):
    """State for the multi-agent triage workflow."""

    messages: list[BaseMessage]
    symptoms: list[str]
    patient_info: PatientInfo
    urgency_score: int
    red_flags: list[str]
    medical_codes: MedicalCodes
    referral_package: Optional[ReferralPackageOutput]
    current_agent: str
    handoff_ready: bool
    chief_complaint: str
    assessment: str
    referral_required: bool
    recommended_setting: str
    guidance_summary: str
    next_steps: list[str]
    selected_physician: Optional[PhysicianInfo]

def _build_azure_model() -> AzureChatOpenAI:
    """Construct the Azure OpenAI client with validated configuration."""
    return AzureChatOpenAI(
        azure_endpoint=_get_required_env("AZURE_OPENAI_ENDPOINT"),
        azure_deployment=_get_required_env("AZURE_OPENAI_DEPLOYMENT_NAME"),
        api_version=_get_required_env("AZURE_OPENAI_API_VERSION"),
        azure_ad_token=SecretStr(_get_required_env("AZURE_OPENAI_API_KEY")),
        temperature=0,
    )


# Initialize Azure OpenAI model once so agent nodes can reuse it
model = _build_azure_model()


_PHYSICIANS_PATH = _BACKEND_ROOT / "app" / "data" / "physicians.json"


def _load_physician_directory() -> list[PhysicianInfo]:
    """Load the physician directory from JSON once at startup."""
    if not _PHYSICIANS_PATH.exists():
        return []

    try:
        with _PHYSICIANS_PATH.open("r", encoding="utf-8") as fis:
            raw_entries = json.load(fis)
    except Exception as exc:  # pragma: no cover - defensive logging path
        raise RuntimeError(f"Failed to load physician directory: {exc}") from exc

    physicians: list[PhysicianInfo] = []
    for entry in raw_entries:
        try:
            physicians.append(PhysicianInfo(**entry))
        except Exception as exc:  # pragma: no cover - invalid entry
            raise RuntimeError(f"Invalid physician entry: {entry}") from exc
    return physicians


PHYSICIAN_DIRECTORY = _load_physician_directory()


def _select_physician(urgency_score: int, recommended_setting: str) -> Optional[PhysicianInfo]:
    """Pick the best physician match using urgency and care setting."""
    if not PHYSICIAN_DIRECTORY:
        return None

    preferred_specialty_map = {
        "primary care": "Primary Care",
        "self-care": "Primary Care",
        "urgent care": "Urgent Care",
        "emergency department": "Emergency Medicine",
        "specialist": "Cardiology",
    }
    preferred = preferred_specialty_map.get(recommended_setting.lower(), "") if recommended_setting else ""

    eligible = [
        physician
        for physician in PHYSICIAN_DIRECTORY
        if physician.urgency_min <= urgency_score <= physician.urgency_max
    ]

    if preferred:
        for physician in eligible:
            if physician.specialty.lower() == preferred.lower():
                return physician

    return eligible[0] if eligible else None


TRIAGE_AGENT_SYSTEM_PROMPT: str = """
You are an experienced triage nurse conducting a clinical assessment.

Your responsibilities:
1. Gather comprehensive symptom information (onset, duration, severity, character, location)
2. Identify RED FLAG symptoms that require immediate attention:
   - Chest pain/pressure (possible heart attack/PE)
   - Sudden severe headache (possible stroke/aneurysm)
   - Difficulty breathing/shortness of breath
   - Altered mental status/confusion
   - Severe bleeding or trauma
   - Loss of consciousness/fainting
   - Stroke symptoms (FAST: Face drooping, Arm weakness, Speech difficulty)
   - Suicidal ideation
3. Assess severity and assign urgency score (1-5):
   - 5: Life-threatening, requires immediate ED (red flags present)
   - 4: Urgent, ED within hours (severe pain, high fever, concerning symptoms)
   - 3: Semi-urgent, Urgent Care or ED same day (moderate symptoms)
   - 2: Non-urgent, Primary Care within days (mild symptoms)
   - 1: Routine, Primary Care scheduling (chronic issues, follow-ups)
4. Generate appropriate SNOMED CT and ICD-10 codes for documented symptoms
5. Create clinical assessment summary

Ask clarifying questions one at a time. When you have:
- Chief complaint clearly identified
- Symptom details (onset, duration, severity)
- Red flag assessment completed
- Urgency score determined

Set handoff_ready to true in your response."""


REFERRAL_BUILDER_SYSTEM_PROMPT: str = """
You are a medical referral coordinator creating comprehensive referral packages.

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


CLINICAL_GUIDANCE_SYSTEM_PROMPT: str = """
You are a clinical guidance specialist who interprets triage data and determines the
appropriate level of care.

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
5. List 2-4 actionable next steps for the patient. If referral is required, include
    preparation next steps; if not, include monitoring/self-care or follow-up advice.
"""


# Agent Node Functions
def triage_agent(state: TriageAgentState) -> TriageAgentState:
    """Triage agent that assesses symptoms and assigns urgency."""
    structured_llm = model.with_structured_output(TriageAgentOutput)
    conversation_history = "\n".join([
        f"{msg.type}: {msg.content}" for msg in state.get("messages", [])
    ])
    prompt = f"""
{TRIAGE_AGENT_SYSTEM_PROMPT}

Conversation History:
{conversation_history}

Based on this conversation, provide your clinical assessment with symptoms, urgency score (1-5), red flags, medical codes, and assessment summary.
If insufficient information, set handoff_ready to false and indicate what information is still needed.
"""
    
    # Invoke LLM with structured output
    result: TriageAgentOutput = structured_llm.invoke(prompt)  # type: ignore[assignment]
    
    # Update state with triage results
    state["symptoms"] = result.symptoms
    state["urgency_score"] = result.urgency_score
    state["red_flags"] = result.red_flags
    state["medical_codes"] = result.medical_codes
    state["handoff_ready"] = result.handoff_ready
    state["chief_complaint"] = result.chief_complaint
    state["assessment"] = result.assessment
    state["current_agent"] = "triage"
    
    print(f"\n[TRIAGE AGENT] Urgency: {result.urgency_score}, Red Flags: {result.red_flags}")
    print(f"[TRIAGE AGENT] Handoff Ready: {result.handoff_ready}")
    
    return state


def clinical_guidance_agent(state: TriageAgentState) -> TriageAgentState:
    """Agent that determines referral necessity and next steps."""

    structured_llm = model.with_structured_output(ClinicalGuidanceOutput)
    prompt = f"""{CLINICAL_GUIDANCE_SYSTEM_PROMPT}

Triage Summary:
- Chief Complaint: {state.get('chief_complaint', 'Unknown')}
- Symptoms: {', '.join(state.get('symptoms', [])) or 'None reported'}
- Urgency Score: {state.get('urgency_score', 'Not assessed')}
- Red Flags: {', '.join(state.get('red_flags', [])) or 'None reported'}
- Assessment: {state.get('assessment', 'Not available')}
- SNOMED Codes: {', '.join(state.get('medical_codes', MedicalCodes()).snomed_codes)}
- ICD-10 Codes: {', '.join(state.get('medical_codes', MedicalCodes()).icd_codes)}

Patient Information:
{state.get('patient_info', PatientInfo()).model_dump_json(indent=2)}

Provide your determination now."""

    result: ClinicalGuidanceOutput = structured_llm.invoke(prompt)  # type: ignore[assignment]

    state["referral_required"] = result.referral_required
    state["recommended_setting"] = result.recommended_setting
    state["guidance_summary"] = result.guidance_summary
    state["next_steps"] = result.next_steps
    state["current_agent"] = "clinical_guidance"

    print(
        f"\n[CLINICAL GUIDANCE] Referral Required: {result.referral_required}, "
        f"Setting: {result.recommended_setting}"
    )

    return state


def referral_builder_agent(state: TriageAgentState) -> TriageAgentState:
    """Referral builder agent that creates comprehensive referral package."""
    if not state.get("referral_required"):
        return state

    # Create structured output model
    structured_llm = model.with_structured_output(ReferralPackageOutput)
    
    # Build context from triage results
    prompt = f"""{REFERRAL_BUILDER_SYSTEM_PROMPT}

Triage Assessment Results:
- Chief Complaint: {state.get('chief_complaint', 'Not specified')}
- Symptoms: {', '.join(state.get('symptoms', []))}
- Urgency Score: {state.get('urgency_score', 'Not assessed')}
- Red Flags: {', '.join(state.get('red_flags', [])) or 'None identified'}
- Assessment: {state.get('assessment', 'Not available')}
- SNOMED Codes: {', '.join(state.get('medical_codes', MedicalCodes()).snomed_codes)}
- ICD-10 Codes: {', '.join(state.get('medical_codes', MedicalCodes()).icd_codes)}

Patient Information:
{state.get('patient_info', PatientInfo()).model_dump_json(indent=2)}

Create a complete referral package with all necessary information for the receiving provider."""
    
    # Invoke LLM with structured output
    result: ReferralPackageOutput = structured_llm.invoke(prompt)  # type: ignore[assignment]

    selected_physician = _select_physician(
        state.get("urgency_score", 0), state.get("recommended_setting", "")
    )

    # Update state with referral package
    state["referral_package"] = result
    state["selected_physician"] = selected_physician
    state["current_agent"] = "referral_builder"

    print(f"\n[REFERRAL BUILDER] Disposition: {result.disposition}")
    if selected_physician:
        print(f"[REFERRAL BUILDER] Physician: {selected_physician.name} ({selected_physician.specialty})")
    
    return state


# Routing Logic
def _route_after_triage(state: TriageAgentState) -> Literal["clinical_guidance", "end"]:
    """Proceed to clinical guidance only when triage captured enough info."""

    handoff_ready = state.get("handoff_ready", False)
    if handoff_ready:
        return "clinical_guidance"
    return "end"


def _route_after_guidance(state: TriageAgentState) -> Literal["referral_builder", "end"]:
    """Only invoke referral builder when guidance confirmed a referral is needed."""

    if state.get("referral_required"):
        return "referral_builder"
    return "end"


# Build the graph
def create_triage_graph() -> CompiledStateGraph:
    """Create the two-agent triage workflow graph."""
    workflow = StateGraph(TriageAgentState)

    # Add agent nodes
    workflow.add_node("triage", triage_agent)
    workflow.add_node("clinical_guidance", clinical_guidance_agent)
    workflow.add_node("referral_builder", referral_builder_agent)
    
    # Set entry point
    workflow.set_entry_point("triage")
    
    # Add conditional routing from triage
    workflow.add_conditional_edges(
        "triage",
        _route_after_triage,
        {
            "clinical_guidance": "clinical_guidance",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "clinical_guidance",
        _route_after_guidance,
        {
            "referral_builder": "referral_builder",
            "end": END,
        },
    )
    
    # Referral builder always ends
    workflow.add_edge("referral_builder", END)
    
    return workflow.compile()


# Create the graph instance
triage_graph = create_triage_graph()
