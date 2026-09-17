"""
AI Product Ops Research System - 10-Application Pilot V2 Pipeline
=================================================================
Executes Step 6 Controlled Experiment:
- Runs improved ResearchAgent (item-level grounding + bounded second-hop search) on 10 apps
- Stores outputs isolated in data/pilot_v2/
- Runs hardened VerificationAgent
- Generates data/pilot_v2/pilot_research_report.json
- Generates data/pilot_v2/pilot_verification_report.json
- Generates data/pilot_v2/pilot_corrections.json
- Generates data/pilot_v2/comparison_report.json comparing V1 vs V2
- Supports --sample-3, --run-all, and --report-only modes
"""

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

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
    VerificationStatus,
)
from agent.researcher import ResearchAgent, get_slug
from agent.scraper import DocScraper
from agent.search import SearchEngine
from verification.verifier import VerificationAgent
from verification.models import (
    AppVerificationRecord,
    ClaimVerificationStatus,
    FieldVerificationResult,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pilot_v2_pipeline")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Old V1 Paths (Preserved)
V1_RESEARCH_REPORT = DATA_DIR / "pilot_research_report.json"
V1_VERIFICATION_REPORT = DATA_DIR / "pilot_verification_report.json"
V1_CORRECTIONS_REPORT = DATA_DIR / "pilot_corrections.json"

# New V2 Paths (Isolated)
V2_DIR = DATA_DIR / "pilot_v2"
V2_RESEARCH_DIR = V2_DIR / "research"
V2_RAW_DIR = V2_DIR / "research_raw"
V2_VERIFICATION_DIR = V2_DIR / "verification"
V2_LOG_FILE = V2_DIR / "research_log.jsonl"
V2_RESEARCH_REPORT = V2_DIR / "pilot_research_report.json"
V2_VERIFICATION_REPORT = V2_DIR / "pilot_verification_report.json"
V2_CORRECTIONS_REPORT = V2_DIR / "pilot_corrections.json"
V2_COMPARISON_REPORT = V2_DIR / "comparison_report.json"

ALL_PILOT_APPS = [
    {"id": 1, "app": "Salesforce", "category": "CRM and Sales"},
    {"id": 11, "app": "Zendesk", "category": "Support and Helpdesk"},
    {"id": 21, "app": "Slack", "category": "Communications and Messaging"},
    {"id": 35, "app": "Mailchimp", "category": "Marketing, Ads, Email and Social"},
    {"id": 41, "app": "Shopify", "category": "Ecommerce"},
    {"id": 55, "app": "Apify", "category": "Data, SEO and Scraping"},
    {"id": 61, "app": "GitHub", "category": "Developer, Infra and Data platforms"},
    {"id": 71, "app": "Notion", "category": "Productivity and Project Management"},
    {"id": 81, "app": "Stripe", "category": "Finance and Fintech"},
    {"id": 91, "app": "NotebookLM", "category": "AI, Research and Media-native"},
]

SAMPLE_3_APPS = [
    {"id": 1, "app": "Salesforce", "category": "CRM and Sales"},
    {"id": 21, "app": "Slack", "category": "Communications and Messaging"},
    {"id": 81, "app": "Stripe", "category": "Finance and Fintech"},
]


def load_existing_research_record(slug: str) -> Optional[AppResearchRecord]:
    candidate = V2_RESEARCH_DIR / f"{slug}.json"
    if candidate.exists():
        try:
            with open(candidate, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            return AppResearchRecord.model_validate(data)
        except Exception as e:
            logger.warning(f"Failed to load existing research record from {candidate}: {e}")
    return None


def load_existing_verification_record(slug: str) -> Optional[AppVerificationRecord]:
    candidate = V2_VERIFICATION_DIR / f"{slug}.json"
    if candidate.exists():
        try:
            with open(candidate, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            return AppVerificationRecord.model_validate(data)
        except Exception as e:
            logger.warning(f"Failed to load existing verification record from {candidate}: {e}")
    return None


def run_app_pipeline(
    app_meta: Dict[str, Any],
    research_agent: ResearchAgent,
    verifier: VerificationAgent,
    force_research: bool = False,
    force_verify: bool = False,
) -> Tuple[AppResearchRecord, AppVerificationRecord, Dict[str, Any]]:
    """Execute end-to-end research and verification for a single app."""
    app_id = app_meta["id"]
    app_name = app_meta["app"]
    category = app_meta["category"]
    slug = get_slug(app_name)

    start_time = time.time()
    logger.info(f"--- Processing {app_name} (ID: {app_id}, Category: {category}) ---")

    # Step 1: Research (Load or Execute)
    rec = None
    if not force_research:
        rec = load_existing_research_record(slug)
        if rec:
            logger.info(f"Loaded existing V2 research record for {app_name}")

    if not rec:
        logger.info(f"Running ResearchAgent for {app_name}...")
        rec = research_agent.research_app(app_name=app_name, app_id=app_id)

    # Step 2: Verification (Load or Execute)
    v_rec = None
    if not force_verify:
        v_rec = load_existing_verification_record(slug)
        if v_rec:
            logger.info(f"Loaded existing V2 verification record for {app_name}")

    if not v_rec:
        logger.info(f"Running VerificationAgent for {app_name}...")
        v_rec = verifier.verify_app(app_name=app_name, app_id=app_id, record=rec)

    elapsed = round(time.time() - start_time, 2)

    metrics = {
        "app": app_name,
        "app_id": app_id,
        "elapsed_seconds": elapsed,
        "auth_methods_count": len(rec.auth_methods),
        "auth_methods": [m.value for m in rec.auth_methods],
        "api_types_count": len(rec.api_types),
        "api_types": [t.value for t in rec.api_types],
        "evidence_items": len(rec.evidence),
        "overall_confidence": rec.overall_confidence,
        "claims_checked": v_rec.claims_checked,
        "claims_verified": v_rec.claims_verified,
        "corrections_made": v_rec.corrections_made,
        "verification_status": v_rec.overall_verification_status.value,
    }

    return rec, v_rec, metrics


def generate_research_report(records: Dict[str, AppResearchRecord]) -> Dict[str, Any]:
    """Generate first-pass quality report for V2."""
    total_attempted = len(records)
    completed_count = sum(1 for r in records.values() if r.research_status == ResearchStatus.COMPLETED)
    needs_verif_count = sum(1 for r in records.values() if r.research_status == ResearchStatus.NEEDS_VERIFICATION)
    failed_count = sum(1 for r in records.values() if r.research_status == ResearchStatus.FAILED)

    conf_list = [r.overall_confidence for r in records.values() if r.overall_confidence is not None]
    avg_conf = round(sum(conf_list) / len(conf_list), 2) if conf_list else 0.0

    evidence_counts = {r.app: len(r.evidence) for r in records.values()}

    unknown_counts = {
        "auth_methods": sum(1 for r in records.values() if AuthMethod.UNKNOWN in r.auth_methods),
        "access_model": sum(1 for r in records.values() if r.access_model == AccessModel.UNKNOWN),
        "api_types": sum(1 for r in records.values() if ApiType.UNKNOWN in r.api_types),
        "mcp_status": sum(1 for r in records.values() if r.mcp_status == McpStatus.UNKNOWN),
        "buildability": sum(1 for r in records.values() if r.buildability == BuildabilityStatus.UNKNOWN),
    }

    lowest_confidence_apps = sorted(
        [{"app": r.app, "category": r.category, "confidence": r.overall_confidence, "status": r.research_status.value} for r in records.values()],
        key=lambda x: x["confidence"] or 0.0,
    )

    failures = [
        {"app": r.app, "error": r.one_line_description}
        for r in records.values()
        if r.research_status == ResearchStatus.FAILED
    ]

    report = {
        "report_title": "10-Application Pilot V2: Grounded Research Quality Report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_apps_attempted": total_attempted,
        "completed": completed_count,
        "needs_verification": needs_verif_count,
        "failed": failed_count,
        "average_confidence": avg_conf,
        "evidence_count_per_app": evidence_counts,
        "unknown_count_per_major_field": unknown_counts,
        "applications_with_lowest_confidence": lowest_confidence_apps[:3],
        "failures": failures,
    }

    with open(V2_RESEARCH_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved V2 Research Quality Report to {V2_RESEARCH_REPORT}")
    return report


def generate_verification_and_corrections_reports(
    records: Dict[str, AppResearchRecord],
    verif_records: Dict[str, AppVerificationRecord],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Generate verification accuracy report and corrections log for V2."""
    total_claims = 0
    total_verified = 0
    total_contradicted = 0
    total_insufficient = 0
    total_corrections = 0

    first_pass_correct = 0
    field_stats = {
        "website": {"checked": 0, "first_pass_correct": 0, "verified": 0, "corrections": 0},
        "authentication": {"checked": 0, "first_pass_correct": 0, "verified": 0, "corrections": 0},
        "access_model": {"checked": 0, "first_pass_correct": 0, "verified": 0, "corrections": 0},
        "api_surface": {"checked": 0, "first_pass_correct": 0, "verified": 0, "corrections": 0},
        "mcp_status": {"checked": 0, "first_pass_correct": 0, "verified": 0, "corrections": 0},
        "buildability": {"checked": 0, "first_pass_correct": 0, "verified": 0, "corrections": 0},
    }

    all_corrections: List[Dict[str, Any]] = []
    correction_types: Dict[str, int] = {}
    new_evidence_count = 0

    for app_name, vr in verif_records.items():
        total_claims += vr.claims_checked
        total_verified += vr.claims_verified
        total_contradicted += vr.claims_contradicted
        total_insufficient += vr.claims_insufficient_evidence
        total_corrections += vr.corrections_made

        for field_name, f_res in vr.field_results.items():
            if field_name not in field_stats:
                continue

            field_stats[field_name]["checked"] += 1
            if f_res.verification_status == ClaimVerificationStatus.VERIFIED:
                field_stats[field_name]["verified"] += 1

            if not f_res.was_corrected and f_res.verification_status == ClaimVerificationStatus.VERIFIED:
                field_stats[field_name]["first_pass_correct"] += 1
                first_pass_correct += 1

            if f_res.was_corrected:
                field_stats[field_name]["corrections"] += 1
                cat = "other"
                if "API" in f_res.verification_notes or field_name == "api_surface":
                    cat = "unsupported API type"
                elif "auth" in f_res.verification_notes.lower() or field_name == "authentication":
                    cat = "unsupported authentication method"
                elif "gating" in f_res.verification_notes.lower() or field_name == "access_model":
                    cat = "unresolved credential gating"
                elif "MCP" in f_res.verification_notes or field_name == "mcp_status":
                    cat = "incorrect MCP classification"
                elif "buildab" in f_res.verification_notes.lower() or field_name == "buildability":
                    cat = "incorrect buildability"

                correction_types[cat] = correction_types.get(cat, 0) + 1

                all_corrections.append({
                    "app": vr.app,
                    "field": field_name,
                    "original_value": f_res.original_value,
                    "corrected_value": f_res.corrected_value,
                    "reason": f_res.verification_notes,
                    "verification_status": f_res.verification_status.value,
                    "verifier_confidence": f_res.verifier_confidence,
                })

            new_evidence_count += len(f_res.evidence)

    first_pass_acc = round((first_pass_correct / total_claims) * 100, 1) if total_claims else 0.0
    post_verif_acc = round((total_verified / total_claims) * 100, 1) if total_claims else 0.0
    corr_rate = round((total_corrections / total_claims) * 100, 1) if total_claims else 0.0

    verif_report = {
        "pilot_label": "10-application pilot V2 (improved grounding)",
        "sample_size_note": "10-application pilot V2. Not presented as statistically representative of all 100 apps.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_applications": len(verif_records),
        "total_claims_checked": total_claims,
        "verified_claims": total_verified,
        "contradicted_claims": total_contradicted,
        "insufficient_evidence_claims": total_insufficient,
        "corrections_made": total_corrections,
        "first_pass_accuracy": first_pass_acc,
        "post_verification_accuracy": post_verif_acc,
        "accuracy_by_field": {
            k: {
                "claims_checked": v["checked"],
                "first_pass_accuracy": round((v["first_pass_correct"] / v["checked"]) * 100, 1) if v["checked"] else 0.0,
                "post_verification_accuracy": round((v["verified"] / v["checked"]) * 100, 1) if v["checked"] else 0.0,
                "corrections_made": v["corrections"],
            }
            for k, v in field_stats.items()
        },
        "correction_rate": corr_rate,
        "new_evidence_items_discovered": new_evidence_count,
    }

    with open(V2_VERIFICATION_REPORT, "w", encoding="utf-8") as f:
        json.dump(verif_report, f, indent=2, ensure_ascii=False)

    corrections_report = {
        "pilot_label": "10-application pilot V2",
        "total_corrections": total_corrections,
        "most_common_correction_types": correction_types,
        "corrections": all_corrections,
    }

    with open(V2_CORRECTIONS_REPORT, "w", encoding="utf-8") as f:
        json.dump(corrections_report, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved V2 Verification Report to {V2_VERIFICATION_REPORT}")
    logger.info(f"Saved V2 Corrections Report to {V2_CORRECTIONS_REPORT}")
    return verif_report, corrections_report


def generate_comparison_report(
    v1_report_path: Path, v2_report_path: Path, out_path: Path
) -> Dict[str, Any]:
    """Generate comprehensive comparison report: Metric, Old Pilot (V1), Improved Pilot (V2), Difference."""
    with open(v1_report_path, "r", encoding="utf-8") as f:
        v1 = json.load(f)
    with open(v2_report_path, "r", encoding="utf-8") as f:
        v2 = json.load(f)

    def diff(v2_val, v1_val):
        return round(v2_val - v1_val, 2)

    comp = {
        "comparison_title": "10-Application Pilot Comparison: Baseline (V1) vs Grounded (V2)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "First-Pass Accuracy (%)": {
                "old_pilot_v1": v1["first_pass_accuracy"],
                "improved_pilot_v2": v2["first_pass_accuracy"],
                "difference": diff(v2["first_pass_accuracy"], v1["first_pass_accuracy"]),
            },
            "Post-Verification Accuracy (%)": {
                "old_pilot_v1": v1["post_verification_accuracy"],
                "improved_pilot_v2": v2["post_verification_accuracy"],
                "difference": diff(v2["post_verification_accuracy"], v1["post_verification_accuracy"]),
            },
            "Corrections Made (Count)": {
                "old_pilot_v1": v1["corrections_made"],
                "improved_pilot_v2": v2["corrections_made"],
                "difference": v2["corrections_made"] - v1["corrections_made"],
            },
            "Insufficient Evidence Claims (Count)": {
                "old_pilot_v1": v1["insufficient_evidence_claims"],
                "improved_pilot_v2": v2["insufficient_evidence_claims"],
                "difference": v2["insufficient_evidence_claims"] - v1["insufficient_evidence_claims"],
            },
        },
        "field_accuracy_comparison": {},
    }

    v1_fields = v1.get("accuracy_by_field", {})
    v2_fields = v2.get("accuracy_by_field", {})

    for field in ["authentication", "api_surface", "access_model", "mcp_status", "buildability", "website"]:
        f1 = v1_fields.get(field, {})
        f2 = v2_fields.get(field, {})
        comp["field_accuracy_comparison"][field] = {
            "first_pass_accuracy_v1": f1.get("first_pass_accuracy", 0.0),
            "first_pass_accuracy_v2": f2.get("first_pass_accuracy", 0.0),
            "first_pass_accuracy_diff": diff(f2.get("first_pass_accuracy", 0.0), f1.get("first_pass_accuracy", 0.0)),
            "post_verif_accuracy_v1": f1.get("post_verification_accuracy", 0.0),
            "post_verif_accuracy_v2": f2.get("post_verification_accuracy", 0.0),
            "post_verif_accuracy_diff": diff(f2.get("post_verification_accuracy", 0.0), f1.get("post_verification_accuracy", 0.0)),
            "corrections_v1": f1.get("corrections_made", 0),
            "corrections_v2": f2.get("corrections_made", 0),
            "corrections_diff": f2.get("corrections_made", 0) - f1.get("corrections_made", 0),
        }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(comp, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved Comparison Report to {out_path}")
    return comp


def main():
    parser = argparse.ArgumentParser(description="Pilot V2 Pipeline")
    parser.add_argument("--sample-3", action="store_true", help="Run validation sample of 3 apps (Salesforce, Slack, Stripe)")
    parser.add_argument("--run-all", action="store_true", help="Run full 10-app pilot V2")
    parser.add_argument("--report-only", action="store_true", help="Generate reports from existing files")
    parser.add_argument("--force-research", action="store_true", help="Force re-running research even if file exists")
    parser.add_argument("--force-verify", action="store_true", help="Force re-running verification even if file exists")
    args = parser.parse_args()

    # Ensure output directories exist
    V2_RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    V2_RAW_DIR.mkdir(parents=True, exist_ok=True)
    V2_VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)

    target_apps = ALL_PILOT_APPS
    if args.sample_3:
        target_apps = SAMPLE_3_APPS

    print("=" * 75)
    print(f" PILOT V2 PIPELINE - TARGETING {len(target_apps)} APPLICATIONS")
    print("=" * 75)

    # Shared search engine and scraper for optimal caching and rate-limit friendliness
    scraper = DocScraper(timeout=15.0)
    search_engine = SearchEngine(max_retries=1, delay_between_calls=0.5)

    research_agent = ResearchAgent(
        search_engine=search_engine,
        scraper=scraper,
        research_dir=V2_RESEARCH_DIR,
        raw_dir=V2_RAW_DIR,
        log_file=V2_LOG_FILE,
        version="2.0.0",
    )

    verifier = VerificationAgent(
        search_engine=search_engine,
        scraper=scraper,
        research_dir=V2_RESEARCH_DIR,
        verification_dir=V2_VERIFICATION_DIR,
        metrics_file=V2_DIR / "verification_metrics.json",
        version="2.0.0",
    )

    research_records: Dict[str, AppResearchRecord] = {}
    verif_records: Dict[str, AppVerificationRecord] = {}
    app_timings: List[Dict[str, Any]] = []

    overall_start = time.time()

    if not args.report_only:
        for idx, app_meta in enumerate(target_apps, start=1):
            print(f"\n[{idx:02d}/{len(target_apps)}] {app_meta['app']} ({app_meta['category']})")
            rec, v_rec, metrics = run_app_pipeline(
                app_meta=app_meta,
                research_agent=research_agent,
                verifier=verifier,
                force_research=args.force_research,
                force_verify=args.force_verify,
            )
            research_records[app_meta["app"]] = rec
            verif_records[app_meta["app"]] = v_rec
            app_timings.append(metrics)

            print(f"       Runtime: {metrics['elapsed_seconds']}s")
            print(f"       Auth Methods: {metrics['auth_methods']}")
            print(f"       API Types: {metrics['api_types']}")
            print(f"       Verified: {metrics['claims_verified']}/{metrics['claims_checked']} | Corrections: {metrics['corrections_made']}")
    else:
        # Load existing files
        for app_meta in target_apps:
            slug = get_slug(app_meta["app"])
            rec = load_existing_research_record(slug)
            v_rec = load_existing_verification_record(slug)
            if rec:
                research_records[app_meta["app"]] = rec
            if v_rec:
                verif_records[app_meta["app"]] = v_rec

    total_time = round(time.time() - overall_start, 2)

    # Print summary metrics for the run
    print("\n" + "=" * 75)
    print(" EXECUTION PERFORMANCE & RESOURCE CONSUMPTION SUMMARY")
    print("=" * 75)
    print(f"Total Apps Processed: {len(research_records)}")
    print(f"Total Elapsed Time:   {total_time}s")
    if app_timings:
        avg_app_time = round(sum(m["elapsed_seconds"] for m in app_timings) / len(app_timings), 2)
        print(f"Avg Time Per App:     {avg_app_time}s")
    print(f"Total Search Calls:   {search_engine.total_searches} (Cache hits: {search_engine.cache_hits}, Second-hop: {search_engine.second_hop_searches})")
    print(f"Total Page Fetches:   {scraper.total_fetches} (Cache hits: {scraper.cache_hits}, Failed URLs skipped: {scraper.failed_hits})")

    # Generate reports if running on all 10 apps
    if len(verif_records) == 10:
        print("\n" + "=" * 75)
        print(" GENERATING FULL 10-APP PILOT V2 REPORTS")
        print("=" * 75)
        generate_research_report(research_records)
        generate_verification_and_corrections_reports(research_records, verif_records)
        comp = generate_comparison_report(V1_VERIFICATION_REPORT, V2_VERIFICATION_REPORT, V2_COMPARISON_REPORT)
        print("\n" + "=" * 75)
        print(" COMPARISON SUMMARY (V1 vs V2):")
        print("=" * 75)
        print(json.dumps(comp["summary"], indent=2))
    elif args.sample_3:
        print("\n" + "=" * 75)
        print(" 3-APP SAMPLE VALIDATION COMPLETE")
        print("=" * 75)
        for m in app_timings:
            print(f"- {m['app']}: {m['elapsed_seconds']}s, Auth: {m['auth_methods']}, APIs: {m['api_types']}, Verified: {m['claims_verified']}/{m['claims_checked']}, Corrections: {m['corrections_made']}")


if __name__ == "__main__":
    main()
