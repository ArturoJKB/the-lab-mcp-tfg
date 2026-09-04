"""Best-effort JSON repair for LLM outputs.

The functions here are intentionally conservative: they fix common structural
mistakes made by small local models (markdown fences, trailing commas, single
quotes, unquoted keys) but give up rather than guess when the text is too far
gone. The caller is expected to fall back to deterministic output when repair
fails.
"""

from __future__ import annotations

import json
import re
from typing import Any


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` style fences and surrounding whitespace."""
    text = text.strip()
    if text.startswith("```"):
        # Drop the opening fence line.
        text = text[text.find("\n") + 1 :]
        text = text.strip()
    if text.endswith("```"):
        text = text[: text.rfind("```")].strip()
    return text


def _extract_balanced_json(text: str) -> str | None:
    """Return the first balanced JSON object or array, or None."""
    start_obj = text.find("{")
    start_arr = text.find("[")
    if start_obj == -1 and start_arr == -1:
        return None

    if start_arr == -1 or (start_obj != -1 and start_obj < start_arr):
        open_char, close_char = "{", "}"
        start = start_obj
    else:
        open_char, close_char = "[", "]"
        start = start_arr

    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"' and not in_string:
            in_string = True
        elif ch == '"' and in_string:
            in_string = False
        if not in_string:
            if ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _remove_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ] inside JSON strings."""
    # Remove commas followed immediately by a closing brace/bracket.
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


def _fix_single_quotes(text: str) -> str:
    """Replace JSON-like single quotes with double quotes where safe.

    This is a heuristic: it only touches single-quoted strings that do not
    contain escaped single quotes or nested double quotes.
    """

    def replacer(match: re.Match[str]) -> str:
        inner = match.group(1)
        if '"' in inner or "\\'" in inner:
            return match.group(0)
        return f'"{inner}"'

    return re.sub(r"'([^'\n]*?)'", replacer, text)


def _quote_unquoted_keys(text: str) -> str:
    """Add double quotes around bare object keys in JSON-like text."""
    return re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3', text)


_TRIPLE_DOUBLE = re.compile(r'("""\s*[\s\S]*?\s*""")')
_TRIPLE_SINGLE = re.compile(r"('''\s*[\s\S]*?\s*''')")


def _convert_triple_quoted_strings(text: str) -> str:
    """Convert Python triple-quoted strings into JSON-compatible strings.

    LLMs frequently emit Python-flavored JSON where a multiline value (e.g.
    generated source code) is delimited with ``\"\"\"...\"\"\"`` instead of a
    JSON string with escaped newlines. Each triple-quoted segment is replaced
    by its JSON-encoded equivalent, preserving the content exactly.
    """

    def _encode(match: re.Match[str]) -> str:
        inner = match.group(0)[3:-3]
        return json.dumps(inner.strip("\n"))

    text = _TRIPLE_DOUBLE.sub(_encode, text)
    text = _TRIPLE_SINGLE.sub(_encode, text)
    return text


def repair_json(text: str) -> dict[str, Any] | list[Any] | None:
    """Try to repair and parse a JSON object/array from LLM output.

    Returns the parsed object/list, or None if it cannot be repaired safely.
    """
    text = _strip_markdown_fences(text)
    candidate = _extract_balanced_json(text)
    if candidate is None:
        return None

    # Try increasingly aggressive repairs.
    attempts = [
        candidate,
        _convert_triple_quoted_strings(candidate),
        _remove_trailing_commas(candidate),
        _fix_single_quotes(_remove_trailing_commas(candidate)),
        _convert_triple_quoted_strings(_remove_trailing_commas(candidate)),
        _quote_unquoted_keys(_fix_single_quotes(_remove_trailing_commas(candidate))),
    ]

    for attempt in attempts:
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, (dict, list)):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def safe_json_loads(text: str) -> dict[str, Any] | list[Any] | None:
    """Parse JSON if valid, otherwise attempt repair."""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return parsed
    except json.JSONDecodeError:
        return repair_json(text)
    return None
