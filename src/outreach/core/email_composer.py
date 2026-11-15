"""Parse one instruction editor; fixed sections are assembled only by code."""

from __future__ import annotations

import re
from dataclasses import dataclass

_MARKER = re.compile(r"\[KEEP\]|\[/KEEP\]")
_VARIABLE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


@dataclass(frozen=True)
class EditorPart:
    kind: str
    text: str
    index: int


def parse_editor(source: str) -> list[EditorPart]:
    """Markers delimit content, never instructions. Only transport CRLF is normalized.

    A newline immediately after/before a marker frames the block; all remaining
    whitespace and punctuation belongs to the fixed content and is preserved.
    """
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    parts = []
    cursor = 0
    opened = None
    for match in _MARKER.finditer(source):
        if match.group() == "[KEEP]":
            if opened is not None:
                raise ValueError("KEEP blocks cannot be nested.")
            instruction = source[cursor : match.start()].strip()
            if instruction:
                parts.append(EditorPart("generate", instruction, len(parts)))
            opened = match.end()
        else:
            if opened is None:
                raise ValueError("A closing [/KEEP] needs an opening [KEEP].")
            fixed = source[opened : match.start()]
            if fixed.startswith("\n"):
                fixed = fixed[1:]
            if fixed.endswith("\n"):
                fixed = fixed[:-1]
            if not fixed.strip():
                raise ValueError("KEEP blocks must contain text.")
            for variable in _VARIABLE.findall(fixed):
                if variable.strip() not in {"name", "company", "designation"}:
                    raise ValueError(f"Unknown fixed-text variable: {{{{{variable.strip()}}}}}.")
            without_variables = _VARIABLE.sub("", fixed)
            if "{{" in without_variables or "}}" in without_variables:
                raise ValueError("Use complete fixed-text variables such as {{company}}.")
            parts.append(EditorPart("keep", fixed, len(parts)))
            cursor = match.end()
            opened = None
    if opened is not None:
        raise ValueError("Close every [KEEP] block with [/KEEP].")
    instruction = source[cursor:].strip()
    if instruction:
        parts.append(EditorPart("generate", instruction, len(parts)))
    return parts


def has_fixed_content(source: str) -> bool:
    return bool(_MARKER.search(source))


def resolve_fixed(text: str, *, evidence: dict[str, str], company: str | None) -> str:
    """Only explicit known recipient placeholders are substituted; nothing inferred."""
    aliases = {
        "name": ("name", "contact name", "contact person", "person name", "recipient name"),
        "designation": ("designation", "job title", "contact title", "title", "role"),
    }
    known = {key.casefold().strip(): value for key, value in evidence.items()}
    values = {"company": company or ""}
    for variable, keys in aliases.items():
        values[variable] = next((known[key] for key in keys if known.get(key)), "")

    def substitute(match):
        variable = match.group(1).strip()
        if variable not in values:
            raise ValueError(f"Unknown fixed-text variable: {{{{{variable}}}}}.")
        value = values[variable]
        if not value:
            raise ValueError(f"No reviewed recipient value is available for {{{{{variable}}}}}.")
        return value

    return _VARIABLE.sub(substitute, text)


def fixed_content(source: str, *, evidence: dict[str, str], company: str | None) -> list[str]:
    return [
        resolve_fixed(part.text, evidence=evidence, company=company)
        for part in parse_editor(source)
        if part.kind == "keep"
    ]


def fixed_content_problem(body: str, blocks: list[str]) -> str | None:
    """Require exact blocks in original order, including internal whitespace."""
    cursor = 0
    for block in blocks:
        position = body.find(block, cursor)
        if position < 0:
            return "A fixed KEEP block is missing, changed, or out of order. Restore it exactly."
        cursor = position + len(block)
    return None
