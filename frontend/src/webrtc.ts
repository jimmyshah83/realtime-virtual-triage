/**
 * WebRTC Connection Manager
 *
 * Handles peer connection establishment, audio stream management,
 * and real-time communication with the backend.
 */

export interface WebRTCConfig {
  iceServers: Array<{ urls: string[] }>
}

export class WebRTCManager {
  private peerConnection: RTCPeerConnection | null = null
  private dataChannel: RTCDataChannel | null = null
  private audioTrack: MediaStreamTrack | null = null
  private onTranscriptChunk?: (chunk: string) => void
  private onStatusUpdate?: (status: string) => void
  private onError?: (error: Error) => void

  /**
   * Initialize and establish peer connection
   */
  async connect(config: WebRTCConfig): Promise<void> {
    try {
      // Create peer connection with STUN/TURN servers
      this.peerConnection = new RTCPeerConnection({
        iceServers: config.iceServers,
      })

      // Set up event handlers
      this.peerConnection.onicecandidate = (event) => {
        if (event.candidate) {
          console.log('New ICE candidate:', event.candidate)
          // TODO: Send ICE candidate to backend
        }
      }

      this.peerConnection.onconnectionstatechange = () => {
        const state = this.peerConnection?.connectionState
        console.log('Connection state:', state)
        this.onStatusUpdate?.(state || 'unknown')
      }

      this.peerConnection.ondatachannel = (event) => {
        this.dataChannel = event.channel
        this.setupDataChannel()
      }

      console.log('WebRTC peer connection initialized')
    } catch (error) {
      this.onError?.(new Error(`Failed to initialize WebRTC: ${error}`))
      throw error
    }
  }

  /**
   * Start capturing microphone audio
   */
  async startMicrophoneCapture(): Promise<MediaStream> {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })

      // Add audio track to peer connection
      for (const track of stream.getAudioTracks()) {
        this.audioTrack = track
        this.peerConnection?.addTrack(track, stream)
      }

      console.log('Microphone capture started')
      return stream
    } catch (error) {
      this.onError?.(new Error(`Failed to access microphone: ${error}`))
      throw error
    }
  }

  /**
   * Stop microphone capture and close peer connection
   */
  async disconnect(): Promise<void> {
    if (this.audioTrack) {
      this.audioTrack.stop()
    }

    if (this.dataChannel) {
      this.dataChannel.close()
    }

    if (this.peerConnection) {
      this.peerConnection.close()
      this.peerConnection = null
    }

    console.log('WebRTC connection closed')
  }

  /**
   * Send an offer to the backend
   */
  async createAndSendOffer(): Promise<RTCSessionDescriptionInit> {
    if (!this.peerConnection) {
      throw new Error('Peer connection not initialized')
    }

    const offer = await this.peerConnection.createOffer()
    await this.peerConnection.setLocalDescription(offer)

    return offer
  }

  /**
   * Receive and set remote description (answer from backend)
   */
  async handleAnswer(answer: RTCSessionDescriptionInit): Promise<void> {
    if (!this.peerConnection) {
      throw new Error('Peer connection not initialized')
    }

    await this.peerConnection.setRemoteDescription(new RTCSessionDescription(answer))
  }

  /**
   * Add ICE candidate from backend
   */
  async addICECandidate(candidate: RTCIceCandidate): Promise<void> {
    if (!this.peerConnection) {
      throw new Error('Peer connection not initialized')
    }

    await this.peerConnection.addIceCandidate(candidate)
  }

  /**
   * Set up data channel for real-time transcript and events
   */
  private setupDataChannel(): void {
    if (!this.dataChannel) return

    this.dataChannel.onopen = () => {
      console.log('Data channel opened')
      this.onStatusUpdate?.('data_channel_open')
    }

    this.dataChannel.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'transcript_chunk') {
          this.onTranscriptChunk?.(data.chunk)
        } else if (data.type === 'status_update') {
          this.onStatusUpdate?.(data.status)
        }
      } catch (error) {
        console.error('Failed to parse data channel message:', error)
      }
    }

    this.dataChannel.onerror = (error) => {
      this.onError?.(new Error(`Data channel error: ${error}`))
    }

    this.dataChannel.onclose = () => {
      console.log('Data channel closed')
    }
  }

  /**
   * Register callback for transcript chunks
   */
  onTranscript(callback: (chunk: string) => void): void {
    this.onTranscriptChunk = callback
  }

  /**
   * Register callback for status updates
   */
  onStatus(callback: (status: string) => void): void {
    this.onStatusUpdate = callback
  }

  /**
   * Register callback for errors
   */
  onErr(callback: (error: Error) => void): void {
    this.onError = callback
  }

  /**
   * Get connection state
   */
  getConnectionState(): RTCPeerConnectionState | undefined {
    return this.peerConnection?.connectionState
  }
}
