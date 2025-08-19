from __future__ import annotations

from dataclasses import dataclass
from typing import List, Any
from src.main.config import get as get_config
import fitz

@dataclass
class RenderedPage:
  page_num: int
  width: int
  height: int
  image_bytes: bytes  # PNG bytes


def render_pdf_to_images(path: str, dpi: int | None = None) -> List[RenderedPage]:
  """Render each PDF page to a PNG image at given DPI.
  Returns a list of RenderedPage with PNG bytes without requiring Pillow.
  """
  out: List[RenderedPage] = []
  if dpi is None:
    dpi = int(get_config("processing.pdf.render_dpi", 300))
  with fitz.open(path) as doc:
    for i in range(len(doc)):
      page: Any = doc[i]
      zoom = dpi / 72.0
      mat = fitz.Matrix(zoom, zoom)
      pix = page.get_pixmap(matrix=mat, alpha=False)  # type: ignore[attr-defined]
      png_bytes = pix.tobytes("png")
      out.append(
        RenderedPage(
          page_num=i + 1,
          width=pix.width,
          height=pix.height,
          image_bytes=png_bytes,
        )
      )
  return out
