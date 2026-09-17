"""
AI Product Ops Research System - Full 100-Application Production Pipeline
==========================================================================
Executes Step 7: Full 100-Application Production Research:
- Reads all 100 applications from data/apps.csv
- Uses stable V1 research methodology (operationally practical and bounded)
- Retains all hardened verification rules
- Saves original research to data/production/research/
- Saves raw research dumps to data/production/research_raw/
- Saves verification audit records to data/production/verification/
- Saves corrected/verified records to data/production/verified/
- Generates:
  * data/production/research_report.json
  * data/production/verification_report.json
  * data/production/corrections.json
  * data/production/metrics.json
  * data/production/run_log.jsonl
- Preserves all pilot files in data/research/, data/verification/, data/pilot_*, data/pilot_v2/
- Supports interruption and incremental resumption
"""

import argparse
import csv
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
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
logger = logging.getLogger("production_pipeline")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
APPS_CSV = DATA_DIR / "apps.csv"

# Production Output Paths
PROD_DIR = DATA_DIR / "production"
PROD_RAW_DIR = PROD_DIR / "research_raw"
PROD_RESEARCH_DIR = PROD_DIR / "research"
PROD_VERIFICATION_DIR = PROD_DIR / "verification"
PROD_VERIFIED_DIR = PROD_DIR / "verified"

PROD_RUN_LOG = PROD_DIR / "run_log.jsonl"
PROD_RESEARCH_REPORT = PROD_DIR / "research_report.json"
PROD_VERIFICATION_REPORT = PROD_DIR / "verification_report.json"
PROD_CORRECTIONS_REPORT = PROD_DIR / "corrections.json"
PROD_METRICS_REPORT = PROD_DIR / "metrics.json"

# Pilot V1 Sources (for initial seeding of the 10 pilot apps)
PILOT_V1_RESEARCH_DIR = DATA_DIR / "research"
PILOT_V1_VERIF_DIR = DATA_DIR / "verification"
PILOT_V1_RAW_DIR = DATA_DIR / "research_raw"


def ensure_production_directories():
    """Create all isolated production directories."""
    PROD_RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROD_RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    PROD_VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    PROD_VERIFIED_DIR.mkdir(parents=True, exist_ok=True)


def seed_from_pilot_v1():
    """Copy the 10 completed pilot V1 records to production so we don't re-research them."""
    if not PILOT_V1_RESEARCH_DIR.exists():
        return

    seeded_count = 0
    for res_file in PILOT_V1_RESEARCH_DIR.glob("*.json"):
        target_res = PROD_RESEARCH_DIR / res_file.name
        if not target_res.exists():
            shutil.copy2(res_file, target_res)
            seeded_count += 1

        raw_file = PILOT_V1_RAW_DIR / res_file.name
        target_raw = PROD_RAW_DIR / res_file.name
        if raw_file.exists() and not target_raw.exists():
            shutil.copy2(raw_file, target_raw)

        verif_file = PILOT_V1_VERIF_DIR / res_file.name
        target_verif = PROD_VERIFICATION_DIR / res_file.name
        if verif_file.exists() and not target_verif.exists():
            shutil.copy2(verif_file, target_verif)

        target_verified = PROD_VERIFIED_DIR / res_file.name
        if verif_file.exists() and not target_verified.exists():
            try:
                with open(verif_file, "r", encoding="utf-8-sig") as vf:
                    v_data = json.load(vf)
                    v_rec = AppVerificationRecord.model_validate(v_data)
                with open(target_verified, "w", encoding="utf-8") as out_vf:
                    out_vf.write(v_rec.verified_record.model_dump_json(indent=2))
            except Exception as e:
                logger.warning(f"Could not extract verified record from {verif_file}: {e}")

    if seeded_count > 0:
        logger.info(f"Seeded {seeded_count} validated pilot records into production directory.")


def load_apps() -> List[Dict[str, Any]]:
    """Load and validate all 100 applications from apps.csv."""
    with open(APPS_CSV, mode="r", encoding="utf-8-sig") as f:
        reader = list(csv.DictReader(f))

    assert len(reader) == 100, f"Expected 100 apps, found {len(reader)}"
    apps = []
    for r in reader:
        apps.append({
            "id": int(r["id"].strip()),
            "app": r["app"].strip(),
            "category": r["category"].strip(),
            "website": r.get("website", "").strip(),
        })
    return sorted(apps, key=lambda x: x["id"])


def run_single_app(
    app_meta: Dict[str, Any],
    research_agent: ResearchAgent,
    verifier: VerificationAgent,
    app_index: int,
    total_apps: int,
) -> Tuple[AppResearchRecord, AppVerificationRecord, AppResearchRecord, Dict[str, Any]]:
    """Run research, verification, and correction for a single app."""
    app_id = app_meta["id"]
    app_name = app_meta["app"]
    slug = get_slug(app_name)
    category = app_meta["category"]

    start_time = time.time()

    # Step 1: Research
    res_path = PROD_RESEARCH_DIR / f"{slug}.json"
    if res_path.exists():
        try:
            with open(res_path, "r", encoding="utf-8-sig") as f:
                res_rec = AppResearchRecord.model_validate(json.load(f))
        except Exception:
            res_rec = research_agent.research_app(app_name=app_name, app_id=app_id)
    else:
        res_rec = research_agent.research_app(app_name=app_name, app_id=app_id)

    print(f"[{app_index}/{total_apps}] {app_name} -- research complete")

    # Step 2: Verification
    verif_path = PROD_VERIFICATION_DIR / f"{slug}.json"
    if verif_path.exists():
        try:
            with open(verif_path, "r", encoding="utf-8-sig") as f:
                verif_rec = AppVerificationRecord.model_validate(json.load(f))
        except Exception:
            verif_rec = verifier.verify_app(app_name=app_name, app_id=app_id, record=res_rec)
    else:
        verif_rec = verifier.verify_app(app_name=app_name, app_id=app_id, record=res_rec)

    print(f"[{app_index}/{total_apps}] {app_name} -- verification complete")

    # Step 3: Verified Record Persistence
    verified_rec = verif_rec.verified_record
    verified_path = PROD_VERIFIED_DIR / f"{slug}.json"
    with open(verified_path, "w", encoding="utf-8") as f:
        f.write(verified_rec.model_dump_json(indent=2))

    elapsed = round(time.time() - start_time, 2)

    app_metric = {
        "id": app_id,
        "app": app_name,
        "category": category,
        "elapsed_seconds": elapsed,
        "research_status": res_rec.research_status.value,
        "verification_status": verif_rec.overall_verification_status.value,
        "claims_checked": verif_rec.claims_checked,
        "claims_verified": verif_rec.claims_verified,
        "claims_insufficient": verif_rec.claims_insufficient_evidence,
        "claims_contradicted": verif_rec.claims_contradicted,
        "corrections_made": verif_rec.corrections_made,
        "evidence_items": len(res_rec.evidence),
        "overall_confidence": res_rec.overall_confidence,
    }

    # Append to run_log.jsonl immediately
    with open(PROD_RUN_LOG, "a", encoding="utf-8") as f:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **app_metric,
        }
        f.write(json.dumps(log_entry) + "\n")

    return res_rec, verif_rec, verified_rec, app_metric


def generate_all_production_reports(
    research_records: Dict[str, AppResearchRecord],
    verif_records: Dict[str, AppVerificationRecord],
    verified_records: Dict[str, AppResearchRecord],
    app_timings: List[Dict[str, Any]],
    search_engine: SearchEngine,
    scraper: DocScraper,
    total_elapsed: float,
):
    """Generate all production reports required by Step 7."""
    # 1. Research Quality Report
    total_apps = len(research_records)
    completed_count = sum(1 for r in research_records.values() if r.research_status == ResearchStatus.COMPLETED)
    needs_verif_count = sum(1 for r in research_records.values() if r.research_status == ResearchStatus.NEEDS_VERIFICATION)
    failed_count = sum(1 for r in research_records.values() if r.research_status == ResearchStatus.FAILED)

    conf_list = [r.overall_confidence for r in research_records.values() if r.overall_confidence is not None]
    avg_conf = round(sum(conf_list) / len(conf_list), 2) if conf_list else 0.0

    evidence_counts = {r.app: len(r.evidence) for r in research_records.values()}

    unknown_counts = {
        "auth_methods": sum(1 for r in research_records.values() if AuthMethod.UNKNOWN in r.auth_methods),
        "access_model": sum(1 for r in research_records.values() if r.access_model == AccessModel.UNKNOWN),
        "api_types": sum(1 for r in research_records.values() if ApiType.UNKNOWN in r.api_types),
        "mcp_status": sum(1 for r in research_records.values() if r.mcp_status == McpStatus.UNKNOWN),
        "buildability": sum(1 for r in research_records.values() if r.buildability == BuildabilityStatus.UNKNOWN),
    }

    research_report = {
        "report_title": "100-Application Production Research Quality Report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_apps_attempted": total_apps,
        "completed": completed_count,
        "needs_verification": needs_verif_count,
        "failed": failed_count,
        "average_confidence": avg_conf,
        "unknown_count_per_major_field": unknown_counts,
        "evidence_counts_summary": {
            "total_evidence_collected": sum(evidence_counts.values()),
            "average_evidence_per_app": round(sum(evidence_counts.values()) / total_apps, 2) if total_apps else 0.0,
            "min_evidence": min(evidence_counts.values()) if evidence_counts else 0,
            "max_evidence": max(evidence_counts.values()) if evidence_counts else 0,
        },
    }

    with open(PROD_RESEARCH_REPORT, "w", encoding="utf-8") as f:
        json.dump(research_report, f, indent=2, ensure_ascii=False)

    # 2. Verification Report & Corrections Log
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
    insufficient_rate = round((total_insufficient / total_claims) * 100, 1) if total_claims else 0.0

    verif_report = {
        "report_title": "100-Application Production Verification Report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_applications": len(verif_records),
        "total_claims_checked": total_claims,
        "verified_claims": total_verified,
        "contradicted_claims": total_contradicted,
        "insufficient_evidence_claims": total_insufficient,
        "corrections_made": total_corrections,
        "first_pass_accuracy": first_pass_acc,
        "post_verification_accuracy": post_verif_acc,
        "correction_rate": corr_rate,
        "insufficient_evidence_rate": insufficient_rate,
        "accuracy_by_field": {
            k: {
                "claims_checked": v["checked"],
                "first_pass_accuracy": round((v["first_pass_correct"] / v["checked"]) * 100, 1) if v["checked"] else 0.0,
                "post_verification_accuracy": round((v["verified"] / v["checked"]) * 100, 1) if v["checked"] else 0.0,
                "corrections_made": v["corrections"],
            }
            for k, v in field_stats.items()
        },
        "new_evidence_items_discovered": new_evidence_count,
    }

    with open(PROD_VERIFICATION_REPORT, "w", encoding="utf-8") as f:
        json.dump(verif_report, f, indent=2, ensure_ascii=False)

    corrections_report = {
        "report_title": "100-Application Production Corrections Log",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_corrections": total_corrections,
        "most_common_correction_types": correction_types,
        "corrections": all_corrections,
    }

    with open(PROD_CORRECTIONS_REPORT, "w", encoding="utf-8") as f:
        json.dump(corrections_report, f, indent=2, ensure_ascii=False)

    # 3. Comprehensive Production Metrics Report
    from collections import Counter
    cat_counts = Counter(r.category for r in verified_records.values())

    # Buildability breakdown
    build_counts = Counter(r.buildability.value for r in verified_records.values())
    mcp_counts = Counter(r.mcp_status.value for r in verified_records.values())
    access_counts = Counter(r.access_model.value for r in verified_records.values())

    metrics_report = {
        "report_title": "100-Application Production Metrics & System Performance",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_summary": {
            "total_applications": len(verified_records),
            "categories_count": len(cat_counts),
            "applications_per_category": dict(cat_counts),
        },
        "accuracy_and_quality": {
            "first_pass_claim_accuracy": first_pass_acc,
            "post_verification_claim_accuracy": post_verif_acc,
            "correction_count": total_corrections,
            "correction_rate": corr_rate,
            "insufficient_evidence_rate": insufficient_rate,
            "average_confidence": avg_conf,
            "field_level_verification_accuracy": verif_report["accuracy_by_field"],
        },
        "portfolio_insights": {
            "buildability_breakdown": dict(build_counts),
            "mcp_status_breakdown": dict(mcp_counts),
            "access_model_breakdown": dict(access_counts),
        },
        "system_performance": {
            "total_runtime_seconds": round(total_elapsed, 2),
            "average_seconds_per_app": round(total_elapsed / total_apps, 2) if total_apps else 0.0,
            "searches_executed": search_engine.total_searches,
            "search_cache_hits": search_engine.cache_hits,
            "second_hop_searches": search_engine.second_hop_searches,
            "page_fetches_executed": scraper.total_fetches,
            "page_cache_hits": scraper.cache_hits,
            "failed_urls_prevented": scraper.failed_hits,
        },
        "metrics_provenance": {
            "measured_metrics": [
                "total_applications",
                "categories_count",
                "first_pass_claim_accuracy",
                "post_verification_claim_accuracy",
                "correction_count",
                "correction_rate",
                "insufficient_evidence_rate",
                "average_confidence",
                "field_level_verification_accuracy",
                "runtime",
                "searches",
                "page_fetches",
            ],
            "inferred_metrics": [
                "buildability_status (heuristic multi-factor determination)",
                "main_blocker (rule-based extraction)",
            ],
            "unavailable_metrics": [
                "ground_truth_accuracy_against_human_oracle (human verification of 100 apps not performed in this autonomous pass)",
            ],
        },
    }

    with open(PROD_METRICS_REPORT, "w", encoding="utf-8") as f:
        json.dump(metrics_report, f, indent=2, ensure_ascii=False)

    print(f"\nSaved Production Research Report to {PROD_RESEARCH_REPORT}")
    print(f"Saved Production Verification Report to {PROD_VERIFICATION_REPORT}")
    print(f"Saved Production Corrections Report to {PROD_CORRECTIONS_REPORT}")
    print(f"Saved Production Metrics Report to {PROD_METRICS_REPORT}")


def main():
    parser = argparse.ArgumentParser(description="Full 100-Application Production Research Pipeline")
    parser.add_argument("--batch-size", type=int, default=100, help="Number of apps to process")
    parser.add_argument("--start-idx", type=int, default=1, help="Starting app index (1-based)")
    parser.add_argument("--seed-pilot", action="store_true", default=True, help="Seed pilot V1 records")
    args = parser.parse_args()

    ensure_production_directories()

    if args.seed_pilot:
        seed_from_pilot_v1()

    apps = load_apps()
    total_apps = len(apps)

    print("=" * 75)
    print(f" FULL 100-APPLICATION PRODUCTION RESEARCH PIPELINE")
    print("=" * 75)
    print(f"Total Applications: {total_apps}")
    print(f"Methodology: Stable V1 Research (Bounded & Fast) + Hardened Verification")
    print(f"Production Dir: {PROD_DIR}\n")

    # Shared search engine and scraper with caching and courteous limits
    scraper = DocScraper(timeout=15.0)
    search_engine = SearchEngine(max_retries=1, delay_between_calls=0.3)

    # Stable V1 researcher: enable_second_hop=False for operational safety and speed
    research_agent = ResearchAgent(
        search_engine=search_engine,
        scraper=scraper,
        research_dir=PROD_RESEARCH_DIR,
        raw_dir=PROD_RAW_DIR,
        log_file=PROD_RUN_LOG,
        version="1.0.0",
        enable_second_hop=False,
    )

    verifier = VerificationAgent(
        search_engine=search_engine,
        scraper=scraper,
        research_dir=PROD_RESEARCH_DIR,
        verification_dir=PROD_VERIFICATION_DIR,
        metrics_file=PROD_DIR / "verification_metrics.json",
        version="1.0.0",
    )

    research_records: Dict[str, AppResearchRecord] = {}
    verif_records: Dict[str, AppVerificationRecord] = {}
    verified_records: Dict[str, AppResearchRecord] = {}
    app_timings: List[Dict[str, Any]] = []

    overall_start = time.time()

    for idx, app_meta in enumerate(apps, start=1):
        if idx < args.start_idx:
            continue
        if idx >= args.start_idx + args.batch_size:
            break

        try:
            res_rec, verif_rec, verified_rec, timing = run_single_app(
                app_meta=app_meta,
                research_agent=research_agent,
                verifier=verifier,
                app_index=idx,
                total_apps=total_apps,
            )
            research_records[app_meta["app"]] = res_rec
            verif_records[app_meta["app"]] = verif_rec
            verified_records[app_meta["app"]] = verified_rec
            app_timings.append(timing)

        except Exception as e:
            logger.error(f"Error processing {app_meta['app']}: {e}", exc_info=True)

        # Courtesy sleep to respect public search engines
        time.sleep(0.3)

    total_elapsed = time.time() - overall_start

    # Load all 100 production records for final aggregation
    for app_meta in apps:
        app_name = app_meta["app"]
        slug = get_slug(app_name)
        res_file = PROD_RESEARCH_DIR / f"{slug}.json"
        verif_file = PROD_VERIFICATION_DIR / f"{slug}.json"
        verified_file = PROD_VERIFIED_DIR / f"{slug}.json"

        if res_file.exists() and app_name not in research_records:
            try:
                with open(res_file, "r", encoding="utf-8-sig") as f:
                    research_records[app_name] = AppResearchRecord.model_validate(json.load(f))
            except Exception:
                pass

        if verif_file.exists() and app_name not in verif_records:
            try:
                with open(verif_file, "r", encoding="utf-8-sig") as f:
                    verif_records[app_name] = AppVerificationRecord.model_validate(json.load(f))
            except Exception:
                pass

        if verified_file.exists() and app_name not in verified_records:
            try:
                with open(verified_file, "r", encoding="utf-8-sig") as f:
                    verified_records[app_name] = AppResearchRecord.model_validate(json.load(f))
            except Exception:
                pass

    print("\n" + "=" * 75)
    print(f" PRODUCTION PIPELINE SUMMARY: {len(verified_records)}/{total_apps} APPLICATIONS")
    print("=" * 75)
    print(f"Total Runtime: {round(total_elapsed, 2)}s")
    if app_timings:
        print(f"Avg Time Per App: {round(total_elapsed / len(app_timings), 2)}s")
    print(f"Searches: {search_engine.total_searches} (Cache hits: {search_engine.cache_hits})")
    print(f"Page Fetches: {scraper.total_fetches} (Cache hits: {scraper.cache_hits}, Blacklisted: {scraper.failed_hits})")

    # Generate all reports
    generate_all_production_reports(
        research_records=research_records,
        verif_records=verif_records,
        verified_records=verified_records,
        app_timings=app_timings,
        search_engine=search_engine,
        scraper=scraper,
        total_elapsed=total_elapsed,
    )


if __name__ == "__main__":
    main()
