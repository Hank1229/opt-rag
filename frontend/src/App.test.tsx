// Step 11 and 13 tests: the question form, its states, answer rendering, and citation markers, with fetch mocked.
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
  expect(answer.textContent).toBe('Up to 90 days [1].')

  const rows = screen.getAllByRole('listitem')
  expect(rows).toHaveLength(2)
  expect(answer.compareDocumentPosition(rows[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  rows.forEach((row, i) => {
    const link = row.querySelector('a')!
    expect(link.textContent).toBe(SOURCES[i].label)
    expect(link.getAttribute('href')).toBe(SOURCES[i].url)
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noopener')
    expect(row.querySelector('.tier')!.textContent).toBe(SOURCES[i].source_tier)
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
  expect(screen.getByTestId('answer').textContent).toBe('Up to 90 days [1].')
})

// Step 13

const FIVE_SOURCES = Array.from({ length: 5 }, (_, i) => ({
  ...SOURCES[0],
  label: `[${i + 1}] 8 CFR 214.2(f)(${i + 1})`,
  url: `https://www.ecfr.gov/on/2026-09-14/title-8/section-214.2#p-214.2(f)(${i + 1})`,
}))

const markers = () => screen.getAllByRole('listitem').map((row) => row.querySelector('.citation')!.textContent)

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
  expect(screen.getByTestId('answer').textContent).toBe('Both apply [2][4].')
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
