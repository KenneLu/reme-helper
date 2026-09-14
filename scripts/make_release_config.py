"""Generate a clean template config.json for a release folder.

Why this exists: the developer's own ``config.json`` holds the LLM/embedding
endpoints and API keys, the local ReMe root, the SSH targets of their VMs and
their saved UI preferences. Copying it into ``release/`` would ship all of that
to every user of the tool.

Instead of copying anything, this writes ``main.DEFAULT_CONFIG`` (the app's own
factory defaults) with every environment-dependent field blanked.

The template is then validated against an **allowlist** - every value must be
either a blank, a boolean, or one of the documented fixed values. That is
deliberately the strict direction: if someone later adds a personal default to
``DEFAULT_CONFIG`` (a real host, a path, a name), the allowlist rejects it and
the build fails, and no developer identifiers have to be written down here to
catch it.

``test_baseline.py`` guards the config shape from the other side.

Usage: python make_release_config.py <output path>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# The application sources live in src/; this script lives in scripts/. Add src/ to
# the path so `import main` works the same way the app and the test suites do it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import main as app  # noqa: E402

# Values that are environment-dependent and must ship blank.
BLANK_PATHS = (
    ("reme_root",),
    ("llm", "base_url"),
    ("llm", "model"),
    ("llm", "api_key"),
    ("embedding", "base_url"),
    ("embedding", "api_key"),
)

# Fixed values the rest of the template is allowed to contain. Anything not
# listed here is only acceptable if it is blank, a number, a boolean, or an
# empty list.
ALLOWED_VALUES: dict[tuple[str, ...], set[Any]] = {
    ("mode",): {"custom", "minimal", "full"},
    ("probe_interval_sec",): {300},
    ("ui_lang",): {"zh", "en"},
    ("theme",): {"light", "dark"},
    ("llm", "max_tokens"): {65536},
    ("llm", "thinking_enable"): {False},
    ("llm", "reasoning_effort"): {""},
    ("llm", "probe_ok"): {False},
    ("llm", "probe_detail"): {"未测试"},
    ("embedding", "model"): {"text-embedding-v4"},
    ("embedding", "dimensions"): {1024},
    ("embedding", "probe_ok"): {False},
    ("embedding", "probe_detail"): {"未测试"},
    ("pipeline", "scan_days"): {2},
    ("pipeline", "max_units"): {5},
    ("pipeline", "dream_cron"): {"0 23 * * *"},
    ("expose", "custom"): {False},
    # The shipped allowlist is the app's built-in default copy; its contents are
    # part of the contract with test_baseline.py, so pin the exact list here.
    ("expose", "jobs"): {tuple(app.EXPOSE_DEFAULT_FALLBACK)},
}


def build_template() -> dict:
    """Return a config with the app's factory defaults in place of local values."""
    template = app.deep_copy(app.DEFAULT_CONFIG)

    for path in BLANK_PATHS:
        node = template
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = ""

    template["mode"] = "custom"
    # Never start anything behind the user's back on first launch.
    template["start_on_launch"] = False
    template["autostart"] = False
    template["start_tunnels_with_reme"] = False

    # The developer's VM hosts, users and ports are personal data.
    template["targets"] = []
    template["ui_lang"] = "zh"
    template["theme"] = "light"
    return template


def find_offending_values(template: dict) -> list[str]:
    """List every path whose value is neither blank nor on the allowlist."""
    offending: list[str] = []

    def walk(node: Any, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, path + (key,))
            return
        if path in ALLOWED_VALUES:
            candidate = tuple(node) if isinstance(node, list) else node
            if candidate not in ALLOWED_VALUES[path]:
                offending.append(f"{'.'.join(path)}={node!r}")
            return
        allowed_blank = node in ("", None, False, True, [])
        allowed_number = isinstance(node, (int, float))
        allowed_empty_list = isinstance(node, list) and not node
        if not (allowed_blank or allowed_number or allowed_empty_list):
            offending.append(f"{'.'.join(path)}={node!r}")

    walk(template, ())
    return offending


def main_cli(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python make_release_config.py <output path>")
        return 2
    output = Path(argv[1])
    template = build_template()
    offending = find_offending_values(template)
    if offending:
        print("ERROR: release template holds values that are not factory defaults:")
        for item in offending:
            print(f"  {item}")
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"release template written: {output} (factory defaults only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli(sys.argv))
