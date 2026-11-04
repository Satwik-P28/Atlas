/** Phase 3 Studio browser verification against the built terminal. */
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:8000'
const OUT = path.resolve(process.cwd(), '..', 'artifacts')
const problems = []
let expectingValidationError = false
await mkdir(OUT, { recursive: true })
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() !== 'error') return
  const text = message.text()
  if (expectingValidationError && /422|Unprocessable Entity/.test(text)) return
  problems.push(`console: ${text}`)
})

const assert = (condition, message) => {
  if (!condition) throw new Error(message)
}

try {
  await page.goto(`${BASE}/studio`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Studio' }).waitFor()

  // Historical cutoff: the cutoff must be visible and flow into the run.
  await page.getByLabel('Information cutoff').fill('2024-06-01')
  await page.getByText(/reconstructing at 2024-06-01/).waitFor({ timeout: 15000 })
  await page.getByRole('button', { name: 'Run DCF' }).click()
  const historicalCard = page.getByTestId('value-per-share')
  await historicalCard.waitFor({ timeout: 20000 })
  const historicalValue = await historicalCard.innerText()
  assert(/\$[\d,.]+/.test(historicalValue), `historical DCF did not render: ${historicalValue}`)
  console.log(`studio historical DCF (2024-06-01) rendered: ${historicalValue.replace(/\n/g, ' ')}`)

  // Current cutoff and the complete valuation surface.
  await page.getByRole('button', { name: 'Use current' }).click()
  await page.getByText(/current evidence cutoff/).waitFor()
  await page.getByRole('button', { name: 'Run DCF' }).click()
  await page.waitForFunction((oldValue) => {
    const card = document.querySelector('[data-testid="value-per-share"]')
    return card && card.textContent !== oldValue
  }, historicalValue.replace(/^Value \/ share/, '').trim(), { timeout: 20000 })
  const valueText = await page.getByTestId('value-per-share').innerText()
  assert(/\$[\d,.]+/.test(valueText), `DCF did not render a value: ${valueText}`)
  const numeric = (text) => Number(text.replace(/[^\d.-]/g, ''))
  assert(numeric(valueText) !== numeric(historicalValue),
    'current DCF reused assumptions loaded for the historical cutoff')
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: path.join(OUT, '13-studio-valuation.png') })
  console.log(`studio DCF rendered: ${valueText.replace(/\n/g, ' ')}`)

  await page.getByRole('button', { name: 'Scenarios + sensitivity' }).click()
  await page.getByText('Sensitivity · WACC × terminal growth').waitFor({ timeout: 20000 })
  await page.screenshot({ path: path.join(OUT, '14-studio-sensitivity.png') })
  console.log('studio scenarios and sensitivity rendered')

  // Reverse DCF: use a price close enough to the base value to stay inside the bounds.
  await page.getByPlaceholder(/Observed /).fill('140')
  await page.getByRole('button', { name: 'Solve implied growth' }).click()
  await page.getByText(/"solved": true/).waitFor({ timeout: 20000 })
  await page.screenshot({ path: path.join(OUT, '18-studio-reverse-dcf.png') })
  console.log('studio reverse DCF solved')

  // Save a complete application and verify it can be reopened.
  await page.getByRole('button', { name: 'Save model + application' }).click()
  await page.getByText(/Saved model/).waitFor({ timeout: 20000 })
  const openButton = page.getByRole('button', { name: 'Open' }).first()
  await openButton.waitFor({ timeout: 15000 })
  await openButton.click()
  await page.getByText(/^Reopened /).waitFor({ timeout: 15000 })
  await page.screenshot({ path: path.join(OUT, '19-studio-reopened.png') })
  console.log('studio application saved and reopened')

  // Fork and compare two immutable application documents.
  page.once('dialog', (dialog) => dialog.accept(`Forked valuation ${Date.now()}`))
  await page.getByRole('button', { name: 'Fork' }).first().click()
  await page.getByText(/Forked to/).waitFor({ timeout: 20000 })
  const compares = page.locator('select[aria-label^="Compare "]')
  await compares.nth(0).selectOption({ index: 1 })
  await compares.nth(1).selectOption({ index: 2 })
  await page.getByRole('button', { name: 'Compare versions' }).click()
  await page.getByText(/\d+ document change\(s\)|The two documents are identical/).waitFor({ timeout: 15000 })
  await page.screenshot({ path: path.join(OUT, '20-studio-compare.png') })
  console.log('studio application fork and compare rendered')

  // Export manifest must download as JSON and contain the run snapshot.
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export' }).first().click()
  const download = await downloadPromise
  const downloadPath = await download.path()
  assert(download.suggestedFilename().endsWith('.json'), 'export did not produce JSON')
  assert(Boolean(downloadPath), 'export download had no path')
  console.log(`studio export downloaded: ${download.suggestedFilename()}`)

  // Invalid model must surface compiler diagnostics rather than crash.
  await page.getByRole('button', { name: 'Equations' }).click()
  const equation = page.locator('textarea').first()
  await equation.fill('revenue +')
  expectingValidationError = true
  await page.getByRole('button', { name: 'Compile + execute' }).click()
  const error = page.getByTestId('studio-error')
  await error.waitFor({ timeout: 15000 })
  assert((await error.innerText()).length > 8, 'compiler error was empty')
  expectingValidationError = false
  await page.screenshot({ path: path.join(OUT, '21-studio-error.png') })
  console.log('studio invalid equation surfaced a compiler diagnostic')

  await equation.fill('revenue * margin')
  await page.getByRole('button', { name: 'Compile + execute' }).click()
  await page.getByText('"output"').waitFor({ timeout: 15000 })
  await page.screenshot({ path: path.join(OUT, '15-studio-equation.png') })
  console.log('studio equation compiled and executed')

  await page.getByRole('button', { name: 'Visual graph' }).click()
  await page.getByRole('button', { name: 'Validate graph' }).click()
  await page.getByText('"plan"').waitFor({ timeout: 15000 })
  await page.screenshot({ path: path.join(OUT, '16-studio-graph.png') })
  console.log('studio visual graph validated')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${BASE}/studio`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Studio' }).waitFor()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
  if (overflow) throw new Error('Studio overflows a 390px viewport')
  await page.screenshot({ path: path.join(OUT, '17-studio-mobile.png'), fullPage: true })
  console.log('studio mobile viewport has no horizontal overflow')
} finally {
  await browser.close()
}

if (problems.length) {
  console.error('STUDIO PROBLEMS:', problems.join(' | '))
  process.exit(1)
}
console.log('STUDIO_EXIT=0')
