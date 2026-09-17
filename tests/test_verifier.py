"""
AI Product Ops Research System - Hardened Verification Tests
============================================================
Deterministic unit test suite for the Automated Verification Loop (verification/verifier.py).

Covers all 15 required hardening tests:
1. HTTP 200 but claim absent -> Insufficient Evidence
2. OAuth page but no evidence of Personal Access Token -> PAT not Verified
3. API page exists but doesn't mention GraphQL -> GraphQL not Verified
4. MCP page absent -> not automatically Verified
5. Third-party MCP cannot become Official MCP
6. No MCP Found requires deliberate search coverage
7. Slack-specific logic is absent from generic verifier
8. Free developer page alone does not automatically prove Free Self-Serve
9. Rate limits are not a Hard Blocker
10. Missing API evidence prevents Buildable Now
11. MCP absence does not prevent Buildable Now when API evidence is sufficient
12. Contradictory evidence produces Contradicted
13. Original research files remain untouched
14. Corrected values always have supporting evidence
15. Accuracy metrics calculated mathematically correctly
"""

import ast
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import pytest

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
    VerificationStatus,
)
from verification.models import (
    BlockerSeverity,
    ClaimVerificationStatus,
    FieldVerificationResult,
    AppVerificationRecord,
    VerificationMetrics,
)
from verification.verifier import VerificationAgent
from agent.search import SearchEngine
from agent.scraper import DocScraper


class MockSearch(SearchEngine):
    def __init__(self, responses: Optional[Dict[str, List[Dict[str, str]]]] = None):
        super().__init__()
        self.responses = responses or {}

    def search(self, query: str, max_results: int = 5, target_domains=None):
        for k, v in self.responses.items():
            if k.lower() in query.lower():
                return v[:max_results]
        return []


class MockScraper(DocScraper):
    def __init__(self, pages: Optional[Dict[str, Dict[str, Any]]] = None):
        super().__init__()
        self.pages = pages or {}

    def fetch_page(self, url: str, fallback_snippet: str = "", **kwargs):
        clean_target = url.rstrip("/")
        for k, v in self.pages.items():
            if k.rstrip("/") == clean_target:
                return v
        return {
            "url": url,
            "status_code": 200,
            "title": "Verified Official Slack Developer Page",
            "text": (
                "Official Slack documentation text confirming OAuth2 authorization code flow and Bearer Token authentication. "
                "Explore public REST API methods and client SDK libraries. "
                "Official Slack Model Context Protocol MCP server support is available. "
                "Sign up for free workspace to create an app self-serve."
            ),
            "excerpt": "Official Slack documentation text.",
            "headings": ["Slack Developer Documentation"],
        }


def make_test_record(
    access_model: AccessModel = AccessModel.UNKNOWN,
    access_conf: float = 0.3,
    mcp_status: McpStatus = McpStatus.OFFICIAL_MCP,
    api_types: Optional[List[ApiType]] = None,
    auth_methods: Optional[List[AuthMethod]] = None,
    evidence: Optional[List[Evidence]] = None,
) -> AppResearchRecord:
    """Helper to instantiate a standard research record for verification tests."""
    if evidence is None:
        evidence = [
            Evidence(
                claim="Slack supports authentication via OAuth2 and Bearer Token.",
                source_url="https://docs.slack.dev/authentication/",
                source_title="Authentication overview",
                source_type=SourceType.OFFICIAL_AUTH_DOCS,
                evidence_summary="OAuth 2.0 flow supported.",
                checked_at=datetime.now(timezone.utc),
            ),
            Evidence(
                claim="Slack provides comprehensive public REST API methods and developer SDK integrations.",
                source_url="https://docs.slack.dev/apis/",
                source_title="Slack Web API",
                source_type=SourceType.OFFICIAL_API_REF,
                evidence_summary="Extensive REST endpoints and client SDK libraries.",
                checked_at=datetime.now(timezone.utc),
            ),
            Evidence(
                claim="Slack provides official Model Context Protocol (MCP) server support.",
                source_url="https://docs.slack.dev/ai/mcp-overview/",
                source_title="Guide to Model Context Protocol in Slack",
                source_type=SourceType.OFFICIAL_MCP_DOCS,
                evidence_summary="You can use the Slack MCP server to connect AI tools to Slack.",
                checked_at=datetime.now(timezone.utc),
            ),
        ]

    return AppResearchRecord(
        id=21,
        app="Slack",
        category="Communications and Messaging",
        website="https://slack.dev",
        one_line_description="Developer Hub: Leading platform in Communications and Messaging.",
        auth_methods=auth_methods or [AuthMethod.OAUTH2, AuthMethod.BEARER_TOKEN],
        access_model=access_model,
        credential_access_notes="Credential access model could not be verified.",
        api_types=api_types or [ApiType.REST, ApiType.SDK],
        api_breadth=ApiBreadth.BROAD,
        api_scope_notes="Extensive API covering messaging.",
        mcp_status=mcp_status,
        mcp_notes="Official MCP server available.",
        buildability=BuildabilityStatus.BUILDABLE_WITH_RESTRICTIONS,
        main_blocker="Standard developer rate limits.",
        evidence=evidence,
        auth_confidence=0.95,
        access_confidence=access_conf,
        api_confidence=0.9,
        mcp_confidence=0.95,
        buildability_confidence=0.8,
        overall_confidence=0.78,
        researched_at=datetime.now(timezone.utc),
        researcher_version="1.0.0",
        research_status=ResearchStatus.COMPLETED,
        verification_status=VerificationStatus.NOT_VERIFIED,
    )


# ==============================================================================
# 15 HARDENED VERIFICATION TESTS
# ==============================================================================


def test_1_http_200_without_claim_evidence_yields_insufficient_evidence(tmp_path):
    """TEST 1: HTTP 200 alone does not prove claim; content must support claim."""
    generic_scraper = MockScraper({
        "https://docs.slack.dev/authentication/": {
            "url": "https://docs.slack.dev/authentication/",
            "status_code": 200,
            "title": "Welcome to Company Portal",
            "text": "This is a generic landing page for company announcements and marketing.",
            "excerpt": "Generic landing page.",
            "headings": ["Announcements"],
        }
    })
    verifier = VerificationAgent(
        search_engine=MockSearch(),
        scraper=generic_scraper,
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record(auth_methods=[AuthMethod.OAUTH2])
    res = verifier.verify_app(record=record)

    # Page was 200 but content lacks OAuth2 proof
    assert res.field_results["authentication"].verification_status == ClaimVerificationStatus.INSUFFICIENT_EVIDENCE


def test_2_oauth_page_without_pat_does_not_verify_pat(tmp_path):
    """TEST 2: OAuth page without Personal Access Token evidence must NOT verify PAT."""
    oauth_only_scraper = MockScraper({
        "https://docs.slack.dev/authentication/": {
            "url": "https://docs.slack.dev/authentication/",
            "status_code": 200,
            "title": "Authentication Overview",
            "text": "Slack uses OAuth 2.0 authorization code flow for app security. Sign in with Slack.",
            "excerpt": "Slack uses OAuth 2.0.",
            "headings": ["OAuth 2.0"],
        }
    })
    verifier = VerificationAgent(
        search_engine=MockSearch(),
        scraper=oauth_only_scraper,
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record(auth_methods=[AuthMethod.OAUTH2, AuthMethod.PERSONAL_ACCESS_TOKEN])
    res = verifier.verify_app(record=record)

    auth_res = res.field_results["authentication"]
    assert auth_res.auth_details is not None

    pat_detail = next(d for d in auth_res.auth_details if d.method == "Personal Access Token")
    assert pat_detail.verification_status == ClaimVerificationStatus.INSUFFICIENT_EVIDENCE

    oauth_detail = next(d for d in auth_res.auth_details if d.method == "OAuth2")
    assert oauth_detail.verification_status == ClaimVerificationStatus.VERIFIED

    # Verified record has PAT removed
    assert AuthMethod.PERSONAL_ACCESS_TOKEN not in res.verified_record.auth_methods
    assert AuthMethod.OAUTH2 in res.verified_record.auth_methods


def test_3_api_page_without_graphql_does_not_verify_graphql(tmp_path):
    """TEST 3: API documentation that only mentions REST must NOT verify GraphQL."""
    rest_only_scraper = MockScraper({
        "https://docs.slack.dev/apis/": {
            "url": "https://docs.slack.dev/apis/",
            "status_code": 200,
            "title": "Slack Web API Reference",
            "text": "Comprehensive REST endpoints for sending messages, reading channels, and user CRUD.",
            "excerpt": "Comprehensive REST endpoints.",
            "headings": ["Methods"],
        }
    })
    verifier = VerificationAgent(
        search_engine=MockSearch(),
        scraper=rest_only_scraper,
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record(api_types=[ApiType.REST, ApiType.GRAPHQL])
    res = verifier.verify_app(record=record)

    api_res = res.field_results["api_surface"]
    assert api_res.api_type_details is not None
    assert api_res.api_type_details["GraphQL"] == ClaimVerificationStatus.INSUFFICIENT_EVIDENCE
    assert api_res.api_type_details["REST"] == ClaimVerificationStatus.VERIFIED
    assert ApiType.GRAPHQL not in res.verified_record.api_types
    assert ApiType.REST in res.verified_record.api_types


def test_4_mcp_page_absent_does_not_verify_mcp(tmp_path):
    """TEST 4: Missing or unreachable MCP page must NOT automatically verify Official MCP."""
    missing_mcp_scraper = MockScraper({
        "https://docs.slack.dev/ai/mcp-overview/": {
            "url": "https://docs.slack.dev/ai/mcp-overview/",
            "status_code": 404,
            "title": "Not Found",
            "text": "The requested URL was not found on this server.",
            "excerpt": "Not found.",
            "headings": ["404 Not Found"],
        }
    })
    verifier = VerificationAgent(
        search_engine=MockSearch(),
        scraper=missing_mcp_scraper,
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record(mcp_status=McpStatus.OFFICIAL_MCP)
    res = verifier.verify_app(record=record)

    mcp_res = res.field_results["mcp_status"]
    assert mcp_res.verification_status == ClaimVerificationStatus.INSUFFICIENT_EVIDENCE
    assert mcp_res.was_corrected is False


def test_5_third_party_mcp_cannot_become_official_mcp(tmp_path):
    """TEST 5: Third-party community MCP implementation cannot be verified as Official MCP."""
    third_party_scraper = MockScraper({
        "https://github.com/community-dev/slack-mcp-wrapper": {
            "url": "https://github.com/community-dev/slack-mcp-wrapper",
            "status_code": 200,
            "title": "community-dev/slack-mcp-wrapper",
            "text": "Unofficial third-party community Model Context Protocol MCP server implementation for Slack.",
            "excerpt": "Community MCP wrapper.",
            "headings": ["Community MCP"],
        }
    })
    mock_search = MockSearch({
        "mcp server": [
            {
                "title": "community-dev/slack-mcp-wrapper",
                "url": "https://github.com/community-dev/slack-mcp-wrapper",
                "snippet": "Community MCP server wrapper.",
            }
        ]
    })
    verifier = VerificationAgent(
        search_engine=mock_search,
        scraper=third_party_scraper,
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record(mcp_status=McpStatus.OFFICIAL_MCP)
    # Give it third-party evidence URL
    record.evidence[2] = Evidence(
        claim="Community MCP server available.",
        source_url="https://github.com/community-dev/slack-mcp-wrapper",
        source_title="Community MCP",
        source_type=SourceType.GITHUB,
        evidence_summary="Community wrapper.",
        checked_at=datetime.now(timezone.utc),
    )
    res = verifier.verify_app(record=record)

    mcp_res = res.field_results["mcp_status"]
    # Cannot remain Official MCP! Must be corrected to Third-Party MCP
    assert mcp_res.was_corrected is True
    assert mcp_res.corrected_value == McpStatus.THIRD_PARTY_MCP
    assert res.verified_record.mcp_status == McpStatus.THIRD_PARTY_MCP


def test_6_no_mcp_found_requires_deliberate_search_coverage(tmp_path):
    """TEST 6: 'No MCP Found' is verified only when deliberate search yields zero MCP hits."""
    verifier = VerificationAgent(
        search_engine=MockSearch(),  # returns empty list for searches
        scraper=MockScraper(),
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record(mcp_status=McpStatus.NO_MCP_FOUND)
    # Remove MCP evidence
    record.evidence = [e for e in record.evidence if "mcp" not in e.claim.lower()]

    res = verifier.verify_app(record=record)
    mcp_res = res.field_results["mcp_status"]
    assert mcp_res.verification_status == ClaimVerificationStatus.VERIFIED
    assert "Deliberate search" in mcp_res.verification_notes


def test_7_slack_specific_logic_absent_from_generic_verifier(tmp_path):
    """TEST 7: Inspect source code to guarantee zero app-specific hardcoding in verifier."""
    verifier_path = Path("verification/verifier.py")
    with open(verifier_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    # Check for any hardcoded string comparisons against "slack"
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and comparator.value == "slack":
                    pytest.fail("Hardcoded 'slack' string comparison found in verification/verifier.py")

    # Also test on non-Slack app (e.g. HubSpot)
    hubspot_scraper = MockScraper({
        "https://developers.hubspot.com": {
            "url": "https://developers.hubspot.com",
            "status_code": 200,
            "title": "HubSpot Developer Portal",
            "text": "HubSpot developer documentation with OAuth 2.0 and REST API endpoints. Sign up for free.",
            "excerpt": "HubSpot APIs.",
            "headings": ["HubSpot"],
        }
    })
    hubspot_record = make_test_record()
    hubspot_record.app = "HubSpot"
    hubspot_record.id = 2
    hubspot_record.website = "https://developers.hubspot.com"
    verifier = VerificationAgent(
        search_engine=MockSearch(),
        scraper=hubspot_scraper,
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    res = verifier.verify_app(record=hubspot_record)
    assert res.field_results["website"].verification_status == ClaimVerificationStatus.VERIFIED


def test_8_free_developer_page_alone_does_not_prove_free_self_serve(tmp_path):
    """TEST 8: A public developer landing page without signup/pricing evidence does NOT prove Free Self-Serve."""
    vague_portal_scraper = MockScraper({
        "https://docs.slack.dev/portal": {
            "url": "https://docs.slack.dev/portal",
            "status_code": 200,
            "title": "Developer Portal Overview",
            "text": "Welcome to the developer portal. Here you can read documentation about our APIs.",
            "excerpt": "Developer portal overview.",
            "headings": ["Portal"],
        }
    })
    verifier = VerificationAgent(
        search_engine=MockSearch(),
        scraper=vague_portal_scraper,
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record(access_model=AccessModel.FREE_SELF_SERVE)
    res = verifier.verify_app(record=record)

    access_res = res.field_results["access_model"]
    assert access_res.verification_status == ClaimVerificationStatus.INSUFFICIENT_EVIDENCE


def test_9_rate_limits_are_classified_as_restriction_not_hard_blocker(tmp_path):
    """TEST 9: Standard rate limits are classified as developer Restriction, NOT Hard Blocker."""
    verifier = VerificationAgent(
        search_engine=MockSearch(),
        scraper=MockScraper(),
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record(
        access_model=AccessModel.FREE_SELF_SERVE,
        access_conf=0.95,
    )
    record.main_blocker = "Standard developer rate limits of 100 requests per minute."
    res = verifier.verify_app(record=record)

    build_res = res.field_results["buildability"]
    assert build_res.blocker_severity == BlockerSeverity.RESTRICTION
    assert res.verified_record.buildability == BuildabilityStatus.BUILDABLE_NOW


def test_10_missing_api_evidence_prevents_buildable_now(tmp_path):
    """TEST 10: Missing public API documentation prevents classification as Buildable Now."""
    failing_api_scraper = MockScraper({
        "https://docs.slack.dev/apis/": {
            "url": "https://docs.slack.dev/apis/",
            "status_code": 404,
            "title": "Not Found",
            "text": "API docs not found.",
        }
    })
    verifier = VerificationAgent(
        search_engine=MockSearch(),
        scraper=failing_api_scraper,
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record(
        access_model=AccessModel.FREE_SELF_SERVE,
        access_conf=0.95,
    )
    # Strip API evidence
    record.evidence = [e for e in record.evidence if "api" not in e.claim.lower()]

    res = verifier.verify_app(record=record)
    build_res = res.field_results["buildability"]
    assert build_res.verification_status == ClaimVerificationStatus.INSUFFICIENT_EVIDENCE
    assert res.verified_record.buildability != BuildabilityStatus.BUILDABLE_NOW


def test_11_mcp_absence_does_not_prevent_buildable_now_when_api_sufficient(tmp_path):
    """TEST 11: MCP absence does NOT prevent Buildable Now if public REST APIs and self-serve exist."""
    verifier = VerificationAgent(
        search_engine=MockSearch(),
        scraper=MockScraper(),
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record(
        access_model=AccessModel.FREE_SELF_SERVE,
        access_conf=0.95,
        mcp_status=McpStatus.NO_MCP_FOUND,
    )
    # Remove MCP evidence
    record.evidence = [e for e in record.evidence if "mcp" not in e.claim.lower()]

    res = verifier.verify_app(record=record)
    build_res = res.field_results["buildability"]
    assert build_res.verification_status == ClaimVerificationStatus.VERIFIED
    assert res.verified_record.buildability == BuildabilityStatus.BUILDABLE_NOW


def test_12_contradictory_evidence_produces_contradicted(tmp_path):
    """TEST 12: Documentation that explicitly contradicts a claim produces Contradicted status."""
    contradicting_scraper = MockScraper({
        "https://docs.slack.dev/apis/": {
            "url": "https://docs.slack.dev/apis/",
            "status_code": 200,
            "title": "API Status",
            "text": "We do not offer a public REST API. All access is private.",
            "excerpt": "No rest api.",
            "headings": ["APIs"],
        }
    })
    verifier = VerificationAgent(
        search_engine=MockSearch(),
        scraper=contradicting_scraper,
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record(api_types=[ApiType.REST])
    res = verifier.verify_app(record=record)

    api_res = res.field_results["api_surface"]
    assert api_res.api_type_details["REST"] == ClaimVerificationStatus.CONTRADICTED


def test_13_original_research_files_remain_untouched(tmp_path):
    """TEST 13: Verifier must never overwrite or modify data/research/ or data/research_raw/."""
    fake_research_dir = tmp_path / "research"
    fake_raw_dir = tmp_path / "research_raw"
    fake_verif_dir = tmp_path / "verification"
    fake_metrics = tmp_path / "metrics.json"
    fake_research_dir.mkdir()
    fake_raw_dir.mkdir()
    fake_verif_dir.mkdir()

    raw_file = fake_raw_dir / "slack.json"
    raw_file.write_text('{"id": 21, "raw": true}', encoding="utf-8")
    research_file = fake_research_dir / "slack.json"
    research_file.write_text('{"id": 21, "first_pass": true}', encoding="utf-8")

    mtime_raw_before = raw_file.stat().st_mtime
    mtime_res_before = research_file.stat().st_mtime

    verifier = VerificationAgent(
        search_engine=MockSearch(),
        scraper=MockScraper(),
        verification_dir=fake_verif_dir,
        metrics_file=fake_metrics,
        research_dir=fake_research_dir,
    )
    record = make_test_record()
    res = verifier.verify_app(record=record)

    assert (fake_verif_dir / "slack.json").exists()
    assert raw_file.stat().st_mtime == mtime_raw_before
    assert research_file.stat().st_mtime == mtime_res_before
    assert research_file.read_text(encoding="utf-8") == '{"id": 21, "first_pass": true}'


def test_14_corrected_values_always_have_supporting_evidence(tmp_path):
    """TEST 14: Whenever was_corrected is True, supporting primary evidence must be attached."""
    mock_search = MockSearch({
        "developer signup": [
            {
                "title": "Slack API: Applications",
                "url": "https://api.slack.com/apps",
                "snippet": "Sign in to create an app in your free workspace.",
            }
        ]
    })
    mock_scraper = MockScraper({
        "https://api.slack.com/apps": {
            "url": "https://api.slack.com/apps",
            "status_code": 200,
            "title": "Slack API: Applications",
            "text": "Sign in to create an app in your free workspace. Sign up for free.",
            "excerpt": "Sign in to create an app.",
            "headings": ["Apps"],
        }
    })
    verifier = VerificationAgent(
        search_engine=mock_search,
        scraper=mock_scraper,
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record(access_model=AccessModel.UNKNOWN, access_conf=0.3)
    res = verifier.verify_app(record=record)

    access_res = res.field_results["access_model"]
    assert access_res.was_corrected is True
    assert access_res.corrected_value == AccessModel.FREE_SELF_SERVE
    assert len(access_res.evidence) >= 1
    for ev in access_res.evidence:
        assert isinstance(ev, Evidence)
        assert str(ev.source_url).startswith("http")
        assert len(ev.claim) > 0


def test_15_accuracy_metrics_calculated_correctly(tmp_path):
    """TEST 15: Accuracy metrics formula mathematically checks first pass vs post verification."""
    verifier = VerificationAgent(
        verification_dir=tmp_path / "verif",
        metrics_file=tmp_path / "metrics.json",
    )
    record = make_test_record()

    field_results = {
        "auth": FieldVerificationResult(
            app_id=1, app="App1", field="auth", original_value="OAuth2",
            verification_status=ClaimVerificationStatus.VERIFIED,
            was_corrected=False, verifier_confidence=0.95, verification_notes="OK"
        ),
        "access": FieldVerificationResult(
            app_id=1, app="App1", field="access", original_value="Unknown",
            verification_status=ClaimVerificationStatus.VERIFIED,
            corrected_value="Free Self-Serve", was_corrected=True,
            verifier_confidence=0.9, verification_notes="Corrected with proof"
        ),
        "api": FieldVerificationResult(
            app_id=1, app="App1", field="api", original_value="REST",
            verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
            was_corrected=False, verifier_confidence=0.5, verification_notes="Unreachable"
        ),
    }

    v_rec = AppVerificationRecord(
        app_id=1,
        app="App1",
        category="CRM",
        verified_at=datetime.now(timezone.utc),
        overall_verification_status=VerificationStatus.PARTIALLY_VERIFIED,
        claims_checked=3,
        claims_verified=2,
        claims_contradicted=0,
        claims_insufficient_evidence=1,
        corrections_made=1,
        field_results=field_results,
        original_record=record,
        verified_record=record,
        summary_notes="Test",
    )

    metrics = verifier.calculate_metrics([v_rec])
    assert metrics.total_apps_verified == 1
    assert metrics.total_claims_checked == 3
    assert metrics.total_verified == 2
    # 1 of 3 verified on first pass without correction = 33.3%
    assert metrics.first_pass_accuracy == 33.3
    # 2 of 3 verified after evidence-backed correction = 66.7%
    assert metrics.post_verification_accuracy == 66.7
    assert metrics.total_insufficient_evidence == 1
    assert "Pilot phase" in metrics.sample_size_note
