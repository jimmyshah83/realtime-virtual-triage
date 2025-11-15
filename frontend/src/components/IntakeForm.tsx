import React, { useState } from 'react'
import './IntakeForm.css'

interface IntakeFormProps {
  onLanguageSelect: (language: string) => void
  onStartClick: () => void
  isLoading?: boolean
}

export const IntakeForm: React.FC<IntakeFormProps> = ({
  onLanguageSelect,
  onStartClick,
  isLoading = false,
}) => {
  const [selectedLanguage, setSelectedLanguage] = useState('en')

  const languages = [
    { code: 'en', name: 'English' },
    { code: 'es', name: 'Español' },
    { code: 'fr', name: 'Français' },
    { code: 'zh', name: '中文' },
    { code: 'ar', name: 'العربية' },
    { code: 'hi', name: 'हिन्दी' },
  ]

  const handleLanguageChange = (code: string) => {
    setSelectedLanguage(code)
    onLanguageSelect(code)
  }

  return (
    <div className="intake-form">
      <h1>Virtual Triage Intake</h1>
      <p className="subtitle">
        Tell us about your symptoms in the language you're most comfortable with.
      </p>

      <div className="language-selector">
        <label htmlFor="language">Select Language:</label>
        <select
          id="language"
          value={selectedLanguage}
          onChange={(e) => handleLanguageChange(e.target.value)}
          disabled={isLoading}
        >
          {languages.map((lang) => (
            <option key={lang.code} value={lang.code}>
              {lang.name}
            </option>
          ))}
        </select>
      </div>

      <div className="button-group">
        <button
          className="start-button"
          onClick={onStartClick}
          disabled={isLoading}
        >
          {isLoading ? 'Starting...' : 'Start Conversation'}
        </button>
      </div>
    </div>
  )
}
