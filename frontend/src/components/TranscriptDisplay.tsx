import React, { useEffect, useRef } from 'react'
import './TranscriptDisplay.css'

interface TranscriptDisplayProps {
  transcript: string
  isLive?: boolean
  status?: string
}

export const TranscriptDisplay: React.FC<TranscriptDisplayProps> = ({
  transcript,
  isLive = false,
  status = 'idle',
}) => {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when transcript updates
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [transcript])

  return (
    <div className="transcript-display">
      <div className="transcript-header">
        <h3>Conversation Transcript</h3>
        {isLive && (
          <div className="live-indicator">
            <span className="dot"></span>
            <span>Live</span>
          </div>
        )}
      </div>

      <div className="transcript-body" ref={scrollRef}>
        {transcript ? (
          <p className="transcript-text">{transcript}</p>
        ) : (
          <p className="transcript-placeholder">Transcript will appear here...</p>
        )}
      </div>

      <div className="transcript-footer">
        <span className={`status-badge status-${status}`}>{status}</span>
      </div>
    </div>
  )
}
