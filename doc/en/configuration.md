# Configuration reference

English | [简体中文](../zh/configuration.md)

User-facing entry point: [README](../../README.md) · version history: [CHANGELOG](../../CHANGELOG.md) ·
connecting Codex / DSH to ReMe: [setup guide](setup.md).
This document is the **technical reference** — fields, variable names, constraints, and validation rules. The
in-app guide ("Where are the files") covers the same ground in operational terms; the two are kept in sync.

> `H:\Tools\ReMe` appears below only as the **default example**. On first run you can choose another folder in the
> settings window, or click **Scan** to detect it.

## Modes

| Mode | Config file | Purpose |
|---|---|---|
| Basic | `<ReMe>\config\app.yaml` | No model calls; keeps Markdown read/write, BM25, wikilinks, Studio, MCP, index maintenance |
| Full | `<ReMe>\config\app-full.yaml` | Extends ReMe's official default with everything on; needs LLM credentials; includes Auto Memory, Auto Resource, Auto Dream, internal Chat |
| Custom | `<ReMe>\config\app-custom.yaml` | Pick each item: auto memory, Claude Code entry, resource processing, dream, proactive, chat, embedding, FAISS, Studio, MCP |

The first two are **fixed presets** (two files this tool does not generate). Rules in the settings window:

- **The mode is derived from the config content, not declared**: as soon as the draft matches a preset exactly, the
  mode switches to that preset (with a toast), so the label always reflects reality.
- **Switching modes only swaps the capability set; your data is kept**: addresses, model names, keys, dimensions and
  tuned parameters travel with you (they are account-level settings, valid in any mode), so going from Basic to Full
  or Custom never clears what you entered.
- **Mode identity depends only on capabilities**: editing a capability while on a fixed preset switches you to
  **Custom**, and only that one item is applied (the baseline is your starting point), with a toast.
- **Shared settings never change the mode**: addresses, models, keys, token budget, reasoning effort, embedding
  dimensions, consolidation parameters, and the MCP allowlist hold in every mode.
- Clicking the current mode does nothing.
- The status bar shows the **baseline** (Basic / Full / saved config); "restore baseline" returns to that point.

While ReMe is not running, switching modes only saves the choice — it does not start anything. While ReMe is running
it asks for confirmation first, then validates the new config, stops the old service and starts the new one; if the
new service fails, it tries to restore the previous mode.

## Language and theme

- Switched from the console's top-right corner or the tray; the dark-mode choice is remembered (dark uses the `clam`
  ttk theme because the native Windows theme ignores colours; light and dark share one ttk engine so switching does
  not shift the layout).
- The translation table lives in `src/i18n.py`, one entry per line; untranslated text falls back to Chinese.
- Window titles and tray hints follow the language (in English they read `ReMe Helper <version> · Console`, where the version comes from `VERSION` in `src/main.py`). `APP_ID` never changes, so the
  tray window class and the autostart registry entry are language-independent.

## Tray menu

- Read-only status: ReMe state, current mode, tunnel count.
- **ReMe console…** (the default item — double-clicking the tray icon opens it); mode switching and fine-tuning live
  there, and the tray no longer offers clickable mode items.
- Start / stop / restart ReMe.
- Open ReMe Studio, the workspace, and **"Where are the files"** — a small window listing the ReMe folder, workspace,
  current config, official default config, `.env` (credentials), log folder, console guide, and the setup guide, each
  row with "open" or "copy path".
- Start / stop all VM tunnels; a "VM targets" submenu adds, edits, deletes, enables and disables targets, and
  re-scans local SSH keys.
- Autostart, start ReMe with the tool, start tunnels with ReMe.

## LLM, Embedding, and the memory pipeline

The settings window is organised in sections and written to disk together on save.

**LLM and model**

- Base URL and model (type it, or click "refresh models" to pull candidates from the endpoint's `/v1/models`).
- API key uses a masked input; leaving it empty means "do not change the existing value".
- `max_tokens`, `thinking_enable`, and **reasoning effort** (`reasoning_effort`, six levels like Codex) are injected
  into the generated config (`components.as_llm.default.parameters`).
- "Test connection" sends a **real request that demands JSON** and verifies two things: (1) the chat endpoint works;
  (2) it **can return structured JSON** as required (auto_memory / auto_dream depend on this). If the connection works
  but `content` is empty (everything landed in `reasoning_content`), it says so plainly — a thinking model that fills
  the budget makes auto_dream write empty content. Non-JSON output also fails, with advice.
- **Credentials are checked before any request**: if the base URL, model, or API key is missing, no request is sent —
  the dialog names the missing variable (for example, "LLM_API_KEY is missing, test not started"), so an unfilled key
  is never mistaken for a broken endpoint.
- Field values are collected into the draft **when the field loses focus**, so clicking other options afterwards does
  not overwrite what you typed.

**Embedding (semantic retrieval)**

- Its own address / model / API key / dimensions; model and dimensions go into the generated config
  (`components.as_embedding`), credentials into `EMBEDDING_*` in `.env`.
- "Test embedding" does three real checks: (1) the endpoint actually serves embeddings (not a 404); (2) the returned
  dimensions match the configuration; (3) **semantic ordering is sane** — with the samples "猫喜欢吃鱼 / 小猫爱吃鱼 /
  今天股市大涨", the similar pair must score **higher** than the unrelated one. On success the message reads like
  "similar 0.83 > unrelated 0.19, dimensions 1024". Endpoints that reject the `dimensions` parameter are retried and
  noted.
- Saving is allowed even if the test has not passed, but a confirmation is shown and it warns that the feature will not
  take effect. Actually enabling it needs: test passes → rebuild the index (`scope=embedding`) → search results show
  vector hits.

**Memory pipeline (cost and quality gates)**

- Scan days, max units per run, and the consolidation schedule are **dropdown levels** (1/2/3/7 days, 3/5/10 units,
  23:00 / 03:00 / 12:00 daily plus custom cron) so hand-written syntax errors cannot happen.
- Live impact preview: next consolidation time, scan scope (daily file counts and characters measured from the real
  workspace), call ceiling (one extraction plus one consolidation per unit), and output location.
- "Consolidate now" calls ReMe's `auto_dream` in the background (it calls the model and modifies the workspace);
  "rebuild index" calls `reindex`, and without embedding the scope offers only `all` / `bm25`.
- The **"Enable automatic memory and consolidation"** switch at the top of the pipeline section toggles Auto Memory and
  Auto Dream together (showing "partially enabled" when they disagree) and needs a working LLM.
- Both buttons are dependency-gated: **consolidate now** needs Auto Dream on + LLM ready + service running (it spends
  tokens); **rebuild index** needs only a running service.

**MCP tool exposure**

- Ticking "custom allowlist" writes `service.jobs`; `write` / `edit` decide whether an agent can write memory
  precisely (skill-style rules need it), and `auto_memory` / `auto_dream` let an agent trigger consolidation.
  Otherwise ReMe's default applies (every non-streaming job).
- The list is gated per item against the current mode and enabled capabilities: a job that does not exist in this
  config is disabled, because writing it into `service.jobs` makes ReMe fail at startup.

**Save behaviour**

- **Validate and save** no longer closes the window: after a successful save the baseline, status bar, and
  "unsaved changes" counter refresh immediately, and a toast plus dialog report the result (including "the service was
  restarted with the new config"). You can keep adjusting.
- A failed save rolls back `config.json`, `.env`, and the running service mode, and keeps the window open so you can
  fix the problem in place.

## Credentials and environment variables

- Full mode and any custom mode with LLM features needs `LLM_API_KEY` and `LLM_BASE_URL` in `<ReMe>\.env` (or the
  current environment); a local Ollama backend is the exception. The settings window can create a local `.env`
  template.
- Embedding uses the `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` family; saving only updates `LLM_*` / `EMBEDDING_*`
  keys and leaves other lines in `.env` untouched.
- When `.env` and the saved values disagree, **`.env` wins** (that is what ReMe actually reads): the UI corrects
  itself from `.env`, tells you which items it corrected, and writes back to `config.json` on save.
- The tool never displays secret values, only whether a non-empty value exists. "Export config" redacts secret fields
  (`api_key` / `token` and friends show as `***`).

## Finding the ReMe folder

- The default is `<drive>\Tools\ReMe`; you can pick another, or click **Scan** to auto-detect (common local folders,
  `REME_ROOT`, `Tools\ReMe` on each drive, `~/ReMe`, `%LOCALAPPDATA%\Programs\ReMe`, …). The test is
  "`venv\Scripts\python.exe` exists and the same folder has `reme.exe` or the `reme` package".
- When the folder is unusable, section 1 shows an orange hint: if candidates were found it says to click Scan; if not,
  it lists the install steps and offers **Copy install prompt** (a ready-made instruction for DSH / Codex covering the
  venv, `pip install "reme-ai[core]"`, `reme start service.backend=http`, a health check, and reporting back) and
  **Open official docs**.
- Switching the root checks `venv\Scripts\reme.exe`, the config, and the version first; the version check reads package
  metadata through ReMe's own virtualenv, so **ReMe does not need to be running**.
- **Endpoint fields are backfilled from `.env`**: if the LLM / Embedding address or model in `config.json` is empty but
  `.env` has a value, opening the window fills it in and says so.

## VM tunnel

An example target is `ubuntu@192.168.1.100`:

```text
VM 127.0.0.1:22333  ── ssh -R ──▶  Windows 127.0.0.1:2333
```

Each target sets its own name, user, host (IP or an `~/.ssh/config` alias), SSH port, VM-side port, private key path,
and enabled state. Leaving the key path empty lets OpenSSH use its default key, and different VMs can use different
mapped ports.

The tool prefers the SSH keys Windows already has and **never generates keys or changes firewall rules**. Clients
inside the VM connect to `http://127.0.0.1:<mapped port>/mcp`.

A tunnel that drops is reconnected by the health check, and a tunnel you stopped stays stopped — the tool remembers
which of the two you asked for.

## Data boundaries

- The tool's config **and** log live in user data
  (`%LOCALAPPDATA%\reme-helper\`: `config.json` plus `log\reme-helper.log`, rotated at 1 MB with 3 backups). Memory data
  stays in ReMe's workspace, and **deleting reme-helper never deletes memories**.
- Quitting the tool stops the ReMe process and SSH tunnels it started or took over.
- The `config.json` in a release is a factory template (containing nothing about the author's machine), generated by
  `scripts/make_release_config.py`. On **first run** the tool copies it - or, for an existing installation, your own file
  next to the exe - into user data. It only copies, never deletes, so an in-place update can neither lose your settings
  nor overwrite them with the shipped template.

## Build and release

```bat
build.bat            :: tests + icon + PyInstaller + verification, then start the new exe
build.bat release    :: the same, plus the packaged --release gate
build.bat norun      :: build without launching it
build.bat clean --force
```

Artifacts go to `release\reme-helper-<version>\`; build intermediates go to `.cache\` (PyInstaller's dist/work/spec
plus a venv created on demand). The build picks its interpreter as "the path configured at the top of
`scripts/build.bat`, else `python` on PATH" — edit that one line for your machine. When PyInstaller is missing, the
build creates an isolated venv and installs `requirements.txt`, so a clean machine (or CI) needs only Python.
