"""
AI Product Ops Research System - Verification Models
====================================================
Defines strict Pydantic v2 data structures for the automated verification loop.
Captures claim-level verification results, corrections, confidence scores,
and comprehensive audit trails without altering original research files.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from agent.schema import (
    AppResearchRecord,
    Evidence,
    VerificationStatus,
)


class ClaimVerificationStatus(str, Enum):
    """Evaluation status of a specific factual claim during independent verification."""

    VERIFIED = "Verified"
    CONTRADICTED = "Contradicted"
    INSUFFICIENT_EVIDENCE = "Insufficient Evidence"
    NOT_CHECKED = "Not Checked"


class BlockerSeverity(str, Enum):
    """Categorical classification of integration obstacles."""

    HARD_BLOCKER = "Hard Blocker"
    RESTRICTION = "Restriction"
    NO_BLOCKER = "No Blocker"
    UNKNOWN = "Unknown"


class AuthenticationVerificationDetail(BaseModel):
    """Granular claim-level verification outcome for a single authentication method."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    method: str = Field(..., description="Authentication method evaluated (e.g. OAuth2, API Key, Personal Access Token).")
    original_present: bool = Field(..., description="Whether this method was claimed in original research.")
    verification_status: ClaimVerificationStatus = Field(
        ..., description="Verification status for this specific auth method."
    )
    evidence: Optional[Evidence] = Field(default=None, description="Supporting evidence for this method.")
    notes: str = Field(..., description="Specific audit note explaining whether and how method was supported.")


class FieldVerificationResult(BaseModel):
    """Verification outcome for an individual research dimension."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    app_id: int = Field(..., description="Application ID matching data/apps.csv.")
    app: str = Field(..., description="Canonical application name.")
    field: str = Field(..., description="Name of the research field evaluated.")
    original_value: Any = Field(..., description="Original research pass value.")
    verification_status: ClaimVerificationStatus = Field(
        ..., description="Verification determination (Verified, Contradicted, Insufficient Evidence, Not Checked)."
    )
    corrected_value: Optional[Any] = Field(
        default=None, description="Corrected value if original was updated or refined."
    )
    was_corrected: bool = Field(
        default=False, description="Whether the original value was changed."
    )
    verifier_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score of the verifier in this determination."
    )
    evidence: List[Evidence] = Field(
        default_factory=list, description="Evidence items supporting or contradicting this finding."
    )
    verification_notes: str = Field(
        ..., description="Detailed explanation of the verifier's findings and reasoning."
    )
    auth_details: Optional[List[AuthenticationVerificationDetail]] = Field(
        default=None, description="Per-method authentication audit details."
    )
    api_type_details: Optional[Dict[str, ClaimVerificationStatus]] = Field(
        default=None, description="Per-API-type verification status."
    )
    blocker_severity: Optional[BlockerSeverity] = Field(
        default=None, description="Classified blocker severity (Hard Blocker, Restriction, No Blocker, Unknown)."
    )


class AppVerificationRecord(BaseModel):
    """Complete verification record for an application, preserving before/after audit state."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    app_id: int
    app: str
    category: str
    verified_at: datetime
    verifier_version: str = "1.0.0"
    overall_verification_status: VerificationStatus
    claims_checked: int
    claims_verified: int
    claims_contradicted: int
    claims_insufficient_evidence: int
    corrections_made: int
    field_results: Dict[str, FieldVerificationResult]
    original_record: AppResearchRecord
    verified_record: AppResearchRecord
    summary_notes: str


class VerificationMetrics(BaseModel):
    """Aggregated accuracy metrics across verified applications."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    total_apps_verified: int
    total_claims_checked: int
    total_verified: int
    total_contradicted: int
    total_insufficient_evidence: int
    first_pass_accuracy: float
    post_verification_accuracy: float
    field_accuracy: Dict[str, Dict[str, float]]
    sample_size_note: str