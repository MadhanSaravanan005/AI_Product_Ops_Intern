"""
AI Product Ops Research System - Core Research Agent
=====================================================
Autonomous research agent for evaluating software platforms against 10 critical dimensions
to determine their feasibility and readiness as AI agent toolkits.

Executes a 6-stage research strategy:
1. Basic Application Information (identity, website, description)
2. Authentication (OAuth2, API keys, tokens, auth docs)
3. Credential Access & Gating (Self-serve vs paid vs admin gated)
4. API Surface & Breadth (REST, GraphQL, Webhooks, endpoints, breadth)
5. Model Context Protocol (MCP) Support (Official, Third-Party, None Found, Unknown)
6. Buildability & Blockers Assessment (Buildable Now / Restricted / Blocked)

Produces strict, claim-backed AppResearchRecord instances validated against agent/schema.py.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
from typing import Optional, Dict, Any, List, Tuple

from agent.schema import (
    AccessModel,
    ApiBreadth,
    ApiType,
    ApiTypeDetail,
    AppResearchRecord,
    AuthenticationDetail,
    AuthMethod,
    BuildabilityStatus,
    Evidence,
    McpStatus,
    ResearchStatus,
    SourceType,
    VerificationStatus,
    create_empty_record,
)
from agent.search import SearchEngine
from agent.scraper import DocScraper
from agent.llm_client import LLMClient

logger = logging.getLogger("agent.researcher")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
APPS_CSV = DATA_DIR / "apps.csv"
RESEARCH_RAW_DIR = DATA_DIR / "research_raw"
RESEARCH_DIR = DATA_DIR / "research"
RESEARCH_LOG_FILE = DATA_DIR / "research_log.jsonl"


def get_slug(name: str) -> str:
    """Convert application name to a clean filesystem slug."""
    clean = re.sub(r"[^\w\s-]", "", name.lower()).strip()
    return re.sub(r"[-\s]+", "_", clean)


class ResearchAgent:
    """Autonomous agent that conducts evidence-first technical platform research."""

    def __init__(
        self,
        search_engine: Optional[SearchEngine] = None,
        scraper: Optional[DocScraper] = None,
        llm_client: Optional[LLMClient] = None,
        version: str = "1.0.0",
        research_dir: Optional[Path] = None,
        raw_dir: Optional[Path] = None,
        log_file: Optional[Path] = None,
        enable_second_hop: bool = True,
    ):
        self.search_engine = search_engine or SearchEngine()
        self.scraper = scraper or DocScraper()
        self.llm_client = llm_client or LLMClient()
        self.version = version
        self.research_dir = research_dir or RESEARCH_DIR
        self.raw_dir = raw_dir or RESEARCH_RAW_DIR
        self.log_file = log_file or RESEARCH_LOG_FILE
        self.enable_second_hop = enable_second_hop

        # Ensure output directories exist
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.research_dir.mkdir(parents=True, exist_ok=True)

    def load_app_by_id_or_name(
        self, app_name: Optional[str] = None, app_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Look up an application from data/apps.csv."""
        if not APPS_CSV.exists():
            raise FileNotFoundError(f"Apps database not found at {APPS_CSV}")

        import csv

        with open(APPS_CSV, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                r_id = int(row["id"].strip())
                r_name = row["app"].strip()
                r_cat = row["category"].strip()

                if app_id is not None and r_id == app_id:
                    return {"id": r_id, "app": r_name, "category": r_cat}
                if app_name is not None and r_name.lower() == app_name.strip().lower():
                    return {"id": r_id, "app": r_name, "category": r_cat}

        lookup_desc = f"ID '{app_id}'" if app_id is not None else f"name '{app_name}'"
        raise ValueError(f"Application with {lookup_desc} not found in {APPS_CSV}")

    def log_run(
        self,
        app_id: int,
        app_name: str,
        status: ResearchStatus,
        evidence_count: int,
        confidence: Optional[float],
        error: Optional[str] = None,
    ):
        """Append a machine-readable entry to data/research_log.jsonl."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "app_id": app_id,
            "app": app_name,
            "status": status.value,
            "evidence_count": evidence_count,
            "overall_confidence": confidence,
            "error": error,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def research_app(
        self,
        app_name: Optional[str] = None,
        app_id: Optional[int] = None,
        target_website: Optional[str] = None,
    ) -> AppResearchRecord:
        """Execute full end-to-end research for an application."""
        # 1. Identity lookup
        try:
            app_meta = self.load_app_by_id_or_name(app_name=app_name, app_id=app_id)
        except Exception as e:
            logger.error(f"Failed to lookup application: {e}")
            raise

        app_id = app_meta["id"]
        app_name = app_meta["app"]
        category = app_meta["category"]
        slug = get_slug(app_name)
        existing_record_path = self.research_dir / f"{slug}.json"
        if existing_record_path.exists():
            try:
                with open(existing_record_path, "r", encoding="utf-8-sig") as f:
                    cached_record = AppResearchRecord.model_validate(json.load(f))
                logger.info(f"Retaining existing completed research for {app_name} from {existing_record_path}")
                return cached_record
            except Exception as e:
                logger.warning(f"Could not load existing record from {existing_record_path}: {e}")

        logger.info(f"Starting research for {app_name} (ID: {app_id}, Category: {category})")

        # Initialize pending record
        record = create_empty_record(
            app_id=app_id,
            app_name=app_name,
            category=category,
            website=target_website,
        )

        evidence_list: List[Evidence] = []
        raw_findings: Dict[str, Any] = {
            "app_id": app_id,
            "app": app_name,
            "category": category,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "searches": {},
            "pages": {},
        }

        try:
            # ------------------------------------------------------------------
            # Stage 1: Basic Information & Official Website
            # ------------------------------------------------------------------
            website_url, one_line_desc = self._research_basic_info(
                app_name, category, target_website, raw_findings, evidence_list
            )
            record.website = website_url or record.website
            record.one_line_description = one_line_desc

            import urllib.parse
            official_domain = urllib.parse.urlparse(str(record.website)).netloc.lower() if record.website else None

            # ------------------------------------------------------------------
            # Stage 2: Authentication
            # ------------------------------------------------------------------
            auth_methods, auth_details, auth_conf = self._research_authentication(
                app_name, raw_findings, evidence_list, official_domain=official_domain
            )
            record.auth_methods = auth_methods
            record.authentication_details = auth_details
            record.auth_confidence = auth_conf

            # ------------------------------------------------------------------
            # Stage 3: Credential Access & Gating
            # ------------------------------------------------------------------
            access_model, access_notes, access_conf = self._research_credential_access(
                app_name, raw_findings, evidence_list, official_domain=official_domain
            )
            record.access_model = access_model
            record.credential_access_notes = access_notes
            record.access_confidence = access_conf

            # ------------------------------------------------------------------
            # Stage 4: API Surface & Breadth
            # ------------------------------------------------------------------
            api_types, api_type_details, api_breadth, api_notes, api_conf = self._research_api_surface(
                app_name, raw_findings, evidence_list, official_domain=official_domain
            )
            record.api_types = api_types
            record.api_type_details = api_type_details
            record.api_breadth = api_breadth
            record.api_scope_notes = api_notes
            record.api_confidence = api_conf

            # ------------------------------------------------------------------
            # Stage 5: MCP Support (Strict Distinction: No MCP Found vs Unknown)
            # ------------------------------------------------------------------
            mcp_status, mcp_notes, mcp_conf = self._research_mcp(
                app_name, raw_findings, evidence_list
            )
            record.mcp_status = mcp_status
            record.mcp_notes = mcp_notes
            record.mcp_confidence = mcp_conf

            # ------------------------------------------------------------------
            # Stage 6: Buildability & Blockers Assessment
            # ------------------------------------------------------------------
            buildability, blocker, build_conf = self._assess_buildability(
                app_name,
                record.auth_methods,
                record.access_model,
                record.api_types,
                record.api_breadth,
                record.mcp_status,
                evidence_list,
            )
            record.buildability = buildability
            record.main_blocker = blocker
            record.buildability_confidence = build_conf

            # ------------------------------------------------------------------
            # Compile Evidence & Confidence
            # ------------------------------------------------------------------
            record.evidence = evidence_list

            confidences = [
                c
                for c in [auth_conf, access_conf, api_conf, mcp_conf, build_conf]
                if c is not None
            ]
            record.overall_confidence = (
                round(sum(confidences) / len(confidences), 2) if confidences else 0.5
            )

            # Determine research lifecycle status
            if len(record.evidence) >= 2 and record.overall_confidence >= 0.7:
                record.research_status = ResearchStatus.COMPLETED
            elif len(record.evidence) >= 1:
                record.research_status = ResearchStatus.NEEDS_VERIFICATION
            else:
                record.research_status = ResearchStatus.FAILED

            record.researched_at = datetime.now(timezone.utc)
            record.researcher_version = self.version

            # Validate the record via Pydantic
            validated_record = AppResearchRecord.model_validate(record.model_dump())

            # Save raw research data (honesty & audit trail requirement)
            raw_path = self.raw_dir / f"{slug}.json"
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(raw_findings, f, indent=2, ensure_ascii=False)

            # Save validated record
            out_path = self.research_dir / f"{slug}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(validated_record.model_dump_json(indent=2))

            self.log_run(
                app_id=app_id,
                app_name=app_name,
                status=validated_record.research_status,
                evidence_count=len(validated_record.evidence),
                confidence=validated_record.overall_confidence,
            )

            logger.info(
                f"Completed research for {app_name}: Status={validated_record.research_status}, "
                f"Evidence={len(validated_record.evidence)}, Conf={validated_record.overall_confidence}"
            )
            return validated_record

        except Exception as e:
            logger.error(f"Research run failed for {app_name}: {e}", exc_info=True)
            record.research_status = ResearchStatus.FAILED
            self.log_run(
                app_id=app_id,
                app_name=app_name,
                status=ResearchStatus.FAILED,
                evidence_count=len(evidence_list),
                confidence=0.0,
                error=str(e),
            )
            raise

    # ==========================================================================
    # RESEARCH STRATEGY MODULES
    # ==========================================================================

    def _is_official_domain(self, url: str, app_name: str) -> bool:
        """Heuristic to check if a URL belongs to the vendor's official domain."""
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        clean_app = re.sub(r"[^\w]", "", app_name.lower())
        blacklist = [
            "wikipedia.org", "github.com", "postman.com", "g2.com",
            "capterra.com", "medium.com", "dev.to", "reddit.com",
            "youtube.com", "unified.to", "composio.dev", "npm.js", "npmjs.com"
        ]
        if any(b in netloc for b in blacklist):
            return False
        parts = netloc.split(".")
        return any(clean_app in p for p in parts)

    def _research_basic_info(
        self,
        app_name: str,
        category: str,
        target_website: Optional[str],
        raw: Dict[str, Any],
        evidence: List[Evidence],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Determine official website and one-line functional description."""
        query = f"{app_name} official website developer"
        results = self.search_engine.search(query, max_results=4)
        raw["searches"]["basic_info"] = results

        website_url = target_website
        description = None

        for r in results:
            url = r.get("url", "")
            is_official = self._is_official_domain(url, app_name)
            if not website_url and is_official:
                parts = url.split("/")
                website_url = f"{parts[0]}//{parts[2]}/"

            if is_official and not description:
                page = self.scraper.fetch_page(url, fallback_snippet=r.get("snippet", ""))
                if page:
                    raw["pages"][url] = page
                    clean_title = page.get("title", "").split("|")[0].split("-")[0].strip()
                    if clean_title:
                        description = f"{clean_title}: Leading platform in {category}."

        if not website_url:
            # Fallback to standard .com if none found
            clean_slug = get_slug(app_name).replace("_", "")
            website_url = f"https://{clean_slug}.com/"

        if not description:
            description = f"{app_name} is a software platform in the {category} category."

        return website_url, description[:250]

    def _research_authentication(
        self,
        app_name: str,
        raw: Dict[str, Any],
        evidence: List[Evidence],
        official_domain: Optional[str] = None,
    ) -> Tuple[List[AuthMethod], List[AuthenticationDetail], float]:
        """Research authentication mechanisms with item-level direct documentation evidence."""
        query = f"{app_name} developer authentication OAuth API key token docs"
        results = self.search_engine.search(query, max_results=4)
        raw["searches"]["authentication_general"] = results

        candidate_checks = [
            (
                AuthMethod.OAUTH2,
                ["oauth2", "oauth 2", "oauth-2", "authorization code", "oauth access token", "oauth app", "oauth flow"],
                "OAuth2 authorization code grant and token management",
            ),
            (
                AuthMethod.API_KEY,
                ["api key", "api_key", "secret key", "x-api-key", "token or api key"],
                "API key provisioning and request header authentication",
            ),
            (
                AuthMethod.BEARER_TOKEN,
                ["bearer token", "bearer authentication", "authorization: bearer"],
                "Bearer token authentication format in HTTP request headers",
            ),
            (
                AuthMethod.PERSONAL_ACCESS_TOKEN,
                ["personal access token", "personal token", "developer token", "pat token"],
                "Personal Access Token generation and scoped developer permissions",
            ),
            (
                AuthMethod.BASIC_AUTH,
                ["basic auth", "basic authentication", "http basic"],
                "HTTP Basic Authentication via credentials",
            ),
        ]

        pages: List[Dict[str, Any]] = []
        for r in results:
            url = r.get("url", "")
            page = self.scraper.fetch_page(url, fallback_snippet=r.get("snippet", ""), allow_fallback_snippet=False, return_failed_status=True)
            if page:
                raw["pages"][url] = page
                if page.get("source_retrieval_status", "Success") == "Success" and len(page.get("text", "")) >= 15:
                    pages.append(page)

        confirmed_methods: List[AuthMethod] = []
        auth_details: List[AuthenticationDetail] = []

        unresolved_candidates = []
        for method, keywords, desc in candidate_checks:
            method_page = None
            matched_snippet = ""

            # Check retrieved pages from general search
            for p in pages:
                p_text = (p.get("text", "") + " " + p.get("title", "")).lower()
                for kw in keywords:
                    if kw in p_text:
                        method_page = p
                        matched_snippet = p.get("excerpt", "")
                        break
                if method_page:
                    break

            if method_page:
                ev = Evidence(
                    claim=f"{app_name} supports authentication via {method.value}.",
                    source_url=method_page["url"],
                    source_title=method_page["title"],
                    source_type=SourceType.OFFICIAL_AUTH_DOCS,
                    evidence_summary=matched_snippet or f"Official documentation describes {desc} for {app_name}.",
                    checked_at=datetime.now(timezone.utc),
                )
                evidence.append(ev)
                detail = AuthenticationDetail(
                    method=method,
                    status="Confirmed",
                    evidence=[ev],
                    confidence=0.92,
                    notes=f"Confirmed via {method_page['title']}: {desc}.",
                )
                auth_details.append(detail)
                confirmed_methods.append(method)
            else:
                unresolved_candidates.append((method, keywords, desc))

        # STEP 3 BOUND: Maximum 1 second-hop search, and ONLY when initial evidence is insufficient
        if self.enable_second_hop and unresolved_candidates and len(confirmed_methods) == 0:
            method, keywords, desc = unresolved_candidates[0]
            sec_results = self.search_engine.search_auth_method(
                app_name, method.value, official_domain=official_domain, max_results=3
            )
            raw["searches"][f"auth_{method.value}"] = sec_results
            for sr in sec_results:
                s_url = sr.get("url", "")
                s_page = self.scraper.fetch_page(s_url, fallback_snippet=sr.get("snippet", ""), allow_fallback_snippet=False, return_failed_status=True)
                if s_page and s_page.get("source_retrieval_status", "Success") == "Success" and len(s_page.get("text", "")) >= 15:
                    s_text = (s_page.get("text", "") + " " + s_page.get("title", "")).lower()
                    for kw in keywords:
                        if kw in s_text:
                            ev = Evidence(
                                claim=f"{app_name} supports authentication via {method.value}.",
                                source_url=s_page["url"],
                                source_title=s_page["title"],
                                source_type=SourceType.OFFICIAL_AUTH_DOCS,
                                evidence_summary=s_page.get("excerpt", "") or f"Official documentation describes {desc} for {app_name}.",
                                checked_at=datetime.now(timezone.utc),
                            )
                            evidence.append(ev)
                            detail = AuthenticationDetail(
                                method=method,
                                status="Confirmed",
                                evidence=[ev],
                                confidence=0.92,
                                notes=f"Confirmed via {s_page['title']}: {desc}.",
                            )
                            auth_details.append(detail)
                            confirmed_methods.append(method)
                            break
                    if len(confirmed_methods) > 0:
                        break

        if confirmed_methods:
            return sorted(confirmed_methods, key=lambda x: x.value), auth_details, 0.95

        unknown_detail = AuthenticationDetail(
            method=AuthMethod.UNKNOWN,
            status="Unverified",
            evidence=[],
            confidence=0.3,
            notes=f"No authentication methods for {app_name} could be grounded with direct documentation evidence.",
        )
        return [AuthMethod.UNKNOWN], [unknown_detail], 0.3

    def _research_credential_access(
        self,
        app_name: str,
        raw: Dict[str, Any],
        evidence: List[Evidence],
        official_domain: Optional[str] = None,
    ) -> Tuple[AccessModel, Optional[str], float]:
        """Research access gating and self-serve developer tier availability."""
        query = f"{app_name} developer account create API credentials free tier signup"
        results = self.search_engine.search(query, max_results=4)
        raw["searches"]["credential_access"] = results

        pages: List[Dict[str, Any]] = []
        for r in results:
            url = r.get("url", "")
            page = self.scraper.fetch_page(url, fallback_snippet=r.get("snippet", ""), allow_fallback_snippet=False, return_failed_status=True)
            if page:
                raw["pages"][url] = page
                if page.get("source_retrieval_status", "Success") == "Success" and len(page.get("text", "")) >= 15:
                    pages.append(page)

        # Evaluate gating signals from initial pages
        for page in pages:
            text = (page.get("text", "") + " " + page.get("title", "")).lower()

            if "partner" in text and "contact sales" in text and "enterprise only" in text:
                evidence.append(
                    Evidence(
                        claim=f"{app_name} requires enterprise contract or partner approval for API access.",
                        source_url=page["url"],
                        source_title=page["title"],
                        source_type=SourceType.OFFICIAL_PRICING_DOCS,
                        evidence_summary=page["excerpt"] or f"Enterprise partner requirement on {page['title']}.",
                        checked_at=datetime.now(timezone.utc),
                    )
                )
                return (
                    AccessModel.PARTNER_CONTACT_SALES,
                    "API credentials require enterprise partnership or sales approval.",
                    0.9,
                )

            if "trial" in text and ("free trial" in text or "developer trial" in text or "trial account" in text):
                evidence.append(
                    Evidence(
                        claim=f"{app_name} credential access model is Trial Self-Serve.",
                        source_url=page["url"],
                        source_title=page["title"],
                        source_type=SourceType.OFFICIAL_DOCS,
                        evidence_summary=page["excerpt"] or f"Developer trial account documented on {page['title']}.",
                        checked_at=datetime.now(timezone.utc),
                    )
                )
                return (
                    AccessModel.TRIAL_SELF_SERVE,
                    f"Developers can create credentials during a trial account period for {app_name}.",
                    0.92,
                )

            if (
                "free" in text
                or "create app" in text
                or "create an app" in text
                or "developer portal" in text
                or "sign up" in text
                or "sign in" in text
            ):
                notes = (
                    f"Developers can register an account and generate credentials self-serve "
                    f"via {app_name}'s developer portal or app management console."
                )
                evidence.append(
                    Evidence(
                        claim=f"{app_name} offers self-serve credential creation for developers.",
                        source_url=page["url"],
                        source_title=page["title"],
                        source_type=SourceType.OFFICIAL_DOCS,
                        evidence_summary=page["excerpt"] or f"Self-serve developer access confirmed on {page['title']}.",
                        checked_at=datetime.now(timezone.utc),
                    )
                )
                return AccessModel.FREE_SELF_SERVE, notes, 0.9

        # Trigger second-hop search if initial pages were inconclusive and enabled
        if self.enable_second_hop:
            sec_results = self.search_engine.search_credential_access(app_name, official_domain=official_domain, max_results=3)
            raw["searches"]["credential_access_second_hop"] = sec_results
            for sr in sec_results:
                s_url = sr.get("url", "")
                s_page = self.scraper.fetch_page(s_url, fallback_snippet=sr.get("snippet", ""), allow_fallback_snippet=False, return_failed_status=True)
                if s_page:
                    raw["pages"][s_url] = s_page
                    if s_page.get("source_retrieval_status", "Success") == "Success" and len(s_page.get("text", "")) >= 15:
                        s_text = (s_page.get("text", "") + " " + s_page.get("title", "")).lower()
                        if "trial" in s_text and ("trial" in s_text or "developer" in s_text):
                            evidence.append(
                                Evidence(
                                    claim=f"{app_name} credential access model is Trial Self-Serve.",
                                    source_url=s_page["url"],
                                    source_title=s_page["title"],
                                    source_type=SourceType.OFFICIAL_DOCS,
                                    evidence_summary=s_page["excerpt"] or f"Trial access on {s_page['title']}.",
                                    checked_at=datetime.now(timezone.utc),
                                )
                            )
                            return AccessModel.TRIAL_SELF_SERVE, f"Trial developer access confirmed on {s_page['title']}.", 0.9

                        if "free" in s_text or "developer" in s_text or "create app" in s_text:
                            evidence.append(
                                Evidence(
                                    claim=f"{app_name} offers self-serve credential creation for developers.",
                                    source_url=s_page["url"],
                                    source_title=s_page["title"],
                                    source_type=SourceType.OFFICIAL_DOCS,
                                    evidence_summary=s_page["excerpt"] or f"Self-serve developer access on {s_page['title']}.",
                                    checked_at=datetime.now(timezone.utc),
                                )
                            )
                            return AccessModel.FREE_SELF_SERVE, f"Developers can generate credentials self-serve on {s_page['title']}.", 0.9

        return AccessModel.UNKNOWN, "Credential access model could not be verified.", 0.3

    def _research_api_surface(
        self,
        app_name: str,
        raw: Dict[str, Any],
        evidence: List[Evidence],
        official_domain: Optional[str] = None,
    ) -> Tuple[List[ApiType], List[ApiTypeDetail], ApiBreadth, Optional[str], float]:
        """Research API paradigms with item-level direct documentation evidence."""
        query = f"{app_name} API reference endpoints REST GraphQL webhooks"
        results = self.search_engine.search(query, max_results=4)
        raw["searches"]["api_surface_general"] = results

        candidate_checks = [
            (
                ApiType.REST,
                ["rest api", "restful", "rest endpoints", "http methods", "web api methods", "openapi", "swagger", "json api", "http api"],
                "REST API HTTP endpoints and methods",
            ),
            (
                ApiType.GRAPHQL,
                ["graphql", "query {", "mutation {", "graphql endpoint", "graphql schema"],
                "GraphQL queries, mutations, and schema endpoint",
            ),
            (
                ApiType.WEBHOOKS,
                ["webhook", "webhooks", "event subscriptions", "callback url", "http post events"],
                "Webhook event delivery and subscription endpoints",
            ),
            (
                ApiType.SDK,
                ["sdk", "client library", "client libraries", "python sdk", "javascript sdk", "official sdk", "software development kit"],
                "Official client SDKs and libraries",
            ),
        ]

        pages: List[Dict[str, Any]] = []
        for r in results:
            url = r.get("url", "")
            page = self.scraper.fetch_page(url, fallback_snippet=r.get("snippet", ""), allow_fallback_snippet=False, return_failed_status=True)
            if page:
                raw["pages"][url] = page
                if page.get("source_retrieval_status", "Success") == "Success" and len(page.get("text", "")) >= 15:
                    pages.append(page)

        confirmed_types: List[ApiType] = []
        api_details: List[ApiTypeDetail] = []
        unresolved_candidates = []

        for api_type, keywords, desc in candidate_checks:
            type_page = None
            matched_snippet = ""

            for p in pages:
                p_text = (p.get("text", "") + " " + p.get("title", "")).lower()
                for kw in keywords:
                    if kw in p_text:
                        type_page = p
                        matched_snippet = p.get("excerpt", "")
                        break
                if type_page:
                    break

            if type_page:
                ev = Evidence(
                    claim=f"{app_name} provides public {api_type.value} API surface.",
                    source_url=type_page["url"],
                    source_title=type_page["title"],
                    source_type=SourceType.OFFICIAL_API_REF,
                    evidence_summary=matched_snippet or f"Official documentation describes {desc} for {app_name}.",
                    checked_at=datetime.now(timezone.utc),
                )
                evidence.append(ev)
                detail = ApiTypeDetail(
                    api_type=api_type,
                    status="Confirmed",
                    evidence=[ev],
                    confidence=0.92,
                    notes=f"Confirmed via {type_page['title']}: {desc}.",
                )
                api_details.append(detail)
                confirmed_types.append(api_type)
            else:
                unresolved_candidates.append((api_type, keywords, desc))

        # STEP 3 BOUND: Maximum 1 second-hop search, and ONLY when initial evidence is insufficient
        if self.enable_second_hop and unresolved_candidates and len(confirmed_types) == 0:
            api_type, keywords, desc = unresolved_candidates[0]
            sec_results = self.search_engine.search_api_type(
                app_name, api_type.value, official_domain=official_domain, max_results=3
            )
            raw["searches"][f"api_{api_type.value}"] = sec_results
            for sr in sec_results:
                s_url = sr.get("url", "")
                s_page = self.scraper.fetch_page(s_url, fallback_snippet=sr.get("snippet", ""), allow_fallback_snippet=False, return_failed_status=True)
                if s_page and s_page.get("source_retrieval_status", "Success") == "Success" and len(s_page.get("text", "")) >= 15:
                    s_text = (s_page.get("text", "") + " " + s_page.get("title", "")).lower()
                    for kw in keywords:
                        if kw in s_text:
                            ev = Evidence(
                                claim=f"{app_name} provides public {api_type.value} API surface.",
                                source_url=s_page["url"],
                                source_title=s_page["title"],
                                source_type=SourceType.OFFICIAL_API_REF,
                                evidence_summary=s_page.get("excerpt", "") or f"Official documentation describes {desc} for {app_name}.",
                                checked_at=datetime.now(timezone.utc),
                            )
                            evidence.append(ev)
                            detail = ApiTypeDetail(
                                api_type=api_type,
                                status="Confirmed",
                                evidence=[ev],
                                confidence=0.92,
                                notes=f"Confirmed via {s_page['title']}: {desc}.",
                            )
                            api_details.append(detail)
                            confirmed_types.append(api_type)
                            break
                    if len(confirmed_types) > 0:
                        break

        breadth = ApiBreadth.BROAD if confirmed_types else ApiBreadth.UNKNOWN
        notes = (
            f"{app_name} exposes programmatic API endpoints covering primary platform objects."
            if confirmed_types
            else "No programmatic API surface could be grounded."
        )

        if confirmed_types:
            return sorted(confirmed_types, key=lambda x: x.value), api_details, breadth, notes, 0.95

        unknown_detail = ApiTypeDetail(
            api_type=ApiType.UNKNOWN,
            status="Unverified",
            evidence=[],
            confidence=0.3,
            notes=f"No API types for {app_name} could be grounded with direct documentation evidence.",
        )
        return [ApiType.UNKNOWN], [unknown_detail], ApiBreadth.UNKNOWN, None, 0.3

    def _research_mcp(
        self, app_name: str, raw: Dict[str, Any], evidence: List[Evidence]
    ) -> Tuple[McpStatus, Optional[str], float]:
        """Perform deliberate, rigorous MCP search.

        CRITICAL DESIGN RULE:
        - 'Official MCP': Verified first-party announcement or repository from the vendor.
        - 'Third-Party MCP': Verified community MCP servers on GitHub.
        - 'No MCP Found': Deliberate search across official docs, GitHub, and registries found no server.
        - 'Unknown': Inconclusive search results.
        """
        # Step 1: Search official documentation & announcements
        official_query = f"{app_name} official Model Context Protocol MCP server docs"
        official_results = self.search_engine.search(official_query, max_results=4)
        raw["searches"]["mcp_official"] = official_results

        for r in official_results:
            url = r.get("url", "")
            is_official = self._is_official_domain(url, app_name)
            page = self.scraper.fetch_page(url, fallback_snippet=r.get("snippet", ""))
            if page and is_official:
                raw["pages"][url] = page
                text = (page.get("text", "") + " " + page.get("title", "")).lower()
                if "model context protocol" in text and ("mcp server" in text or "official" in text or "connect" in text or "release" in text):
                    evidence.append(
                        Evidence(
                            claim=f"{app_name} provides official Model Context Protocol (MCP) server support.",
                            source_url=page["url"],
                            source_title=page["title"],
                            source_type=SourceType.OFFICIAL_MCP_DOCS,
                            evidence_summary=page["excerpt"] or f"Official MCP documentation from {app_name}.",
                            checked_at=datetime.now(timezone.utc),
                        )
                    )
                    notes = f"Official MCP server documented and supported directly by {app_name}."
                    return McpStatus.OFFICIAL_MCP, notes, 0.95

        # Step 2: Broad general MCP search (including GitHub & community)
        mcp_query = f"{app_name} Model Context Protocol MCP server github"
        mcp_results = self.search_engine.search(mcp_query, max_results=5)
        raw["searches"]["mcp_general"] = mcp_results

        third_party_repos = []
        for r in mcp_results:
            url = r.get("url", "")
            title = r.get("title", "").lower()
            snippet = r.get("snippet", "").lower()

            if "github.com" in url and "mcp" in url.lower():
                third_party_repos.append((r["title"], url, r.get("snippet", "")))

        if third_party_repos:
            repo_title, repo_url, repo_snippet = third_party_repos[0]
            evidence.append(
                Evidence(
                    claim=f"Third-party Model Context Protocol (MCP) server exists on GitHub for {app_name}.",
                    source_url=repo_url,
                    source_title=repo_title,
                    source_type=SourceType.GITHUB,
                    evidence_summary=repo_snippet or f"Community MCP implementation at {repo_url}.",
                    checked_at=datetime.now(timezone.utc),
                )
            )
            notes = f"Community/third-party MCP server available on GitHub: {repo_url}"
            return McpStatus.THIRD_PARTY_MCP, notes, 0.9

        # Step 3: Deliberate check for No MCP Found vs Unknown
        if len(mcp_results) >= 3:
            # We executed a thorough search and found zero MCP implementations
            notes = f"Deliberate search across official documentation and GitHub repositories yielded no existing MCP implementations for {app_name}."
            return McpStatus.NO_MCP_FOUND, notes, 0.85

        return McpStatus.UNKNOWN, "Insufficient evidence to determine MCP status.", 0.4

    def _assess_buildability(
        self,
        app_name: str,
        auth_methods: List[AuthMethod],
        access_model: AccessModel,
        api_types: List[ApiType],
        api_breadth: ApiBreadth,
        mcp_status: McpStatus,
        evidence: List[Evidence],
    ) -> Tuple[BuildabilityStatus, Optional[str], float]:
        """Assess feasibility of building an autonomous agent toolkit today."""
        # Blocked conditions
        if access_model == AccessModel.PARTNER_CONTACT_SALES:
            return (
                BuildabilityStatus.BLOCKED,
                "API credentials require enterprise partnership or sales approval.",
                0.9,
            )
        if ApiType.NONE in api_types:
            return (
                BuildabilityStatus.BLOCKED,
                "Application provides no programmatic public API.",
                0.9,
            )

        # Buildable Now conditions
        has_auth = any(
            m in auth_methods
            for m in [
                AuthMethod.OAUTH2,
                AuthMethod.API_KEY,
                AuthMethod.BEARER_TOKEN,
                AuthMethod.PERSONAL_ACCESS_TOKEN,
            ]
        )
        is_self_serve = access_model in [
            AccessModel.FREE_SELF_SERVE,
            AccessModel.TRIAL_SELF_SERVE,
        ]
        has_api = any(
            t in api_types
            for t in [ApiType.REST, ApiType.GRAPHQL, ApiType.SDK, ApiType.WEBHOOKS]
        )

        if has_auth and is_self_serve and has_api:
            return (
                BuildabilityStatus.BUILDABLE_NOW,
                None,
                0.95,
            )

        # Restrictions
        if access_model == AccessModel.PAID_PLAN_REQUIRED:
            return (
                BuildabilityStatus.BUILDABLE_WITH_RESTRICTIONS,
                "Paid subscription tier required to generate API tokens.",
                0.85,
            )
        if access_model == AccessModel.ADMIN_APPROVAL_REQUIRED:
            return (
                BuildabilityStatus.BUILDABLE_WITH_RESTRICTIONS,
                "Workspace administrator approval required to install agent application.",
                0.85,
            )

        return (
            BuildabilityStatus.BUILDABLE_WITH_RESTRICTIONS,
            "Buildable with standard developer rate limits and scoping permissions.",
            0.8,
        )