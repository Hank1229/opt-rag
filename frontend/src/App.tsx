// Single-page question form: posts to the FastAPI /query endpoint and shows the answer and its sources.
import { useEffect, useState, type FormEvent } from 'react'
import Markdown from 'react-markdown'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// The fields of QueryResponse (app/main.py) this page shows.
type Source = { label: string; source_tier: string; url: string }
type Answer = { answer: string; sources: Source[] }

type State =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'answer'; reply: Answer }
  | { status: 'error' }

// Source numbers the answer cites as [n], 1-based like the source labels.
function citedNumbers(answer: string) {
  return new Set([...answer.matchAll(/\[(\d+)\]/g)].map((match) => Number(match[1])))
}

export default function App() {
  const [question, setQuestion] = useState('')
  const [state, setState] = useState<State>({ status: 'idle' })
  const [slow, setSlow] = useState(false)

  // The backend scales to zero; start its cold start while the user is still typing.
  useEffect(() => {
    fetch(`${API_URL}/health`).catch(() => {})
  }, [])

  useEffect(() => {
    if (state.status !== 'loading') return
    const timer = setTimeout(() => setSlow(true), 3000)
    return () => {
      clearTimeout(timer)
      setSlow(false)
    }
  }, [state.status])

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

      {state.status === 'loading' && (
        <>
          <p>Searching the regulations...</p>
          {slow && <p>Waking up the server, the first request can take about 5 s.</p>}
        </>
      )}
      {state.status === 'error' && <p role="alert">Something went wrong. Please try again.</p>}
      {state.status === 'answer' && (
        <>
          <div data-testid="answer" className="answer">
            <Markdown>{state.reply.answer}</Markdown>
          </div>
          {state.reply.sources.length > 0 && (
            <Sources sources={state.reply.sources} cited={citedNumbers(state.reply.answer)} />
          )}
        </>
      )}
    </main>
  )
}

function Sources({ sources, cited }: { sources: Source[]; cited: Set<number> }) {
  return (
    <section className="sources">
      <h2>Sources</h2>
      <ol>
        {sources.map((source, i) => (
          <li key={source.label}>
            <a href={source.url} target="_blank" rel="noopener">
              {source.label}
            </a>{' '}
            <span className="tier">{source.source_tier}</span>{' '}
            {cited.has(i + 1) ? (
              <span className="citation cited">cited</span>
            ) : (
              <span className="citation">retrieved, not cited</span>
            )}
          </li>
        ))}
      </ol>
    </section>
  )
}
