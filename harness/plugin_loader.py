"""
plugin_loader.py — file-based plugin system for the harness.

Plugins live in plugins/<name>/ and consist of:
  plugin.json     manifest (name, description, commands, skills)
  skills/*.md     domain knowledge injected automatically into synthesis
  commands/*.md   prompt templates for explicit slash commands

Calling load_all() scans the directory, registers commands into skills.REGISTRY
(so parse_skills() picks them up as /plugin:command tokens), and caches skill
content for injection into synthesis.

Hot-reloading: call load_all() again after creating a new plugin — everything
updates in place without restarting the process.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.config import ROOT as _ROOT

PLUGINS_DIR  = _ROOT / "plugins"

# ── Internal state ────────────────────────────────────────────────────────────

_plugins:  dict[str, dict] = {}   # name → {dir, manifest}
_commands: dict[str, dict] = {}   # "name:cmd" → {plugin, definition, template}
_skills:   list[tuple]     = []   # [(plugin_name, skill_name, content)]

# Keys we added to skills.REGISTRY so we can remove them on reload.
_registry_keys: set[str] = set()


# ── Loader ────────────────────────────────────────────────────────────────────

def load_all():
    """Scan plugins/ and load every plugin manifest. Updates skills.REGISTRY."""
    global _plugins, _commands, _skills, _registry_keys

    # Remove any previously registered plugin keys from skills.REGISTRY
    try:
        from harness.skills import REGISTRY
        for key in _registry_keys:
            REGISTRY.pop(key, None)
    except ImportError:
        REGISTRY = None
    _registry_keys = set()

    _plugins  = {}
    _commands = {}
    _skills   = []

    if not PLUGINS_DIR.exists():
        return

    for plugin_dir in sorted(PLUGINS_DIR.iterdir()):
        if not plugin_dir.is_dir():
            continue
        manifest_path = plugin_dir / "plugin.json"
        if not manifest_path.exists():
            continue
        try:
            _load_plugin(plugin_dir, manifest_path, REGISTRY)
        except Exception as exc:
            print(f"[warn] plugin {plugin_dir.name}: {exc}")


def _load_plugin(plugin_dir: Path, manifest_path: Path, registry):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    name     = manifest.get("name", plugin_dir.name)

    _plugins[name] = {"dir": plugin_dir, "manifest": manifest}

    # ── Register commands ─────────────────────────────────────────────────────
    for cmd in manifest.get("commands", []):
        cmd_name = cmd["name"]
        key      = f"{name}:{cmd_name}"

        tpl_path = plugin_dir / cmd.get("template", f"commands/{cmd_name}.md")
        template = tpl_path.read_text(encoding="utf-8") if tpl_path.exists() else ""

        _commands[key] = {
            "plugin":     name,
            "definition": cmd,
            "template":   template,
        }

        # Inject into skills.REGISTRY so parse_skills() recognises /plugin:cmd
        if registry is not None and key not in registry:
            registry[key] = {
                "description": cmd.get("description", f"{name} — {cmd_name}"),
                "hook":        "standalone",
                "prompt":      None,
                "auto":        None,
            }
            _registry_keys.add(key)

    # ── Load auto-inject skills ───────────────────────────────────────────────
    for skill in manifest.get("skills", []):
        if not skill.get("auto_inject", True):
            continue
        skill_file = skill.get("file") or skill.get("path", "")
        if not skill_file:
            continue
        skill_path = plugin_dir / skill_file
        if skill_path.exists():
            _skills.append((name, skill["name"], skill_path.read_text(encoding="utf-8")))


# ── Accessors ─────────────────────────────────────────────────────────────────

def get_commands() -> dict[str, dict]:
    return dict(_commands)


def get_plugins() -> dict[str, dict]:
    return dict(_plugins)


def get_skill_context() -> str:
    """Return all auto-inject skill content, ready to append to skill_context."""
    if not _skills:
        return ""
    parts = []
    for plugin_name, skill_name, content in _skills:
        parts.append(f"### Plugin skill: {plugin_name}/{skill_name}\n\n{content.strip()}")
    return "\n\n---\n\n".join(parts)


def resolve_command(key: str) -> dict | None:
    return _commands.get(key)


def command_path_optional(key: str) -> bool:
    cmd = _commands.get(key)
    return bool(cmd and cmd["definition"].get("path_optional", False))


# ── Plugin creation (used by /forge) ─────────────────────────────────────────

def create_plugin(
    name:     str,
    manifest: dict,
    skills:   dict[str, str],   # filename → content
    commands: dict[str, str],   # filename → content
) -> Path:
    """Write a new plugin to plugins/<name>/ and hot-reload. Returns plugin dir."""
    plugin_dir = PLUGINS_DIR / name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if skills:
        skills_dir = plugin_dir / "skills"
        skills_dir.mkdir(exist_ok=True)
        for fname, content in skills.items():
            (skills_dir / fname).write_text(content, encoding="utf-8")

    if commands:
        cmds_dir = plugin_dir / "commands"
        cmds_dir.mkdir(exist_ok=True)
        for fname, content in commands.items():
            (cmds_dir / fname).write_text(content, encoding="utf-8")

    load_all()   # hot-reload so new commands are immediately live
    return plugin_dir
