// Single-page question form: posts to the FastAPI /query endpoint and shows the answer and its sources.
import { useState, type FormEvent } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// The fields of QueryResponse (app/main.py) this page shows.
type Source = { label: string; source_tier: string; url: string }
type Answer = { answer: string; sources: Source[] }

type State =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'answer'; reply: Answer }
  | { status: 'error' }

export default function App() {
  const [question, setQuestion] = useState('')
  const [state, setState] = useState<State>({ status: 'idle' })

  async function ask(event: FormEvent) {
    event.preventDefault()
    if (!question.trim()) return
    setState({ status: 'loading' })
    try {
      const response = await fetch(`${API_URL}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setState({ status: 'answer', reply: await response.json() })
    } catch {
      setState({ status: 'error' })
    }
  }

  return (
    <main>
      <h1>F-1 / OPT questions</h1>
      <form onSubmit={ask}>
        <label htmlFor="question">Question</label>
        <input id="question" value={question} onChange={(e) => setQuestion(e.target.value)} />
        <button type="submit" disabled={!question.trim() || state.status === 'loading'}>
          Ask
        </button>
      </form>

      {state.status === 'loading' && <p>Searching...</p>}
      {state.status === 'error' && <p role="alert">Something went wrong. Please try again.</p>}
      {state.status === 'answer' && (
        <>
          <p data-testid="answer" className="answer">
            {state.reply.answer}
          </p>
          {state.reply.sources.length > 0 && (
            <section>
              <h2>Sources</h2>
              <ol>
                {state.reply.sources.map((source) => (
                  <li key={source.label}>
                    <a href={source.url} target="_blank" rel="noopener">
                      {source.label}
                    </a>{' '}
                    <span className="tier">{source.source_tier}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </>
      )}
    </main>
  )
}
