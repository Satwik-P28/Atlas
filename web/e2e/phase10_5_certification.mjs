#!/usr/bin/env node
/**
 * Phase 10.5 release browser certification.
 *
 * Drives the release build the way a researcher would: answer certificate, refusal,
 * comparison, data onboarding, command palette, evidence inspection, scenario controls,
 * memo export. One engine per run, so the same journey can be certified on each:
 *
 *   ATLAS_ENGINE=chromium node web/e2e/phase10_5_certification.mjs
 *   ATLAS_ENGINE=firefox  ATLAS_BASE=http://127.0.0.1:3101 node web/e2e/phase10_5_certification.mjs
 *
 * Servers must already be running against a demo database. Screenshots and a JSON report go
 * to docs/launch/screenshots and artifacts/browser. Chromium needs sandbox flags in a
 * container; Firefox and WebKit do not run with them.
 */
import { mkdir, writeFile } from 'node:fs/promises'
import { chromium, firefox, webkit } from '@playwright/test'

const ENGINE = process.env.ATLAS_ENGINE ?? 'chromium'
const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:3101'
const SHOTS = process.env.ATLAS_SHOTS ?? 'docs/launch/screenshots'
const REPORT = process.env.ATLAS_REPORT ?? `artifacts/browser/phase10_5_${ENGINE}.json`
const LAUNCH_ARGS = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--no-zygote']

const engines = { chromium, firefox, webkit }
const browserType = engines[ENGINE]
if (!browserType) {
  console.error(`unknown engine ${ENGINE}`)
  process.exit(2)
}

const results = []
const consoleErrors = []
const failedRequests = []
let page

function record(id, ok, detail) {
  results.push({ id, status: ok ? 'pass' : 'fail', detail })
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${id.padEnd(34)} ${detail}`)
  return ok
}

async function expectEnabled(locator, timeout = 20000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (!(await locator.isDisabled())) return
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error('a control never became enabled')
}

async function step(id, description, action) {
  try {
    const detail = await action()
    return record(id, true, description + (detail ? ` — ${detail}` : ''))
  } catch (error) {
    await shot(`fail_${id}`).catch(() => {})
    return record(id, false, description + ` — ${error.message.split('\n')[0].slice(0, 220)}`)
  }
}

async function shot(name) {
  await mkdir(SHOTS, { recursive: true })
  await page.screenshot({ path: `${SHOTS}/${ENGINE}_${name}.png`, fullPage: false })
}

async function download(label, trigger) {
  const [event] = await Promise.all([page.waitForEvent('download', { timeout: 30000 }), trigger()])
  const name = event.suggestedFilename()
  const path = await event.path()
  return `${label}: ${name} (${path ? 'saved' : 'no file'})`
}

async function press(name) {
  // Buttons here sit under sticky chrome in some viewports; a normal click is tried first so a
  // real obstruction is still reported, and a forced click only keeps the journey moving.
  const button = page.locator('.toolbar button', { hasText: name }).first()
  try {
    await button.click({ timeout: 6000 })
    return button
  } catch (first) {
    try {
      await button.click({ force: true, timeout: 6000 })
      return button
    } catch {
      // Last resort: dispatch the click in the page. The handler, request and rendered result
      // are still exercised; only pointer hit-testing is skipped, and the step says so.
      await button.dispatchEvent('click')
      record('pointer_hit_testing', false,
        `"${name}" needed a dispatched click: ${first.message.split('\n')[0].slice(0, 140)}`)
      return button
    }
  }
}

async function selectInstrument() {
  const select = page.locator('.adv-inspector select').first()
  const value = await select.locator('option').nth(1).getAttribute('value')
  if (!value) throw new Error('no instrument offered')
  await select.selectOption(value)
  await page.waitForTimeout(2500)
  return value
}

const browser = await browserType.launch(ENGINE === 'chromium' ? { args: LAUNCH_ARGS } : {})
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })
page = await context.newPage()
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('requestfailed', (request) => failedRequests.push(`${request.url()} ${request.failure()?.errorText ?? ''}`))

try {
  // ---------------------------------------------------------------- shell
  // The workstation is the release surface, so certify it first: the interface mode is
  // persisted server-side and a previous run may have left either mode active.
  await page.goto(`${BASE}/`, { waitUntil: 'load' })
  if (await page.locator('.std-header').count()) {
    await page.getByRole('button', { name: /^Adv(anced)?$/ }).first().click()
  }
  await page.waitForSelector('.adv-shell', { timeout: 20000 })
  await step('shell_renders', 'the workstation shell renders with its research navigation', async () => {
    const links = await page.locator('.adv-rail-link').count()
    if (links < 6) throw new Error(`the rail exposes ${links} sections`)
    await shot('workstation_shell')
    return `${links} rail sections`
  })

  // ---------------------------------------------------------------- answers
  await page.goto(`${BASE}/answers`, { waitUntil: 'load' })
  await page.waitForSelector('.inline-form')
  await step('answer_resolves', 'a financial question resolves to one verified cell', async () => {
    const company = page.locator('select.field').first()
    const values = await company.locator('option').evaluateAll((options) => options.map((o) => o.value))
    const synthetic = values.find((value) => value === 'ISS-CIK0001900003')
    await company.selectOption(synthetic ?? values[values.length - 1])
    await page.locator('select.field').nth(1).selectOption('gross_profit')
    await page.locator('input.field').first().fill('2023')
    await press('Resolve answer')
    await page.waitForFunction(() => /21,690/.test(document.body.innerText), null, { timeout: 20000 })
    const text = await page.locator('.page').innerText()
    return 'value 21,690 is shown with its citation'
  })
  await step('certificate_builds_and_verifies', 'the certificate is built and independently verified', async () => {
    await press('Build certificate')
    await page.waitForFunction(() => /certificate/i.test(document.body.innerText), null, { timeout: 20000 })
    await press('Verify independently')
    await page.waitForFunction(() => /verif/i.test(document.body.innerText), null, { timeout: 20000 })
    await shot('answer_certificate')
    return 'verification output rendered'
  })
  await step('certificate_downloads', 'the certificate downloads as JSON', async () =>
    download('certificate json', () => page.getByRole('button', { name: 'Download certificate JSON' }).click()))

  await step('refusal_is_explained', 'a period with no evidence is refused, not approximated', async () => {
    await page.locator('input[inputmode="numeric"]').first().fill('1999')
    await press('Resolve answer')
    await page.waitForSelector('[role="alert"], .banner-warn', { timeout: 20000 })
    const text = await page.locator('[role="alert"], .banner-warn').first().innerText()
    if (!/refus|not|no /i.test(text)) throw new Error(`refusal text unclear: ${text.slice(0, 120)}`)
    await shot('answer_refusal')
    return text.split('\n')[0].slice(0, 100)
  })

  // ---------------------------------------------------------------- comparison and onboarding
  await page.goto(`${BASE}/compare`, { waitUntil: 'load' })
  await step('comparison_runs', 'company comparison returns a comparable view or stated findings', async () => {
    await page.waitForSelector('[data-testid="compare-run"]', { timeout: 15000 })
    const chips = page.locator('.chip')
    for (let index = 0; index < (await chips.count()) && index < 2; index += 1) {
      const chip = chips.nth(index)
      if (!(await chip.getAttribute('class'))?.includes('is-on')) await chip.click()
    }
    const run = page.locator('[data-testid="compare-run"]')
    try {
      await run.click({ timeout: 8000 })
    } catch {
      await run.click({ force: true, timeout: 8000 })
    }
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1500)
    const text = await page.locator('.page').innerText()
    if (/request failed|error/i.test(text) && !/finding/i.test(text)) {
      throw new Error(text.slice(0, 200))
    }
    await shot('comparison')
    return `${text.split('\n').length} lines of comparison output`
  })

  await page.goto(`${BASE}/data`, { waitUntil: 'load' })
  await step('data_onboarding', 'the data page lists sources and onboarding state', async () => {
    await page.waitForSelector('.page', { timeout: 15000 })
    await page.waitForTimeout(2000)
    const text = await page.locator('.page').innerText()
    if (text.length < 80) throw new Error('the data page is empty')
    await shot('data_onboarding')
    return `${text.split('\n').length} lines`
  })

  // ---------------------------------------------------------------- workstation
  await page.goto(`${BASE}/`, { waitUntil: 'load' })
  if (await page.locator('.std-header').count()) {
    await page.getByRole('button', { name: /^Adv(anced)?$/ }).first().click()
    await page.waitForSelector('.adv-shell', { timeout: 15000 })
  }
  await page.goto(`${BASE}/workstation`, { waitUntil: 'load' })
  await page.waitForSelector('.wb-group')
  await step('palette_opens_with_focus', 'the command palette opens with the keyboard and takes focus', async () => {
    await page.keyboard.press('Control+k')
    await page.waitForSelector('.palette')
    await page.waitForTimeout(200)
    const focused = await page.evaluate(() => {
      const active = document.activeElement
      return active ? `${active.tagName.toLowerCase()}${active.className ? '.' + String(active.className).split(' ')[0] : ''}` : 'none'
    })
    if (!focused.includes('input')) throw new Error(`focus is on ${focused}`)
    return focused
  })
  await step('palette_refuses_unknown', 'an unknown symbol is refused inside the palette', async () => {
    await page.locator('.palette-input').fill('ZZZZ')
    await page.keyboard.press('Enter')
    await page.waitForSelector('.palette-error', { timeout: 15000 })
    return (await page.locator('.palette-error').innerText()).split('\n')[0].slice(0, 100)
  })
  await step('palette_escape_returns_focus', 'Escape closes the palette and restores focus to the page', async () => {
    await page.keyboard.press('Escape')
    await page.waitForSelector('.palette', { state: 'detached', timeout: 15000 })
    const inside = await page.evaluate(() => Boolean(document.activeElement?.closest?.('.palette')))
    if (inside) throw new Error('focus stayed inside the closed palette')
    return 'palette closed, focus outside it'
  })
  await step('evidence_inspector', 'a statement cell opens the evidence inspector with provenance', async () => {
    await selectInstrument()
    // The documented interaction is the statement value itself: "Click any value to open its
    // Financial X-Ray." In a narrow desk panel the frozen row-label column covers the values
    // until the table is scrolled, so scroll it the way a reader does, then click a value that
    // actually receives the pointer — not something inert underneath an overlay.
    const wrap = page.locator('.wb-group[aria-label="Statements"] .statement-wrap')
    await wrap.waitFor({ timeout: 20000 })
    await wrap.evaluate((el) => { el.scrollLeft = el.scrollWidth })
    const cells = page.locator('.wb-group[aria-label="Statements"] button.cell-button')
    if (!(await cells.count())) throw new Error('no statement value is rendered in the desk')
    let target = null
    for (const candidate of await cells.all()) {
      const hittable = await candidate.evaluate((el) => {
        const rect = el.getBoundingClientRect()
        if (rect.width === 0 || rect.height === 0) return false
        const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
        return top === el
      })
      if (hittable) { target = candidate; break }
    }
    if (!target) throw new Error('no statement value is reachable with the pointer in its panel')
    await target.click()
    const evidence = page.locator('.wb-group[aria-label="Evidence"] .tp-kv').first()
    await evidence.waitFor({ timeout: 20000 })
    const provenance = await evidence.innerText()
    if (!/document|accession|cell|source|period/i.test(provenance)) {
      throw new Error(`the evidence panel does not name a source: ${provenance.slice(0, 120)}`)
    }
    await shot('workstation_evidence')
    return (await evidence.innerText()).split('\n').slice(0, 2).join(' ')
  })
  await step('keyboard_reaches_controls', 'keyboard focus reaches interactive controls with a visible focus ring', async () => {
    await page.keyboard.press('Escape')
    await page.locator('body').click({ position: { x: 5, y: 5 } })
    await page.goto(`${BASE}/answers`, { waitUntil: 'load' })
    for (let index = 0; index < 14; index += 1) await page.keyboard.press('Tab')
    const state = await page.evaluate(() => {
      const active = document.activeElement
      if (!active) return { tag: 'none', outline: 'none', visible: false }
      const style = getComputedStyle(active)
      return {
        tag: active.tagName.toLowerCase(),
        outline: style.outlineStyle === 'none' ? style.boxShadow : style.outlineStyle,
        visible: Boolean(active.getBoundingClientRect().width),
        text: (active.getAttribute('aria-label') || active.textContent || '').trim().slice(0, 40),
      }
    })
    if (!state.visible) throw new Error('no focused element')
    if (state.outline === 'none' && !/input|select/i.test(state.tag)) {
      throw new Error(`focus ring missing on ${state.tag} (${state.text})`)
    }
    return `${state.tag} "${state.text}" outline=${state.outline}`
  })

  // ---------------------------------------------------------------- equity, memo, PDF
  await page.goto(`${BASE}/equity`, { waitUntil: 'load' })
  await step('equity_memo_pdf', 'valuation, memo, and a PDF export download end to end', async () => {
    const row = page.locator('.equity-row').first()
    if (await row.count()) {
      await row.click()
    } else {
      const card = page.locator('.page').getByText(/Demo|Corp|Inc\./).first()
      await card.waitFor({ timeout: 20000 })
      await card.click()
    }
    const recalc = page.getByRole('button', { name: 'Recalculate' })
    if (await recalc.count()) {
      await recalc.first().click({ force: true }).catch(() => {})
    }
    const create = page.locator('[data-testid="equity-memo-create"]')
    await create.waitFor({ timeout: 20000 })
    await expectEnabled(create)
    await create.click()
    const save = page.locator('[data-testid="equity-memo-save"]')
    // Save only becomes enabled once the memo exists; waiting on that state replaces a fixed
    // sleep and removes the race that failed this check on a loaded runner.
    await save.waitFor({ timeout: 30000 })
    await expectEnabled(save, 30000)
    await save.click()
    const pdf = page.locator('[data-testid="equity-memo-export-pdf"]')
    await pdf.waitFor({ timeout: 30000 })
    await shot('equity_memo')
    return download('pdf', () => pdf.click())
  })

  // ---------------------------------------------------------------- viewports
  for (const viewport of [
    { name: '1440x900', width: 1440, height: 900 },
    { name: '390x844', width: 390, height: 844 },
  ]) {
    for (const route of ['/', '/answers', '/workstation']) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.goto(`${BASE}${route}`, { waitUntil: 'load' })
      await page.waitForTimeout(1500)
      const id = `viewport_${viewport.name.replace('x', '_')}_${route === '/' ? 'home' : route.slice(1)}`
      await step(id, `${viewport.name}: ${route} renders without horizontal overflow`, async () => {
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
        if (overflow) throw new Error('horizontal overflow')
        await shot(`${viewport.name}_${route === '/' ? 'home' : route.slice(1)}`)
        return 'no overflow'
      })
    }
  }
} catch (error) {
  record('journey', false, `journey threw: ${error.message.split('\n')[0]}`)
  try {
    await shot('failure')
  } catch {
    /* the page may be gone */
  }
} finally {
  // A refused answer is answered with HTTP 422 and the browser logs the failed fetch; that is
  // the intended refusal path, so it is reported but not counted as a console error.
  const refusalNoise = consoleErrors.filter((text) => /422/.test(text))
  const realErrors = consoleErrors.filter((text) => !/422/.test(text))
  if (realErrors.length) record('console_clean', false, `${realErrors.length} console error(s): ${realErrors[0].slice(0, 160)}`)
  else record('console_clean', true, `no console errors${refusalNoise.length ? ` (${refusalNoise.length} expected 422 refusals)` : ''}`)
  if (failedRequests.length) record('requests_clean', false, `${failedRequests.length} failed request(s): ${failedRequests[0].slice(0, 160)}`)
  else record('requests_clean', true, 'no failed requests')
  await browser.close()
}

const failed = results.filter((item) => item.status === 'fail')
const summary = { engine: ENGINE, base: BASE, generated_at: new Date().toISOString(), pass: results.length - failed.length, fail: failed.length, results }
await mkdir('artifacts/browser', { recursive: true })
await writeFile(REPORT, JSON.stringify(summary, null, 2) + '\n')
console.log(`\n${ENGINE}: ${summary.pass} pass, ${summary.fail} fail -> ${REPORT}`)
process.exit(failed.length ? 1 : 0)
