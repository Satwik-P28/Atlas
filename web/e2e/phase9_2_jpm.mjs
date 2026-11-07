/**
 * Scenario A — real JPM research from distributable evidence only.
 *
 * JPM's financials come from SEC filings and FR Y-9C/Call Report evidence, both public
 * domain. No authorised market price ships with the repository, so this journey asserts
 * that price-relative analysis is *unavailable* and that Atlas says so instead of inventing
 * or silently substituting a quote.
 */
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:3000'
const OUT = path.resolve(process.cwd(), '..', 'artifacts')
const startedAt = Date.now()
const problems = []
const httpErrors = []
const assert = (condition, message) => {
  if (!condition) throw new Error(message)
}
const numeric = (text) => Number(String(text).replace(/[^0-9.-]/g, ''))
const close = (left, right, tolerance = 0.011) => Math.abs(left - right) <= tolerance

await mkdir(OUT, { recursive: true })
const browser = await chromium.launch({
  headless: true,
  chromiumSandbox: false,
  args: ['--disable-gpu', '--disable-software-rasterizer', '--disable-dev-shm-usage'],
})
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
let page = await context.newPage()
const hook = (target) => {
  target.on('crash', () => problems.push('page crash'))
  target.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
  target.on('console', (message) => {
    if (message.type() === 'error' && !/favicon/.test(message.text())
      && !/Failed to load resource: the server responded with a status of 4\d\d/i.test(message.text())) {
      problems.push(`console: ${message.text()}`)
    }
  })
  target.on('response', (response) => {
    if (response.status() >= 400) httpErrors.push({ status: response.status(), url: response.url() })
  })
  target.on('requestfailed', (request) => {
    if (!/favicon/.test(request.url())) problems.push(`requestfailed: ${request.url()}`)
  })
}
hook(page)

const evidence = {
  schema: 'atlas.phase9_2.browser.jpm.v1',
  scenario: 'real_regulatory_evidence_without_market_price',
  base: BASE,
  assertions: [],
}

async function selectJpm(target) {
  await target.locator('.equity-row').filter({ hasText: 'JPM' }).first().click()
  await target.getByTestId('equity-regulatory-parent').waitFor({ timeout: 30000 })
}

async function generate(target, { roe = '', coe = '', previous = null } = {}) {
  if (roe !== '') await target.getByTestId('equity-roe').fill(roe)
  if (coe !== '') await target.getByTestId('equity-coe').fill(coe)
  const response = target.waitForResponse(
    (item) => item.url().includes('/api/equity/') && new URL(item.url()).pathname.endsWith('/report')
      && item.request().method() === 'POST',
    { timeout: 30000 },
  )
  await target.getByRole('button', { name: 'Recalculate' }).click()
  const answered = await response
  assert(answered.ok(), `recalculation returned ${answered.status()}`)
  await target.getByTestId('equity-value-number').waitFor({ timeout: 30000 })
  if (previous != null) {
    await target.waitForFunction(
      (before) => {
        const node = document.querySelector('[data-testid="equity-value-number"]')
        const value = Number((node?.textContent ?? '').replace(/[^0-9.-]/g, ''))
        return Number.isFinite(value) && Math.abs(value - before) > 0.005
      },
      previous,
      { timeout: 30000 },
    )
  }
  return numeric(await target.getByTestId('equity-value-number').innerText())
}

try {
  const health = await (await page.request.get(`${BASE}/api/health`)).json()
  assert(health.schema_version === 13, `expected schema 13, found ${health.schema_version}`)

  await page.goto(`${BASE}/equity`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Source-grounded equity research' }).waitFor()
  await selectJpm(page)
  const detail = await page.locator('.equity-detail').innerText()
  assert(/JPMORGAN CHASE & CO/.test(detail), 'JPM legal name is not rendered')
  assert(/CIK\s+0000019617/.test(detail), 'JPM CIK is not rendered')
  const parentText = await page.getByTestId('equity-regulatory-parent').innerText()
  assert(/top-tier RSSD\s*1039502/.test(parentText), 'top-tier holding-company RSSD is missing')
  assert(/consolidated/i.test(parentText), 'consolidated basis is not labelled')
  assert(/BHCK2170/.test(parentText) && /4\.00T/.test(parentText), 'FR Y-9C total assets are not visible')
  assert(/BHCAP793/.test(parentText) && /15\.68%/.test(parentText), 'FR Y-9C CET1 ratio is not visible')
  assert(/not a point-in-time/i.test(parentText), 'point-in-time limitation is not visible')
  assert(/FDIC certificate 628/.test(detail), 'FDIC subsidiary certificate 628 is missing')
  assert(/Subsidiary standalone report/.test(detail), 'subsidiary scope is not labelled')
  evidence.assertions.push('A1 real JPM identity, FR Y-9C consolidated 4.00T/15.68%, FDIC CERT 628')
  await page.screenshot({ path: path.join(OUT, 'phase9_2_jpm_desktop.png'), fullPage: true })

  await page.getByTestId('equity-cutoff').fill('2025-06-30')
  await page.getByRole('button', { name: 'Apply cutoff' }).click()
  await page.getByText(/Information cutoff set to 2025-06-30/).waitFor({ timeout: 30000 })
  const baseline = await generate(page)
  const reference = await (await page.request.post(`${BASE}/api/equity/JPM/report`, {
    data: { as_of: '2025-06-30' },
  })).json()
  assert(reference.metadata.as_of === '2025-06-30T00:00:00Z', 'reference report ignored cutoff')
  assert(reference.valuation.market.accounting_period_end === '2024-12-31', 'accounting period changed')
  assert(close(baseline, reference.valuation.institution.outputs.value_per_share), 'rendered baseline differs from API')

  // The critical change: no authorised JPM price exists, and the surface says so.
  const marketCard = await page.getByTestId('equity-market-context').innerText()
  assert(/No observed price matches this issuer/i.test(marketCard),
    `market card did not report unavailability: ${marketCard}`)
  assert(!/\b289\.91\b/.test(marketCard), 'a removed restricted price is still rendered')
  const marketApi = reference.valuation.market
  assert(marketApi.status === 'unavailable', `market status is ${marketApi.status}, expected unavailable`)
  assert(marketApi.price == null, 'an unavailable market comparison returned a price')
  assert(/No observed price/i.test(String(marketApi.reason)), 'API does not explain the missing price')
  evidence.assertions.push('A2 price-relative analysis is unavailable without an authorised observation')

  const modified = await generate(page, { roe: '17', coe: '9.5', previous: baseline })
  const modifiedReference = await (await page.request.post(`${BASE}/api/equity/JPM/report`, {
    data: { as_of: '2025-06-30', assumptions: { sustainable_roe: 0.17, cost_of_equity: 0.095 } },
  })).json()
  assert(modifiedReference.valuation.method === 'residual_income_equity', 'bank method is not residual income')
  assert(close(modified, modifiedReference.valuation.institution.outputs.value_per_share),
    `rendered modified value ${modified} != API ${modifiedReference.valuation.institution.outputs.value_per_share}`)
  evidence.assertions.push(`A3 model reproduction ${baseline.toFixed(4)} -> ${modified.toFixed(4)}`)
  evidence.values = {
    baseline_value_per_share: baseline,
    modified_value_per_share: modified,
    report_sha256: modifiedReference.metadata.report_sha256,
    market_status: marketApi.status,
  }

  await page.getByRole('button', { name: 'Test FCFF DCF' }).click()
  await page.getByRole('heading', { name: 'Valuation declined' }).waitFor({ timeout: 30000 })
  const declined = await page.locator('.equity-detail').innerText()
  assert(/unsupported_methodology|rejected_method/.test(declined), 'FCFF rejection is not visible')
  assert(await page.getByTestId('equity-cutoff').inputValue() === '2025-06-30',
    'rejected method lost the selected cutoff')
  evidence.assertions.push('A4 FCFF rejected for a bank; cutoff preserved')

  await generate(page, { roe: '17', coe: '9.5' })
  const savedValue = numeric(await page.getByTestId('equity-value-number').innerText())
  await page.getByTestId('equity-save').click()
  await page.locator('.banner-ok').filter({ hasText: 'Saved research application' }).waitFor({ timeout: 30000 })
  const savedMessage = await page.locator('.banner-ok').filter({ hasText: 'Saved research application' }).innerText()
  const objectId = savedMessage.match(/URO-APP-[a-z0-9]+/)?.[0]
  assert(objectId, `saved object id missing from: ${savedMessage}`)
  const object = await (await page.request.get(`${BASE}/api/research/objects/${objectId}`)).json()
  const document = object.document
  assert(document.spec.application.cik === '0000019617', 'company identity was not saved')
  assert(document.spec.information_cutoff === '2025-06-30T00:00:00Z', 'cutoff was not saved')
  assert(document.spec.market_context.price_included === false, 'price was marked included')
  assert(document.spec.market_context.export_allowed === false, 'export status was lost')
  assert(document.spec.market_context.observation_pin == null, 'a pin was recorded without an observation')
  assert(!JSON.stringify(document).includes('289.91'), 'removed restricted price leaked into the saved object')
  assert(document.source_ids.includes('sec-edgar') && document.source_ids.includes('fdic-bankfind'),
    'saved source identities are incomplete')
  await page.screenshot({ path: path.join(OUT, 'phase9_2_jpm_saved.png'), fullPage: true })

  await page.close()
  page = await context.newPage()
  hook(page)
  await page.goto(`${BASE}/equity`, { waitUntil: 'networkidle' })
  await selectJpm(page)
  await page.getByRole('button', { name: 'Reopen' }).first().waitFor({ timeout: 30000 })
  await page.getByRole('button', { name: 'Reopen' }).first().click()
  await page.locator('.banner-ok').filter({ hasText: /Reopened .* reproduced/ }).waitFor({ timeout: 30000 })
  const reopenedValue = numeric(await page.getByTestId('equity-value-number').innerText())
  assert(close(reopenedValue, savedValue), `reopened value ${reopenedValue} != saved ${savedValue}`)
  assert(await page.getByTestId('equity-cutoff').inputValue() === '2025-06-30', 'reopen lost cutoff')
  assert(await page.getByTestId('equity-roe').inputValue() === '17', 'reopen lost ROE')
  assert(await page.getByTestId('equity-coe').inputValue() === '9.5', 'reopen lost cost of equity')
  evidence.assertions.push(`A5 ${objectId} saved and reopened at ${reopenedValue.toFixed(4)}`)
  evidence.saved_object_id = objectId

  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 30000 }),
    page.getByRole('button', { name: 'Download package' }).click(),
  ])
  const packagePath = path.join(OUT, 'phase9_2_jpm_application.atlas')
  await download.saveAs(packagePath)
  assert(/\.atlas$/.test(download.suggestedFilename()), 'package download is not .atlas')
  evidence.assertions.push(`A6 exported ${download.suggestedFilename()}`)
  evidence.package_path = 'artifacts/phase9_2_jpm_application.atlas'

  const routes = ['/', '/studio', '/lab', '/lab/learning', '/lab/economic', '/applications', '/equity', '/markets']
  evidence.routes = []
  for (const route of routes) {
    const response = await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' })
    assert(response?.status() === 200, `${route} returned ${response?.status()}`)
    const heading = await page.getByRole('heading').first().innerText().catch(() => '')
    const length = (await page.locator('body').innerText()).length
    assert(length > 100, `${route} rendered an empty page`)
    evidence.routes.push({ route, heading, text_length: length })
  }
  evidence.assertions.push('A7 research surfaces render')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${BASE}/equity`, { waitUntil: 'networkidle' })
  await selectJpm(page)
  await page.getByTestId('equity-cutoff').fill('2025-06-30')
  await page.getByRole('button', { name: 'Recalculate' }).click()
  await page.getByTestId('equity-value-number').waitFor({ timeout: 30000 })
  const mobile = await page.evaluate(() => {
    const clipped = []
    const selectors = [
      '[data-testid="equity-value-number"]',
      '[data-testid="equity-regulatory-parent"]',
      '[data-testid="equity-market-context"]',
      '.equity-metrics input',
      '.equity-saved-panel',
    ]
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (element.scrollWidth > element.clientWidth + 1) {
          clipped.push(`${selector}: ${element.scrollWidth}>${element.clientWidth}`)
        }
      }
    }
    const tables = [...document.querySelectorAll('.table-wrap')].map((element) => ({
      overflowX: getComputedStyle(element).overflowX,
      clippedCells: [...element.querySelectorAll('td, th')]
        .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
        .map((cell) => cell.textContent.trim()),
    }))
    return { scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth, clipped, tables }
  })
  assert(mobile.scrollWidth <= mobile.innerWidth + 1, `mobile page overflows: ${mobile.scrollWidth}`)
  assert(mobile.clipped.length === 0, `mobile content clipped: ${mobile.clipped.join(' | ')}`)
  assert(mobile.tables.every((table) => ['auto', 'scroll'].includes(table.overflowX)),
    'mobile regulatory table is not horizontally reachable')
  assert(mobile.tables.every((table) => table.clippedCells.length === 0), 'mobile table cells are clipped')
  assert(await page.getByTestId('equity-market-context').isVisible(), 'mobile market card is not visible')
  await page.screenshot({ path: path.join(OUT, 'phase9_2_jpm_mobile.png'), fullPage: true })
  evidence.mobile = mobile
  evidence.assertions.push('A8 390x844 no overflow, no clipped values, tables reachable')

  const knownGaps = httpErrors.filter((item) => item.status === 422
    && item.url.includes('/api/economic/panel'))
  const unexpected = httpErrors.filter((item) => !knownGaps.includes(item))
  assert(unexpected.length === 0, `unexpected HTTP errors: ${JSON.stringify(unexpected)}`)
  evidence.health = health
  evidence.known_data_gaps = knownGaps
  evidence.browser_workflow_ms = Date.now() - startedAt
  await writeFile(path.join(OUT, 'phase9_2_jpm_browser.json'), JSON.stringify(evidence, null, 2) + '\n')
} catch (error) {
  await page.screenshot({ path: path.join(OUT, 'phase9_2_jpm_failure.png'), fullPage: true }).catch(() => {})
  console.error('PHASE9_2_JPM FAILURE:', error)
  throw error
} finally {
  await browser.close()
}

if (problems.length) {
  console.error('PHASE9_2_JPM PROBLEMS:', [...new Set(problems)].join(' | '))
  process.exit(1)
}
console.log('PHASE9_2_JPM_EXIT=0')
