"""Thin wrapper around Tavily's HTTP API — nothing here knows what a "lead" is.

Only responsibility: send a search query, return raw results, handle timeouts.
Business logic (turning results into Lead objects) lives in services/search_service.py.
"""

from functools import lru_cache

from tavily import TavilyClient

from app.config import settings


@lru_cache
def _get_client() -> TavilyClient:
    """Created lazily on first use, not at import time — so the app can boot
    even before this key is configured; it only fails when actually called."""
    return TavilyClient(api_key=settings.tavily_api_key)


def raw_search(query: str, max_results: int = 10) -> list[dict]:
    """Run a Tavily search and return the raw result list (untouched).

    include_raw_content=True pulls full page text, not just the short search
    snippet — needed because details like working hours are rarely in the
    snippet but often present on the page itself.
    """
    response = _get_client().search(query=query, max_results=max_results, include_raw_content="text")
    return response.get("results", [])
