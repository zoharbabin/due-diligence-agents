import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { Tabs } from '../components/ui'

const TABS = [
  { id: 'a', label: 'One' },
  { id: 'b', label: 'Two' },
  { id: 'c', label: 'Three' },
]

function Harness() {
  const [active, setActive] = useState('a')
  return <Tabs tabs={TABS} active={active} onChange={setActive} />
}

describe('Tabs keyboard', () => {
  it('only the active tab is in the Tab order', () => {
    render(<Harness />)
    expect(screen.getByRole('tab', { name: 'One' })).toHaveAttribute('tabindex', '0')
    expect(screen.getByRole('tab', { name: 'Two' })).toHaveAttribute('tabindex', '-1')
  })

  it('arrow keys move and select, and wrap around', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    screen.getByRole('tab', { name: 'One' }).focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Two' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'Two' })).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{ArrowLeft}{ArrowLeft}')
    expect(screen.getByRole('tab', { name: 'Three' })).toHaveFocus()
    await user.keyboard('{Home}')
    expect(screen.getByRole('tab', { name: 'One' })).toHaveFocus()
    await user.keyboard('{End}')
    expect(screen.getByRole('tab', { name: 'Three' })).toHaveAttribute('aria-selected', 'true')
  })
})
