import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { createProject, open, room } from './helpers'

// All specs share one server. This file is named to sort after review.spec.ts, whose first test needs an empty project list.

/** Fail on serious and critical problems. Minor ones are reported but do not block. */
async function expectAccessible(page: Page, where: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  const blocking = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  test.info().annotations.push(...violations.filter((v) => !blocking.includes(v)).map((v) => ({ type: 'minor', description: `${where}: ${v.id}` })))
  expect(
    blocking.map((v) => `${v.id}: ${v.help} (${v.nodes.length}) [${v.nodes[0]?.target.join(' ')}]`),
    `Accessibility problems on ${where}`,
  ).toEqual([])
}

test('every screen passes the accessibility check', async ({ page }) => {
  await open(page)
  await expect(page.getByRole('button', { name: 'New project' }).first()).toBeVisible()
  await expectAccessible(page, 'the project list')

  await createProject(page, room('a11y-deal'))
  await page.getByRole('button', { name: 'Run full review' }).click()
  await expect(page.getByRole('button', { name: 'Run full review' })).toBeVisible({ timeout: 30_000 })
  for (const tab of ['Overview', 'Findings', 'Report', 'Ask', 'Agents', 'Compare', 'History', 'Screening', 'Settings']) {
    await page.getByRole('tab', { name: tab }).click()
    await expect(page.getByRole('tab', { name: tab, selected: true })).toBeVisible()
    await expectAccessible(page, `the ${tab} tab`)
  }
})

test('the check catches a real problem', async ({ page }) => {
  await open(page)
  await expect(page.getByRole('button', { name: 'New project' }).first()).toBeVisible()
  await page.evaluate(() => document.body.insertAdjacentHTML('beforeend', '<button></button><img src="x.png">'))
  const { violations } = await new AxeBuilder({ page }).analyze()
  expect(violations.map((v) => v.id)).toEqual(expect.arrayContaining(['button-name', 'image-alt']))
})
