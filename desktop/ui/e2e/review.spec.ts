import { expect, test, type Page } from '@playwright/test'
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const open = (page: Page, hash = '') => page.goto(`/?token=e2e-token-0123456789${hash}`)

function room(name: string): string {
  const dir = join(mkdtempSync(join(tmpdir(), 'dd-room-')), name)
  mkdirSync(dir)
  writeFileSync(join(dir, 'msa.txt'), 'Master services agreement')
  writeFileSync(join(dir, 'nda.txt'), 'NDA')
  return dir
}

async function createProject(page: Page, folder: string) {
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

test('first launch shows the empty state, and the token leaves the address bar', async ({ page }) => {
  await open(page)
  await expect(page.getByText('Start your first review')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()
  expect(page.url()).not.toContain('token=')
})

test('setup: a missing key is requested, tested and accepted', async ({ page }) => {
  await open(page)
  await page.getByLabel('API key').fill('sk-ant-e2e-key-1234')
  await page.getByRole('button', { name: 'Save and test' }).click()
  await expect(page.getByText('Connected.')).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByLabel('API key')).toHaveCount(0)
  await page.reload()
  await expect(page.getByLabel('API key')).toHaveCount(0)
})

test('wrong folder shows a clear error', async ({ page }) => {
  await open(page, '#/new')
  await page.getByLabel('Data room folder').fill('/definitely/not/here')
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('alert')).toContainText('existing absolute folder')
})

test('full review: create, run with live progress, findings, report', async ({ page }) => {
  await createProject(page, room('fast-deal'))
  await page.getByRole('button', { name: 'Run full review' }).click()
  await expect(page.getByRole('progressbar')).toBeVisible()
  await expect(page.getByText('Review in progress')).toBeVisible()
  await expect(page.getByText(/Latest results/)).toBeVisible({ timeout: 30_000 })

  await page.getByRole('tab', { name: 'Findings' }).click()
  await expect(page.getByText('4 findings')).toBeVisible()
  await page.getByLabel('Severity').selectOption('P0')
  await expect(page.getByText('1 findings')).toBeVisible()
  await page.getByText('Change of control needs consent').click()
  await expect(page.getByText('Either party may terminate.')).toBeVisible()

  await page.getByRole('tab', { name: 'Report' }).click()
  await expect(page.frameLocator('iframe[title="Report"]').locator('#r')).toHaveText('Fake report')
})

test('cancel stops a running review', async ({ page }) => {
  await createProject(page, room('slow-deal'))
  await page.getByRole('button', { name: 'Run full review' }).click()
  await expect(page.getByRole('progressbar')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()
  await expect(page.getByRole('button', { name: 'Run full review' })).toBeVisible({ timeout: 20_000 })
})

test('the API rejects a request without the token', async ({ request }) => {
  const res = await request.get('/api/projects')
  expect(res.status()).toBe(401)
})
