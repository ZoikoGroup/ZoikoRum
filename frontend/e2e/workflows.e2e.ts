import { expect, test } from '@playwright/test'
import {
  buyerWithOrganisation, call, credentialInReview, day, engagementAwaitingAcceptance, eventually, proposalRequest, signIn, staffMember,
  verifiedProfessional,
} from './api'

test('a customer describes what they need and finds a matching professional', async ({ page }) => {
  await verifiedProfessional('Venky Intent')
  const { account: buyer } = await buyerWithOrganisation('Lennox Describe')
  await signIn(page, buyer.email)
  await page.goto('/app/find')
  await page.getByRole('button', { name: 'Describe what you need' }).click()
  // Keyword rules (no AI key in browser tests): "machine learning engineer" -> the specialization, "remote" -> delivery.
  await page.getByLabel('Describe what you need').fill('A machine learning engineer to build a churn model, remote')
  await page.getByRole('button', { name: 'Find matches' }).click()

  const note = page.getByRole('status').filter({ hasText: 'We read your request as:' })
  await expect(note).toBeVisible()
  await expect(note.getByText('Specialization: AI / Machine Learning Engineering')).toBeVisible()
  await expect(note.getByText('Works remotely')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Venky Intent', exact: true })).toBeVisible()
})

test('a professional writes and submits a proposal', async ({ page }) => {
  const { account: pro, pro: profile } = await verifiedProfessional('Venky Propose')
  const { account: buyer, org } = await buyerWithOrganisation('Lennox Request')
  const req = await proposalRequest(buyer, org, profile.id)

  await signIn(page, pro.email)
  await page.goto('/app/professional/requests')
  await page.getByRole('link', { name: 'Respond' }).click()
  await expect(page).toHaveURL(new RegExp(`/app/professional/requests/${req.id}$`))
  await page.getByLabel('Summary for the buyer').fill('I will build and validate a churn model and ship it as a scoring API.')
  await page.getByLabel('Deliverable', { exact: true }).fill('Trained churn model')
  await page.getByLabel('Acceptance criteria').fill('AUC above 0.80 on the hold-out set')
  await page.getByLabel('Milestone', { exact: true }).fill('Model')
  await page.getByLabel('Amount', { exact: true }).fill('12000')
  await page.getByLabel('Due date').fill(day(30))
  await page.getByLabel('Start date').fill(day(10))
  await page.getByLabel('Completion date').fill(day(40))
  await page.getByRole('button', { name: 'Submit proposal' }).click()

  await expect(page.getByText('Proposal sent to the buyer.')).toBeVisible()
  await expect(page.getByText('Awaiting review')).toBeVisible()
  await expect(page.getByText('Total $12,000', { exact: true })).toBeVisible()
  const [received] = await call(buyer, 'GET', `/v1/proposal-requests/${req.id}/proposals`)
  expect(received).toMatchObject({ status: 'SUBMITTED', summary: 'I will build and validate a churn model and ship it as a scoring API.' })
  expect(received.milestones).toMatchObject([{ title: 'Model', amountMinor: 1_200_000 }])
})

test('a customer raises a dispute on submitted work', async ({ page }) => {
  const { account: pro, pro: profile } = await verifiedProfessional('Venky Dispute')
  const { account: buyer, org } = await buyerWithOrganisation('Lennox Dispute')
  const { contract } = await engagementAwaitingAcceptance(buyer, org, pro, profile.id)

  await signIn(page, buyer.email)
  await page.goto(`/app/engagements/${contract.id}`)
  await page.getByRole('button', { name: 'Raise a dispute' }).click()
  const dialog = page.getByRole('dialog', { name: 'Raise a dispute' })
  await dialog.getByLabel(/Category/).selectOption({ label: 'Quality / acceptance' })
  await expect(dialog.getByRole('checkbox', { name: /M1 Model/ })).toBeChecked()  // the submitted milestone is preselected
  await dialog.getByLabel(/Issue summary/).fill('The model scores AUC 0.71 on our hold-out set, below the agreed 0.80.')
  await dialog.getByLabel('Desired outcome').selectOption({ label: 'Rework' })
  await dialog.getByRole('checkbox', { name: /I understand the funds/ }).check()
  await dialog.getByRole('button', { name: 'Submit dispute' }).click()

  await expect(page).toHaveURL(/\/app\/disputes\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('heading', { name: /^Dispute / })).toBeVisible()
  await expect(page.getByText('Evidence collection')).toBeVisible()
  await expect(page.getByText('The model scores AUC 0.71 on our hold-out set, below the agreed 0.80.')).toBeVisible()
})

test('a compliance officer approves a credential in the review queue', async ({ page }) => {
  const officer = await staffMember('Cora Compliance', ['COMPLIANCE_OFFICER'])
  const { account: pro, pro: profile, caseId } = await credentialInReview('Venky Licensed')

  await signIn(page, officer.email, { staff: true })
  await page.goto('/app/ops/verification')
  await page.getByRole('row').filter({ hasText: 'Venky Licensed' }).getByRole('button', { name: 'Review' }).click()
  await expect(page.getByRole('heading', { name: 'CPA (US)' })).toBeVisible()
  await expect(page.getByText('cpa-licence.pdf')).toBeVisible()
  await page.getByLabel('Decision').selectOption('VERIFIED')
  await page.getByLabel('Reason').selectOption('REGISTRY_MATCH')  // standard reasons (verification/reasons.py)
  await page.getByRole('button', { name: 'Record decision' }).click()

  await expect(page.getByText('Decision recorded for CPA (US).')).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'Venky Licensed' })).toHaveCount(0)
  const kase = await call(pro, 'GET', `/v1/verification/cases/${caseId}`)
  expect(kase.status).toBe('VERIFIED')
  await eventually(async () => {
    const [claim] = await call(pro, 'GET', '/v1/professionals/me/credentials')
    return claim?.status === 'VERIFIED'
  }, `the verified credential for ${profile.id}`)
})

test('dialogs work from the keyboard: focus moves in, stays in, Escape closes, focus returns', async ({ page }) => {
  const { account: buyer } = await buyerWithOrganisation('Lennox Keys')
  await signIn(page, buyer.email)
  await page.goto('/app/find?sort=verified')  // the guides show once a search is under way
  const opener = page.getByRole('button', { name: /Understanding Trust Tiers/ })
  await opener.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Understanding Trust Tiers' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Close' })).toBeFocused()
  for (let i = 0; i < 5; i++) {
    await page.keyboard.press('Tab')
    expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true)
  }
  await page.keyboard.press('Shift+Tab')
  expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(opener).toBeFocused()
})

test('an administrator pauses sign-ups during an incident and switches them back on', async ({ page }) => {
  const admin = await staffMember('Ada Operations', ['PLATFORM_ADMIN'])
  await signIn(page, admin.email, { staff: true })
  await page.getByRole('link', { name: 'Switches & Worker' }).click()
  await expect(page.getByRole('heading', { name: 'Switches and Worker' })).toBeVisible()
  await expect(page.getByText('Events waiting')).toBeVisible()

  const row = page.getByRole('row').filter({ hasText: 'New accounts' })
  await row.getByRole('button', { name: 'Pause' }).click()
  await row.getByLabel('Reason (recorded in the audit trail)').fill('Fraud wave of fake accounts')
  await row.getByRole('button', { name: 'Pause now' }).click()
  await expect(row.getByText('Paused', { exact: true })).toBeVisible()
  await expect(row.getByText(/Fraud wave of fake accounts/)).toBeVisible()
  const refused = await admin.api.post('/v1/auth/register', { data: {
    email: `paused-${Date.now()}@example.com`, password: 'correct-horse-battery-staple', displayName: 'Paused', country: 'GB',
    accountType: 'BUYER', acceptTerms: true } })
  expect(refused.status()).toBe(503)

  await row.getByRole('button', { name: 'Switch back on' }).click()
  await row.getByLabel('Reason (recorded in the audit trail)').fill('Fraud wave contained')
  await row.getByRole('button', { name: 'Switch on' }).click()
  await expect(row.getByText('On', { exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/switches.png', fullPage: true })
})

test('an organisation adds its legal entity and the contract names it as the buyer', async ({ page }) => {
  const { account: pro, pro: profile } = await verifiedProfessional('Venky Entity')
  const { account: buyer, org } = await buyerWithOrganisation('Lennox Entity')
  await signIn(page, buyer.email)
  await page.goto('/app/organisation?tab=entities')
  await page.getByRole('button', { name: 'Add legal entity' }).click()
  await page.getByLabel('Registered name').fill('Lennox Analytics Ltd')
  await page.getByLabel('Country of registration').selectOption('GB')
  await page.getByLabel('Company registration number (optional)').fill('09876543')
  await page.getByLabel('Tax ID: VAT, GSTIN, EIN (optional)').fill('GB987654321')
  await page.getByLabel('Registered address').fill('2 Kings Road, Manchester M1 1AA')
  await page.getByRole('button', { name: 'Save' }).click()
  const row = page.getByRole('row').filter({ hasText: 'Lennox Analytics Ltd' })
  await expect(row.getByText('Default')).toBeVisible()  // the first entity is the default

  const { contract } = await engagementAwaitingAcceptance(buyer, org, pro, profile.id)  // a request with no choice: the default
  await page.goto(`/app/engagements/${contract.id}`)
  const parties = page.getByRole('complementary').filter({ hasText: 'Parties' })
  await expect(parties.getByText('Lennox Analytics Ltd')).toBeVisible()
  await expect(parties.getByText(/Reg\. no\. 09876543/)).toBeVisible()
  const document = await buyer.api.get(`/v1/contracts/${contract.id}/document`, { headers: { Authorization: `Bearer ${buyer.token}` } })
  expect(await document.text()).toContain('Buyer: Lennox Analytics Ltd (registration no. 09876543, tax ID GB987654321')
})
