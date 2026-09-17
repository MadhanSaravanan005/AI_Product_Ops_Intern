"""
AI Product Ops Research System - Web Documentation Scraper
==========================================================
Retrieves and parses web pages to extract textual evidence, titles,
and quotes from official documentation, avoiding reliance solely on search snippets.
"""

import logging
from typing import Optional, Dict, Any
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("agent.scraper")


class DocScraper:
    """HTTP client and content parser for extracting primary source evidence."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = min(timeout, 20.0)  # enforce strict 20s max timeout
        self.session = requests.Session()
        self.page_cache: Dict[str, Dict[str, Any]] = {}
        self.failed_urls: set[str] = set()
        self.total_fetches = 0
        self.cache_hits = 0
        self.failed_hits = 0
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })

    def fetch_page(
        self,
        url: str,
        fallback_snippet: str = "",
        allow_fallback_snippet: bool = True,
        return_failed_status: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Fetch and parse a web page into structured text and metadata.

        Returns:
            Dict containing {url, status_code, title, text, excerpt, headings}
            or None on failure.
        """
        self.total_fetches += 1
        if not url.startswith("http://") and not url.startswith("https://"):
            if return_failed_status:
                return {
                    "url": url,
                    "status_code": 0,
                    "source_retrieval_status": "Failed",
                    "is_snippet_only": False,
                    "title": "",
                    "text": "",
                    "excerpt": "",
                    "headings": [],
                    "error": "Invalid URL scheme",
                }
            return None

        # 1. Fast path: return cached result
        if url in self.page_cache:
            self.cache_hits += 1
            return self.page_cache[url]

        # 2. Fast path: never re-request failed or blocked URLs
        if url in self.failed_urls:
            self.failed_hits += 1
            if return_failed_status:
                return {
                    "url": url,
                    "status_code": 0,
                    "source_retrieval_status": "Failed",
                    "is_snippet_only": False,
                    "title": "",
                    "text": "",
                    "excerpt": "",
                    "headings": [],
                    "error": "Previously failed URL (cached failure)",
                }
            return None

        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            if response.status_code >= 400:
                logger.warning(f"HTTP {response.status_code} fetching {url}")
                self.failed_urls.add(url)
                if return_failed_status:
                    return {
                        "url": url,
                        "status_code": response.status_code,
                        "source_retrieval_status": "Failed",
                        "is_snippet_only": False,
                        "title": "",
                        "text": "",
                        "excerpt": "",
                        "headings": [],
                        "error": f"HTTP {response.status_code}",
                    }
                return None

            soup = BeautifulSoup(response.text, "html.parser")

            # Extract title
            title = ""
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            elif soup.find("meta", property="og:title"):
                title = soup.find("meta", property="og:title").get("content", "").strip()

            # Extract meta description
            meta_desc = ""
            meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
            if meta_tag and meta_tag.get("content"):
                meta_desc = meta_tag["content"].strip()

            # Remove scripts, styles, navigations
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                tag.decompose()

            # Extract text blocks
            paragraphs = [p.get_text(separator=" ", strip=True) for p in soup.find_all(["p", "li"])]
            text = " ".join([p for p in paragraphs if len(p) > 20])

            is_snippet_only = False
            if len(text) < 50:
                if meta_desc:
                    text = meta_desc
                elif fallback_snippet and allow_fallback_snippet:
                    text = fallback_snippet
                    is_snippet_only = True

            # Extract headings
            headings = [
                h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])
            ]

            result_dict = {
                "url": url,
                "status_code": response.status_code,
                "source_retrieval_status": "Success",
                "is_snippet_only": is_snippet_only,
                "title": title or "Documentation Page",
                "text": text[:10000],  # keep first 10k chars for analysis
                "excerpt": text[:300] if text else "",
                "headings": headings[:15],
            }
            self.page_cache[url] = result_dict
            return result_dict
        except Exception as e:
            logger.warning(f"Error fetching {url}: {e}")
            self.failed_urls.add(url)
            if return_failed_status:
                return {
                    "url": url,
                    "status_code": 0,
                    "source_retrieval_status": "Failed",
                    "is_snippet_only": False,
                    "title": "",
                    "text": "",
                    "excerpt": "",
                    "headings": [],
                    "error": str(e),
                }
            return None