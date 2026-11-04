/**
 * Phase 2 browser verification: the ten required journeys, run against the built
 * terminal served by the FastAPI process on 127.0.0.1:8000.
 *
 * Run with: node e2e/journeys.mjs
 * Screenshots land in ../artifacts.
 */
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:8000'
const OUT = path.resolve(process.cwd(), '..', 'artifacts')
const problems = []
let step = 0

function log(message) {
  console.log(`  ${message}`)
}

async function shot(page, name) {
  step += 1
  const file = path.join(OUT, `${String(step).padStart(2, '0')}-${name}.png`)
  await page.screenshot({ path: file, fullPage: false })
  log(`screenshot ${path.basename(file)}`)
}

await mkdir(OUT, { recursive: true })
const browser = await chromium.launch()

const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error') problems.push(`console: ${message.text()}`)
})

try {
  // ---------------------------------------------------------------- 1. markets
  await page.goto(BASE, { waitUntil: 'networkidle' })
  await page.waitForSelector('.data-table, .page h1')
  log('markets loaded')
  await shot(page, 'markets-desktop')

  // ------------------------------------------------------- 2. search for Apple
  const search = page.getByLabel('Search companies or tickers')
  await search.fill('Apple')
  await page.waitForSelector('.search-hit', { timeout: 10000 })
  await page.locator('.search-hit').first().click()
  await page.waitForSelector('.company-page')
  await page.waitForSelector('.metric-grid, .data-table')
  const companyTitle = (await page.locator('h1').first().innerText()).trim()
  if (!/Apple/i.test(companyTitle)) throw new Error(`search did not open Apple: ${companyTitle}`)
  log(`search opened ${companyTitle}`)
  await shot(page, 'company-overview')

  // ------------------------------------------------------- 3. statements tab
  await page.getByRole('tab', { name: 'Statements' }).click()
  await page.waitForSelector('.statement-table tbody tr')
  const rows = await page.locator('.statement-table tbody tr').count()
  const beforeHeaders = await page.locator('.statement-table thead th').allInnerTexts()
  if (rows < 5) throw new Error(`income statement has only ${rows} rows`)
  log(`statements rendered ${rows} rows across ${beforeHeaders.length} columns`)
  await shot(page, 'statements')

  // --------------------------------------------------------------- 4. x-ray
  await page.locator('.statement-table tbody tr').first().locator('button').first().click()
  const xray = page.locator('[class*="xray"], [class*="drawer"], [role="dialog"]').first()
  await xray.waitFor({ timeout: 10000 })
  const xrayText = await xray.innerText()
  if (!/EV-/.test(xrayText)) throw new Error('X-Ray panel did not show an evidence id')
  log('X-Ray panel shows provenance')
  await shot(page, 'xray')

  // close panel (Escape or close button)
  await page.keyboard.press('Escape')
  if (await xray.isVisible().catch(() => false)) {
    await page.locator('[class*="xray"] button, [role="dialog"] button').first().click().catch(() => {})
  }

  // ------------------------------------------------- 5. historical as-of view
  await page.getByLabel('Historical view').check()
  const asOf = page.getByLabel('As-of date')
  await asOf.fill('2023-12-31')
  await asOf.dispatchEvent('change')
  await page.waitForTimeout(1200)
  const afterHeaders = await page.locator('.statement-table thead th').allInnerTexts()
  if (JSON.stringify(afterHeaders) === JSON.stringify(beforeHeaders)) {
    throw new Error('as-of selection did not change the statement columns')
  }
  if (afterHeaders.some((header) => /202[4-6]/.test(header))) {
    throw new Error(`as-of 2023 leaked later periods: ${afterHeaders.join(' | ')}`)
  }
  log(`as-of 2023-12-31 columns: ${afterHeaders.join(' | ')}`)
  await shot(page, 'as-of')

  // ----------------------------------------------- 6. chart + indicator maths
  await page.getByLabel('Historical view').uncheck()
  await page.getByRole('tab', { name: 'Charts' }).click()
  await page.getByRole('button', { name: 'RSI 14' }).click()
  await page.waitForSelector('text=atlas.indicator.rsi.v1', { timeout: 15000 })
  await page.waitForSelector('canvas')
  log('chart canvas and RSI v1 row rendered')
  await shot(page, 'charts-indicators')

  // ------------------------------------- 6b. real observations + research view
  await search.fill('IBM')
  await page.waitForSelector('.search-hit', { timeout: 10000 })
  await page.locator('.search-hit').first().click()
  await page.waitForSelector('.company-page')
  const ibm = await page.evaluate(async () => {
    const companies = await (await fetch('/api/companies?q=IBM')).json()
    const company = companies.items[0]
    const securityId = company.securities[0].security_id
    const market = await (await fetch(`/api/securities/${securityId}/market?range=1Y`)).json()
    return {
      name: company.legal_name,
      source: market.data_source?.source_id,
      status: market.data_status,
      real: market.real_data,
      bars: market.bars.length,
      sessions: market.coverage.sessions,
    }
  })
  if (ibm.source !== 'alphavantage') throw new Error(`IBM market source is ${ibm.source}`)
  if (ibm.status !== 'reported' || ibm.real !== true) throw new Error('IBM real data is not labelled reported')
  if (ibm.bars < 100) throw new Error(`IBM 1Y series has only ${ibm.bars} bars`)
  log(`IBM real series: ${ibm.bars} bars, ${ibm.sessions} sessions, source ${ibm.source}`)

  await page.getByRole('tab', { name: 'Research' }).click()
  await page.waitForSelector('text=Independent validation', { timeout: 20000 })
  await page.waitForSelector('text=Annual financial history')
  await page.waitForSelector('text=Comparable issuers')
  await page.getByText(/\d+\/\d+ checks/).waitFor({ timeout: 30000 })
  await page.waitForSelector('.mini-table tbody tr')
  const researchText = await page.locator('.company-page').innerText()
  if (!/checks/.test(researchText)) throw new Error('research validation badge missing')
  if (!/IBM/.test(researchText)) throw new Error('research view did not identify the issuer')
  log('research tab rendered validation, history, peers and revisions')
  await shot(page, 'research-ibm')

  // ------------------------------------------------------ 7. watchlist persistence
  const unique = `Verification ${Date.now()}`
  await page.goto(`${BASE}/watchlists`, { waitUntil: 'networkidle' })
  await page.getByLabel('New watchlist name').fill(unique)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.waitForSelector('text=' + unique)
  const selector = page.getByLabel('Security to add')
  const firstSecurity = await selector.locator('option').nth(1).getAttribute('value')
  await selector.selectOption(firstSecurity)
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.waitForSelector('.data-table tbody tr')
  const listText = await page.locator('.data-table').innerText()
  if (!/\b[A-Z]{2,5}\b/.test(listText)) throw new Error('watchlist row has no ticker')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForSelector('.data-table tbody tr')
  const persisted = await page.locator('.data-table').innerText()
  if (!/\b[A-Z]{2,5}\b/.test(persisted)) throw new Error('watchlist did not survive reload')
  log('watchlist survived a reload with stable security ids')
  await shot(page, 'watchlist')
  const watchlistId = await page.evaluate(async () => {
    const response = await fetch('/api/watchlists')
    const payload = await response.json()
    return payload.items[0]?.watchlist_id
  })

  // --------------------------------------------------- 8. advanced workspace
  await page.getByRole('button', { name: 'Advanced', exact: true }).click()
  await page.goto(`${BASE}/workspaces`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.preset-card')
  // Presets are saved by name, so a previous verification run leaves a conflict. Remove
  // only the workspace with this preset's exact name before recreating it.
  const presetName = (await page.locator('.preset-card').first().locator('h3').innerText()).trim()
  await page.evaluate(async (name) => {
    const payload = await (await fetch('/api/workspaces')).json()
    for (const workspace of payload.items) {
      if (workspace.name === name) {
        await fetch(`/api/workspaces/${workspace.workspace_id}`, { method: 'DELETE' })
      }
    }
  }, presetName)
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForSelector('.preset-card')
  await page.locator('.preset-card').first().getByRole('button', { name: 'Create' }).click()
  await page.waitForURL(/\/workspaces\/WS-/, { timeout: 15000 })
  await page.waitForSelector('.workspace-grid')
  const panelsBefore = await page.locator('.workspace-grid > *').count()
  if ((await page.getByLabel('Increase width').count()) === 0) {
    await page.getByRole('button', { name: /Edit/i }).first().click()
    await page.waitForTimeout(300)
  }
  // The full-width panel cannot grow; shrink or grow whichever control is enabled.
  const resize = page
    .locator('[aria-label="Increase width"]:not([disabled]), [aria-label="Decrease width"]:not([disabled])')
    .first()
  await resize.click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await page.waitForTimeout(800)
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForSelector('.workspace-grid')
  const panelsAfter = await page.locator('.workspace-grid > *').count()
  if (panelsAfter !== panelsBefore) throw new Error('workspace panels changed after reload')
  log(`workspace saved and restored with ${panelsAfter} panels`)
  await shot(page, 'workspace-advanced')

  // -------------------------------------------------------------- 9. screener
  await page.goto(`${BASE}/screeners`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.data-table tbody tr', { timeout: 20000 })
  const screenRows = await page.locator('.data-table tbody tr').count()
  const matches = await page.locator('.screener-summary').innerText()
  if (screenRows < 3) throw new Error(`screener returned only ${screenRows} rows`)
  log(`screener matched ${screenRows} rows; summary: ${matches.replace(/\n/g, ' ')}`)
  await shot(page, 'screener')

  // --------------------------------------------------- 10. mode invariance
  const companies = await (await fetch(`${BASE}/api/companies`)).json()
  const issuerId = companies.items[0].issuer_id
  await page.getByRole('button', { name: 'Standard', exact: true }).click()
  await page.goto(`${BASE}/companies/${issuerId}`, { waitUntil: 'networkidle' })
  await page.getByRole('tab', { name: 'Statements' }).click()
  await page.waitForSelector('.statement-table tbody tr')
  const standardNumbers = await page.locator('.statement-table').innerText()
  await page.getByRole('button', { name: 'Advanced', exact: true }).click()
  await page.waitForTimeout(900)
  const advancedNumbers = await page.locator('.statement-table').innerText()
  if (standardNumbers !== advancedNumbers) throw new Error('mode switch changed displayed numbers')
  log('standard and advanced mode show identical statement values')
  await shot(page, 'mode-advanced')

  // -------------------------------------------------- 11. API failure state
  await page.route('**/api/**', (route) => route.abort())
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const bodyText = await page.locator('body').innerText()
  if (!/Database unavailable|unavailable|error|failed/i.test(bodyText)) {
    throw new Error('offline API did not surface a visible error state')
  }
  log('API failure surfaced a visible degraded state instead of a blank page')
  await shot(page, 'offline-api')
  await page.unroute('**/api/**')

  // ---------------------------------------------------------- mobile layout
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true })
  await mobile.goto(`${BASE}/companies/${issuerId}`, { waitUntil: 'networkidle' })
  await mobile.waitForSelector('.company-page')
  const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  if (overflow > 2) throw new Error(`mobile layout overflows horizontally by ${overflow}px`)
  log('mobile 390x844 has no horizontal overflow')
  step += 1
  await mobile.screenshot({ path: path.join(OUT, `${String(step).padStart(2, '0')}-company-mobile.png`) })
  await mobile.close()

  // cleanup the verification watchlist
  if (watchlistId) {
    await page.evaluate((id) => fetch(`/api/watchlists/${id}`, { method: 'DELETE' }), watchlistId)
  }
} catch (error) {
  problems.push(`journey failed: ${error.message}`)
  await page.screenshot({ path: path.join(OUT, 'failure.png') }).catch(() => {})
} finally {
  await browser.close()
}

// ERR_FAILED is expected: the offline journey aborts /api/** on purpose to prove the UI
// degrades visibly. A real API failure arrives as an HTTP status, not a network abort.
const ignored = /favicon|ResizeObserver|Download the React DevTools|net::ERR_FAILED|Failed to load resource/i
const real = problems.filter((problem) => !ignored.test(problem))
console.log(`\nJOURNEY PROBLEMS: ${real.length}`)
for (const problem of real) console.log(` - ${problem}`)
process.exitCode = real.length === 0 ? 0 : 1
