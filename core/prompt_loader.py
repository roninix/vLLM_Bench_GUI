"""Parser for prompts.md — loads benchmark prompts from the external file."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Default location: project root / prompts.md
_DEFAULT_PATH = Path(__file__).parent.parent / "prompts.md"

# Module-level cache
_cache: dict[str, dict[str, Any]] | None = None
_cache_mtime: float = 0.0


def _parse_prompts_md(path: Path) -> dict[str, dict[str, Any]]:
    """
    Parse prompts.md into a dict keyed by prompt_key.

    Format per block:
        ## key_name
        label: Some Label
        max_tokens: 512
        temperature: 0.7      (optional)
        ---
        The actual prompt text goes here,
        can span multiple lines...

    Returns:
        {"key_name": {"prompt": "...", "max_tokens": 512, "label": "...", "temperature": None}, ...}
    """
    text = path.read_text(encoding="utf-8")

    # Split on ## headings
    blocks = re.split(r"^## ", text, flags=re.MULTILINE)

    prompts: dict[str, dict[str, Any]] = {}

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # First line is the key
        lines = block.split("\n")
        key = lines[0].strip().lower()
        if not key or not re.match(r"^[a-z_][a-z0-9_]*$", key):
            continue

        # Parse parameters and find --- separator
        params: dict[str, str] = {}
        prompt_start = None

        for i, line in enumerate(lines[1:], start=1):
            stripped = line.strip()

            # --- separator marks beginning of prompt text
            if stripped == "---":
                prompt_start = i + 1
                break

            # Parse "key: value" parameter lines
            if ":" in stripped and not stripped.startswith("#"):
                pkey, _, pval = stripped.partition(":")
                pkey = pkey.strip().lower()
                pval = pval.strip()
                if pkey and pval:
                    params[pkey] = pval

        # Extract prompt text (everything after ---)
        if prompt_start is not None:
            prompt_text = "\n".join(lines[prompt_start:]).strip()
        else:
            # No --- separator found, treat everything after params as prompt
            prompt_text = ""

        # Build entry
        entry: dict[str, Any] = {
            "prompt": prompt_text,
            "max_tokens": int(params.get("max_tokens", "256")),
            "label": params.get("label", key.replace("_", " ").title()),
        }

        # Optional temperature override (per-prompt)
        if "temperature" in params:
            try:
                entry["temperature"] = float(params["temperature"])
            except ValueError:
                pass

        prompts[key] = entry

    return prompts


def load_prompts(path: Path | str | None = None, force_reload: bool = False) -> dict[str, dict[str, Any]]:
    """
    Load and cache prompts from prompts.md.
    Auto-reloads if the file has been modified since last load.
    """
    global _cache, _cache_mtime

    p = Path(path) if path else _DEFAULT_PATH

    if not p.exists():
        # Fallback: return minimal custom-only dict
        return {
            "custom": {"prompt": "", "max_tokens": 256, "label": "Custom"},
        }

    mtime = p.stat().st_mtime

    if _cache is not None and not force_reload and mtime == _cache_mtime:
        return _cache

    _cache = _parse_prompts_md(p)
    _cache_mtime = mtime
    return _cache


def get_prompt_keys(path: Path | str | None = None) -> list[str]:
    """Return sorted list of available prompt keys (excluding 'custom')."""
    prompts = load_prompts(path)
    return [k for k in prompts if k != "custom"]


def get_prompt_options(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Return list of {key, label, max_tokens} for frontend UI."""
    prompts = load_prompts(path)
    result = []
    for key, cfg in prompts.items():
        result.append({
            "key": key,
            "label": cfg.get("label", key),
            "max_tokens": cfg.get("max_tokens", 256),
        })
    return result
