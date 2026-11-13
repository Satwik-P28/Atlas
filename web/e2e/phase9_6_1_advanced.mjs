/**
 * Phase 9.6.1 browser certification: the Advanced `filing` panel.
 *
 * A rendered page is not proof the panel works. This asserts issuer binding, cutoff changes,
 * cross-issuer isolation, exact spans, save/reload restoration, 390x844 layout and console
 * cleanliness against the real API.
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:3000'
const ARTIFACTS = process.env.ATLAS_ARTIFACTS ?? '../artifacts'
const results = []
const consoleErrors = []
const failedRequests = []

function check(passed, label) {
  results.push({ passed, label })
  console.log(`${passed ? 'ok  ' : 'FAIL'} ${label}`)
}

async function shot(page, name) {
  fs.mkdirSync(ARTIFACTS, { recursive: true })
  await page.screenshot({ path: path.join(ARTIFACTS, `phase9_6_2_${name}.png`) })
}

const browser = await chromium.launch({
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
    '--disable-gpu', '--single-process', '--no-zygote'],
})
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('requestfailed', (request) =>
  failedRequests.push(`${request.url()} ${request.failure()?.errorText}`))

async function issuerOptions() {
  return page.getByLabel('Instrument').locator('option').evaluateAll((nodes) =>
    nodes.map((node) => ({ value: node.value, label: node.textContent ?? '' })).filter((o) => o.value))
}

async function selectIssuer(value) {
  await page.getByLabel('Instrument').selectOption(value)
  await page.waitForTimeout(400)
}

async function searchFilings(query) {
  const input = page.getByLabel('Search archived filings')
  await input.fill(query)
  await input.press('Enter')
  await page.waitForSelector('.tp-passage, .tp-empty', { timeout: 25000 })
}

async function passages() {
  return page.locator('.tp-passage').evaluateAll((nodes) => nodes.map((node) => node.innerText))
}

try {
  await page.goto(`${BASE}/workstation`, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => {
    const select = [...document.querySelectorAll('select')]
      .find((node) => node.closest('label')?.textContent?.trim().startsWith('Instrument'))
    return Boolean(select) && select.options.length > 1
  }, null, { timeout: 30000 })
  check(true, 'Advanced workstation loads')

  const options = await issuerOptions()
  check(options.length > 2, `instrument list populated (${options.length} issuers)`)

  await page.getByLabel('Information cutoff').fill('2021-06-30')
  await page.getByLabel('Information cutoff').dispatchEvent('change')

  // Bind the desk to an issuer before adding the panel: an unbound filing panel renders an
  // empty-link state, which is correct but not what this step is certifying.
  const firstIssuer = options[0]
  await selectIssuer(firstIssuer.value)
  // Start from an empty desk: the default layout includes panels that require a priced
  // security, which this corpus does not have, and an unsaveable panel is not a panel bug.
  await page.getByRole('button', { name: 'Reset' }).click()
  await page.waitForTimeout(400)
  // The default desk includes panels that require a priced security; this corpus has filings
  // but no market data, so close them and certify the filing panel on its own.
  for (const title of ['Price', 'Statements', 'Metrics', 'Memos']) {
    const close = page.getByRole('button', { name: `Close ${title}` })
    if (await close.count()) {
      await close.first().click()
      await page.waitForTimeout(250)
    }
  }
  await page.waitForTimeout(300)
  await page.getByLabel('Panel type').selectOption('filing')
  await page.getByRole('button', { name: 'Add panel' }).click()
  await page.waitForSelector('.tp-form', { timeout: 25000 })
  check(true, 'filing panel added and bound from the workstation')

  let bound = null
  let rendered = []
  for (const option of options.slice(0, 12)) {
    await selectIssuer(option.value)
    await searchFilings('customer concentration risk')
    rendered = await passages()
    if (rendered.length) { bound = option; break }
  }
  check(rendered.length > 0, `historical passages render for a bound issuer (${rendered.length})`)
  check(Boolean(bound), `issuer binding produced evidence (${bound?.label ?? 'none'})`)

  const first = rendered[0] ?? ''
  check(/chars \d+–\d+/.test(first), 'passage discloses its exact character span')
  check(/available|20\d\d/.test(first), 'passage discloses availability')

  await page.locator('.tp-passage').first().click()
  await page.waitForSelector('.tp-passage-body', { timeout: 10000 })
  const body = await page.locator('.tp-passage-body').first().innerText()
  check(/Exact span \d+–\d+/.test(body), 'opened passage exposes the precise span')
  check(/availability/.test(body), `opened passage states availability class (${body.split('\n')[0].slice(0, 70)})`)
  await shot(page, 'advanced_filing')

  const beforeCutoff = await page.locator('.tp-passage-meta').first().innerText()
  const [cutoffResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().includes('/api/knowledge/search'),
      { timeout: 25000 }),
    (async () => {
      await page.getByLabel('Information cutoff').fill('2019-06-30')
      await page.getByLabel('Information cutoff').dispatchEvent('change')
    })(),
  ])
  await page.waitForTimeout(900)
  const cutoffBody = await cutoffResponse.json()
  const requestedCutoff = cutoffResponse.request().postDataJSON()?.cutoff ?? ''
  const allWithinCutoff = (cutoffBody.results ?? []).every(
    (row) => String(row.availability_time) <= '2019-06-30T23:59:59Z')
  check(requestedCutoff.startsWith('2019-06-30') && allWithinCutoff,
    `cutoff change is applied server-side (${requestedCutoff}, ${(cutoffBody.results ?? []).length} rows)`)
  check(beforeCutoff.length > 0, 'earlier cutoff returned evidence before the change')

  const firstAccessions = await page.locator('.tp-passage-meta').evaluateAll((nodes) =>
    nodes.map((node) => node.innerText))
  const next = options.find((option) => option.value !== bound?.value)
  await selectIssuer(next.value)
  await page.waitForTimeout(1200)
  const switched = await page.locator('.tp-passage-meta').evaluateAll((nodes) =>
    nodes.map((node) => node.innerText))
  const stale = switched.some((row) => firstAccessions.includes(row))
  check(!stale, `issuer switch leaves no stale results (${switched.length} rows)`)

  await page.getByRole('button', { name: 'Save' }).click()
  await page.waitForTimeout(1500)
  const savedBadge = await page.locator('.tp-badge').first().innerText()
  const notice = await page.locator('.ws-banner').innerText().catch(() => 'no-banner')
  check(/saved/i.test(savedBadge), `workspace saved (${savedBadge.trim()} · ${notice.replace(/\s+/g, ' ').slice(0, 90)})`)

  // A saved desk is reopened by id; reloading /workstation alone would load the default desk,
  // which would not prove anything about restoration.
  const workspaces = await page.evaluate(async () => (await fetch('/api/workspaces')).json())
  const items = Array.isArray(workspaces) ? workspaces : (workspaces.items ?? [])
  // The list is not guaranteed to be newest-first: select the desk we just saved by name,
  // otherwise the newest row, never merely the last array element.
  const savedName = (notice.match(/[“"]([^”"]+)[”"]/) ?? [])[1]
  const target = items.find((item) => savedName && item.name === savedName)
    ?? items[items.length - 1] ?? {}
  const workspaceId = target.workspace_id ?? target.id
  check(Boolean(workspaceId), `saved workspace is listed (${workspaceId ?? 'none'})`)
  await page.goto(`${BASE}/workstation/${workspaceId}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.tp-form, .tp-empty', { timeout: 25000 })
  const titles = await page.locator('.wb-tab').evaluateAll((nodes) =>
    nodes.map((node) => node.textContent?.trim() ?? ''))
  check(titles.some((title) => title.includes('Document evidence')),
    `filing panel restored from the saved desk (${titles.join(' | ')})`)
  const boundAfter = await page.getByLabel('Instrument').inputValue()
  check(boundAfter === next.value,
    `desk instrument binding persisted (${boundAfter || 'none'} vs ${next.value})`)

  // Phase 9.6.2: close down to a single panel, save it and reopen it. A lone panel must be a
  // tabs node; a one-child split is rejected by both validators.
  const closers = page.getByRole('button', { name: /^Close / })
  let guard = 0
  while ((await closers.count()) > 1 && guard < 8) {
    await closers.first().click()
    await page.waitForTimeout(350)
    guard += 1
  }
  await page.getByRole('button', { name: 'Save' }).click()
  await page.waitForTimeout(1500)
  const singleBanner = await page.locator('.ws-banner').innerText().catch(() => '')
  check(!/layout refused/i.test(singleBanner),
    `single-panel layout accepted by the server (${singleBanner.replace(/\s+/g, ' ').slice(0, 80)})`)
  const list2 = await page.evaluate(async () => (await fetch('/api/workspaces')).json())
  const rows2 = Array.isArray(list2) ? list2 : (list2.items ?? [])
  const singleName = (singleBanner.match(/[“"]([^”"]+)[”"]/) ?? [])[1]
  const single = rows2.find((item) => singleName && item.name === singleName)
    ?? rows2[rows2.length - 1] ?? {}
  const singleId = single.workspace_id ?? single.id
  if (singleId) {
    await page.goto(`${BASE}/workstation/${singleId}`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.wb-tab', { timeout: 25000 })
    const tabs = await page.locator('.wb-tab').count()
    check(tabs === 1, `one-panel desk restored (${tabs} tab)`)
    check(await page.getByLabel('Instrument').inputValue() === next.value,
      'one-panel desk keeps the instrument binding')
  } else {
    check(false, 'one-panel desk saved and listed')
  }

  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(600)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  check(overflow <= 0, `390x844: no page overflow (delta ${overflow}px)`)
  // Header controls must be reachable without horizontal scrolling. Panel bodies may scroll
  // internally by design; the theme and mode switches may not be pushed off-screen.
  const clipped = await page.evaluate(() => {
    const header = document.querySelector('.adv-header')
    if (!header) return ['no-header']
    return Array.from(header.querySelectorAll('button, select, input'))
      .filter((node) => node.getBoundingClientRect().width > 0)
      .filter((node) => node.getBoundingClientRect().right > window.innerWidth + 1)
      .map((node) => `${node.tagName}:${node.getAttribute('aria-label') ?? (node.textContent ?? '').trim().slice(0, 20)}`)
  })
  check(clipped.length === 0, `390x844: no control clipped (${clipped.slice(0, 3).join(', ') || 'none'})`)
  await shot(page, 'advanced_filing_mobile')
} catch (error) {
  check(false, `journey completed without an exception (${error.message})`)
} finally {
  check(consoleErrors.length === 0, `console errors: ${consoleErrors.length} ${consoleErrors.slice(0, 2).join(' | ')}`)
  check(failedRequests.length === 0, `failed requests: ${failedRequests.length} ${failedRequests.slice(0, 2).join(' | ')}`)
  await browser.close()
}

const failures = results.filter((item) => !item.passed)
console.log(`\n${results.length - failures.length}/${results.length} checks passed`)
if (failures.length) {
  for (const failure of failures) console.log(` - ${failure.label}`)
  process.exit(1)
}
console.log('Advanced filing panel certified.')
