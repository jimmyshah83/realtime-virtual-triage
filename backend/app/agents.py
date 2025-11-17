"""Langgraph Orchestration Agents Implementation."""

import os
from typing import TypedDict, Literal, Annotated, Any
from langgraph.graph import StateGraph, END
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from pydantic import SecretStr
from langchain.agents import create_agent

class TriageState(TypedDict):
    """State for the Triage Agent."""
    messages: list
    current_agent: Literal["intake", "clinical-guidance", "access", "pre-visit", "coverage"]
    symptoms: list[str]
    patient_info: dict
    assessment: str | None
    next_steps: str | None

model = AzureChatOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    azure_ad_token=SecretStr(os.environ["AZURE_OPENAI_API_KEY"])
)

INTAKE_AGENT_SYSTEM_PROMPT: str = """You are a compassionate intake nurse. 
    Your job is to gather the patient's symptoms, medical history, and current concerns. 
    Ask clarifying questions one at a time. 
    When you have enough information (chief complaint, duration, severity, related symptoms), 
    say 'HANDOFF_TO_CLINICAL' to transfer to clinical assessment."""

agent: Any = create_agent(
    model=model,
    system_prompt=INTAKE_AGENT_SYSTEM_PROMPT,
    tools=[],
)

def intake_agent(state: TriageState) -> TriageState:
    """Intake agent that gathers patient information"""

    messages = [
        {"role": "user", "content": state["messages"]}
    ]
    result = agent.invoke(messages)
    state["messages"].append(result["output"])
    state["assessment"] = result["output"]

    return state

# Build the graph
def create_triage_graph():
    workflow = StateGraph(TriageState)
    
    # Add nodes
    workflow.add_node("intake", intake_agent)
    workflow.add_node("clinical", clinical_guidance_agent)
    
    # Add edges
    workflow.set_entry_point("intake")
    
    # Conditional routing
    workflow.add_conditional_edges(
        "intake",
        route_agent,
        {
            "intake": "intake",
            "clinical": "clinical",
            "end": END
        }
    )
    
    workflow.add_edge("clinical", END)
    
    return workflow.compile()