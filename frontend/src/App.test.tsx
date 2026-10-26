// Step 11 tests: the question form and its four states, with fetch mocked.
// Numbered tests map to Hank's expected results 1-5; "extra" tests are edge cases added by Claude.
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

function mockFetch(reply: () => Promise<Response>) {
  const fetch = vi.fn(reply)
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }))
}

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
  expect(fetch).not.toHaveBeenCalled()
})

test('1 extra: whitespace-only input disables submit, and submitting the form sends nothing', async () => {
  const fetch = mockFetch(() => json({ answer: 'x', sources: [] }))
  render(<App />)
  fireEvent.change(input(), { target: { value: '   ' } })
  expect(button().disabled).toBe(true)
  await act(async () => fireEvent.submit(input().form!))
  expect(fetch).not.toHaveBeenCalled()
})

test('2: while the request is pending, submit is disabled and "Searching..." shows, no answer yet', async () => {
  let resolve!: (response: Response) => void
  mockFetch(() => new Promise((r) => (resolve = r)))
  render(<App />)
  await ask()
  expect(button().disabled).toBe(true)
  expect(screen.getByText('Searching...')).toBeTruthy()
  expect(screen.queryByTestId('answer')).toBeNull()
  await act(async () => resolve(new Response(JSON.stringify({ answer: 'Done.', sources: [] }))))
  expect(screen.queryByText('Searching...')).toBeNull()
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
