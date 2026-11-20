// Single-page question form: posts to the FastAPI /query endpoint and shows the answer and its sources.
import { useEffect, useRef, useState, type FormEvent } from 'react'
import Markdown, { type Components } from 'react-markdown'
import remarkBreaks from 'remark-breaks'
import remarkAnswerMarks, { CITATION } from './answerMarks'

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
const DISCLAIMER = "Not legal advice. Check with your school's DSO before you act."
const LEADING_NUMERAL = /^\[\d+\]\s*/
const LARGE_HEADLINE_MAX = 70
const MEDIUM_HEADLINE_MAX = 140

// Source numbers the answer cites as [n] or [n, m], 1-based like the source labels.
function citedNumbers(answer: string) {
  return new Set([...answer.matchAll(CITATION)].flatMap((match) => match[1].split(',').map(Number)))
}

// The answer is model output: links leave in a new tab, and images (dropped below) never load outside URLs.
// A chip links only to a source that exists in this response; otherwise it is a plain chip.
function answerComponents(sourceCount: number): Components {
  return {
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ),
    // answerMarks.ts emits <cite> for [n]; its only child is the source number.
    cite: ({ children }) => {
      const number = Number(children)
      if (number < 1 || number > sourceCount) return <span className="chip">{children}</span>
      return (
        <a className="chip" href={`#src-${number}`} aria-label={`Source ${number}`}>
          {children}
        </a>
      )
    },
    mark: ({ children }) => <mark className="highlight">{children}</mark>,
  }
}

// One class per size so the CSS and the tests share the same three tiers.
function headlineSize(text: string) {
  if (text.length <= LARGE_HEADLINE_MAX) return 'h1-lg'
  return text.length <= MEDIUM_HEADLINE_MAX ? 'h1-md' : 'h1-sm'
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

  const headline = state.status === 'idle' ? INTRO : state.asked

  return (
    <div className="page">
      <div className="content">
        <header className="site-header">
          <span className="brand">opt-rag</span>
          <span className="header-note">Not legal advice</span>
        </header>
        <main>
          <div className="hero">
            <h1 className={`headline ${headlineSize(headline)}`}>{headline}</h1>
            <form onSubmit={submit}>
              <label htmlFor="question" className="sr-only">
                Question
              </label>
              <input id="question" value={question} onChange={(e) => setQuestion(e.target.value)} />
              <button type="submit" className="ask" disabled={!question.trim() || state.status === 'loading'}>
                Ask
              </button>
            </form>

            {state.status === 'idle' && (
              <div className="examples">
                {EXAMPLE_QUESTIONS.map((example) => (
                  <button key={example} type="button" className="outline example" onClick={() => askExample(example)}>
                    {example}
                  </button>
                ))}
              </div>
            )}
            {state.status === 'loading' && (
              <>
                <p className="status">Searching the regulations...</p>
                {state.waking && <p className="status">Waking up the server, the first answer can take about 10 s.</p>}
              </>
            )}
          </div>
          {state.status === 'error' && (
            <section className="answer-section">
              <div className="answer-col">
                <div className="band band-error">
                  <p role="alert">Something went wrong. Please try again.</p>
                  <button type="button" className="outline" onClick={() => void ask(state.asked)}>
                    Try again
                  </button>
                </div>
              </div>
            </section>
          )}
          {state.status === 'answer' && <Reply reply={state.reply} />}
        </main>
      </div>
      <footer className="site-footer">
        <div className="footer-inner">
          <InfoIcon />
          <span>{DISCLAIMER}</span>
        </div>
      </footer>
    </div>
  )
}

function Reply({ reply }: { reply: Answer }) {
  const is_refusal = reply.sources.length === 0 || reply.answer.trimStart().startsWith(REFUSAL_PREFIX)
  return (
    <section className="answer-section">
      <div className="answer-col">
        <h2 className="sr-only">Answer</h2>
        <div data-testid="answer" className={is_refusal ? 'answer band band-refusal' : 'answer'}>
          <Markdown
            remarkPlugins={[remarkBreaks, remarkAnswerMarks]}
            components={answerComponents(reply.sources.length)}
            disallowedElements={['img']}
          >
            {reply.answer}
          </Markdown>
        </div>
      </div>
      {reply.sources.length > 0 && <Sources sources={reply.sources} cited={citedNumbers(reply.answer)} />}
    </section>
  )
}

function Sources({ sources, cited }: { sources: Source[]; cited: Set<number> }) {
  return (
    <aside className="sources" aria-label="Sources">
      <h2>Sources</h2>
      <ol role="list">
        {sources.map((source, i) => {
          const number = i + 1
          const title = shownLabel(source).replace(LEADING_NUMERAL, '')
          const tier = TIER_NAMES[source.source_tier] ?? source.source_tier
          return (
            <li key={source.label}>
              <span className={cited.has(number) ? 'numeral' : 'numeral is-uncited'} aria-hidden="true">
                {number}
              </span>
              <div className="source-body">
                <p className="source-title" id={`src-${number}`}>
                  <span className="sr-only">Source {number}: </span>
                  {title}
                </p>
                <p className="source-meta">
                  <span className="tier">{tier}</span>{' '}
                  {cited.has(number) ? (
                    <span className="citation cited">cited</span>
                  ) : (
                    <span className="citation">retrieved, not cited</span>
                  )}
                </p>
                {HTTP_URL.test(source.url) && (
                  <a
                    className="source-link"
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`Open on ${tier}: ${title}, opens in a new tab`}
                  >
                    Open on {tier}
                    <ExternalIcon />
                  </a>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </aside>
  )
}

// Study in the States labels end in a raw citation-key slug, so show the page title after the [n] numeral.
function shownLabel(source: Source) {
  if (source.source_tier !== 'sits' || !source.title) return source.label
  const numeral = source.label.match(/^\[\d+\]/)?.[0] ?? ''
  return `${numeral} ${source.title}`.trim()
}

function InfoIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4M12 8h.01" />
    </svg>
  )
}

function ExternalIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </svg>
  )
}
