import { expect, test } from '@playwright/test'
import { buyerWithOrganisation, PASSWORD, verifiedProfessional } from './api'

/* Signed-out discovery keeps the visitor's intent: a request to one professional survives sign-in and sign-up, and
   the category page keeps its multi-select specializations in the address. */

test('a signed-out request to a professional lands on the request after sign-in', async ({ page }) => {
  const { pro } = await verifiedProfessional('Ira Intent')
  const { account: buyer } = await buyerWithOrganisation('Lena Intent')
  await page.goto(`/professionals/${pro.id}`)
  await page.getByRole('link', { name: 'Sign in to request a proposal' }).click()
  await expect(page).toHaveURL(/\/login\?next=/)
  await page.getByLabel('Work email').fill(buyer.email)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/app/requests/new\\?pro=${pro.id}$`))
})

test('a deep link while signed out keeps its query through sign-up', async ({ page }) => {
  const { pro } = await verifiedProfessional('Ira Deeplink')
  await page.goto(`/app/requests/new?pro=${pro.id}`)
  await expect(page).toHaveURL(/\/login$/)
  await page.getByRole('link', { name: 'Create an account' }).click()  // carries the full destination on to sign-up
  await expect(page).toHaveURL(/\/join\?next=/)
  await page.getByLabel('Full name').fill('Nia Newbuyer')
  await page.getByLabel('Work email').fill(`nia-${Date.now()}@example.com`)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(new RegExp(`/app/requests/new\\?pro=${pro.id}$`))
})

test('an outside address in next is ignored', async ({ page }) => {
  const { account: buyer } = await buyerWithOrganisation('Lena Redirect')
  await page.goto('/login?next=%2F%2Fevil.example%2Fapp')
  await page.getByLabel('Work email').fill(buyer.email)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/localhost:\d+\/app\//)
})

test('the category page keeps several specializations in the address', async ({ page }) => {
  await page.goto('/finance-accounting')
  await expect(page).toHaveURL(/\/categories\/finance-and-accounting$/)
  await expect(page.getByRole('heading', { name: 'Finance & Accounting', level: 1 })).toBeVisible()
  const filter = page.getByLabel('Filter specializations')
  await filter.fill('Bookkeeping')
  // The address is the state (router update, then render): click and wait for it rather than check() at once.
  await page.getByRole('checkbox', { name: /Bookkeeping/ }).first().click()
  await expect(page.getByRole('checkbox', { name: /Bookkeeping/ }).first()).toBeChecked()
  await filter.fill('Management Accounting')
  await page.getByRole('checkbox', { name: /Management Accounting/ }).first().click()
  await expect(page.getByRole('checkbox', { name: /Management Accounting/ }).first()).toBeChecked()
  await expect(page).toHaveURL(/spec=[a-z-]+%2C[a-z-]+/)
  await expect(page.getByRole('button', { name: /^Remove / })).toHaveCount(2)
  await page.reload()
  await expect(page.getByRole('button', { name: /^Remove / })).toHaveCount(2)
})
