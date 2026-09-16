# Connect your agents to ReMe (an integration spec for an AI agent)

> **How to use this**: in reme-helper click **Copy the setup guide**, then paste the **whole thing** into an AI agent that
> can read and write files on this machine. It will **probe the machine first and report which ends apply**; once you
> confirm, it wires each end up and verifies each one. If you only have Codex, only Codex gets done; if there is no
> second Linux machine, the two cross-machine ends are skipped — **do not install things just to complete the list**.
> `<...>` marks a placeholder: replace it with this machine's real value (see the table below; the ReMe port and
> workspace are already filled in when the guide is copied).
> Sentences marked **invariant** come from failures we actually hit — follow them. Everything else may be adapted to
> local conditions, but do not invent a different design.

This document is about one thing only: connecting clients to ReMe. It is not about any particular skill or tool.

---

## 0. Variables

| Placeholder | Meaning | Where the value comes from |
|---|---|---|
| `<REME_PORT>` | ReMe's HTTP port on the machine that runs it | reme-helper settings, default `2333` |
| `<REME_WORKSPACE>` | ReMe's memory directory (`daily/ digest/ session/`) | the `workspace` folder under the ReMe directory configured in reme-helper |
| `<CODEX_HOME>` | Codex home | `%USERPROFILE%\.codex` on Windows, `~/.codex` on Linux |
| `<CLAUDE_HOME>` | Claude Code home | `%USERPROFILE%\.claude` on Windows, `~/.claude` on Linux |
| `<DSH_HOME>` `<DSH_PROFILE>` | DSH home and profile (only if DSH is installed) | `%USERPROFILE%\.dsh` on Windows; `web` for the Web UI |
| `<SRC_DIR>` | Scratch source directory (for the DSH source build) | your choice |
| `<VM_HOST>` `<VM_USER>` | Address and user of the second Linux machine (skip if none) | your environment |
| `<REMOTE_PORT>` | Tunnel port on the Linux side | reme-helper's VM target settings, e.g. `22333` |

**Prerequisites depend on what you want — not all of them are required**:

| Capability you want | What it needs |
|---|---|
| Recall (keyword / file-level search) | ReMe running; **no model needed** |
| Semantic recall (paraphrase, cross-language) | additionally needs embeddings; without them search degrades to keywords and misses |
| Automatic recording every turn | **needs an LLM** — distillation is the model's job; without an LLM, do not wire up capture |
| Memory consolidation (daily → digest) | needs an LLM, and only the ReMe instance reme-helper started does it |

In every case, confirm `POST http://127.0.0.1:<REME_PORT>/health_check` returns `healthy: true` first.
ReMe **listens on loopback only and uses no API key** — which is why a second machine must go through a tunnel, and why
every client shares one workspace.

---

## 1. Step one: probe, do not start editing

Find out the following, **show the table to the user and wait for confirmation** before touching any file:

1. Is ReMe running? Does the health check pass? What are the port and the workspace?
2. Which hosts are installed on this machine, and where: Codex, Claude Code, DSH (there may be none).
3. Is there a second Linux machine? Is a VM target configured in reme-helper? Does `ss -ltn` on that machine show the
   tunnel port listening?

Report in this shape:

| End | Applies? | Path it will take (see §3) | Manual action needed from the user |
|---|---|---|---|

**Only continue once the user confirms.** What applies is decided by the probe, not by this document's list.

---

## 2. What each end must do

Two capabilities per end:

- **Recall**: the session can search long-term memory — over MCP.
- **Automatic recording**: every finished turn hands its **new** content back to ReMe, with no manual step.

**Invariants** (every end, no improvising):

1. **Recording goes over REST, not MCP**: `POST <endpoint>/auto_memory` — one request, no handshake. MCP serves recall only.
2. **The message shape is fixed**: `{ id, name, role, content:[{type:"text",text}], created_at }`, where `name` must equal
   `role`. `session_id` is not marked required in the tool schema but **is required at runtime** (`Error: session_id is
   required` otherwise).
3. **The hook is an anchor only**: resolve the path → spawn a detached process → return immediately. The detached process
   does the submission. Hooks still running when the session ends get cancelled — submitting inline loses the record.
4. **Idempotency comes from deterministic ids**: `"<prefix>-<short session hash>-<index>"`; resending a batch is deduped
   server-side. This is what makes retrying safe.
5. **Memory consolidation happens in exactly one place**: only the ReMe that reme-helper started. Clients must not run
   their own consolidation schedule, and must not call `auto_dream` by hand.
6. **The endpoint is the port this side actually listens on**: local port when co-located, tunnel port when remote.
   Getting it wrong shows up as `fetch failed` / `Connection refused`.
7. **Proof is an artifact, not a log line**: `ok` in a hook log only means the call returned — it also returns `ok` for a
   session id that does not exist. Real evidence is in §6.

---

## 3. Decision table: which path each end takes

| End | Co-located with ReMe | Remote from ReMe |
|---|---|---|
| **Codex** | capture bridge (§4) | **the same capture bridge**, endpoint changed |
| **Claude Code** | official plugin | **must switch to the capture bridge** |
| **DSH** (only if installed) | official plugin | official plugin, endpoint changed |

Facts you must know, or you will get this wrong:

- **The official Claude Code setup assumes Claude Code and ReMe are on the same machine**: its hook hands ReMe only a
  `session_id`, and ReMe reads the transcript off its own disk (`~/.claude/projects/*/<session_id>.jsonl`). Across
  machines it reads nothing and returns "no messages" while the hook log still looks fine — **completely silent**.
- **The official Claude Code setup is only asynchronous on Linux/macOS**: it detaches with `fork()`. Windows has no
  `fork`, so it **falls back to running inline**, and the 30-second hook timeout kills the recording. So **the official
  version does not work on Windows either**:
  - Want one implementation across all ends and the same semantics as the VM → use the capture bridge (Appendix B).
  - Want less code and accept two implementations → patch the official hook to detach properly on Windows (relaunch
    itself with `pythonw.exe` + `DETACHED_PROCESS` and return at once; put the absolute `pythonw` path in the hook
    command so it does not depend on `PATH`).
- **Codex has no official automatic capture**: officially you get a skill / MCP only ("automatic capture requires
  integrating with the host lifecycle" — their words). The capture bridge is the glue we add; the mechanism itself
  (host lifecycle hooks) is an official Codex feature, not a hack.

---

## 4. The generic capture bridge (the only part that needs code)

In one sentence: **the client reads its own transcript locally → computes what is new → inlines it as ReMe messages →
POSTs it; failures are queued and retried next round.**

Five elements; missing any one of them fails silently:

1. **Read locally**: parse the file the host itself writes (Codex rollouts, Claude Code transcripts). Never make the
   server read it.
2. **Watermark**: track submitted count per **absolute transcript path**; send only what is new, **oldest first, at most N
   per round**, leaving the rest for the next round; advance only after a successful submit, and only by the number
   actually sent. Re-read state from disk and take `max` before writing back — **the watermark only moves forward**.
   Otherwise a manual submit and a hook worker read the same old value and write back in turn; the later write wins, the
   watermark goes backwards, and already-recorded content is resubmitted over and over.
3. **Deterministic ids**: `"<prefix>-<short session hash>-<index>"`, where the index is the message's position in the
   watermark. Resending is idempotent for free.
4. **Detached hook + file lock**: the hook returns in milliseconds; a detached process submits; the **lock must cover every
   submission entry point** (hook worker, single-session manual submit, full backfill) or two paths will fight over the
   watermark. Reclaim stale locks by age.
5. **Queue on failure**: write the task back to a queue file and retry next round — that is how "the tunnel dropped, it
   caught up by itself once reconnected" works.

**Message rendering rules** (shared by all ends):

| Input | Handling |
|---|---|
| User/assistant text | keep; join multiple blocks with newlines |
| Tool call | `[tool <name>(<input, truncated to 200 chars>)]` |
| Tool result | `[tool_result <excerpt, truncated to 200 chars>]` |
| Private reasoning (thinking) | drop |
| Subagent / internal threads (`isSidechain`, Codex internal threads) | drop |
| Turns that contain nothing but injected boilerplate (`<system-reminder>`, `<local-command-*>`, `<environment_context>`) | drop |
| Timestamp | take the original line's timestamp into `created_at` |

**Porting to a host means changing four things**: transcript directory, file-matching rule, parser, noise prefixes.
Everything else (endpoint resolution, watermark, lock, queue, detached process, REST submission) is shared:

| End | Transcript location | Matching | Extra filtering |
|---|---|---|---|
| Codex | `<CODEX_HOME>/sessions/<year>/<month>/<day>/rollout-*.jsonl` | names start with `rollout-`; session id from the `session_meta` line | internal threads, approval/environment boilerplate |
| Claude Code | `<CLAUDE_HOME>/projects/<project>/<session-id>.jsonl` | one JSON object per line; session id is the file name | `isSidechain`, injected templates, thinking |

**Endpoint resolution order** (same everywhere): `REME_URL` env var > **the host's own config file** > default local
port. On the Codex side that is `config.json` next to the capture script; on the Claude Code side it is the plugin's
`.mcp.json` (strip the `/mcp` suffix).
**Note**: the Claude Code side must prefer the plugin's `.mcp.json`, not the MCP entry registered with the client — the
two can disagree. We hit exactly that: the hook kept dialling the default port while `curl` on the tunnel port worked.

---

## 5. Per-end wiring

| End | Where the hook goes | Where the endpoint goes | Manual action |
|---|---|---|---|
| Codex (co-located) | `Stop` in `<CODEX_HOME>/hooks.json` | `<CODEX_HOME>/reme-bridge/config.json` | run `/hooks` in Codex once to **review and trust** it (untrusted hooks are skipped silently) |
| Codex (remote) | the same file (**one file for both**: `command` uses `$HOME` for Linux, `commandWindows` holds the absolute path) | same file, value becomes `http://127.0.0.1:<REMOTE_PORT>` | same, once per machine |
| Claude Code (remote) | `Stop` in `<CLAUDE_HOME>/settings.json`, pointing at the capture bridge | the plugin's `.mcp.json` (**rewritten to the tunnel port**) **and** the `reme` MCP entry in `~/.claude.json` — **both must match** | none (user-level settings hooks run directly) |
| Claude Code (co-located, official) | same, pointing at the official hook (needs the async patch on Windows, see §3) | plugin `.mcp.json` = local port | none |
| DSH | managed by the official plugin (no hook) | `endpoint` in the plugin config | restart DSH Web and hard-refresh the browser |

MCP registration for recall:

```toml
# <CODEX_HOME>/config.toml
[mcp_servers.reme]
url = "http://127.0.0.1:<REME_PORT>/mcp"   # on a remote machine, use the tunnel port
```

On the Claude Code side, write `mcpServers.reme` in `~/.claude.json`:
`{ "type": "http", "url": "http://127.0.0.1:<port>/mcp" }`.

Other fixed actions:

- **Do not let the agent record by hand while the hook also captures**, or the same conversation lands twice. State it in
  `<CODEX_HOME>/AGENTS.md`: **do not call `auto_memory` / `auto_dream` manually**.
- **Do not add client-side schedules**: no ReMe entry in `crontab -l`, `systemctl --user list-timers`, or Windows Task
  Scheduler.
- On a remote machine, a `notify` pointing at the other machine's path (say a Windows `C:\...` path) never fires on Linux
  and `doctor` does not complain — remove it or replace it with a local command.
- Codex gates MCP tool calls behind approval: `approval_policy = "never"` **rejects them outright**
  (`MCP tool call requires approval`). Interactive sessions prompt; for automation pass `--approve-for-me`.

---

## 6. Verification: look at artifacts, not logs

Check every end; all of it must be real evidence:

1. `POST /health_check` → `healthy: true`.
2. After one turn on each end, `<REME_WORKSPACE>/session/` gains that end's archive:
   Codex and this document's Claude Code path land in `dialog/` (`codex-*.jsonl` or `<session-id>.jsonl`);
   a Claude Code install on the official plugin lands in `claude_code/<session-id>.jsonl` (raw entries preserved).
3. A note appears under `<REME_WORKSPACE>/daily/<the day the conversation happened>/` — the date is when the
   conversation happened, not today. ReMe decides whether a conversation is worth a note: small talk leaves an archive
   and no note, which is normal.
4. For a remote end: content from the other machine is searchable in the memory on the machine running ReMe.
5. Idempotency: submit the same turn again → it reports "nothing new", the watermark does not move, no duplicate note.
6. Reconciliation: `POST /app_config` shows exactly one `dream_cron` job; no client-side schedules.

**Not evidence**: `ok` in a hook log, `worker submitted`, or HTTP 200 with `success:false`.

Command-line self-check (Codex side; on a VM the codex binary is usually not on `PATH` — the VSCode extension ships one,
e.g. `/usr/lib/chatgpt/resources/codex`):

```bash
CX=<path to the codex binary>
$CX mcp list | grep reme
$CX exec --skip-git-repo-check --approve-for-me "say something" < /dev/null
tail -5 <CODEX_HOME>/reme-bridge/capture.log
```

`< /dev/null` is not optional: in non-interactive mode stdin is a pipe that never closes, and `codex exec` waits on it
forever.

---

## 7. Failure modes that fail silently (most dangerous first)

| Symptom | Cause | Fix |
|---|---|---|
| Hook logs look fine, zero artifacts | the server cannot read the transcript (remote), or the hook was cancelled because it was not detached | use the capture bridge (§4) |
| `fetch failed` / `Connection refused` | wrong endpoint (remote machines need the tunnel port, not the default local port) | fix the endpoint, then submit once by hand |
| The hook never fires | Codex hook not trusted | run `/hooks` in Codex and trust it |
| HTTP 200 but `success:false`, `validation error for Msg` | message lacks `name` (must equal `role`) | follow the message shape in §2 |
| The same conversation produces two notes | manual recording plus hook capture | forbid manual calls in `AGENTS.md` |
| Approval JSON or environment boilerplate shows up in memory | internal threads and injected text not filtered | follow the rendering rules in §4 |
| Already-recorded content is resubmitted | watermark pushed backwards by a concurrent writer | forward-only watermark + lock on every submission path |
| The official Claude Code hook times out on Windows | no `fork`, runs inline, killed by the 30-second hook timeout | patch it to detach, or use the capture bridge |
| DSH plugin reports `settingsNamespace` | an old combined package from the registry is installed | source build, §9 |
| DSH plugin reports `ERR_MODULE_NOT_FOUND: @deepseek-ai/dsh-llm` | plugin not inside the profile directory | move it under `<DSH_HOME>\profiles\<DSH_PROFILE>\local-plugins\` |
| No `mcp__reme__*` tools in DSH | the MCP client did not connect (`failOnStartupError: false` keeps startup alive) | check ReMe is running and the `url` is right; restart DSH Web |

---

## 8. Rollback

| To stop | Do |
|---|---|
| Codex automatic recording | delete `<CODEX_HOME>/hooks.json` (one per machine) |
| Claude Code automatic recording | delete the matching `Stop` entry from `<CLAUDE_HOME>/settings.json` |
| Claude Code memory tools | delete the `reme` MCP entry |
| Codex memory tools | delete `[mcp_servers.reme]` from `config.toml` |
| DSH memory plugin | `dsh plugin --profile <DSH_PROFILE> remove @agentscope-ai/reme-dsh-plugin`, then restart |

Back up every file you modify as `.bak-<timestamp>` first.

---

## 9. Optional end: DSH (only if installed)

**Windows install (source build)**: the old combined package on the registry (`@agentscope-ai/reme@0.1.2`) is
incompatible with current DSH builds (it imports `settingsNamespace` from `@deepseek-ai/dsh-settings`, which the runtime
does not export — an upstream packaging inconsistency), and the new dedicated package has not been published to the
registry yet. So build from source, which is the officially recommended development path:

```powershell
git clone --depth 1 https://github.com/agentscope-ai/ReMe <SRC_DIR>\ReMe-src
cd <SRC_DIR>\ReMe-src\integrations\dsh
npm ci --ignore-scripts
node node_modules\typescript\bin\tsc -p tsconfig.json
node scripts\build-client.mjs            # produces dist\client.js; must be allowed to spawn esbuild
```

Install the build output under the profile (**it must live inside the profile directory**, or host peer resolution fails
with `ERR_MODULE_NOT_FOUND`):

```powershell
$dst = '<DSH_HOME>\profiles\<DSH_PROFILE>\local-plugins\dsh-reme-plugin'
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item dist,cordis.patch.yml,package.json,README.md,README_ZH.md $dst -Recurse -Force
dsh plugin --profile <DSH_PROFILE> add $dst --ignore-scripts
```

Append the `reme-memory` block to `<DSH_HOME>\profiles\<DSH_PROFILE>\cordis.patch.yml`:

```yaml
- id: reme-memory
  config:
    - id: reme-memory-runtime
      name: "@agentscope-ai/reme-dsh-plugin"
      config:
        endpoint: http://127.0.0.1:<REME_PORT>   # on a remote machine, the tunnel port
        language: en            # language of the memory instructions
        timezone: Asia/Shanghai
        autoMemoryEnabled: true
        autoMemoryInterval: 5   # turns per submission
        autoDreamEnabled: false # consolidation belongs to the reme-helper instance only
        rootAgentsOnly: true
```

The official plugin **registers the read-only `reme_search` tool only**. To write memory from inside a session, insert one
more block in the same `cordis.patch.yml`:

```yaml
- insert:
    - id: mcp-reme
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        transport: streamable-http
        serverName: reme
        url: http://127.0.0.1:<REME_PORT>/mcp
        toolCallTimeoutMs: 60000
        failOnStartupError: false      # ReMe being down must not block DSH startup
        reconnect:
          enabled: true
```

Then **restart DSH Web** (and hard-refresh the browser). Verify: new sessions carry a `reme-memory` context block; the
tool list shows both `reme_search` and `mcp__reme__<tool>`; after `autoMemoryInterval` turns, `session/dialog/` gains a
`dsh-*.jsonl`.

**Cost and capability surface**: every MCP tool is registered in every request. Those tools sit in a stable prefix and
are billed at cache-read price, so **the money per request is negligible**. The real cost is model attention (more tools
means more mis-selection) and capability surface (with everything exposed, `delete`/`move`/`reindex`/`auto_dream` are
handed to the agent too). To narrow it, use reme-helper's MCP tool exposure switches — narrowing does not affect
background auto-memory or scheduled consolidation.

---

## Appendices: the capture scripts

reme-helper appends both scripts in full **when the guide is copied**; they are not duplicated in this file, so the two
can never drift apart.

### Appendix A: Codex capture script (`capture.mjs`)

Install at `<CODEX_HOME>/reme-bridge/capture.mjs` (**write it verbatim; do not change the message shape**).
Co-located and remote use the **same script** — only the endpoint in `config.json` differs.

<!--APPENDIX A-->

### Appendix B: Claude Code capture script (`capture_cc.mjs`)

Install at `<CLAUDE_HOME>/plugins/reme-claude/hooks/capture_cc.mjs` (same idea when a co-located install switches to the
bridge). Runtime state (watermark / lock / queue / log) lives in the `bridge/` directory **next to the script**, fully
isolated from the Codex side. Same skeleton as Appendix A with the four host-specific pieces from §4 swapped.

<!--APPENDIX B-->
