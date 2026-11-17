import { describe, expect, it } from 'vitest'
import { categoryLabel, providerLabel } from '../lib/format'

describe('categoryLabel', () => {
  it('turns a snake_case category into readable words', () => {
    expect(categoryLabel('renewal_terms')).toBe('Renewal terms')
    expect(categoryLabel('change_of_control')).toBe('Change of control')
  })
  it('leaves an already readable category alone', () => {
    expect(categoryLabel('Pricing')).toBe('Pricing')
    expect(categoryLabel('')).toBe('')
  })
})

describe('providerLabel', () => {
  it('names the known providers', () => {
    expect(providerLabel('anthropic')).toBe('Anthropic API')
    expect(providerLabel('bedrock')).toBe('Amazon Bedrock')
    expect(providerLabel('vertex')).toBe('Google Vertex AI')
    expect(providerLabel('gateway')).toBe('Custom gateway')
  })
  it('shows an unknown provider as it is', () => {
    expect(providerLabel('other')).toBe('other')
  })
})
