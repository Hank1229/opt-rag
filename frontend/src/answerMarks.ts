// Remark plugin for answer text: [n] citations become chips, and "number + time unit" phrases get the highlighter.

// Same grammar as LABEL in app/evals/metrics.py, so the page and the eval agree on what is cited.
export const CITATION = /\[(\d+(?:\s*,\s*\d+)*)\]/g
// "12 months" and "90 days" match; "214.2(f)(10)" has no unit and does not.
const TIME_AMOUNT = /\b\d+(?:\.\d+)?\s?(?:day|month|week|year)s?\b/i
const CITATION_OR_AMOUNT = new RegExp(`${CITATION.source}|(${TIME_AMOUNT.source})`, 'gi')

type MdNode = { type: string; value?: string; children?: MdNode[]; data?: { hName: string } }

const text = (value: string): MdNode => ({ type: 'text', value })

// hName turns a plain mdast node into the <cite> or <mark> element that App.tsx renders.
const chip = (number: string): MdNode => ({ type: 'emphasis', data: { hName: 'cite' }, children: [text(number)] })
const highlight = (amount: string): MdNode => ({ type: 'emphasis', data: { hName: 'mark' }, children: [text(amount)] })

export default function remarkAnswerMarks() {
  return (tree: MdNode) => markChildren(tree, true)
}

// Links are skipped (a chip inside a link would nest anchors); strong already carries the highlighter.
function markChildren(node: MdNode, withAmounts: boolean) {
  if (!node.children || node.type === 'link' || node.type === 'linkReference') return
  const childAmounts = withAmounts && node.type !== 'strong'
  node.children = node.children.flatMap((child) => {
    if (child.type === 'text') return markText(child.value ?? '', childAmounts)
    markChildren(child, childAmounts)
    return [child]
  })
}

function markText(value: string, withAmounts: boolean): MdNode[] {
  const pieces: MdNode[] = []
  let end = 0
  for (const match of value.matchAll(withAmounts ? CITATION_OR_AMOUNT : CITATION)) {
    if (match.index > end) pieces.push(text(value.slice(end, match.index)))
    pieces.push(...(match[1] ? match[1].split(',').map((n) => chip(n.trim())) : [highlight(match[0])]))
    end = match.index + match[0].length
  }
  if (end < value.length) pieces.push(text(value.slice(end)))
  return pieces
}
