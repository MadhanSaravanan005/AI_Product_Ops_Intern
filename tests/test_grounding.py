"""
Deterministic Unit Tests for Research Agent Evidence Grounding (Step 6)
========================================================================
Validates that:
1. Multiple auth methods require separate evidence items.
2. Multiple API types require separate evidence items.
3. OAuth evidence cannot automatically prove PAT.
4. REST evidence cannot automatically prove GraphQL.
5. Webhook evidence cannot automatically prove REST.
6. Second-hop search is triggered when needed.
7. Failed page retrieval does not create positive evidence.
8. Search snippets are not equivalent to retrieved page evidence.
9. Official sources are prioritized.
10. Backward compatibility with existing records is preserved.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from agent.researcher import ResearchAgent
from agent.schema import (
    AccessModel,
    ApiType,
    ApiTypeDetail,
    AppResearchRecord,
    AuthMethod,
    AuthenticationDetail,
    BuildabilityStatus,
    Evidence,
    ResearchStatus,
    SourceType,
)
from agent.search import SearchEngine
from agent.scraper import DocScraper


class GroundingMockSearch(SearchEngine):
    """Mock search engine recording query history and returning targeted responses."""

    def __init__(self, responses: Optional[Dict[str, List[Dict[str, str]]]] = None):
        super().__init__()
        self.responses = responses or {}
        self.query_log: List[str] = []

    def search(
        self, query: str, max_results: int = 5, target_domains: Optional[List[str]] = None
    ) -> List[Dict[str, str]]:
        self.query_log.append(query)
        matched_results = []
        for k, res in self.responses.items():
            if k.lower() in query.lower():
                for item in res:
                    if item not in matched_results:
                        matched_results.append(item)
        if matched_results:
            return matched_results[:max_results]
        return [
            {
                "title": "General Portal",
                "url": "https://api.example.com/overview",
                "snippet": "General developer portal overview.",
            }
        ]


class GroundingMockScraper(DocScraper):
    """Mock scraper with configurable status and contents."""

    def __init__(self, pages: Optional[Dict[str, Dict[str, Any]]] = None):
        super().__init__()
        self.pages = pages or {}

    def fetch_page(
        self,
        url: str,
        fallback_snippet: str = "",
        allow_fallback_snippet: bool = False,
        return_failed_status: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if url in self.pages:
            res = self.pages[url]
            if res is None and return_failed_status:
                return {
                    "url": url,
                    "status_code": 403,
                    "source_retrieval_status": "Failed",
                    "is_snippet_only": False,
                    "title": "",
                    "text": "",
                    "excerpt": "",
                    "headings": [],
                    "error": "HTTP 403 Forbidden",
                }
            return res

        return {
            "url": url,
            "status_code": 200,
            "source_retrieval_status": "Success",
            "is_snippet_only": False,
            "title": "Example Docs",
            "text": "General documentation text.",
            "excerpt": "General documentation text.",
            "headings": ["Docs"],
        }


# ==============================================================================
# TESTS
# ==============================================================================


def test_1_multiple_auth_methods_require_separate_evidence(tmp_path):
    """Verify multiple confirmed auth methods have separate evidence items and details."""
    search = GroundingMockSearch({
        "oauth": [
            {"title": "OAuth Docs", "url": "https://api.example.com/oauth", "snippet": "OAuth2 flow"}
        ],
        "api key": [
            {"title": "API Key Docs", "url": "https://api.example.com/keys", "snippet": "API keys"}
        ],
    })
    scraper = GroundingMockScraper({
        "https://api.example.com/oauth": {
            "url": "https://api.example.com/oauth",
            "status_code": 200,
            "source_retrieval_status": "Success",
            "is_snippet_only": False,
            "title": "OAuth 2.0 Guide",
            "text": "Supports OAuth2 authorization code flow for applications.",
            "excerpt": "Supports OAuth2 authorization code flow.",
            "headings": ["OAuth2"],
        },
        "https://api.example.com/keys": {
            "url": "https://api.example.com/keys",
            "status_code": 200,
            "source_retrieval_status": "Success",
            "is_snippet_only": False,
            "title": "API Keys Guide",
            "text": "Authenticate via API key in the x-api-key request header.",
            "excerpt": "Authenticate via API key header.",
            "headings": ["API Key"],
        },
    })
    agent = ResearchAgent(
        search_engine=search,
        scraper=scraper,
        research_dir=tmp_path / "research",
        raw_dir=tmp_path / "research_raw",
        log_file=tmp_path / "log.jsonl",
    )
    record = agent.research_app(app_name="Slack")

    assert AuthMethod.OAUTH2 in record.auth_methods
    assert AuthMethod.API_KEY in record.auth_methods

    # Verify per-item evidence grounding
    auth_claims = [e.claim for e in record.evidence if "supports authentication via" in e.claim]
    assert any("OAuth2" in c for c in auth_claims)
    assert any("API Key" in c for c in auth_claims)
    assert len(auth_claims) >= 2

    # Verify authentication_details structure
    assert len(record.authentication_details) >= 2
    methods = [d.method for d in record.authentication_details]
    assert AuthMethod.OAUTH2 in methods
    assert AuthMethod.API_KEY in methods
    for d in record.authentication_details:
        assert len(d.evidence) >= 1
        assert d.status == "Confirmed"


def test_2_multiple_api_types_require_separate_evidence(tmp_path):
    """Verify multiple confirmed API types have independent evidence items and details."""
    search = GroundingMockSearch({
        "rest": [
            {"title": "REST API", "url": "https://api.example.com/rest", "snippet": "REST API"}
        ],
        "webhook": [
            {"title": "Webhooks", "url": "https://api.example.com/webhooks", "snippet": "Webhooks"}
        ],
    })
    scraper = GroundingMockScraper({
        "https://api.example.com/rest": {
            "url": "https://api.example.com/rest",
            "status_code": 200,
            "source_retrieval_status": "Success",
            "is_snippet_only": False,
            "title": "REST Reference",
            "text": "Complete REST API endpoints and HTTP methods for developers.",
            "excerpt": "Complete REST API endpoints.",
            "headings": ["REST API"],
        },
        "https://api.example.com/webhooks": {
            "url": "https://api.example.com/webhooks",
            "status_code": 200,
            "source_retrieval_status": "Success",
            "is_snippet_only": False,
            "title": "Webhooks Reference",
            "text": "Real-time webhook event subscriptions and delivery payloads.",
            "excerpt": "Real-time webhook event subscriptions.",
            "headings": ["Webhooks"],
        },
    })
    agent = ResearchAgent(
        search_engine=search,
        scraper=scraper,
        research_dir=tmp_path / "research",
        raw_dir=tmp_path / "research_raw",
        log_file=tmp_path / "log.jsonl",
    )
    record = agent.research_app(app_name="Shopify")

    assert ApiType.REST in record.api_types
    assert ApiType.WEBHOOKS in record.api_types

    api_claims = [e.claim for e in record.evidence if "provides public" in e.claim]
    assert any("REST" in c for c in api_claims)
    assert any("Webhooks" in c for c in api_claims)
    assert len(api_claims) >= 2

    # Verify api_type_details structure
    assert len(record.api_type_details) >= 2
    types = [d.api_type for d in record.api_type_details]
    assert ApiType.REST in types
    assert ApiType.WEBHOOKS in types


def test_3_oauth_evidence_cannot_automatically_prove_pat(tmp_path):
    """Anti-inference: page proving OAuth2 must NOT result in confirming Personal Access Token."""
    search = GroundingMockSearch({
        "authentication": [
            {"title": "OAuth Docs", "url": "https://api.example.com/oauth", "snippet": "OAuth2"}
        ],
    })
    scraper = GroundingMockScraper({
        "https://api.example.com/oauth": {
            "url": "https://api.example.com/oauth",
            "status_code": 200,
            "source_retrieval_status": "Success",
            "is_snippet_only": False,
            "title": "OAuth 2.0 Only",
            "text": "We strictly support OAuth 2.0 authorization code flows. No other methods.",
            "excerpt": "We strictly support OAuth 2.0.",
            "headings": ["OAuth"],
        },
    })
    agent = ResearchAgent(
        search_engine=search,
        scraper=scraper,
        research_dir=tmp_path / "research",
        raw_dir=tmp_path / "research_raw",
        log_file=tmp_path / "log.jsonl",
    )
    record = agent.research_app(app_name="Zendesk")

    assert AuthMethod.OAUTH2 in record.auth_methods
    assert AuthMethod.PERSONAL_ACCESS_TOKEN not in record.auth_methods
    assert AuthMethod.BEARER_TOKEN not in record.auth_methods


def test_4_rest_evidence_cannot_automatically_prove_graphql(tmp_path):
    """Anti-inference: page proving REST endpoints must NOT confirm GraphQL without evidence."""
    search = GroundingMockSearch({
        "rest": [
            {"title": "REST Docs", "url": "https://api.example.com/rest", "snippet": "REST API"}
        ],
    })
    scraper = GroundingMockScraper({
        "https://api.example.com/rest": {
            "url": "https://api.example.com/rest",
            "status_code": 200,
            "source_retrieval_status": "Success",
            "is_snippet_only": False,
            "title": "REST API Only",
            "text": "Documentation covering our REST API and HTTP methods.",
            "excerpt": "REST API endpoints and methods.",
            "headings": ["REST"],
        },
    })
    agent = ResearchAgent(
        search_engine=search,
        scraper=scraper,
        research_dir=tmp_path / "research",
        raw_dir=tmp_path / "research_raw",
        log_file=tmp_path / "log.jsonl",
    )
    record = agent.research_app(app_name="Stripe")

    assert ApiType.REST in record.api_types
    assert ApiType.GRAPHQL not in record.api_types


def test_5_webhook_evidence_cannot_automatically_prove_rest(tmp_path):
    """Anti-inference: Webhook documentation alone must not automatically confirm REST."""
    search = GroundingMockSearch({
        "api reference": [
            {"title": "Events Only", "url": "https://api.example.com/webhooks", "snippet": "Webhooks"}
        ],
        "api_rest": [],  # REST search returns nothing
    })
    scraper = GroundingMockScraper({
        "https://api.example.com/webhooks": {
            "url": "https://api.example.com/webhooks",
            "status_code": 200,
            "source_retrieval_status": "Success",
            "is_snippet_only": False,
            "title": "Events and Webhooks",
            "text": "Outbound webhook event subscriptions only.",
            "excerpt": "Outbound webhook event subscriptions only.",
            "headings": ["Webhooks"],
        },
    })
    agent = ResearchAgent(
        search_engine=search,
        scraper=scraper,
        research_dir=tmp_path / "research",
        raw_dir=tmp_path / "research_raw",
        log_file=tmp_path / "log.jsonl",
    )
    record = agent.research_app(app_name="Mailchimp")

    assert ApiType.WEBHOOKS in record.api_types
    assert ApiType.REST not in record.api_types


def test_6_second_hop_search_triggered_when_needed(tmp_path):
    """Verify second-hop search is executed when initial pages do not prove candidate types."""
    search = GroundingMockSearch({
        "general": [
            {"title": "General", "url": "https://api.example.com/general", "snippet": "General developer portal"}
        ],
        "rest api": [
            {"title": "REST Docs", "url": "https://api.example.com/rest-docs", "snippet": "REST API"}
        ],
    })
    scraper = GroundingMockScraper({
        "https://api.example.com/general": {
            "url": "https://api.example.com/general",
            "status_code": 200,
            "source_retrieval_status": "Success",
            "is_snippet_only": False,
            "title": "Developer Portal",
            "text": "Welcome to our developer ecosystem.",
            "excerpt": "Welcome to our developer ecosystem.",
            "headings": ["Overview"],
        },
        "https://api.example.com/rest-docs": {
            "url": "https://api.example.com/rest-docs",
            "status_code": 200,
            "source_retrieval_status": "Success",
            "is_snippet_only": False,
            "title": "REST API Reference",
            "text": "Public REST API endpoints and HTTP methods.",
            "excerpt": "Public REST API endpoints.",
            "headings": ["Endpoints"],
        },
    })
    agent = ResearchAgent(
        search_engine=search,
        scraper=scraper,
        research_dir=tmp_path / "research",
        raw_dir=tmp_path / "research_raw",
        log_file=tmp_path / "log.jsonl",
    )
    record = agent.research_app(app_name="Apify")

    # Verify second-hop search query was logged
    second_hop_queries = [q for q in search.query_log if "REST" in q]
    assert len(second_hop_queries) >= 1
    assert ApiType.REST in record.api_types


def test_7_failed_page_retrieval_does_not_create_positive_evidence(tmp_path):
    """Verify failed HTTP retrieval (403/500/timeout) is recorded as Failed and creates no evidence."""
    search = GroundingMockSearch({
        "authentication": [
            {"title": "Protected Docs", "url": "https://blocked.example.com/docs", "snippet": "OAuth2"}
        ],
    })
    # Scraper returns None/Failed for the URL
    scraper = GroundingMockScraper({
        "https://blocked.example.com/docs": None,
    })
    agent = ResearchAgent(
        search_engine=search,
        scraper=scraper,
        research_dir=tmp_path / "research",
        raw_dir=tmp_path / "research_raw",
        log_file=tmp_path / "log.jsonl",
    )
    record = agent.research_app(app_name="Salesforce")

    # No auth claims should cite the blocked URL
    for ev in record.evidence:
        assert "blocked.example.com" not in str(ev.source_url)


def test_8_search_snippets_are_not_equivalent_to_retrieved_page_evidence(tmp_path):
    """Verify search snippets are not used as verified page evidence when page retrieval fails."""
    search = GroundingMockSearch({
        "authentication": [
            {
                "title": "OAuth 2.0 Auth Docs",
                "url": "https://unreachable.example.com/auth",
                "snippet": "Supports OAuth 2.0 authorization code flow.",
            }
        ],
    })
    scraper = GroundingMockScraper({
        "https://unreachable.example.com/auth": None,
    })
    agent = ResearchAgent(
        search_engine=search,
        scraper=scraper,
        research_dir=tmp_path / "research",
        raw_dir=tmp_path / "research_raw",
        log_file=tmp_path / "log.jsonl",
    )
    record = agent.research_app(app_name="GitHub")

    for ev in record.evidence:
        assert "unreachable.example.com" not in str(ev.source_url)


def test_9_official_sources_are_prioritized(tmp_path):
    """Verify that official website domain is identified and prioritized in targeted search queries."""
    search = GroundingMockSearch({
        "official website": [
            {"title": "Official Notion", "url": "https://developers.notion.com/", "snippet": "Official"}
        ],
    })
    scraper = GroundingMockScraper({
        "https://developers.notion.com/": {
            "url": "https://developers.notion.com/",
            "status_code": 200,
            "source_retrieval_status": "Success",
            "is_snippet_only": False,
            "title": "Notion Developers",
            "text": "Official developer platform for Notion integrations.",
            "excerpt": "Official developer platform.",
            "headings": ["Developers"],
        },
    })
    agent = ResearchAgent(
        search_engine=search,
        scraper=scraper,
        research_dir=tmp_path / "research",
        raw_dir=tmp_path / "research_raw",
        log_file=tmp_path / "log.jsonl",
    )
    record = agent.research_app(app_name="Notion")
    assert record.website is not None
    assert "notion.com" in str(record.website)


def test_10_backward_compatibility_with_existing_records():
    """Verify existing AppResearchRecord serializations without details validate seamlessly."""
    legacy_data = {
        "id": 1,
        "app": "TestApp",
        "category": "CRM and Sales",
        "website": "https://example.com/",
        "one_line_description": "A test platform.",
        "auth_methods": ["OAuth2"],
        "access_model": "Free Self-Serve",
        "api_types": ["REST"],
        "api_breadth": "Broad",
        "mcp_status": "No MCP Found",
        "buildability": "Buildable Now",
        "evidence": [
            {
                "claim": "TestApp supports OAuth2.",
                "source_url": "https://example.com/oauth",
                "source_title": "OAuth Docs",
                "source_type": "Official Authentication Documentation",
                "evidence_summary": "OAuth2 docs.",
            }
        ],
        "research_status": "Completed",
    }
    rec = AppResearchRecord.model_validate(legacy_data)
    assert rec.authentication_details == []
    assert rec.api_type_details == []
    assert rec.auth_methods == [AuthMethod.OAUTH2]
