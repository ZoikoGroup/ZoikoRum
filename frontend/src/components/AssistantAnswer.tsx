import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Icon } from './dashboard'

export interface AssistantReply {
  answerId: string
  intent: string
  answer: string
  sections: { title: string; items: string[] }[]
  suggestions: string[]
  limitations: string
  related: { label: string; to: string }[]
  disclaimer: string
  fallbackUsed: boolean
  model: string
}

const DEFAULT_SUGGESTIONS = ['How do I find the right professional?', 'How are payments protected?']

/** One structured assistant answer: direct answer, key points, safe links, follow-ups and feedback. */
export default function AssistantAnswer({ reply, onSuggest, onNavigate }: {
  reply: AssistantReply
  onSuggest: (suggestion: string) => void
  onNavigate?: () => void
}) {
  const [feedback, setFeedback] = useState<'idle' | 'sending' | 'done' | 'error'>('idle')
  const suggestions = reply.suggestions.length ? reply.suggestions : DEFAULT_SUGGESTIONS
  const canFeedback = reply.answerId !== 'welcome'

  async function sendFeedback(rating: 'HELPFUL' | 'NOT_HELPFUL') {
    setFeedback('sending')
    try {
      await api(`/v1/ai/chat/${reply.answerId}/feedback`, { method: 'POST', body: { rating } })
      setFeedback('done')
    } catch {
      setFeedback('error')
    }
  }

  return (
    <div className="assistant-answer">
      <p className="assistant-lead">{reply.answer}</p>
      {reply.sections.map((section) => (
        <div key={section.title} className="assistant-section">
          <h4>{section.title}</h4>
          <ul>{section.items.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      ))}
      {reply.related.length > 0 && (
        <div className="assistant-related">
          {reply.related.map((page) => (
            <Link key={page.to} to={page.to} onClick={onNavigate}>{page.label}<Icon name="arrow" /></Link>
          ))}
        </div>
      )}
      <p className="assistant-limitations">{reply.limitations}</p>
      {reply.fallbackUsed && <p className="assistant-note">Offline guidance: the AI model was unavailable.</p>}
      <div className="assistant-chips">
        {suggestions.map((suggestion) => (
          <button key={suggestion} type="button" onClick={() => onSuggest(suggestion)}>{suggestion}</button>
        ))}
      </div>
      {canFeedback && (
        <div className="assistant-feedback" aria-live="polite">
          {feedback === 'done' ? <span>Thanks. Your feedback helps us improve public information.</span>
            : feedback === 'error' ? (
              <>
                <span>Your feedback was not saved.</span>
                <button type="button" onClick={() => setFeedback('idle')}>Try again</button>
              </>
            ) : (
              <>
                <span>{feedback === 'sending' ? 'Saving feedback…' : 'Was this helpful?'}</span>
                <button type="button" disabled={feedback === 'sending'} onClick={() => void sendFeedback('HELPFUL')}>Yes</button>
                <button type="button" disabled={feedback === 'sending'} onClick={() => void sendFeedback('NOT_HELPFUL')}>Not really</button>
              </>
            )}
        </div>
      )}
    </div>
  )
}
