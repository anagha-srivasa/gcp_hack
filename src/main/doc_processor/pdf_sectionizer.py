from __future__ import annotations

from typing import Dict, List, Optional

from src.main.doc_processor.sectionizer import Section


def _compute_size_thresholds(pages: List[Dict]) -> float:
    sizes: List[float] = []
    for p in pages:
        for ln in p.get("lines", []):
            sz = ln.get("size")
            if isinstance(sz, (int, float)) and sz > 0:
                sizes.append(float(sz))
    if not sizes:
        return 0.0
    sizes.sort()
    idx = int(0.85 * (len(sizes) - 1))
    return sizes[idx]


def sectionize_pdf_lines(pages: List[Dict]) -> List[Section]:
    """Create sections from PDF lines using font-size and spacing heuristics.
    pages: list of {page_num, lines:[{text,bbox,size,bold}]}
    """
    sections: List[Section] = []
    sid = 0
    current: Optional[Section] = None
    size_thr = _compute_size_thresholds(pages)

    for p in pages:
        page_num = p.get("page_num", 0)
        for ln in p.get("lines", []):
            text = (ln.get("text") or "").strip()
            if not text:
                continue
            size = float(ln.get("size") or 0.0)
            bold = bool(ln.get("bold"))
            is_heading = size >= size_thr or (bold and size_thr and size >= 0.9 * size_thr)
            if is_heading:
                if current:
                    sections.append(current)
                sid += 1
                current = Section(
                    section_id=f"sec_{sid}",
                    level=2,
                    title=text,
                    text="",
                    page_start=page_num,
                    page_end=page_num,
                )
            else:
                if current:
                    current.text += ("\n" if current.text else "") + text
                    current.page_end = max(current.page_end, page_num)
                else:
                    sid += 1
                    current = Section(
                        section_id=f"sec_{sid}",
                        level=3,
                        title="Preamble",
                        text=text,
                        page_start=page_num,
                        page_end=page_num,
                    )
    if current:
        sections.append(current)
    return sections
