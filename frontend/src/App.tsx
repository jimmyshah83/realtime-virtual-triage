import { useState, useRef, useEffect } from 'react'
import './App.css'

type AgentRole = 'triage' | 'referral_builder'
type AgentStageStatus = 'waiting' | 'pending' | 'active' | 'complete'

interface TriageSummary {
  urgency: number
  redFlags: string[]
  symptoms: string[]
  chiefComplaint: string
  assessment: string
  medicalCodes: MedicalCodes | null
}

interface Message {
  id: number
  text: string
  sender: 'user' | 'bot'
  timestamp: Date
  agent?: AgentRole
}

interface RealtimeEvent {
  type: string
  [key: string]: unknown
}

interface MedicalCodes {
  snomed_codes?: string[]
  icd_codes?: string[]
}

interface PatientInfo {
  name?: string | null
  age?: number | null
  gender?: string | null
  contact?: string | null
  medical_history?: string[]
  medications?: string[]
  allergies?: string[]
}

interface ChatResponsePayload {
  current_agent: AgentRole
  response: string
  urgency: number
  red_flags: string[]
  handoff_ready: boolean
  referral_complete: boolean
  symptoms: string[]
  chief_complaint?: string | null
  assessment?: string | null
  medical_codes?: MedicalCodes | null
  patient_info?: PatientInfo | null
}

interface SessionResponsePayload {
  session_id: string
  client_secret: { value: string }
  model: string
  voice: string
  session_ttl_seconds: number
}

function App() {
  const createIntroMessage = (): Message => ({
    id: 1,
    text: "Hello! I'm your virtual triage nurse. Tell me what's going on so I can assess your symptoms.",
    sender: 'bot',
    timestamp: new Date(),
    agent: 'triage'
  })

  const createInitialTriageSummary = (): TriageSummary => ({
    urgency: 0,
    redFlags: [],
    symptoms: [],
    chiefComplaint: '',
    assessment: '',
    medicalCodes: null
  })

  const [messages, setMessages] = useState<Message[]>([createIntroMessage()])
  const [inputText, setInputText] = useState('')
  const [isRecording, setIsRecording] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [currentAgent, setCurrentAgent] = useState<AgentRole>('triage')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [triageSummary, setTriageSummary] = useState<TriageSummary>(createInitialTriageSummary())
  const [handoffReady, setHandoffReady] = useState(false)
  const [referralComplete, setReferralComplete] = useState(false)
  const [patientInfo, setPatientInfo] = useState<PatientInfo | null>(null)
  const [sessionMeta, setSessionMeta] = useState<{ model: string; voice: string; ttl: number } | null>(null)

  const peerConnectionRef = useRef<RTCPeerConnection | null>(null)
  const audioElementRef = useRef<HTMLAudioElement | null>(null)
  const dataChannelRef = useRef<RTCDataChannel | null>(null)

  const handleSendMessage = async () => {
    if (inputText.trim()) {
      setMessages(prev => {
        const newMessage: Message = {
          id: prev.length + 1,
          text: inputText,
          sender: 'user',
          timestamp: new Date()
        }
        return [...prev, newMessage]
      })
      
      const messageText = inputText
      setInputText('')
      
      if (sessionId) {
        await processWithAgents(messageText)
      }
    }
  }

  const processWithAgents = async (userInput: string) => {
    try {
      const sessionResponse = await fetch(`http://localhost:8000/chat/${sessionId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({message: userInput})
      })
      
      if (!sessionResponse.ok) {
        throw new Error(`Failed to process message with agents: ${sessionResponse.statusText}`)
      }
      
      const responseData: ChatResponsePayload = await sessionResponse.json()

      setCurrentAgent(responseData.current_agent)
      setTriageSummary({
        urgency: responseData.urgency ?? 0,
        redFlags: responseData.red_flags ?? [],
        symptoms: responseData.symptoms ?? [],
        chiefComplaint: responseData.chief_complaint ?? '',
        assessment: responseData.assessment ?? '',
        medicalCodes: responseData.medical_codes ?? null
      })
      setHandoffReady(Boolean(responseData.handoff_ready))
      setReferralComplete(Boolean(responseData.referral_complete))
      setPatientInfo(responseData.patient_info ?? null)

      setMessages(prev => {
        const agentMessage: Message = {
          id: prev.length + 1,
          text: responseData.response,
          sender: 'bot',
          timestamp: new Date(),
          agent: responseData.current_agent
        }
        return [...prev, agentMessage]
      })

      if (dataChannelRef.current && dataChannelRef.current.readyState === 'open') {
        const responseEvent: RealtimeEvent = {
          type: 'conversation.item.create',
          item: {
            type: 'message',
            role: 'assistant',
            content: [{
              type: 'text',
              text: responseData.response,
            }]
          }
        }

        dataChannelRef.current.send(JSON.stringify(responseEvent))

        const generateEvent: RealtimeEvent = {
          type: 'response.create',
        }

        dataChannelRef.current.send(JSON.stringify(generateEvent))
      }
    }
    catch (error) {
      console.error('Error processing message with agents:', error)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  useEffect(() => {
    return () => {
      // Cleanup on unmount
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
    setTriageSummary(createInitialTriageSummary())
    setPatientInfo(null)
    setHandoffReady(false)
    setReferralComplete(false)
    setCurrentAgent('triage')
  }

  const startRealtimeSession = async () => {
    try {
      setIsRecording(true)

      const sessionResponse = await fetch('http://localhost:8000/session', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      })

      if (!sessionResponse.ok) {
        throw new Error(`Failed to create session: ${sessionResponse.statusText}`)
      }

      const sessionData: SessionResponsePayload = await sessionResponse.json()
      const ephemeralKey = sessionData.client_secret?.value
      const newSessionId = sessionData.session_id

      if (!ephemeralKey || !newSessionId) {
        throw new Error('Session response missing credentials')
      }

      resetConversationState()
      setSessionId(newSessionId)
      setSessionMeta({ model: sessionData.model, voice: sessionData.voice, ttl: sessionData.session_ttl_seconds })
      
      // Create a peer connection
      const pc = new RTCPeerConnection()
      peerConnectionRef.current = pc

      // Set up to play remote audio from the model
      audioElementRef.current = document.createElement('audio')
      audioElementRef.current.autoplay = true
      pc.ontrack = (e) => {
        if (audioElementRef.current) {
          audioElementRef.current.srcObject = e.streams[0]
        }
      }

      // Add local audio track for microphone input in the browser
      const ms = await navigator.mediaDevices.getUserMedia({
        audio: true,
      })
      pc.addTrack(ms.getTracks()[0])

      // Set up data channel for sending and receiving events
      const dc = pc.createDataChannel('realtime-channel')
      dataChannelRef.current = dc

      dc.onopen = () => {
        console.log('Data channel opened')
        setIsConnected(true)

      const sessionUpdate: RealtimeEvent = {
        type: 'session.update',
        session: {
          turn_detection: {
            type: 'server_vad',
            threshold: 0.5,
            prefix_padding_ms: 300,
            silence_duration_ms: 500
          }, 
          input_audio_transcription: {
            model: 'whisper-1', 
          },
        }
      }
      dc.send(JSON.stringify(sessionUpdate))
        
      }

      dc.onmessage = async (event) => {
        console.log('Received realtime event:', event.data)
        // Handle events from the realtime API
        try {
          const realtimeEvent: RealtimeEvent = JSON.parse(event.data)
          console.log('Parsed event type:', realtimeEvent.type)

          // You can handle different message types here
          switch (realtimeEvent.type) {
            case 'conversation.item.input_audio_transcription.completed': {
              if (typeof realtimeEvent.transcript !== 'string') {
                break
              }

              const transcript = realtimeEvent.transcript
              console.log('Transcription completed:', transcript)

              setMessages(prev => {
                const userMessage: Message = {
                  id: prev.length + 1,
                  text: transcript,
                  sender: 'user',
                  timestamp: new Date()
                }
                return [...prev, userMessage]
              })

              await processWithAgents(transcript)
              break
            }
            case 'response.done':
              console.log('Response generation completed')
              break

            case 'response.error':
              console.error('Error during response generation:', realtimeEvent.error)
              break

            default:
              console.log('Unhandled event type:', realtimeEvent.type)
              break
            }
          }
        catch (err) {
          console.error('Error parsing message:', err)
        }
      }

      dc.onclose = () => {
        console.log('Data channel closed')
        setIsConnected(false)
        setIsRecording(false)
      }

      // Start the session using the Session Description Protocol (SDP)
      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)

      // Connect to realtime API with ephemeral key
      const region = 'eastus2'
      const deployment = 'gpt-realtime'
      const url = `https://${region}.realtimeapi-preview.ai.azure.com/v1/realtimertc?model=${deployment}&api-version=2025-08-28`

      const sdpResponse = await fetch(url, {
        method: 'POST',
        body: offer.sdp,
        headers: {
          'Authorization': `Bearer ${ephemeralKey}`,
          'Content-Type': 'application/sdp',
        },
      })

      if (!sdpResponse.ok) {
        throw new Error(`Failed to create session: ${sdpResponse.statusText}`)
      }

      const answerSdp = await sdpResponse.text()
      const answer: RTCSessionDescriptionInit = {
        type: 'answer',
        sdp: answerSdp,
      }
      await pc.setRemoteDescription(answer)

      console.log('Realtime session started successfully')
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
    console.log('Realtime session stopped')
  }

  const toggleRecording = async () => {
    if (isRecording) {
      stopRealtimeSession()
    } else {
      await startRealtimeSession()
    }
  }

  const getAgentLabel = (agent: AgentRole) => {
    switch (agent) {
      case 'triage':
        return '🩺 Triage Nurse'
      case 'referral_builder':
        return '📨 Referral Coordinator'
      default:
        return '🤖 Assistant'
    }
  }

  const getStageStatus = (agent: AgentRole): AgentStageStatus => {
    if (agent === 'triage') {
      if (handoffReady || referralComplete) {
        return 'complete'
      }
      return currentAgent === 'triage' ? 'active' : 'pending'
    }

    if (referralComplete) {
      return 'complete'
    }

    if (!handoffReady) {
      return 'waiting'
    }

    return currentAgent === 'referral_builder' ? 'active' : 'pending'
  }

  const statusLabels: Record<AgentStageStatus, string> = {
    waiting: 'Waiting',
    pending: 'Ready',
    active: 'Active',
    complete: 'Complete'
  }

  const agentStages = [
    {
      id: 'triage' as AgentRole,
      title: 'Triage Nurse',
      icon: '🩺',
      description: 'Collects symptoms, red flags, and urgency.',
      helper: handoffReady ? 'Assessment locked in for referral.' : 'Gathering clinical details.',
      status: getStageStatus('triage')
    },
    {
      id: 'referral_builder' as AgentRole,
      title: 'Referral Coordinator',
      icon: '📨',
      description: 'Builds the referral package for providers.',
      helper: referralComplete
        ? 'Referral package ready to share.'
        : handoffReady
          ? 'Preparing referral summary now.'
          : 'Waiting for triage handoff.',
      status: getStageStatus('referral_builder')
    }
  ]

  return (
    <div className="chat-container">
      <div className="chat-header">
        <div className="header-content">
          <div className="avatar">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 5C13.66 5 15 6.34 15 8C15 9.66 13.66 11 12 11C10.34 11 9 9.66 9 8C9 6.34 10.34 5 12 5ZM12 19.2C9.5 19.2 7.29 17.92 6 15.98C6.03 13.99 10 12.9 12 12.9C13.99 12.9 17.97 13.99 18 15.98C16.71 17.92 14.5 19.2 12 19.2Z" fill="currentColor"/>
            </svg>
          </div>
          <div className="header-text">
            <h1>Virtual Health Assistant</h1>
            <p className="status">
              <span className="status-dot"></span>
              {isConnected ? `Connected - ${getAgentLabel(currentAgent)}` : 'Offline'}
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
                  <div className="agent-icon" aria-hidden="true">{stage.icon}</div>
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

      {(triageSummary.urgency > 0 || triageSummary.redFlags.length > 0 || triageSummary.symptoms.length > 0) && (
        <div className="triage-summary">
          <div>
            <strong>Urgency:</strong> {triageSummary.urgency ? `${triageSummary.urgency}/5` : 'Evaluating'}
          </div>
          {triageSummary.redFlags.length > 0 && (
            <div className="red-flags">
              <strong>⚠️ Red Flags:</strong> {triageSummary.redFlags.join(', ')}
            </div>
          )}
          {triageSummary.symptoms.length > 0 && (
            <div>
              <strong>Symptoms:</strong> {triageSummary.symptoms.join(', ')}
            </div>
          )}
          {triageSummary.chiefComplaint && (
            <div>
              <strong>Chief Complaint:</strong> {triageSummary.chiefComplaint}
            </div>
          )}
          {triageSummary.assessment && (
            <div>
              <strong>Assessment:</strong> {triageSummary.assessment}
            </div>
          )}
          {patientInfo && (patientInfo.name || patientInfo.age || patientInfo.gender) && (
            <div>
              <strong>Patient:</strong> {[patientInfo.name, patientInfo.age ? `${patientInfo.age}y` : null, patientInfo.gender]
                .filter(Boolean)
                .join(' • ')}
            </div>
          )}
          {triageSummary.medicalCodes && (
            (triageSummary.medicalCodes.snomed_codes?.length || triageSummary.medicalCodes.icd_codes?.length) ? (
              <div className="medical-codes">
                {triageSummary.medicalCodes.snomed_codes?.length ? (
                  <div><strong>SNOMED:</strong> {triageSummary.medicalCodes.snomed_codes.join(', ')}</div>
                ) : null}
                {triageSummary.medicalCodes.icd_codes?.length ? (
                  <div><strong>ICD-10:</strong> {triageSummary.medicalCodes.icd_codes.join(', ')}</div>
                ) : null}
              </div>
            ) : null
          )}
          {handoffReady && !referralComplete && (
            <div className="handoff-note">
              <strong>Next:</strong> Referral coordinator is preparing your package.
            </div>
          )}
          {referralComplete && (
            <div className="handoff-note success">
              <strong>Referral Ready:</strong> Package completed for provider handoff.
            </div>
          )}
        </div>
      )}

      <div className="chat-messages">
        {messages.map((message) => (
          <div key={message.id} className={`message ${message.sender}`}>
            <div className="message-bubble">
              {message.agent && (
                <div className="agent-badge">
                  {getAgentLabel(message.agent)}
                </div>
              )}
              <p>{message.text}</p>
              <span className="message-time">
                {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          </div>
        ))}
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
          />
          <button 
            className={`mic-button ${isRecording ? 'recording' : ''}`}
            onClick={toggleRecording}
            aria-label="Voice input"
          >
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 14C13.66 14 15 12.66 15 11V5C15 3.34 13.66 2 12 2C10.34 2 9 3.34 9 5V11C9 12.66 10.34 14 12 14Z" fill="currentColor"/>
              <path d="M17 11C17 13.76 14.76 16 12 16C9.24 16 7 13.76 7 11H5C5 14.53 7.61 17.43 11 17.92V21H13V17.92C16.39 17.43 19 14.53 19 11H17Z" fill="currentColor"/>
            </svg>
          </button>
          <button 
            className="send-button"
            onClick={handleSendMessage}
            disabled={!inputText.trim()}
            aria-label="Send message"
          >
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M2.01 21L23 12L2.01 3L2 10L17 12L2 14L2.01 21Z" fill="currentColor"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  )
}

export default App
