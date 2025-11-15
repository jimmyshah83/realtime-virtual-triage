import { create } from 'zustand'

export interface IntakeSession {
  sessionId: string
  userLanguage: string
  status: 'idle' | 'connecting' | 'active' | 'completed' | 'error'
  transcript: string
  extractedSymptoms: Record<string, unknown> | null
  errorMessage?: string
}

interface IntakeStore {
  session: IntakeSession | null
  setSession: (session: IntakeSession) => void
  updateSession: (updates: Partial<IntakeSession>) => void
  clearSession: () => void
}

export const useIntakeStore = create<IntakeStore>((set) => ({
  session: null,
  setSession: (session: IntakeSession) => set({ session }),
  updateSession: (updates: Partial<IntakeSession>) =>
    set((state) => ({
      session: state.session ? { ...state.session, ...updates } : null,
    })),
  clearSession: () => set({ session: null }),
}))
