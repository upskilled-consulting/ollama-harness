"""
harness/skills — skill registry and loader.

Skills are auto-discovered from this package. Each skill module exposes:
  SKILL_DEFS: list[dict]  — op-level skill descriptors (name, aliases, description, handler)

The registry merges all SKILL_DEFS at import time.
"""

from __future__ import annotations
import importlib
import pkgutil
from pathlib import Path
from typing import Any

_HERE = Path(__file__).parent
_registry: dict[str, dict] = {}


def _load_all() -> None:
    for info in pkgutil.iter_modules([str(_HERE)]):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"harness.skills.{info.name}")
            for skill in getattr(mod, "SKILL_DEFS", []):
                _registry[skill["name"]] = skill
        except Exception:
            pass


_load_all()


def get(name: str) -> dict | None:
    return _registry.get(name)


def all_skills() -> list[dict]:
    return list(_registry.values())


def run(name: str, **kwargs: Any) -> Any:
    skill = _registry.get(name)
    if not skill:
        raise KeyError(f"Unknown skill: {name!r}")
    return skill["handler"](**kwargs)
