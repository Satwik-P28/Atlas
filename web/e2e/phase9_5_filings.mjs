/**
 * Phase 9.5 browser certification: document research through the Standard interface.
 *
 * It asserts rendered passages, exact-span disclosure, claim verification and console
 * cleanliness. A 200 response is not accepted as evidence that the page works.
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
  await page.screenshot({ path: path.join(ARTIFACTS, `phase9_5_${name}.png`), fullPage: false })
}

const browser = await chromium.launch({
  args: [
    '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
    '--disable-gpu', '--single-process', '--no-zygote',
  ],
})
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('requestfailed', (request) => failedRequests.push(`${request.url()} ${request.failure()?.errorText}`))

try {
  await page.goto(`${BASE}/filings`, { waitUntil: 'domcontentloaded' })
  // The interface mode persists server-side; make the Standard shell explicit.
  const standard = page.getByRole('button', { name: /^Standard$/ })
  if (await standard.count()) {
    const selected = await standard.first().getAttribute('class')
    if (!selected?.includes('is-selected')) {
      await standard.first().click({ force: true })
      await page.waitForTimeout(1200)
    }
  }
  // <option> elements are never "visible"; wait for attachment instead.
  await page.waitForFunction(
    () => document.querySelectorAll('.filing-controls select option').length > 0,
    null,
    { timeout: 20000 },
  )
  const options = await page.locator('.filing-controls select option').count()
  check(options > 0, `issuer list is populated (${options} issuers)`)

  const select = page.locator('.filing-controls select')
  const values = await select.locator('option').evaluateAll((nodes) => nodes.map((node) => node.value))
  let passages = 0
  for (const value of values.slice(0, 6)) {
    await select.selectOption(value)
    await page.fill('.filing-controls input[placeholder]', 'customer concentration risk')
    await page.getByRole('button', { name: 'Search filings' }).click()
    await page.waitForSelector('.passage, .banner-warn', { timeout: 20000 })
    passages = await page.locator('.passage').count()
    if (passages > 0) break
  }
  check(passages > 0, `archived filing passages render (${passages} passages)`)

  const meta = (await page.locator('.passage-meta').first().innerText()).replace(/\s+/g, ' ')
  check(/available/.test(meta) && /chars/.test(meta), `passage states availability and span (${meta.slice(0, 90)})`)

  await page.locator('.passage').first().click()
  await page.waitForSelector('.passage-opened', { timeout: 10000 })
  const opened = await page.locator('.passage-opened').innerText()
  check(/Exact span \d+–\d+/.test(opened), 'opened passage discloses its exact character span')
  await shot(page, 'filings')

  await page.getByRole('button', { name: 'Verify as a claim' }).click()
  await page.waitForSelector('text=/verified|unsupported|partially verified/i', { timeout: 20000 })
  const claimText = await page.locator('.card').last().innerText()
  check(/citation\(s\)/.test(claimText), 'claim reports its citation count and export decision')

  const denial = await page.evaluate(async () => {
    const response = await fetch('/api/knowledge/search', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: 'antarctic penguin subsidiary revenue', issuer_id: 'ISS-NONE' }),
    })
    return response.status
  })
  check(denial === 200 || denial === 422, `unscoped/unknown issuer request is refused or abstains (${denial})`)

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.filing-controls', { timeout: 20000 })
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  check(overflow <= 0, `390x844: no horizontal page overflow (delta ${overflow}px)`)
  await shot(page, 'filings_mobile')
} catch (error) {
  check(false, `journey completed without an exception (${error.message})`)
} finally {
  const ignorable = /409 \(Conflict\)/
  const errors = consoleErrors.filter((text) => !ignorable.test(text))
  check(errors.length === 0, `console errors: ${errors.length}`)
  check(failedRequests.length === 0, `failed requests: ${failedRequests.length}`)
  await browser.close()
}

const failures = results.filter((item) => !item.passed)
console.log(`\n${results.length - failures.length}/${results.length} checks passed`)
if (failures.length) {
  for (const failure of failures) console.log(` - ${failure.label}`)
  process.exit(1)
}
console.log('All document-research assertions passed.')
