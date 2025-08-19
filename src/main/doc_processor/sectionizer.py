from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Section:
    section_id: str
    level: int
    title: str
    text: str
    page_start: int
    page_end: int
    related: Dict[str, Any] = field(default_factory=dict)


def sectionize_from_docx_paragraphs(paragraphs: List[Dict[str, str]]) -> List[Section]:
    """Build sections from a list of {text, style} dicts (DOCX path)."""
    sections: List[Section] = []
    curr: Optional[Section] = None
    sid = 0

    def level_from_style(style: str) -> int:
        s = style.lower()
        if s.startswith("heading "):
            try:
                return max(1, min(6, int(s.split()[1])))
            except Exception:
                return 2
        if s.startswith("heading") and len(s) > 7 and s[7:].isdigit():
            return max(1, min(6, int(s[7:])))
        return 7  # body text

    for p in paragraphs:
        text = (p.get("text") or "").strip()
        style = p.get("style") or ""
        lvl = level_from_style(style)
        if lvl <= 6 and text:
            if curr:
                sections.append(curr)
            sid += 1
            curr = Section(
                section_id=f"sec_{sid}",
                level=lvl,
                title=text,
                text="",
                page_start=1,
                page_end=1,
            )
        else:
            if curr and text:
                curr.text += ("\n" if curr.text else "") + text
    if curr:
        sections.append(curr)
    return sections
