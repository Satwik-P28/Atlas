/** Phase 5 browser acceptance: fixed income, portfolio risk, optimization and OOS. */
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:8000'
const OUT = path.resolve(process.cwd(), '..', 'artifacts')
const problems = []
await mkdir(OUT, { recursive: true })
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error' && !/favicon/.test(message.text())) {
    problems.push(`console: ${message.text()}`)
  }
})
const assert = (condition, message) => {
  if (!condition) throw new Error(message)
}
const numeric = (text) => Number(String(text).replace(/[^0-9.-]/g, ''))

try {
  // Independent reference values from the API are compared with the rendered UI.
  const curve = await (await page.request.get(`${BASE}/api/institutional/curve`)).json()
  assert(curve.source.sha256 === '6775840b76cd7fd41121f61d6f6c60184eca6b2ba49954ec7372c463cbeef34d',
    'Treasury source hash changed')
  const reference = await (await page.request.post(`${BASE}/api/institutional/bond`, {
    data: { settlement_date: '2024-07-01', maturity_date: '2029-06-30', coupon_rate: 0.0425 },
  })).json()
  assert(reference.instrument_class === 'hypothetical_fixed_coupon_government_bond',
    'bond response did not disclose hypothetical terms')

  await page.goto(`${BASE}/lab`, { waitUntil: 'networkidle' })
  await page.getByRole('link', { name: 'Risk & pricing' }).click()
  await page.getByRole('heading', { name: 'Institutional research lab' }).waitFor()
  await page.getByRole('heading', { name: 'Zero-coupon curve' }).waitFor()
  assert(await page.locator('#curve-date').inputValue() === '2024-06-28', 'curve date control did not select the loaded ISO date')
  assert(await page.getByText(/Official|Treasury/i).first().isVisible(), 'curve provenance is not visible')

  await page.getByRole('button', { name: 'Calculate bond' }).click()
  const clean = page.getByTestId('bond-clean-price')
  await clean.waitFor({ timeout: 20000 })
  assert(Math.abs(numeric(await clean.innerText()) - reference.clean_price) < 0.000001,
    'rendered clean price differs from the independently requested API value')
  assert(numeric(await page.getByTestId('bond-dv01').innerText()) > 0, 'bond DV01 did not render')
  await page.screenshot({ path: path.join(OUT, '29-institutional-fixed-income.png'), fullPage: true })

  await page.getByRole('button', { name: 'Save fixed income' }).click()
  await page.getByText(/^Saved application /).waitFor({ timeout: 20000 })
  assert(/Saved application/.test(await page.getByTestId('inst-message').innerText()), 'fixed-income save failed')
  const savedApps = await (await page.request.get(`${BASE}/api/institutional/applications`)).json()
  assert(savedApps.items.length > 0, 'saved application is not visible through the API')
  const saved = await (await page.request.get(`${BASE}/api/research/objects/${savedApps.items[0].object_id}`)).json()
  assert(saved.document.spec.application.type === 'fixed_income', 'application type was not preserved')

  // Reopen through the history row, then export the reproducible manifest.
  await page.locator('.lab-history-row').first().click()
  await page.getByText(/^Reopened /).waitFor({ timeout: 20000 })
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export manifest' }).click()
  const download = await downloadPromise
  assert(download.suggestedFilename().endsWith('.json'), 'manifest export was not JSON')

  await page.getByRole('tab', { name: 'Portfolio risk' }).click()
  await page.getByRole('button', { name: 'Run risk' }).click()
  const risk = page.getByTestId('risk-vol')
  await risk.waitFor({ timeout: 20000 })
  const riskText = await risk.innerText()
  assert(numeric(riskText) > 0, `portfolio volatility did not render: ${riskText}`)
  const varText = await page.getByTestId('risk-var').innerText()
  assert(numeric(varText) > 0, `historical VaR must render a positive loss: ${varText}`)
  assert(await page.getByText('Risk decomposition').isVisible(), 'risk contribution analysis is missing')
  await page.screenshot({ path: path.join(OUT, '30-institutional-portfolio-risk.png'), fullPage: true })
  await page.getByRole('button', { name: 'Save risk' }).click()
  await page.getByText(/^Saved application /).waitFor({ timeout: 20000 })
  await page.locator('.lab-history-row').first().click()
  await page.getByText(/^Reopened /).waitFor({ timeout: 20000 })
  await page.getByTestId('risk-vol').waitFor({ timeout: 20000 })
  const riskApps = await (await page.request.get(`${BASE}/api/institutional/applications`)).json()
  const savedRisk = await (await page.request.get(`${BASE}/api/research/objects/${riskApps.items[0].object_id}`)).json()
  assert(savedRisk.document.spec.application.type === 'portfolio_risk', 'portfolio risk application was not preserved')

  await page.getByRole('button', { name: 'Optimize portfolio' }).click()
  await page.getByTestId('optimization-result').waitFor({ timeout: 30000 })
  assert(await page.getByText('Constraint audit').isVisible(), 'optimizer diagnostics are missing')
  await page.screenshot({ path: path.join(OUT, '31-institutional-optimization.png'), fullPage: true })

  await page.getByRole('tab', { name: 'Out-of-sample validation' }).click()
  await page.getByRole('button', { name: 'Run walk-forward' }).click()
  await page.getByTestId('validation-summary').waitFor({ timeout: 60000 })
  const summary = await page.getByTestId('validation-summary').innerText()
  assert(/OOS return/i.test(summary) && /Adjusted p-value/i.test(summary), 'walk-forward summary is incomplete')
  assert(await page.getByText('Every candidate retained').isVisible(), 'attempt log is not rendered')
  await page.getByRole('button', { name: 'Save validation' }).click()
  await page.getByText(/^Saved application /).waitFor({ timeout: 20000 })
  await page.screenshot({ path: path.join(OUT, '32-institutional-walk-forward.png'), fullPage: true })

  await page.getByRole('button', { name: 'Compare latest two' }).click()
  await page.getByText('What is actually supported').waitFor()
  assert(await page.locator('.data-table').last().isVisible(), 'comparison table did not render')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${BASE}/lab/institutional`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Institutional research lab' }).waitFor()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
  if (overflow) throw new Error('Institutional research page overflows a 390px viewport')
  await page.screenshot({ path: path.join(OUT, '33-institutional-mobile.png'), fullPage: true })
} finally {
  await browser.close()
}

if (problems.length) {
  console.error('PHASE5 PROBLEMS:', problems.join(' | '))
  process.exit(1)
}
console.log('PHASE5_EXIT=0')
