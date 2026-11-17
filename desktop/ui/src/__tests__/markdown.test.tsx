import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Markdown } from '../components/Markdown'

describe('Markdown', () => {
  it('renders bold, italic and inline code without showing the markers', () => {
    const { container } = render(<Markdown text={'The **Subject B license** (`a/b.txt`) is *mutual*.'} />)
    expect(container.querySelector('strong')?.textContent).toBe('Subject B license')
    expect(container.querySelector('code')?.textContent).toBe('a/b.txt')
    expect(container.querySelector('em')?.textContent).toBe('mutual')
    expect(container.textContent).not.toMatch(/[*`]/)
  })

  it('renders a table with a header row', () => {
    const text = '| Severity | Source |\n|---|---|\n| P2 | a.txt |\n| P1 | b.txt |'
    render(<Markdown text={text} />)
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('columnheader').map((c) => c.textContent)).toEqual(['Severity', 'Source'])
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    expect(within(table).getByText('b.txt')).toBeInTheDocument()
  })

  it('renders lists and headings', () => {
    render(<Markdown text={'## Why\n\n- one\n- two\n\n1. first\n2. second'} />)
    expect(screen.getByRole('heading', { name: 'Why' })).toBeInTheDocument()
    expect(screen.getAllByRole('list')).toHaveLength(2)
    expect(screen.getAllByRole('listitem')).toHaveLength(4)
  })

  it('keeps separate paragraphs and shows an unfinished code block while streaming', () => {
    const { container } = render(<Markdown text={'One.\n\nTwo.\n\n```\nlet x = 1'} />)
    expect(container.querySelectorAll('p')).toHaveLength(2)
    expect(container.querySelector('pre')?.textContent).toBe('let x = 1')
  })

  it('never turns text into HTML or links', () => {
    const { container } = render(<Markdown text={'<img src=x onerror=alert(1)> [click](https://example.com)'} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>')
  })

  it('leaves a half-typed marker as plain text', () => {
    const { container } = render(<Markdown text={'This is **not closed yet'} />)
    expect(container.textContent).toBe('This is **not closed yet')
  })
})
