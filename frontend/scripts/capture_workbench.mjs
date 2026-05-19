import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const frontendRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(frontendRoot, '..')

const targetUrl = process.env.SHOT_URL || 'http://127.0.0.1:5173'
const requestedScenario = process.env.SHOT_NAME || 'all'
const outDir = process.env.SHOT_OUT_DIR || path.join(repoRoot, '.runtime', 'ui_shots')
const viewportWidth = Number(process.env.SHOT_WIDTH || 1600)
const viewportHeight = Number(process.env.SHOT_HEIGHT || 1100)

const scenarios = {
  default: { selector: '' },
  leftRail: { selector: '[data-shot="left-rail"]', texts: ['大纲'] },
  centerSurface: { selector: '[data-shot="center-surface"]' },
  rightRail: { selector: '[data-shot="right-rail"]' },
  rightRailDropdown: { selector: '[data-shot="right-rail"]', prepare: 'chat-history', includeInAll: false },
  defaultEn: { selector: '', prepare: 'english', includeInAll: false },
  rightRailEn: { selector: '[data-shot="right-rail"]', prepare: 'english', includeInAll: false },
  messageEditHover: { selector: '[data-shot="right-rail"]', prepare: 'message-edit-hover', includeInAll: false },
  messageEditInline: { selector: '[data-shot="right-rail"]', prepare: 'message-edit-inline', includeInAll: false },
  thinkStreaming: { selector: '[data-shot="right-rail"]', prepare: 'think-stream', includeInAll: false },
  conversationRail: { selector: '[data-shot="conversation-rail"]' },
  conversationBody: { selector: '[data-shot="conversation-body"]' },
  gitDefault: { selector: '', prepare: 'git' },
  reviewWorkspace: { selector: '', prepare: 'review', includeInAll: false },
}

async function prepareScenario(page, prepare) {
  if (prepare === 'message-edit-hover' || prepare === 'message-edit-inline') {
    const prompt = 'codex-inline-edit-smoke'
    const input = page.locator('input[placeholder*="输入你的指令"], input[placeholder*="Ask anything"]').first()
    await input.fill(prompt)
    await page.locator('button').filter({ hasText: /^(发送|Send)$/ }).first().click()
    const userBubble = page.getByText(prompt, { exact: true }).last()
    await userBubble.waitFor({ timeout: 15000, state: 'visible' })
    await userBubble.hover()
    await page.waitForTimeout(250)
    if (prepare === 'message-edit-inline') {
      const editButton = page.locator('[data-shot="conversation-body"]').getByRole('button', { name: /^(编辑|Edit)$/ }).last()
      await editButton.click()
      await page.waitForTimeout(300)
    }
    return
  }

  if (prepare === 'think-stream') {
    const outlineFile = page.getByText('arc_outline.md', { exact: true }).first()
    await outlineFile.click()
    await page.waitForTimeout(400)
    const prompt = '你认为我们篇章二esl具体的章节大纲应该如何写？你有什么想法吗？'
    const input = page.locator('input[placeholder*="输入你的指令"], input[placeholder*="Ask anything"]').first()
    await input.fill(prompt)
    await page.locator('button').filter({ hasText: /^(发送|Send)$/ }).first().click()
    await page.waitForTimeout(3500)
    return
  }

  if (prepare === 'english') {
    const englishToggle = page.getByRole('button', { name: 'English' }).first()
    await englishToggle.click()
    await page.waitForTimeout(250)
    return
  }

  if (prepare === 'git') {
    const gitModeButton = page.getByRole('button', { name: /^(Git|版本)$/ }).first()
    await gitModeButton.click()
    await page.waitForTimeout(500)
    return
  }

  if (prepare === 'review') {
    const outlineFile = page.getByText('arc_outline.md', { exact: true }).first()
    await outlineFile.click()
    await page.waitForTimeout(400)
    const prompt = process.env.SHOT_REVIEW_PROMPT || '把当前 arc_outline.md 里已经稳定的篇章内容下沉到 chapter_outline.md，只生成一份很小的草稿。'
    const input = page.locator('input[placeholder*="输入你的指令"], input[placeholder*="输出进行中"], input[placeholder*="修改最后一问"], input[placeholder*="Ask anything"], input[placeholder*="Still streaming"], input[placeholder*="Rewrite the last turn"]').first()
    await input.fill(prompt)
    await page.locator('button').filter({ hasText: /^(发送|Send)$/ }).first().click()
    await page.locator('button').filter({ hasText: /^(进入审阅|Enter review)$/ }).first().waitFor({ timeout: 120000, state: 'visible' })
    await page.locator('button').filter({ hasText: /^(进入审阅|Enter review)$/ }).first().click()
    await page.waitForSelector('text=/审阅检查器|Review Inspector/', { timeout: 120000, state: 'visible' })
    await page.waitForSelector('text=/审阅画布|Review Canvas/', { timeout: 120000, state: 'visible' })
    return
  }

  if (prepare === 'chat-history') {
    const currentConversation = page.locator('[data-shot="conversation-rail"] button[aria-expanded]').first()
    await currentConversation.click()
    await page.waitForTimeout(350)
  }
}

await mkdir(outDir, { recursive: true })

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({
  viewport: { width: viewportWidth, height: viewportHeight },
  deviceScaleFactor: 1,
})

try {
  await page.goto(targetUrl, { waitUntil: 'networkidle', timeout: 30000 })
  await page.evaluate(() => {
    document.documentElement.style.scrollBehavior = 'auto'
  })
  const scenarioNames = requestedScenario === 'all'
    ? Object.entries(scenarios).filter(([, config]) => config.includeInAll !== false).map(([name]) => name)
    : [requestedScenario]
  const outputs = []
  for (const scenario of scenarioNames) {
    const config = scenarios[scenario]
    if (!config)
      throw new Error(`Unknown screenshot scenario: ${scenario}`)
    await page.goto(targetUrl, { waitUntil: 'networkidle', timeout: 30000 })
    await prepareScenario(page, config.prepare)
    const outPath = path.join(outDir, `${scenario}.png`)
    if (config.selector) {
      const handle = await page.waitForSelector(config.selector, { timeout: 10000, state: 'visible' })
      if (config.texts) {
        for (const text of config.texts) {
          await page.waitForSelector(`text=${text}`, { timeout: 10000, state: 'visible' })
        }
      }
      await handle.screenshot({ path: outPath })
    } else {
      await page.screenshot({ path: outPath, fullPage: true })
    }
    outputs.push({
      scenario,
      selector: config.selector || null,
      output: outPath,
    })
  }

  console.log(JSON.stringify({
    status: 'success',
    requestedScenario,
    url: targetUrl,
    viewport: { width: viewportWidth, height: viewportHeight },
    outputs,
  }))
} finally {
  await page.close().catch(() => undefined)
  await browser.close().catch(() => undefined)
}
