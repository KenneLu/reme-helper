#!/usr/bin/env node
// reme-codex-capture —— 把 Codex 会话增量喂给 ReMe 的 auto_memory。
//
// 用法：
//   手动/批量：node capture.mjs --last | --rollout <path> | --sweep [--submit] [--dry-run]
//   Codex hook：node capture.mjs --hook      （stdin 收 hook 事件 JSON，毫秒级返回）
//   实际干活的：node capture.mjs --worker <transcript_path>   （由 --hook 分离进程拉起）
//
// 为什么 hook 本体不直接提交：
//   Codex 在会话结束时（exec 跑完、桌面端关闭会话）会取消未完成的后台/同步 hook；
//   直接提交会随会话结束被打断。因此 hook 只做路径解析 + 分离进程，立刻退出，
//   由 detached worker 完成网络提交与水位线更新；文件锁避免并发重复提交。
//
// hook 模式下 stdout 必须是合法 JSON（Stop 事件要求），因此只输出 `{}`，诊断走 stderr/日志。
//
// 消息结构对齐 DSH 官方适配器 dist/messages.js：
//   { id, name(=role), role, content:[{type:'text',text}], created_at }
// ReMe 的 Msg 模型要求 name 字段，缺失会报 validation error。
//
// 环境变量：CODEX_HOME（默认 ~/.codex）、REME_URL（默认 http://127.0.0.1:2333）

import { readFile, writeFile, appendFile, readdir, mkdir, stat, rm } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { spawn } from 'node:child_process'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const CODEX_HOME = process.env.CODEX_HOME || join(homedir(), '.codex')
const BRIDGE_DIR = join(CODEX_HOME, 'reme-bridge')
const STATE_FILE = join(BRIDGE_DIR, 'state.json')
const LOCK_FILE = join(BRIDGE_DIR, 'submit.lock')
const QUEUE_FILE = join(BRIDGE_DIR, 'queue.txt')
const LOG_FILE = join(BRIDGE_DIR, 'capture.log')
const SESSIONS_DIR = join(CODEX_HOME, 'sessions')
const LOCK_STALE_MS = 5 * 60 * 1000
const NOISE_PREFIXES = [
  '<permissions instructions>', '<environment_context>', '<user_instructions>', '<turn_context>',
  '<recommended_plugins>',
  'The following is the Codex agent history added since your last approval assessment'
]

/**
 * ReMe 端点优先级：环境变量 REME_URL > 本目录 config.json 的 endpoint > 默认 http://127.0.0.1:2333。
 * reme 只监听回环地址：同机直连用 2333；经 reme-helper 反向隧穿的机器（如 VM）必须用隧道端口
 * （例如 22333）。所以端点必须能在不改脚本的前提下切换 —— 这就是 config.json 存在的理由。
 */
async function currentEndpoint() {
  if (process.env.REME_URL) return process.env.REME_URL.replace(/\/$/, '')
  try {
    const cfg = JSON.parse(await readFile(join(BRIDGE_DIR, 'config.json'), 'utf8'))
    if (cfg && typeof cfg.endpoint === 'string' && cfg.endpoint.trim()) return cfg.endpoint.trim().replace(/\/$/, '')
  } catch { /* 无配置文件则用默认 */ }
  return 'http://127.0.0.1:2333'
}

function parseArgs(argv) {
  const out = { last: false, rollout: '', dryRun: false, sweep: false, submit: false, hook: false, worker: '', drain: false, max: 40 }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--last') out.last = true
    else if (a === '--dry-run') out.dryRun = true
    else if (a === '--sweep') out.sweep = true
    else if (a === '--submit') out.submit = true
    else if (a === '--hook') out.hook = true
    else if (a === '--worker') out.worker = argv[++i] || ''
    else if (a === '--rollout') out.rollout = argv[++i] || ''
    else if (a === '--drain') out.drain = true
    else if (a === '--max') out.max = Number(argv[++i]) || 40
  }
  return out
}

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

async function collectRollouts() {
  const found = []
  async function walk(dir) {
    let entries
    try { entries = await readdir(dir, { withFileTypes: true }) } catch { return }
    for (const e of entries) {
      const p = join(dir, e.name)
      if (e.isDirectory()) await walk(p)
      else if (e.isFile() && e.name.startsWith('rollout-') && e.name.endsWith('.jsonl')) {
        const s = await stat(p)
        found.push({ path: p, mtimeMs: s.mtimeMs })
      }
    }
  }
  await walk(SESSIONS_DIR)
  return found.sort((a, b) => a.mtimeMs - b.mtimeMs)
}

function extract(text) {
  const messages = []
  let fileId = ''
  let source = null
  for (const line of text.split('\n')) {
    if (!line.trim()) continue
    let o
    try { o = JSON.parse(line) } catch { continue }
    if (o.type === 'session_meta' && o.payload) {
      fileId = o.payload.id || o.payload.session_id || fileId
      source = o.payload.source === undefined ? null : o.payload.source
      continue
    }
    if (o.type !== 'response_item' || !o.payload || o.payload.type !== 'message') continue
    const role = o.payload.role
    if (role !== 'user' && role !== 'assistant') continue
    const parts = Array.isArray(o.payload.content) ? o.payload.content : []
    const body = parts.map((c) => (c && typeof c.text === 'string' ? c.text : '')).join('\n').trim()
    if (!body) continue
    if (NOISE_PREFIXES.some((p) => body.startsWith(p))) continue
    messages.push({ role, content: body, createdAt: typeof o.timestamp === 'string' ? o.timestamp : '' })
  }
  return { messages, fileId, source }
}

const isInternal = (source) => source !== null && typeof source === 'object'

async function loadState() {
  try { return JSON.parse(await readFile(STATE_FILE, 'utf8')) } catch { return { rollouts: {} } }
}

async function saveState(state) {
  await mkdir(BRIDGE_DIR, { recursive: true })
  await writeFile(STATE_FILE, JSON.stringify(state, null, 2) + '\n', 'utf8')
}

/** 获取锁；允许重试以覆盖并发会话（另一个 worker 通常 2~4 秒完成）。 */
async function acquireLock(attempts = 12, delayMs = 700) {
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

function toRemeMessages(sessionId, batch, offset) {
  const short = createHash('sha256').update(sessionId).digest('hex').slice(0, 12)
  return batch.map((m, i) => ({
    id: `codex-${short}-${offset + i}`,
    name: m.role,
    role: m.role,
    content: [{ type: 'text', text: m.content }],
    ...(m.createdAt ? { created_at: m.createdAt } : {})
  }))
}

async function submit(sessionId, messages) {
  const endpoint = await currentEndpoint()
  const res = await fetch(`${endpoint}/auto_memory`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, messages, memory_hint: 'source: codex session capture' })
  })
  const raw = await res.text()
  let parsed = null
  try { parsed = JSON.parse(raw) } catch { /* 按失败处理 */ }
  const ok = res.status === 200 && parsed !== null && parsed.success === true
  return { ok, answer: parsed && typeof parsed.answer === 'string' ? parsed.answer.slice(0, 160) : '', raw: raw.replace(/\s+/g, ' ').slice(0, 240) }
}

async function handleOne(path, args, state, { commit }) {
  const text = await readFile(path, 'utf8')
  const { messages, fileId, source } = extract(text)
  if (isInternal(source)) return { kind: 'internal', count: 0 }
  if (!messages.length) return { kind: 'empty', count: 0 }
  const seen = Number((state.rollouts[path] || {}).count || 0)
  const fresh = messages.slice(seen)
  if (!fresh.length) return { kind: 'uptodate', count: messages.length }
  const batch = fresh.slice(-args.max)
  const sessionId = `codex-${fileId || 'unknown'}`
  const payload = toRemeMessages(sessionId, batch, seen)
  if (!commit) return { kind: 'pending', count: messages.length, fresh: batch.length, sessionId, preview: batch[0] && batch[0].content.slice(0, 60) }
  const result = await submit(sessionId, payload)
  if (result.ok) {
    state.rollouts[path] = { count: messages.length, sessionId, at: new Date().toISOString() }
    await saveState(state)
  }
  return { kind: result.ok ? 'submitted' : 'failed', count: messages.length, fresh: batch.length, sessionId, answer: result.answer }
}

/** 队列消费：一次处理所有待捕获 transcript，失败的重新入队以便下次重试。 */
async function runDrain() {
  const got = await acquireLock()
  if (!got) { await logLine('drain: lock still busy after retries; queue kept for next run'); return 0 }
  try {
    const paths = await takeQueue()
    if (!paths.length) return 0
    const state = await loadState()
    let failed = 0
    for (const path of paths) {
      try {
        const res = await handleOne(path, { max: 40, dryRun: false }, state, { commit: true })
        await logLine(`worker ${res.kind} session=${res.sessionId || '-'} fresh=${res.fresh || 0} msg=${res.answer || ''}`)
        if (res.kind === 'failed') { failed++; await appendQueue(path) }
      } catch (err) {
        failed++
        await appendQueue(path)
        await logLine(`worker error path=${path} err=${err?.message || err}`)
      }
    }
    return failed ? 1 : 0
  } finally {
    await releaseLock()
  }
}

async function runSweep(args, log) {
  const rollouts = await collectRollouts()
  const state = await loadState()
  const stats = { rollouts: rollouts.length, internal: 0, empty: 0, uptodate: 0, pending: [], submitted: 0, failed: 0, failedSample: [] }
  for (const r of rollouts) {
    const res = await handleOne(r.path, args, state, { commit: args.submit })
    if (res.kind === 'internal') stats.internal++
    else if (res.kind === 'empty') stats.empty++
    else if (res.kind === 'uptodate') stats.uptodate++
    else if (res.kind === 'pending') stats.pending.push({ sessionId: res.sessionId, fresh: res.fresh, preview: res.preview })
    else if (res.kind === 'submitted') stats.submitted++
    else if (res.kind === 'failed') { stats.failed++; if (stats.failedSample.length < 3) stats.failedSample.push({ sessionId: res.sessionId, answer: res.answer }) }
  }
  log(JSON.stringify({
    mode: args.submit ? 'sweep+submit' : 'sweep(dry)',
    rollouts: stats.rollouts, internal: stats.internal, empty: stats.empty, upToDate: stats.uptodate,
    pendingRollouts: stats.pending.length,
    pendingMessages: stats.pending.reduce((n, x) => n + x.fresh, 0),
    pendingSample: stats.pending.slice(-5),
    submitted: stats.submitted, failed: stats.failed, failedSample: stats.failedSample
  }, null, 2))
  return stats.failed ? 1 : 0
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  const log = makeLog(args.hook)

  // 分离出来的实际执行者：统一走队列，避免并发会话互相顶掉
  if (args.drain) return runDrain()
  if (args.worker) { await appendQueue(args.worker); return runDrain() }

  if (args.hook) {
    const evt = await readStdinJson()
    let path = evt && typeof evt.transcript_path === 'string' ? evt.transcript_path : ''
    if (!path) {
      const rollouts = await collectRollouts()
      path = rollouts.length ? rollouts[rollouts.length - 1].path : ''
    }
    if (path) {
      await appendQueue(path)
      const child = spawn(process.execPath, [fileURLToPath(import.meta.url), '--drain'], {
        detached: true, stdio: 'ignore', windowsHide: true
      })
      child.unref()
      await logLine(`hook event=${evt && evt.hook_event_name} session=${evt && evt.session_id} queued+drain pid=${child.pid} path=${path}`)
    } else {
      await logLine('hook: no transcript path resolved')
    }
    // Stop 事件要求退出 0 时 stdout 为合法 JSON
    process.stdout.write('{}\n')
    return 0
  }

  if (args.sweep) return runSweep(args, log)

  const rollouts = await collectRollouts()
  const path = args.rollout || (rollouts.length ? rollouts[rollouts.length - 1].path : '')
  if (!path) { log('no rollout found'); return 0 }

  const state = await loadState()
  const res = await handleOne(path, args, state, { commit: !args.dryRun })
  if (res.kind === 'internal') log('skip: internal codex thread — not a user conversation')
  else if (res.kind === 'empty') log(`no capturable messages in ${path}`)
  else if (res.kind === 'uptodate') log(`nothing new (${res.count} messages already captured)`)
  else if (args.dryRun) log(JSON.stringify({ rollout: path, sessionId: res.sessionId, fresh: res.fresh, preview: res.preview }, null, 2))
  else log(JSON.stringify({ rollout: path, sessionId: res.sessionId, submitted: res.fresh, ok: res.kind === 'submitted', answer: res.answer }, null, 2))
  return res.kind === 'failed' ? 1 : 0
}

main().then((c) => process.exit(c)).catch((err) => { console.error('capture failed:', err?.message || err); process.exit(1) })
