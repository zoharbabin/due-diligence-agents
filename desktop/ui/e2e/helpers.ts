import { expect, type Page } from '@playwright/test'
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export const open = (page: Page, hash = '') => page.goto(`/?token=e2e-token-0123456789${hash}`)

export function room(name: string): string {
  const dir = join(mkdtempSync(join(tmpdir(), 'dd-room-')), name)
  mkdirSync(dir)
  writeFileSync(join(dir, 'msa.txt'), 'Master services agreement')
  writeFileSync(join(dir, 'nda.txt'), 'NDA')
  return dir
}

export async function createProject(page: Page, folder: string) {
  await open(page)
  await page.getByRole('button', { name: 'New project' }).first().click()
  await page.getByLabel('Data room folder').fill(folder)
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByText(/Found 2 files/)).toBeVisible()
  await page.getByLabel('Buyer').fill('Buyer Co')
  await page.getByLabel('Target company').fill('Target Co')
  await page.getByRole('button', { name: 'Create project' }).click()
  await expect(page.getByRole('button', { name: 'Run full review' })).toBeVisible()
}
