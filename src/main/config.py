from __future__ import annotations

import os
from typing import Any, Dict, Optional
import yaml

_CONFIG: Optional[Dict[str, Any]] = None


def _resolve_config_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    # .../src/main -> .../src/properties.yml
    return os.path.normpath(os.path.join(here, "..", "properties.yml"))


def _parse_kv_fallback(raw: str) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            key = k.strip()
            val = v.strip().strip('\"\'')
            # attempt to cast ints/bools
            if val.lower() in ("true", "false"):
                cfg[key] = val.lower() == "true"
            else:
                try:
                    cfg[key] = int(val)
                except ValueError:
                    try:
                        cfg[key] = float(val)
                    except ValueError:
                        cfg[key] = val
    return cfg


def load_config() -> Dict[str, Any]:
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    path = _resolve_config_path()
    if not os.path.exists(path):
        _CONFIG = {}
        return _CONFIG
    raw: str = ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        parsed = yaml.safe_load(raw)
        if isinstance(parsed, dict):
            _CONFIG = parsed
        else:
            _CONFIG = _parse_kv_fallback(raw)
    except Exception:
        _CONFIG = _parse_kv_fallback(raw)
    return _CONFIG


def get(path: str, default: Any = None) -> Any:
    cfg = load_config()
    # Support nested dict access via dot path
    cur: Any = cfg
    if isinstance(cur, dict):
        parts = path.split(".")
        for p in parts:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                # try flat key with dots (for kv fallback)
                return cfg.get(path, default)
        return cur
    return default
