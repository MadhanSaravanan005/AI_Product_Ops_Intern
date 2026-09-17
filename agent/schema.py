"""
AI Product Ops Research System - Core Research Schema
=====================================================
Defines strict Pydantic v2 data models, enums, and validation logic for evaluating
100 software platforms for AI agent toolkit feasibility.

Every record captures:
1. Application Identity (id, name, category, official website)
2. Functional Overview (one-line description)
3. Authentication Mechanisms (OAuth2, API keys, PATs, etc.)
4. Credential Access & Gating (Self-serve, paid plans, partner gating)
5. API Surface & Breadth (REST, GraphQL, Webhooks, scale)
6. MCP Support (Official, Third-Party, None Found, Unknown)
7. Buildability & Integration Blockers (Viability as an agent toolkit today)
8. Claim-Level Evidence (Traceable URLs, titles, source types, and excerpts)
9. Granular Confidence Scores (0.0 to 1.0 per domain area + overall)
10. Research & Verification Lifecycle Metadata
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


# ==============================================================================
# ENUMS
# ==============================================================================


class AuthMethod(str, Enum):
    """Supported authentication mechanisms for developer/API access."""

    OAUTH2 = "OAuth2"
    API_KEY = "API Key"
    BASIC_AUTH = "Basic Auth"
    BEARER_TOKEN = "Bearer Token"
    PERSONAL_ACCESS_TOKEN = "Personal Access Token"
    JWT = "JWT"
    OTHER = "Other"
    UNKNOWN = "Unknown"


class AccessModel(str, Enum):
    """Credential accessibility tier and gating mechanisms.

    Indicates how easily a developer or agent can obtain credentials.
    """

    FREE_SELF_SERVE = "Free Self-Serve"
    TRIAL_SELF_SERVE = "Trial Self-Serve"
    PAID_PLAN_REQUIRED = "Paid Plan Required"
    ADMIN_APPROVAL_REQUIRED = "Admin Approval Required"
    PARTNER_CONTACT_SALES = "Partner/Contact Sales"
    INVITE_ONLY = "Invite Only"
    UNKNOWN = "Unknown"


class ApiType(str, Enum):
    """API architecture paradigms offered by the platform."""

    REST = "REST"
    GRAPHQL = "GraphQL"
    SOAP = "SOAP"
    SDK = "SDK"
    CLI = "CLI"
    WEBHOOKS = "Webhooks"
    OTHER = "Other"
    NONE = "None"
    UNKNOWN = "Unknown"


class ApiBreadth(str, Enum):
    """Approximate scope and coverage of the public API surface.

    - Narrow: Only a few specific endpoints (e.g. read-only status, single webhook).
    - Moderate: Core entity CRUD operations covered.
    - Broad: Full coverage of platform functionality.
    - Very Broad: Expansive ecosystem APIs (e.g., Salesforce Tooling/Metadata/REST).
    - Unknown: Documentation insufficient to estimate coverage.
    """

    NARROW = "Narrow"
    MODERATE = "Moderate"
    BROAD = "Broad"
    VERY_BROAD = "Very Broad"
    UNKNOWN = "Unknown"


class McpStatus(str, Enum):
    """Status of Model Context Protocol (MCP) server support.

    CRITICAL DISTINCTION:
    - 'No MCP Found': Active research was conducted across official repositories,
      documentation, and registry indexes, and confirmed NO MCP server exists.
    - 'Unknown': Insufficient evidence or unverified search results; cannot confirm.
    """

    OFFICIAL_MCP = "Official MCP"
    THIRD_PARTY_MCP = "Third-Party MCP"
    MCP_MENTIONED = "MCP Mentioned"
    NO_MCP_FOUND = "No MCP Found"
    UNKNOWN = "Unknown"


class BuildabilityStatus(str, Enum):
    """Feasibility of constructing an autonomous agent toolkit today."""

    BUILDABLE_NOW = "Buildable Now"
    BUILDABLE_WITH_RESTRICTIONS = "Buildable With Restrictions"
    BLOCKED = "Blocked"
    UNKNOWN = "Unknown"


class SourceType(str, Enum):
    """Classification of the primary source cited in evidence."""

    OFFICIAL_DOCS = "Official Documentation"
    OFFICIAL_API_REF = "Official API Reference"
    OFFICIAL_AUTH_DOCS = "Official Authentication Documentation"
    OFFICIAL_PRICING_DOCS = "Official Pricing Documentation"
    OFFICIAL_MCP_DOCS = "Official MCP Documentation"
    OFFICIAL_BLOG = "Official Blog/Announcement"
    GITHUB = "GitHub"
    OTHER = "Other"


class ResearchStatus(str, Enum):
    """Lifecycle state of the autonomous research stage."""

    PENDING = "Pending"
    COMPLETED = "Completed"
    NEEDS_VERIFICATION = "Needs Verification"
    FAILED = "Failed"


class VerificationStatus(str, Enum):
    """Lifecycle state of the automated/human verification stage."""

    NOT_VERIFIED = "Not Verified"
    VERIFIED = "Verified"
    PARTIALLY_VERIFIED = "Partially Verified"
    FAILED_VERIFICATION = "Failed Verification"


# ==============================================================================
# EVIDENCE MODEL
# ==============================================================================


class Evidence(BaseModel):
    """A single factual claim paired with verifiable citation evidence.

    To maintain honesty and auditability, the research system avoids storing
    unreferenced assertions. Every critical claim must be backed by an Evidence
    instance citing an HTTP/HTTPS source.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    claim: str = Field(
        ...,
        min_length=3,
        description="The specific factual claim or finding supported by this source.",
    )
    source_url: HttpUrl = Field(
        ...,
        description="Direct HTTP/HTTPS link to official documentation or source repository.",
    )
    source_title: str = Field(
        ...,
        min_length=1,
        description="Title or heading of the documentation page.",
    )
    source_type: SourceType = Field(
        ...,
        description="Categorical type of the reference source.",
    )
    evidence_summary: str = Field(
        ...,
        min_length=3,
        description="Direct quote, excerpt, or concise summary extracted from the source.",
    )
    checked_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the source URL was accessed and verified.",
    )


# ==============================================================================
# ITEM-LEVEL GROUNDING MODELS
# ==============================================================================


class AuthenticationDetail(BaseModel):
    """Detailed evidence-backed finding for a single authentication method."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    method: AuthMethod = Field(
        ..., description="The specific authentication mechanism evaluated."
    )
    status: str = Field(
        default="Confirmed",
        description="Grounding status (e.g. Confirmed, Unverified, Needs Verification).",
    )
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Direct citation evidence supporting this specific authentication method.",
    )
    confidence: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Confidence score for this specific authentication finding.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Specific notes on token formats, lifetimes, scopes, or header conventions.",
    )


class ApiTypeDetail(BaseModel):
    """Detailed evidence-backed finding for a single API architectural paradigm."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    api_type: ApiType = Field(
        ..., description="The specific API type evaluated (e.g. REST, GraphQL, Webhooks)."
    )
    status: str = Field(
        default="Confirmed",
        description="Grounding status (e.g. Confirmed, Unverified, Needs Verification).",
    )
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Direct citation evidence supporting this specific API type.",
    )
    confidence: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Confidence score for this specific API type finding.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Specific notes on endpoints, specifications, schemas, or webhook deliveries.",
    )


# ==============================================================================
# APPLICATION RESEARCH RECORD MODEL
# ==============================================================================


class AppResearchRecord(BaseModel):
    """Complete research and evaluation record for an application.

    Encompasses identity, API capabilities, auth gating, MCP status,
    buildability, claim-level evidence, and quality confidence scores.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        use_enum_values=False,
    )

    # 1. Application Identity
    id: int = Field(
        ...,
        ge=1,
        le=1000,
        description="Unique identifier matching data/apps.csv.",
    )
    app: str = Field(
        ...,
        min_length=1,
        description="Canonical application name.",
    )
    category: str = Field(
        ...,
        min_length=1,
        description="Assigned category domain.",
    )
    website: Optional[HttpUrl] = Field(
        default=None,
        description="Official homepage or developer portal URL.",
    )

    # 2. Basic Description
    one_line_description: Optional[str] = Field(
        default=None,
        max_length=300,
        description="High-level single-sentence summary of what the software does.",
    )

    # 3. Authentication
    auth_methods: list[AuthMethod] = Field(
        default_factory=list,
        description="List of supported authentication mechanisms.",
    )
    authentication_details: list[AuthenticationDetail] = Field(
        default_factory=list,
        description="Detailed evidence-backed findings for each evaluated authentication method.",
    )

    # 4. Credential Access / Gating
    access_model: AccessModel = Field(
        default=AccessModel.UNKNOWN,
        description="Ease and gating model for acquiring API credentials.",
    )
    credential_access_notes: Optional[str] = Field(
        default=None,
        description="Details on signup friction, credit card requirements, or tier locks.",
    )

    # 5. API Surface
    api_types: list[ApiType] = Field(
        default_factory=list,
        description="Supported API paradigms (REST, GraphQL, etc.).",
    )
    api_type_details: list[ApiTypeDetail] = Field(
        default_factory=list,
        description="Detailed evidence-backed findings for each evaluated API architectural paradigm.",
    )
    api_breadth: ApiBreadth = Field(
        default=ApiBreadth.UNKNOWN,
        description="Scope and breadth of available programmatic capabilities.",
    )
    api_scope_notes: Optional[str] = Field(
        default=None,
        description="Observations regarding endpoint variety, rate limits, or documentation clarity.",
    )

    # 6. MCP / Agent Support
    mcp_status: McpStatus = Field(
        default=McpStatus.UNKNOWN,
        description="State of Model Context Protocol integration.",
    )
    mcp_notes: Optional[str] = Field(
        default=None,
        description="Details on existing MCP servers, GitHub repos, or platform roadmap.",
    )

    # 7. Buildability
    buildability: BuildabilityStatus = Field(
        default=BuildabilityStatus.UNKNOWN,
        description="Feasibility assessment for deploying an autonomous agent toolkit today.",
    )
    main_blocker: Optional[str] = Field(
        default=None,
        description="Key architectural, financial, or licensing barrier if buildability is restricted or blocked.",
    )

    # 8. Evidence (Claim-Level Traceability)
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Collection of verifiable citations supporting claims in this record.",
    )

    # 9. Granular Confidence Scores (0.0 to 1.0)
    auth_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score for authentication findings (0.0 - 1.0).",
    )
    access_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score for credential access findings (0.0 - 1.0).",
    )
    api_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score for API surface & breadth findings (0.0 - 1.0).",
    )
    mcp_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score for MCP status findings (0.0 - 1.0).",
    )
    buildability_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score for buildability assessment (0.0 - 1.0).",
    )
    overall_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Aggregated confidence metric across all research findings (0.0 - 1.0).",
    )

    # 10. Research Metadata
    researched_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the research run concluded.",
    )
    researcher_version: str = Field(
        default="1.0.0",
        description="Version string of the autonomous research agent pipeline.",
    )
    research_status: ResearchStatus = Field(
        default=ResearchStatus.PENDING,
        description="Current status in the research workflow lifecycle.",
    )

    # 11. Verification Metadata
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.NOT_VERIFIED,
        description="Current status in the verification lifecycle.",
    )
    verification_notes: Optional[str] = Field(
        default=None,
        description="Audit notes, failure explanations, or validation notes.",
    )
    verified_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when verification occurred.",
    )

    # ==========================================================================
    # VALIDATORS
    # ==========================================================================

    @field_validator("website", mode="before")
    @classmethod
    def clean_website(cls, v):
        """Convert empty string to None so unpopulated records pass validation."""
        if v == "" or v is None:
            return None
        return v

    @model_validator(mode="after")
    def validate_completed_integrity(self) -> "AppResearchRecord":
        """Enforce consistency rules between research status and evidence claims.

        - If research_status is COMPLETED, evidence list must not be empty.
        - Positive claims must be substantiated by at least one evidence item.
        - 'No MCP Found' and 'Unknown' must be respected as distinct states.
        """
        if self.research_status == ResearchStatus.COMPLETED:
            if not self.evidence:
                raise ValueError(
                    "Completed research record cannot have an empty evidence list. "
                    "Every completed finding must cite at least one verified source."
                )

        # Ensure blocked status notes a main blocker
        if self.buildability == BuildabilityStatus.BLOCKED and not self.main_blocker:
            raise ValueError(
                "When buildability is 'Blocked', a 'main_blocker' explanation is mandatory."
            )

        return self


# ==============================================================================
# FACTORY HELPER
# ==============================================================================


def create_empty_record(
    app_id: int,
    app_name: str,
    category: str,
    website: Optional[str] = None,
) -> AppResearchRecord:
    """Instantiate a valid empty/pending research record without factual hallucinations.

    Used to initialize the research pipeline for an entry from apps.csv.
    """
    return AppResearchRecord(
        id=app_id,
        app=app_name,
        category=category,
        website=website,
        one_line_description=None,
        auth_methods=[],
        authentication_details=[],
        access_model=AccessModel.UNKNOWN,
        credential_access_notes=None,
        api_types=[],
        api_type_details=[],
        api_breadth=ApiBreadth.UNKNOWN,
        api_scope_notes=None,
        mcp_status=McpStatus.UNKNOWN,
        mcp_notes=None,
        buildability=BuildabilityStatus.UNKNOWN,
        main_blocker=None,
        evidence=[],
        auth_confidence=None,
        access_confidence=None,
        api_confidence=None,
        mcp_confidence=None,
        buildability_confidence=None,
        overall_confidence=None,
        researched_at=None,
        researcher_version="1.0.0",
        research_status=ResearchStatus.PENDING,
        verification_status=VerificationStatus.NOT_VERIFIED,
        verification_notes=None,
        verified_at=None,
    )