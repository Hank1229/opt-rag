// Single-page question form: posts to the FastAPI /query endpoint and shows the answer and its sources.
import { useEffect, useRef, useState, type FormEvent } from 'react'
import Markdown, { type Components } from 'react-markdown'
import remarkBreaks from 'remark-breaks'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// The fields of QueryResponse (app/main.py) this page shows.
type Source = { label: string; title?: string; source_tier: string; url: string }
type Answer = { answer: string; sources: Source[] }

type State =
  | { status: 'idle' }
  | { status: 'loading'; waking: boolean; asked: string }
  | { status: 'answer'; reply: Answer; asked: string }
  | { status: 'error'; asked: string }

const EXAMPLE_QUESTIONS = [
  "How long do I need to study full-time before I'm eligible for OPT?",
  "I'm on OPT. How recent does the travel signature on my I-20 need to be when I re-enter the U.S.?",
  "I'm on OPT based on a non-STEM degree, but I earned a STEM degree before that. Can I use my earlier degree to apply for a STEM OPT extension, and what requirements would my earlier degree and current job need to meet?",
]
const TIER_NAMES: Record<string, string> = { ecfr: 'eCFR', sits: 'Study in the States' }
const INTRO = 'Answers from 8 CFR 214.2(f) and Study in the States, with sources. Pick an example or type your own.'
// Source urls come from the backend; anything but http(s) (e.g. javascript:) is shown as plain text.
const HTTP_URL = /^https?:\/\//i
// Opening words of REFUSAL in app/generation.py; the backend sends sources=[] when nothing was retrieved.
const REFUSAL_PREFIX = 'The provided sources do not contain the answer'

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

  function submit(event: FormEvent) {
    event.preventDefault()
    void ask()
  }

  // Fills the input as if typed, then asks, so an example takes the same path as typing and pressing Ask.
  function askExample(example: string) {
    setQuestion(example)
    void ask(example)
  }

  // Try again passes the heading's question, so editing the input after an error does not change the resend.
  async function ask(text = question) {
    const asked = text.trim()
    if (!asked) return
    setState({ status: 'loading', waking: !warm.current, asked })
    try {
      const response = await fetch(`${API_URL}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: asked }),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setState({ status: 'answer', reply: await response.json(), asked })
    } catch {
      setState({ status: 'error', asked })
    }
  }

  return (
    <main>
      <h1 className="site-name">F-1 / OPT questions</h1>
      {state.status === 'idle' && <p className="intro">{INTRO}</p>}
      <form onSubmit={submit}>
        <label htmlFor="question">Question</label>
        <input id="question" value={question} onChange={(e) => setQuestion(e.target.value)} />
        <button type="submit" disabled={!question.trim() || state.status === 'loading'}>
          Ask
        </button>
      </form>

      {state.status === 'idle' && (
        <div className="examples">
          {EXAMPLE_QUESTIONS.map((example) => (
            <button key={example} type="button" className="example" onClick={() => askExample(example)}>
              {example}
            </button>
          ))}
        </div>
      )}
      {state.status !== 'idle' && <h2 className="asked">{state.asked}</h2>}
      {state.status === 'loading' && (
        <>
          <p className="status">Searching the regulations...</p>
          {state.waking && <p className="status">Waking up the server, the first answer can take about 10 s.</p>}
        </>
      )}
      {state.status === 'error' && (
        <div className="band band-error">
          <p role="alert">Something went wrong. Please try again.</p>
          <button type="button" onClick={() => void ask(state.asked)}>
            Try again
          </button>
        </div>
      )}
      {state.status === 'answer' && <Reply reply={state.reply} />}
    </main>
  )
}

function Reply({ reply }: { reply: Answer }) {
  const is_refusal = reply.sources.length === 0 || reply.answer.trimStart().startsWith(REFUSAL_PREFIX)
  return (
    <>
      <div data-testid="answer" className={is_refusal ? 'answer band band-refusal' : 'answer'}>
        <Markdown remarkPlugins={[remarkBreaks]} components={answerComponents} disallowedElements={['img']}>
          {reply.answer}
        </Markdown>
      </div>
      {reply.sources.length > 0 && <Sources sources={reply.sources} cited={citedNumbers(reply.answer)} />}
    </>
  )
}

function Sources({ sources, cited }: { sources: Source[]; cited: Set<number> }) {
  return (
    <section className="sources" aria-label="Sources">
      <ol>
        {sources.map((source, i) => (
          <li key={source.label}>
            {HTTP_URL.test(source.url) ? (
              <a href={source.url} target="_blank" rel="noopener">
                <SourceLabel label={shownLabel(source)} />
              </a>
            ) : (
              <SourceLabel label={shownLabel(source)} />
            )}{' '}
            <span className="tier">{TIER_NAMES[source.source_tier] ?? source.source_tier}</span>{' '}
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

// Study in the States labels end in a raw citation-key slug, so show the page title after the [n] numeral.
function shownLabel(source: Source) {
  if (source.source_tier !== 'sits' || !source.title) return source.label
  const numeral = source.label.match(/^\[\d+\]/)?.[0] ?? ''
  return `${numeral} ${source.title}`.trim()
}

// The leading "[n]" becomes a red numeral; the link text stays exactly the label.
function SourceLabel({ label }: { label: string }) {
  const [, numeral, rest] = label.match(/^(\[\d+\])(.*)$/s) ?? [null, '', label]
  return (
    <>
      <span className="numeral">{numeral}</span>
      {rest}
    </>
  )
}
