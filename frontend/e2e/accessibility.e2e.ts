import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { buyerWithOrganisation, signIn, verifiedProfessional } from './api'

/* Automated accessibility checks (WCAG 2.1 A and AA) on the main screens. Serious and critical problems fail the
   build; the full list of findings is attached to the test report. Automated checks find only part of the problems,
   so keyboard and screen-reader journeys stay in workflows.e2e.ts. */

async function check(page: Page, what: string) {
  await page.waitForLoadState('networkidle')
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 15_000 })
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  await test.info().attach(`axe-${what}.json`, { body: JSON.stringify(results.violations, null, 2), contentType: 'application/json' })
  const blocking = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect.soft(blocking.map((v) => `${v.id}: ${v.help} (${v.nodes.length}) e.g. ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`), `${what} has accessibility problems`).toEqual([])
}

test('public pages have no serious accessibility problems', async ({ page }) => {
  const { pro } = await verifiedProfessional('Axel Access')
  for (const [path, what] of [['/login', 'sign-in'], ['/join', 'join'], ['/professionals', 'browse'],
    [`/professionals/${pro.id}`, 'profile'], ['/categories/finance-and-accounting', 'category']] as const) {
    await page.goto(path)
    await check(page, what)
  }
})

test('signed-in buyer pages have no serious accessibility problems', async ({ page }) => {
  const { account } = await buyerWithOrganisation('Ada Access')
  await signIn(page, account.email)
  for (const [path, what] of [['/app/buyer', 'buyer-home'], ['/app/find', 'find'], ['/app/requests', 'requests'],
    ['/app/payments', 'payments'], ['/app/policies', 'policies']] as const) {
    await page.goto(path)
    await check(page, what)
  }
})
