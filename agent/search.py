"""
AI Product Ops Research System - Search Engine Interface
=========================================================
Provides search functionality prioritizing first-party documentation,
developer portals, GitHub repositories, and MCP registries.
Supports duckduckgo-search / ddgs with graceful timeout and rate-limit handling,
as well as optional Serper / Tavily APIs via environment configuration.
"""

import logging
import os
import time
from typing import List, Dict, Any, Optional

logger = logging.getLogger("agent.search")


class SearchEngine:
    """Unified search engine interface for autonomous platform research."""

    def __init__(self, max_retries: int = 1, delay_between_calls: float = 0.3):
        self.max_retries = max_retries
        self.delay_between_calls = delay_between_calls
        self.query_cache: Dict[str, List[Dict[str, str]]] = {}
        self.total_searches = 0
        self.cache_hits = 0
        self.second_hop_searches = 0

    def search(
        self,
        query: str,
        max_results: int = 5,
        target_domains: Optional[List[str]] = None,
    ) -> List[Dict[str, str]]:
        """Execute a targeted web search query with caching.

        Returns a list of dicts: [{"title": ..., "url": ..., "snippet": ...}]
        """
        self.total_searches += 1
        full_query = query
        if target_domains:
            domain_filter = " OR ".join([f"site:{d}" for d in target_domains])
            full_query = f"{query} ({domain_filter})"

        # Check in-memory query cache
        cache_key = f"{full_query}::max={max_results}"
        if cache_key in self.query_cache:
            self.cache_hits += 1
            return self.query_cache[cache_key]

        logger.info(f"Searching: {full_query} (max={max_results})")

        # Try ddgs with fast direct duckduckgo backend first
        for attempt in range(self.max_retries + 1):
            try:
                from ddgs import DDGS

                results = []
                with DDGS() as ddgs:
                    try:
                        raw_results = list(ddgs.text(full_query, backend="duckduckgo", max_results=max_results))
                    except Exception:
                        raw_results = list(ddgs.text(full_query, backend="auto", max_results=max_results))

                    for r in raw_results:
                        results.append({
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                        })
                if results:
                    time.sleep(self.delay_between_calls)
                    self.query_cache[cache_key] = results
                    return results
            except Exception as e:
                logger.warning(f"Search attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries:
                    time.sleep(0.5)

        self.query_cache[cache_key] = []
        return []

    def targeted_documentation_search(
        self, app_name: str, topic: str, max_results: int = 4
    ) -> List[Dict[str, str]]:
        """Search specifically for official developer documentation on a topic."""
        query = f"{app_name} official developer documentation {topic}"
        return self.search(query, max_results=max_results)

    def search_auth_method(
        self,
        app_name: str,
        method: str,
        official_domain: Optional[str] = None,
        max_results: int = 3,
    ) -> List[Dict[str, str]]:
        """Perform targeted search for a specific authentication mechanism."""
        self.second_hop_searches += 1
        target_domains = [official_domain] if official_domain else None
        query = f"{app_name} {method} authentication documentation"
        return self.search(query, max_results=max_results, target_domains=target_domains)

    def search_api_type(
        self,
        app_name: str,
        api_type: str,
        official_domain: Optional[str] = None,
        max_results: int = 3,
    ) -> List[Dict[str, str]]:
        """Perform targeted search for a specific API architectural paradigm."""
        self.second_hop_searches += 1
        target_domains = [official_domain] if official_domain else None
        query = f"{app_name} {api_type} API reference documentation"
        return self.search(query, max_results=max_results, target_domains=target_domains)

    def search_credential_access(
        self,
        app_name: str,
        official_domain: Optional[str] = None,
        max_results: int = 3,
    ) -> List[Dict[str, str]]:
        """Perform targeted search for developer signup and credential gating."""
        self.second_hop_searches += 1
        target_domains = [official_domain] if official_domain else None
        query = f"{app_name} create API key developer portal sign up pricing"
        return self.search(query, max_results=max_results, target_domains=target_domains)

    def targeted_mcp_search(
        self, app_name: str, max_results: int = 5
    ) -> List[Dict[str, str]]:
        """Search specifically for Model Context Protocol (MCP) implementations."""
        query = f"{app_name} Model Context Protocol MCP server github official"
        return self.search(query, max_results=max_results)