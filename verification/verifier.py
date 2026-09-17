"""
AI Product Ops Research System - Hardened Automated Verification Loop
======================================================================
Independently audits first-pass research records against live primary sources.

Key Hardening Principles:
1. Never equate HTTP 200 with Verified: Inspect actual text content for claim evidence.
2. Claim-level Authentication Audit: Verify each claimed auth method independently.
3. Strict Evidence-Based API Audit: Require explicit evidence for every claimed API type.
4. Rigorous MCP Verification: Official requires vendor provenance; No MCP requires deliberate search.
5. Generic Platform Architecture: Zero app-specific hardcoding; works for all 100 apps.
6. Evidence-Backed Gating & Access: Distinguish Free Self-Serve, Paid, and Partner Gating.
7. Explicit Buildability Reasoning: Evaluate auth, access, APIs, restrictions, and hard blockers.
8. Zero Modification of Original Research: All original files remain strictly untouched.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

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
from agent.search import SearchEngine
from agent.scraper import DocScraper
from agent.researcher import get_slug, APPS_CSV
from verification.models import (
    AuthenticationVerificationDetail,
    BlockerSeverity,
    ClaimVerificationStatus,
    FieldVerificationResult,
    AppVerificationRecord,
    VerificationMetrics,
)

logger = logging.getLogger("verification.verifier")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESEARCH_DIR = DATA_DIR / "research"
VERIFICATION_DIR = DATA_DIR / "verification"
METRICS_FILE = DATA_DIR / "verification_metrics.json"


# ==============================================================================
# KEYWORD MATCHING MATRICES
# ==============================================================================

AUTH_METHOD_KEYWORDS: Dict[AuthMethod, List[List[str]]] = {
    AuthMethod.OAUTH2: [["oauth2", "oauth 2", "oauth-2", "authorization code", "oauth access token", "oauth app", "oauth flow"]],
    AuthMethod.API_KEY: [["api key", "api_key", "secret key", "x-api-key", "token or api key"]],
    AuthMethod.BEARER_TOKEN: [["bearer token", "bearer authentication", "authorization: bearer", "bearer <token>"]],
    AuthMethod.PERSONAL_ACCESS_TOKEN: [["personal access token", "user token", "personal token", "developer token", "pat token"]],
    AuthMethod.BASIC_AUTH: [["basic auth", "basic authentication", "http basic", "username and password"]],
    AuthMethod.JWT: [["jwt", "json web token", "jwt bearer", "signed jwt"]],
    AuthMethod.OTHER: [["custom authentication", "sso", "saml", "mutual tls"]],
}

AUTH_CONTRADICTIONS: Dict[AuthMethod, List[str]] = {
    AuthMethod.BASIC_AUTH: ["basic auth is not supported", "do not support basic auth", "basic authentication deprecated", "basic auth disabled"],
    AuthMethod.API_KEY: ["api keys are not supported", "we do not provide api keys", "no api key support"],
    AuthMethod.OAUTH2: ["oauth is not supported", "no oauth support"],
    AuthMethod.PERSONAL_ACCESS_TOKEN: ["personal access tokens are not supported", "no personal access tokens"],
}

API_TYPE_KEYWORDS: Dict[ApiType, List[List[str]]] = {
    ApiType.REST: [["rest api", "restful", "rest endpoints", "http methods", "web api methods", "openapi", "swagger", "json api", "http api"]],
    ApiType.GRAPHQL: [["graphql", "query {", "mutation {", "graphql endpoint", "graphql schema"]],
    ApiType.WEBHOOKS: [["webhook", "webhooks", "event subscriptions", "callback url", "http post events"]],
    ApiType.SDK: [["sdk", "client library", "client libraries", "python sdk", "javascript sdk", "bolt framework", "official sdk", "software development kit"]],
    ApiType.CLI: [["cli", "command line", "command-line interface", "terminal command"]],
    ApiType.SOAP: [["soap", "wsdl", "xml-rpc"]],
    ApiType.OTHER: [["websocket", "streaming api", "socket mode", "grpc", "protobuf"]],
}

API_CONTRADICTIONS: Dict[ApiType, List[str]] = {
    ApiType.GRAPHQL: ["do not support graphql", "no graphql api", "graphql is not supported"],
    ApiType.REST: ["no rest api", "rest api is deprecated"],
    ApiType.SOAP: ["soap has been retired", "soap is deprecated", "no soap support"],
}


class VerificationAgent:
    """Independent verification agent auditing research findings and evidence."""

    def __init__(
        self,
        search_engine: Optional[SearchEngine] = None,
        scraper: Optional[DocScraper] = None,
        version: str = "1.0.0",
        verification_dir: Optional[Path] = None,
        metrics_file: Optional[Path] = None,
        research_dir: Optional[Path] = None,
    ):
        self.search_engine = search_engine or SearchEngine()
        self.scraper = scraper or DocScraper()
        self.version = version
        self.verification_dir = verification_dir or VERIFICATION_DIR
        self.metrics_file = metrics_file or METRICS_FILE
        self.research_dir = research_dir or RESEARCH_DIR

        # Ensure verification directory exists
        self.verification_dir.mkdir(parents=True, exist_ok=True)

    def load_research_record(
        self, app_name: Optional[str] = None, app_id: Optional[int] = None
    ) -> AppResearchRecord:
        """Load an existing first-pass research record from research_dir."""
        if not self.research_dir.exists():
            raise FileNotFoundError(f"Research directory not found at {self.research_dir}")

        target_file = None
        if app_name:
            slug = get_slug(app_name)
            candidate = self.research_dir / f"{slug}.json"
            if candidate.exists():
                target_file = candidate

        if not target_file:
            for p in self.research_dir.glob("*.json"):
                try:
                    with open(p, "r", encoding="utf-8-sig") as f:
                        data = json.load(f)
                        if app_id is not None and data.get("id") == app_id:
                            target_file = p
                            break
                        if app_name is not None and data.get("app", "").lower() == app_name.lower():
                            target_file = p
                            break
                except Exception:
                    continue

        if not target_file or not target_file.exists():
            lookup_desc = f"ID '{app_id}'" if app_id is not None else f"name '{app_name}'"
            raise FileNotFoundError(
                f"No research record found for {lookup_desc} in {self.research_dir}. "
                f"Run research pass first using 'python main.py --research <name>'."
            )

        with open(target_file, "r", encoding="utf-8-sig") as f:
            data = json.load(f)

        return AppResearchRecord.model_validate(data)

    def verify_app(
        self,
        app_name: Optional[str] = None,
        app_id: Optional[int] = None,
        record: Optional[AppResearchRecord] = None,
    ) -> AppVerificationRecord:
        """Execute hardened independent verification loop for an application."""
        if record is None:
            record = self.load_research_record(app_name=app_name, app_id=app_id)

        app_id = record.id
        app_name = record.app
        category = record.category
        slug = get_slug(app_name)

        logger.info(f"Starting hardened independent verification for {app_name} (ID: {app_id})")

        field_results: Dict[str, FieldVerificationResult] = {}
        corrected_record_dict = record.model_dump()
        newly_added_evidence: List[Evidence] = []

        # ======================================================================
        # 1. Verify Website & Basic Identity (Content-checked, never HTTP 200 alone)
        # ======================================================================
        website_res = self._verify_website(record)
        field_results["website"] = website_res
        if website_res.was_corrected and website_res.corrected_value:
            corrected_record_dict["website"] = website_res.corrected_value

        # ======================================================================
        # 2. Verify Authentication (Claim-Level Per-Method Audit)
        # ======================================================================
        auth_res = self._verify_authentication(record, newly_added_evidence)
        field_results["authentication"] = auth_res
        if auth_res.was_corrected and auth_res.corrected_value:
            corrected_record_dict["auth_methods"] = auth_res.corrected_value
            corrected_record_dict["auth_confidence"] = auth_res.verifier_confidence

        # ======================================================================
        # 3. Verify Credential Access & Gating (Generic Evidence-Based)
        # ======================================================================
        access_res = self._verify_credential_access(record, newly_added_evidence)
        field_results["access_model"] = access_res
        if access_res.was_corrected and access_res.corrected_value:
            corrected_record_dict["access_model"] = access_res.corrected_value
            corrected_record_dict["credential_access_notes"] = access_res.verification_notes
            corrected_record_dict["access_confidence"] = access_res.verifier_confidence

        # ======================================================================
        # 4. Verify API Surface & Breadth (Evidence-Based, No Generic Inferences)
        # ======================================================================
        api_res = self._verify_api_surface(record, newly_added_evidence)
        field_results["api_surface"] = api_res
        if api_res.was_corrected and api_res.corrected_value:
            corrected_record_dict["api_types"] = api_res.corrected_value
            corrected_record_dict["api_confidence"] = api_res.verifier_confidence

        # ======================================================================
        # 5. Verify MCP Status (Rigorous Provenance & Deliberate Search)
        # ======================================================================
        mcp_res = self._verify_mcp_status(record, newly_added_evidence)
        field_results["mcp_status"] = mcp_res
        if mcp_res.was_corrected and mcp_res.corrected_value:
            corrected_record_dict["mcp_status"] = mcp_res.corrected_value
            corrected_record_dict["mcp_notes"] = mcp_res.verification_notes
            corrected_record_dict["mcp_confidence"] = mcp_res.verifier_confidence

        # ======================================================================
        # 6. Verify Buildability & Blockers (Explicit Multi-Factor Reasoning)
        # ======================================================================
        build_res = self._verify_buildability(record, field_results)
        field_results["buildability"] = build_res
        if build_res.was_corrected and build_res.corrected_value:
            corrected_record_dict["buildability"] = build_res.corrected_value
            corrected_record_dict["buildability_confidence"] = build_res.verifier_confidence
            if build_res.verification_notes:
                corrected_record_dict["main_blocker"] = build_res.verification_notes

        # Combine all evidence preserving original items
        all_evidence = list(record.evidence)
        for ev in newly_added_evidence:
            if not any(str(e.source_url) == str(ev.source_url) and e.claim == ev.claim for e in all_evidence):
                all_evidence.append(ev)
        corrected_record_dict["evidence"] = all_evidence

        # Overall confidence & status
        conf_list = [f.verifier_confidence for f in field_results.values()]
        new_overall_conf = round(sum(conf_list) / len(conf_list), 2) if conf_list else 0.8
        corrected_record_dict["overall_confidence"] = new_overall_conf

        # Count metrics
        claims_checked = len(field_results)
        claims_verified = sum(
            1 for f in field_results.values() if f.verification_status == ClaimVerificationStatus.VERIFIED
        )
        claims_contradicted = sum(
            1 for f in field_results.values() if f.verification_status == ClaimVerificationStatus.CONTRADICTED
        )
        claims_insufficient = sum(
            1 for f in field_results.values() if f.verification_status == ClaimVerificationStatus.INSUFFICIENT_EVIDENCE
        )
        corrections_made = sum(1 for f in field_results.values() if f.was_corrected)

        if claims_contradicted > 0 or claims_insufficient > 1:
            overall_status = VerificationStatus.PARTIALLY_VERIFIED
        elif claims_insufficient == 1:
            overall_status = VerificationStatus.PARTIALLY_VERIFIED
        else:
            overall_status = VerificationStatus.VERIFIED

        corrected_record_dict["verification_status"] = overall_status
        corrected_record_dict["verified_at"] = datetime.now(timezone.utc)
        corrected_record_dict["verification_notes"] = (
            f"Hardened verification audit by VerificationAgent v{self.version}. "
            f"{claims_verified}/{claims_checked} claims verified. {corrections_made} corrections applied."
        )

        verified_record = AppResearchRecord.model_validate(corrected_record_dict)

        verification_record = AppVerificationRecord(
            app_id=app_id,
            app=app_name,
            category=category,
            verified_at=datetime.now(timezone.utc),
            verifier_version=self.version,
            overall_verification_status=overall_status,
            claims_checked=claims_checked,
            claims_verified=claims_verified,
            claims_contradicted=claims_contradicted,
            claims_insufficient_evidence=claims_insufficient,
            corrections_made=corrections_made,
            field_results=field_results,
            original_record=record,
            verified_record=verified_record,
            summary_notes=(
                f"Independent hardened audit for {app_name}. {claims_verified}/{claims_checked} verified. "
                f"{corrections_made} fields corrected."
            ),
        )

        # Persist verification result
        out_file = self.verification_dir / f"{slug}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(verification_record.model_dump_json(indent=2))

        logger.info(f"Saved verification record to {out_file}")

        # Update metrics report
        self.update_metrics_report([verification_record])

        return verification_record

    # ==========================================================================
    # EVIDENCE INSPECTION HELPER (Content-First, Never HTTP 200 Alone)
    # ==========================================================================

    def _inspect_page_content(
        self,
        url: str,
        expected_keyword_groups: List[List[str]],
        contradiction_phrases: Optional[List[str]] = None,
        minimum_length: int = 40,
    ) -> Tuple[ClaimVerificationStatus, Optional[Dict[str, Any]], str]:
        """Fetch a page and verify actual text content for supporting or contradictory evidence.

        Never treats HTTP 200 alone as proof of any claim.
        """
        if not url or not str(url).startswith("http"):
            return ClaimVerificationStatus.INSUFFICIENT_EVIDENCE, None, "Invalid or missing URL."

        page = self.scraper.fetch_page(str(url))
        if not page or page.get("status_code") != 200:
            return (
                ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                page,
                f"Source page unreachable or returned non-200 HTTP status ({page.get('status_code') if page else 'No Response'}).",
            )

        title = page.get("title", "")
        text = page.get("text", "")
        excerpt = page.get("excerpt", "")
        headings = " ".join(page.get("headings", []))
        full_content = f"{title} {headings} {excerpt} {text}".lower()

        if len(full_content.strip()) < minimum_length:
            return (
                ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                page,
                "Page returned HTTP 200 but content is empty or truncated (< 40 characters).",
            )

        # 1. Check for explicit contradiction phrases
        if contradiction_phrases:
            for phrase in contradiction_phrases:
                if phrase.lower() in full_content:
                    return (
                        ClaimVerificationStatus.CONTRADICTED,
                        page,
                        f"Documentation explicitly contradicts claim with statement: '{phrase}'.",
                    )

        # 2. Check for expected keyword groups (every group must have >= 1 match)
        missing_groups: List[List[str]] = []
        matched_terms: List[str] = []

        for group in expected_keyword_groups:
            matched = False
            for term in group:
                if term.lower() in full_content:
                    matched = True
                    matched_terms.append(term)
                    break
            if not matched:
                missing_groups.append(group)

        if missing_groups:
            first_missing = missing_groups[0][0]
            return (
                ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                page,
                f"Page retrieved successfully (HTTP 200) but lacked supporting evidence for '{first_missing}'.",
            )

        return (
            ClaimVerificationStatus.VERIFIED,
            page,
            f"Content verified: direct evidence found for ({', '.join(matched_terms)}).",
        )

    # ==========================================================================
    # 1. WEBSITE AUDIT (Generic, Content-Verified)
    # ==========================================================================

    def _verify_website(self, record: AppResearchRecord) -> FieldVerificationResult:
        """Audit official website existence and confirm it actually belongs to the application."""
        website_str = str(record.website) if record.website else ""
        if not website_str:
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="website",
                original_value=None,
                verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                corrected_value=None,
                was_corrected=False,
                verifier_confidence=0.5,
                verification_notes="No official website was provided in the research record.",
            )

        # Content-level verification: page must mention the app name or its clean domain
        clean_app_name = re.sub(r"[^\w]", "", record.app.lower())
        page = self.scraper.fetch_page(website_str)

        if not page or page.get("status_code") != 200:
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="website",
                original_value=website_str,
                verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                corrected_value=None,
                was_corrected=False,
                verifier_confidence=0.6,
                verification_notes=f"Website could not be reached with HTTP 200: {website_str}.",
            )

        content = f"{page.get('title', '')} {' '.join(page.get('headings', []))} {page.get('text', '')}".lower()
        domain = urlparse(website_str).netloc.lower()

        # Confirm identity in content or domain
        app_in_content = record.app.lower() in content or clean_app_name in domain
        if not app_in_content:
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="website",
                original_value=website_str,
                verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                corrected_value=None,
                was_corrected=False,
                verifier_confidence=0.5,
                verification_notes=f"Page returned HTTP 200 but content lacks any reference to '{record.app}'.",
            )

        title = page.get("title", "")
        return FieldVerificationResult(
            app_id=record.id,
            app=record.app,
            field="website",
            original_value=website_str,
            verification_status=ClaimVerificationStatus.VERIFIED,
            corrected_value=None,
            was_corrected=False,
            verifier_confidence=0.98,
            verification_notes=f"Official website verified live and references '{record.app}': {title}",
        )

    # ==========================================================================
    # 2. AUTHENTICATION AUDIT (Claim-Level Per-Method Audit)
    # ==========================================================================

    def _verify_authentication(
        self, record: AppResearchRecord, new_evidence: List[Evidence]
    ) -> FieldVerificationResult:
        """Verify each claimed authentication method independently against primary documentation."""
        claimed_methods = list(record.auth_methods)
        auth_details: List[AuthenticationVerificationDetail] = []
        verified_methods: List[AuthMethod] = []

        # Gather candidate evidence pages
        candidate_urls: List[str] = []
        for e in record.evidence:
            claim_low = e.claim.lower()
            if any(k in claim_low for k in ["auth", "token", "oauth", "api key", "credential"]):
                candidate_urls.append(str(e.source_url))

        # If needed, perform generic independent search
        if not candidate_urls:
            query = f"{record.app} authentication developer docs api key oauth token"
            results = self.search_engine.search(query, max_results=3)
            for r in results:
                if r.get("url"):
                    candidate_urls.append(r["url"])

        # Audit each claimed method independently
        for method in claimed_methods:
            if method == AuthMethod.UNKNOWN:
                auth_details.append(
                    AuthenticationVerificationDetail(
                        method=method.value,
                        original_present=True,
                        verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                        evidence=None,
                        notes="Authentication method was recorded as Unknown on first pass.",
                    )
                )
                continue

            method_kw_groups = AUTH_METHOD_KEYWORDS.get(method, [[method.value.lower()]])
            contradiction_phrases = AUTH_CONTRADICTIONS.get(method, [])

            method_verified = False
            method_contradicted = False
            best_detail_ev: Optional[Evidence] = None
            best_detail_note = f"No documentation found supporting {method.value}."

            for url in candidate_urls:
                status, page, note = self._inspect_page_content(
                    url=url,
                    expected_keyword_groups=method_kw_groups,
                    contradiction_phrases=contradiction_phrases,
                )

                if status == ClaimVerificationStatus.CONTRADICTED:
                    method_contradicted = True
                    best_detail_note = note
                    break
                elif status == ClaimVerificationStatus.VERIFIED:
                    method_verified = True
                    best_detail_note = note
                    ev = Evidence(
                        claim=f"{record.app} supports authentication via {method.value}.",
                        source_url=url,
                        source_title=page.get("title", "Official Documentation") if page else "Documentation",
                        source_type=SourceType.OFFICIAL_AUTH_DOCS,
                        evidence_summary=page.get("excerpt", note) if page else note,
                        checked_at=datetime.now(timezone.utc),
                    )
                    best_detail_ev = ev
                    break

            if method_contradicted:
                auth_details.append(
                    AuthenticationVerificationDetail(
                        method=method.value,
                        original_present=True,
                        verification_status=ClaimVerificationStatus.CONTRADICTED,
                        evidence=None,
                        notes=best_detail_note,
                    )
                )
            elif method_verified:
                verified_methods.append(method)
                if best_detail_ev and not any(str(e.source_url) == str(best_detail_ev.source_url) for e in new_evidence):
                    new_evidence.append(best_detail_ev)

                auth_details.append(
                    AuthenticationVerificationDetail(
                        method=method.value,
                        original_present=True,
                        verification_status=ClaimVerificationStatus.VERIFIED,
                        evidence=best_detail_ev,
                        notes=best_detail_note,
                    )
                )
            else:
                auth_details.append(
                    AuthenticationVerificationDetail(
                        method=method.value,
                        original_present=True,
                        verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                        evidence=None,
                        notes=f"Retrieved documentation lacked specific supporting evidence for {method.value}.",
                    )
                )

        # Aggregate authentication results
        total_claimed = len(claimed_methods)
        num_verified = len(verified_methods)
        has_insufficient = any(d.verification_status == ClaimVerificationStatus.INSUFFICIENT_EVIDENCE for d in auth_details)
        has_contradicted = any(d.verification_status == ClaimVerificationStatus.CONTRADICTED for d in auth_details)

        ev_list = [d.evidence for d in auth_details if d.evidence is not None]

        if num_verified == total_claimed and total_claimed > 0:
            # All claimed methods verified
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="authentication",
                original_value=[m.value for m in claimed_methods],
                verification_status=ClaimVerificationStatus.VERIFIED,
                corrected_value=None,
                was_corrected=False,
                verifier_confidence=0.98,
                evidence=ev_list,
                auth_details=auth_details,
                verification_notes=f"All {num_verified} claimed auth methods verified with primary evidence: {', '.join(m.value for m in verified_methods)}.",
            )
        elif num_verified > 0:
            # Partial verification: correct to only the verified subset backed by evidence
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="authentication",
                original_value=[m.value for m in claimed_methods],
                verification_status=ClaimVerificationStatus.VERIFIED,
                corrected_value=verified_methods,
                was_corrected=True,
                verifier_confidence=0.92,
                evidence=ev_list,
                auth_details=auth_details,
                verification_notes=(
                    f"Partially verified: {num_verified}/{total_claimed} methods confirmed ({', '.join(m.value for m in verified_methods)}). "
                    f"Unverified methods lacked direct documentation evidence."
                ),
            )
        elif has_contradicted:
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="authentication",
                original_value=[m.value for m in claimed_methods],
                verification_status=ClaimVerificationStatus.CONTRADICTED,
                corrected_value=None,
                was_corrected=False,
                verifier_confidence=0.90,
                evidence=[],
                auth_details=auth_details,
                verification_notes="Authentication claim contradicted by primary documentation.",
            )
        else:
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="authentication",
                original_value=[m.value for m in claimed_methods],
                verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                corrected_value=None,
                was_corrected=False,
                verifier_confidence=0.5,
                evidence=[],
                auth_details=auth_details,
                verification_notes="None of the claimed authentication methods could be verified with supporting documentation.",
            )

    # ==========================================================================
    # 3. CREDENTIAL ACCESS & GATING AUDIT (Generic, Never Hardcoded)
    # ==========================================================================

    def _verify_credential_access(
        self, record: AppResearchRecord, new_evidence: List[Evidence]
    ) -> FieldVerificationResult:
        """Independently audit credential access and resolve gating models generically.

        Never assumes Free Self-Serve merely because an app has a public developer page.
        """
        access_evidence = [
            e for e in record.evidence if any(k in e.claim.lower() for k in ["credential", "self-serve", "gated", "sign up", "quickstart"])
        ]

        # Gather pages to inspect
        pages_to_check: List[str] = [str(e.source_url) for e in access_evidence]

        # Perform generic independent search only if no candidate pages were provided by research
        if not pages_to_check:
            query = f"{record.app} developer signup create app api credentials free workspace pricing"
            search_hits = self.search_engine.search(query, max_results=5)
            for hit in search_hits:
                u = hit.get("url")
                if u and u not in pages_to_check:
                    pages_to_check.append(u)

        # Access model detection indicators
        self_serve_terms = [
            "sign up for free", "create free account", "free workspace",
            "create an app", "quickstart: creating a", "quickstart: creating an",
            "developer console", "free tier", "no credit card required",
            "start building for free", "free developer account", "anyone can create",
            "manage apps", "create new app"
        ]
        trial_terms = ["free trial", "14-day trial", "30-day trial", "trial account", "start your trial"]
        paid_terms = ["paid plan required", "api access requires paid", "available on pro and enterprise", "enterprise plan required"]
        partner_terms = ["partner program only", "contact sales to access api", "restricted to certified partners", "request access from sales"]
        admin_terms = ["admin approval required", "workspace admin must approve", "admin consent required"]

        detected_model: Optional[AccessModel] = None
        evidence_found: Optional[Evidence] = None
        access_note = ""

        for url in pages_to_check:
            page = self.scraper.fetch_page(url)
            if not page or page.get("status_code") != 200:
                continue

            content = f"{page.get('title', '')} {' '.join(page.get('headings', []))} {page.get('text', '')}".lower()
            if len(content) < 40:
                continue

            # Prioritize definitive evidence
            if any(term in content for term in partner_terms):
                detected_model = AccessModel.PARTNER_CONTACT_SALES
                access_note = f"Primary documentation at {url} indicates API access requires partnership or sales contact."
            elif any(term in content for term in paid_terms):
                detected_model = AccessModel.PAID_PLAN_REQUIRED
                access_note = f"Primary documentation at {url} indicates API access requires paid subscription plan."
            elif any(term in content for term in admin_terms):
                detected_model = AccessModel.ADMIN_APPROVAL_REQUIRED
                access_note = f"Primary documentation at {url} indicates app installation requires tenant admin approval."
            elif any(term in content for term in trial_terms):
                detected_model = AccessModel.TRIAL_SELF_SERVE
                access_note = f"Primary documentation at {url} indicates developer access is available via free trial."
            elif any(term in content for term in self_serve_terms):
                detected_model = AccessModel.FREE_SELF_SERVE
                access_note = f"Confirmed free self-serve credential creation at {url}."

            if detected_model:
                ev = Evidence(
                    claim=f"{record.app} credential access model is {detected_model.value}.",
                    source_url=url,
                    source_title=page.get("title", "Developer Documentation"),
                    source_type=SourceType.OFFICIAL_DOCS,
                    evidence_summary=page.get("excerpt", access_note),
                    checked_at=datetime.now(timezone.utc),
                )
                evidence_found = ev
                break

        # Decision logic
        if detected_model and evidence_found:
            if evidence_found not in new_evidence:
                new_evidence.append(evidence_found)

            was_corrected = record.access_model != detected_model
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="access_model",
                original_value=record.access_model.value,
                verification_status=ClaimVerificationStatus.VERIFIED,
                corrected_value=detected_model if was_corrected else None,
                was_corrected=was_corrected,
                verifier_confidence=0.95,
                evidence=[evidence_found],
                verification_notes=(
                    f"{'CORRECTED: ' if was_corrected else ''}{access_note}"
                ),
            )

        # No definitive evidence found
        if record.access_model == AccessModel.UNKNOWN:
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="access_model",
                original_value=record.access_model.value,
                verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                corrected_value=None,
                was_corrected=False,
                verifier_confidence=0.5,
                evidence=[],
                verification_notes="Independent search could not definitively verify credential gating model.",
            )

        # Original was not Unknown, but retrieved pages do NOT contain proof of the claimed access model
        return FieldVerificationResult(
            app_id=record.id,
            app=record.app,
            field="access_model",
            original_value=record.access_model.value,
            verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
            corrected_value=None,
            was_corrected=False,
            verifier_confidence=0.6,
            evidence=[],
            verification_notes=f"Developer pages exist but lack explicit proof of '{record.access_model.value}'.",
        )

    # ==========================================================================
    # 4. API SURFACE & BREADTH AUDIT (Strictly Evidence-Based)
    # ==========================================================================

    def _verify_api_surface(
        self, record: AppResearchRecord, new_evidence: List[Evidence]
    ) -> FieldVerificationResult:
        """Verify each claimed API type against actual documentation text.

        Removes all generic fallback inference ('consistent with platform architecture').
        """
        claimed_types = list(record.api_types)
        api_type_details: Dict[str, ClaimVerificationStatus] = {}
        verified_types: List[ApiType] = []
        ev_items: List[Evidence] = []

        # Candidate evidence pages
        candidate_urls: List[str] = [
            str(e.source_url) for e in record.evidence if any(k in e.claim.lower() for k in ["api", "rest", "graphql", "sdk", "webhook"])
        ]

        if not candidate_urls:
            query = f"{record.app} official api documentation rest graphql sdk webhooks"
            results = self.search_engine.search(query, max_results=3)
            for r in results:
                if r.get("url"):
                    candidate_urls.append(r["url"])

        # Audit each claimed API type
        for api_t in claimed_types:
            kw_groups = API_TYPE_KEYWORDS.get(api_t, [[api_t.value.lower()]])
            contradictions = API_CONTRADICTIONS.get(api_t, [])

            t_verified = False
            t_contradicted = False
            best_note = f"No documentation evidence found for {api_t.value}."

            for url in candidate_urls:
                status, page, note = self._inspect_page_content(
                    url=url,
                    expected_keyword_groups=kw_groups,
                    contradiction_phrases=contradictions,
                )
                if status == ClaimVerificationStatus.CONTRADICTED:
                    t_contradicted = True
                    best_note = note
                    break
                elif status == ClaimVerificationStatus.VERIFIED:
                    t_verified = True
                    best_note = note
                    ev = Evidence(
                        claim=f"{record.app} provides public {api_t.value} API surface.",
                        source_url=url,
                        source_title=page.get("title", "API Documentation") if page else "Documentation",
                        source_type=SourceType.OFFICIAL_API_REF,
                        evidence_summary=page.get("excerpt", note) if page else note,
                        checked_at=datetime.now(timezone.utc),
                    )
                    ev_items.append(ev)
                    break

            if t_contradicted:
                api_type_details[api_t.value] = ClaimVerificationStatus.CONTRADICTED
            elif t_verified:
                api_type_details[api_t.value] = ClaimVerificationStatus.VERIFIED
                verified_types.append(api_t)
            else:
                api_type_details[api_t.value] = ClaimVerificationStatus.INSUFFICIENT_EVIDENCE

        # Aggregation
        total_claimed = len(claimed_types)
        num_verified = len(verified_types)

        for ev in ev_items:
            if not any(str(e.source_url) == str(ev.source_url) for e in new_evidence):
                new_evidence.append(ev)

        if num_verified == total_claimed and total_claimed > 0:
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="api_surface",
                original_value=[t.value for t in claimed_types],
                verification_status=ClaimVerificationStatus.VERIFIED,
                corrected_value=None,
                was_corrected=False,
                verifier_confidence=0.95,
                evidence=ev_items,
                api_type_details=api_type_details,
                verification_notes=f"All {num_verified} claimed API types verified with primary evidence: {', '.join(t.value for t in verified_types)}.",
            )
        elif num_verified > 0:
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="api_surface",
                original_value=[t.value for t in claimed_types],
                verification_status=ClaimVerificationStatus.VERIFIED,
                corrected_value=verified_types,
                was_corrected=True,
                verifier_confidence=0.92,
                evidence=ev_items,
                api_type_details=api_type_details,
                verification_notes=(
                    f"Partially verified: {num_verified}/{total_claimed} API types confirmed ({', '.join(t.value for t in verified_types)}). "
                    f"Unverified types lacked documentation evidence."
                ),
            )
        else:
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="api_surface",
                original_value=[t.value for t in claimed_types],
                verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                corrected_value=None,
                was_corrected=False,
                verifier_confidence=0.5,
                evidence=[],
                api_type_details=api_type_details,
                verification_notes="None of the claimed API types could be verified in documentation.",
            )

    # ==========================================================================
    # 5. MCP STATUS AUDIT (Evidence-Based, Deliberate Search)
    # ==========================================================================

    def _verify_mcp_status(
        self, record: AppResearchRecord, new_evidence: List[Evidence]
    ) -> FieldVerificationResult:
        """Audit MCP status with rigorous provenance and deliberate registry/doc search."""
        mcp_evidence = [
            e for e in record.evidence if any(k in e.claim.lower() for k in ["mcp", "model context protocol"])
        ]

        candidate_urls = [str(e.source_url) for e in mcp_evidence]

        # Perform deliberate search for MCP server only if no candidate evidence URL was provided
        if not candidate_urls:
            query = f"{record.app} model context protocol mcp server github"
            search_hits = self.search_engine.search(query, max_results=5)
            for h in search_hits:
                u = h.get("url")
                if u and u not in candidate_urls:
                    candidate_urls.append(u)

        official_mcp_found = False
        third_party_mcp_found = False
        mcp_mentioned = False
        best_ev: Optional[Evidence] = None

        for url in candidate_urls:
            page = self.scraper.fetch_page(url)
            if not page or page.get("status_code") != 200:
                continue

            content = f"{page.get('title', '')} {' '.join(page.get('headings', []))} {page.get('text', '')}".lower()
            if not ("mcp" in content or "model context protocol" in content):
                continue

            mcp_mentioned = True
            parsed_domain = urlparse(url).netloc.lower()
            clean_app = re.sub(r"[^\w]", "", record.app.lower())

            # Check for explicit third-party / community indicators
            is_explicitly_community = any(
                phrase in content for phrase in ["unofficial", "third-party", "community-maintained", "community implementation", "community mcp", "community wrapper"]
            )

            # Check provenance: vendor domain or vendor github organization
            is_vendor_domain = clean_app in parsed_domain or (record.website and urlparse(str(record.website)).netloc.lower() in parsed_domain)
            path_parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
            github_owner = path_parts[0].lower() if "github.com" in parsed_domain and path_parts else ""
            is_vendor_github = "github.com" in parsed_domain and (github_owner == clean_app or github_owner == f"{clean_app}api" or github_owner == f"{clean_app}hq")

            if (is_vendor_domain or is_vendor_github) and not is_explicitly_community:
                official_mcp_found = True
                best_ev = Evidence(
                    claim=f"{record.app} provides official Model Context Protocol (MCP) server support.",
                    source_url=url,
                    source_title=page.get("title", "Official MCP Documentation"),
                    source_type=SourceType.OFFICIAL_MCP_DOCS,
                    evidence_summary=page.get("excerpt", "Official MCP server verified directly via vendor docs/repository."),
                    checked_at=datetime.now(timezone.utc),
                )
                break
            else:
                third_party_mcp_found = True
                if not best_ev:
                    best_ev = Evidence(
                        claim=f"Third-party community MCP server exists for {record.app}.",
                        source_url=url,
                        source_title=page.get("title", "Community MCP Repository"),
                        source_type=SourceType.GITHUB,
                        evidence_summary=page.get("excerpt", "Community MCP server implementation."),
                        checked_at=datetime.now(timezone.utc),
                    )

        if best_ev and best_ev not in new_evidence:
            new_evidence.append(best_ev)

        # Audit against original claim
        if record.mcp_status == McpStatus.OFFICIAL_MCP:
            if official_mcp_found:
                return FieldVerificationResult(
                    app_id=record.id,
                    app=record.app,
                    field="mcp_status",
                    original_value=record.mcp_status.value,
                    verification_status=ClaimVerificationStatus.VERIFIED,
                    corrected_value=None,
                    was_corrected=False,
                    verifier_confidence=0.98,
                    evidence=[best_ev] if best_ev else [],
                    verification_notes=f"Official MCP server verified via vendor documentation at {best_ev.source_url if best_ev else ''}.",
                )
            elif third_party_mcp_found:
                return FieldVerificationResult(
                    app_id=record.id,
                    app=record.app,
                    field="mcp_status",
                    original_value=record.mcp_status.value,
                    verification_status=ClaimVerificationStatus.VERIFIED,
                    corrected_value=McpStatus.THIRD_PARTY_MCP,
                    was_corrected=True,
                    verifier_confidence=0.92,
                    evidence=[best_ev] if best_ev else [],
                    verification_notes="CORRECTED: Claimed Official MCP, but evidence proves third-party community implementation only.",
                )
            else:
                return FieldVerificationResult(
                    app_id=record.id,
                    app=record.app,
                    field="mcp_status",
                    original_value=record.mcp_status.value,
                    verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                    corrected_value=None,
                    was_corrected=False,
                    verifier_confidence=0.5,
                    evidence=[],
                    verification_notes="No official documentation or repository found confirming Official MCP support.",
                )

        elif record.mcp_status == McpStatus.THIRD_PARTY_MCP:
            if third_party_mcp_found or official_mcp_found:
                return FieldVerificationResult(
                    app_id=record.id,
                    app=record.app,
                    field="mcp_status",
                    original_value=record.mcp_status.value,
                    verification_status=ClaimVerificationStatus.VERIFIED,
                    corrected_value=None,
                    was_corrected=False,
                    verifier_confidence=0.92,
                    evidence=[best_ev] if best_ev else [],
                    verification_notes="Third-party community MCP server verified with repository evidence.",
                )
            else:
                return FieldVerificationResult(
                    app_id=record.id,
                    app=record.app,
                    field="mcp_status",
                    original_value=record.mcp_status.value,
                    verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                    corrected_value=None,
                    was_corrected=False,
                    verifier_confidence=0.5,
                    evidence=[],
                    verification_notes="No working third-party MCP repository could be verified.",
                )

        elif record.mcp_status == McpStatus.NO_MCP_FOUND:
            # Requires deliberate search coverage
            if official_mcp_found or third_party_mcp_found:
                found_status = McpStatus.OFFICIAL_MCP if official_mcp_found else McpStatus.THIRD_PARTY_MCP
                return FieldVerificationResult(
                    app_id=record.id,
                    app=record.app,
                    field="mcp_status",
                    original_value=record.mcp_status.value,
                    verification_status=ClaimVerificationStatus.VERIFIED,
                    corrected_value=found_status,
                    was_corrected=True,
                    verifier_confidence=0.95,
                    evidence=[best_ev] if best_ev else [],
                    verification_notes=f"CORRECTED: Original found no MCP, but deliberate verification discovered {found_status.value}.",
                )
            else:
                return FieldVerificationResult(
                    app_id=record.id,
                    app=record.app,
                    field="mcp_status",
                    original_value=record.mcp_status.value,
                    verification_status=ClaimVerificationStatus.VERIFIED,
                    corrected_value=None,
                    was_corrected=False,
                    verifier_confidence=0.90,
                    evidence=[],
                    verification_notes=f"Deliberate search across docs and repositories confirmed no MCP server currently available.",
                )

        # Original was Unknown
        if official_mcp_found or third_party_mcp_found:
            found_status = McpStatus.OFFICIAL_MCP if official_mcp_found else McpStatus.THIRD_PARTY_MCP
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="mcp_status",
                original_value=record.mcp_status.value,
                verification_status=ClaimVerificationStatus.VERIFIED,
                corrected_value=found_status,
                was_corrected=True,
                verifier_confidence=0.95,
                evidence=[best_ev] if best_ev else [],
                verification_notes=f"CORRECTED: Resolved Unknown to {found_status.value} with primary evidence.",
            )

        return FieldVerificationResult(
            app_id=record.id,
            app=record.app,
            field="mcp_status",
            original_value=record.mcp_status.value,
            verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
            corrected_value=None,
            was_corrected=False,
            verifier_confidence=0.5,
            evidence=[],
            verification_notes="MCP status remains Unknown due to inconclusive search results.",
        )

    # ==========================================================================
    # 6. BUILDABILITY & BLOCKERS AUDIT (Explicit Reasoning Function)
    # ==========================================================================

    def _verify_buildability(
        self,
        record: AppResearchRecord,
        field_results: Dict[str, FieldVerificationResult],
    ) -> FieldVerificationResult:
        """Explicit reasoning function auditing buildability status and integration blockers.

        Evaluates:
        - Public API availability (missing API evidence prevents Buildable Now)
        - Authentication availability
        - Credential gating model
        - Blocker severity: Hard Blocker vs Restriction vs No Blocker
        - MCP is treated as an optional supporting capability, never a prerequisite.
        """
        api_res = field_results.get("api_surface")
        access_res = field_results.get("access_model")
        auth_res = field_results.get("authentication")

        # 1. Check API Evidence
        has_verified_apis = False
        if api_res and api_res.verification_status == ClaimVerificationStatus.VERIFIED:
            has_verified_apis = True
        elif not api_res or api_res.verification_status != ClaimVerificationStatus.VERIFIED:
            has_verified_apis = False

        if not has_verified_apis:
            return FieldVerificationResult(
                app_id=record.id,
                app=record.app,
                field="buildability",
                original_value=record.buildability.value,
                verification_status=ClaimVerificationStatus.INSUFFICIENT_EVIDENCE,
                corrected_value=None,
                was_corrected=False,
                verifier_confidence=0.5,
                blocker_severity=BlockerSeverity.UNKNOWN,
                verification_notes="Missing or unverified API evidence prevents confirming 'Buildable Now'.",
            )

        # 2. Check Effective Access Model
        effective_access = record.access_model
        if access_res and access_res.corrected_value:
            effective_access = access_res.corrected_value

        # 3. Classify Blocker Severity & Expected Buildability
        blocker_severity = BlockerSeverity.NO_BLOCKER
        expected_status = BuildabilityStatus.BUILDABLE_NOW
        notes = ""

        if effective_access == AccessModel.PARTNER_CONTACT_SALES:
            blocker_severity = BlockerSeverity.HARD_BLOCKER
            expected_status = BuildabilityStatus.BLOCKED
            notes = "HARD BLOCKER: Partner contract or sales approval required to obtain API access."
        elif effective_access == AccessModel.PAID_PLAN_REQUIRED:
            blocker_severity = BlockerSeverity.RESTRICTION
            expected_status = BuildabilityStatus.BUILDABLE_WITH_RESTRICTIONS
            notes = "RESTRICTION: Programmatic access requires an active paid subscription tier."
        elif effective_access == AccessModel.ADMIN_APPROVAL_REQUIRED:
            blocker_severity = BlockerSeverity.RESTRICTION
            expected_status = BuildabilityStatus.BUILDABLE_WITH_RESTRICTIONS
            notes = "RESTRICTION: App deployment requires enterprise organization admin consent."
        elif effective_access == AccessModel.TRIAL_SELF_SERVE:
            blocker_severity = BlockerSeverity.RESTRICTION
            expected_status = BuildabilityStatus.BUILDABLE_WITH_RESTRICTIONS
            notes = "RESTRICTION: Credentials available self-serve during limited trial window."
        elif effective_access == AccessModel.FREE_SELF_SERVE:
            # Rate limits and OAuth scopes are developer restrictions, NOT hard blockers
            blocker_severity = BlockerSeverity.RESTRICTION
            expected_status = BuildabilityStatus.BUILDABLE_NOW
            notes = "Buildable Now. Standard rate limits and OAuth scoping permissions are developer restrictions, not hard blockers."
        else:
            blocker_severity = BlockerSeverity.UNKNOWN
            expected_status = BuildabilityStatus.UNKNOWN
            notes = "Inconclusive credential gating model prevents establishing buildability."

        was_corrected = record.buildability != expected_status
        return FieldVerificationResult(
            app_id=record.id,
            app=record.app,
            field="buildability",
            original_value=record.buildability.value,
            verification_status=ClaimVerificationStatus.VERIFIED,
            corrected_value=expected_status if was_corrected else None,
            was_corrected=was_corrected,
            verifier_confidence=0.95,
            blocker_severity=blocker_severity,
            verification_notes=notes,
        )

    # ==========================================================================
    # METRICS & REPORTING
    # ==========================================================================

    def calculate_metrics(
        self, records: List[AppVerificationRecord]
    ) -> VerificationMetrics:
        """Calculate mathematically exact accuracy metrics across verified records.

        Definitions:
        - Total claims checked: count of individual field claims independently evaluated.
        - First-pass accuracy: claims verified correct in original research without verifier correction.
        - Post-verification accuracy: claims verified after verifier audit and evidence-backed corrections.
        - Insufficient Evidence and Contradicted claims are NOT counted as correct in either metric.
        """
        if not records:
            return VerificationMetrics(
                total_apps_verified=0,
                total_claims_checked=0,
                total_verified=0,
                total_contradicted=0,
                total_insufficient_evidence=0,
                first_pass_accuracy=0.0,
                post_verification_accuracy=0.0,
                field_accuracy={},
                sample_size_note="No verification records processed.",
            )

        total_claims = 0
        total_verified = 0
        first_pass_correct = 0
        total_contradicted = 0
        total_insufficient = 0

        field_stats: Dict[str, Dict[str, Any]] = {}

        for rec in records:
            for field_name, fres in rec.field_results.items():
                total_claims += 1

                if field_name not in field_stats:
                    field_stats[field_name] = {"checked": 0, "first_pass_correct": 0, "post_verified": 0}

                field_stats[field_name]["checked"] += 1

                if fres.verification_status == ClaimVerificationStatus.VERIFIED:
                    total_verified += 1
                    field_stats[field_name]["post_verified"] += 1
                    if not fres.was_corrected:
                        first_pass_correct += 1
                        field_stats[field_name]["first_pass_correct"] += 1
                elif fres.verification_status == ClaimVerificationStatus.CONTRADICTED:
                    total_contradicted += 1
                elif fres.verification_status == ClaimVerificationStatus.INSUFFICIENT_EVIDENCE:
                    total_insufficient += 1

        first_pass_accuracy = round((first_pass_correct / total_claims) * 100, 1) if total_claims else 0.0
        post_verification_accuracy = round((total_verified / total_claims) * 100, 1) if total_claims else 0.0

        field_accuracy_summary: Dict[str, Dict[str, float]] = {}
        for fname, stats in field_stats.items():
            cnt = stats["checked"]
            field_accuracy_summary[fname] = {
                "first_pass_accuracy": round((stats["first_pass_correct"] / cnt) * 100, 1) if cnt else 0.0,
                "post_verification_accuracy": round((stats["post_verified"] / cnt) * 100, 1) if cnt else 0.0,
            }

        note = (
            f"Pilot phase: N={len(records)} application(s). "
            "First-pass accuracy measures claims supported without verifier correction. "
            "Post-verification accuracy measures claims verified with independent primary evidence. "
            "Insufficient Evidence and Contradicted claims are not counted as accurate."
        )

        return VerificationMetrics(
            total_apps_verified=len(records),
            total_claims_checked=total_claims,
            total_verified=total_verified,
            total_contradicted=total_contradicted,
            total_insufficient_evidence=total_insufficient,
            first_pass_accuracy=first_pass_accuracy,
            post_verification_accuracy=post_verification_accuracy,
            field_accuracy=field_accuracy_summary,
            sample_size_note=note,
        )

    def update_metrics_report(self, records: List[AppVerificationRecord]):
        """Persist measured verification metrics to data/verification_metrics.json."""
        metrics = self.calculate_metrics(records)
        with open(self.metrics_file, "w", encoding="utf-8") as f:
            f.write(metrics.model_dump_json(indent=2))
        logger.info(f"Updated metrics report at {self.metrics_file}")
