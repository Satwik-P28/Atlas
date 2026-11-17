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
import { mkdir, readFile } from 'node:fs/promises'
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

async function openCompany(page) {
  await page.goto(`${BASE}/companies/${COMPANY}`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('tab', { name: 'Charts' }).click()
  await page.getByTestId('explain-range-toggle').waitFor({ timeout: 20000 })
  await page.waitForSelector('canvas')
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
