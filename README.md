# reme-helper

English | [简体中文](README.zh-CN.md)

Set up ReMe, connect your agents to it, and keep one memory across machines.

**A Windows tray application for [ReMe](https://github.com/agentscope-ai/ReMe).** It selects and generates ReMe's
configuration, runs the service, and connects agent clients — Codex on Windows, Codex inside a VM, and DeepSeek
Harness — to a single ReMe instance with a single workspace.

## What it configures

ReMe's behaviour comes from YAML: which jobs run, on what schedule, against which model and embedding endpoint. This
tool writes that configuration from a window instead of by hand.

- **Modes** — Basic, Full, or Custom. The mode is derived from the generated file's content, so it cannot disagree
  with what is actually running.
- **Job allowlist** — writes `service.jobs`, checked against the jobs that exist in your ReMe version (a name that
  does not exist makes ReMe fail at startup).
- **LLM and embedding** — endpoints, models, keys, token budget, reasoning effort, embedding dimensions, and the
  consolidation schedule. Keys go to `.env`, everything else to the generated config.
- **Connection tests** — a real request that verifies the model returns structured JSON (which `auto_memory` and
  `auto_dream` require), and an embedding test that checks similar sentences score above unrelated ones.
- **Service control** — start, stop, restart, and see state, from the tray.
- **VM tunnels** — named SSH reverse-tunnel targets, each with its own VM-side port, so a VM reaches the same ReMe
  instance. Tunnels that drop are reconnected; tunnels you stop stay stopped.
- **Generated config is validated before it is written**, and a change that fails is rolled back.

## What it connects

| Client | How it reaches ReMe |
|---|---|
| Codex (Windows) | MCP server entry + a lifecycle hook that records conversations automatically |
| Codex (inside a VM) | Same, through the reverse tunnel, pointed at the tunnel port |
| DeepSeek Harness | ReMe's official DSH plugin, plus an MCP client entry for write access |

The app ships the step-by-step guide for all three — read it in a window, or copy it (with the Codex capture script
appended) and hand the whole thing to an agent that can edit files on the machine.

## Get started

1. Download `reme-helper-<version>-windows-x64.zip` from [Releases](../../releases) and unpack it anywhere.
2. Run `reme-helper-<version>.exe`. It lives in the tray; double-click the icon for the console.
3. If ReMe is not detected, click **Copy install prompt** and give it to an agent, then point the app at the ReMe
   folder — or click **Scan** to find it.
4. Fill in the LLM and embedding endpoints, click **Test**, then **Validate and save**.
5. For agent clients, click **Read the setup guide** (or **Copy the setup guide**) and follow it.

> [!IMPORTANT]
> ReMe must be running for agents to use memory. The app manages that, but it does not install ReMe itself — that is
> what the install prompt and **Scan** are for.

## Skill installation

Skills are read from one location. Installing a skill into `~/.agents/skills/<name>/` makes it available to Codex,
DeepSeek Harness, and other agents that follow the same conventions — do not also copy it into `~/.codex/skills/`,
which would load the same skill twice:

```text
~/.agents/skills/<name>/SKILL.md      canonical user-scope location
```

The app itself is not a skill and needs no installation beyond unpacking the zip.

## Modes

| Mode | Config file | What is on |
|---|---|---|
| Basic | `config/app.yaml` | Markdown read/write, BM25, wikilinks, Studio, MCP, index maintenance. No model calls. |
| Full | `config/app-full.yaml` | ReMe's official defaults: Auto Memory, Auto Resource, Auto Dream, internal Chat. Needs LLM credentials. |
| Custom | `config/app-custom.yaml` | You pick: auto memory, Claude Code entry, resource processing, dream, proactive, chat, embedding, FAISS, Studio, MCP. |

Switching modes swaps the capability set only — addresses, models, keys, and tuning values are shared settings and
are never cleared. Editing one capability while on a preset switches you to Custom and applies just that change.

## Repository layout

```
src/          application sources (main.py, i18n.py, guide.py)
tests/        test suites - all of them gates in the build; conftest.py sets up src/
scripts/      build.bat (the real build) and make_release_config.py
doc/          documentation, by language: doc/zh/ and doc/en/ hold setup.md and
              configuration.md; doc/capture.mjs is the Codex capture script.
              The app reads this folder at runtime, so it ships inside the release.
.github/      CI: tests on every push, release artifacts on a v* tag
build.bat     thin wrapper -> scripts/build.bat
release.bat   tag and push v<version> -> CI builds the release
```

Runtime output stays out of the sources and out of a release:

```
doc's sibling log/         diagnostics written by a single run (smoke / ui-check / release /
                           lang-audit) and log/tests/<suite>.log - all disposable
.cache/                    PyInstaller staging, the on-demand build venv, the spec file
release/reme-helper-<v>/   the built package (this is what a release zip contains)
%LOCALAPPDATA%/reme-helper/log/reme-helper.log   the app's own log, rotated at 1 MB with 3
                                                 backups - user data, never part of the package
```

## Build from source

```bat
build.bat                  :: tests, icon, package, verify - then start the new exe
build.bat release          :: the same, plus the packaged --release gate
build.bat norun            :: build without launching it
build.bat clean --force    :: remove the build cache and built releases
release.bat                :: tag v<version> and push; CI publishes the zip
```

The version lives in `src/main.py` (`VERSION`) — the single source of truth for the app, the folder name, and the git
tag. The build refuses to run while any `reme-helper*.exe` is running (locked files, two trays fighting over one
config), runs every test suite as a gate, and writes to `release/reme-helper-<version>/`. If PyInstaller is missing it
creates an isolated venv under `.cache/venv` and installs `requirements.txt`, so a clean machine needs only Python.

Every build verifies the frozen artifact before it counts as a release: `--smoke` (config shape, generated configs,
bundled documentation), `--ui-check` (the settings window really builds), `--make-icon` (the tray icon still renders
with numpy and the PIL codecs excluded), and with `release`, `--release` (frozen, clean template config, icon and menu
construct, no other instance running).

## Data boundaries

The app's config lives next to the exe; its log lives in user data. Memory data stays in ReMe's workspace — deleting
reme-helper never deletes memories. Quitting stops the ReMe process and SSH tunnels it started. A release ships a
template config generated from factory defaults; `scripts/make_release_config.py` validates it against an allowlist, so
a personal default added later fails the build instead of shipping.

## License

[MIT](LICENSE) © 2026 KenneLu

Version history: [CHANGELOG.md](CHANGELOG.md) · configuration reference: [doc/en/configuration.md](doc/en/configuration.md)
