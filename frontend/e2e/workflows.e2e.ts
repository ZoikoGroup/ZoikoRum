import { expect, test } from '@playwright/test'
import {
  approvePending, buyerWithOrganisation, call, credentialInReview, day, engagementAwaitingAcceptance, eventually, proposalRequest, signIn,
  staffMember, verifiedProfessional,
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
  await page.goto('/platform-admin/verification-center')
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
  const opener = page.getByRole('button', { name: /Understanding trust lights/ })
  await opener.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Understanding trust lights' })
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
  const checker = await staffMember('Cy Checker', ['PLATFORM_ADMIN'])  // maker-checker: a second admin approves each change
  await signIn(page, admin.email, { staff: true })
  await page.getByRole('link', { name: 'Feature Controls' }).click()
  await expect(page.getByRole('heading', { name: 'Feature Controls', level: 1 })).toBeVisible()

  const row = page.getByRole('row').filter({ hasText: 'New accounts' })
  await row.getByRole('button', { name: 'Pause', exact: true }).click()
  await page.getByLabel('Reason (recorded in the audit trail)').fill('Fraud wave of fake accounts')
  await page.getByRole('button', { name: 'Request pause' }).click()
  await expect(page.getByText(/Request submitted — awaiting approval by another Platform Admin/)).toBeVisible()
  await expect(row.getByText('On', { exact: true })).toBeVisible()  // nothing changes before approval
  await approvePending(checker, 'Pause: New accounts')
  await page.reload()
  await expect(row.getByText('Paused', { exact: true })).toBeVisible()
  await expect(row.getByText(/Fraud wave of fake accounts/)).toBeVisible()
  const refused = await admin.api.post('/v1/auth/register', { data: {
    email: `paused-${Date.now()}@example.com`, password: 'correct-horse-battery-staple', displayName: 'Paused', country: 'GB',
    accountType: 'BUYER', acceptTerms: true } })
  expect(refused.status()).toBe(503)

  await row.getByRole('button', { name: 'Switch back on' }).click()
  await page.getByLabel('Reason (recorded in the audit trail)').fill('Fraud wave contained')
  await page.getByRole('button', { name: 'Request switch on', exact: true }).click()
  await expect(page.getByText(/Request submitted — awaiting approval/)).toBeVisible()
  await approvePending(checker, 'Switch back on: New accounts')
  await page.reload()
  await expect(row.getByText('On', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Service Health & Workers' }).click()
  await expect(page.getByText('Events waiting').first()).toBeVisible()
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

test('an organisation sets up its first policy from a template and reviews it before activating', async ({ page }) => {
  const { account } = await buyerWithOrganisation('Pia Policy')
  await signIn(page, account.email)
  await page.goto('/app/policies')
  await expect(page.getByRole('heading', { name: 'Set up your first policy' })).toBeVisible()
  await page.getByRole('button', { name: 'Use this template' }).nth(2).click()  // Cross-border
  await expect(page.getByRole('heading', { name: 'Cross-border policy' })).toBeVisible()
  await expect(page.getByLabel('Minimum trust light')).toHaveValue('B')
  await expect(page.getByText('Professional in another country is yes')).toBeVisible()  // the template's rule, in words
  await expect(page.getByText('Before you activate')).toBeVisible()
  await page.getByRole('tab', { name: 'Dashboard' }).click()
  await expect(page.getByRole('heading', { name: 'Policy dashboard' })).toBeVisible()
})

test('a customer posts an open brief, a matching professional is interested, and the customer requests a proposal', async ({ page }) => {
  const { account: pro } = await verifiedProfessional('Venky Brief')
  const { account: buyer } = await buyerWithOrganisation('Lennox Brief')

  await signIn(page, buyer.email)
  await page.goto('/app/briefs')
  await page.getByLabel('What do you need?').fill('Churn prediction model')
  await page.getByLabel('Specialization').selectOption('ai-machine-learning-engineering')
  await page.getByLabel(/^Objective/).fill('Predict which customers will cancel next month')
  await page.getByRole('button', { name: 'Post brief' }).click()
  await expect(page.getByText(/Brief posted/)).toBeVisible()
  await expect(page.getByText('No one has said they are interested yet.')).toBeVisible()

  // The professional sees it (no buyer name) and says they are interested.
  await page.locator('.user-menu-pop summary').click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login/)
  await signIn(page, pro.email)
  await page.goto('/app/professional/briefs')
  const card = page.locator('section').filter({ hasText: 'Churn prediction model' })
  await expect(card.getByText(/Buyer in/)).toBeVisible()
  await card.getByPlaceholder(/short note/).fill('Built churn models for two subscription businesses.')
  await card.getByRole('button', { name: "I'm interested" }).click()
  await expect(card.getByText(/You said you are interested/)).toBeVisible()

  // The buyer picks them and the request form opens with the brief's wording.
  await page.locator('.user-menu-pop summary').click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login/)
  await signIn(page, buyer.email)
  await page.goto('/app/briefs')
  await expect(page.getByText('Built churn models for two subscription businesses.')).toBeVisible()
  await page.getByRole('checkbox', { name: 'Choose Venky Brief' }).check()
  await page.getByRole('link', { name: /Request proposal/ }).click()
  await expect(page).toHaveURL(/\/app\/requests\/new\?pro=.*&brief=/)
  await expect(page.getByLabel('Service needed')).toHaveValue('Churn prediction model')
})

test('both sides keep a task list and schedule a meeting on an engagement', async ({ page }) => {
  const { account: pro, pro: profile } = await verifiedProfessional('Venky Tasks')
  const { account: buyer, org } = await buyerWithOrganisation('Lennox Tasks')
  const { contract } = await engagementAwaitingAcceptance(buyer, org, pro, profile.id)

  await signIn(page, buyer.email)
  await page.goto(`/app/engagements/${contract.id}`)
  await page.getByRole('tab', { name: 'Tasks' }).click()
  await page.getByLabel('Task', { exact: true }).fill('Share last year’s accounts')
  await page.getByRole('button', { name: 'Add' }).click()
  const task = page.getByRole('checkbox', { name: /Share last year’s accounts/ })
  await expect(task).toBeVisible()
  await task.check()
  await expect(task).toBeChecked()

  await page.getByRole('tab', { name: 'Messages' }).click()
  await page.getByRole('button', { name: 'Schedule a meeting' }).click()
  await page.getByLabel('Title').fill('Kick-off call')
  await page.getByLabel(/Your meeting link/).fill('https://example.zoom.us/j/42')
  await page.getByRole('button', { name: 'Schedule', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Join' })).toHaveAttribute('href', 'https://example.zoom.us/j/42')
  await expect(page.getByText(/Meeting scheduled: Kick-off call/)).toBeVisible()
})
