"""Contrato aditivo de contenido enriquecido para canales web/móvil."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

RICH_CONTENT_VERSION = "1.0"
_ALLOWED_SCHEMES = {"http", "https", "tel", "mailto"}


def safe_href(href: str) -> str | None:
    value = (href or "").strip()
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return None
    return value


def _format_deceased_process(text: str) -> str:
    low = text.lower()
    if "cliente fallecido" not in low and "de cujus" not in low:
        return text
    out = text
    out = re.sub(
        r"\s*(Etapas del Proceso)\s*",
        r"\n\n## \1\n\n",
        out,
        flags=re.I,
    )
    out = re.sub(
        r"\s*(Fase\s+[IVX]+\s*[–—-]\s*[^0-9\n]+?)(?=\s+\d+\.)",
        lambda m: f"\n\n## {m.group(1).strip()}\n\n",
        out,
        flags=re.I,
    )
    # Los ítems del proceso llegan del Excel en una sola línea.
    out = re.sub(
        r"\s+(?=(?:\d{1,2})\.\s+[A-ZÁÉÍÓÚÑ])",
        "\n",
        out,
    )
    out = re.sub(
        r"(?m)^(\d{1,2})\.\s+([^:\n]{2,80}):\s*",
        r"\1. **\2:** ",
        out,
    )
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def normalize_client_markdown(text: str | None) -> str:
    """Normaliza Markdown visible y agrega enlaces accionables como fallback."""
    out = str(text or "").strip()
    if not out:
        return ""

    # Una máscara no debe competir con delimitadores Markdown.
    out = re.sub(r"\*{3,}(?=\d{3,})", "••••", out)
    out = _format_deceased_process(out)

    if "tel:" not in out.lower():
        out = re.sub(
            r"(?<![\]\d])((?:\+?1[\s.-]?)?809[.\s-]?726[.\s-]?1000)(?![\d(])",
            lambda m: f"[{m.group(1)}](tel:+18097261000)",
            out,
        )
    if "mailto:" not in out.lower():
        out = re.sub(
            r"(?<![\w:/])([A-Z0-9._%+-]+@bsc\.com\.do)\b",
            lambda m: f"[{m.group(1)}](mailto:{m.group(1)})",
            out,
            flags=re.I,
        )
    # URLs oficiales desnudas. No tocar las que ya están dentro de ](...).
    out = re.sub(
        r"(?<![\w/(])(https?://(?:www\.)?bsc\.com\.do[^\s)]*)",
        lambda m: f"[{m.group(1)}]({m.group(1)})",
        out,
        flags=re.I,
    )
    out = re.sub(
        r"(?<![\w/@(:.\[])(bsc\.com\.do(?:/[^\s)]*)?)",
        lambda m: f"[{m.group(1)}](https://{m.group(1)})",
        out,
        flags=re.I,
    )
    return out


_TOKEN = re.compile(r"(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*)")


def inline_content(text: str) -> list[dict[str, str]]:
    """Convierte énfasis/enlaces Markdown a tokens inline seguros."""
    parts: list[dict[str, str]] = []
    pos = 0
    for match in _TOKEN.finditer(text or ""):
        if match.start() > pos:
            parts.append({"type": "text", "text": text[pos : match.start()]})
        token = match.group(0)
        link = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", token)
        if link:
            href = safe_href(link.group(2))
            if href:
                scheme = urlparse(href).scheme.lower()
                kind = "phone" if scheme == "tel" else ("email" if scheme == "mailto" else "web")
                parts.append({
                    "type": "link",
                    "text": link.group(1),
                    "href": href,
                    "kind": kind,
                })
            else:
                parts.append({"type": "text", "text": link.group(1)})
        else:
            parts.append({"type": "strong", "text": token[2:-2]})
        pos = match.end()
    if pos < len(text or ""):
        parts.append({"type": "text", "text": text[pos:]})
    return parts or [{"type": "text", "text": ""}]


def _text_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            nested: list[dict[str, Any]] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("## "):
                nested_line = lines[index].strip()
                if nested_line:
                    if re.match(r"^(?:•|-|\*)\s+", nested_line):
                        items: list[dict[str, Any]] = []
                        while index < len(lines):
                            candidate = lines[index].strip()
                            match = re.match(r"^(?:•|-|\*)\s+(.+)", candidate)
                            if not match:
                                break
                            items.append({"content": inline_content(match.group(1))})
                            index += 1
                        nested.append({"type": "list", "style": "unordered", "items": items})
                        continue
                    numbered = re.match(r"^\d+\.\s+(.+)", nested_line)
                    if numbered:
                        items = []
                        while index < len(lines):
                            candidate = lines[index].strip()
                            match = re.match(r"^\d+\.\s+(.+)", candidate)
                            if not match:
                                break
                            items.append({"content": inline_content(match.group(1))})
                            index += 1
                        nested.append({"type": "list", "style": "ordered", "items": items})
                        continue
                    nested.append({"type": "paragraph", "content": inline_content(nested_line)})
                index += 1
            blocks.append({
                "type": "section",
                "id": re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "section",
                "title": title,
                "collapsible": len(nested) > 3,
                "initially_expanded": True,
                "blocks": nested,
            })
            continue

        bullet = re.match(r"^(?:•|-|\*)\s+(.+)", line)
        numbered = re.match(r"^\d+\.\s+(.+)", line)
        if bullet or numbered:
            ordered = bool(numbered)
            items = []
            pattern = r"^\d+\.\s+(.+)" if ordered else r"^(?:•|-|\*)\s+(.+)"
            while index < len(lines):
                match = re.match(pattern, lines[index].strip())
                if not match:
                    break
                items.append({"content": inline_content(match.group(1))})
                index += 1
            blocks.append({
                "type": "list",
                "style": "ordered" if ordered else "unordered",
                "items": items,
            })
            continue

        paragraph = [line]
        index += 1
        while index < len(lines) and lines[index].strip() and not re.match(
            r"^(?:## |• |- |\* |\d+\.\s+)", lines[index].strip()
        ):
            paragraph.append(lines[index].strip())
            index += 1
        blocks.append({
            "type": "paragraph",
            "content": inline_content(" ".join(paragraph)),
        })
    return blocks


def build_rich_content(
    text: str | None,
    *,
    options: list[dict[str, Any]] | None = None,
    suggestions: list[dict[str, Any]] | None = None,
    normalized: bool = False,
) -> dict[str, Any] | None:
    markdown = str(text or "") if normalized else normalize_client_markdown(text)
    if not markdown and not options and not suggestions:
        return None

    blocks = _text_blocks(markdown) if markdown else []
    if options:
        cards = []
        for option in options[:12]:
            ref = str(option.get("ref") or "")
            selection = option.get("selection") or {}
            action = {
                "type": "select_option",
                "label": "Seleccionar",
                "selected_option_ref": ref,
            }
            if selection.get("message"):
                action["message"] = selection["message"]
            cards.append({
                "id": ref,
                "title": str(option.get("label") or ref),
                "subtitle": str(option.get("subtitle") or " · ".join(filter(None, [
                    str(option.get("product_type") or ""),
                    str(option.get("currency") or ""),
                ]))),
                "context": option.get("context"),
                "actions": [action],
            })
        blocks.append({"type": "card_group", "cards": cards})
    if suggestions:
        blocks.append({
            "type": "actions",
            "actions": [
                {
                    "type": "message",
                    "label": str(item.get("label") or item.get("question") or ""),
                    "message": str(item.get("question") or item.get("label") or ""),
                }
                for item in suggestions[:6]
                if item.get("question") or item.get("label")
            ],
        })
    return {"version": RICH_CONTENT_VERSION, "blocks": blocks}
