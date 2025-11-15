import React, { useState, useEffect } from 'react'
import './App.css'
import { IntakeForm } from './components/IntakeForm'
import { TranscriptDisplay } from './components/TranscriptDisplay'
import { useIntakeStore } from './store'
import { WebRTCManager } from './webrtc'

export default function App() {
  const [selectedLanguage, setSelectedLanguage] = useState('en')
  const [isConnecting, setIsConnecting] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [webrtcManager] = useState(() => new WebRTCManager())

  const { session, setSession, updateSession } = useIntakeStore()

  const handleLanguageSelect = (language: string) => {
    setSelectedLanguage(language)
  }

  const handleStartClick = async () => {
    setIsConnecting(true)
    setError(null)
    setTranscript('')

    try {
      // TODO: Call backend to create session
      // const response = await intakeAPI.createSession(selectedLanguage)
      // setSession({
      //   sessionId: response.session_id,
      //   userLanguage: selectedLanguage,
      //   status: 'connecting',
      //   transcript: '',
      //   extractedSymptoms: null,
      // })

      // // Initialize WebRTC
      // await webrtcManager.connect({
      //   iceServers: response.ice_servers,
      // })

      // // Set up event handlers
      // webrtcManager.onTranscript((chunk) => {
      //   setTranscript((prev) => prev + chunk)
      //   updateSession({ transcript: transcript + chunk })
      // })

      // webrtcManager.onStatus((status) => {
      //   updateSession({ status: status as any })
      // })

      // webrtcManager.onErr((err) => {
      //   setError(err.message)
      //   updateSession({ status: 'error', errorMessage: err.message })
      // })

      // // Start microphone capture
      // await webrtcManager.startMicrophoneCapture()

      console.log('Starting intake session for language:', selectedLanguage)
      setSession({
        sessionId: 'demo-session-123',
        userLanguage: selectedLanguage,
        status: 'active',
        transcript: 'Initializing conversation...',
        extractedSymptoms: null,
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(message)
      console.error('Failed to start session:', err)
    } finally {
      setIsConnecting(false)
    }
  }

  const handleEndClick = async () => {
    try {
      await webrtcManager.disconnect()
      setSession({
        ...session!,
        status: 'completed',
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(message)
      console.error('Failed to end session:', err)
    }
  }

  const handleReset = () => {
    setTranscript('')
    setError(null)
    setSelectedLanguage('en')
    useIntakeStore.setState({ session: null })
  }

  // Show form or active session
  if (!session) {
    return (
      <div className="app">
        <IntakeForm
          onLanguageSelect={handleLanguageSelect}
          onStartClick={handleStartClick}
          isLoading={isConnecting}
        />
        {error && <div className="error-message">{error}</div>}
      </div>
    )
  }

  return (
    <div className="app active-session">
      <div className="session-container">
        <header className="session-header">
          <h2>Intake Session</h2>
          <div className="session-meta">
            <span>Language: {session.userLanguage.toUpperCase()}</span>
            <span>Session ID: {session.sessionId.slice(0, 8)}</span>
          </div>
        </header>

        <div className="session-content">
          <TranscriptDisplay
            transcript={transcript || session.transcript}
            isLive={session.status === 'active'}
            status={session.status}
          />

          {session.extractedSymptoms && (
            <div className="symptoms-panel">
              <h3>Extracted Symptoms</h3>
              <pre>{JSON.stringify(session.extractedSymptoms, null, 2)}</pre>
            </div>
          )}
        </div>

        <footer className="session-footer">
          {session.status === 'active' && (
            <button className="end-button" onClick={handleEndClick}>
              End Conversation
            </button>
          )}
          <button className="reset-button" onClick={handleReset}>
            Start Over
          </button>
        </footer>

        {error && <div className="error-message">{error}</div>}
      </div>
    </div>
  )
}
