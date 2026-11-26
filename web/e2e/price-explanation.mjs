/**
 * Real-browser acceptance for "Explain this move".
 *
 * Run against the Vite dev server (which proxies /api to FastAPI):
 *   cd web && node e2e/price-explanation.mjs
 *
 * The script drives a real Chromium: pointer drags in both directions, one candle,
 * keyboard range selection, wheel zoom with an active band, resize, share-class change,
 * repeated investigations, a delayed API, a forced API error, benchmark-unavailable state,
 * export authorization, and a touch/mobile viewport. Screenshots land in ../artifacts.
 */
import { chromium } from 'playwright'
import { mkdir, readFile, readdir, unlink } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:3002'
const COMPANY = process.env.ATLAS_TICKER ?? 'GOOGL'
const OUT = path.resolve(process.cwd(), '..', 'artifacts')
const LAUNCH = {
  executablePath: process.env.ATLAS_CHROME || undefined,
  args: [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
  ],
}

const problems = []
const checks = []
let shotIndex = 0

function pass(name, detail = '') {
  checks.push({ name, status: 'passed', detail })
  console.log(`  PASS ${name}${detail ? ` — ${detail}` : ''}`)
}

function fail(name, error) {
  const message = error instanceof Error ? error.message : String(error)
  checks.push({ name, status: 'failed', detail: message })
  problems.push(`${name}: ${message}`)
  console.log(`  FAIL ${name} — ${message}`)
}

async function check(name, fn) {
  try {
    await fn()
    pass(name)
  } catch (error) {
    fail(name, error)
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function shot(page, name, fullPage = false) {
  shotIndex += 1
  const file = path.join(OUT, `${String(shotIndex).padStart(2, '0')}-audit-${name}.png`)
  await page.screenshot({ path: file, fullPage })
  return file
}

function watch(page, label) {
  page.__tolerateHttpErrors = false
  page.on('pageerror', (error) => problems.push(`${label} pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() !== 'error') return
    const url = message.location()?.url ?? ''
    if (/favicon\.ico/.test(url)) return
    if (page.__tolerateHttpErrors && /Failed to load resource/.test(message.text())) return
    problems.push(`${label} console: ${message.text()}`)
  })
}

async function openDetail(page, title) {
  const detail = page.locator('.explain-detail', { hasText: title }).first()
  const isOpen = await detail.evaluate((element) => element.open)
  if (!isOpen) await detail.locator('summary').first().click()
  await page.waitForTimeout(100)
}

async function openTicker(page, ticker) {
  await page.goto(`${BASE}/companies/${ticker}`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('tab', { name: 'Charts' }).click()
  await page.getByTestId('explain-range-toggle').waitFor({ timeout: 20000 })
  await page.waitForSelector('canvas')
}

async function openCompany(page) {
  await openTicker(page, COMPANY)
}

async function selectRange(page, start, end) {
  await page.getByLabel('Selection start session').fill(start)
  await page.waitForTimeout(150)
  await page.getByLabel('Selection end session').fill(end)
  await loadedPanel(page)
  await page.waitForTimeout(300)
}

async function enableExplain(page) {
  const toggle = page.getByTestId('explain-range-toggle')
  if ((await toggle.getAttribute('aria-pressed')) !== 'true') await toggle.click()
  await page.waitForSelector('.chart-range-overlay')
  const box = await page.locator('.chart-range-overlay').boundingBox()
  assert(box && box.width > 100 && box.height > 100, 'chart overlay has no usable size')
  return box
}

async function drag(page, fromFraction, toFraction) {
  const box = await page.locator('.chart-range-overlay').boundingBox()
  assert(box, 'no chart overlay')
  const y = box.y + box.height * 0.5
  const x1 = box.x + box.width * fromFraction
  const x2 = box.x + box.width * toFraction
  await page.mouse.move(x1, y)
  await page.mouse.down()
  await page.mouse.move((x1 + x2) / 2, y, { steps: 4 })
  await page.mouse.move(x2, y, { steps: 4 })
  await page.mouse.up()
  await page.waitForSelector('.price-explanation .explain-grid', { timeout: 20000 })
  await page.waitForTimeout(150)
}

async function clickCandle(page, fraction) {
  const box = await page.locator('.chart-range-overlay').boundingBox()
  assert(box, 'no chart overlay')
  const x = box.x + box.width * fraction
  const y = box.y + box.height * 0.5
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.up()
  await page.waitForSelector('.price-explanation .explain-grid', { timeout: 20000 })
}

async function selectionHeader(page) {
  return (await page.locator('.price-explanation h3').first().innerText()).trim()
}

async function loadedPanel(page) {
  await page.locator('.price-explanation').waitFor({ timeout: 20000 })
  await page.waitForFunction(
    () => !document.querySelector('.price-explanation .state-block[role="status"]'),
    undefined,
    { timeout: 20000 },
  )
}

await mkdir(OUT, { recursive: true })
for (const entry of await readdir(OUT)) {
  if (/^\d+-audit-.*\.png$/.test(entry)) await unlink(path.join(OUT, entry))
}
const browser = await chromium.launch(LAUNCH)
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
const page = await context.newPage()
watch(page, 'desktop')

try {
  await check('desktop company chart loads', async () => {
    await openCompany(page)
    assert(await page.locator('canvas').count(), 'no chart canvas')
  })

  await check('normal chart is untouched while Explain mode is off', async () => {
    assert((await page.locator('.chart-range-overlay').count()) === 0, 'overlay present while mode off')
    const box = await page.locator('canvas').first().boundingBox()
    assert(box, 'no chart canvas box')
    await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.5)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width * 0.4, box.y + box.height * 0.5, { steps: 6 })
    await page.mouse.up()
    await page.mouse.wheel(0, -240)
    await page.waitForTimeout(250)
    assert((await page.locator('.price-explanation').count()) === 0, 'drag opened a panel while mode off')
    assert((await page.locator('.chart-range-overlay').count()) === 0, 'overlay appeared while mode off')
    assert(await page.locator('canvas').count(), 'chart disappeared after normal pan/zoom')
  })

  await check('desktop drag left-to-right opens the investigation', async () => {
    await enableExplain(page)
    await drag(page, 0.35, 0.7)
    await loadedPanel(page)
    const header = await selectionHeader(page)
    assert(/\d{4}-\d{2}-\d{2}/.test(header), `selection header not dated: ${header}`)
    await shot(page, 'desktop-panel')
  })

  await check('drag right-to-left is normalised to the same interval', async () => {
    const before = await selectionHeader(page)
    await drag(page, 0.72, 0.42)
    await loadedPanel(page)
    const after = await selectionHeader(page)
    const [start, end] = after.split('→').map((part) => part.trim())
    assert(start <= end, `reversed drag produced an unnormalised interval: ${after}`)
    assert(after !== before, 'reversed drag did not change the selection')
  })

  await check('one-candle selection uses the previous eligible close', async () => {
    await clickCandle(page, 0.55)
    await loadedPanel(page)
    const text = await page.locator('.price-explanation').innerText()
    assert(/one-candle|previous eligible|single-session/i.test(text), 'no single-session explanation')
    assert(!/NaN|undefined/.test(text), 'panel contains NaN or undefined')
  })

  await check('keyboard selection commits a range', async () => {
    const before = await selectionHeader(page)
    await page.locator('.chart-range-overlay').focus()
    await page.keyboard.press('Home')
    for (let index = 0; index < 3; index += 1) await page.keyboard.press('Shift+ArrowRight')
    await page.keyboard.press('Enter')
    await page.waitForTimeout(600)
    await loadedPanel(page)
    const after = await selectionHeader(page)
    assert(after !== before, 'keyboard selection did not change the interval')
  })

  await check('wheel zoom keeps the selection band and panel coherent', async () => {
    const box = await page.locator('.chart-range-overlay').boundingBox()
    const band = page.locator('.chart-range-band')
    assert((await band.isVisible()) || (await band.count()) === 0, 'band state unreadable')
    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5)
    await page.mouse.wheel(0, -300)
    await page.waitForTimeout(400)
    await loadedPanel(page)
    assert(await page.locator('.price-explanation').isVisible(), 'panel vanished on zoom')
  })

  await check('resize redraws the overlay and keeps the panel', async () => {
    await page.setViewportSize({ width: 1100, height: 780 })
    await page.waitForTimeout(500)
    const box = await page.locator('.chart-range-overlay').boundingBox()
    assert(box && box.width > 100, 'overlay lost its size after resize')
    await loadedPanel(page)
    await shot(page, 'desktop-resized')
    await page.setViewportSize({ width: 1440, height: 960 })
    await page.waitForTimeout(400)
  })

  await check('changing the share class clears the investigation', async () => {
    const selector = page.getByLabel('Share class')
    assert(await selector.count(), 'Alphabet share-class selector missing')
    const options = await selector.locator('option').all()
    assert(options.length > 1, 'expected more than one share class')
    await selector.selectOption({ index: 1 })
    await page.waitForTimeout(900)
    assert((await page.locator('.price-explanation').count()) === 0, 'panel survived an instrument change')
    await page.waitForSelector('.chart-range-overlay')
  })

  await check('repeated investigations stay consistent', async () => {
    const headers = new Set()
    for (const [from, to] of [
      [0.2, 0.4],
      [0.45, 0.65],
      [0.7, 0.9],
    ]) {
      await drag(page, from, to)
      await loadedPanel(page)
      headers.add(await selectionHeader(page))
      assert(!/NaN|undefined/.test(await page.locator('.price-explanation').innerText()), 'NaN in panel')
    }
    assert(headers.size >= 2, `repeated investigations produced only ${headers.size} interval(s)`)
  })

  await check('empty relative-data state is explicit', async () => {
    await openDetail(page, 'Quantitative interpretation')
    const text = await page.locator('.price-explanation').innerText()
    assert(
      /no benchmark_security_id was supplied|not available|no benchmark/i.test(text),
      'benchmark-unavailable state is not explained in the panel',
    )
  })

  await check('slow API shows loading, then resolves', async () => {
    await page.route('**/api/securities/*/price-explanations', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1400))
      await route.continue()
    })
    await page.getByLabel('Selection start session').fill('2024-04-01')
    await page.getByLabel('Selection end session').fill('2024-05-15')
    await page.waitForSelector('.price-explanation [role="status"]', { timeout: 5000 })
    await loadedPanel(page)
    const text = await page.locator('.price-explanation').innerText()
    assert(/2024-04-01/.test(text) && /2024-05-15/.test(text), 'slow response did not update the header')
    await page.unroute('**/api/securities/*/price-explanations')
  })

  await check('API error shows a retryable state and recovers', async () => {
    let failNext = true
    page.__tolerateHttpErrors = true
    await page.route('**/api/securities/*/price-explanations', async (route) => {
      if (failNext) {
        failNext = false
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: { code: 'acceptance_injected', message: 'synthetic acceptance failure' } }),
        })
        return
      }
      await route.continue()
    })
    await page.getByLabel('Selection start session').fill('2024-05-01')
    await page.waitForSelector('.price-explanation [role="alert"]', { timeout: 10000 })
    assert(
      /synthetic acceptance failure/.test(await page.locator('.price-explanation [role="alert"]').innerText()),
      'injected error message not surfaced',
    )
    await shot(page, 'error-state')
    await page.getByRole('button', { name: 'Retry' }).click()
    await loadedPanel(page)
    await page.unroute('**/api/securities/*/price-explanations')
    page.__tolerateHttpErrors = false
  })

  await check('authorized export downloads an auditable JSON report', async () => {
    const button = page.getByRole('button', { name: 'Export report' })
    assert(await button.isEnabled(), 'export disabled for project-authored demo data')
    const [download] = await Promise.all([page.waitForEvent('download'), button.click()])
    const target = path.join(OUT, 'price-explanation-export.json')
    await download.saveAs(target)
    const payload = JSON.parse(await readFile(target, 'utf8'))
    assert(payload.rights.export_allowed === true, 'exported report is not authorized')
    assert(payload.reproducibility.hash, 'exported report has no reproducibility hash')
    assert(payload.selection.price_vintage.status === 'unverified', 'vintage claim is not qualified')
    assert(payload.price_statistics.return_convention, 'return convention missing from export')
  })

  await check('restricted export disables the control and says why', async () => {
    await page.route('**/api/securities/*/price-explanations', async (route) => {
      const response = await route.fetch()
      const payload = await response.json()
      payload.rights.export_allowed = false
      payload.rights.restricted_sources = ['SRC-restricted-fixture']
      payload.rights.unregistered_sources = []
      payload.rights.reasons = ['SRC-restricted-fixture: redistribution class is not exportable']
      await route.fulfill({ response, json: payload })
    })
    await page.getByLabel('Basis').selectOption('price')
    await loadedPanel(page)
    const button = page.getByRole('button', { name: 'Export report' })
    assert(await button.isDisabled(), 'export button enabled for a restricted response')
    await openDetail(page, 'Evidence inspector and reproducibility')
    const text = await page.locator('.price-explanation').innerText()
    assert(/no — restricted source/.test(text), 'restriction reason not shown')
    assert(/redistribution class is not exportable/.test(text), 'per-source reason not shown')
    await shot(page, 'export-disabled')
    await page.unroute('**/api/securities/*/price-explanations')
    await page.getByLabel('Basis').selectOption('split_adjusted')
    await loadedPanel(page)
  })

  // The next checks move to Apple: its 31 October 2024 8-K was accepted at 20:30Z,
  // after that session's 20:00Z close, so it must be visible but not ranked. The
  // document text is an explicit offline UI fixture because this demo has no archived
  // filing HTML; the locator, accession and timestamp are the real stored values.
  await check('after-close filing is visible but marked not a candidate explanation', async () => {
    await openTicker(page, 'AAPL')
    await enableExplain(page)
    await selectRange(page, '2024-10-28', '2024-10-31')
    const panel = page.locator('.price-explanation')
    const text = await panel.innerText()
    assert(/after final close|subsequent to price window/i.test(text), 'after-close relation not shown')
    assert(/Not a candidate explanation/.test(text), 'eligibility reason not shown')
    assert(/2024-10-31T20:30:25Z/.test(text), 'real acceptance instant not shown')
    assert(!/NaN|undefined/.test(text), 'panel contains NaN or undefined')
  })

  await check('original SEC document link, passages and citation spans render', async () => {
    const fixtureText =
      'TEST FIXTURE: offline UI fixture for the original-document panel; not a real Apple excerpt.'
    await page.route('**/api/securities/*/price-explanations', async (route) => {
      const response = await route.fetch()
      const payload = await response.json()
      const target = payload.events.items.find(
        (item) =>
          item.kind === 'sec_filing' && item.accession_number === '0000320193-24-000120',
      )
      if (target) target.document = {
        ...(target.document ?? {}),
        status: 'resolved',
        sha256: 'f'.repeat(64),
        availability_time: '2024-10-31T20:30:25Z',
        availability_precision: 'exact',
        rights: { redistribution: 'public_domain', redistributable: true, retention_policy: 'archive' },
        items: [
          {
            item: '2.02',
            label: 'Results of Operations and Financial Condition',
            observed_heading: 'Item 2.02. Results of Operations and Financial Condition',
            section_path: 'Item 2.02',
            unit_id: 'KU-fixture-1',
          },
        ],
        passages: [
          {
            unit_id: 'KU-fixture-1',
            section_path: 'Item 2.02',
            heading: 'Item 2.02. Results of Operations and Financial Condition',
            unit_kind: 'paragraph',
            char_start: 100,
            char_end: 260,
            sha256: 'e'.repeat(64),
            excerpt: fixtureText,
            excerpt_truncated: false,
            excerpt_withheld: null,
            citation:
              'accession 0000320193-24-000120 section Item 2.02 chars 100-260',
          },
        ],
        passage_status: 'available',
        reason: null,
      }
      await route.fulfill({ response, json: payload })
    })
    // Force a new request after installing the fixture route: re-selecting the same
    // interval would leave the already-loaded response in place.
    await selectRange(page, '2024-10-28', '2024-10-30')
    await selectRange(page, '2024-10-28', '2024-10-31')
    const link = page.getByTestId('document-link').first()
    await link.waitFor({ timeout: 10000 })
    assert(
      (await link.getAttribute('href')) ===
        'https://www.sec.gov/Archives/edgar/data/320193/000032019324000120/aapl-20241031.htm',
      'original SEC locator is not the stored accession and primary document',
    )
    await page.locator('.document-evidence details summary').first().click()
    const citation = page.getByTestId('passage-citation').first()
    await citation.waitFor({ timeout: 5000 })
    assert(
      (await citation.innerText()).includes('accession 0000320193-24-000120 section Item 2.02'),
      'citation does not name the accession and section',
    )
    assert(
      (await page.locator('blockquote').first().innerText()).includes('TEST FIXTURE'),
      'stored fixture passage was not rendered',
    )
    await shot(page, 'document-passages')
    await page.unroute('**/api/securities/*/price-explanations')
  })

  await check('saving an investigation shows its retrospective as-of time', async () => {
    const save = page.getByRole('button', { name: 'Save investigation' })
    await save.click()
    const savedAsOf = page.getByTestId('saved-as-of')
    await savedAsOf.waitFor({ timeout: 15000 })
    const value = await savedAsOf.innerText()
    assert(/^\d{4}-\d{2}-\d{2}T/.test(value), `saved as_of is not a timestamp: ${value}`)
    assert(value.slice(0, 10) >= '2026', `retrospective as_of leaked back to the period: ${value}`)
    const text = await page.locator('.price-explanation').innerText()
    assert(/retrospective run/.test(text), 'retrospective label missing beside saved time')
    await shot(page, 'saved-investigation')
  })

  await check('saving the same version again is refused, not overwritten', async () => {
    // This request is expected to fail, so its 4xx console line is not a defect.
    page.__tolerateHttpErrors = true
    await page.getByRole('button', { name: 'Save investigation' }).click()
    const alert = page.locator('.price-explanation [role="alert"]')
    await alert.waitFor({ timeout: 10000 })
    assert(/already exists/i.test(await alert.innerText()), 'duplicate save was not refused')
    page.__tolerateHttpErrors = false
  })

  await check('check for changes reports a labelled current-state comparison', async () => {
    await page.getByRole('button', { name: 'Check for changes' }).first().click()
    const impact = page.getByTestId('impact-status')
    await impact.waitFor({ timeout: 10000 })
    const text = await impact.innerText()
    assert(/unchanged/.test(text), `unexpected impact status: ${text}`)
    assert(/current_state_drift_check/.test(text), 'drift comparison is not labelled')
    assert(/drift check, not a replay/i.test(text), 'drift guarantee is overstated')
  })

  await check('saved work can be reopened with its knowledge cutoff', async () => {
    const savedSection = page.getByTestId('saved-investigations')
    await savedSection.evaluate((element) => {
      element.open = true
    })
    const item = savedSection.locator('li').first()
    await item.waitFor({ timeout: 10000 })
    const itemText = await item.innerText()
    assert(
      /2024-10-28|2024-10-29/.test(itemText) && /URO-PRI-/.test(itemText),
      `saved list does not show the saved interval and object: ${itemText}`,
    )
    await page.getByTestId('reopen-investigation').first().click()
    const snapshot = page.getByTestId('saved-snapshot')
    await snapshot.waitFor({ timeout: 10000 })
    const text = await snapshot.innerText()
    assert(/Retrospective investigation/.test(text), 'reopened snapshot lost its retrospective label')
    assert(/Knowledge cutoff/.test(text), 'reopened snapshot has no knowledge cutoff')
    assert(/analysis_run_time_retrospective/.test(text), 'cutoff basis is missing')
    assert(/URO-PRI-/.test(text), 'reopened snapshot does not identify the stored object')
    await shot(page, 'reopened-saved-work')
  })

  await check('a failed saved-work request shows a retryable error', async () => {
    page.__tolerateHttpErrors = true
    await page.route('**/api/research/price-investigations/*', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          error: { code: 'acceptance_injected', message: 'synthetic reopen failure' },
        }),
      })
    })
    await page.getByTestId('reopen-investigation').first().click()
    const error = page.getByTestId('reopen-error')
    await error.waitFor({ timeout: 10000 })
    assert(/synthetic reopen failure/.test(await error.innerText()), 'reopen failure not surfaced')
    await page.unroute('**/api/research/price-investigations/*')
    page.__tolerateHttpErrors = false
  })

  await check('closing Explain mode restores normal chart interaction', async () => {
    await page.getByRole('button', { name: 'Close investigation' }).click()
    await page.waitForTimeout(300)
    assert((await page.locator('.chart-range-overlay').count()) === 0, 'overlay survived closing Explain mode')
    const box = await page.locator('canvas').first().boundingBox()
    await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.5)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5, { steps: 5 })
    await page.mouse.up()
    await page.waitForTimeout(300)
    assert((await page.locator('.price-explanation').count()) === 0, 'panel reopened after closing Explain mode')
  })

  await shot(page, 'desktop-final', true)
} finally {
  await context.close()
}

// ------------------------------------------------------------------ mobile / touch
const mobile = await browser.newContext({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
})
const phone = await mobile.newPage()
watch(phone, 'mobile')
try {
  await check('mobile layout has no horizontal overflow', async () => {
    await openCompany(phone)
    const overflow = await phone.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    assert(overflow <= 1, `page overflows horizontally by ${overflow}px`)
    await shot(phone, 'mobile-chart')
  })

  await check('touch drag selects an interval and renders the panel', async () => {
    const box = await enableExplain(phone)
    const y = box.y + box.height * 0.55
    const x1 = box.x + box.width * 0.25
    const x2 = box.x + box.width * 0.72
    const overlay = phone.locator('.chart-range-overlay')
    const base = { pointerId: 7, pointerType: 'touch', isPrimary: true, button: 0, buttons: 1, bubbles: true }
    await overlay.dispatchEvent('pointerdown', { ...base, clientX: x1, clientY: y })
    await overlay.dispatchEvent('pointermove', { ...base, clientX: (x1 + x2) / 2, clientY: y })
    await overlay.dispatchEvent('pointermove', { ...base, clientX: x2, clientY: y })
    await overlay.dispatchEvent('pointerup', { ...base, buttons: 0, clientX: x2, clientY: y })
    await loadedPanel(phone)
    const overflow = await phone.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    assert(overflow <= 1, `panel causes ${overflow}px horizontal overflow on mobile`)
    await shot(phone, 'mobile-panel', true)
  })

  await check('mobile save and saved-work layout fit the viewport', async () => {
    await selectRange(phone, '2024-10-29', '2024-11-01')
    await phone.getByRole('button', { name: 'Save investigation' }).click()
    await phone.getByTestId('saved-as-of').waitFor({ timeout: 15000 })
    await phone.getByTestId('saved-investigations').locator('summary').click()
    const overflow = await phone.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    assert(overflow <= 1, `saved work causes ${overflow}px horizontal overflow on mobile`)
    const text = await phone.locator('.price-explanation').innerText()
    assert(/retrospective run/.test(text), 'mobile saved time lost its retrospective label')
    await shot(phone, 'mobile-saved')
  })

  await check('mobile panel exposes export and rights', async () => {
    await openDetail(phone, 'Evidence inspector and reproducibility')
    const text = await phone.locator('.price-explanation').innerText()
    assert(/Export report/.test(text), 'export control missing on mobile')
    assert(/Export allowed/.test(text), 'rights decision missing on mobile')
    await shot(phone, 'mobile-rights', true)
  })
} finally {
  await mobile.close()
}

await browser.close()

const summary = {
  base: BASE,
  checks,
  problems,
  screenshots: checks.length,
}
console.log(`\n${JSON.stringify(summary, null, 2)}`)
if (problems.length) {
  console.error(`\nBROWSER ACCEPTANCE FAILED: ${problems.length} problem(s)`)
  process.exit(1)
}
console.log('\nBROWSER ACCEPTANCE PASSED')
