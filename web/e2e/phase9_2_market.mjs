/**
 * Scenario B — synthetic market-data functionality.
 *
 * The committed fixture is an Atlas-authored synthetic ATLS series. This journey exercises
 * price availability, synthetic labelling, provider/revision inspection, exact pinning, an
 * explicit revision update and reproduction. Nothing here may be presented as exchange data.
 */
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { LATEST_SCHEMA_VERSION } from './schema.mjs'
import path from 'node:path'

const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:3000'
const OUT = path.resolve(process.cwd(), '..', 'artifacts')
const startedAt = Date.now()
const problems = []
const httpErrors = []
const assert = (condition, message) => {
  if (!condition) throw new Error(message)
}

await mkdir(OUT, { recursive: true })
const browser = await chromium.launch({
  headless: true,
  chromiumSandbox: false,
  args: ['--disable-gpu', '--disable-software-rasterizer', '--disable-dev-shm-usage'],
})
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
const page = await context.newPage()
page.on('crash', () => problems.push('page crash'))
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error' && !/favicon/.test(message.text())
    && !/Failed to load resource: the server responded with a status of 4\d\d/i.test(message.text())) {
    problems.push(`console: ${message.text()}`)
  }
})
page.on('response', (response) => {
  if (response.status() >= 400) httpErrors.push({ status: response.status(), url: response.url() })
})

const evidence = {
  schema: 'atlas.phase9_2.browser.market.v1',
  scenario: 'synthetic_market_observation_provenance',
  base: BASE,
  assertions: [],
}

try {
  const health = await (await page.request.get(`${BASE}/api/health`)).json()
  assert(
    health.schema_version === LATEST_SCHEMA_VERSION,
    `served schema ${health.schema_version} is not the migration head ${LATEST_SCHEMA_VERSION}`,
  )

  const overview = await (await page.request.get(`${BASE}/api/markets/overview`)).json()
  const series = (overview.items ?? []).find((item) => item.ticker === 'ATLS')
  assert(series, `ATLS synthetic series is not in the market overview: ${(overview.items ?? []).length} securities`)
  const securityId = series.security_id
  evidence.security_id = securityId
  evidence.overview_status = series.data_status
  assert(series.data_status === 'synthetic', `ATLS is labelled ${series.data_status}, expected synthetic`)

  await page.goto(`${BASE}/markets`, { waitUntil: 'networkidle' })
  const banner = await page.locator('.banner-synthetic').innerText()
  assert(/SYNTHETIC price series/i.test(banner), 'the synthetic banner is missing')
  assert(/not exchange data/i.test(banner), 'the synthetic banner does not deny exchange provenance')
  const row = page.locator('tr', { hasText: 'ATLS' }).first()
  await row.waitFor({ timeout: 30000 })
  evidence.assertions.push('B1 ATLS is present and explicitly labelled synthetic')

  await page.getByTestId('markettop-provenance-ATLS').click()
  const panel = page.getByTestId('provenance-panel')
  await panel.waitFor({ timeout: 30000 })
  const observationId = (await page.getByTestId('provenance-id').innerText()).trim()
  const contentHash = (await page.getByTestId('provenance-hash').innerText()).trim()
  assert(/^MOB-[0-9a-f]{24}$/.test(observationId), `observation id is not immutable: ${observationId}`)
  assert(/^[0-9a-f]{64}$/.test(contentHash), `content hash is not a sha256: ${contentHash}`)
  const sourceText = await page.getByTestId('provenance-source').innerText()
  assert(/project_authorized|project_authored/.test(sourceText), `rights class is missing: ${sourceText}`)
  assert(/export allowed/i.test(sourceText), 'exportability is not stated')
  assert(/unadjusted|raw/.test(sourceText), 'adjustment convention is not stated')
  evidence.assertions.push(`B2 provenance ${observationId} with a recomputable hash`)

  const listed = await (await page.request.get(`${BASE}/api/securities/${securityId}/observations`)).json()
  const apiItem = (listed.items ?? []).find((item) => item.observation_id === observationId)
  assert(apiItem, 'the rendered observation is not returned by the observation endpoint')
  const detail = await (await page.request.get(`${BASE}/api/market/observations/${observationId}`)).json()
  assert(detail.identity.observation_id === observationId, 'detail identity differs from the browser')
  assert(detail.session.revision_seq === apiItem.revision_seq, 'revision differs between list and detail')
  assert(detail.pin.observation_id === observationId, 'the detail does not expose a replayable pin')
  assert(detail.source.export_allowed === true, 'project-authored synthetic data must stay exportable')
  evidence.assertions.push('B3 browser identity equals the API identity')

  const replay = await (await page.request.post(`${BASE}/api/market/replay`, {
    data: { pin: detail.pin, information_cutoff: '2024-12-13' },
  })).json()
  assert(replay.status === 'exact' && replay.exact_replay === true, `pin replay is ${replay.status}`)
  assert(replay.price.close === apiItem.close, 'replayed close differs from the stored observation')
  const tampered = { ...detail.pin, revision_seq: 99 }
  const missing = await (await page.request.post(`${BASE}/api/market/replay`, { data: { pin: tampered } })).json()
  assert(missing.status === 'exact_revision_unavailable', `a missing revision reported ${missing.status}`)
  assert(missing.price === null, 'a missing pinned revision was replaced with another price')
  evidence.assertions.push('B4 exact replay, and a missing pin is never substituted')

  await page.getByTestId('provenance-pin').click()
  await page.getByTestId('provenance-status').filter({ hasText: 'Pinned' }).waitFor({ timeout: 15000 })
  await page.getByTestId('provenance-copy').click()
  await page.waitForTimeout(250)
  const status = await page.getByTestId('provenance-status').innerText()
  assert(/Pinned|Copied|Clipboard unavailable/.test(status), `copy/pin feedback is missing: ${status}`)
  const revisions = await page.getByTestId('provenance-revisions').innerText()
  assert(/r1/.test(revisions), 'the revision chain does not name revision 1')
  const conflicts = await page.getByTestId('provenance-conflicts').innerText()
  assert(/No competing provider observation|providers disagree/i.test(conflicts), 'provider comparison is missing')
  await page.getByTestId('provenance-replay').click()
  const replayCard = page.getByTestId('provenance-replay-result')
  await replayCard.waitFor({ timeout: 30000 })
  const replayText = await replayCard.innerText()
  assert(/exact replay\s*yes/i.test(replayText), `panel replay is not exact: ${replayText}`)
  assert(/pin status\s*exact/i.test(replayText), `panel pin status is not exact: ${replayText}`)
  evidence.assertions.push('B5 pin, copy, revision and provider inspection work in the interface')
  await page.screenshot({ path: path.join(OUT, 'phase9_2_market_desktop.png'), fullPage: true })

  // Save and reopen a research object that carries the exact observation dependency.
  const saveResponse = await page.request.post(`${BASE}/api/research/objects`, {
    data: {
      document: {
        schema_version: 'atlas.research_object.v1',
        kind: 'dataset',
        name: 'Synthetic ATLS pinned observation',
        version: '1.0.0',
        status: 'draft',
        description: 'Records the exact synthetic observation revision used by the study.',
        as_of: `${apiItem.session_date}T00:00:00Z`,
        mode: 'atlas_ingested',
        evidence_ids: [],
        source_ids: [apiItem.source_id],
        spec: { universe: ['ATLS'], fields: ['close'], frequency: 'daily', adjustment: 'raw', observation_pin: detail.pin },
      },
    },
  })
  const saved = await saveResponse.json()
  // The object is content-addressed: a repeated run re-opens the identical version instead
  // of failing on the duplicate, so the journey proves idempotent persistence.
  let objectId = saved.object_id
  if (!saveResponse.ok()) {
    assert(saveResponse.status() === 422, `saving the pinned object failed: ${JSON.stringify(saved)}`)
    objectId = saved?.error?.context?.object_id
    assert(objectId, `the duplicate response does not name the existing object: ${JSON.stringify(saved)}`)
  }
  const reopened = await (await page.request.get(`${BASE}/api/research/objects/${objectId}`)).json()
  const storedPin = reopened.document.spec.observation_pin
  assert(storedPin.observation_id === detail.pin.observation_id, 'the saved object lost the pin')
  const replayed = await (await page.request.post(`${BASE}/api/market/replay`, {
    data: { pin: storedPin },
  })).json()
  assert(replayed.exact_replay === true, 'the reopened object no longer replays exactly')
  assert(replayed.price.close === apiItem.close, 'reopened replay changed the observation')
  evidence.saved_object_id = objectId
  evidence.assertions.push(`B6 ${objectId} saved and reopened on the pinned revision`)

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${BASE}/markets`, { waitUntil: 'networkidle' })
  await page.getByTestId('markettop-provenance-ATLS').click()
  await page.getByTestId('provenance-panel').waitFor({ timeout: 30000 })
  const mobile = await page.evaluate(() => {
    const clipped = []
    for (const selector of ['[data-testid="provenance-id"]', '[data-testid="provenance-panel"]', '.source-card']) {
      for (const element of document.querySelectorAll(selector)) {
        if (element.scrollWidth > element.clientWidth + 1 && getComputedStyle(element).overflowX === 'visible') {
          clipped.push(`${selector}: ${element.scrollWidth}>${element.clientWidth}`)
        }
      }
    }
    return { scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth, clipped }
  })
  assert(mobile.scrollWidth <= mobile.innerWidth + 1, `mobile page overflows: ${mobile.scrollWidth}`)
  assert(mobile.clipped.length === 0, `mobile provenance content clipped: ${mobile.clipped.join(' | ')}`)
  // The panel mounts before its observation resolves; wait for the action itself rather
  // than sampling visibility while the loading state is still rendered.
  await page.getByTestId('provenance-pin').waitFor({ state: 'visible', timeout: 30000 })
  await page.screenshot({ path: path.join(OUT, 'phase9_2_market_mobile.png'), fullPage: true })
  evidence.mobile = mobile
  evidence.assertions.push('B7 390x844 provenance panel fits without document overflow')

  const unexpected = httpErrors.filter((item) => !/favicon/.test(item.url))
  assert(unexpected.length === 0, `unexpected HTTP errors: ${JSON.stringify(unexpected)}`)
  evidence.health = health
  evidence.browser_workflow_ms = Date.now() - startedAt
  await writeFile(path.join(OUT, 'phase9_2_market_browser.json'), JSON.stringify(evidence, null, 2) + '\n')
} catch (error) {
  await page.screenshot({ path: path.join(OUT, 'phase9_2_market_failure.png'), fullPage: true }).catch(() => {})
  console.error('PHASE9_2_MARKET FAILURE:', error)
  throw error
} finally {
  await browser.close()
}

if (problems.length) {
  console.error('PHASE9_2_MARKET PROBLEMS:', [...new Set(problems)].join(' | '))
  process.exit(1)
}
console.log('PHASE9_2_MARKET_EXIT=0')
