#!/usr/bin/env node
/**
 * Phase 9.4 workstation acceptance journey.
 *
 * Runnable with a working Chromium and the terminal running on ATLAS_BASE
 * (default http://127.0.0.1:3000):
 *
 *   node web/e2e/phase9_4_workstation.mjs
 *
 * It captures console errors, failed requests and screenshots into
 * artifacts/phase9_4_*, and exits non-zero on the first failed assertion.
 * In the phase 9.4 environment Chromium could not start (missing X11/GTK
 * libraries, no unprivileged install path), so this file has NOT been run;
 * see docs/PHASE9_4_BROWSER_ACCEPTANCE.md.
 */
import { mkdir } from 'node:fs/promises'
import { chromium } from '@playwright/test'

const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:3000'
const OUT = process.env.ATLAS_ARTIFACTS ?? 'artifacts'
// This container has no user namespaces, no shared memory and no GPU; containerised CI
// images need the same flags. They relax isolation inside the test browser process only,
// never in the application or in production.
const LAUNCH_ARGS = [
  '--no-sandbox',
  '--disable-setuid-sandbox',
  '--disable-dev-shm-usage',
  '--disable-gpu',
  '--single-process',
  '--no-zygote',
]
const VIEWPORTS = [
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '1440x900', width: 1440, height: 900 },
  { name: '1280x800', width: 1280, height: 800 },
  { name: '1024x768', width: 1024, height: 768 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '390x844', width: 390, height: 844 },
]

const failures = []
const consoleErrors = []
const failedRequests = []

function check(condition, message) {
  if (!condition) {
    failures.push(message)
    console.error(`FAIL ${message}`)
  } else {
    console.log(`ok   ${message}`)
  }
}

async function shot(page, name) {
  await mkdir(OUT, { recursive: true })
  await page.screenshot({ path: `${OUT}/phase9_4_${name}.png`, fullPage: false })
}

const browser = await chromium.launch({ args: LAUNCH_ARGS })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })
const page = await context.newPage()
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('requestfailed', (request) => failedRequests.push(`${request.url()} ${request.failure()?.errorText ?? ''}`))

try {
  // ---------------------------------------------------------------- standard
  await page.goto(`${BASE}/`, { waitUntil: 'load' })
  // The interface mode is persisted server-side, so a previous run may have left
  // Advanced active. Select Standard explicitly instead of assuming a default.
  if (await page.locator('.adv-shell').count()) {
    await page.getByRole('button', { name: 'Std', exact: true }).click()
    await page.waitForSelector('.std-header', { timeout: 15000 })
  }
  check(await page.locator('header.std-header').isVisible(), 'standard shell renders a top navigation header')
  check(await page.locator('nav.std-nav a').count() >= 7, 'standard navigation exposes the research sections')
  await shot(page, 'standard_markets')

  await page.goto(`${BASE}/companies`, { waitUntil: 'load' })
  await page.locator('a.company-card, .company-card').first().click()
  await page.waitForLoadState('networkidle')
  check(await page.locator('.statement-table, .metric-grid').first().isVisible(), 'standard company page renders statements or metrics')
  await shot(page, 'standard_company')

  // ---------------------------------------------------------------- advanced
  await page.getByRole('button', { name: /^Adv(anced)?$/ }).first().click()
  await page.waitForSelector('.adv-shell')
  check(await page.locator('.adv-shell').isVisible(), 'advanced shell renders a command header and rail')
  check(await page.locator('.adv-rail-link').count() >= 6, 'advanced rail exposes workstation sections')

  await page.goto(`${BASE}/workstation`, { waitUntil: 'load' })
  await page.waitForSelector('.wb-group')
  const groups = await page.locator('.wb-group').count()
  check(groups >= 4, `workstation renders at least four panels (found ${groups})`)

  // Select a real instrument before the visual capture: chrome-only screenshots
  // would not prove that data-backed panels render.
  const instrumentSelect = page.locator('.adv-inspector select').first()
  const optionValue = await instrumentSelect.locator('option').nth(1).getAttribute('value')
  check(Boolean(optionValue), 'inspector offers a covered instrument')
  if (optionValue) {
    await instrumentSelect.selectOption(optionValue)
    await page.waitForTimeout(2500)
    const statementRows = await page.locator('.statement-table tbody tr').count()
    check(statementRows > 0, `statements render for the selected issuer (${statementRows} rows)`)
    const metricRows = await page.locator('.wb-group').filter({ hasText: 'METRICS' }).locator('tbody tr').count()
    check(metricRows > 0, `metrics render for the selected issuer (${metricRows} rows)`)
  }
  await shot(page, 'advanced_desk')

  // Command palette: select an instrument, then open a panel.
  await page.keyboard.press('Control+k')
  await page.waitForSelector('.palette')
  const firstSymbol = (await page.locator('.palette-item strong').first().innerText()).split('·')[0].trim()
  await page.locator('.palette-input').fill(`${firstSymbol} FIN`)
  await page.keyboard.press('Enter')
  await page.waitForSelector('.palette', { state: 'detached' })
  check(await page.locator('.wb-tab', { hasText: 'Statements' }).count() > 0, 'command opened the statements panel')

  // Unknown symbol must be refused, not resolved.
  await page.keyboard.press('Control+k')
  await page.locator('.palette-input').fill('ZZZZ')
  await page.keyboard.press('Enter')
  check(await page.locator('.palette-error').isVisible(), 'unknown symbol produces a visible command error')
  await page.keyboard.press('Escape')

  // Docking: drag one tab onto another group and confirm the panel count holds.
  const before = await page.locator('.wb-tab').count()
  await page.locator('.wb-tab').nth(1).hover()
  await page.mouse.down()
  await page.locator('.wb-tab').nth(0).hover()
  await page.mouse.up()
  check((await page.locator('.wb-tab').count()) === before, 'dragging a tab does not drop a panel')

  // Resize a splitter and confirm the panes keep their boxes.
  const splitter = page.locator('.wb-splitter').first()
  if (await splitter.count()) {
    const box = await splitter.boundingBox()
    if (box) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
      await page.mouse.down()
      await page.mouse.move(box.x + 80, box.y + box.height / 2, { steps: 8 })
      await page.mouse.up()
      check(true, 'splitter drag completed without an exception')
    }
  }
  await shot(page, 'advanced_desk_docked')

  // Persistence: save, reload, confirm the layout is still there.
  await page.keyboard.press('Control+s')
  await page.waitForSelector('.ws-banner', { timeout: 20000 })
  const saveBanner = (await page.locator('.ws-banner').first().innerText()).trim().replace(/\s+/g, ' ')
  console.log(`     save banner: ${saveBanner}`)
  check((await page.locator('.ws-banner.is-ok').count()) > 0, `layout saves (${saveBanner})`)
  const savedUrl = page.url()
  await page.reload({ waitUntil: 'load' })
  await page.waitForSelector('.wb-group')
  check((await page.locator('.wb-group').count()) >= 4, 'saved desk reopens after reload on its own URL')
  check(savedUrl.includes('/workstation'), 'save keeps the desk on the workstation route')

  // Evidence inspector. A saved layout stores panels, not the transient link
  // selection, so re-select an instrument before clicking a value.
  const reselect = page.locator('.adv-inspector select').first()
  const reselectValue = await reselect.locator('option').nth(1).getAttribute('value')
  if (reselectValue) {
    await reselect.selectOption(reselectValue)
    await page.waitForTimeout(2500)
  }
  const cell = page.locator('.statement-table button.link-button').first()
  if (await cell.count()) {
    await cell.click()
  } else {
    const chip = page.locator('.evidence-chip').first()
    if (await chip.count()) await chip.click()
  }
  const evidenceGroup = page.locator('.wb-group').filter({ hasText: 'EVIDENCE' })
  const inspectorVisible = await evidenceGroup
    .locator('.tp-kv')
    .first()
    .isVisible()
    .catch(() => false)
  check(inspectorVisible, 'evidence inspector shows provenance for the selected value')
  await shot(page, 'advanced_evidence')

  // Point-in-time: moving the cutoff must be visible in the shell.
  await page.locator('.adv-inspector input[type="date"]').fill('2023-06-01')
  await page.waitForTimeout(600)
  check((await page.locator('.adv-fact strong').first().innerText()).includes('2023-06-01'), 'cutoff is stated in the command header')

  // ---------------------------------------------------------------- viewports
  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await page.goto(`${BASE}/workstation`, { waitUntil: 'load' })
    await page.waitForSelector('.wb-group')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
    check(!overflow, `${viewport.name}: no horizontal page overflow`)
    const tabVisible = await page.locator('.wb-tab').first().isVisible()
    check(tabVisible, `${viewport.name}: workstation remains operable`)
    await shot(page, `advanced_${viewport.name}`)
  }

  // Mobile standard journey.
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${BASE}/companies`, { waitUntil: 'load' })
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
  check(!mobileOverflow, '390x844: standard company list has no horizontal overflow')
  await shot(page, 'standard_mobile')
  // Leave the database in Standard mode so the next run starts from the default.
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`${BASE}/`, { waitUntil: 'load' })
  if (await page.locator('.adv-shell').count()) {
    await page.getByRole('button', { name: 'Std', exact: true }).click()
  }
} catch (error) {
  failures.push(`journey threw: ${error.message}`)
  console.error(error)
} finally {
  if (consoleErrors.length) {
    failures.push(`${consoleErrors.length} console error(s)`)
    console.error('console errors:', consoleErrors)
  }
  if (failedRequests.length) {
    failures.push(`${failedRequests.length} failed request(s)`)
    console.error('failed requests:', failedRequests)
  }
  await browser.close()
}

if (failures.length) {
  console.error(`\n${failures.length} failure(s):`)
  for (const failure of failures) console.error(` - ${failure}`)
  process.exit(1)
}
console.log('\nAll workstation assertions passed.')
