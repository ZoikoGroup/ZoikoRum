import { expect, test, type Page } from '@playwright/test'
import { buyerWithOrganisation, engagementAwaitingAcceptance, PASSWORD, verifiedProfessional } from './api'

async function signIn(page: Page, email: string) {
  await page.goto('/login')
  await page.getByLabel('Work email').fill(email)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/app\//)
}

test('a new customer signs up, confirms their email and signs back in', async ({ page }) => {
  const email = `lennox-${Date.now()}@example.com`
  await page.goto('/join')
  await page.getByRole('radio', { name: /Buyer/ }).click()
  await page.getByLabel('Full name').fill('Lennox Shaw')
  await page.getByLabel('Work email').fill(email)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/app\//)

  await expect(page.getByText('Welcome to Zoikorum, Lennox Shaw.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Resend confirmation email' })).toBeVisible()
  // Development mode shows the confirmation link that the email would carry.
  await page.getByRole('link', { name: 'confirm now' }).click()
  await expect(page.getByText(/confirmed/i).first()).toBeVisible()

  await page.goto('/app/account')
  await expect(page.getByText('Confirmed', { exact: true })).toBeVisible()
  await page.locator('.user-menu-pop summary').click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login/)
  await signIn(page, email)
})

test('a customer finds a verified professional and opens their profile', async ({ page }) => {
  const { pro } = await verifiedProfessional('Venky Rao')
  const { account: buyer } = await buyerWithOrganisation('Lennox Find')
  await signIn(page, buyer.email)
  await page.goto('/app/find')
  await page.getByLabel('Search professionals').fill('Venky Rao')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page.getByText('1 professional found')).toBeVisible()
  await expect(page.getByText('Venky Rao').first()).toBeVisible()
  await page.goto(`/professionals/${pro.id}`)
  await expect(page.getByRole('heading', { name: 'Venky Rao' }).first()).toBeVisible()
  await expect(page.getByText('AI/ML engineer for startups').first()).toBeVisible()
})

test('a customer accepts delivered work and downloads the invoice PDF', async ({ page }) => {
  const { account: pro, pro: profile } = await verifiedProfessional('Venky Deliver')
  const { account: buyer, org } = await buyerWithOrganisation('Lennox Accept')
  const { contract } = await engagementAwaitingAcceptance(buyer, org, pro, profile.id)

  await signIn(page, buyer.email)
  await page.goto(`/app/engagements/${contract.id}`)
  await page.getByRole('tab', { name: /Milestones/ }).click()
  page.once('dialog', (d) => d.accept())  // "Accept M1 …? This releases … from escrow"
  await page.getByRole('button', { name: 'Accept milestone' }).first().click()
  await expect(page.getByText(/Milestone accepted/)).toBeVisible()

  await page.getByRole('tab', { name: 'Agreement' }).click()
  const agreement = page.waitForEvent('download')
  await page.getByRole('button', { name: /Download PDF/ }).click()
  expect((await agreement).suggestedFilename()).toBe(`${contract.reference}-v1.pdf`)

  await page.goto('/app/payments')
  await page.getByRole('tab', { name: /Invoices/ }).click()
  await expect(page.getByText(/ZK-INV-\d{6}/)).toBeVisible({ timeout: 20_000 })
  const invoice = page.waitForEvent('download')
  await page.getByRole('button', { name: 'PDF' }).first().click()
  expect((await invoice).suggestedFilename()).toMatch(/^ZK-INV-\d{6}\.pdf$/)
})
