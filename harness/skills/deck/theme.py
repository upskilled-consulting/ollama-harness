"""Parse design-system markdown -> DesignTheme with colors, fonts, sizes."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DesignTheme:
    bg_primary:     str = "#0f1117"
    bg_surface:     str = "#1e2030"
    text_primary:   str = "#e2e8f0"
    text_secondary: str = "#94a3b8"
    accent:         str = "#818cf8"
    heading_font:   str = "Calibri"
    body_font:      str = "Calibri"
    title_size:     int = 40
    h1_size:        int = 32
    h2_size:        int = 24
    h3_size:        int = 18
    body_size:      int = 14
    small_size:     int = 11


def _hex_from_val(val: str) -> str | None:
    val = val.strip()
    m = re.match(r"#([0-9a-fA-F]{3,6})$", val)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = h[0] * 2 + h[1] * 2 + h[2] * 2
        return f"#{h.lower()}"
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", val)
    if m:
        return f"#{int(m.group(1)):02x}{int(m.group(2)):02x}{int(m.group(3)):02x}"
    return None


# Priority-ordered candidate var-name fragments for each slot.
# First match in dict order wins.
_SLOT_PATTERNS: dict[str, list[str]] = {
    "bg_primary":     ["bg-primary", "background-primary", "bg-base", "bg-main",
                       "color-bg", "bg(?!.*surface|.*card|.*secondary)", "background(?!.*surface)"],
    "bg_surface":     ["bg-surface", "surface", "bg-card", "card-bg", "bg-secondary",
                       "bg-elevated", "panel-bg", "bg-2"],
    "text_primary":   ["text-primary", "foreground(?!.*secondary|.*muted)", "text-base",
                       "color-text(?!.*secondary)", "fg(?!.*secondary)", "text(?!.*secondary|.*muted)"],
    "text_secondary": ["text-secondary", "text-muted", "muted", "dim(?!ension)", "subtle",
                       "text-dim", "foreground-muted"],
    "accent":         ["accent(?!.*bg|.*background)", "brand", "highlight(?!.*bg)",
                       "interactive", "color-accent", "primary-color", "cta"],
}


def _match_slot(css_vars: dict[str, str], patterns: list[str]) -> str | None:
    """Return hex value for the first var whose name matches any of the regex patterns."""
    for pat in patterns:
        rx = re.compile(pat, re.IGNORECASE)
        for k, v in css_vars.items():
            if rx.search(k):
                h = _hex_from_val(v)
                if h:
                    return h
    return None


def parse_design_tokens(design_md: str) -> DesignTheme:
    """Extract DesignTheme from a design-system markdown document."""
    theme = DesignTheme()

    # ── Primary: parse :root CSS block ────────────────────────────────────────
    css_vars: dict[str, str] = {}
    for root_block in re.finditer(r":root\s*\{([^}]+)\}", design_md, re.DOTALL):
        for m in re.finditer(r"--([^:\s]+)\s*:\s*([^;]+);", root_block.group(1)):
            css_vars[m.group(1).strip()] = m.group(2).strip()
        break  # use first :root block only

    if css_vars:
        if h := _match_slot(css_vars, _SLOT_PATTERNS["bg_primary"]):
            theme.bg_primary    = h
        if h := _match_slot(css_vars, _SLOT_PATTERNS["bg_surface"]):
            theme.bg_surface    = h
        if h := _match_slot(css_vars, _SLOT_PATTERNS["text_primary"]):
            theme.text_primary  = h
        if h := _match_slot(css_vars, _SLOT_PATTERNS["text_secondary"]):
            theme.text_secondary = h
        if h := _match_slot(css_vars, _SLOT_PATTERNS["accent"]):
            theme.accent        = h

        # If bg_surface is same as bg_primary, use a slightly lighter shade or keep default
        if theme.bg_surface == theme.bg_primary:
            theme.bg_surface = theme.bg_primary  # caller decides; default is fine

        # Font families — heading first, then body
        font_vars = {k: v for k, v in css_vars.items()
                     if re.search(r"font|typeface|family|sans|serif|body|heading", k, re.IGNORECASE)}
        for k, v in font_vars.items():
            family = v.strip("\"'").split(",")[0].strip().strip("\"'")
            # Skip non-font values: hex colors, numbers, CSS keywords, empty
            if not family or family.startswith("var(") or family.startswith("--"):
                continue
            if _hex_from_val(family):
                continue   # it's a color value, not a font name
            if re.match(r"^[\d.]+(?:px|em|rem|%)?$", family):
                continue   # it's a size
            if family.lower() in ("none", "normal", "bold", "italic", "inherit", "initial"):
                continue
            if re.search(r"heading|display|title", k, re.IGNORECASE):
                theme.heading_font = family
            elif re.search(r"body|sans|base", k, re.IGNORECASE):
                theme.body_font = family
                if theme.heading_font == "Calibri":
                    theme.heading_font = family
            else:
                if theme.body_font == "Calibri":
                    theme.body_font    = family
                if theme.heading_font == "Calibri":
                    theme.heading_font = family
            break

    # ── Fallback: scan Color System section ───────────────────────────────────
    if not css_vars:
        cs_m = re.search(r"##\s*Color System(.*?)(?=\n##|\Z)", design_md, re.DOTALL | re.IGNORECASE)
        if cs_m:
            hexes = re.findall(r"#([0-9a-fA-F]{6})", cs_m.group(1))
            if hexes:
                theme.bg_primary = f"#{hexes[0]}"
            if len(hexes) >= 2:
                theme.bg_surface = f"#{hexes[1]}"
            for h in hexes:
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                if (r + g + b) / 3 > 180 and f"#{h}" != theme.bg_primary:
                    theme.text_primary = f"#{h}"
                    break

    # ── Google Fonts link -> font name ────────────────────────────────────────
    gf_m = re.search(r"family=([A-Za-z+]+)", design_md)
    if gf_m:
        font_name = gf_m.group(1).replace("+", " ")
        if theme.heading_font == "Calibri":
            theme.heading_font = font_name
        if theme.body_font == "Calibri":
            theme.body_font = font_name

    return theme
