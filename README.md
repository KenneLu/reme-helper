# reme-helper

English | [简体中文](README.zh-CN.md)

Set up ReMe, connect your agents to it, and keep one memory across machines.

**A Windows tray application for [ReMe](https://github.com/agentscope-ai/ReMe).** It writes ReMe's
configuration from a window instead of by hand, runs the service, and connects agent clients — Codex on
Windows, Codex inside a VM, and DeepSeek Harness — to a single ReMe instance with a single workspace.

## Features

### Configuration

ReMe's behaviour comes from YAML: which jobs run, on what schedule, against which model and embedding
endpoint. The app writes that configuration from a window, and validates it before saving — a change that
fails is rolled back.

- **Modes** — Basic, Full, or Custom. The mode is derived from the generated file's content, so it cannot
  disagree with what is actually running.
- **Job allowlist** — writes `service.jobs`, checked against the jobs that exist in your ReMe version (a name
  that does not exist makes ReMe fail at startup).
- **LLM and embedding** — endpoints, models, keys, token budget, reasoning effort, embedding dimensions, and
  the consolidation schedule. Keys go to `.env`, everything else to the generated config.
- **Connection tests** — a real request that verifies the model returns structured JSON (which `auto_memory`
  and `auto_dream` require), and an embedding test that checks similar sentences score above unrelated ones.

### Running it

Start, stop and restart the ReMe service, and see whether it is healthy, from the tray.

### VM tunnels

Named SSH reverse-tunnel targets, each with its own VM-side port, so a VM reaches the same ReMe instance.
Tunnels that drop are reconnected; tunnels you stop stay stopped.

## What it connects

| Client | How it reaches ReMe |
|---|---|
| Codex (Windows) | MCP server entry + a lifecycle hook that records conversations automatically |
| Codex (inside a VM) | Same, through the reverse tunnel, pointed at the tunnel port |
| DeepSeek Harness | ReMe's official DSH plugin, plus an MCP client entry for write access |

The app ships the step-by-step guide for all three — read it in a window, or copy it (with the Codex capture
script appended) and hand the whole thing to an agent that can edit files on the machine.

## Install

1. Download `reme-helper-<version>-windows-x64.zip` from [Releases](../../releases) and unpack it anywhere.
2. Run `reme-helper.exe`. It lives in the tray; double-click the icon for the console.
3. If ReMe is not detected, click **Copy install prompt** and give it to an agent, then point the app at the
   ReMe folder — or click **Scan** to find it.
4. Fill in the LLM and embedding endpoints, click **Test**, then **Validate and save**.
5. For agent clients, click **Read the setup guide** (or **Copy the setup guide**) and follow it.

To update later, use **Check for ReMe Helper updates** in the tray menu. It replaces the app in place and
keeps the previous build in `%LOCALAPPDATA%\reme-helper\_backup`.

> [!IMPORTANT]
> ReMe must be running for agents to use memory. The app manages that, but it does not install ReMe itself —
> that is what the install prompt and **Scan** are for.

## Modes

| Mode | Config file | What is on |
|---|---|---|
| Basic | `config/app.yaml` | Markdown read/write, BM25, wikilinks, Studio, MCP, index maintenance. No model calls. |
| Full | `config/app-full.yaml` | ReMe's official defaults: Auto Memory, Auto Resource, Auto Dream, internal Chat. Needs LLM credentials. |
| Custom | `config/app-custom.yaml` | You pick: auto memory, Claude Code entry, resource processing, dream, proactive, chat, embedding, FAISS, Studio, MCP. |

Switching modes swaps the capability set only — addresses, models, keys, and tuning values are shared settings
and are never cleared. Editing one capability while on a preset switches you to Custom and applies just that
change.

## Skills

Skills are read from one location. Installing a skill into `~/.agents/skills/<name>/` makes it available to
Codex, DeepSeek Harness, and other agents that follow the same conventions — do not also copy it into
`~/.codex/skills/`, which would load the same skill twice:

```text
~/.agents/skills/<name>/SKILL.md      canonical user-scope location
```

The app itself is not a skill and needs no installation beyond unpacking the zip.

## Configuration and data

Everything the app writes lives in `%LOCALAPPDATA%\reme-helper\`, never in the folder you unpacked:

```text
config.json    settings written by the window
log/           the app's own log, rotated at 1 MB with 3 backups
_backup/       the previous build, kept by an in-place update
```

Field-by-field reference: [doc/en/configuration.md](doc/en/configuration.md). Memory data stays in ReMe's
workspace — deleting reme-helper never deletes memories. Quitting stops the ReMe process and the SSH tunnels
it started.

## Troubleshooting

- **The process is running but its tray icon has not appeared yet:** Windows Explorer can delay removing a stale icon. The helper retries in the background for about five minutes; if the first three retries fail, it also shows an explanatory dialog. Search for `tray: registration` in `%LOCALAPPDATA%\reme-helper\log\reme-helper.log`.
- **Quit without the tray UI:** run `reme-helper.exe --quit`. It uses the same cleanup path as **Quit** in the tray menu.
- **Roll back an update:** the previous build is in `%LOCALAPPDATA%\reme-helper\_backup`; quit the current instance before restoring it.

## Development

```bat
build.bat          :: tests, icon, package, verify - then start the new exe
build.bat release  :: the same, plus the packaged --release gate
build.bat norun    :: build without launching it
release.bat        :: tag v<version> and push; CI publishes the zip
```

`src/` holds the application, `tests/` the suites (all of them gates in the build), `scripts/` the build and
the release-config generator, and `doc/` the documentation the app reads at runtime. The version lives in
`src/main.py` (`VERSION`) — the single source of truth for the app, the folder name, and the git tag; pushing
a `v*` tag is what publishes a release. See [CHANGELOG.md](CHANGELOG.md) for what changed.

## License

[MIT](LICENSE) © 2026 KenneLu
