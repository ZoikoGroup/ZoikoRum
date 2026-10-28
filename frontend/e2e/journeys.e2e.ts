import { expect, test } from '@playwright/test'
import { buyerWithOrganisation, engagementAwaitingAcceptance, PASSWORD, signIn, verifiedProfessional } from './api'

test('staff and customers each sign in on their own page', async ({ page }) => {
  const { account: buyer } = await buyerWithOrganisation('Lennox Portal')
  await page.goto('/staff/login')
  await expect(page.getByRole('heading', { name: 'Zoikorum staff sign-in' })).toBeVisible()
  await page.getByLabel('Work email').fill(buyer.email)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByText(/for Zoikorum staff only/)).toBeVisible()  // a customer account is refused here
  await page.getByRole('link', { name: 'Sign in here' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await signIn(page, buyer.email)
})

test('a new customer signs up, confirms their email and signs back in', async ({ page }) => {
  const email = `lennox-${Date.now()}@example.com`
  await page.goto('/join')
  await page.getByRole('button', { name: /I want to hire/ }).click()
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
  // The exact success message: /confirmed/i would also match the "Not confirmed" badge and move on before the
  // confirmation request finishes (leaving the page then cancels it).
  await expect(page.getByText('Your email is confirmed.')).toBeVisible()

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
  await page.getByRole('button', { name: /^Accept all & release/ }).first().click()
  await page.getByRole('dialog').getByRole('button', { name: 'Accept and release' }).click()  // "This releases … from escrow"
  await expect(page.getByText(/Milestone accepted/)).toBeVisible()

  await page.getByRole('tab', { name: 'Agreement' }).click()
  const agreement = page.waitForEvent('download')
  await page.getByRole('button', { name: /Download PDF/ }).click()
  expect((await agreement).suggestedFilename()).toBe(`${contract.reference}-v1.pdf`)

  // The invoice is issued by the worker a moment after the release; the list loads once, so reload until it is there.
  await expect(async () => {
    await page.goto('/app/payments')
    await page.getByRole('tab', { name: /Invoices/ }).click()
    await expect(page.getByText(/ZK-INV-\d{6}/)).toBeVisible({ timeout: 3_000 })
  }).toPass({ timeout: 30_000 })
  const invoice = page.waitForEvent('download')
  await page.getByRole('button', { name: 'PDF' }).first().click()
  expect((await invoice).suggestedFilename()).toMatch(/^ZK-INV-\d{6}\.pdf$/)
})

test('a customer adds a passkey and signs in with it, no password or code', async ({ page }) => {
  // Chromium's virtual authenticator: a platform passkey that answers with a "fingerprint" automatically.
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('WebAuthn.enable')
  await cdp.send('WebAuthn.addVirtualAuthenticator', { options: {
    protocol: 'ctap2', transport: 'internal', hasResidentKey: true, hasUserVerification: true, isUserVerified: true,
    automaticPresenceSimulation: true } })
  const { account: buyer } = await buyerWithOrganisation('Lennox Passkey')
  await signIn(page, buyer.email)

  await page.goto('/app/security')
  await page.getByRole('button', { name: 'Add a passkey' }).click()
  await page.getByLabel('Name for this passkey (optional)').fill('Test laptop')
  await page.getByLabel('Your password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Create passkey' }).click()
  await expect(page.getByText('Passkey added.')).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'Test laptop' })).toBeVisible()

  await page.locator('.user-menu-pop summary').click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login/)
  await page.getByRole('button', { name: 'Sign in with a passkey' }).click()
  await expect(page).toHaveURL(/\/app\/buyer/)  // signed in: no email, password or code typed
})
