import { useState, useRef, useEffect, useCallback } from 'react'
import './App.css'

// ============================================================================
// Types
// ============================================================================

type AgentRole = 'triage' | 'clinical_guidance' | 'referral_builder'
type AgentStageStatus = 'waiting' | 'pending' | 'active' | 'complete'

interface MedicalCodes {
  snomed_codes: string[]
  icd_codes: string[]
}

interface TriageData {
  symptoms: string[]
  chiefComplaint: string
  urgencyScore: number
  redFlags: string[]
  assessment: string
  medicalCodes: MedicalCodes
  handoffReady: boolean
  clarifyingQuestion: string | null
  clarificationAttempts: number
}

interface GuidanceData {
  referralRequired: boolean
  recommendedSetting: string
  guidanceSummary: string
  nextSteps: string[]
}

interface ReferralData {
  disposition: string
  urgencyScore: number
  historyPresentIllness: string
  referralNotes: string
  complete: boolean
}

interface PhysicianInfo {
  id: string
  name: string
  specialty: string
  location: string
  urgency_min: number
  urgency_max: number
  contact_phone?: string | null
  contact_email?: string | null
}

interface Message {
  id: number
  text: string
  sender: 'user' | 'bot'
  timestamp: Date
  agent?: AgentRole
}

interface ConversationMessage {
  role: 'user' | 'assistant'
  content: string
}

interface RealtimeEvent {
  type: string
  [key: string]: unknown
}

// ============================================================================
// Agent Orchestrator - State Machine
// ============================================================================

interface OrchestratorState {
  currentAgent: AgentRole
  triage: TriageData
  guidance: GuidanceData
  referral: ReferralData
  physician: PhysicianInfo | null
  conversationHistory: ConversationMessage[]
}

const createInitialOrchestratorState = (): OrchestratorState => ({
  currentAgent: 'triage',
  triage: {
    symptoms: [],
    chiefComplaint: '',
    urgencyScore: 0,
    redFlags: [],
    assessment: '',
    medicalCodes: { snomed_codes: [], icd_codes: [] },
    handoffReady: false,
    clarifyingQuestion: null,
    clarificationAttempts: 0,
  },
  guidance: {
    referralRequired: false,
    recommendedSetting: '',
    guidanceSummary: '',
    nextSteps: [],
  },
  referral: {
    disposition: '',
    urgencyScore: 0,
    historyPresentIllness: '',
    referralNotes: '',
    complete: false,
  },
  physician: null,
  conversationHistory: [],
})

// ============================================================================
// API Functions
// ============================================================================

const API_BASE = 'http://localhost:8000'

interface AgentInvokeResponse {
  agent_type: string
  response_text: string
  structured_output: Record<string, unknown>
}

async function invokeAgent(
  agentType: AgentRole,
  userMessage: string,
  conversationHistory: ConversationMessage[],
  context: Record<string, unknown>
): Promise<AgentInvokeResponse> {
  const response = await fetch(`${API_BASE}/agent/invoke`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      agent_type: agentType,
      user_message: userMessage,
      conversation_history: conversationHistory,
      context,
    }),
  })

  if (!response.ok) {
    throw new Error(`Agent invocation failed: ${response.statusText}`)
  }

  return response.json()
}

async function matchPhysician(urgency: number, setting: string): Promise<PhysicianInfo | null> {
  const response = await fetch(
    `${API_BASE}/physicians/match?urgency=${urgency}&setting=${encodeURIComponent(setting)}`
  )
  if (!response.ok || response.status === 204) {
    return null
  }
  return response.json()
}

// ============================================================================
// Main App Component
// ============================================================================

const PASS_THROUGH_REALTIME_EVENTS = new Set<string>([
  'session.updated',
  'input_audio_buffer.speech_started',
  'input_audio_buffer.speech_stopped',
  'input_audio_buffer.committed',
  'response.created',
  'response.output_item.added',
  'response.output_item.done',
  'response.content_part.added',
  'response.content_part.done',
  'response.output_audio_transcript.delta',
  'response.output_audio_transcript.done',
  'response.output_audio.done',
  'output_audio_buffer.started',
  'output_audio_buffer.stopped',
  'conversation.item.added',
  'conversation.item.done',
])

function App() {
  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------
  
  const createIntroMessage = (): Message => ({
    id: 1,
    text: "Hello! I'm your virtual triage nurse. Tell me what's going on so I can assess your symptoms.",
    sender: 'bot',
    timestamp: new Date(),
    agent: 'triage',
  })

  const [messages, setMessages] = useState<Message[]>([createIntroMessage()])
  const [inputText, setInputText] = useState('')
  const [isRecording, setIsRecording] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionMeta, setSessionMeta] = useState<{ model: string; voice: string; ttl: number } | null>(null)
  
  // Orchestrator state
  const [orchestrator, setOrchestrator] = useState<OrchestratorState>(createInitialOrchestratorState())

  // Refs for WebRTC
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null)
  const audioElementRef = useRef<HTMLAudioElement | null>(null)
  const dataChannelRef = useRef<RTCDataChannel | null>(null)
  const sessionIdRef = useRef<string | null>(null)

  useEffect(() => {
    sessionIdRef.current = sessionId
  }, [sessionId])

  // -------------------------------------------------------------------------
  // Agent Orchestration Logic
  // -------------------------------------------------------------------------

  const buildContext = useCallback((state: OrchestratorState): Record<string, unknown> => {
    return {
      currentAgent: state.currentAgent,
      triage: {
        symptoms: state.triage.symptoms,
        chief_complaint: state.triage.chiefComplaint,
        urgency_score: state.triage.urgencyScore,
        red_flags: state.triage.redFlags,
        assessment: state.triage.assessment,
        medical_codes: state.triage.medicalCodes,
        handoff_ready: state.triage.handoffReady,
      },
      guidance: {
        referral_required: state.guidance.referralRequired,
        recommended_setting: state.guidance.recommendedSetting,
        guidance_summary: state.guidance.guidanceSummary,
        next_steps: state.guidance.nextSteps,
      },
    }
  }, [])

  const shouldTransitionToGuidance = useCallback((triageData: TriageData): boolean => {
    // Transition when triage is ready to hand off
    return (
      triageData.handoffReady ||
      triageData.redFlags.length > 0 ||
      triageData.urgencyScore >= 4 ||
      triageData.clarificationAttempts >= 2
    )
  }, [])

  const shouldTransitionToReferral = useCallback((guidanceData: GuidanceData): boolean => {
    // Transition when guidance is complete and referral is required
    return guidanceData.referralRequired && guidanceData.guidanceSummary !== ''
  }, [])

  const processWithOrchestrator = useCallback(async (userMessage: string) => {
    if (isProcessing) return
    setIsProcessing(true)

    try {
      let currentState = { ...orchestrator }
      
      // Add user message to conversation history
      currentState.conversationHistory = [
        ...currentState.conversationHistory,
        { role: 'user' as const, content: userMessage },
      ]

      let responseText = ''
      let agentResponded: AgentRole = currentState.currentAgent

      // Step 1: Always invoke current agent first
      if (currentState.currentAgent === 'triage') {
        const context = buildContext(currentState)
        const result = await invokeAgent('triage', userMessage, currentState.conversationHistory, context)
        const output = result.structured_output

        // Update triage data
        const attempts = currentState.triage.clarificationAttempts
        currentState.triage = {
          symptoms: (output.symptoms as string[]) || [],
          chiefComplaint: (output.chief_complaint as string) || '',
          urgencyScore: (output.urgency_score as number) || 0,
          redFlags: (output.red_flags as string[]) || [],
          assessment: (output.assessment as string) || '',
          medicalCodes: (output.medical_codes as MedicalCodes) || { snomed_codes: [], icd_codes: [] },
          handoffReady: (output.handoff_ready as boolean) || false,
          clarifyingQuestion: (output.clarifying_question as string) || null,
          clarificationAttempts: output.handoff_ready ? 0 : attempts + 1,
        }

        responseText = result.response_text
        agentResponded = 'triage'

        // Check if we should transition to clinical guidance
        if (shouldTransitionToGuidance(currentState.triage)) {
          currentState.currentAgent = 'clinical_guidance'

          // Immediately invoke clinical guidance
          const guidanceContext = buildContext(currentState)
          const guidanceResult = await invokeAgent(
            'clinical_guidance',
            '',
            currentState.conversationHistory,
            guidanceContext
          )
          const guidanceOutput = guidanceResult.structured_output

          currentState.guidance = {
            referralRequired: (guidanceOutput.referral_required as boolean) || false,
            recommendedSetting: (guidanceOutput.recommended_setting as string) || '',
            guidanceSummary: (guidanceOutput.guidance_summary as string) || '',
            nextSteps: (guidanceOutput.next_steps as string[]) || [],
          }

          responseText = guidanceResult.response_text
          agentResponded = 'clinical_guidance'

          // Check if we should transition to referral builder
          if (shouldTransitionToReferral(currentState.guidance)) {
            currentState.currentAgent = 'referral_builder'

            // Immediately invoke referral builder
            const referralContext = buildContext(currentState)
            const referralResult = await invokeAgent(
              'referral_builder',
              '',
              currentState.conversationHistory,
              referralContext
            )
            const referralOutput = referralResult.structured_output

            currentState.referral = {
              disposition: (referralOutput.disposition as string) || '',
              urgencyScore: (referralOutput.urgency_score as number) || 0,
              historyPresentIllness: (referralOutput.history_present_illness as string) || '',
              referralNotes: (referralOutput.referral_notes as string) || '',
              complete: true,
            }

            // Match a physician
            const physician = await matchPhysician(
              currentState.triage.urgencyScore,
              currentState.guidance.recommendedSetting
            )
            currentState.physician = physician

            responseText = referralResult.response_text
            agentResponded = 'referral_builder'
          }
        }
      }

      // Add assistant message to conversation history
      currentState.conversationHistory = [
        ...currentState.conversationHistory,
        { role: 'assistant' as const, content: responseText },
      ]

      // Update orchestrator state
      setOrchestrator(currentState)

      // Add bot message to UI
      setMessages((prev) => [
        ...prev,
        {
          id: prev.length + 1,
          text: responseText,
          sender: 'bot',
          timestamp: new Date(),
          agent: agentResponded,
        },
      ])

      // Send response to GPT-realtime for TTS
      if (dataChannelRef.current && dataChannelRef.current.readyState === 'open') {
        const responseEvent: RealtimeEvent = {
          type: 'conversation.item.create',
          item: {
            type: 'message',
            role: 'assistant',
            content: [{ type: 'output_text', text: responseText }],
          },
        }
        dataChannelRef.current.send(JSON.stringify(responseEvent))

        const generateEvent: RealtimeEvent = {
          type: 'response.create',
        }
        dataChannelRef.current.send(JSON.stringify(generateEvent))
      }
    } catch (error) {
      console.error('Error in orchestrator:', error)
      setMessages((prev) => [
        ...prev,
        {
          id: prev.length + 1,
          text: "I'm sorry, I encountered an error processing your request. Please try again.",
          sender: 'bot',
          timestamp: new Date(),
          agent: orchestrator.currentAgent,
        },
      ])
    } finally {
      setIsProcessing(false)
    }
  }, [orchestrator, isProcessing, buildContext, shouldTransitionToGuidance, shouldTransitionToReferral])

  // -------------------------------------------------------------------------
  // Message Handling
  // -------------------------------------------------------------------------

  const extractTranscriptText = (event: RealtimeEvent): string | null => {
    if (!event) return null

    const directTranscript = (event as { transcript?: unknown }).transcript
    if (typeof directTranscript === 'string' && directTranscript.trim()) {
      return directTranscript.trim()
    }

    const content = (event as { content?: unknown }).content as { text?: unknown } | undefined
    if (content && typeof content.text === 'string' && content.text.trim()) {
      return content.text.trim()
    }

    const item = (event as { item?: unknown }).item as { content?: Array<{ text?: unknown }> } | undefined
    if (item && Array.isArray(item.content)) {
      const textPart = item.content.find((part) => typeof part?.text === 'string')
      if (textPart && typeof textPart.text === 'string' && textPart.text.trim()) {
        return textPart.text.trim()
      }
    }

    return null
  }

  const handleSendMessage = async () => {
    if (inputText.trim() && !isProcessing) {
      const messageText = inputText
      setInputText('')

      setMessages((prev) => [
        ...prev,
        {
          id: prev.length + 1,
          text: messageText,
          sender: 'user',
          timestamp: new Date(),
        },
      ])

      await processWithOrchestrator(messageText)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  // -------------------------------------------------------------------------
  // WebRTC / Realtime Session
  // -------------------------------------------------------------------------

  useEffect(() => {
    return () => {
      if (peerConnectionRef.current) {
        peerConnectionRef.current.close()
      }
      if (audioElementRef.current) {
        audioElementRef.current.srcObject = null
      }
    }
  }, [])

  const resetConversationState = () => {
    setMessages([createIntroMessage()])
    setOrchestrator(createInitialOrchestratorState())
  }

  const startRealtimeSession = async () => {
    try {
      setIsRecording(true)

      const sessionResponse = await fetch(`${API_BASE}/session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })

      if (!sessionResponse.ok) {
        throw new Error(`Failed to create session: ${sessionResponse.statusText}`)
      }

      const sessionData = await sessionResponse.json()
      const ephemeralKey = sessionData.client_secret?.value
      const newSessionId = sessionData.session_id

      if (!ephemeralKey || !newSessionId) {
        throw new Error('Session response missing credentials')
      }

      resetConversationState()
      setSessionId(newSessionId)
      sessionIdRef.current = newSessionId
      setSessionMeta({
        model: sessionData.model,
        voice: sessionData.voice,
        ttl: sessionData.session_ttl_seconds,
      })

      // Create WebRTC peer connection
      const pc = new RTCPeerConnection()
      peerConnectionRef.current = pc

      // Set up remote audio playback
      audioElementRef.current = document.createElement('audio')
      audioElementRef.current.autoplay = true
      pc.ontrack = (e) => {
        if (audioElementRef.current) {
          audioElementRef.current.srcObject = e.streams[0]
        }
      }

      // Add local audio track
      const ms = await navigator.mediaDevices.getUserMedia({ audio: true })
      pc.addTrack(ms.getTracks()[0])

      // Set up data channel
      const dc = pc.createDataChannel('realtime-channel')
      dataChannelRef.current = dc

      dc.onopen = () => {
        console.log('Data channel opened')
        setIsConnected(true)

        const sessionUpdate: RealtimeEvent = {
          type: 'session.update',
          session: {
            type: 'realtime',
            audio: {
              input: {
                turn_detection: {
                  type: 'server_vad',
                  threshold: 0.5,
                  prefix_padding_ms: 300,
                  silence_duration_ms: 500,
                  create_response: false,
                  interrupt_response: true,
                },
                transcription: {
                  model: 'whisper-1',
                },
              },
            },
          },
        }
        dc.send(JSON.stringify(sessionUpdate))
      }

      dc.onmessage = async (event) => {
        try {
          const realtimeEvent: RealtimeEvent = JSON.parse(event.data)
          console.log('Realtime event:', realtimeEvent.type)

          switch (realtimeEvent.type) {
            case 'session.created':
              console.log('Realtime API session is ready')
              break

            case 'conversation.item.input_audio_transcription.completed':
            case 'conversation.item.audio_transcription.completed': {
              const transcript = extractTranscriptText(realtimeEvent)
              if (!transcript) {
                console.warn('Transcription event missing text')
                break
              }

              console.log('Transcription:', transcript)

              setMessages((prev) => [
                ...prev,
                {
                  id: prev.length + 1,
                  text: transcript,
                  sender: 'user',
                  timestamp: new Date(),
                },
              ])

              await processWithOrchestrator(transcript)
              break
            }

            case 'conversation.item.input_audio_transcription.failed':
            case 'conversation.item.audio_transcription.failed':
              console.error('Transcription failed:', realtimeEvent)
              break

            case 'response.done':
              console.log('Response generation completed')
              break

            case 'response.error':
              console.error('Response error:', realtimeEvent.error)
              break

            case 'error':
              console.error('Realtime API error:', realtimeEvent.error ?? realtimeEvent)
              break

            default:
              if (!PASS_THROUGH_REALTIME_EVENTS.has(realtimeEvent.type)) {
                console.log('Unhandled event:', realtimeEvent.type)
              }
              break
          }
        } catch (err) {
          console.error('Error parsing message:', err)
        }
      }

      dc.onclose = () => {
        console.log('Data channel closed')
        setIsConnected(false)
        setIsRecording(false)
      }

      // Start WebRTC session
      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)

      const region = 'eastus2'
      const deployment = 'gpt-realtime'
      const url = `https://${region}.realtimeapi-preview.ai.azure.com/v1/realtimertc?model=${deployment}&api-version=2025-08-28`

      const sdpResponse = await fetch(url, {
        method: 'POST',
        body: offer.sdp,
        headers: {
          Authorization: `Bearer ${ephemeralKey}`,
          'Content-Type': 'application/sdp',
        },
      })

      if (!sdpResponse.ok) {
        throw new Error(`SDP exchange failed: ${sdpResponse.statusText}`)
      }

      const answerSdp = await sdpResponse.text()
      await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp })

      console.log('Realtime session started')
    } catch (error) {
      console.error('Error starting realtime session:', error)
      alert(`Failed to start session: ${error instanceof Error ? error.message : 'Unknown error'}`)
      setIsRecording(false)
      setIsConnected(false)
    }
  }

  const stopRealtimeSession = () => {
    if (peerConnectionRef.current) {
      peerConnectionRef.current.close()
      peerConnectionRef.current = null
    }
    if (audioElementRef.current) {
      audioElementRef.current.srcObject = null
    }
    if (dataChannelRef.current) {
      dataChannelRef.current.close()
      dataChannelRef.current = null
    }
    setIsRecording(false)
    setIsConnected(false)
    setSessionId(null)
    sessionIdRef.current = null
    console.log('Realtime session stopped')
  }

  const toggleRecording = async () => {
    if (isRecording) {
      stopRealtimeSession()
    } else {
      await startRealtimeSession()
    }
  }

  // -------------------------------------------------------------------------
  // UI Helpers
  // -------------------------------------------------------------------------

  const getAgentLabel = (agent: AgentRole) => {
    switch (agent) {
      case 'triage':
        return '🩺 Triage Nurse'
      case 'clinical_guidance':
        return '🧭 Clinical Guidance'
      case 'referral_builder':
        return '📨 Referral Coordinator'
      default:
        return '🤖 Assistant'
    }
  }

  const getStageStatus = (agent: AgentRole): AgentStageStatus => {
    const { currentAgent, triage, guidance, referral } = orchestrator

    if (agent === 'triage') {
      if (triage.handoffReady || referral.complete) {
        return 'complete'
      }
      return currentAgent === 'triage' ? 'active' : 'pending'
    }

    if (agent === 'clinical_guidance') {
      if (!triage.handoffReady && triage.redFlags.length === 0 && triage.urgencyScore < 4) {
        return 'waiting'
      }
      if (!guidance.guidanceSummary) {
        return currentAgent === 'clinical_guidance' ? 'active' : 'pending'
      }
      return 'complete'
    }

    // referral_builder
    if (!guidance.referralRequired) {
      return guidance.guidanceSummary ? 'complete' : 'waiting'
    }
    if (referral.complete) {
      return 'complete'
    }
    if (!guidance.guidanceSummary) {
      return 'waiting'
    }
    return currentAgent === 'referral_builder' ? 'active' : 'pending'
  }

  const statusLabels: Record<AgentStageStatus, string> = {
    waiting: 'Waiting',
    pending: 'Ready',
    active: 'Active',
    complete: 'Complete',
  }

  const agentStages = [
    {
      id: 'triage' as AgentRole,
      title: 'Triage Nurse',
      icon: '🩺',
      description: 'Collects symptoms, red flags, and urgency.',
      helper: orchestrator.triage.handoffReady
        ? 'Assessment locked in for referral.'
        : 'Gathering clinical details.',
      status: getStageStatus('triage'),
    },
    {
      id: 'clinical_guidance' as AgentRole,
      title: 'Clinical Guidance',
      icon: '🧭',
      description: 'Determines care setting and next steps.',
      helper: !orchestrator.triage.handoffReady && orchestrator.triage.redFlags.length === 0
        ? 'Waiting for triage findings.'
        : orchestrator.guidance.guidanceSummary
          ? orchestrator.guidance.referralRequired
            ? 'Referral recommended; sharing provider soon.'
            : 'No referral needed—sharing next steps.'
          : orchestrator.currentAgent === 'clinical_guidance'
            ? 'Evaluating urgency and referral need...'
            : 'Preparing guidance summary.',
      status: getStageStatus('clinical_guidance'),
    },
    {
      id: 'referral_builder' as AgentRole,
      title: 'Referral Coordinator',
      icon: '📨',
      description: 'Builds the referral package for providers.',
      helper: !orchestrator.guidance.referralRequired
        ? 'Referral not required for this case.'
        : orchestrator.referral.complete
          ? 'Referral package ready to share.'
          : orchestrator.guidance.guidanceSummary
            ? 'Preparing referral summary now.'
            : 'Waiting for guidance decision.',
      status: getStageStatus('referral_builder'),
    },
  ]

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="chat-container">
      <div className="chat-header">
        <div className="header-content">
          <div className="avatar">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 5C13.66 5 15 6.34 15 8C15 9.66 13.66 11 12 11C10.34 11 9 9.66 9 8C9 6.34 10.34 5 12 5ZM12 19.2C9.5 19.2 7.29 17.92 6 15.98C6.03 13.99 10 12.9 12 12.9C13.99 12.9 17.97 13.99 18 15.98C16.71 17.92 14.5 19.2 12 19.2Z"
                fill="currentColor"
              />
            </svg>
          </div>
          <div className="header-text">
            <h1>Virtual Health Assistant</h1>
            <p className="status">
              <span className="status-dot"></span>
              {isConnected
                ? `Connected - ${getAgentLabel(orchestrator.currentAgent)}`
                : 'Offline'}
            </p>
            {sessionMeta && isConnected && (
              <p className="session-meta">
                {sessionMeta.model} • {sessionMeta.voice} • TTL {Math.round(sessionMeta.ttl / 60)}m
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="agent-tracker">
        {agentStages.map((stage) => (
          <div key={stage.id} className={`agent-card ${stage.status}`}>
            <div className="agent-card-top">
              <div className="agent-icon" aria-hidden="true">
                {stage.icon}
              </div>
              <div className="agent-text">
                <p className="agent-name">{stage.title}</p>
                <p className="agent-desc">{stage.description}</p>
              </div>
              <span className={`agent-status-pill ${stage.status}`}>
                {statusLabels[stage.status]}
              </span>
            </div>
            <p className="agent-helper">{stage.helper}</p>
          </div>
        ))}
      </div>

      {(orchestrator.triage.urgencyScore > 0 ||
        orchestrator.triage.redFlags.length > 0 ||
        orchestrator.triage.symptoms.length > 0) && (
        <div className="triage-summary">
          <div>
            <strong>Urgency:</strong>{' '}
            {orchestrator.triage.urgencyScore
              ? `${orchestrator.triage.urgencyScore}/5`
              : 'Evaluating'}
          </div>
          {orchestrator.triage.redFlags.length > 0 && (
            <div className="red-flags">
              <strong>⚠️ Red Flags:</strong> {orchestrator.triage.redFlags.join(', ')}
            </div>
          )}
          {orchestrator.triage.symptoms.length > 0 && (
            <div>
              <strong>Symptoms:</strong> {orchestrator.triage.symptoms.join(', ')}
            </div>
          )}
          {orchestrator.triage.chiefComplaint && (
            <div>
              <strong>Chief Complaint:</strong> {orchestrator.triage.chiefComplaint}
            </div>
          )}
          {orchestrator.triage.assessment && (
            <div>
              <strong>Assessment:</strong> {orchestrator.triage.assessment}
            </div>
          )}
          {orchestrator.triage.medicalCodes &&
            (orchestrator.triage.medicalCodes.snomed_codes?.length ||
              orchestrator.triage.medicalCodes.icd_codes?.length) && (
              <div className="medical-codes">
                {orchestrator.triage.medicalCodes.snomed_codes?.length ? (
                  <div>
                    <strong>SNOMED:</strong>{' '}
                    {orchestrator.triage.medicalCodes.snomed_codes.join(', ')}
                  </div>
                ) : null}
                {orchestrator.triage.medicalCodes.icd_codes?.length ? (
                  <div>
                    <strong>ICD-10:</strong>{' '}
                    {orchestrator.triage.medicalCodes.icd_codes.join(', ')}
                  </div>
                ) : null}
              </div>
            )}
          {orchestrator.triage.handoffReady && !orchestrator.referral.complete && (
            <div className="handoff-note">
              <strong>Next:</strong> Referral coordinator is preparing your package.
            </div>
          )}
          {orchestrator.referral.complete && (
            <div className="handoff-note success">
              <strong>Referral Ready:</strong> Package completed for provider handoff.
            </div>
          )}
        </div>
      )}

      {(orchestrator.guidance.guidanceSummary || orchestrator.physician) && (
        <div className="guidance-summary-card">
          <div>
            <strong>Recommended Setting:</strong>{' '}
            {orchestrator.guidance.recommendedSetting || 'Determining'}
          </div>
          {orchestrator.guidance.guidanceSummary && (
            <div>
              <strong>Guidance:</strong> {orchestrator.guidance.guidanceSummary}
            </div>
          )}
          {orchestrator.guidance.nextSteps.length > 0 && (
            <div className="next-steps">
              <strong>Next Steps:</strong>
              <ul>
                {orchestrator.guidance.nextSteps.map((step, index) => (
                  <li key={`step-${index}`}>{step}</li>
                ))}
              </ul>
            </div>
          )}
          {orchestrator.physician && (
            <div className="physician-card">
              <div className="physician-header">Assigned Physician</div>
              <div className="physician-name">{orchestrator.physician.name}</div>
              <div className="physician-detail">
                {orchestrator.physician.specialty} • {orchestrator.physician.location}
              </div>
              {orchestrator.physician.contact_phone && (
                <div className="physician-detail">
                  Phone: {orchestrator.physician.contact_phone}
                </div>
              )}
              {orchestrator.physician.contact_email && (
                <div className="physician-detail">
                  Email: {orchestrator.physician.contact_email}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="chat-messages">
        {messages.map((message) => (
          <div key={message.id} className={`message ${message.sender}`}>
            <div className="message-bubble">
              {message.agent && (
                <div className="agent-badge">{getAgentLabel(message.agent)}</div>
              )}
              <p>{message.text}</p>
              <span className="message-time">
                {message.timestamp.toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
            </div>
          </div>
        ))}
        {isProcessing && (
          <div className="message bot">
            <div className="message-bubble">
              <div className="agent-badge">{getAgentLabel(orchestrator.currentAgent)}</div>
              <p className="typing-indicator">Thinking...</p>
            </div>
          </div>
        )}
      </div>

      <div className="chat-input-container">
        <div className="input-wrapper">
          <textarea
            className="chat-input"
            placeholder="Type your message..."
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyPress={handleKeyPress}
            rows={1}
            disabled={isProcessing}
          />
          <button
            className={`mic-button ${isRecording ? 'recording' : ''}`}
            onClick={toggleRecording}
            aria-label="Voice input"
          >
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M12 14C13.66 14 15 12.66 15 11V5C15 3.34 13.66 2 12 2C10.34 2 9 3.34 9 5V11C9 12.66 10.34 14 12 14Z"
                fill="currentColor"
              />
              <path
                d="M17 11C17 13.76 14.76 16 12 16C9.24 16 7 13.76 7 11H5C5 14.53 7.61 17.43 11 17.92V21H13V17.92C16.39 17.43 19 14.53 19 11H17Z"
                fill="currentColor"
              />
            </svg>
          </button>
          <button
            className="send-button"
            onClick={handleSendMessage}
            disabled={!inputText.trim() || isProcessing}
            aria-label="Send message"
          >
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M2.01 21L23 12L2.01 3L2 10L17 12L2 14L2.01 21Z" fill="currentColor" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  )
}

export default App
