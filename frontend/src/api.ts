import axios, { AxiosInstance } from 'axios'

const API_BASE_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

export class IntakeAPIClient {
  private apiClient: AxiosInstance

  constructor() {
    this.apiClient = axios.create({
      baseURL: `${API_BASE_URL}/api/intake`,
      headers: {
        'Content-Type': 'application/json',
      },
    })
  }

  /**
   * Create a new intake session
   */
  async createSession(userLanguage: string, userId?: string): Promise<{
    session_id: string
    ice_servers: Array<{ urls: string[] }>
  }> {
    const response = await this.apiClient.post('/sessions', {
      user_language: userLanguage,
      user_id: userId,
    })
    return response.data
  }

  /**
   * Send WebRTC offer (SDP)
   */
  async sendWebRTCOffer(sessionId: string, sdp: string): Promise<{ sdp: string }> {
    const response = await this.apiClient.post(`/sessions/${sessionId}/offer`, {
      sdp,
    })
    return response.data
  }

  /**
   * Send ICE candidates
   */
  async sendICECandidates(
    sessionId: string,
    candidates: Array<{
      candidate: string
      sdp_mid?: string
      sdp_mline_index?: number
    }>,
  ): Promise<{ ack: boolean }> {
    const response = await this.apiClient.post(
      `/sessions/${sessionId}/candidates`,
      { candidates },
    )
    return response.data
  }

  /**
   * Get current session state
   */
  async getSession(sessionId: string) {
    const response = await this.apiClient.get(`/sessions/${sessionId}`)
    return response.data
  }

  /**
   * Delete a session
   */
  async deleteSession(sessionId: string): Promise<{ deleted: boolean }> {
    const response = await this.apiClient.delete(`/sessions/${sessionId}`)
    return response.data
  }

  /**
   * Connect to WebSocket event stream
   */
  connectEventStream(
    sessionId: string,
    onMessage: (event: string, data: unknown) => void,
    onError: (error: Error) => void,
  ): WebSocket {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/intake/${sessionId}/events`

    const ws = new WebSocket(wsUrl)

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onMessage(data.type || 'unknown', data)
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err)
      }
    }

    ws.onerror = (event) => {
      onError(new Error(`WebSocket error: ${event}`))
    }

    return ws
  }
}

export const intakeAPI = new IntakeAPIClient()
