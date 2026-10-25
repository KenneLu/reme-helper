#!/usr/bin/env node
// reme-zcode-capture —— 把 ZCode 原生会话增量喂给 ReMe 的 auto_memory。
//
// 这是"捕获桥"的 ZCode 版，与 capture.mjs（Codex）、capture_cc.mjs（Claude Code）同构但彼此隔离：
// 同一套机制（本地读对话文件 → 水位线取增量 → 内联 messages → REST 提交），
// 各自独立的脚本、状态、锁、队列与日志，任一侧出问题不影响另一侧。
//
// 为什么需要它：ZCode 原生会话（bigmodel 路线）的对话记录写在
//   <ZCODE_HOME>/cli/rollout/model-io-sess_<id>.jsonl
// 既没有 ~/.claude/projects 转录（官方 Claude Code 钩子的前提），也没有 Codex 的 rollout。
// 按接入规格（reme-helper doc/zh/setup.md §4）移植，只改了四处：
//   对话文件目录、文件匹配规则、解析器、噪音前缀；其余基础设施共用。
//
// rollout 文件格式（每行一条模型 I/O 记录）：
//   { querySource, sessionId, turnId, attempt, startedAt, completedAt,
//     request: { messagesKind: full|delta|tail, messageOffset, messageCount, messages: [...] },
//     response: { text, reasoningText, toolCalls: [{id,name,input}], ... } }
// messages 条目：{ role: system|user|assistant|tool, content: str|块数组, tool_calls?, toolCallId?, toolName? }
// full=全量（offset=0）；delta=从 offset 起的增量；tail=丢掉头部 offset 条的尾部窗口。
// 三种都能用「绝对下标 = messageOffset + j」定位，逐行覆盖写入即可重建完整对话；
// 每行还带一条 response（模型本轮回复），它要等下一行才进历史——所以最后一行的
// response 要单独补到对话末尾，否则每次 Stop 都会漏掉最后一条助手消息。
//
// 用法：
//   手动/批量：node capture_zcode.mjs --last | --transcript <path> | --sweep [--submit] [--dry-run]
//   Stop hook：node capture_zcode.mjs --hook    （stdin 收 hook 事件 JSON，毫秒级返回）
//   实际干活：node capture_zcode.mjs --worker   （由 --hook 分离进程拉起，消费队列）
//
// 为什么 hook 本体不直接提交：会话结束时未完成的钩子会被取消，直接提交等于丢记录。
// hook 只做路径解析 + 分离进程，立刻退出；由 detached worker 完成网络提交与水位线更新。
//
// 记录走 REST Job API（POST <端点>/auto_memory），不走 MCP：无需握手，链路短。
// 消息结构对齐 Codex 版与接入规格 §2：{ id, name(=role), role, content:[{type:'text',text}], created_at }
// id = "zc-会话短哈希-绝对下标"，服务端按 id 去重，失败重试天然幂等。
//
// 环境变量：
//   REME_URL          端点覆盖（可带 /mcp 后缀，会自动去掉）
//   ZCODE_HOME        ZCode 主目录覆盖（默认 ~/.zcode；rollout 在其 cli/rollout 下）

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

const ZCODE_HOME = process.env.ZCODE_HOME || join(homedir(), '.zcode')
const ROLLOUT_DIR = join(ZCODE_HOME, 'cli', 'rollout')
const ROLLOUT_PREFIX = 'model-io-sess_'

// 端点解析优先级与各端一致：REME_URL 环境变量 > 脚本同目录 config.json > 默认本机 2333。
const ENDPOINT_CONFIG = join(SCRIPT_DIR, 'config.json')

const LOCK_STALE_MS = 5 * 60 * 1000   // 陈旧锁回收阈值：worker 正常几秒完成，auto_memory 单次可达两分钟
const BATCH_MAX = 40                  // 单次提交的消息上限，超出的部分留给下一轮
const TOOL_EXCERPT = 200              // 工具调用/结果的正文截断长度

// 整条只含以下注入模板的轮次不是用户对话，丢弃。对齐 Codex/Claude Code 两版的前缀。
const INJECTED_TAGS = [
  '<local-command-caveat>', '<local-command-stdout>', '<local-command-stderr>',
  '<command-name>', '<command-message>', '<command-args>',
  '<system-reminder>', '<bash-input>', '<bash-stdout>', '<bash-stderr>',
  '<environment_context>', '<task-notification>',
]

async function currentEndpoint() {
  const strip = (u) => u.trim().replace(/\/+$/, '').replace(/\/mcp$/, '')
  if (process.env.REME_URL) return strip(process.env.REME_URL)
  try {
    const cfg = JSON.parse(await readFile(ENDPOINT_CONFIG, 'utf8'))
    const url = cfg && cfg.mcpServers && cfg.mcpServers.reme && cfg.mcpServers.reme.url
    if (typeof url === 'string' && url.trim()) return strip(url)
  } catch { /* 落到默认端口 */ }
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

/** 列出 rollout 目录下的 model-io-sess_*.jsonl，按修改时间升序。 */
async function collectRollouts() {
  const found = []
  let files
  try { files = await readdir(ROLLOUT_DIR, { withFileTypes: true }) } catch { return found }
  for (const f of files) {
    if (!f.isFile() || !f.name.startsWith(ROLLOUT_PREFIX) || !f.name.endsWith('.jsonl')) continue
    const full = join(ROLLOUT_DIR, f.name)
    try { found.push({ path: full, mtimeMs: (await stat(full)).mtimeMs }) } catch { /* 忽略瞬时文件 */ }
  }
  return found.sort((a, b) => a.mtimeMs - b.mtimeMs)
}

/** 会话 id 的形态可能是 sess_<uuid>、<uuid> 或完整文件名stem，统一按后缀匹配。 */
async function findRollout(sessionId) {
  if (!sessionId) return ''
  const all = await collectRollouts()
  const hit = all.filter((t) => basename(t.path, '.jsonl').endsWith(sessionId))
  return hit.length ? hit[hit.length - 1].path : ''
}

/** 把 assistant 的 content 块数组渲染成纯文本。reasoning 块是私有推理，丢弃。 */
function renderBlocks(blocks) {
  if (!Array.isArray(blocks)) return ''
  const parts = []
  for (const block of blocks) {
    if (!block || typeof block !== 'object') continue
    if (block.type === 'text') {
      const t = (block.text || '').trim()
      if (t) parts.push(t)
    } else if (block.type === 'tool_use' || block.type === 'toolCall') {
      let input
      try { input = JSON.stringify(block.input ?? block.arguments ?? {}) } catch { input = '' }
      parts.push(`[tool ${block.name || block.toolName || '?'}(${(input || '').slice(0, TOOL_EXCERPT)})]`)
    }
    // reasoning / thinking 等其余块类型一律丢弃
  }
  return parts.join('\n').trim()
}

function renderToolCalls(calls) {
  if (!Array.isArray(calls)) return ''
  const parts = []
  for (const c of calls) {
    if (!c) continue
    let input
    try { input = JSON.stringify(c.input ?? (c.function ? c.function.arguments : c.arguments) ?? {}) } catch { input = '' }
    parts.push(`[tool ${c.name || (c.function && c.function.name) || '?'}(${(input || '').slice(0, TOOL_EXCERPT)})]`)
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

/** 把单条 rollout 消息渲染成 { role, content }，不渲染时返回 null。
 *  ReMe 的 Msg 只收 user/assistant/system，tool 结果归入 user 侧（与 Claude 版内联位置一致）。 */
function renderMessage(m) {
  if (!m || typeof m !== 'object') return null
  const role = m.role
  if (role !== 'user' && role !== 'assistant' && role !== 'tool') return null   // system 是宿主样板
  let body = ''
  if (role === 'tool') {
    const inner = String(m.content || '')
    body = `[tool_result ${inner.slice(0, TOOL_EXCERPT)}${inner.length > TOOL_EXCERPT ? '...' : ''}]`
  } else if (typeof m.content === 'string') {
    body = m.content.trim()
  } else {
    body = renderBlocks(m.content)
  }
  if (role === 'assistant') {
    const calls = renderToolCalls(m.tool_calls)
    if (calls) body = body ? `${body}\n${calls}` : calls
  }
  if (!body || isInjectedOnly(body)) return null
  return { role: role === 'tool' ? 'user' : role, content: body }
}

/**
 * 解析 rollout 文件，重建按时间顺序的用户/助手消息。
 *
 * 做法：按绝对下标「逐行覆盖写格子」——每行消息 j 位于对话下标 messageOffset + j，
 * full/delta/tail 三种存法通用；后写的行覆盖先写的（历史被改写时以最新为准）。
 * 只吃 querySource=main_turn 的行：session_title 之类辅助调用的消息坐标系完全不同，混进来必错。
 * 扫完后把最后一行的 response 补到末尾——它要等下一行才进历史，不补每次都漏最后一条。
 */
function extract(text) {
  const cells = new Map()   // 对话绝对下标 -> { role, content, createdAt }
  let lastMain = null
  for (const line of text.split('\n')) {
    if (!line.trim()) continue
    let rec
    try { rec = JSON.parse(line) } catch { continue }
    if (rec.querySource !== 'main_turn') continue
    const msgs = rec.request && rec.request.messages
    if (!Array.isArray(msgs)) continue
    const ts = typeof rec.completedAt === 'string' ? rec.completedAt : ''
    const off = Number(rec.request.messageOffset) || 0
    msgs.forEach((m, j) => {
      const rendered = renderMessage(m)
      if (rendered) cells.set(off + j, { ...rendered, createdAt: ts })
    })
    lastMain = { rec, ts }
  }
  if (!lastMain) return []

  // 对话总长以最后一行为准（messageCount 三种存法都是"到本行为止的总条数"）
  const req = lastMain.rec.request || {}
  const total = Number(req.messageCount) || 0
  const messages = []
  for (let i = 0; i < total; i++) {
    const cell = cells.get(i)
    if (cell) messages.push({ role: cell.role, content: cell.content, createdAt: cell.createdAt })
  }

  // 最后一行的 response 是尚未进历史的助手回复，补到末尾
  const resp = lastMain.rec.response || {}
  const tail = [String(resp.text || '').trim(), renderToolCalls(resp.toolCalls)].filter(Boolean).join('\n').trim()
  if (tail) messages.push({ role: 'assistant', content: tail, createdAt: lastMain.ts })
  return messages
}

/** 组装 ReMe 的 Msg：id 确定性（绝对下标即序号），服务端据此去重，重发同一批是幂等的。 */
function toRemeMessages(sessionId, batch, offset) {
  const short = createHash('sha256').update(sessionId).digest('hex').slice(0, 12)
  return batch.map((m, i) => ({
    id: `zc-${short}-${offset + i}`,
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
    body: JSON.stringify({ session_id: sessionId, messages, memory_hint: 'source: zcode session capture' }),
  })
  const raw = await res.text()
  let parsed = null
  try { parsed = JSON.parse(raw) } catch { /* 按失败处理 */ }
  const ok = res.status === 200 && parsed !== null && parsed.success === true
  const answer = parsed && typeof parsed.answer === 'string' ? parsed.answer.slice(0, 160) : ''
  return { ok, answer, raw: raw.replace(/\s+/g, ' ').slice(0, 240) }
}

/**
 * 处理单个 rollout：算出水位线之后的增量并提交。
 *
 * 两条纪律：
 *   ① 只取最前面的 N 条（oldest-first），未发的留给下一轮 —— 不会跳过中间的消息；
 *   ② 水位线只增不减：写回前重新读盘取 max，且只按"实际发出的条数"推进。
 */
async function handleOne(rawPath, args, state, { commit }) {
  // 水位线按路径记账：手动调用与 hook worker 拿到的斜杠方向可能不同（C:/ 与 C:\），
  // 不统一就会裂成两条水位线、互相打回。统一成正斜杠后再当键用（node 的 fs 两边都认）。
  const path = rawPath.replace(/\\/g, '/')
  let text
  try { text = await readFile(path, 'utf8') } catch { return { kind: 'missing', count: 0 } }
  const messages = extract(text)
  if (!messages.length) return { kind: 'empty', count: 0 }

  const sessionId = basename(path, '.jsonl').replace(/^model-io-/, '')
  const stored = state.transcripts[path] || {}
  // 对话被压缩改写导致总条数缩水时水位线失效，从头重来（id 确定性，服务端会去重）
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

/** 队列消费：一次处理所有待捕获 rollout，失败的重新入队以便下次重试。 */
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
  const sessionId = (payload && payload.session_id) || process.env.CLAUDE_SESSION_ID || ''
  let path = await findRollout(sessionId)
  if (!path && !sessionId) {
    // 拿不到会话 id 时才用"最近修改"兜底；有 id 但匹配不到宁可跳过，不能张冠李戴
    const all = await collectRollouts()
    path = all.length ? all[all.length - 1].path : ''
  }
  if (!path) { await logLine(`hook event=Stop session=${sessionId || '-'} no rollout; skipped`); return 0 }

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
    const all = await collectRollouts()
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
    const all = await collectRollouts()
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
