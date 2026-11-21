"""Query Crossref for real scholarly-work metadata (not full text)."""
from __future__ import annotations

import httpx


async def search_literature(query: str, limit: int = 5) -> list[dict]:
    params = {"query.bibliographic": query, "rows": min(max(limit, 1), 10),
              "select": "DOI,title,author,published,container-title,URL,type,abstract"}
    headers = {"User-Agent": "ORCA-X/0.3 (scientific literature discovery; mailto:orca-x@example.org)"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5), follow_redirects=True) as client:
        response = await client.get("https://api.crossref.org/works", params=params, headers=headers)
        response.raise_for_status()
    items = response.json().get("message", {}).get("items", [])
    results = []
    for item in items:
        titles = item.get("title") or []
        if not titles:
            continue
        date_parts = item.get("published", {}).get("date-parts", [[]])[0]
        authors = [" ".join(filter(None, (a.get("given"), a.get("family")))) for a in item.get("author", [])[:8]]
        results.append({"title": titles[0], "authors": authors, "year": date_parts[0] if date_parts else None,
                        "doi": item.get("DOI"), "url": item.get("URL"),
                        "journal": (item.get("container-title") or [None])[0], "type": item.get("type"),
                        "abstract_available": bool(item.get("abstract")),
                        "abstract": item.get("abstract", "")[:4000],
                        "source": "Crossref metadata; abstract availability depends on publisher deposit"})
    return results
