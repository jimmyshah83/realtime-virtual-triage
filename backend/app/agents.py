"""Langgraph Orchestration Agents Implementation."""

import json
import logging
import os
from pathlib import Path
from typing import Optional, Literal
from app.utils.triage_prompt import TRIAGE_AGENT_SYSTEM_PROMPT
from app.utils.referral_builder import REFERRAL_BUILDER_SYSTEM_PROMPT
from app.utils.clinical_guidance import CLINICAL_GUIDANCE_SYSTEM_PROMPT
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field, SecretStr
from typing_extensions import TypedDict
from dotenv import load_dotenv

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_ROOT / ".env", override=False)

logger = logging.getLogger(__name__)

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
    clarifying_question: Optional[str] = Field(
        default=None,
        description="Next question to ask the patient when more info is required",
    )


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
    clarifying_question: Optional[str]
    clarification_attempts: int

def _build_azure_model() -> ChatOpenAI:
    """Construct the Azure OpenAI client pointed at the v1 endpoint."""
    endpoint = _get_required_env("AZURE_OPENAI_ENDPOINT").rstrip("/")
    base_url = f"{endpoint}/openai/v1"
    model_name = os.getenv("AZURE_OPENAI_AGENT_MODEL", "gpt-5")

    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=SecretStr(_get_required_env("AZURE_OPENAI_API_KEY")),
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

# Agent Node Functions
def triage_agent(state: TriageAgentState) -> TriageAgentState:
    """Triage agent that assesses symptoms and assigns urgency."""
    
    logger.info("Starting triage agent with state: %s", state)

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
    state["clarifying_question"] = result.clarifying_question
    state["current_agent"] = "triage"

    previous_attempts = state.get("clarification_attempts", 0) or 0
    if result.handoff_ready or not result.clarifying_question:
        state["clarification_attempts"] = 0
    else:
        if previous_attempts >= 2:
            state["handoff_ready"] = True
            state["clarifying_question"] = None
            state["clarification_attempts"] = 0
        else:
            state["clarification_attempts"] = previous_attempts + 1
    
    print(f"\n[TRIAGE AGENT] Urgency: {result.urgency_score}, Red Flags: {result.red_flags}")
    print(f"[TRIAGE AGENT] Handoff Ready: {result.handoff_ready}")
    
    logger.info("Completed triage agent with updated state: %s", state)

    return state


def clinical_guidance_agent(state: TriageAgentState) -> TriageAgentState:
    """Agent that determines referral necessity and next steps."""

    logger.info("Starting clinical guidance agent with state: %s", state)

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

    logger.info("Completed clinical guidance agent with updated state: %s", state)

    return state


def referral_builder_agent(state: TriageAgentState) -> TriageAgentState:
    """Referral builder agent that creates comprehensive referral package."""

    logger.info("Starting referral builder agent with state: %s", state)
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
    
    logger.info("Completed referral builder agent with updated state: %s", state)
    return state


# Routing Logic
def _route_after_triage(state: TriageAgentState) -> Literal["clinical_guidance", "end"]:
    """Proceed to clinical guidance only when triage captured enough info."""

    handoff_ready = state.get("handoff_ready", False)
    red_flags = state.get("red_flags", []) or []
    urgency = state.get("urgency_score", 0) or 0

    if handoff_ready or red_flags or urgency >= 4:
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
