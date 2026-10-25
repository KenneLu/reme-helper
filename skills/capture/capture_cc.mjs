#!/usr/bin/env node
// reme-claude-capture —— 把 Claude Code 会话增量喂给 ReMe 的 auto_memory。
//
// 这是"跨机会话捕获桥"的 Claude Code 版：当 ReMe 与 Claude Code 不在同一台机器上时，
// 官方插件（只把 session_id 交给服务端、由服务端读自己磁盘上的 transcript）读不到东西，
// 会返回"无消息"而钩子日志仍然正常。本脚本改成由客户端自己读 transcript、
// 自己算增量、内联成 messages 再提交，因此跨机也能记录。
//
// 与 Codex 版 capture.mjs 同构但彼此隔离：同一套机制（本地读 transcript → 内联
// messages → REST 提交 → 水位线去重），各自独立的脚本、状态、锁、队列与日志，
// 任一侧出问题不影响另一侧。
//
// 用法：
//   手动/批量：node capture_cc.mjs --last | --transcript <path> | --sweep [--submit] [--dry-run]
//   Stop hook：node capture_cc.mjs --hook      （stdin 收 hook 事件 JSON，毫秒级返回）
//   实际干活：node capture_cc.mjs --worker     （由 --hook 分离进程拉起，消费队列）
//
// 为什么 hook 本体不直接提交：会话结束时 Claude Code 会取消未完成的 hook，
// 直接提交会随会话结束被打断。因此 hook 只做路径解析 + 分离进程，立刻退出，
// 由 detached worker 完成网络提交与水位线更新；文件锁避免并发重复提交。
//
// 记录走 REST Job API（POST <端点>/auto_memory），不走 MCP：无需 initialize
// 握手与会话，链路更短，对隧道抖动更耐受。MCP 只服务于"回忆"。
//
// 消息结构对齐 Codex 版与 DSH 官方适配器：
//   { id, name(=role), role, content:[{type:'text',text}], created_at }
// id 是"会话短哈希 + 序号"的确定性取值，重发同一批消息时服务端按 id 去重，
// 因此失败重试天然幂等。
//
// 环境变量：
//   REME_URL           端点覆盖（可带 /mcp 后缀，会自动去掉）
//   CLAUDE_CONFIG_DIR  Claude Code 主目录覆盖（默认 ~/.claude）
//
// 运行时状态（水位线 / 锁 / 队列 / 日志）写在**本脚本同级的 bridge/ 目录**，
// 所以脚本放在哪里都行；与 Codex 侧的 reme-bridge/ 完全隔离。

import { readFile, writeFile, appendFile, readdir, mkdir, stat, rm } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { spawn } from 'node:child_process'
import { homedir } from 'node:os'
import { basename, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const BRIDGE_DIR = join(SCRIPT_DIR, 'bridge')
const STATE_FILE = join(BRIDGE_DIR, 'state.json')
const LOCK_FILE = join(BRIDGE_DIR, 'submit.lock')
const QUEUE_FILE = join(BRIDGE_DIR, 'queue.txt')
const LOG_FILE = join(BRIDGE_DIR, 'capture.log')

const CLAUDE_HOME = process.env.CLAUDE_CONFIG_DIR || join(homedir(), '.claude')
const PROJECTS_DIR = join(CLAUDE_HOME, 'projects')

// 插件自带的 .mcp.json 是端点的单一事实来源：钩子与 MCP 注册必须指向同一个地址，
// 所以按"离脚本最近的配置优先"依次找，找不到才用默认端口。
const MCP_CONFIG_CANDIDATES = [
  join(dirname(SCRIPT_DIR), '.mcp.json'),                      // <插件目录>/hooks/ 的上一层
  join(SCRIPT_DIR, '.mcp.json'),                               // 与脚本同目录
  join(CLAUDE_HOME, 'plugins', 'reme-claude', '.mcp.json'),    // 官方插件的默认落点
]

const LOCK_STALE_MS = 5 * 60 * 1000   // 陈旧锁回收阈值：worker 正常几秒完成，auto_memory 单次可达两分钟
const BATCH_MAX = 40                  // 单次提交的消息上限，超出的部分留给下一轮
const TOOL_EXCERPT = 200              // 工具调用/结果的正文截断长度

// 整条只含以下注入模板的轮次不是用户对话，丢弃。对齐官方 auto_memory_cc 的噪音前缀。
const INJECTED_TAGS = [
  '<local-command-caveat>', '<local-command-stdout>', '<local-command-stderr>',
  '<command-name>', '<command-message>', '<command-args>',
  '<system-reminder>', '<bash-input>', '<bash-stdout>', '<bash-stderr>',
]

/**
 * ReMe 端点解析优先级：REME_URL 环境变量 > 插件自带 .mcp.json > 默认本机 2333。
 * 去掉 /mcp 后缀得到 REST 根地址。经隧道接入的机器必须写隧道端口，
 * 而不是 ReMe 本机的默认端口 —— 写错的表现是 fetch failed / Connection refused。
 */
async function currentEndpoint() {
  const strip = (u) => u.trim().replace(/\/+$/, '').replace(/\/mcp$/, '')
  if (process.env.REME_URL) return strip(process.env.REME_URL)
  for (const candidate of MCP_CONFIG_CANDIDATES) {
    try {
      const cfg = JSON.parse(await readFile(candidate, 'utf8'))
      const url = cfg && cfg.mcpServers && cfg.mcpServers.reme && cfg.mcpServers.reme.url
      if (typeof url === 'string' && url.trim()) return strip(url)
    } catch { /* 换下一个候选 */ }
  }
  return 'http://127.0.0.1:2333'
}

function parseArgs(argv) {
  const out = { last: false, transcript: '', dryRun: false, sweep: false, submit: false, hook: false, worker: false, max: BATCH_MAX }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--last') out.last = true
    else if (a === '--dry-run') out.dryRun = true
    else if (a === '--sweep') out.sweep = true
    else if (a === '--submit') out.submit = true
    else if (a === '--hook') out.hook = true
    else if (a === '--worker') out.worker = true
    else if (a === '--transcript') out.transcript = argv[++i] || ''
    else if (a === '--max') out.max = Number(argv[++i]) || BATCH_MAX
  }
  return out
}

// hook 模式下 stdout 保持干净：诊断走 stderr，明细一律进日志文件。
function makeLog(hook) {
  return (msg) => { if (hook) console.error(msg); else console.log(msg) }
}

async function logLine(msg) {
  try {
    await mkdir(BRIDGE_DIR, { recursive: true })
    await appendFile(LOG_FILE, `${new Date().toISOString()} ${msg}\n`, 'utf8')
  } catch { /* 日志失败不影响主流程 */ }
}

async function readStdinJson() {
  if (process.stdin.isTTY) return null
  const chunks = []
  for await (const c of process.stdin) chunks.push(c)
  const text = Buffer.concat(chunks).toString('utf8').trim()
  if (!text) return null
  try { return JSON.parse(text) } catch { return null }
}

/** 列出 <CLAUDE_HOME>/projects/<项目目录>/<会话id>.jsonl，按修改时间升序。 */
async function collectTranscripts() {
  const found = []
  let projects
  try { projects = await readdir(PROJECTS_DIR, { withFileTypes: true }) } catch { return found }
  for (const p of projects) {
    if (!p.isDirectory()) continue
    const dir = join(PROJECTS_DIR, p.name)
    let files
    try { files = await readdir(dir, { withFileTypes: true }) } catch { continue }
    for (const f of files) {
      if (!f.isFile() || !f.name.endsWith('.jsonl')) continue
      const full = join(dir, f.name)
      try { found.push({ path: full, mtimeMs: (await stat(full)).mtimeMs }) } catch { /* 忽略瞬时文件 */ }
    }
  }
  return found.sort((a, b) => a.mtimeMs - b.mtimeMs)
}

/** 由会话 id 反查 transcript 路径（hook 事件没带路径时的回退）；同名取最新。 */
async function findTranscript(sessionId) {
  if (!sessionId) return ''
  const all = await collectTranscripts()
  const hit = all.filter((t) => basename(t.path, '.jsonl') === sessionId)
  return hit.length ? hit[hit.length - 1].path : ''
}

/** 把一条 content 块数组渲染成纯文本。thinking 块是私有推理，丢弃。 */
function renderContent(content) {
  if (typeof content === 'string') return content.trim()
  if (!Array.isArray(content)) return ''
  const parts = []
  for (const block of content) {
    if (!block || typeof block !== 'object') continue
    if (block.type === 'text') {
      const t = (block.text || '').trim()
      if (t) parts.push(t)
    } else if (block.type === 'tool_use') {
      let input
      try { input = JSON.stringify(block.input) } catch { input = String(block.input) }
      parts.push(`[tool ${block.name || '?'}(${(input || '').slice(0, TOOL_EXCERPT)})]`)
    } else if (block.type === 'tool_result') {
      const inner = Array.isArray(block.content) ? renderContent(block.content) : String(block.content || '')
      const excerpt = inner.trim()
      parts.push(`[tool_result ${excerpt.slice(0, TOOL_EXCERPT)}${excerpt.length > TOOL_EXCERPT ? '...' : ''}]`)
    }
  }
  return parts.join('\n').trim()
}

/** 去掉注入模板后几乎不剩内容的轮次，判为纯模板。 */
function isInjectedOnly(text) {
  const s = text.trim()
  if (!INJECTED_TAGS.some((tag) => s.startsWith(tag))) return false
  const remaining = s.replace(/<([a-z-]+)>[\s\S]*?<\/\1>/g, '')
  return remaining.trim().length < 16
}

/**
 * 解析 Claude Code transcript，产出按时间顺序的用户/助手消息。
 * 跳过 subagent 内部线程（isSidechain）——那不是用户对话，属于噪音。
 */
function extract(text) {
  const messages = []
  for (const line of text.split('\n')) {
    if (!line.trim()) continue
    let rec
    try { rec = JSON.parse(line) } catch { continue }
    if (rec.type !== 'user' && rec.type !== 'assistant') continue
    if (rec.isSidechain === true) continue
    const m = rec.message
    if (!m || (m.role !== 'user' && m.role !== 'assistant')) continue
    const body = renderContent(m.content)
    if (!body || isInjectedOnly(body)) continue
    messages.push({ role: m.role, content: body, createdAt: typeof rec.timestamp === 'string' ? rec.timestamp : '' })
  }
  return messages
}

/** 组装 ReMe 的 Msg：id 确定性，服务端据此去重，故重发同一批是幂等的。 */
function toRemeMessages(sessionId, batch, offset) {
  const short = createHash('sha256').update(sessionId).digest('hex').slice(0, 12)
  return batch.map((m, i) => ({
    id: `cc-${short}-${offset + i}`,
    name: m.role,
    role: m.role,
    content: [{ type: 'text', text: m.content }],
    ...(m.createdAt ? { created_at: m.createdAt } : {}),
  }))
}

async function loadState() {
  try { return JSON.parse(await readFile(STATE_FILE, 'utf8')) } catch { return { transcripts: {} } }
}

async function saveState(state) {
  await mkdir(BRIDGE_DIR, { recursive: true })
  await writeFile(STATE_FILE, JSON.stringify(state, null, 2) + '\n', 'utf8')
}

/** 获取锁；等待上限覆盖 auto_memory 单次最长耗时，避免与并发 worker 抢写。 */
async function acquireLock(attempts = 60, delayMs = 2000) {
  await mkdir(BRIDGE_DIR, { recursive: true })
  for (let i = 0; i < attempts; i++) {
    try {
      const s = await stat(LOCK_FILE)
      if (Date.now() - s.mtimeMs >= LOCK_STALE_MS) await rm(LOCK_FILE, { force: true })
    } catch { /* 无锁即正常 */ }
    try {
      await writeFile(LOCK_FILE, `${process.pid}\n`, { flag: 'wx' })
      return true
    } catch {
      await new Promise((r) => setTimeout(r, delayMs))
    }
  }
  return false
}

async function releaseLock() {
  try { await rm(LOCK_FILE, { force: true }) } catch { /* 忽略 */ }
}

async function appendQueue(path) {
  await mkdir(BRIDGE_DIR, { recursive: true })
  await appendFile(QUEUE_FILE, `${path}\n`, 'utf8')
}

/** 取出并清空队列（先清空再处理，避免处理期间新到的条目被覆盖）。 */
async function takeQueue() {
  let text = ''
  try { text = await readFile(QUEUE_FILE, 'utf8') } catch { return [] }
  await writeFile(QUEUE_FILE, '', 'utf8')
  return [...new Set(text.split('\n').map((s) => s.trim()).filter(Boolean))]
}

/** 提交一批消息到 ReMe 的 REST Job API。成功必须同时满足 200 与 success:true。 */
async function submit(sessionId, messages) {
  const endpoint = await currentEndpoint()
  const res = await fetch(`${endpoint}/auto_memory`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, messages, memory_hint: 'source: claude code session capture' }),
  })
  const raw = await res.text()
  let parsed = null
  try { parsed = JSON.parse(raw) } catch { /* 按失败处理 */ }
  const ok = res.status === 200 && parsed !== null && parsed.success === true
  const answer = parsed && typeof parsed.answer === 'string' ? parsed.answer.slice(0, 160) : ''
  return { ok, answer, raw: raw.replace(/\s+/g, ' ').slice(0, 240) }
}

/**
 * 处理单个 transcript：算出水位线之后的增量并提交。
 *
 * 两条纪律：
 *   ① 只取最前面的 N 条（oldest-first），未发的留给下一轮 —— 不会跳过中间的消息；
 *   ② 水位线只增不减：写回前重新读盘取 max，且只按"实际发出的条数"推进。
 * 否则手工提交与 Stop worker 并发时，两者各读旧值、各写回，后写者胜，水位线会被打回，
 * 已入库内容被反复重发。
 */
async function handleOne(path, args, state, { commit }) {
  let text
  try { text = await readFile(path, 'utf8') } catch { return { kind: 'missing', count: 0 } }
  const messages = extract(text)
  if (!messages.length) return { kind: 'empty', count: 0 }

  const sessionId = basename(path, '.jsonl')
  const stored = state.transcripts[path] || {}
  // transcript 被重写/截断时水位线失效，从头重来（id 确定性，服务端会去重）
  let seen = Number(stored.count || 0)
  if (seen > messages.length) seen = 0

  const fresh = messages.slice(seen)
  if (!fresh.length) return { kind: 'uptodate', sessionId, count: messages.length }

  const batch = fresh.slice(0, args.max)
  const payload = toRemeMessages(sessionId, batch, seen)

  if (!commit) {
    return { kind: 'pending', sessionId, count: messages.length, fresh: fresh.length, batch: batch.length, preview: batch[0].content.slice(0, 60) }
  }
  const result = await submit(sessionId, payload)
  if (result.ok) {
    const disk = await loadState()
    const cur = Number((disk.transcripts[path] || {}).count || 0)
    disk.transcripts[path] = { count: Math.max(cur, seen + batch.length), session_id: sessionId, at: new Date().toISOString() }
    state.transcripts = disk.transcripts
    await saveState(disk)
  }
  return { kind: result.ok ? 'submitted' : 'failed', sessionId, count: messages.length, fresh: fresh.length, batch: batch.length, answer: result.answer, raw: result.raw }
}

/**
 * 队列消费：一次处理所有待捕获 transcript，失败的重新入队以便下次重试。
 * 这就是"隧道断了不用管，连上自动补"的实现。
 */
async function runDrain() {
  const got = await acquireLock()
  if (!got) { await logLine('drain: lock still busy after retries; queue kept for next run'); return 0 }
  try {
    const paths = await takeQueue()
    if (!paths.length) return 0
    const state = await loadState()
    for (const path of paths) {
      try {
        const res = await handleOne(path, { max: BATCH_MAX }, state, { commit: true })
        await logLine(`worker ${res.kind} session=${res.sessionId || '-'} pending=${res.fresh || 0} sent=${res.batch || 0} msg=${res.answer || ''}`)
        if (res.kind === 'failed') await appendQueue(path)   // 交给下一轮重试
      } catch (err) {
        await logLine(`worker error path=${path} err=${err && err.message ? err.message : err}`)
        await appendQueue(path)
      }
    }
    return paths.length
  } finally {
    await releaseLock()
  }
}

/** hook 模式：解析事件 → 入队 → 拉起分离 worker → 立刻返回。 */
async function runHook() {
  const payload = await readStdinJson()
  const sessionId = (payload && payload.session_id) || ''
  let path = (payload && payload.transcript_path) || ''
  if (!path) path = await findTranscript(sessionId)     // transcript 还没落盘时按 id 回退查找
  if (!path) { await logLine(`hook event=Stop session=${sessionId || '-'} no transcript; skipped`); return 0 }

  await appendQueue(path)
  await logLine(`hook event=Stop session=${sessionId || '-'} queued path=${path}`)

  const child = spawn(process.execPath, [fileURLToPath(import.meta.url), '--worker'], {
    detached: true, stdio: 'ignore', windowsHide: true,
  })
  child.unref()
  await logLine(`hook spawned worker pid=${child.pid}`)
  return 0
}

/** worker 模式：独立进程里消费队列，不受会话结束影响。 */
async function runWorker(log) {
  const n = await runDrain()
  if (!n) log('no pending transcript')
  return 0
}

async function runSweep(args, log) {
  if (args.submit) {
    const got = await acquireLock()
    if (!got) { log('lock busy: another submit is running, try again later'); return 1 }
  }
  try {
    const all = await collectTranscripts()
    const state = await loadState()
    const stats = { total: all.length, submitted: 0, failed: 0, pending: 0, uptodate: 0, empty: 0 }
    for (const t of all) {
      const res = await handleOne(t.path, args, state, { commit: args.submit })
      if (res.kind === 'submitted') stats.submitted++
      else if (res.kind === 'failed') { stats.failed++; log(`  FAIL ${t.path} :: ${res.raw || ''}`) }
      else if (res.kind === 'pending') { stats.pending++; log(`  PENDING ${basename(t.path)} fresh=${res.fresh} batch=${res.batch} :: ${res.preview}`) }
      else if (res.kind === 'uptodate') stats.uptodate++
      else stats.empty++
    }
    log(JSON.stringify(stats, null, 2))
  } finally {
    if (args.submit) await releaseLock()
  }
  return 0
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  const log = makeLog(args.hook)
  if (args.hook) return runHook()
  if (args.worker) return runWorker(log)
  if (args.sweep) return runSweep(args, log)

  let path = args.transcript
  if (!path && args.last) {
    const all = await collectTranscripts()
    path = all.length ? all[all.length - 1].path : ''
  }
  if (!path) { log('usage: --last | --transcript <path> | --sweep [--submit] [--dry-run] | --hook | --worker'); return 1 }

  const committing = args.submit && !args.dryRun
  if (committing) {
    // 锁必须覆盖所有提交入口（hook worker / 单会话 / 全量回补），否则两条路径必然抢写。
    const got = await acquireLock()
    if (!got) { log('lock busy: another submit is running, try again later'); return 1 }
  }
  try {
    const state = await loadState()
    const res = await handleOne(path, args, state, { commit: committing })
    log(JSON.stringify({ ...res, endpoint: await currentEndpoint() }, null, 2))
  } finally {
    if (committing) await releaseLock()
  }
  return 0
}

main().then((code) => process.exit(code)).catch(async (err) => {
  await logLine(`fatal err=${err && err.stack ? err.stack : err}`)
  process.exit(1)
})
