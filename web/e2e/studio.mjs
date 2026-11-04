/** Phase 3 Studio browser verification against the built terminal. */
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
  if (message.type() === 'error') problems.push(`console: ${message.text()}`)
})

try {
  await page.goto(`${BASE}/studio`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Studio' }).waitFor()
  await page.getByRole('button', { name: 'Run DCF' }).click()
  await page.getByText('Value / share').waitFor({ timeout: 20000 })
  const valueText = await page.getByText('Value / share').locator('..').innerText()
  if (!/\$[\d,.]+/.test(valueText)) throw new Error(`DCF did not render a value: ${valueText}`)
  await page.screenshot({ path: path.join(OUT, '13-studio-valuation.png'), fullPage: true })
  console.log(`studio DCF rendered: ${valueText.replace(/\n/g, ' ')}`)

  await page.getByRole('button', { name: 'Scenarios + sensitivity' }).click()
  await page.getByText('Sensitivity · WACC × terminal growth').waitFor({ timeout: 20000 })
  await page.screenshot({ path: path.join(OUT, '14-studio-sensitivity.png') })
  console.log('studio scenarios and sensitivity rendered')

  await page.getByRole('button', { name: 'Equations' }).click()
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
