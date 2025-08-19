from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from docx import Document  # python-docx


@dataclass
class Paragraph:
  text: str
  style: str


@dataclass
class DocxContent:
  paragraphs: List[Paragraph]
  has_heading_styles: bool


def _safe_style_name(p) -> str:
  """Return paragraph style name as a safe lowercase-able string."""
  try:
    if getattr(p, "style", None) is None:
      return ""
    raw = getattr(p.style, "name", "")
    if raw is None:
      return ""
    return str(raw)
  except Exception:
    return ""


def extract_docx_fast(path: str) -> DocxContent:
  """Extract paragraphs and their styles from a .docx file quickly.
  Uses python-docx; good for well-authored documents.
  """
  doc = Document(path)
  paras: List[Paragraph] = []
  has_heading = False
  for p in doc.paragraphs:
    st = _safe_style_name(p)
    if st and st.lower().startswith("heading"):
      has_heading = True
    paras.append(Paragraph(text=(p.text or ""), style=(st or "")))
  return DocxContent(paragraphs=paras, has_heading_styles=has_heading)
