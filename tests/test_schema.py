"""
Unit tests for Pydantic research schema (agent/schema.py).

Validates:
1. Valid records are accepted (both pending and completed).
2. Invalid confidence values (< 0.0 or > 1.0) are rejected.
3. Invalid enum values are strictly rejected.
4. Invalid URLs (malformed or invalid scheme) are rejected.
5. Empty evidence is allowed for Pending records.
6. A completed record can contain multiple evidence items (and requires at least one).
7. "No MCP Found" and "Unknown" are strictly distinct values.
8. Extra undeclared fields are forbidden.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from pydantic import ValidationError

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
    create_empty_record,
)

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_JSON_PATH = BASE_DIR / "data" / "sample_pending_record.json"


# ==============================================================================
# 1. VALID RECORD ACCEPTANCE TESTS
# ==============================================================================


def test_valid_pending_record_accepted():
    """Verify an empty/pending record passes strict validation."""
    record = create_empty_record(
        app_id=1,
        app_name="Salesforce",
        category="CRM and Sales",
        website="https://www.salesforce.com",
    )
    assert record.id == 1
    assert record.app == "Salesforce"
    assert record.category == "CRM and Sales"
    assert str(record.website) == "https://www.salesforce.com/"
    assert record.research_status == ResearchStatus.PENDING
    assert record.verification_status == VerificationStatus.NOT_VERIFIED
    assert len(record.evidence) == 0


def test_sample_pending_json_file_validates():
    """Verify that data/sample_pending_record.json passes validation."""
    assert SAMPLE_JSON_PATH.exists(), f"Sample file not found at {SAMPLE_JSON_PATH}"
    with open(SAMPLE_JSON_PATH, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    record = AppResearchRecord.model_validate(data)
    assert record.id == 1
    assert record.app == "Salesforce"
    assert record.research_status == ResearchStatus.PENDING
    assert record.verification_status == VerificationStatus.NOT_VERIFIED


def test_valid_completed_record_accepted():
    """Verify a thoroughly researched completed record is accepted."""
    record = AppResearchRecord(
        id=71,
        app="Notion",
        category="Productivity and Project Management",
        website="https://www.notion.so",
        one_line_description="All-in-one workspace for notes, docs, and project management.",
        auth_methods=[AuthMethod.OAUTH2, AuthMethod.BEARER_TOKEN],
        access_model=AccessModel.FREE_SELF_SERVE,
        credential_access_notes="Internal integrations can be created instantly in developer portal.",
        api_types=[ApiType.REST, ApiType.WEBHOOKS],
        api_breadth=ApiBreadth.BROAD,
        api_scope_notes="Extensive API covering databases, pages, blocks, and users.",
        mcp_status=McpStatus.THIRD_PARTY_MCP,
        mcp_notes="Multiple community MCP servers available on GitHub.",
        buildability=BuildabilityStatus.BUILDABLE_NOW,
        main_blocker=None,
        evidence=[
            Evidence(
                claim="Notion supports OAuth2 and Bearer token auth.",
                source_url="https://developers.notion.com/docs/authorization",
                source_title="Notion Authorization Guide",
                source_type=SourceType.OFFICIAL_AUTH_DOCS,
                evidence_summary="Notion supports both internal integrations using bearer tokens and public OAuth2.",
                checked_at=datetime.now(timezone.utc),
            )
        ],
        auth_confidence=0.95,
        access_confidence=0.9,
        api_confidence=0.9,
        mcp_confidence=0.85,
        buildability_confidence=0.9,
        overall_confidence=0.9,
        researched_at=datetime.now(timezone.utc),
        researcher_version="1.0.0",
        research_status=ResearchStatus.COMPLETED,
        verification_status=VerificationStatus.NOT_VERIFIED,
    )
    assert record.app == "Notion"
    assert record.research_status == ResearchStatus.COMPLETED
    assert len(record.evidence) == 1


# ==============================================================================
# 2. CONFIDENCE VALUE BOUNDARY TESTS
# ==============================================================================


@pytest.mark.parametrize("invalid_val", [-0.01, -1.0, 1.01, 2.5, 100.0])
def test_invalid_confidence_values_rejected(invalid_val):
    """Verify confidence floats outside [0.0, 1.0] raise ValidationError."""
    with pytest.raises(ValidationError):
        AppResearchRecord(
            id=1,
            app="TestApp",
            category="CRM and Sales",
            overall_confidence=invalid_val,
        )

    with pytest.raises(ValidationError):
        AppResearchRecord(
            id=1,
            app="TestApp",
            category="CRM and Sales",
            auth_confidence=invalid_val,
        )


@pytest.mark.parametrize("valid_val", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_valid_confidence_boundaries_accepted(valid_val):
    """Verify confidence floats exactly at 0.0, 1.0, and intermediate values are valid."""
    record = AppResearchRecord(
        id=1,
        app="TestApp",
        category="CRM and Sales",
        overall_confidence=valid_val,
        auth_confidence=valid_val,
    )
    assert record.overall_confidence == valid_val
    assert record.auth_confidence == valid_val


# ==============================================================================
# 3. ENUM INTEGRITY TESTS
# ==============================================================================


def test_invalid_auth_method_rejected():
    """Verify invalid auth method values are rejected."""
    with pytest.raises(ValidationError):
        AppResearchRecord(
            id=1,
            app="TestApp",
            category="CRM and Sales",
            auth_methods=["FingerprintAuth"],
        )


def test_invalid_access_model_rejected():
    """Verify invalid access model values are rejected."""
    with pytest.raises(ValidationError):
        AppResearchRecord(
            id=1,
            app="TestApp",
            category="CRM and Sales",
            access_model="Totally Free Forever",
        )


def test_invalid_api_type_rejected():
    """Verify invalid API type values are rejected."""
    with pytest.raises(ValidationError):
        AppResearchRecord(
            id=1,
            app="TestApp",
            category="CRM and Sales",
            api_types=["CORBA"],
        )


def test_invalid_mcp_status_rejected():
    """Verify invalid MCP status values are rejected."""
    with pytest.raises(ValidationError):
        AppResearchRecord(
            id=1,
            app="TestApp",
            category="CRM and Sales",
            mcp_status="Has MCP Somewhere",
        )


def test_invalid_source_type_rejected():
    """Verify invalid evidence source type values are rejected."""
    with pytest.raises(ValidationError):
        Evidence(
            claim="Valid claim",
            source_url="https://example.com/docs",
            source_title="Example Docs",
            source_type="Reddit Thread",
            evidence_summary="Some claim summary",
        )


# ==============================================================================
# 4. URL VALIDATION TESTS
# ==============================================================================


@pytest.mark.parametrize(
    "bad_url",
    [
        "not_a_url",
        "ftp://example.com/file",
        "htp://typo.com",
        "www.missing-scheme.com",
        "://missing-host",
    ],
)
def test_invalid_website_urls_rejected(bad_url):
    """Verify malformed website URLs are rejected."""
    with pytest.raises(ValidationError):
        AppResearchRecord(
            id=1,
            app="TestApp",
            category="CRM and Sales",
            website=bad_url,
        )


@pytest.mark.parametrize(
    "bad_url",
    [
        "just-some-text",
        "file:///C:/path/to/local/file",
        "http://",
    ],
)
def test_invalid_evidence_source_url_rejected(bad_url):
    """Verify invalid source URLs in Evidence objects are rejected."""
    with pytest.raises(ValidationError):
        Evidence(
            claim="Valid claim",
            source_url=bad_url,
            source_title="Docs",
            source_type=SourceType.OFFICIAL_DOCS,
            evidence_summary="Valid summary",
        )


def test_empty_string_website_converts_to_none():
    """Verify empty string website gracefully converts to None."""
    record = AppResearchRecord(
        id=1,
        app="TestApp",
        category="CRM and Sales",
        website="",
    )
    assert record.website is None


# ==============================================================================
# 5. EVIDENCE & STATUS RELATIONSHIP TESTS
# ==============================================================================


def test_empty_evidence_allowed_for_pending_records():
    """Verify that a Pending record is explicitly allowed to have empty evidence."""
    record = create_empty_record(app_id=1, app_name="App", category="Cat")
    assert record.research_status == ResearchStatus.PENDING
    assert len(record.evidence) == 0


def test_completed_record_without_evidence_rejected():
    """Verify that completing a record without evidence citations fails validation."""
    with pytest.raises(ValidationError) as excinfo:
        AppResearchRecord(
            id=1,
            app="TestApp",
            category="CRM and Sales",
            research_status=ResearchStatus.COMPLETED,
            evidence=[],
        )
    assert "Completed research record cannot have an empty evidence list" in str(
        excinfo.value
    )


def test_completed_record_can_contain_multiple_evidence_items():
    """Verify that multiple evidence items across different source types are stored."""
    ev1 = Evidence(
        claim="Supports OAuth 2.0 and API Keys",
        source_url="https://api.example.com/docs/auth",
        source_title="Example Auth Docs",
        source_type=SourceType.OFFICIAL_AUTH_DOCS,
        evidence_summary="All requests require an Authorization header with Bearer token.",
    )
    ev2 = Evidence(
        claim="Free tier includes 1,000 monthly API calls",
        source_url="https://example.com/pricing",
        source_title="Example Pricing",
        source_type=SourceType.OFFICIAL_PRICING_DOCS,
        evidence_summary="Free developer plan available with 1k calls/mo.",
    )
    ev3 = Evidence(
        claim="Official MCP server published on GitHub",
        source_url="https://github.com/example/mcp-server",
        source_title="Example MCP Repository",
        source_type=SourceType.GITHUB,
        evidence_summary="Reference Model Context Protocol server implementation.",
    )

    record = AppResearchRecord(
        id=1,
        app="ExampleApp",
        category="Developer, Infra and Data platforms",
        research_status=ResearchStatus.COMPLETED,
        evidence=[ev1, ev2, ev3],
    )
    assert len(record.evidence) == 3
    assert record.evidence[0].source_type == SourceType.OFFICIAL_AUTH_DOCS
    assert record.evidence[1].source_type == SourceType.OFFICIAL_PRICING_DOCS
    assert record.evidence[2].source_type == SourceType.GITHUB


# ==============================================================================
# 6. "NO MCP FOUND" VS "UNKNOWN" DISTINCTION TEST
# ==============================================================================


def test_no_mcp_found_and_unknown_are_distinct():
    """Verify 'No MCP Found' and 'Unknown' are distinct enums with clear semantics.

    - 'No MCP Found': Search was executed, no MCP was discovered.
    - 'Unknown': Insufficient evidence / search not yet performed.
    """
    assert McpStatus.NO_MCP_FOUND != McpStatus.UNKNOWN
    assert McpStatus.NO_MCP_FOUND.value == "No MCP Found"
    assert McpStatus.UNKNOWN.value == "Unknown"

    rec1 = create_empty_record(app_id=1, app_name="App1", category="Cat")
    assert rec1.mcp_status == McpStatus.UNKNOWN

    rec2 = AppResearchRecord(
        id=2,
        app="App2",
        category="Cat",
        mcp_status=McpStatus.NO_MCP_FOUND,
        mcp_notes="Searched GitHub, MCP registry, and official documentation. Zero MCP implementations exist.",
    )
    assert rec2.mcp_status == McpStatus.NO_MCP_FOUND
    assert rec1.mcp_status != rec2.mcp_status


# ==============================================================================
# 7. BLOCKER & BUILDABILITY CONSISTENCY TESTS
# ==============================================================================


def test_blocked_status_requires_main_blocker():
    """Verify that marking buildability as Blocked requires a main_blocker explanation."""
    with pytest.raises(ValidationError) as excinfo:
        AppResearchRecord(
            id=1,
            app="BlockedApp",
            category="Finance and Fintech",
            buildability=BuildabilityStatus.BLOCKED,
            main_blocker=None,
        )
    assert "main_blocker" in str(excinfo.value)

    # With explanation it should pass
    record = AppResearchRecord(
        id=1,
        app="BlockedApp",
        category="Finance and Fintech",
        buildability=BuildabilityStatus.BLOCKED,
        main_blocker="Requires enterprise banking license and physical hardware token.",
    )
    assert record.buildability == BuildabilityStatus.BLOCKED
    assert record.main_blocker is not None


# ==============================================================================
# 8. EXTRA FIELDS FORBIDDEN TEST
# ==============================================================================


def test_extra_fields_forbidden():
    """Verify that unmodeled arbitrary fields are rejected by strict config."""
    with pytest.raises(ValidationError):
        AppResearchRecord(
            id=1,
            app="TestApp",
            category="CRM and Sales",
            unsupported_field="arbitrary_value",
        )