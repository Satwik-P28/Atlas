/** Phase 4 browser acceptance: historical reopen and the Quant Lab workflow. */
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:8000'
const OUT = path.resolve(process.cwd(), '..', 'artifacts')
const problems = []
await mkdir(OUT, { recursive: true })
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error' && !/favicon|422|Unprocessable Entity/.test(message.text())) {
    problems.push(`console: ${message.text()}`)
  }
})

const assert = (condition, message) => {
  if (!condition) throw new Error(message)
}
const numeric = (text) => Number(String(text).replace(/[^0-9.-]/g, ''))
const money = (text) => Number(String(text).replace(/[^0-9.-]/g, ''))

try {
  // ---------------------------------------------------------- historical replay
  await page.goto(`${BASE}/studio`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Studio' }).waitFor()
  await page.getByLabel('Information cutoff').fill('2024-06-01')
  await page.getByText(/reconstructing at 2024-06-01/).waitFor({ timeout: 15000 })
  await page.getByRole('button', { name: 'Run DCF' }).click()
  const valueCard = page.getByTestId('value-per-share')
  await valueCard.waitFor({ timeout: 20000 })
  const historicalValue = (await valueCard.innerText()).replace(/\n/g, ' ')
  const historicalNumber = numeric(historicalValue)
  assert(isFinitePositive(historicalNumber), `historical DCF did not render: ${historicalValue}`)

  await page.getByRole('button', { name: 'Save model + application' }).click()
  await page.getByText(/Saved model/).waitFor({ timeout: 20000 })
  const applications = await (await page.request.get(`${BASE}/api/research/objects?kind=application`)).json()
  assert(applications.items.length > 0, 'no saved application returned by the API')
  const application = await (await page.request.get(`${BASE}/api/research/objects/${applications.items[0].object_id}`)).json()
  assert(String(application.document.spec.as_of).startsWith('2024-06-01'),
    `application lost its historical cutoff: ${application.document.spec.as_of}`)
  const model = await (await page.request.get(`${BASE}/api/research/objects/${application.document.spec.model_object_id}`)).json()
  const storedAsOf = model.document.spec.as_of
  const storedAssumptions = model.document.spec.assumptions

  await page.reload({ waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Studio' }).waitFor()
  await page.getByRole('button', { name: 'Open' }).first().click()
  await page.getByText(/^Reopened /).waitFor({ timeout: 20000 })
  assert(await page.getByLabel('Information cutoff').inputValue() === '2024-06-01',
    'reopen did not restore the historical information cutoff')
  await page.getByRole('button', { name: 'Close opened application' }).click()
  await page.getByText(/Closed the opened application/).waitFor()
  assert(await page.getByText(/Closed the opened application/).isVisible(), 'close action did not clear the opened state')
  await page.getByRole('button', { name: 'Open' }).first().click()
  await page.getByText(/^Reopened /).waitFor({ timeout: 20000 })
  await page.getByRole('button', { name: 'Run DCF' }).click()
  await page.waitForFunction((expected) => {
    const card = document.querySelector('[data-testid="value-per-share"]')
    return card && Number(card.textContent.replace(/[^0-9.-]/g, '')) === expected
  }, historicalNumber, { timeout: 30000 })
  const reopenedValue = (await valueCard.innerText()).replace(/\n/g, ' ')
  assert(numeric(reopenedValue) === historicalNumber,
    `re-execution changed the historical valuation: ${historicalValue} -> ${reopenedValue}`)
  await page.screenshot({ path: path.join(OUT, '22-studio-historical-reopen.png') })

  // Independent interface check: the same archived assumptions against the stored cutoff.
  const dcf = await (await page.request.post(`${BASE}/api/valuation/dcf`, {
    data: {
      issuer: model.document.spec.issuer_id,
      assumptions: storedAssumptions,
      as_of: storedAsOf,
      mode: model.document.mode,
    },
  })).json()
  assert(Number(dcf.outputs.value_per_share).toFixed(2) === historicalNumber.toFixed(2),
    `API and browser historical values differ: ${dcf.outputs.value_per_share} vs ${historicalNumber}`)
  console.log(`historical replay preserved ${historicalValue} at ${storedAsOf}`)

  // --------------------------------------------------------------- Quant Lab
  await page.goto(`${BASE}/lab`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Research, not a performance chart' }).waitFor()
  await page.getByLabel('Instrument').selectOption({ index: 0 })
  await page.getByRole('button', { name: 'Run research' }).click()
  await page.getByTestId('lab-message').waitFor({ timeout: 30000 })
  await page.getByTestId('lab-run-id').waitFor({ timeout: 20000 })
  await page.getByText('Every cash flow accounted for').waitFor({ timeout: 20000 })
  await page.screenshot({ path: path.join(OUT, '23-quant-lab-buy-hold.png'), fullPage: true })
  console.log('quant lab buy-and-hold accounting rendered')

  const firstRunId = await page.getByTestId('lab-run-id').innerText()
  await page.getByLabel('Research strategy').selectOption('sma_cross')
  await page.getByRole('button', { name: 'Run research' }).click()
  await page.waitForFunction((oldId) => {
    const node = document.querySelector('[data-testid="lab-run-id"]')
    return node && node.textContent && node.textContent !== oldId
  }, firstRunId, { timeout: 30000 })
  await page.getByText('Trend following.', { exact: false }).first().waitFor()
  await page.screenshot({ path: path.join(OUT, '24-quant-lab-trend.png'), fullPage: true })
  console.log('quant lab trend strategy rendered')

  const secondRunId = await page.getByTestId('lab-run-id').innerText()
  await page.getByLabel('Research strategy').selectOption('custom_model')
  await page.getByRole('button', { name: 'Run research' }).click()
  await page.waitForFunction((oldId) => {
    const node = document.querySelector('[data-testid="lab-run-id"]')
    return node && node.textContent && node.textContent !== oldId
  }, secondRunId, { timeout: 30000 })
  await page.getByText('Custom Model Forge signal.', { exact: true }).waitFor()
  await page.getByText('Every cash flow accounted for').waitFor({ timeout: 20000 })
  await page.screenshot({ path: path.join(OUT, '25-quant-lab-custom-model.png'), fullPage: true })
  console.log('quant lab custom Model Forge signal rendered')

  await page.getByRole('button', { name: 'Inspect capsule' }).click()
  await page.getByTestId('lab-capsule').waitFor({ timeout: 15000 })
  const capsuleText = await page.getByTestId('lab-capsule').innerText()
  assert(/external_provider_only|partial|archived/.test(capsuleText), 'capsule did not expose reproducibility status')
  await page.getByRole('button', { name: 'Replay run' }).click()
  await page.getByTestId('lab-replay').waitFor({ timeout: 20000 })
  const replayText = await page.getByTestId('lab-replay').innerText()
  assert(/matched exactly/.test(replayText), `replay did not match: ${replayText}`)
  await page.screenshot({ path: path.join(OUT, '26-quant-lab-capsule.png'), fullPage: true })
  console.log('quant lab Time Capsule and replay rendered')

  await page.getByRole('button', { name: 'Compare latest two' }).click()
  await page.getByText('Same accounting, different hypothesis').waitFor({ timeout: 15000 })
  await page.screenshot({ path: path.join(OUT, '27-quant-lab-compare.png'), fullPage: true })
  console.log('quant lab experiment comparison rendered')

  // The complete research manifest must be downloadable, not only an API capability.
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export experiment' }).click()
  const download = await downloadPromise
  assert(download.suggestedFilename().endsWith('.json'),
    `experiment export did not produce JSON: ${download.suggestedFilename()}`)
  console.log('quant lab experiment manifest downloaded')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${BASE}/lab`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Research, not a performance chart' }).waitFor()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
  if (overflow) throw new Error('Quant Lab overflows a 390px viewport')
  await page.screenshot({ path: path.join(OUT, '28-quant-lab-mobile.png'), fullPage: true })
  console.log('quant lab mobile viewport has no horizontal overflow')
} finally {
  await browser.close()
}

if (problems.length) {
  console.error('PHASE4 PROBLEMS:', problems.join(' | '))
  process.exit(1)
}
console.log('PHASE4_EXIT=0')

function isFinitePositive(value) {
  return Number.isFinite(value) && value > 0
}
