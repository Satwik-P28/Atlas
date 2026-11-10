/**
 * Phase 9.3.1 — research-memo certification on the real interface.
 *
 * Scenario A (JPM): real SEC/FR Y-9C evidence, residual-income valuation, memo creation,
 * claim and integrity inspection, save, export of all three formats, reopen, change check.
 * Scenario B (AAPL): operating-company DCF memo, exports, numerical agreement.
 * Scenario C (mobile 390x844): the same memo surface and the market provenance panel.
 *
 * The journey reads downloaded bytes rather than trusting a download event, and it asserts
 * that the memo it saved is the memo the analyst reviewed (preview hash == saved hash).
 */
import { chromium } from 'playwright'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:3000'
const OUT = path.resolve(process.cwd(), '..', 'artifacts')
const startedAt = Date.now()
const problems = []
const httpErrors = []
const steps = []
const assert = (condition, message) => {
  if (!condition) throw new Error(message)
}
const numeric = (text) => Number(String(text).replace(/[^0-9.-]/g, ''))
const sha256 = (buffer) => createHash('sha256').update(buffer).digest('hex')
const step = (id, detail, data = {}) => steps.push({ id, detail, status: 'pass', ...data })

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
    if (message.type() === 'error' && !/favicon/.test(message.text())) {
      problems.push(`console: ${message.text()}`)
    }
  })
  target.on('response', (response) => {
    if (response.status() >= 500) httpErrors.push({ status: response.status(), url: response.url() })
  })
}
hook(page)

const evidence = {
  schema: 'atlas.phase9_3_1.browser.memo.v1',
  base: BASE,
  steps,
  assertions: [],
}

async function selectIssuer(target, ticker) {
  await target.locator('.equity-row').filter({ hasText: ticker }).first().click()
  await target.getByTestId('equity-regulatory-parent').waitFor({ timeout: 30000 })
}

async function generate(target) {
  const response = target.waitForResponse(
    (item) => item.url().includes('/api/equity/') && new URL(item.url()).pathname.endsWith('/report')
      && item.request().method() === 'POST',
    { timeout: 60000 },
  )
  await target.getByRole('button', { name: 'Recalculate' }).click()
  const answered = await response
  assert(answered.ok(), `recalculation returned ${answered.status()}`)
  await target.getByTestId('equity-value-number').waitFor({ timeout: 60000 })
  return numeric(await target.getByTestId('equity-value-number').innerText())
}

async function buildMemo(target) {
  const response = target.waitForResponse(
    (item) => /\/api\/equity\/.*\/memo$/.test(new URL(item.url()).pathname)
      && item.request().method() === 'POST',
    { timeout: 60000 },
  )
  await target.getByTestId('equity-memo-create').click()
  const answered = await response
  assert(answered.ok(), `memo build returned ${answered.status()}`)
  const built = await answered.json()
  await target.getByTestId('equity-memo-summary').waitFor({ timeout: 60000 })
  return built
}

async function saveMemo(target) {
  const response = target.waitForResponse(
    (item) => /\/api\/equity\/.*\/memo\/save$/.test(new URL(item.url()).pathname),
    { timeout: 60000 },
  )
  await target.getByTestId('equity-memo-save').click()
  const answered = await response
  const saved = await answered.json()
  assert(answered.ok(), `memo save returned ${answered.status()}: ${JSON.stringify(saved)}`)
  return saved
}

async function download(target, format) {
  const [event] = await Promise.all([
    target.waitForEvent('download', { timeout: 60000 }),
    target.getByTestId(`equity-memo-export-${format}`).click(),
  ])
  const file = path.join(OUT, `phase9_3_1_${format}_${event.suggestedFilename()}`)
  await event.saveAs(file)
  const bytes = await readFile(file)
  assert(bytes.length > 500, `${format} download is too small: ${bytes.length} bytes`)
  return { file, bytes, name: event.suggestedFilename() }
}

function inspectExport(format, bytes, memo) {
  const text = bytes.toString('utf8')
  const digest = sha256(bytes)
  const report = { format, bytes: bytes.length, sha256: digest, checks: [] }
  if (format === 'markdown') {
    assert(/^#\s/m.test(text), 'markdown export has no heading')
    assert(/Claim register/.test(text), 'markdown export has no claim register')
    assert(text.includes(memo.content_hash), 'markdown export does not carry the memo hash')
    assert(!/<script/i.test(text), 'markdown export contains a script tag')
    report.checks.push('heading', 'claim register', 'memo hash', 'no script')
  } else if (format === 'html') {
    assert(/^<!DOCTYPE html>/i.test(text), 'html export is not a document')
    assert(!/<script/i.test(text), 'html export contains a script tag')
    assert(!/onerror\s*=/i.test(text), 'html export contains an event handler')
    assert(text.includes(memo.content_hash), 'html export does not carry the memo hash')
    assert(/&lt;script&gt;|<script>alert/.test(text) === false, 'injected script survived export')
    report.checks.push('doctype', 'no script', 'no event handler', 'memo hash')
  } else {
    const body = JSON.parse(text)
    const manifest = body.manifest ?? body.memo?.manifest ?? {}
    const claims = body.memo?.claims ?? body.claims ?? []
    assert(manifest.memo_content_hash === memo.content_hash,
      `json manifest memo hash ${manifest.memo_content_hash} != ${memo.content_hash}`)
    assert(Array.isArray(manifest.evidence_dependencies), 'json manifest has no evidence dependencies')
    assert(claims.length > 0, 'json export has no claims')
    assert(manifest.rights?.redistributable === true || manifest.rights_decision?.redistributable === true,
      'json export does not state a redistributable rights decision')
    report.claims = claims.length
    report.checks.push('manifest hash', 'evidence dependencies', 'claims', 'rights')
  }
  report.sha256 = digest
  return report
}

async function verifyExports(target, memo, objectId) {
  const allowed = memo?.rights?.redistributable === true
  const reports = []
  for (const format of ['markdown', 'html', 'json']) {
    if (!allowed) {
      const api = await target.request.get(
        `${BASE}/api/research/memos/${objectId}/export?format=${format}`)
      assert(api.status() === 422, `a restricted export returned ${api.status()}`)
      const body = await api.json()
      assert(/redistribution/.test(JSON.stringify(body)), 'the refusal does not name redistribution')
      const panel = await target.getByTestId('equity-memo-panel').innerText()
      assert(/Export is refused/.test(panel),
        'the interface does not disclose that export is refused')
      reports.push({ format, refused: true, status: 422 })
      continue
    }
    const file = await download(target, format)
    reports.push({ ...inspectExport(format, file.bytes, memo), file: path.basename(file.file) })
  }
  return { allowed, reports }
}

try {
  const health = await (await page.request.get(`${BASE}/api/health`)).json()
  assert(health.schema_version === 13, `expected schema 13, found ${health.schema_version}`)
  evidence.health = health

  // ---------------------------------------------------------------- Scenario A: JPM
  await page.goto(`${BASE}/equity`, { waitUntil: 'networkidle' })
  await selectIssuer(page, 'JPM')
  await page.getByTestId('equity-cutoff').fill('2025-06-30')
  await page.getByRole('button', { name: 'Apply cutoff' }).click()
  await page.getByText(/Information cutoff set to 2025-06-30/).waitFor({ timeout: 60000 })
  const jpmValue = await generate(page)
  const jpmReport = await (await page.request.post(`${BASE}/api/equity/JPM/report`, {
    data: { as_of: '2025-06-30' },
  })).json()
  assert(jpmReport.valuation.method === 'residual_income_equity', 'JPM method is not residual income')
  assert(jpmReport.valuation.market.status === 'unavailable', 'JPM market status is not unavailable')
  const detail = await page.locator('.equity-detail').innerText()
  assert(/residual income/i.test(detail), 'the report does not name the residual-income method')
  assert(!/non-financial operating company/i.test(detail),
    'the report still describes the bank as a non-financial operating company')
  step('A1', 'JPM identity, cutoff, residual-income method, unavailable price', {
    value: jpmValue, report_sha256: jpmReport.metadata.report_sha256,
  })

  const jpmMemo = await buildMemo(page)
  assert(jpmMemo.claims.length > 0, 'JPM memo has no claims')
  const decision = jpmMemo.integrity.dimensions.decision
  assert(decision.outcome === 'fail', `JPM decision integrity is ${decision.outcome}, expected fail`)
  assert(jpmMemo.integrity.dimensions.statistical.outcome === 'not_applicable',
    'JPM statistical integrity was scored')
  const summary = await page.getByTestId('equity-memo-summary').innerText()
  assert(new RegExp(`${jpmMemo.claims.length} claims`).test(summary), 'claim count is not rendered')
  for (const dimension of ['evidence', 'computational', 'statistical', 'decision']) {
    assert(await page.getByTestId(`equity-memo-integrity-${dimension}`).isVisible(),
      `${dimension} integrity is not visible`)
  }
  const decisionText = await page.getByTestId('equity-memo-integrity-decision').innerText()
  assert(/fail/.test(decisionText), 'the decision failure is not shown as a failure')
  step('A2', 'JPM memo built with four integrity dimensions and a visible decision failure', {
    claims: jpmMemo.claims.length, memo_hash: jpmMemo.content_hash,
  })

  const verified = jpmMemo.claims.filter((claim) => claim.verification.outcome === 'verified').length
  assert(verified >= 10, `only ${verified} JPM claims verified`)
  const citation = jpmMemo.citations.evidence.find((item) => item.status === 'resolved')
  assert(citation && citation.accession_number && citation.evidence_id,
    'no resolved evidence citation with an accession number')
  assert(citation.passage === null && citation.passage_reason,
    'an unsupported passage was invented instead of stating why it is absent')
  step('A3', 'claim verification and resolvable citations', { verified, citation: citation.evidence_id })

  const savedJpm = await saveMemo(page)
  assert(savedJpm.memo.content_hash === jpmMemo.content_hash,
    'the saved memo differs from the reviewed preview (preview/save divergence)')
  const storedJpm = await (await page.request.get(`${BASE}/api/research/memos/${savedJpm.object_id}`)).json()
  assert(storedJpm.memo.content_hash === jpmMemo.content_hash,
    'stored memo hash differs from the reviewed preview')
  assert(storedJpm.memo.claims.length === jpmMemo.claims.length, 'stored claim count differs')
  step('A4', `saved ${savedJpm.object_id} v${savedJpm.version} on the reviewed hash`, {
    object_id: savedJpm.object_id, content_hash: savedJpm.content_hash,
  })
  await page.screenshot({ path: path.join(OUT, 'phase9_3_1_jpm_memo_desktop.png'), fullPage: true })

  const jpmExportCheck = await verifyExports(page, jpmMemo, savedJpm.object_id)
  const values = jpmMemo.claims
    .filter((claim) => claim.claim_type === 'model_output')
    .map((claim) => String(claim.value))
  if (jpmExportCheck.allowed) {
    const jsonReport = jpmExportCheck.reports.find((item) => item.format === 'json')
    const exportedJson = JSON.parse(String((await readFile(
      path.join(OUT, jsonReport.file))).toString('utf8')))
    const exportedClaims = exportedJson.memo?.claims ?? exportedJson.claims ?? []
    for (const claim of exportedClaims) {
      assert(claim.claim_type && claim.verification?.outcome, 'exported claim lost its type or outcome')
    }
    assert(exportedClaims.length === jpmMemo.claims.length, 'exported claim count differs from the memo')
  }
  step('A5', 'export paths verified with the rights decision enforced', {
    exports: jpmExportCheck.reports, allowed: jpmExportCheck.allowed, values,
  })

  const changeResponse = page.waitForResponse(
    (item) => /\/api\/research\/memos\/.*\/check$/.test(new URL(item.url()).pathname),
    { timeout: 60000 },
  )
  await page.getByTestId('equity-memo-check').click()
  const changeReport = await (await changeResponse).json()
  await page.getByTestId('equity-memo-change').waitFor({ timeout: 30000 })
  assert(changeReport.status === 'unchanged', `an untouched memo reports ${changeReport.status}`)
  assert(changeReport.review_required === false, 'an untouched memo requires review')
  assert(/Review required: no/.test(await page.getByTestId('equity-memo-change-review').innerText()),
    'the interface does not state that no review is required')
  step('A6', 'evidence-change check reports unchanged and does not rewrite the memo')

  await page.close()
  page = await context.newPage()
  hook(page)
  await page.goto(`${BASE}/equity`, { waitUntil: 'networkidle' })
  await selectIssuer(page, 'JPM')
  const listed = await (await page.request.get(`${BASE}/api/research/memos`)).json()
  assert((listed.items ?? []).some((item) => item.object_id === savedJpm.object_id),
    'the saved memo is not listed after a reload')
  const reopened = await (await page.request.get(`${BASE}/api/research/memos/${savedJpm.object_id}`)).json()
  assert(reopened.memo.content_hash === jpmMemo.content_hash, 'the reopened memo changed its hash')
  const reopenedDecision = reopened.memo.integrity.dimensions.decision.outcome
  assert(reopenedDecision === 'fail', 'the reopened memo no longer reports the decision failure')
  step('A7', 'saved memo reopened after a reload with the same hash and outcome')

  // --------------------------------------------------------------- Scenario B: AAPL
  await page.goto(`${BASE}/equity`, { waitUntil: 'networkidle' })
  await selectIssuer(page, 'AAPL')
  const aaplValue = await generate(page)
  const aaplReport = await (await page.request.post(`${BASE}/api/equity/AAPL/report`, { data: {} })).json()
  assert(aaplReport.valuation.method === 'unlevered_fcff_dcf', 'AAPL method is not FCFF DCF')
  const aaplText = await page.locator('.equity-detail').innerText()
  assert(/FCFF|free cash flow/i.test(aaplText), 'the operating-company narrative does not name the DCF')
  assert(!/residual income/i.test(aaplText), 'an operating company is described with residual income')
  const aaplMemo = await buildMemo(page)
  const aaplClaimTypes = new Set(aaplMemo.claims.map((claim) => claim.claim_type))
  for (const type of ['observed_fact', 'derived_financial_metric', 'model_output', 'analyst_assumption']) {
    assert(aaplClaimTypes.has(type), `AAPL memo has no ${type} claim`)
  }
  assert(aaplMemo.integrity.dimensions.evidence.outcome === 'pass', 'AAPL evidence integrity is not a pass')
  const savedAapl = await saveMemo(page)
  assert(savedAapl.memo.content_hash === aaplMemo.content_hash, 'AAPL preview and save diverged')
  const aaplExportCheck = await verifyExports(page, aaplMemo, savedAapl.object_id)
  const aaplExports = aaplExportCheck.reports
  await page.screenshot({ path: path.join(OUT, 'phase9_3_1_aapl_memo_desktop.png'), fullPage: true })
  step('B1', 'AAPL DCF memo saved and exported', {
    value: aaplValue, claims: aaplMemo.claims.length,
    hash: aaplMemo.content_hash, exports: aaplExports,
  })

  // ------------------------------------------------------------- Scenario C: mobile
  const mobile = {}
  await page.setViewportSize({ width: 390, height: 844 })
  for (const [name, route] of [['overview', '/'], ['profile', '/equity'], ['markets', '/markets']]) {
    await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' })
    const layout = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      clipped: [...document.querySelectorAll('[data-testid], .card, .table-wrap')]
        .filter((element) => element.scrollWidth > element.clientWidth + 1
          && getComputedStyle(element).overflowX === 'visible')
        .map((element) => element.getAttribute('data-testid') || element.className)
        .slice(0, 8),
      tables: [...document.querySelectorAll('.table-wrap')].map((element) => getComputedStyle(element).overflowX),
    }))
    assert(layout.scrollWidth <= layout.innerWidth + 1, `${name} overflows: ${layout.scrollWidth}`)
    assert(layout.clipped.length === 0, `${name} clips content: ${layout.clipped.join(' | ')}`)
    assert(layout.tables.every((value) => ['auto', 'scroll'].includes(value)),
      `${name} has an unreachable table`)
    mobile[name] = layout
  }
  await page.goto(`${BASE}/equity`, { waitUntil: 'networkidle' })
  await selectIssuer(page, 'JPM')
  const mobileMemo = await buildMemo(page)
  assert(await page.getByTestId('equity-memo-panel').isVisible(), 'memo panel is not visible at 390x844')
  assert(await page.getByTestId('equity-memo-integrity-decision').isVisible(),
    'integrity is not visible at 390x844')
  const savedMobile = await saveMemo(page)
  assert(savedMobile.memo.content_hash === mobileMemo.content_hash, 'mobile preview and save diverged')
  const mobileExports = await verifyExports(page, mobileMemo, savedMobile.object_id)
  assert(mobileExports.reports.length === 3, 'the mobile export path did not cover all formats')
  const mobileLayout = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    buttons: [...document.querySelectorAll('[data-testid^="equity-memo-"]')]
      .filter((element) => element.offsetParent !== null)
      .map((element) => element.getAttribute('data-testid')),
  }))
  assert(mobileLayout.scrollWidth <= mobileLayout.innerWidth + 1,
    `memo panel overflows at 390x844: ${mobileLayout.scrollWidth}`)
  for (const testid of ['equity-memo-create', 'equity-memo-save', 'equity-memo-export-json']) {
    assert(mobileLayout.buttons.includes(testid), `${testid} is unreachable at 390x844`)
  }
  await page.screenshot({ path: path.join(OUT, 'phase9_3_1_memo_mobile.png'), fullPage: true })
  mobile.memo = mobileLayout
  step('C1', '390x844 overview, profile, markets and memo panel without overflow', { mobile })

  await page.goto(`${BASE}/markets`, { waitUntil: 'networkidle' })
  await page.getByTestId('markettop-provenance-ATLS').click()
  await page.getByTestId('provenance-panel').waitFor({ timeout: 60000 })
  const provenance = await page.getByTestId('provenance-id').innerText()
  assert(/^MOB-[0-9a-f]{24}$/.test(provenance.trim()), `mobile observation id is malformed: ${provenance}`)
  await page.screenshot({ path: path.join(OUT, 'phase9_3_1_provenance_mobile.png'), fullPage: true })
  step('C2', 'synthetic market provenance is reachable and identified at 390x844')

  const unexpected = httpErrors.filter((item) => !/favicon/.test(item.url))
  assert(unexpected.length === 0, `unexpected server errors: ${JSON.stringify(unexpected)}`)
  evidence.steps = steps
  evidence.problems = [...new Set(problems)]
  evidence.assertions = steps.map((item) => item.id)
  evidence.duration_ms = Date.now() - startedAt
  await writeFile(path.join(OUT, 'phase9_3_1_browser_acceptance.json'),
    JSON.stringify(evidence, null, 2) + '\n')
} catch (error) {
  await page.screenshot({ path: path.join(OUT, 'phase9_3_1_memo_failure.png'), fullPage: true }).catch(() => {})
  steps.push({ id: 'FAILED', detail: String(error?.message ?? error), status: 'fail' })
  await writeFile(path.join(OUT, 'phase9_3_1_browser_acceptance.json'),
    JSON.stringify({ ...evidence, steps, problems: [...new Set([...problems, String(error?.message)])] }, null, 2)
      + '\n')
  console.error('PHASE9_3_1_MEMO FAILURE:', error)
  throw error
} finally {
  await browser.close()
}

if (problems.length) {
  console.error('PHASE9_3_1_MEMO PROBLEMS:', [...new Set(problems)].join(' | '))
  process.exit(1)
}
console.log('PHASE9_3_1_MEMO_EXIT=0')
