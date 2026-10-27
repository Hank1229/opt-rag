// Single-page question form: posts to the FastAPI /query endpoint and shows the answer and its sources.
import { useEffect, useRef, useState, type FormEvent } from 'react'
import Markdown, { type Components } from 'react-markdown'
import remarkBreaks from 'remark-breaks'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// The fields of QueryResponse (app/main.py) this page shows.
type Source = { label: string; source_tier: string; url: string }
type Answer = { answer: string; sources: Source[] }

type State =
  | { status: 'idle' }
  | { status: 'loading'; waking: boolean }
  | { status: 'answer'; reply: Answer }
  | { status: 'error' }

// Same grammar as LABEL in app/evals/metrics.py, so the page and the eval agree on what is cited.
const LABEL = /\[(\d+(?:\s*,\s*\d+)*)\]/g

// Source numbers the answer cites as [n] or [n, m], 1-based like the source labels.
function citedNumbers(answer: string) {
  return new Set([...answer.matchAll(LABEL)].flatMap((match) => match[1].split(',').map(Number)))
}

// The answer is model output: links leave in a new tab, and images (dropped below) never load outside URLs.
const answerComponents: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
}

export default function App() {
  const [question, setQuestion] = useState('')
  const [state, setState] = useState<State>({ status: 'idle' })
  const warm = useRef(false)

  // The backend scales to zero; start its cold start while the user is still typing.
  // A failed ping also counts as settled: the server is not waking, and /query reports its own error.
  useEffect(() => {
    fetch(`${API_URL}/health`)
      .catch(() => {})
      .finally(() => (warm.current = true))
  }, [])

  async function ask(event: FormEvent) {
    event.preventDefault()
    if (!question.trim()) return
    setState({ status: 'loading', waking: !warm.current })
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
          {state.waking && <p>Waking up the server, the first answer can take about 10 s.</p>}
        </>
      )}
      {state.status === 'error' && <p role="alert">Something went wrong. Please try again.</p>}
      {state.status === 'answer' && (
        <>
          <div data-testid="answer">
            <Markdown remarkPlugins={[remarkBreaks]} components={answerComponents} disallowedElements={['img']}>
              {state.reply.answer}
            </Markdown>
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
