# Connecting Codex and DSH to ReMe (Agent setup guide)

> **How to use this document**: read it first by clicking "Read the setup guide" in reme-helper, or click
> "Copy the setup guide" and paste the **entire copied text** into an AI agent that can read and write files on this
> machine — it can then do the integration by following this document.
> `<...>` are placeholders to substitute with real local values (see the variable table; the ReMe port and
> workspace are already filled in when you copy from reme-helper).

This document covers exactly one thing — connecting clients to ReMe. It is independent of any specific skill or
third-party tool. Every step has been verified on real machines; implement it as written rather than designing
an alternative.

---

## 0. Variables

| Placeholder | Meaning | Source |
|---|---|---|
| `<REME_PORT>` | ReMe HTTP port | reme-helper settings, default `2333` |
| `<REME_WORKSPACE>` | ReMe memory directory (contains `daily/ digest/ session/`) | `workspace` under reme-helper's ReMe directory |
| `<DSH_HOME>` | DSH home | Windows default `%USERPROFILE%\.dsh` |
| `<DSH_PROFILE>` | Profile to integrate | `web` for the Web UI |
| `<CODEX_HOME>` | Codex home | Windows default `%USERPROFILE%\.codex` |
| `<SRC_DIR>` | Scratch directory for sources | your choice |
| `<REMOTE_PORT>` | Tunnel port on the VM | reme-helper's VM target settings, e.g. `22333` |
| `<VM_HOST>`, `<VM_USER>` | VM address and user | your environment |
| `<VM_CODEX_HOME>` | Codex home inside the VM | e.g. `/home/<VM_USER>/.codex` |

**Prerequisites**: reme-helper is running ReMe (full mode + LLM + embedding) and
`POST http://127.0.0.1:<REME_PORT>/health_check` returns `healthy: true`.
ReMe listens on **loopback only** and uses **no API key** — which is why cross-machine access needs a tunnel
and why every client must point at the same single workspace.

---

## 1. What you get when you are done

| # | Capability | Provided by |
|---|---|---|
| 1 | DSH conversations are **auto-recorded every 5 turns**, and new sessions receive memory-usage guidance | ReMe's official DSH plugin |
| 2 | DSH sessions can retrieve long-term memory on demand | same (read-only tool `reme_search`) |
| 3 | DSH sessions can **read and write** memory (create/modify memory nodes) | DSH's built-in official MCP client + ReMe MCP |
| 4 | Codex (Windows and the VSCode extension inside a VM) can retrieve and write memory | ReMe MCP + Codex's MCP client |
| 5 | Codex submits each finished turn to ReMe **automatically** | Codex lifecycle hook + the capture script in Appendix A |
| 6 | Memory consolidation (daily→digest) runs only in the ReMe instance started by reme-helper | configuration (disable client-side schedules) |

---

## 2. Official support matrix (read first — it explains the design)

| Agent | ReMe's official integration | Ships automatic conversation capture? |
|---|---|---|
| DeepSeek Harness | official plugin `@agentscope-ai/reme-dsh-plugin` | ✅ yes, zero custom code |
| Claude Code | MCP + skill + **Stop hook** (`integrations/claude_code/reme/hooks/` in the ReMe repo) | ✅ yes |
| OpenClaw / Hermes / QwenPaw | official plugin / provider / Python API | ✅ yes |
| **Codex (incl. the VSCode extension in a VM)** | **a skill only** | ❌ **no** |

**Conclusion**: Codex is currently the only host where ReMe ships a skill but no automatic capture. ReMe's own
documentation says *"automatic capture requires explicitly wiring into the host lifecycle."* So Codex auto-capture
needs a host-side hook — **and it follows the same design ReMe itself published for Claude Code** (§3.4);
Codex lifecycle hooks are an official Codex feature (`features.hooks`, on by default).

**The one upstream issue we work around**: the old combined package on the package registry,
`@agentscope-ai/reme@0.1.2`, is incompatible with the DSH 0.1.2 line — it imports `settingsNamespace`
from `@deepseek-ai/dsh-settings`, which the runtime does not export (an upstream packaging inconsistency),
and the new dedicated package is not published yet. Hence the source-build path in §3.2, which is ReMe's own
documented development path.

---

## 3. Windows

### 3.1 Codex: connect the memory tools (MCP)

Append to `<CODEX_HOME>\config.toml`:

```toml
[mcp_servers.reme]
url = "http://127.0.0.1:<REME_PORT>/mcp"
```

Restart Codex and verify with `codex mcp list` → `reme … enabled`. Then have Codex search a known memory node
with ReMe's `search` tool; seeing `mcp_tool_call server=reme tool=search` and its result means it works.

**Note**: Codex gates MCP tool calls behind approvals. `approval_policy = "never"` **rejects** them
(`MCP tool call requires approval, but approval policy is never`). Interactive sessions prompt;
automation should pass `--approve-for-me`.

### 3.2 DSH: install the official plugin (source build)

```powershell
git clone --depth 1 https://github.com/agentscope-ai/ReMe <SRC_DIR>\ReMe-src
cd <SRC_DIR>\ReMe-src\integrations\dsh
npm ci --ignore-scripts
node node_modules\typescript\bin\tsc -p tsconfig.json
node scripts\build-client.mjs            # emits dist\client.js; needs permission to spawn esbuild
```

Install into the profile (**must live inside the profile directory**, or host peer packages will not resolve and
you will get `ERR_MODULE_NOT_FOUND: @deepseek-ai/dsh-llm`):

```powershell
$dst = '<DSH_HOME>\profiles\<DSH_PROFILE>\local-plugins\dsh-reme-plugin'
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item dist,cordis.patch.yml,package.json,README.md,README_ZH.md $dst -Recurse -Force
dsh plugin --profile <DSH_PROFILE> add $dst --ignore-scripts
```

Append to `<DSH_HOME>\profiles\<DSH_PROFILE>\cordis.patch.yml`:

```yaml
- id: reme-memory
  config:
    - id: reme-memory-runtime
      name: "@agentscope-ai/reme-dsh-plugin"
      config:
        endpoint: http://127.0.0.1:<REME_PORT>
        language: en            # guidance language; "zh" also supported
        timezone: Asia/Shanghai
        autoMemoryEnabled: true
        autoMemoryInterval: 5   # submit every N completed turns
        autoDreamEnabled: false # consolidation belongs to reme-helper's ReMe only
        rootAgentsOnly: true
```

### 3.3 DSH: attach the official MCP client to gain write access

The official plugin registers **read-only `reme_search` only**; writes happen in the background auto-memory job.
When a session needs to persist memory on demand, add one more block to the same `cordis.patch.yml`:

```yaml
- insert:
    - id: mcp-reme
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        transport: streamable-http
        serverName: reme
        url: http://127.0.0.1:<REME_PORT>/mcp
        toolCallTimeoutMs: 60000
        failOnStartupError: false      # ReMe being down never blocks DSH startup
        reconnect:
          enabled: true
```

Then **restart DSH Web** (and hard-refresh the browser with Ctrl+Shift+R).

**Verify**:
- a new session shows the `reme-memory` context injection (metadata `plugin=reme-memory`, `form=instructions`);
- the tool list contains both the plugin's `reme_search` and MCP names `mcp__reme__<tool>`
  (`search`/`read`/`write`/`edit`/…);
- after `autoMemoryInterval` turns, `<REME_WORKSPACE>\session\dialog\` gains `dsh-*.jsonl` and
  `daily\<date>\` gains a note.

**Context and cost impact (measured)**: every MCP tool is registered into every request. With ReMe's default
exposure (official all-open), 30 tools grow the per-request tool block from 53,535 to 65,201 characters
(+11,137 ≈ 2.8k tokens). Those tools sit in the stable prefix and are therefore billed at the **cache-read** rate
(for DeepSeek V4 Flash-class models: input $0.14/M, cache $0.0028/M — cache reads are about 1/50 of input),
so the money per request is negligible; rule of thumb: `delta ≈ 2,942 tokens × requests × cache price`.
The real cost of MCP is not money but **model attention** (more tools make tool selection less reliable) and the
capability surface: all-open also hands the agent `delete`/`move`/`reindex`/`auto_dream`. To narrow it, use
reme-helper's "MCP tool exposure" switches; narrowing does not affect background auto-memory or scheduled consolidation.

### 3.4 Codex: automatic capture (the key step)

**Reference implementation**: ReMe's official Claude Code hook — `integrations/claude_code/reme/hooks/hooks.json`
plus `hooks/auto_memory.py`. That hook binds the **`Stop` event**, reads `session_id` from stdin,
**detaches immediately (double-fork) so stopping is never blocked**, and lets the detached process record the
session into ReMe.

Our Codex version keeps the identical design with one necessary difference: ReMe has no transcript resolver for
Codex (it ships `auto_memory_cc` for Claude Code, but no `auto_memory_codex`), so the capture script parses
Codex's own rollout files and hands the messages to the **generic** `auto_memory` job.

**Step 1** — write **Appendix A**'s capture script verbatim to `<CODEX_HOME>\reme-bridge\capture.mjs`
(reme-helper's "Copy the setup guide" appends Appendix A for you; if you only have the files, it is
`capture.mjs` one level up (in `doc/`)).

It does five things: read the rollout → filter injected boilerplate and internal threads → build ReMe's message
shape → keep a per-rollout high-water mark for incremental, idempotent submission → `POST /auto_memory`.
Two constraints are non-negotiable (both are documented Codex hook behaviours; violating them fails **silently**):

- The hook itself must **return in milliseconds**: the `Stop` event requires valid JSON on stdout at exit 0, and
  background `async` hooks are cancelled when the session ends. So the hook only does "parse `transcript_path`
  from the event → spawn a detached worker → print `{}` → exit".
- Concurrent sessions must not lose records: use a queue file plus lock retry and requeue-on-failure.

**Step 2** — write the endpoint config `<CODEX_HOME>\reme-bridge\config.json`:

```json
{ "endpoint": "http://127.0.0.1:<REME_PORT>" }
```

**Step 3** — create `<CODEX_HOME>\hooks.json` (a **new file**; do not touch `notify` in `config.toml`):

```jsonc
{
  "hooks": {
    "Stop": [
      { "hooks": [ {
        "type": "command",
        "command": "node \"$HOME/.codex/reme-bridge/capture.mjs\" --hook",
        "commandWindows": "node \"<CODEX_HOME>\\reme-bridge\\capture.mjs\" --hook",
        "timeout": 30,
        "statusMessage": "ReMe: capturing this turn"
      } ] }
    ]
  }
}
```

**Step 4 (manual, once)** — run `/hooks` in Codex, review and **trust** the hook.
Untrusted hooks are **silently skipped** (no error, nothing in the log).

**Verify**: after one chat turn, `<CODEX_HOME>\reme-bridge\capture.log` shows
`hook event=Stop … queued+drain` and `worker submitted session=codex-…`; the ReMe workspace gains
`session\dialog\codex-*.jsonl`. (ReMe decides value itself: trivial chatter keeps the transcript but creates no
note — that is expected.)

**Boundary**: do not let the agent record manually *and* let the hook capture, or the same conversation is written
twice. Write this into `<CODEX_HOME>\AGENTS.md`: **never call `auto_memory` / `auto_dream` manually**.

### 3.5 Consolidation ownership (exactly one)

`POST /app_config` should list exactly **one** `dream_cron` job (e.g. `0 23 * * *`, written by reme-helper);
`auto_dream`/`auto_memory` are on-demand jobs, not schedulers.
Client side: DSH plugin `autoDreamEnabled: false`; no scheduled tasks for Codex; never call `auto_dream` manually.

---

## 4. VM (Ubuntu): tunnel first, then the same integration

### 4.1 Why a tunnel is required

ReMe listens on loopback only, so the VM cannot reach Windows' `<REME_PORT>` directly.
reme-helper creates an **SSH reverse tunnel** from Windows to the VM:
the VM's `127.0.0.1:<REMOTE_PORT>` → Windows' `127.0.0.1:<REME_PORT>`.
(Add targets in reme-helper's tray menu "VM targets" and let them start/stop with ReMe.)

Verify inside the VM:

```bash
ss -ltn | grep <REMOTE_PORT>
python3 -c "import json,urllib.request;r=urllib.request.Request('http://127.0.0.1:<REMOTE_PORT>/version',data=b'{}',headers={'Content-Type':'application/json'});print(json.loads(urllib.request.urlopen(r,timeout=20).read())['answer'])"
```

### 4.2 VM configuration (same as Windows, endpoint = tunnel port)

1. Append to `<VM_CODEX_HOME>/config.toml`:

```toml
[mcp_servers.reme]
url = "http://127.0.0.1:<REMOTE_PORT>/mcp"
```

2. Copy the capture script to `<VM_CODEX_HOME>/reme-bridge/capture.mjs` (same file as Windows; runs on Linux node 18+).
3. Write `<VM_CODEX_HOME>/reme-bridge/config.json`:

```json
{ "endpoint": "http://127.0.0.1:<REMOTE_PORT>" }
```

4. Copy `hooks.json` to `<VM_CODEX_HOME>/hooks.json` (one file serves both: `command` uses `$HOME` for Linux,
   `commandWindows` for Windows).
5. Run `/hooks` inside the VM's Codex and trust it.

**Verify** (the VM's codex is usually not on PATH; the VSCode extension bundles it, e.g. `/usr/lib/chatgpt/resources/codex`):

```bash
CX=/usr/lib/chatgpt/resources/codex
$CX mcp list | grep reme
$CX doctor | grep -E 'parse|MCP servers'
$CX exec --skip-git-repo-check --approve-for-me "say something" < /dev/null
tail -5 <VM_CODEX_HOME>/reme-bridge/capture.log
```

`< /dev/null` is mandatory: in non-interactive runs stdin is a pipe that never closes and `codex exec` blocks on it.

### 4.3 What must NOT exist on the VM

- A `notify` pointing at a Windows path (e.g. `C:\...\codex-computer-use.exe`): it can never work on Linux, yet
  `doctor` reports no error. Delete it or replace it with a VM-local command.
- Any client-side consolidation schedule: `crontab -l`, `systemctl --user list-timers` must not mention ReMe.

---

## 5. Troubleshooting (ordered by "fails silently")

| Symptom | Cause | Fix |
|---|---|---|
| `worker error … fetch failed` | Wrong endpoint (on the VM, ReMe is on the tunnel port, not `<REME_PORT>`) | Fix `reme-bridge/config.json`, then `node capture.mjs --drain` |
| `capture.log` stays empty | Hook not trusted | Run `/hooks` in Codex and trust it |
| `validation error for Msg` (HTTP 200 but `success:false`) | Messages missing the `name` field | Use Appendix A's script; do not hand-roll the message shape |
| Lost records / `worker skipped` | Older implementations dropped work under lock contention | Use Appendix A's script (queue + lock retry) and `--drain` to catch up |
| The same conversation yields two notes | Agent recorded manually *and* the hook captured it | Write "do not call auto_memory manually" into `AGENTS.md` |
| Approval JSON or environment boilerplate in memory | Internal threads / injected text not filtered | Use Appendix A's script (filters by source and known prefixes) |
| Plugin fails with `settingsNamespace` | The old combined package from the registry was installed | Follow §3.2 (source build) |
| `ERR_MODULE_NOT_FOUND: @deepseek-ai/dsh-llm` | Plugin is not inside the profile directory | Move it to `<DSH_HOME>\profiles\<DSH_PROFILE>\local-plugins\` |
| `MCP tool call requires approval` | `approval_policy = "never"` | Approve interactively, or run with `--approve-for-me` |
| MCP tools never appear in DSH | The MCP client could not connect (`failOnStartupError: false` does not block startup) | Confirm ReMe is running and the `url` is correct; restart DSH Web |

## 6. Acceptance checklist

1. `POST /health_check` → `healthy: true`, all four components `is_started: true`
2. A new DSH session shows the `reme-memory` injection; the tool list has `reme_search` and `mcp__reme__*`
3. After `autoMemoryInterval` turns, `<REME_WORKSPACE>\session\dialog\dsh-*.jsonl` exists
4. `codex mcp list` → `reme enabled`
5. One Codex turn → `capture.log` has `worker submitted`; the ReMe workspace gains `codex-*.jsonl`
6. VM: `ss -ltn | grep <REMOTE_PORT>` listens; `$CX mcp list` shows reme enabled; a VM session is retrievable from Windows
7. `POST /app_config` → exactly one `dream_cron`; no client-side schedules

## 7. End-to-end runbook (fresh machine, in this order)

| Step | Action | Ref |
|---|---|---|
| 1 | reme-helper: install and start ReMe (full mode + LLM + embedding); confirm `/health_check`; note port and workspace | §0 |
| 2 | DSH official plugin: source-build → copy into the profile's `local-plugins` → `dsh plugin add` → add the `reme-memory` block to `cordis.patch.yml` | §3.2 |
| 3 | DSH MCP write access: insert the `mcp-reme` block into the same patch file | §3.3 |
| 4 | **Restart DSH Web** and hard-refresh the browser | §3.3 |
| 5 | Codex memory tools: add `[mcp_servers.reme]` to `config.toml` | §3.1 |
| 6 | Codex automatic capture: write `capture.mjs` → write `reme-bridge/config.json` → create `hooks.json` → run `/hooks` in Codex to trust it | §3.4 |
| 7 | VM: enable the tunnel → configure the VM's `config.toml` / `hooks.json` / `reme-bridge/config.json` (endpoint = `<REMOTE_PORT>`) → run `/hooks` in the VM's Codex | §4 |
| 8 | Walk the acceptance checklist | §6 |

**Two hard ordering dependencies**: step 2 must finish before the step 4 restart, and the `/hooks` trust in
steps 6/7 is a manual action — until it is done, the hook is skipped silently.

## 8. Rollback

| To disable | Do |
|---|---|
| Codex automatic capture | delete `<CODEX_HOME>\hooks.json` (Windows and VM) |
| DSH memory plugin | `dsh plugin --profile <DSH_PROFILE> remove @agentscope-ai/reme-dsh-plugin`, then restart |
| DSH MCP write access | delete the `- insert: mcp-reme` block from `cordis.patch.yml`, then restart |
| Codex memory tools | delete `[mcp_servers.reme]` from `config.toml` |

---

## Appendix A: the Codex capture script (`capture.mjs`)

> reme-helper's "Copy the setup guide" appends the full script here, so one paste gives an AI both the instructions
> and the script. If you are reading this from the filesystem, the script is `capture.mjs` in the `doc/` folder
> directory. Target path: `<CODEX_HOME>\reme-bridge\capture.mjs` (**write it verbatim; do not change the message shape**).
