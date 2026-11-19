/** Phase 8 browser acceptance: local gallery, pinned package, execution, fork, mobile. */
import { chromium } from 'playwright'
import { mkdir, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { LATEST_SCHEMA_VERSION } from './schema.mjs'

const BASE = process.env.ATLAS_BASE ?? 'http://127.0.0.1:8003'
const OUT = path.resolve(process.cwd(), '..', 'artifacts')
const PACKAGE = path.resolve(process.cwd(), '..', 'fixtures', 'phase8', 'flagship_weather_demand.atlas')
const problems = []
const assert = (condition, message) => {
  if (!condition) throw new Error(message)
}
await mkdir(OUT, { recursive: true })
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error' && !/favicon/.test(message.text())) {
    problems.push(`console: ${message.text()}`)
  }
})

try {
  const health = await (await page.request.get(`${BASE}/api/health`)).json()
  assert(
    health.schema_version === LATEST_SCHEMA_VERSION,
    `served schema ${health.schema_version} is not the migration head ${LATEST_SCHEMA_VERSION}`,
  )
  assert(health.application_installations === 1, 'E2E database is missing the pinned installation')
  const fixtureInfo = await stat(PACKAGE)
  assert(fixtureInfo.size > 40000, 'pinned package fixture is unexpectedly small')

  await page.goto(`${BASE}/applications`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Portable research, without executable strangers' }).waitFor()
  assert(await page.getByText('Unsigned packages', { exact: true }).isVisible(),
    'unsigned trust boundary is missing')

  await page.setInputFiles('[data-testid="apps-file"]', PACKAGE)
  await page.getByTestId('apps-message').filter({ hasText: /^Installed / }).waitFor({ timeout: 30000 })
  await page.getByTestId('app-detail').waitFor({ timeout: 30000 })
  assert(await page.getByTestId('app-tile').count() === 1, 'gallery did not show the imported application')
  const detail = await page.getByTestId('app-detail').innerText()
  assert(/92ab1bf753438a0f/.test(detail), 'pinned package hash is not displayed')
  assert(/unsigned/.test(detail), 'unsigned status is not displayed')
  assert(/U\.S\. Government public domain/.test(detail), 'source rights are missing')
  assert(/as-issued historical vintage/i.test(detail), 'vintage limitation is missing')
  assert(/hypothetical/i.test(detail), 'hypothetical exposure limitation is missing')
  assert(/atlas\.economic\.weather_demand\.v1/.test(detail), 'runtime is missing')

  await page.getByTestId('app-execute').click()
  await page.getByTestId('app-execution').waitFor({ timeout: 30000 })
  const execution = await page.getByTestId('app-execution').innerText()
  assert(/reproduced/.test(execution), 'package did not reproduce')
  assert(/2,?956\.58/.test(execution), `expected test RMSE 2,956.58, rendered ${execution}`)
  assert(/-0\.8935/.test(execution), 'expected negative test R² is missing')
  assert(/not_identified/.test(execution), 'causal boundary is missing')
  assert(await page.getByText(/Package-provided code is never imported/).isVisible(),
    'declarative execution boundary is missing')

  await page.getByRole('button', { name: 'Verify integrity' }).click()
  await page.getByTestId('apps-message').filter({ hasText: /Integrity verified/ }).waitFor({ timeout: 30000 })
  assert(/publisher identity is not authenticated/i.test(await page.getByTestId('apps-message').innerText()),
    'verification overstated publisher identity')

  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 30000 }),
    page.getByRole('button', { name: 'Download', exact: true }).click(),
  ])
  assert(/\.atlas$/.test(download.suggestedFilename()), 'download did not produce a .atlas file')

  await page.getByPlaceholder('Local research variant').fill('Browser fork')
  await page.locator('.apps-fork input').nth(1).fill('1.0.1')
  await page.getByRole('button', { name: 'Fork locally' }).click()
  await page.getByTestId('apps-message').filter({ hasText: /^Forked locally/ }).waitFor({ timeout: 30000 })
  assert(await page.getByTestId('app-tile').count() === 2, 'fork was not added to the gallery')

  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(150)
  await page.screenshot({ path: path.join(OUT, '38-application-gallery.png'), fullPage: true })
  const desktop = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    nodes: document.querySelectorAll('*').length,
  }))
  assert(desktop.scrollWidth <= desktop.innerWidth + 1, 'desktop application gallery overflows')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${BASE}/applications`, { waitUntil: 'networkidle' })
  await page.getByTestId('app-detail').waitFor({ timeout: 30000 })
  const mobile = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))
  assert(mobile.scrollWidth <= mobile.innerWidth + 1, 'application gallery overflows at 390px')
  assert(await page.getByTestId('app-execute').isVisible(), 'execute action is clipped on mobile')
  const clipped = await page.getByTestId('app-detail').evaluate((root) =>
    [...root.querySelectorAll('.kv dt, .kv dd')]
      .filter((element) => element.scrollWidth > element.clientWidth + 1)
      .map((element) => `${element.textContent}: ${element.scrollWidth} > ${element.clientWidth}`))
  assert(clipped.length === 0, `detail values are clipped on mobile: ${clipped.join(' | ')}`)
  const labelHeights = await page.locator('.apps-export label, .apps-fork label').evaluateAll(
    (elements) => elements.map((element) => element.getBoundingClientRect().height))
  assert(Math.max(...labelHeights) < 80, `mobile form labels reserve excess height: ${labelHeights.join(', ')}`)
  await page.screenshot({ path: path.join(OUT, '39-applications-mobile.png'), fullPage: true })

  const gallery = await (await page.request.get(`${BASE}/api/applications`)).json()
  assert(gallery.count === 2, `expected two installations, found ${gallery.count}`)
  assert(gallery.pack_count === 0, 'unexpected domain pack in browser fixture')
  await writeFile(path.join(OUT, 'phase8_browser.json'), JSON.stringify({
    schema: 'atlas.phase8.browser.v1',
    base: BASE,
    schema_version: health.schema_version,
    fixture_bytes: fixtureInfo.size,
    fixture_sha256_prefix: '92ab1bf753438a0f',
    imported: true,
    executed: true,
    reproduced: true,
    test_rmse: 2956.577890101359,
    test_r2: -0.8934655019352953,
    forked: true,
    installations_after_fork: gallery.count,
    desktop_viewport: { width: 1440, height: 1100 },
    mobile_viewport: { width: 390, height: 844 },
    desktop_dom_nodes: desktop.nodes,
    screenshots: ['artifacts/38-application-gallery.png', 'artifacts/39-applications-mobile.png'],
  }, null, 2) + '\n')
} finally {
  await browser.close()
}

if (problems.length) {
  console.error('PHASE8 PROBLEMS:', problems.join(' | '))
  process.exit(1)
}
console.log('PHASE8_EXIT=0')
