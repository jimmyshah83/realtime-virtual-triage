"""Langgraph Orchestration Agents Implementation."""

import os
from typing import TypedDict
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langchain_openai import AzureChatOpenAI
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from pydantic import SecretStr, BaseModel
from dotenv import load_dotenv

load_dotenv()

class AgentState(TypedDict):
    """State for the Triage Agent."""
    messages: list

class IntakeAgent(BaseModel):
    """Intake Agent Response format."""
    messages: list
    symptoms: list[str]
    patient_info: dict

model = AzureChatOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    azure_ad_token=SecretStr(os.environ["AZURE_OPENAI_API_KEY"]),
    temperature=0,
)

INTAKE_AGENT_SYSTEM_PROMPT: str = """You are a compassionate intake nurse. 
    Your job is to gather the patient's symptoms, medical history, and current concerns. 
    Ask clarifying questions one at a time. 
    When you have enough information (chief complaint, duration, severity, related symptoms), 
    say 'HANDOFF_TO_CLINICAL' to transfer to clinical assessment."""

# Create intake agent with tools placeholder
intake_agent_executor: CompiledStateGraph = create_agent(
    model=model,
    system_prompt=INTAKE_AGENT_SYSTEM_PROMPT,
    tools=[],  # Add tools here later
    response_format=ToolStrategy(IntakeAgent)
)

def intake_agent(state: AgentState) -> AgentState:
    """Intake agent that gathers patient information"""
    result = intake_agent_executor.invoke({
        "messages": [{"role": "user", "content": "Extract contact info from: John Doe, john@example.com, (555) 123-4567"}]
    })

    intake_agent_response: IntakeAgent = result["structured_response"]
    print(f"Intake Agent Response: {intake_agent_response}")
    return state

# Build the graph
def create_triage_graph():
    """Create the triage workflow graph."""
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("intake", intake_agent)
    
    # Add edges
    workflow.set_entry_point("intake")
    workflow.add_edge("intake", END)
    
    return workflow.compile()

# Create the graph instance
triage_graph = create_triage_graph()
