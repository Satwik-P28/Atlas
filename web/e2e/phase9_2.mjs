/** Phase 9.2 browser acceptance: consolidated JPM research, cutoff, save/reopen, mobile. */
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
  schema: 'atlas.phase9_2.browser.v1',
  base: BASE,
  viewport: { desktop: '1440x1100', mobile: '390x844' },
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
  assert(health.supported_schema === 13, 'API supported schema is not 13')

  // A/B: real institution page, parent and subsidiary identities.
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
  assert(/FR Y-9C/.test(parentText), 'FR Y-9C form identity is missing')
  assert(/not present in the bulk archive/i.test(parentText), 'publication timestamp limitation is not visible')
  assert(/not a point-in-time/i.test(parentText), 'point-in-time limitation is not visible')
  assert(/FDIC certificate 628/.test(detail), 'FDIC subsidiary certificate 628 is missing')
  assert(/Subsidiary standalone report/.test(detail), 'subsidiary scope is not labelled')
  evidence.assertions.push('A/B parent RSSD 1039502, FR Y-9C consolidated 4.00T/15.68%, FDIC CERT 628')
  await page.screenshot({ path: path.join(OUT, 'phase9_2_final_desktop_jpm.png'), fullPage: true })

  // D: explicit cutoff before the first report.
  await page.getByTestId('equity-cutoff').fill('2025-06-30')
  await page.getByRole('button', { name: 'Apply cutoff' }).click()
  await page.getByText(/Information cutoff set to 2025-06-30/).waitFor({ timeout: 30000 })
  const baseline = await generate(page)
  const reference = await (await page.request.post(`${BASE}/api/equity/JPM/report`, {
    data: { as_of: '2025-06-30' },
  })).json()
  assert(reference.metadata.as_of === '2025-06-30T00:00:00Z', 'reference report ignored cutoff')
  assert(reference.valuation.market.price_date === '2025-06-30', 'reference market price is after cutoff')
  assert(reference.valuation.market.accounting_period_end === '2024-12-31', 'accounting period changed')
  assert(reference.valuation.market.lookahead_safe === true, 'reference comparison is not lookahead-safe')
  assert(close(baseline, reference.valuation.institution.outputs.value_per_share), 'rendered baseline differs from API')

  // C: modify ROE and cost of equity, compare rendered result to independent API call.
  const modified = await generate(page, { roe: '17', coe: '9.5', previous: baseline })
  assert(Math.abs(modified - baseline) > 0.01, 'assumption changes did not change the value')
  const modifiedReference = await (await page.request.post(`${BASE}/api/equity/JPM/report`, {
    data: { as_of: '2025-06-30', assumptions: { sustainable_roe: 0.17, cost_of_equity: 0.095 } },
  })).json()
  assert(modifiedReference.valuation.method === 'residual_income_equity', 'bank method is not residual income')
  assert(close(modified, modifiedReference.valuation.institution.outputs.value_per_share),
    `rendered modified value ${modified} != API ${modifiedReference.valuation.institution.outputs.value_per_share}`)
  evidence.assertions.push(`C baseline ${baseline.toFixed(4)} -> modified ${modified.toFixed(4)} matched API`)
  evidence.values = {
    baseline_value_per_share: baseline,
    modified_value_per_share: modified,
    report_sha256: modifiedReference.metadata.report_sha256,
    price: modifiedReference.valuation.market.price,
    price_date: modifiedReference.valuation.market.price_date,
  }

  // D: historical boundary shown in the browser.
  const cutoffValue = await page.getByTestId('equity-cutoff').inputValue()
  assert(cutoffValue === '2025-06-30', 'cutoff was not preserved in the control')
  const marketText = await page.getByTestId('equity-market-context').innerText()
  assert(/289\.91/.test(marketText) && /2025-06-30/.test(marketText),
    'historical market comparison is not rendered')
  evidence.assertions.push('D cutoff 2025-06-30; price 289.91 on 2025-06-30; accounting 2024-12-31')

  // E: unsupported bank DCF must be rejected without dropping the cutoff.
  await page.getByRole('button', { name: 'Test FCFF DCF' }).click()
  await page.getByRole('heading', { name: 'Valuation declined' }).waitFor({ timeout: 30000 })
  const declined = await page.locator('.equity-detail').innerText()
  assert(/unsupported_methodology|rejected_method/.test(declined), 'FCFF rejection is not visible')
  assert(await page.getByTestId('equity-cutoff').inputValue() === '2025-06-30',
    'rejected method lost the selected cutoff')
  evidence.assertions.push('E FCFF rejected as unsupported_methodology; cutoff preserved')

  // F: lawful historical price source and semantics.
  await generate(page, { roe: '17', coe: '9.5' })
  const marketAfter = await page.getByTestId('equity-market-context').innerText()
  assert(/user-market-data/.test(marketAfter), 'market source is missing')
  assert(/unadjusted/.test(marketAfter), 'price adjustment semantics are missing')
  assert(/export allowed:\s*no/i.test(marketAfter), 'restricted export status is missing')
  assert(/mixed-date/i.test(marketAfter), 'mixed-date warning is missing')
  evidence.assertions.push('F market source user-market-data, unadjusted, export denied, mixed date')

  // G: save, close, reopen and reproduce.
  const savedValue = numeric(await page.getByTestId('equity-value-number').innerText())
  await page.getByTestId('equity-save').click()
  await page.locator('.banner-ok').filter({ hasText: 'Saved research application' }).waitFor({ timeout: 30000 })
  const savedMessage = await page.locator('.banner-ok').filter({ hasText: 'Saved research application' }).innerText()
  const objectId = savedMessage.match(/URO-APP-[a-z0-9]+/)?.[0]
  assert(objectId, `saved object id missing from: ${savedMessage}`)
  const object = await (await page.request.get(`${BASE}/api/research/objects/${objectId}`)).json()
  const document = object.document
  assert(document.spec.application.type === 'equity_research', 'saved application type is wrong')
  assert(document.spec.application.cik === '0000019617'
    && /JPMORGAN CHASE/.test(document.spec.application.company), 'company identity was not saved')
  assert(document.spec.information_cutoff === '2025-06-30T00:00:00Z', 'cutoff was not saved')
  assert(document.spec.method === 'residual_income_equity', 'method was not saved')
  assert(document.spec.regulatory_evidence.parent.rssd === 1039502, 'parent RSSD was not saved')
  assert(document.spec.regulatory_evidence.parent.form === 'FR Y-9C', 'FR Y-9C identity was not saved')
  assert(document.spec.regulatory_evidence.subsidiaries.some((item) => item.cert === 628),
    'subsidiary identity was not saved')
  assert(document.spec.market_context.price_included === false, 'restricted price was marked included')
  assert(document.spec.market_context.export_allowed === false, 'restricted export status was lost')
  assert(!JSON.stringify(document).includes('289.91'), 'restricted market price leaked into saved application')
  assert(document.evidence_ids.length > 0, 'saved application has no evidence ids')
  assert(document.source_ids.includes('sec-edgar') && document.source_ids.includes('fdic-bankfind')
    && document.source_ids.includes('ffiec-nic-bhcf'), 'saved source identities are incomplete')
  assert(document.spec.result.report_sha256 === modifiedReference.metadata.report_sha256,
    'saved report hash differs from API reference')
  await page.screenshot({ path: path.join(OUT, 'phase9_2_final_saved.png'), fullPage: true })

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
  const reopenedText = await page.locator('.equity-detail').innerText()
  assert(/residual_income_equity/.test(reopenedText), 'reopen lost method')
  assert(/FR Y-9C/.test(await page.getByTestId('equity-regulatory-parent').innerText()),
    'reopen lost consolidated regulatory evidence')
  evidence.assertions.push(`G ${objectId} saved and reopened at ${reopenedValue.toFixed(4)}`)
  evidence.saved_object_id = objectId
  await page.screenshot({ path: path.join(OUT, 'phase9_2_final_reopened.png'), fullPage: true })

  // H: export the application package used for clean-database reproduction.
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 30000 }),
    page.getByRole('button', { name: 'Download package' }).click(),
  ])
  const packagePath = path.join(OUT, 'phase9_2_application.atlas')
  await download.saveAs(packagePath)
  assert(/\.atlas$/.test(download.suggestedFilename()), 'package download is not .atlas')
  evidence.assertions.push(`H exported ${download.suggestedFilename()}`)
  evidence.package_path = 'artifacts/phase9_2_application.atlas'

  // J: existing research surfaces still render.
  const routes = ['/', '/studio', '/lab', '/lab/learning', '/lab/economic', '/applications', '/equity']
  evidence.routes = []
  for (const route of routes) {
    const response = await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' })
    assert(response?.status() === 200, `${route} returned ${response?.status()}`)
    const heading = await page.getByRole('heading').first().innerText().catch(() => '')
    const length = (await page.locator('body').innerText()).length
    assert(length > 100, `${route} rendered an empty page`)
    evidence.routes.push({ route, heading, text_length: length })
  }
  evidence.assertions.push('J Equity Research, Studio, Lab, Learning Lab, Economic Lab, Applications render')

  // I: 390 x 844 primary workflow.
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
      '[data-testid="equity-value-per-share"]',
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
    const controls = [...document.querySelectorAll('.equity-metrics input, .equity-saved-panel button, .equity-actions button')]
      .map((element) => ({
        tag: element.tagName,
        text: (element.textContent || element.getAttribute('aria-label') || '').trim(),
        width: element.getBoundingClientRect().width,
        height: element.getBoundingClientRect().height,
      }))
    const tables = [...document.querySelectorAll('.table-wrap')].map((element) => ({
      overflowX: getComputedStyle(element).overflowX,
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
      clippedCells: [...element.querySelectorAll('td, th')]
        .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
        .map((cell) => cell.textContent.trim()),
    }))
    return {
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      clipped,
      controls,
      tables,
    }
  })
  assert(mobile.scrollWidth <= mobile.innerWidth + 1, `mobile page overflows: ${mobile.scrollWidth}`)
  assert(mobile.clipped.length === 0, `mobile content clipped: ${mobile.clipped.join(' | ')}`)
  assert(mobile.controls.every((item) => item.width > 40 && item.height >= 24), 'mobile controls are not usable')
  assert(mobile.tables.length > 0, 'mobile regulatory tables are missing')
  assert(mobile.tables.every((table) => ['auto', 'scroll'].includes(table.overflowX)),
    'mobile regulatory table is not horizontally reachable')
  assert(mobile.tables.every((table) => table.clippedCells.length === 0),
    `mobile table cells are clipped: ${JSON.stringify(mobile.tables)}`)
  assert(await page.getByTestId('equity-save').isVisible(), 'mobile save action is not visible')
  assert(await page.getByTestId('equity-market-context').isVisible(), 'mobile market card is not visible')
  await page.screenshot({ path: path.join(OUT, 'phase9_2_final_mobile.png'), fullPage: true })
  evidence.assertions.push('I 390x844 no document overflow, no clipped key values, controls usable')

  const knownGaps = httpErrors.filter((item) => item.status === 422
    && item.url.includes('/api/economic/panel'))
  const unexpectedHttp = httpErrors.filter((item) => !knownGaps.includes(item))
  assert(unexpectedHttp.length === 0, `unexpected HTTP errors: ${JSON.stringify(unexpectedHttp)}`)
  evidence.mobile = mobile
  evidence.health = health
  evidence.known_data_gaps = knownGaps
  evidence.browser_workflow_ms = Date.now() - startedAt
  await writeFile(path.join(OUT, 'phase9_2_browser.json'), JSON.stringify(evidence, null, 2) + '\n')
} catch (error) {
  await page.screenshot({ path: path.join(OUT, 'phase9_2_failure.png'), fullPage: true }).catch(() => {})
  console.error('PHASE9_2 FAILURE:', error)
  throw error
} finally {
  await browser.close()
}

if (problems.length) {
  console.error('PHASE9_2 PROBLEMS:', [...new Set(problems)].join(' | '))
  process.exit(1)
}
console.log('PHASE9_2_EXIT=0')
