from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any


@dataclass
class PageText:
  page_num: int
  width: float
  height: float
  words: List[Dict]
  lines: List[Dict]


def extract_pdf_native_text(path: str) -> List[PageText]:
  """Extract words and lines with bounding boxes and font sizes.
  Uses PyMuPDF if available; falls back to pdfplumber otherwise.
  """
  # Try PyMuPDF first
  try:
    try:
      import fitz  # type: ignore
    except Exception:
      from pymupdf import fitz  # type: ignore

    pages: List[PageText] = []
    doc = fitz.open(path)
    try:
      for page_index in range(len(doc)):
        page: Any = doc[page_index]
        width, height = page.rect.width, page.rect.height
        # Compatibility across PyMuPDF versions: get_text vs getText
        try:
          words = page.get_text("words")
        except AttributeError:
          words = page.getText("words")  # type: ignore[attr-defined]
        words_dicts = [
          {
            "text": w[4],
            "bbox": {"x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3]},
            "block": w[5],
            "line": w[6],
            "word_index": w[7],
          }
          for w in words
        ]
        lines: List[Dict] = []
        try:
          text_dict = page.get_text("dict")
        except AttributeError:
          text_dict = page.getText("dict")  # type: ignore[attr-defined]
        for block in text_dict.get("blocks", []):
          if block.get("type", 0) != 0:
            continue
          for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
              continue
            x0 = min(s.get("bbox", [0, 0, 0, 0])[0] for s in spans)
            y0 = min(s.get("bbox", [0, 0, 0, 0])[1] for s in spans)
            x1 = max(s.get("bbox", [0, 0, 0, 0])[2] for s in spans)
            y1 = max(s.get("bbox", [0, 0, 0, 0])[3] for s in spans)
            text = "".join(s.get("text", "") for s in spans).strip()
            max_size = max(s.get("size", 0.0) for s in spans)
            bold = any("Bold" in (s.get("font", "") or "") for s in spans)
            lines.append({
              "text": text,
              "bbox": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
              "size": max_size,
              "bold": bold,
            })

        pages.append(PageText(page_num=page_index + 1, width=width, height=height, words=words_dicts, lines=lines))
    finally:
      doc.close()
    return pages
  except Exception:
    # Fallback to pdfplumber
    try:
      import pdfplumber  # type: ignore
    except Exception as _e:
      raise ImportError("Install PyMuPDF or pdfplumber for PDF parsing") from _e

    pages: List[PageText] = []
    with pdfplumber.open(path) as pdf:
      for page_index, page in enumerate(pdf.pages):
        width, height = float(page.width), float(page.height)
        words_pl = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False) or []
        words_dicts = [
          {
            "text": w.get("text", ""),
            "bbox": {"x0": float(w.get("x0", 0)), "y0": float(w.get("top", 0)), "x1": float(w.get("x1", 0)), "y1": float(w.get("bottom", 0))},
            "block": 0,
            "line": int(page_index),
            "word_index": idx,
          }
          for idx, w in enumerate(words_pl)
        ]
        chars = page.chars or []
        buckets: Dict[int, List[Dict]] = {}
        for ch in chars:
          top = int(round(float(ch.get("top", 0))))
          buckets.setdefault(top, []).append(ch)
        lines: List[Dict] = []
        for top, chs in sorted(buckets.items(), key=lambda kv: kv[0]):
          chs_sorted = sorted(chs, key=lambda c: float(c.get("x0", 0)))
          if not chs_sorted:
            continue
          x0 = min(float(c.get("x0", 0)) for c in chs_sorted)
          y0 = min(float(c.get("top", 0)) for c in chs_sorted)
          x1 = max(float(c.get("x1", 0)) for c in chs_sorted)
          y1 = max(float(c.get("bottom", 0)) for c in chs_sorted)
          text = "".join(c.get("text", "") for c in chs_sorted).strip()
          max_size = max(float(c.get("size", 0.0)) for c in chs_sorted)
          bold = any("Bold" in str(c.get("fontname", "")) for c in chs_sorted)
          if text:
            lines.append({
              "text": text,
              "bbox": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
              "size": max_size,
              "bold": bold,
            })
        pages.append(PageText(page_num=page_index + 1, width=width, height=height, words=words_dicts, lines=lines))
    return pages
