import { useState, useRef, useEffect } from 'react'
import './App.css'

interface Message {
  id: number
  text: string
  sender: 'user' | 'bot'
  timestamp: Date
}

// Declare SpeechRecognition types
declare global {
  interface Window {
    SpeechRecognition: any
    webkitSpeechRecognition: any
  }
}

function App() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 1,
      text: "Hello! I'm your virtual health assistant. How can I help you today?",
      sender: 'bot',
      timestamp: new Date()
    }
  ])
  const [inputText, setInputText] = useState('')
  const [isRecording, setIsRecording] = useState(false)
  const recognitionRef = useRef<any>(null)

  const handleSendMessage = () => {
    if (inputText.trim()) {
      const newMessage: Message = {
        id: messages.length + 1,
        text: inputText,
        sender: 'user',
        timestamp: new Date()
      }
      setMessages([...messages, newMessage])
      setInputText('')
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  useEffect(() => {
    // Initialize speech recognition
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition()
      recognition.continuous = false
      recognition.interimResults = false
      recognition.lang = 'en-US'

      recognition.onstart = () => {
        console.log('Speech recognition started')
      }

      recognition.onresult = (event: any) => {
        const transcript = event.results[0][0].transcript
        console.log('Transcript:', transcript)
        setInputText(transcript)
        setIsRecording(false)
      }

      recognition.onerror = (event: any) => {
        console.error('Speech recognition error:', event.error)
        setIsRecording(false)
        
        if (event.error === 'not-allowed') {
          alert('Microphone access was denied. Please allow microphone access in your browser settings.')
        } else if (event.error === 'no-speech') {
          alert('No speech was detected. Please try again.')
        } else {
          alert(`Speech recognition error: ${event.error}`)
        }
      }

      recognition.onend = () => {
        console.log('Speech recognition ended')
        setIsRecording(false)
      }

      recognitionRef.current = recognition
    }

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop()
      }
    }
  }, [])

  const toggleRecording = async () => {
    if (!recognitionRef.current) {
      alert('Speech recognition is not supported in your browser. Please use Chrome, Edge, or Safari.')
      return
    }

    if (isRecording) {
      // Stop recording
      recognitionRef.current.stop()
      setIsRecording(false)
    } else {
      // Start recording
      try {
        // Request microphone permission
        await navigator.mediaDevices.getUserMedia({ audio: true })
        recognitionRef.current.start()
        setIsRecording(true)
      } catch (error) {
        console.error('Microphone access error:', error)
        alert('Unable to access microphone. Please ensure microphone permissions are granted.')
      }
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
              Online
            </p>
          </div>
        </div>
      </div>

      <div className="chat-messages">
        {messages.map((message) => (
          <div key={message.id} className={`message ${message.sender}`}>
            <div className="message-bubble">
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
