import { useState, useRef, useEffect } from 'react'
import './App.css'

interface Message {
  id: number
  text: string
  sender: 'user' | 'bot'
  timestamp: Date
  agent?: 'intake' | 'clinical-guidance' | 'access' | 'pre-visit' | 'coverage'
}

interface RealtimeEvent {
  type: string
  [key: string]: any
}

function App() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 1,
      text: "Hello! I'm your virtual health assistant. How can I help you today?",
      sender: 'bot',
      timestamp: new Date(),
      agent: 'intake'
    }
  ])
  const [inputText, setInputText] = useState('')
  const [isRecording, setIsRecording] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [currentAgent, setCurrentAgent] = useState<'intake' | 'clinical-guidance' | 'access' | 'pre-visit' | 'coverage'>('intake')
  const [sessionId, setSessionId] = useState<string | null>(null)
  
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
      
      const responseData = await sessionResponse.json()

      setCurrentAgent(responseData.current_agent)

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

      const sessionData = await sessionResponse.json()
      const ephemeralKey = sessionData.client_secret?.value
      const newSessionId = sessionData.id

      setSessionId(newSessionId)
      
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
            case 'conversation.item.input_audio_transcription.completed':
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

  const getAgentLabel = (agent: string) => {
    switch (agent) {
      case 'intake':
        return '👨‍⚕️ Intake Nurse'
      case 'clinical-guidance':
        return '🩺 Clinical Specialist'
      case 'access':
        return '🏥 Access Coordinator'
      case 'pre-visit':
        return '📋 Pre-Visit Assistant'
      case 'coverage':
        return '💳 Coverage Specialist'
      default:
        return '🤖 Assistant'
    }
  }

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
          </div>
        </div>
      </div>

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
