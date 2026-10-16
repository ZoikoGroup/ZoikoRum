import { expect, test } from '@playwright/test'
import { buyerWithOrganisation, credentialInReview, signIn, staffMember, verifiedProfessional } from './api'

test('reviewer filters all cases by person and opens the correct case', async ({ page }) => {
  const officer = await staffMember('Glitch Reviewer', ['COMPLIANCE_OFFICER'])
  const first = await credentialInReview('Review Person Alpha')
  const second = await credentialInReview('Review Person Beta')
  await signIn(page, officer.email, { staff: true })
  await page.goto('/app/ops/verification')
  await expect(page.getByLabel('Professional or firm').locator(`option[value="PROFESSIONAL:${first.pro.id}"]`)).toHaveCount(1)
  await page.getByLabel('Professional or firm').selectOption(`PROFESSIONAL:${first.pro.id}`)
  await expect(page.getByRole('row').filter({ hasText: 'Review Person Alpha' })).toHaveCount(1)
  await expect(page.getByRole('row').filter({ hasText: 'Review Person Beta' })).toHaveCount(0)
  await page.getByLabel('Professional or firm').selectOption(`PROFESSIONAL:${second.pro.id}`)
  await page.getByRole('row').filter({ hasText: 'Review Person Beta' }).getByRole('button', { name: 'Review', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'CPA (US)', exact: true })).toBeVisible()
  // Only the opened case: the "Second looks" panel on the same page has its own "View professional" links.
  const opened = page.getByRole('region', { name: 'Open verification case' })
  await expect(opened.getByRole('link', { name: 'View professional', exact: true })).toHaveAttribute('href', `/professionals/${second.pro.id}`)
})

test('professional list fits the results container with long expertise labels', async ({ page }) => {
  await verifiedProfessional('Responsive Professional')
  const { account } = await buyerWithOrganisation('Responsive Buyer')
  await signIn(page, account.email)
  for (const width of [1880, 1440, 1024, 700]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/app/find?q=Responsive%20Professional')
    await page.getByRole('button', { name: 'List', exact: true }).click()
    const row = page.locator('.pro-row').filter({ hasText: 'Responsive Professional' }).first()
    await expect(row).toBeVisible()
    const overflow = await row.evaluate(element => {
      const outer = element.getBoundingClientRect()
      return [...element.querySelectorAll('.chip, .pro-facts, .pro-cta, .why-inline li')].some(child => {
        const box = child.getBoundingClientRect()
        const parent = child.classList.contains('chip') ? child.parentElement!.getBoundingClientRect() : outer
        return box.right > outer.right + 1 || box.left < outer.left - 1 || box.right > parent.right + 1
      })
    })
    expect(overflow, `Professional details overflow at ${width}px`).toBe(false)
    await expect(page.getByRole('link', { name: 'Request proposal', exact: true }).first()).toBeVisible()
  }
})

test('mark read updates the notice and bell before the server responds', async ({ page }) => {
  const { account } = await buyerWithOrganisation('Notification Buyer')
  const notice = { id: 'test-notice', title: 'Review this update', body: 'An update', url: '/app/notifications', notice: null, mandatory: false, readAt: null, createdAt: new Date().toISOString(), emailStatus: 'LOCAL' }
  let unread = 1
  let release: (() => void) | undefined
  await page.route('**/v1/notifications/unread-count', route => route.fulfill({ json: { unread } }))
  await page.route('**/v1/notifications', route => route.fulfill({ json: { items: [notice], nextCursor: null } }))
  await page.route('**/v1/notifications/test-notice/read', async route => {
    await new Promise<void>(resolve => { release = resolve })
    unread = 0
    await route.fulfill({ json: { ...notice, readAt: new Date().toISOString() } })
  })
  await signIn(page, account.email)
  await page.goto('/app/notifications')
  await expect(page.getByRole('button', { name: 'Notifications: 1 waiting for you', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Mark Read', exact: true }).click()
  try {
    await expect(page.getByRole('button', { name: 'Notifications', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Mark Read', exact: true })).toHaveCount(0)
    // A count refresh still returns the old server value until the read finishes.
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await expect(page.getByRole('button', { name: 'Notifications', exact: true })).toBeVisible()
    await expect.poll(() => !!release).toBe(true)
  } finally { release?.() }
})
