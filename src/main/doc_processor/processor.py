from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from src.main.tools.identify import sniff_file, FileInfo
from src.main.doc_processor.extractors.docx_fast import extract_docx_fast
from src.main.doc_processor.extractors.pdf_native import extract_pdf_native_text
from src.main.doc_processor.pdf_sectionizer import sectionize_pdf_lines
from src.main.doc_processor.sectionizer import sectionize_from_docx_paragraphs, Section


@dataclass
class ProcessResult:
    document_id: str
    mime: str
    sections: List[Section]
    meta: Dict[str, Any]


def process_file(document_id: str, path: str) -> ProcessResult:
    info: FileInfo = sniff_file(path)
    sections: List[Section] = []
    meta: Dict[str, Any] = {"path": path, "mime": info.mime, "ext": info.ext}

    if info.mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/x-zip-compressed",
    ) or path.lower().endswith(".docx"):
        docx = extract_docx_fast(path)
        paragraphs = [{"text": p.text, "style": p.style} for p in docx.paragraphs]
        sections = sectionize_from_docx_paragraphs(paragraphs)
        meta["has_heading_styles"] = docx.has_heading_styles
    elif info.mime == "application/pdf" or path.lower().endswith(".pdf"):
        pages = extract_pdf_native_text(path)
        pages_dict = [
            {"page_num": p.page_num, "lines": p.lines}  # minimal for sectionizer
            for p in pages
        ]
        sections = sectionize_pdf_lines(pages_dict)
    elif info.mime == "application/msword" or path.lower().endswith(".doc"):
        meta["note"] = "Legacy .doc normalization to .docx required before extraction"
        sections = []
    else:
        meta["note"] = f"Unsupported MIME: {info.mime}"

    return ProcessResult(document_id=document_id, mime=info.mime, sections=sections, meta=meta)
