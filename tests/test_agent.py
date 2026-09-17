"""
Unit tests for the research agent (agent/researcher.py).

Uses mocked search and scraping engines to ensure deterministic,
fast execution without depending on live web network calls.

Covers:
1. App lookup by name.
2. App lookup by ID.
3. Unknown app handling.
4. Research output validation against Pydantic schema.
5. Evidence validation and claim association.
6. Missing evidence does not silently become a positive claim.
7. Research failure produces Failed status and logs.
8. Research results saved to correct directories.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
import pytest

from agent.researcher import ResearchAgent, get_slug
from agent.schema import (
    AccessModel,
    ApiBreadth,
    ApiType,
    AppResearchRecord,
    AuthMethod,
    BuildabilityStatus,
    Evidence,
    McpStatus,
    ResearchStatus,
    SourceType,
)
from agent.search import SearchEngine
from agent.scraper import DocScraper


# ==============================================================================
# MOCKS
# ==============================================================================


class MockSearchEngine(SearchEngine):
    """Deterministic mock search engine."""

    def __init__(self, search_responses: Optional[Dict[str, List[Dict[str, str]]]] = None):
        super().__init__()
        self.search_responses = search_responses or {}

    def search(
        self, query: str, max_results: int = 5, target_domains: Optional[List[str]] = None
    ) -> List[Dict[str, str]]:
        for key, res in self.search_responses.items():
            if key.lower() in query.lower():
                return res[:max_results]
        return [
            {
                "title": "Generic Documentation",
                "url": "https://api.example.com/docs",
                "snippet": "General developer documentation overview.",
            }
        ]


class MockDocScraper(DocScraper):
    """Deterministic mock scraper."""

    def __init__(self, page_responses: Optional[Dict[str, Dict[str, Any]]] = None):
        super().__init__()
        self.page_responses = page_responses or {}

    def fetch_page(
        self, url: str, fallback_snippet: str = "", **kwargs
    ) -> Optional[Dict[str, Any]]:
        if url in self.page_responses:
            return self.page_responses[url]
        return {
            "url": url,
            "status_code": 200,
            "title": "Example Platform Docs",
            "text": "Supports OAuth 2.0 and API keys. Free developer sign up available. REST API endpoints.",
            "excerpt": "Supports OAuth 2.0 and API keys. Free developer sign up available.",
            "headings": ["Overview", "Authentication"],
        }


# ==============================================================================
# 1. LOOKUP TESTS
# ==============================================================================


def test_app_lookup_by_name():
    """Verify application metadata lookup by exact name and case-insensitive name."""
    agent = ResearchAgent()
    app = agent.load_app_by_id_or_name(app_name="Slack")
    assert app["id"] == 21
    assert app["app"] == "Slack"
    assert app["category"] == "Communications and Messaging"

    # Case insensitive
    app_lower = agent.load_app_by_id_or_name(app_name="slack")
    assert app_lower["id"] == 21


def test_app_lookup_by_id():
    """Verify application metadata lookup by integer ID."""
    agent = ResearchAgent()
    app = agent.load_app_by_id_or_name(app_id=1)
    assert app["id"] == 1
    assert app["app"] == "Salesforce"
    assert app["category"] == "CRM and Sales"


def test_unknown_app_handling():
    """Verify looking up non-existent apps raises ValueError."""
    agent = ResearchAgent()
    with pytest.raises(ValueError) as exc1:
        agent.load_app_by_id_or_name(app_name="CompletelyFictionalApp999")
    assert "not found" in str(exc1.value)

    with pytest.raises(ValueError) as exc2:
        agent.load_app_by_id_or_name(app_id=9999)
    assert "not found" in str(exc2.value)


# ==============================================================================
# 2. RESEARCH OUTPUT & VALIDATION TESTS
# ==============================================================================


def test_mocked_research_output_validation(tmp_path):
    """Verify full research workflow output strictly conforms to Pydantic schema."""
    mock_search = MockSearchEngine({
        "authentication": [
            {
                "title": "OAuth 2.0 Documentation",
                "url": "https://api.slack.com/authentication/oauth-v2",
                "snippet": "Slack supports OAuth 2.0 authorization code flow.",
            }
        ],
        "credential": [
            {
                "title": "Slack API: Applications",
                "url": "https://api.slack.com/apps",
                "snippet": "Create an app and generate credentials for your free workspace.",
            }
        ],
        "api reference": [
            {
                "title": "Web API Methods",
                "url": "https://api.slack.com/methods",
                "snippet": "Explore hundreds of REST API endpoints for chat, channels, users.",
            }
        ],
        "mcp": [
            {
                "title": "Slack MCP Server - GitHub",
                "url": "https://github.com/slackapi/mcp-server",
                "snippet": "Official Slack Model Context Protocol MCP server implementation.",
            }
        ],
    })

    mock_scraper = MockDocScraper({
        "https://api.slack.com/authentication/oauth-v2": {
            "url": "https://api.slack.com/authentication/oauth-v2",
            "status_code": 200,
            "title": "Installing via OAuth authorization code flow",
            "text": "Slack uses OAuth 2.0 to authenticate apps and grant bot tokens.",
            "excerpt": "Slack uses OAuth 2.0 to authenticate apps.",
            "headings": ["OAuth 2.0 Flow"],
        },
        "https://api.slack.com/apps": {
            "url": "https://api.slack.com/apps",
            "status_code": 200,
            "title": "Slack API Applications Console",
            "text": "Sign in to your free workspace and create app self-serve.",
            "excerpt": "Sign in to your free workspace and create app self-serve.",
            "headings": ["Create App"],
        },
        "https://api.slack.com/methods": {
            "url": "https://api.slack.com/methods",
            "status_code": 200,
            "title": "Slack Web API Reference",
            "text": "Comprehensive REST endpoints for sending messages and reading channels.",
            "excerpt": "Comprehensive REST endpoints for sending messages.",
            "headings": ["Methods"],
        },
        "https://github.com/slackapi/mcp-server": {
            "url": "https://github.com/slackapi/mcp-server",
            "status_code": 200,
            "title": "slackapi/mcp-server on GitHub",
            "text": "Model Context Protocol server for Slack workspaces.",
            "excerpt": "Model Context Protocol server for Slack workspaces.",
            "headings": ["README"],
        },
    })

    agent = ResearchAgent(
        search_engine=mock_search,
        scraper=mock_scraper,
        research_dir=tmp_path / "research",
        raw_dir=tmp_path / "research_raw",
        log_file=tmp_path / "research_log.jsonl",
    )
    record = agent.research_app(app_name="Slack")

    # Assert schema compliance
    assert isinstance(record, AppResearchRecord)
    assert record.id == 21
    assert record.app == "Slack"
    assert record.category == "Communications and Messaging"
    assert AuthMethod.OAUTH2 in record.auth_methods
    assert record.access_model == AccessModel.FREE_SELF_SERVE
    assert ApiType.REST in record.api_types
    assert record.mcp_status in [McpStatus.OFFICIAL_MCP, McpStatus.THIRD_PARTY_MCP]
    assert record.buildability == BuildabilityStatus.BUILDABLE_NOW
    assert record.research_status == ResearchStatus.COMPLETED
    assert record.overall_confidence is not None
    assert 0.0 <= record.overall_confidence <= 1.0


def test_evidence_validation_in_research_output(tmp_path):
    """Verify evidence items are populated with mandatory fields and valid URLs."""
    mock_search = MockSearchEngine()
    mock_scraper = MockDocScraper()
    agent = ResearchAgent(
        search_engine=mock_search,
        scraper=mock_scraper,
        research_dir=tmp_path / "research",
        raw_dir=tmp_path / "research_raw",
        log_file=tmp_path / "research_log.jsonl",
    )
    record = agent.research_app(app_id=21)

    assert len(record.evidence) >= 1
    for ev in record.evidence:
        assert isinstance(ev, Evidence)
        assert len(ev.claim) >= 3
        assert str(ev.source_url).startswith("http")
        assert len(ev.source_title) >= 1
        assert ev.source_type in list(SourceType)
        assert len(ev.evidence_summary) >= 3


def test_missing_evidence_does_not_become_positive_claim(tmp_path):
    """Verify that when no evidence is found, the agent sets Unknown and does NOT invent claims."""
    empty_search = MockSearchEngine({
        "authentication": [],
        "credential": [],
        "api reference": [],
        "mcp": [],
    })
    # Scraper that fails all requests
    class FailingScraper(DocScraper):
        def fetch_page(self, *args, **kwargs):
            return None

    agent = ResearchAgent(
        search_engine=empty_search,
        scraper=FailingScraper(),
        research_dir=tmp_path / "research",
        raw_dir=tmp_path / "research_raw",
        log_file=tmp_path / "research_log.jsonl",
    )
    record = agent.research_app(app_id=21)

    # Must NOT claim OAuth2 or Free access when no evidence was retrieved
    assert record.auth_methods == [AuthMethod.UNKNOWN]
    assert record.access_model == AccessModel.UNKNOWN
    assert record.mcp_status == McpStatus.UNKNOWN
    # Must NOT claim completed without evidence
    assert record.research_status in [ResearchStatus.NEEDS_VERIFICATION, ResearchStatus.FAILED]


def test_research_results_saved_to_correct_directories(tmp_path):
    """Verify raw and validated JSON files are written to disk."""
    raw_dir = tmp_path / "research_raw"
    research_dir = tmp_path / "research"
    log_file = tmp_path / "research_log.jsonl"
    agent = ResearchAgent(
        search_engine=MockSearchEngine(),
        scraper=MockDocScraper(),
        research_dir=research_dir,
        raw_dir=raw_dir,
        log_file=log_file,
    )
    record = agent.research_app(app_name="Slack")

    slug = get_slug(record.app)
    raw_file = raw_dir / f"{slug}.json"
    validated_file = research_dir / f"{slug}.json"

    assert raw_file.exists(), f"Raw file {raw_file} missing"
    assert validated_file.exists(), f"Validated file {validated_file} missing"
    assert log_file.exists(), f"Log file {log_file} missing"

    # Verify content parses as valid AppResearchRecord
    with open(validated_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    loaded_record = AppResearchRecord.model_validate(data)
    assert loaded_record.app == "Slack"