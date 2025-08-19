from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional

import filetype


@dataclass
class FileInfo:
  path: str
  mime: str
  ext: str


def sniff_file(path: str) -> FileInfo:
  """Content-based file identification using filetype.
  Returns mime/ext grounded in magic bytes, not filename.
  """
  with open(path, 'rb') as f:
    head = f.read(261)
  kind = filetype.guess(head)
  if kind is None:
    # Fallback to generic octet-stream; ext unknown
    return FileInfo(path=path, mime='application/octet-stream', ext='')
  return FileInfo(path=path, mime=kind.mime or '', ext=kind.extension or '')
