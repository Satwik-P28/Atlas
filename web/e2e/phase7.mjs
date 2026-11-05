/** Phase 7 browser acceptance: real weather/demand chain, graph, conflict, scenario, replay, Sentinel. */
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:8001'
const OUT = path.resolve(process.cwd(), '..', 'artifacts')
const problems = []
const assert = (condition, message) => {
  if (!condition) throw new Error(message)
}
const numeric = (text) => Number(String(text).replace(/[^0-9.-]/g, ''))
await mkdir(OUT, { recursive: true })
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error' && !/favicon/.test(message.text())) {
    problems.push(`console: ${message.text()}`)
  }
})

try {
  const catalog = await (await page.request.get(`${BASE}/api/economic/catalog`)).json()
  assert(catalog.counts.observations === 1095, 'expected 1,095 real public observations')
  assert(catalog.counts.edges === 12, 'expected 12 evidence graph edges')
  assert(catalog.counts.conflicts === 1, 'expected the preserved station conflict')
  const runsBefore = await (await page.request.get(`${BASE}/api/economic/runs`)).json()
  const existing = runsBefore.items.find((item) => item.run_id === 'ERUN-ac92ae9ffef03de2')
  assert(existing, 'persisted flagship run is missing')
  assert(existing.stale === false, 'shipped flagship run should start non-stale')
  const full = await (await page.request.get(`${BASE}/api/economic/runs/${existing.run_id}`)).json()
  assert(Math.abs(full.test.r2 + 0.8934655) < 0.0005, 'test R² changed unexpectedly')
  assert(full.causal_status === 'not_identified', 'association was promoted to a causal claim')

  await page.goto(`${BASE}/lab/economic`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Weather, electricity, financial consequence' }).waitFor()
  await page.getByTestId('econ-result').waitFor({ timeout: 30000 })
  assert(await page.getByText('U.S. Energy Information Administration Form EIA-930').isVisible(),
    'EIA source identity is missing')
  assert(await page.getByText('NOAA NCEI GHCN-Daily').isVisible(), 'NOAA source identity is missing')
  assert(await page.getByText('No historical vintage', { exact: true }).isVisible(),
    'historical vintage warning is missing')
  assert(await page.getByRole('heading', { name: 'The coefficient is an association' }).isVisible(),
    'causal boundary is not visible')
  assert(await page.getByText('not identified', { exact: true }).first().isVisible(),
    'causal status is not visible')
  assert(/negative test R²/.test(await page.getByTestId('econ-warning').innerText()),
    'forecast instability warning is missing')
  const r2 = numeric(await page.getByTestId('econ-r2').innerText())
  assert(Math.abs(r2 + 0.893) < 0.002, `rendered R² ${r2} differs from API`)
  const rmse = numeric(await page.getByTestId('econ-rmse').innerText())
  assert(Math.abs(rmse - 2956.58) < 0.5, `rendered RMSE ${rmse} differs from API`)
  await page.screenshot({ path: path.join(OUT, '36-economic-lab.png'), fullPage: true })

  const graphRows = await page.locator('.econ-graph-table tbody tr').count()
  assert(graphRows === 12, `expected 12 graph rows, found ${graphRows}`)
  assert(await page.getByText('Hypothetical Texas manufacturer').isVisible(),
    'hypothetical company identity is missing')
  const conflictText = await page.getByTestId('econ-conflict').innerText()
  assert(/32\.8/.test(conflictText) && /35\.6/.test(conflictText), 'both station values are not visible')
  assert(/No automatic source wins/.test(conflictText), 'conflict policy is missing')

  await page.getByTestId('econ-scenario-result').waitFor()
  await page.getByLabel('Temperature shock (°C)').fill('2')
  const centralResponse = page.waitForResponse(
    (response) => response.url().includes('/scenario') && response.request().method() === 'POST',
  )
  await page.getByTestId('econ-scenario').click()
  assert((await centralResponse).ok(), 'central scenario request failed')
  await page.waitForTimeout(150)
  const firstCost = numeric(await page.getByTestId('econ-cost').innerText())
  assert(Math.abs(firstCost - 37726.3) < 1, `rendered scenario cost ${firstCost} differs from API`)
  await page.getByLabel('Temperature shock (°C)').fill('4')
  const shockedResponse = page.waitForResponse(
    (response) => response.url().includes('/scenario') && response.request().method() === 'POST',
  )
  await page.getByTestId('econ-scenario').click()
  assert((await shockedResponse).ok(), 'shocked scenario request failed')
  await page.waitForTimeout(150)
  const shockedCost = numeric(await page.getByTestId('econ-cost').innerText())
  assert(shockedCost > firstCost + 30000, 'temperature sensitivity did not recompute financial consequence')
  assert(await page.getByText(/Relationship/).first().isVisible(), 'uncertainty components are missing')

  await page.getByTestId('econ-save').click()
  await page.getByText(/^Saved research application /).waitFor({ timeout: 30000 })
  await page.locator('.econ-memory .lab-history-row').first().click()
  await page.getByText(/^Reopened /).waitFor({ timeout: 30000 })

  await page.getByLabel('Cutoff date').fill('2023-12-31')
  await page.getByRole('button', { name: 'Check replay' }).click()
  await page.getByTestId('econ-replay').waitFor({ timeout: 30000 })
  assert(/insufficient evidence/i.test(await page.getByTestId('econ-replay').innerText()),
    'replay invented a 2023 vintage instead of refusing')

  await page.getByRole('button', { name: 'Refresh sentinel' }).click()
  await page.getByText(/Source freshness, dependencies and alerts refreshed/).waitFor({ timeout: 30000 })
  assert((await page.getByTestId('econ-sentinel').innerText()).includes('Automatic retrain: false'),
    'Sentinel safety boundary is missing')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${BASE}/lab/economic`, { waitUntil: 'networkidle' })
  await page.getByTestId('econ-result').waitFor({ timeout: 30000 })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
  if (overflow) throw new Error('Economic Lab overflows a 390px viewport')
  const graphOverflow = await page.locator('.econ-graph-table').evaluate(
    (element) => element.scrollWidth > element.clientWidth + 1,
  )
  assert(!graphOverflow, 'economic graph table is clipped at 390px')
  assert(await page.getByTestId('econ-rmse').isVisible(), 'mobile test metric is clipped')
  await page.screenshot({ path: path.join(OUT, '37-economic-mobile.png'), fullPage: true })

  await page.setViewportSize({ width: 1440, height: 1100 })
  await page.goto(`${BASE}/lab/economic`, { waitUntil: 'networkidle' })
  await page.getByTestId('econ-result').waitFor({ timeout: 30000 })
  await page.getByRole('button', { name: 'Record a 35.7 °C correction drill' }).click()
  await page.getByText(/dependent run\(s\) marked stale/).waitFor({ timeout: 30000 })
  const after = await (await page.request.get(`${BASE}/api/economic/runs/${existing.run_id}`)).json()
  assert(after.stale === true, 'revision did not invalidate the dependent run')
  assert((await page.getByTestId('econ-sentinel').innerText()).includes('observation revised'),
    'Sentinel did not display the stale reason')

  const navigation = await page.evaluate(() => {
    const entries = performance.getEntriesByType('navigation')
    const paints = performance.getEntriesByType('paint')
    const first = entries[0]
    return {
      dom_content_loaded_ms: first ? first.domContentLoadedEventEnd : null,
      load_event_ms: first ? first.loadEventEnd : null,
      response_start_ms: first ? first.responseStart : null,
      transfer_size: first ? first.transferSize : null,
      first_paint_ms: paints.find((p) => p.name === 'first-paint')?.startTime ?? null,
      first_contentful_paint_ms: paints.find((p) => p.name === 'first-contentful-paint')?.startTime ?? null,
      dom_nodes: document.querySelectorAll('*').length,
      viewport: { width: window.innerWidth, height: window.innerHeight },
    }
  })
  await writeFile(path.join(OUT, 'phase7_browser.json'), JSON.stringify({
    schema: 'atlas.phase7.browser.v1',
    base: BASE,
    desktop_viewport: { width: 1440, height: 1100 },
    mobile_viewport: { width: 390, height: 844 },
    navigation,
    graph_rows: graphRows,
    scenario_cost_default: firstCost,
    scenario_cost_4c: shockedCost,
    replay_status: 'insufficient_evidence',
    revision_invalidated_run: after.stale,
    screenshots: ['artifacts/36-economic-lab.png', 'artifacts/37-economic-mobile.png'],
  }, null, 2) + '\n')
} finally {
  await browser.close()
}

if (problems.length) {
  console.error('PHASE7 PROBLEMS:', problems.join(' | '))
  process.exit(1)
}
console.log('PHASE7_EXIT=0')
