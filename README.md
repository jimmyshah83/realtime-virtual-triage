# Realtime Virtual Triage

A multi-agent orchestration platform helping patients get triaged virtually using LangGraph, GPT Realtime, and GPT-5.

## Features

Virtual Front Door & Nurse Triage (primary/urgent care access & navigation)
What it is
A multi‑agent intake system that triages symptoms, stratifies risk, navigates to the right level of care (PCP, virtual visit, community clinic, ED when necessary), and completes pre‑visit steps (forms, labs, imaging). It integrates with eReferral/eConsult and provincial resources where available.
Multi‑agent design (example roles)

Intake Agent: converses (voice/chat) with patients, captures symptoms, history, meds; writes a structured triage note.
Clinical Guideline Agent: applies evidence‑based pathways, checks red flags, and proposes a safe disposition; hands off to a human nurse when confidence is low.
Access & Wait‑time Agent: finds the best available care setting (same‑day/next‑day), factoring distance and opening hours; books the slot.
Pre‑Visit Orchestration Agent: orders labs/imaging per pathway, obtains consent, and shares preparation instructions.
Benefits & Coverage Agent: validates eligibility/coverage (public/private), avoids surprise costs, and routes prior‑auth when applicable.

Why multi‑agent?
Triage + navigation + booking + pre‑visit orchestration are distinct competencies. Coordinated agents shorten access time and lower inappropriate ED use, while maintaining human‑in‑the‑loop for safety. (Agent differences and autonomy patterns summarized in your decks agentic_ai and ctc_agentic_agents.) [agentic_ai | PDF], [ctc_agentic_agents | PowerPoint]
Patient‑care impact (Canadian context)

Faster access, safer triage: appropriate level‑of‑care routing reduces delays and clinical risk; fewer low‑acuity ED visits.
Better preparedness: pre‑visit labs and forms reduce repeat visits and diagnostic delays.
Equity: multilingual intake improves access for newcomers and linguistically diverse communities common across Ontario/Canada.
Trust & compliance: triage notes, decisions, and handoffs are auditable (PHIPA/PIPEDA), with clear escalation rules to licensed clinicians. 

## Flow

```
User speaks → WebRTC → Azure Realtime API → Transcription (built-in Whisper)
                                          ↓
                          Realtime API sends transcription event
                                          ↓
                          Frontend receives transcription text
                                          ↓
                          Send text to LangGraph backend
                                          ↓
                          LangGraph agent processes
                                          ↓
                          Send agent response back to Realtime API
                                          ↓
                          Realtime API converts to speech (TTS)
                                          ↓
                          User hears response
```