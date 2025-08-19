from __future__ import annotations

from typing import Dict, Any, List

# Define JSON-like query templates. Use ${param} placeholders for values.
QUERIES: Dict[str, Dict[str, Any]] = {
    "by_document_id": {
        "description": "Delete by exact document_id",
        "expects": ["document_id"],
        "query": {"document_id": "${document_id}"},
    },
    "by_title_contains": {
        "description": "Delete documents whose title matches substring (case-insensitive)",
        "expects": ["title"],
        "query": {"title": {"$regex": "${title}", "$options": "i"}},
    },
    "by_author_contains": {
        "description": "Delete documents with author matching substring (case-insensitive)",
        "expects": ["author"],
        "query": {"author": {"$regex": "${author}", "$options": "i"}},
    },
    "by_date_range": {
        "description": "Delete documents uploaded within ISO date range",
        "expects": ["from", "to"],
        "query": {"upload_date": {"$gte": "${from}", "$lte": "${to}"}},
    },
    "by_tag": {
        "description": "Delete documents that have a specific tag",
        "expects": ["tag"],
        "query": {"tags": "${tag}"},
    },
}


def list_query_names() -> List[str]:
    return sorted(QUERIES.keys())


def get_query_template(name: str) -> Dict[str, Any]:
    if name not in QUERIES:
        raise KeyError(f"Unknown query: {name}")
    return QUERIES[name]


def materialize_query(name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    tmpl = get_query_template(name)
    # Deep replace ${...} in the query dict
    import json, re
    raw = json.dumps(tmpl.get("query", {}))
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        val = params.get(key, "")
        return str(val)
    raw = re.sub(r"\$\{([^}]+)\}", repl, raw)
    return json.loads(raw)
