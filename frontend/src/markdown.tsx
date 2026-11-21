import { Fragment, type ReactNode } from 'react'

// A small Markdown renderer for assistant replies: paragraphs, headings, bullet and numbered
// lists, fenced code blocks, inline code, bold, italic and http(s) links. It builds React
// elements only (no dangerouslySetInnerHTML), so model output can never inject HTML.

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+?\*\*|__[^_\n]+?__)|(\*[^*\s][^*\n]*?\*|_[^_\s][^_\n]*?_)|(\[[^\]\n]+\]\(https?:\/\/[^)\s]+\))/g

function inline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let i = 0
  for (const m of text.matchAll(INLINE)) {
    const start = m.index ?? 0
    if (start > last) out.push(text.slice(last, start))
    const token = m[0]
    const key = `${keyPrefix}-${i++}`
    if (m[1]) out.push(<code key={key}>{token.slice(1, -1)}</code>)
    else if (m[2]) out.push(<strong key={key}>{inline(token.slice(2, -2), key)}</strong>)
    else if (m[3]) out.push(<em key={key}>{inline(token.slice(1, -1), key)}</em>)
    else {
      const [, label, href] = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token) ?? []
      out.push(
        <a key={key} href={href} target="_blank" rel="noopener noreferrer">
          {label}
        </a>,
      )
    }
    last = start + token.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

function withBreaks(lines: string[], keyPrefix: string): ReactNode[] {
  return lines.map((line, i) => (
    <Fragment key={`${keyPrefix}-${i}`}>
      {i > 0 && <br />}
      {inline(line, `${keyPrefix}-${i}`)}
    </Fragment>
  ))
}

const BULLET = /^\s*[-*+]\s+(.*)$/
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/
const HEADING = /^(#{1,6})\s+(.*)$/
const FENCE = /^\s*```/

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const key = `b${blocks.length}`
    if (FENCE.test(line)) {
      const body: string[] = []
      i++
      while (i < lines.length && !FENCE.test(lines[i])) body.push(lines[i++])
      i++ // closing fence (or end of text)
      blocks.push(
        <pre key={key}>
          <code>{body.join('\n')}</code>
        </pre>,
      )
    } else if (HEADING.test(line)) {
      const [, hashes, content] = HEADING.exec(line)!
      const level = Math.min(hashes.length + 2, 6) // keep headings small inside a bubble
      const Tag = `h${level}` as 'h3' | 'h4' | 'h5' | 'h6'
      blocks.push(<Tag key={key}>{inline(content, key)}</Tag>)
      i++
    } else if (BULLET.test(line) || NUMBERED.test(line)) {
      const ordered = !BULLET.test(line)
      const pattern = ordered ? NUMBERED : BULLET
      const items: string[] = []
      while (i < lines.length && pattern.test(lines[i])) items.push(pattern.exec(lines[i++])![1])
      const List = ordered ? 'ol' : 'ul'
      blocks.push(
        <List key={key}>
          {items.map((item, j) => (
            <li key={j}>{inline(item, `${key}-${j}`)}</li>
          ))}
        </List>,
      )
    } else if (line.trim() === '') {
      i++
    } else {
      const para: string[] = []
      while (
        i < lines.length &&
        lines[i].trim() !== '' &&
        !FENCE.test(lines[i]) &&
        !HEADING.test(lines[i]) &&
        !BULLET.test(lines[i]) &&
        !NUMBERED.test(lines[i])
      )
        para.push(lines[i++])
      blocks.push(<p key={key}>{withBreaks(para, key)}</p>)
    }
  }
  return <>{blocks}</>
}
