// Step 11 and 13 tests: the question form, its states, answer rendering, and citation chips, with fetch mocked.
// Numbered tests map to Hank's expected results (Step 11: 1-5, Step 13: S13-1 to S13-3,
// review follow-ups of Step 13: F1 to F5);
// "extra" tests are edge cases added by Claude.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'

const QUESTION = 'How many days of unemployment are allowed on post-completion OPT?'
const SOURCES = [
  {
    label: '[1] 8 CFR 214.2(f)(10)(ii)(E)',
    citation_key: '214.2(f)(10)(ii)(E)',
    title: '8 CFR 214.2(f) Students',
    source_tier: 'ecfr',
    url: 'https://www.ecfr.gov/on/2026-09-14/title-8/section-214.2#p-214.2(f)(10)(ii)(E)',
    distance: 0.21,
  },
  {
    label: '[2] Form I-983 Overview Reporting',
    citation_key: 'Reporting',
    title: 'Form I-983 Overview',
    source_tier: 'sits',
    url: 'https://studyinthestates.dhs.gov/stem-opt-hub/additional-resources/form-i-983-overview',
    distance: 0.34,
  },
]

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

// reply answers /query; the mount-time /health ping always gets a 200 unless health is given.
function mockFetch(reply: () => Promise<Response>, health = () => json({ status: 'ok' })) {
  const fetch = vi.fn((url: string, _init?: RequestInit) => (url.endsWith('/health') ? health() : reply()))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

const queryCalls = (fetch: ReturnType<typeof mockFetch>) => fetch.mock.calls.filter(([url]) => url.endsWith('/query'))

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }))
}

const SEARCHING = 'Searching the regulations...'
const WAKING = 'Waking up the server, the first answer can take about 10 s.'

const input = () => screen.getByLabelText('Question') as HTMLInputElement
const button = () => screen.getByRole('button', { name: 'Ask' }) as HTMLButtonElement

async function ask(question = QUESTION) {
  fireEvent.change(input(), { target: { value: question } })
  await act(async () => fireEvent.click(button()))
}

test('1: empty input disables submit and sends no request', async () => {
  const fetch = mockFetch(() => json({ answer: 'x', sources: [] }))
  render(<App />)
  expect(button().disabled).toBe(true)
  await act(async () => fireEvent.click(button()))
  expect(queryCalls(fetch)).toHaveLength(0)
})

test('1 extra: whitespace-only input disables submit, and submitting the form sends nothing', async () => {
  const fetch = mockFetch(() => json({ answer: 'x', sources: [] }))
  render(<App />)
  fireEvent.change(input(), { target: { value: '   ' } })
  expect(button().disabled).toBe(true)
  await act(async () => fireEvent.submit(input().form!))
  expect(queryCalls(fetch)).toHaveLength(0)
})

test('2: while the request is pending, submit is disabled and the searching message shows, no answer yet', async () => {
  let resolve!: (response: Response) => void
  mockFetch(() => new Promise((r) => (resolve = r)))
  render(<App />)
  await ask()
  expect(button().disabled).toBe(true)
  expect(screen.getByText(SEARCHING)).toBeTruthy()
  expect(screen.queryByTestId('answer')).toBeNull()
  await act(async () => resolve(new Response(JSON.stringify({ answer: 'Done.', sources: [] }))))
  expect(screen.queryByText(SEARCHING)).toBeNull()
})

test('3: answer on top, sources below in response order with label, tier tag, and new-tab link', async () => {
  const fetch = mockFetch(() => json({ answer: 'Up to 90 days [1].', sources: SOURCES }))
  render(<App />)
  await ask()

  expect(fetch).toHaveBeenCalledWith('http://localhost:8000/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: QUESTION }),
  })
  const answer = screen.getByTestId('answer')
  expect(answer.textContent).toBe('Up to 90 days1.')

  const rows = screen.getAllByRole('listitem')
  expect(rows).toHaveLength(2)
  expect(answer.compareDocumentPosition(rows[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  const shown = ['8 CFR 214.2(f)(10)(ii)(E)', 'Form I-983 Overview']
  const tiers = ['eCFR', 'Study in the States']
  rows.forEach((row, i) => {
    const link = row.querySelector('a')!
    expect(visibleTitle(row)).toBe(shown[i])
    expect(link.textContent).toBe(`Open on ${tiers[i]}`)
    expect(link.getAttribute('aria-label')).toBe(`Open on ${tiers[i]}: ${shown[i]}, opens in a new tab`)
    expect(link.getAttribute('href')).toBe(SOURCES[i].url)
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
    expect(row.querySelector('.tier')!.textContent).toBe(tiers[i])
  })
  expect(screen.queryByText(/0\.21|0\.34/)).toBeNull()
})

test.each([
  ['5xx', () => json({ detail: 'Internal Server Error' }, 500)],
  ['network error', () => Promise.reject(new TypeError('Failed to fetch'))],
])('4: %s shows one error, keeps the question, re-enables submit', async (_, reply) => {
  mockFetch(reply)
  render(<App />)
  await ask()
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(input().value).toBe(QUESTION)
  expect(button().disabled).toBe(false)
  expect(screen.queryByTestId('answer')).toBeNull()
})

test('5: answer with no sources shows the answer and no sources section', async () => {
  mockFetch(() => json({ answer: 'The provided sources do not contain the answer.', sources: [] }))
  render(<App />)
  await ask()
  expect(screen.getByTestId('answer').textContent).toBe('The provided sources do not contain the answer.')
  expect(screen.queryByRole('list')).toBeNull()
  expect(screen.queryByText('Sources')).toBeNull()
})

test('extra: a new question after an error clears the error', async () => {
  const fetch = mockFetch(() => json({}, 503))
  render(<App />)
  await ask()
  fetch.mockImplementation(() => json({ answer: 'Up to 90 days [1].', sources: SOURCES }))
  await ask()
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByTestId('answer').textContent).toBe('Up to 90 days1.')
})

// Step 13

const FIVE_SOURCES = Array.from({ length: 5 }, (_, i) => ({
  ...SOURCES[0],
  label: `[${i + 1}] 8 CFR 214.2(f)(${i + 1})`,
  url: `https://www.ecfr.gov/on/2026-09-14/title-8/section-214.2#p-214.2(f)(${i + 1})`,
}))

const markers = () => screen.getAllByRole('listitem').map((row) => row.querySelector('.citation')!.textContent)

// The title as sighted users read it: the screen-reader-only "Source N: " prefix is dropped.
function visibleTitle(row: Element) {
  const title = row.querySelector('.source-title')!.cloneNode(true) as Element
  title.querySelector('.sr-only')!.remove()
  return title.textContent
}

test('S13-1a: markdown bold renders as <strong> without literal asterisks', async () => {
  mockFetch(() => json({ answer: 'The student must be enrolled for **one full academic year** [1].', sources: SOURCES }))
  render(<App />)
  await ask()
  const answer = screen.getByTestId('answer')
  expect(answer.querySelector('strong')!.textContent).toBe('one full academic year')
  expect(answer.textContent).not.toContain('*')
})

test('S13-1b: a <script> tag in the answer shows as text and never becomes a script element', async () => {
  mockFetch(() => json({ answer: 'Before <script>alert(1)</script> after [1].', sources: SOURCES }))
  render(<App />)
  await ask()
  expect(screen.getByTestId('answer').textContent).toContain('<script>alert(1)</script>')
  expect(document.querySelector('script')).toBeNull()
})

test('S13-1 extra: a <script> block at line start (CommonMark HTML block) also stays text', async () => {
  mockFetch(() => json({ answer: '<script>alert(1)</script>\n\nSecond paragraph.', sources: [] }))
  render(<App />)
  await ask()
  expect(screen.getByTestId('answer').textContent).toContain('<script>alert(1)</script>')
  expect(document.querySelector('script')).toBeNull()
})

test('S13-1 extra: <script> and <img onerror> in one answer both show as inert text and nothing runs', async () => {
  const alert = vi.spyOn(window, 'alert').mockImplementation(() => {})
  mockFetch(() => json({ answer: '<script>alert(1)</script> and <img src=x onerror=alert(1)>', sources: [] }))
  render(<App />)
  await ask()
  const answer = screen.getByTestId('answer')
  expect(answer.textContent).toContain('<script>alert(1)</script>')
  expect(answer.textContent).toContain('<img src=x onerror=alert(1)>')
  expect(document.querySelector('script, img, [onerror]')).toBeNull()
  expect(alert).not.toHaveBeenCalled()
  alert.mockRestore()
})

test('S13-1 extra: a javascript: markdown link gets no javascript href', async () => {
  mockFetch(() => json({ answer: 'See [this](javascript:alert(1)).', sources: [] }))
  render(<App />)
  await ask()
  const link = screen.getByTestId('answer').querySelector('a')
  expect(link?.getAttribute('href') ?? '').not.toMatch(/^javascript:/i)
})

test('S13-2a: answer cites [1] and [3] of 5 sources -> 1 and 3 cited, the rest retrieved, not cited', async () => {
  mockFetch(() => json({ answer: 'Up to 90 days [1]. Reporting applies [3].', sources: FIVE_SOURCES }))
  render(<App />)
  await ask()
  expect(markers()).toEqual(['cited', 'retrieved, not cited', 'cited', 'retrieved, not cited', 'retrieved, not cited'])
})

test('S13-2b: answer cites [7] with 5 sources -> no crash, all 5 retrieved, not cited', async () => {
  mockFetch(() => json({ answer: 'Up to 90 days [7].', sources: FIVE_SOURCES }))
  render(<App />)
  await ask()
  expect(screen.getAllByRole('listitem')).toHaveLength(5)
  expect(markers()).toEqual(Array(5).fill('retrieved, not cited'))
})

test('S13-2 extra, F1b: adjacent citations [2][4], the prompt\'s documented form, mark both', async () => {
  mockFetch(() => json({ answer: 'Both apply [2][4].', sources: FIVE_SOURCES }))
  render(<App />)
  await ask()
  expect(markers()).toEqual(['retrieved, not cited', 'cited', 'retrieved, not cited', 'cited', 'retrieved, not cited'])
  expect(screen.getByTestId('answer').textContent).toBe('Both apply24.')
  expect([...screen.getByTestId('answer').querySelectorAll('a.chip')].map((chip) => chip.getAttribute('href'))).toEqual(['#src-2', '#src-4'])
})

test('S13-3c: mount -> exactly one fetch, a GET to /health, none to /query', async () => {
  const fetch = mockFetch(() => json({ answer: 'x', sources: [] }))
  await act(async () => render(<App />))
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch).toHaveBeenCalledWith('http://localhost:8000/health')
})

test('S13-3 extra: a failed /health ping shows no error and the form still works', async () => {
  mockFetch(
    () => json({ answer: 'Done.', sources: [] }),
    () => Promise.reject(new TypeError('Failed to fetch')),
  )
  await act(async () => render(<App />))
  expect(screen.queryByRole('alert')).toBeNull()
  await ask()
  expect(screen.getByTestId('answer').textContent).toBe('Done.')
})

// Step 13 review follow-ups

test('F1a: a comma list [1, 3] marks sources 1 and 3 cited, as LABEL in app/evals/metrics.py does', async () => {
  mockFetch(() => json({ answer: 'Both apply [1, 3].', sources: FIVE_SOURCES }))
  render(<App />)
  await ask()
  expect(markers()).toEqual(['cited', 'retrieved, not cited', 'cited', 'retrieved, not cited', 'retrieved, not cited'])
})

test('F1c: brackets LABEL does not match ([ 2], [3a], [1-3], (4), [5,]) mark nothing cited', async () => {
  mockFetch(() => json({ answer: 'See [ 2], [3a], [1-3], (4), [5,].', sources: FIVE_SOURCES }))
  render(<App />)
  await ask()
  expect(markers()).toEqual(Array(5).fill('retrieved, not cited'))
})

test('F1 extra: comma lists with uneven spacing ([1,2 , 5]) mark every number', async () => {
  mockFetch(() => json({ answer: 'All apply [1,2 , 5].', sources: FIVE_SOURCES }))
  render(<App />)
  await ask()
  expect(markers()).toEqual(['cited', 'cited', 'retrieved, not cited', 'retrieved, not cited', 'cited'])
})

test('F2a: /health still pending at submit -> wake-up line under the searching line, gone when the answer arrives', async () => {
  let resolve!: (response: Response) => void
  mockFetch(
    () => new Promise((r) => (resolve = r)),
    () => new Promise(() => {}),
  )
  render(<App />)
  await ask()
  expect(screen.getByText(SEARCHING)).toBeTruthy()
  expect(screen.getByText(WAKING)).toBeTruthy()
  await act(async () => resolve(new Response(JSON.stringify({ answer: 'Done.', sources: [] }))))
  expect(screen.queryByText(WAKING)).toBeNull()
  expect(screen.getByTestId('answer').textContent).toBe('Done.')
})

test('F2b: /health resolved before submit -> wake-up line never shows', async () => {
  let resolve!: (response: Response) => void
  mockFetch(() => new Promise((r) => (resolve = r)))
  await act(async () => render(<App />))
  await ask()
  expect(screen.getByText(SEARCHING)).toBeTruthy()
  expect(screen.queryByText(WAKING)).toBeNull()
  await act(async () => resolve(new Response(JSON.stringify({ answer: 'Done.', sources: [] }))))
  expect(screen.queryByText(WAKING)).toBeNull()
})

test('F2c: /health failed before submit -> wake-up line never shows', async () => {
  mockFetch(
    () => new Promise(() => {}),
    () => Promise.reject(new TypeError('Failed to fetch')),
  )
  await act(async () => render(<App />))
  await ask()
  expect(screen.getByText(SEARCHING)).toBeTruthy()
  expect(screen.queryByText(WAKING)).toBeNull()
})

test('F2 extra: /health resolving mid-request keeps the line until the answer; the next question has none', async () => {
  let resolveHealth!: (response: Response) => void
  let resolve!: (response: Response) => void
  const fetch = mockFetch(
    () => new Promise((r) => (resolve = r)),
    () => new Promise((r) => (resolveHealth = r)),
  )
  render(<App />)
  await ask()
  await act(async () => resolveHealth(new Response(JSON.stringify({ status: 'ok' }))))
  expect(screen.getByText(WAKING)).toBeTruthy()
  await act(async () => resolve(new Response(JSON.stringify({ answer: 'Done.', sources: [] }))))
  fetch.mockImplementation(() => new Promise(() => {}))
  await ask()
  expect(screen.getByText(SEARCHING)).toBeTruthy()
  expect(screen.queryByText(WAKING)).toBeNull()
})

test('F2 extra: an error response also clears the wake-up line', async () => {
  mockFetch(
    () => json({}, 503),
    () => new Promise(() => {}),
  )
  render(<App />)
  await ask()
  expect(screen.getByRole('alert')).toBeTruthy()
  expect(screen.queryByText(WAKING)).toBeNull()
})

test('F4a: a single newline renders as a line break inside one paragraph', async () => {
  mockFetch(() => json({ answer: 'line one\nline two', sources: [] }))
  render(<App />)
  await ask()
  const answer = screen.getByTestId('answer')
  expect(answer.querySelectorAll('p')).toHaveLength(1)
  expect(answer.querySelectorAll('br')).toHaveLength(1)
})

test('F4b: a blank line still separates two paragraphs', async () => {
  mockFetch(() => json({ answer: 'para\n\npara', sources: [] }))
  render(<App />)
  await ask()
  const answer = screen.getByTestId('answer')
  expect([...answer.querySelectorAll('p')].map((p) => p.textContent)).toEqual(['para', 'para'])
  expect(answer.querySelector('br')).toBeNull()
})

test('F5a: a markdown link from the model opens in a new tab with noopener noreferrer', async () => {
  mockFetch(() => json({ answer: 'See [eCFR](https://example.com).', sources: [] }))
  render(<App />)
  await ask()
  const link = screen.getByTestId('answer').querySelector('a')!
  expect(link.textContent).toBe('eCFR')
  expect(link.getAttribute('href')).toBe('https://example.com')
  expect(link.getAttribute('target')).toBe('_blank')
  expect(link.getAttribute('rel')).toBe('noopener noreferrer')
})

test('F5b: a markdown image from the model renders no <img>', async () => {
  mockFetch(() => json({ answer: 'Look ![x](https://example.com/a.png) here.', sources: [] }))
  render(<App />)
  await ask()
  expect(screen.getByTestId('answer').querySelector('img')).toBeNull()
  expect(document.querySelector('img')).toBeNull()
})

// Polish pass (extra: tests added by Claude)

test('polish extra: Try again resends the question and shows the answer', async () => {
  const fetch = mockFetch(() => json({}, 503))
  render(<App />)
  await ask()
  fetch.mockImplementation(() => json({ answer: 'Up to 90 days [1].', sources: SOURCES }))
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Try again' })))
  expect(queryCalls(fetch)).toHaveLength(2)
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByTestId('answer').textContent).toBe('Up to 90 days1.')
})

test('polish extra: unreachable API shows the red error band, and Try again resends the same question', async () => {
  const fetch = mockFetch(() => Promise.reject(new TypeError('Failed to fetch')))
  render(<App />)
  await ask()
  expect(screen.getByRole('alert').parentElement!.className).toContain('band-error')
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Try again' })))
  const bodies = queryCalls(fetch).map(([, init]) => init!.body)
  expect(bodies).toEqual([JSON.stringify({ question: QUESTION }), JSON.stringify({ question: QUESTION })])
  expect(screen.getByRole('alert')).toBeTruthy()
})

test('polish extra: editing the input after an error does not change what Try again resends', async () => {
  const fetch = mockFetch(() => json({}, 503))
  render(<App />)
  await ask()
  fireEvent.change(input(), { target: { value: 'A different question' } })
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Try again' })))
  const bodies = queryCalls(fetch).map(([, init]) => init!.body)
  expect(bodies).toEqual(Array(2).fill(JSON.stringify({ question: QUESTION })))
})

test('polish extra: a source with a javascript: url shows its label as plain text, not a link', async () => {
  const sources = [{ ...SOURCES[0], url: 'javascript:alert(1)' }, SOURCES[1]]
  mockFetch(() => json({ answer: 'Up to 90 days [1].', sources }))
  render(<App />)
  await ask()
  const [bad, good] = screen.getAllByRole('listitem')
  expect(bad.querySelector('a')).toBeNull()
  expect(bad.textContent).toContain('8 CFR 214.2(f)(10)(ii)(E)')
  expect(good.querySelector('a')!.getAttribute('href')).toBe(SOURCES[1].url)
})

test.each([
  ['leading whitespace before the refusal opening', '\n  The provided sources do not contain the answer to this.', true],
  ['no leading whitespace', 'The provided sources do not contain the answer to this.', true],
  ['extra: leading whitespace before ordinary text', '\n  Sure, here is the answer.', false],
])('refusal band: %s', async (_, answer, is_refusal) => {
  mockFetch(() => json({ answer, sources: SOURCES }))
  render(<App />)
  await ask()
  expect(screen.getByTestId('answer').className.includes('band-refusal')).toBe(is_refusal)
})

test('polish extra: the asked question shows as a heading; a refusal with sources gets the refusal band but keeps its sources', async () => {
  mockFetch(() => json({ answer: 'The provided sources do not contain the answer to this question.', sources: SOURCES }))
  render(<App />)
  await ask()
  expect(screen.getByRole('heading', { name: QUESTION })).toBeTruthy()
  expect(screen.getByTestId('answer').className).toContain('band-refusal')
})

const EXAMPLES = [
  "How long do I need to study full-time before I'm eligible for OPT?",
  "I'm on OPT. How recent does the travel signature on my I-20 need to be when I re-enter the U.S.?",
  "I'm on OPT based on a non-STEM degree, but I earned a STEM degree before that. Can I use my earlier degree to apply for a STEM OPT extension, and what requirements would my earlier degree and current job need to meet?",
]
const exampleButton = (text: string) => screen.queryByRole('button', { name: text })

test('examples a: the empty state shows three buttons with the exact example questions, not a list', async () => {
  mockFetch(() => json({ answer: 'x', sources: [] }))
  render(<App />)
  EXAMPLES.forEach((text) => expect(exampleButton(text)).toBeTruthy())
  expect(document.querySelectorAll('.example')).toHaveLength(3)
  expect(screen.queryByRole('list')).toBeNull()
})

test.each(EXAMPLES.map((text, i) => [i + 1, text] as const))(
  'examples b: clicking example %i sends one POST /query with that exact question',
  async (_, text) => {
    const fetch = mockFetch(() => new Promise(() => {}))
    render(<App />)
    await act(async () => fireEvent.click(exampleButton(text)!))
    expect(queryCalls(fetch)).toHaveLength(1)
    expect(queryCalls(fetch)[0][1]!.body).toBe(JSON.stringify({ question: text }))
    expect(input().value).toBe(text)
  },
)

test('examples c (extra): once the answer appears, the example buttons are gone', async () => {
  mockFetch(() => json({ answer: 'Up to 90 days [1].', sources: SOURCES }))
  render(<App />)
  await act(async () => fireEvent.click(exampleButton(EXAMPLES[0])!))
  expect(screen.getByTestId('answer')).toBeTruthy()
  expect(document.querySelector('.example')).toBeNull()
})

test('examples d (extra): while a request is loading no example button is left to start a second request', async () => {
  const fetch = mockFetch(() => new Promise(() => {}))
  render(<App />)
  await act(async () => fireEvent.click(exampleButton(EXAMPLES[0])!))
  expect(screen.getByText(SEARCHING)).toBeTruthy()
  expect(document.querySelector('.example')).toBeNull()
  expect(queryCalls(fetch)).toHaveLength(1)
})

// Source names and intro sentence

const INTRO = 'Answers from 8 CFR 214.2(f) and Study in the States, with sources. Pick an example or type your own.'
const SLUG = 'applying-for-practical-training#practical-training-for-f-students/optional-practical-training'

async function askWithSources(sources: unknown[]) {
  mockFetch(() => json({ answer: 'Up to 90 days [1].', sources }))
  render(<App />)
  await ask()
}

test('names a: a sits source shows its title and "Open on Study in the States", never the raw key slug', async () => {
  const sits = {
    label: `[1] Applying for Practical Training ${SLUG}`,
    title: 'Applying for Practical Training',
    source_tier: 'sits',
    url: 'https://studyinthestates.dhs.gov/students/work/applying-for-practical-training',
  }
  await askWithSources([sits])
  const row = screen.getByRole('listitem')
  expect(visibleTitle(row)).toBe('Applying for Practical Training')
  expect(row.querySelector('a')!.textContent).toBe('Open on Study in the States')
  expect(row.querySelector('a')!.getAttribute('aria-label')).toBe('Open on Study in the States: Applying for Practical Training, opens in a new tab')
  expect(row.querySelector('a')!.getAttribute('href')).toBe(sits.url)
  expect(row.querySelector('.tier')!.textContent).toBe('Study in the States')
  expect(document.body.textContent).not.toContain(SLUG)
})

test('names b: an ecfr source keeps its label and shows "eCFR"', async () => {
  await askWithSources([{ ...SOURCES[0], label: '[1] 8 CFR 214.2(f)(10)', title: '8 CFR 214.2(f) Students' }])
  const row = screen.getByRole('listitem')
  expect(visibleTitle(row)).toBe('8 CFR 214.2(f)(10)')
  expect(row.querySelector('a')!.textContent).toBe('Open on eCFR')
  expect(row.querySelector('.tier')!.textContent).toBe('eCFR')
})

test('names c (extra): an unknown tier "foo" is shown as is and does not crash', async () => {
  await askWithSources([{ ...SOURCES[0], source_tier: 'foo' }])
  expect(screen.getByRole('listitem').querySelector('.tier')!.textContent).toBe('foo')
})

test('names d (extra): a sits source with no title shows its label', async () => {
  const label = `[1] Form I-983 Overview ${SLUG}`
  await askWithSources([{ label, source_tier: 'sits', url: SOURCES[1].url }])
  expect(visibleTitle(screen.getByRole('listitem'))).toBe(label.replace('[1] ', ''))
})

test('intro e: the sentence is the title in the empty state, and is gone once an answer is shown', async () => {
  mockFetch(() => json({ answer: 'Up to 90 days [1].', sources: SOURCES }))
  render(<App />)
  expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(INTRO)
  await ask()
  expect(screen.queryByText(INTRO)).toBeNull()
})

// Option D restyle (extra: tests added by Claude)

const FOOTER = "Not legal advice. Check with your school's DSO before you act."

test('restyle a: "12 months" is highlighted and the citation is a chip linking to #src-1', async () => {
  mockFetch(() => json({ answer: 'Work for 12 months [1].', sources: SOURCES }))
  render(<App />)
  await ask()
  const answer = screen.getByTestId('answer')
  expect(answer.querySelector('mark')!.textContent).toBe('12 months')
  const chip = answer.querySelector('a.chip')!
  expect(chip.getAttribute('href')).toBe('#src-1')
  expect(chip.getAttribute('aria-label')).toBe('Source 1')
  expect(document.getElementById('src-1')).toBeTruthy()
})

test('restyle b: "8 CFR 214.2(f)(10)" has no time unit, so nothing is highlighted', async () => {
  mockFetch(() => json({ answer: 'See 8 CFR 214.2(f)(10) for the rule.', sources: SOURCES }))
  render(<App />)
  await ask()
  expect(screen.getByTestId('answer').querySelector('mark')).toBeNull()
})

test('restyle c: a 120-character question gets the medium headline class', async () => {
  const question = 'q'.repeat(120)
  mockFetch(() => json({ answer: 'x', sources: [] }))
  render(<App />)
  await ask(question)
  expect(screen.getByRole('heading', { level: 1 }).className).toContain('h1-md')
})

test.each([
  [70, 'h1-lg'],
  [71, 'h1-md'],
  [140, 'h1-md'],
  [141, 'h1-sm'],
])('restyle c extra: a %i-character question gets %s', async (length, size) => {
  mockFetch(() => json({ answer: 'x', sources: [] }))
  render(<App />)
  await ask('q'.repeat(length))
  expect(screen.getByRole('heading', { level: 1 }).className).toContain(size)
})

test.each([
  ['empty', () => json({ answer: 'x', sources: [] }), false],
  ['answer', () => json({ answer: 'Up to 90 days [1].', sources: SOURCES }), true],
  ['refusal', () => json({ answer: 'The provided sources do not contain the answer.', sources: [] }), true],
  ['error', () => json({}, 503), true],
])('restyle d: the footer text shows in the %s state', async (_, reply, shouldAsk) => {
  mockFetch(reply)
  render(<App />)
  if (shouldAsk) await ask()
  expect(screen.getByText(FOOTER)).toBeTruthy()
})

test('restyle extra: auto-highlight skips links and inline code, and bold text is not wrapped twice', async () => {
  mockFetch(() => json({ answer: '[90 days](https://example.com) and `12 months` and **30 days** [1].', sources: SOURCES }))
  render(<App />)
  await ask()
  const answer = screen.getByTestId('answer')
  expect(answer.querySelector('mark')).toBeNull()
  expect(answer.querySelector('strong')!.textContent).toBe('30 days')
  expect(answer.querySelectorAll('a.chip')).toHaveLength(1)
})

test('restyle extra: a comma citation [1, 2] renders one chip per source', async () => {
  mockFetch(() => json({ answer: 'Both apply [1, 2].', sources: SOURCES }))
  render(<App />)
  await ask()
  const chips = [...screen.getByTestId('answer').querySelectorAll('a.chip')]
  expect(chips.map((chip) => chip.getAttribute('aria-label'))).toEqual(['Source 1', 'Source 2'])
})

test('typography a: a bold label ending in ":" has no marker class, while "10 years" is still highlighted', async () => {
  mockFetch(() => json({ answer: '- **Degree Level:** Master for 10 years [1].\n\n**Important** note', sources: SOURCES }))
  render(<App />)
  await ask()
  const answer = screen.getByTestId('answer')
  const [label, other] = answer.querySelectorAll('strong')
  expect(label.className).toBe('label')
  expect(other.className).toBe('')
  expect(answer.querySelector('mark')!.textContent).toBe('10 years')
})

test('typography b: a markdown "## Title" renders as an h3, and "#### Title" as an h4', async () => {
  mockFetch(() => json({ answer: '## Title\n\n#### Small [1]', sources: SOURCES }))
  render(<App />)
  await ask()
  const answer = screen.getByTestId('answer')
  expect(answer.querySelector('h3')!.textContent).toBe('Title')
  expect(answer.querySelector('h4')!.textContent).toBe('Small1')
  expect(answer.querySelector('h2')).toBeNull()
})

test('typography c: no whitespace before or between chips, also after bold and highlighted text', async () => {
  mockFetch(() => json({ answer: 'See the rule [1] [2].\n\nFor **one full year** [1][2] or 12 months [3].', sources: SOURCES }))
  render(<App />)
  await ask()
  const answer = screen.getByTestId('answer')
  expect(answer.textContent).toBe('See the rule12.\nFor one full year12 or 12 months3.')
  expect(answer.querySelectorAll('.chip')).toHaveLength(5)
})

test('a11y a: each source title starts with a hidden "Source N: " and the visible text is unchanged', async () => {
  mockFetch(() => json({ answer: 'Both apply [1, 2].', sources: SOURCES }))
  render(<App />)
  await ask()
  screen.getAllByRole('listitem').forEach((row, i) => {
    const title = row.querySelector('.source-title')!
    expect(title.querySelector('.sr-only')!.textContent).toBe(`Source ${i + 1}: `)
    expect(title.firstElementChild!.className).toBe('sr-only')
  })
  expect(visibleTitle(screen.getAllByRole('listitem')[0])).toBe('8 CFR 214.2(f)(10)(ii)(E)')
})

test('a11y b: answer cites [7] with 3 sources -> no link for 7, the number is still shown', async () => {
  const three = [...SOURCES, { ...SOURCES[0], label: '[3] Third' }]
  mockFetch(() => json({ answer: 'See [1] and [7].', sources: three }))
  render(<App />)
  await ask()
  const chips = [...screen.getByTestId('answer').querySelectorAll('.chip')]
  expect(chips.map((chip) => chip.textContent)).toEqual(['1', '7'])
  expect(chips[0].tagName).toBe('A')
  expect(chips[1].tagName).toBe('SPAN')
  expect(chips[1].getAttribute('href')).toBeNull()
  expect(chips[1].getAttribute('aria-label')).toBeNull()
})

test('a11y c: the source link aria-label says it opens in a new tab', async () => {
  mockFetch(() => json({ answer: 'Up to 90 days [1].', sources: SOURCES }))
  render(<App />)
  await ask()
  screen.getAllByRole('listitem').forEach((row) => {
    expect(row.querySelector('a')!.getAttribute('aria-label')).toContain('opens in a new tab')
  })
})

test('centered a: the empty state has the is-empty class on the page and the answer state does not', async () => {
  mockFetch(() => json({ answer: 'Up to 90 days [1].', sources: SOURCES }))
  const { container } = render(<App />)
  expect(container.querySelector('.page')!.classList.contains('is-empty')).toBe(true)
  await ask()
  expect(container.querySelector('.page')!.classList.contains('is-empty')).toBe(false)
})
