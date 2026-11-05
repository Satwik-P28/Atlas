/** Phase 6 browser acceptance: experiment, calibration, audit, forecast-to-portfolio, memory, mobile. */
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
  const catalog = await (await page.request.get(`${BASE}/api/learning/catalog`)).json()
  assert(catalog.datasets.length === 1, 'expected one real demo dataset')
  assert(catalog.datasets[0].securities === 5, 'demo panel should have five securities')
  assert(catalog.datasets[0].point_in_time_verified === false, 'demo panel must not claim point-in-time verification')
  const runsBefore = await (await page.request.get(`${BASE}/api/learning/runs`)).json()
  const existing = runsBefore.items.find((item) => item.run_id === 'LRUN-5465504d8d6a287fade6')
  assert(existing, 'the persisted real-data run is missing')
  assert(existing.test_brier > 0.24 && existing.test_brier < 0.25, 'real-data Brier changed unexpectedly')

  await page.goto(`${BASE}/lab/learning`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Learning Lab' }).waitFor()
  await page.getByTestId('learn-dataset-name').waitFor()
  assert(/EODHD demo market observations/.test(await page.getByTestId('learn-dataset-name').innerText()),
    'dataset identity is not visible')
  assert(await page.getByText(/restricted rights/).isVisible(), 'dataset rights are not visible')
  assert(await page.getByText('Not point-in-time verified', { exact: true }).isVisible(), 'historical-vintage badge is missing')

  await page.getByRole('button', { name: 'Run experiment' }).click()
  await page.getByTestId('learning-result').waitFor({ timeout: 60000 })
  const brierText = await page.getByTestId('learn-brier').innerText()
  assert(Math.abs(numeric(brierText) - existing.test_brier) < 0.0005,
    `rendered Brier ${brierText} differs from API ${existing.test_brier}`)
  assert(/not supported/i.test(await page.getByTestId('learning-result').innerText()),
    'negative conclusion is not visible')
  assert(await page.getByText('Reliability on the untouched test').isVisible(), 'calibration section is missing')
  assert(await page.getByText('Specific findings, not a score').isVisible(), 'audit section is missing')
  assert(await page.getByText('Restricted vendor data stays in the local database').isVisible(),
    'data-rights limitation is missing')

  await page.getByRole('button', { name: 'Run portfolio rule' }).click()
  await page.getByTestId('learning-portfolio').waitFor({ timeout: 60000 })
  const portfolioText = await page.getByTestId('learning-portfolio').innerText()
  assert(/14\.38%/.test(portfolioText), `portfolio return did not render: ${portfolioText.slice(0, 300)}`)
  assert(/Accounting reconciled: true/.test(portfolioText), 'portfolio ledger did not reconcile')
  await page.screenshot({ path: path.join(OUT, '34-learning-lab.png'), fullPage: true })

  await page.getByRole('button', { name: 'Check monitor' }).click()
  await page.getByTestId('learning-monitor').waitFor({ timeout: 60000 })
  assert(await page.getByText('No automatic retraining or deployment.').isVisible(),
    'monitor safety boundary is missing')
  await page.getByRole('button', { name: 'Save application' }).click()
  await page.getByText(/^Saved research application /).waitFor({ timeout: 30000 })
  const applications = await (await page.request.get(`${BASE}/api/learning/applications`)).json()
  assert(applications.items.length >= 1, 'saved learning application is not in the API')

  await page.locator('.lab-history-row').first().click()
  await page.getByText(/^Reopened /).waitFor({ timeout: 30000 })
  await page.getByTestId('learning-result').waitFor({ timeout: 30000 })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${BASE}/lab/learning`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Learning Lab' }).waitFor()
  await page.locator('.lab-history-row').first().click()
  await page.getByTestId('learning-result').waitFor({ timeout: 30000 })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
  if (overflow) throw new Error('Learning Lab overflows a 390px viewport')
  assert(await page.getByTestId('learn-brier').isVisible(), 'mobile Brier is clipped')
  await page.screenshot({ path: path.join(OUT, '35-learning-mobile.png'), fullPage: true })
} finally {
  await browser.close()
}

if (problems.length) {
  console.error('PHASE6 PROBLEMS:', problems.join(' | '))
  process.exit(1)
}
console.log('PHASE6_EXIT=0')
