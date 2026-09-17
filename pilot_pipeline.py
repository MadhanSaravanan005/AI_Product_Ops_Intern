"""
AI Product Ops Research System - 10-Application Pilot Pipeline
==============================================================
Orchestrates:
- Phase A: First-pass research across 10 target applications
- Phase B: First-pass quality report (data/pilot_research_report.json)
- Phase C: Independent hardened verification across the 10 applications
- Phase D: Pilot accuracy & verification metrics (data/pilot_verification_report.json)
- Phase E: Correction analysis & classification (data/pilot_corrections.json)
- Phase F: Failure analysis and weakness diagnosis
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

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
from verification.verifier import VerificationAgent
from verification.models import (
    AppVerificationRecord,
    ClaimVerificationStatus,
    FieldVerificationResult,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pilot_pipeline")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RESEARCH_DIR = DATA_DIR / "research"
RAW_DIR = DATA_DIR / "research_raw"
VERIFICATION_DIR = DATA_DIR / "verification"

PILOT_APPS = [
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


def run_phase_a(research_agent: ResearchAgent) -> Dict[str, AppResearchRecord]:
    """Phase A: First-Pass Research across the 10 pilot applications."""
    print("\n" + "=" * 75)
    print(" PHASE A: FIRST-PASS RESEARCH (10 PILOT APPLICATIONS)")
    print("=" * 75)

    records: Dict[str, AppResearchRecord] = {}

    for item in PILOT_APPS:
        app_id = item["id"]
        app_name = item["app"]
        slug = get_slug(app_name)
        existing_file = RESEARCH_DIR / f"{slug}.json"

        # Preserve Slack's existing first-pass research record
        if app_name.lower() == "slack" and existing_file.exists():
            print(f"[{app_id:02d}/10] Preserving authentic first-pass research for {app_name} from {existing_file}")
            with open(existing_file, "r", encoding="utf-8-sig") as f:
                rec = AppResearchRecord.model_validate(json.load(f))
            records[app_name] = rec
            continue

        print(f"\n[{app_id:02d}/10] Conducting autonomous research for: {app_name} ({item['category']})")
        try:
            record = research_agent.research_app(app_name=app_name, app_id=app_id)
            records[app_name] = record
            print(f"       Status: {record.research_status.value} | Confidence: {record.overall_confidence} | Evidence Items: {len(record.evidence)}")
            print(f"       Auth: {[m.value for m in record.auth_methods]} | Access: {record.access_model.value} | MCP: {record.mcp_status.value}")
        except Exception as e:
            logger.error(f"Failed research for {app_name}: {e}", exc_info=True)
            failed_rec = AppResearchRecord(
                id=app_id,
                app=app_name,
                category=item["category"],
                one_line_description=f"{app_name} research failed due to runtime error.",
                auth_methods=[AuthMethod.UNKNOWN],
                access_model=AccessModel.UNKNOWN,
                api_types=[ApiType.UNKNOWN],
                api_breadth=ApiBreadth.UNKNOWN,
                mcp_status=McpStatus.UNKNOWN,
                buildability=BuildabilityStatus.UNKNOWN,
                evidence=[],
                overall_confidence=0.0,
                researched_at=datetime.now(timezone.utc),
                research_status=ResearchStatus.FAILED,
                verification_status=VerificationStatus.NOT_VERIFIED,
            )
            records[app_name] = failed_rec

        time.sleep(1.5)  # Rate-limit courtesy delay between apps

    return records


def run_phase_b(records: Dict[str, AppResearchRecord]) -> Dict[str, Any]:
    """Phase B: Generate first-pass quality report (data/pilot_research_report.json)."""
    print("\n" + "=" * 75)
    print(" PHASE B: FIRST-PASS QUALITY REPORT")
    print("=" * 75)

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
        "report_title": "10-Application Pilot: First-Pass Research Quality Report",
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

    report_path = DATA_DIR / "pilot_research_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Saved first-pass quality report to {report_path}")
    print(f" - Attempted: {total_attempted} | Completed: {completed_count} | Needs Verification: {needs_verif_count} | Failed: {failed_count}")
    print(f" - Average First-Pass Confidence: {avg_conf}")
    print(f" - Unknowns: Access Model ({unknown_counts['access_model']}), MCP ({unknown_counts['mcp_status']}), APIs ({unknown_counts['api_types']})")

    return report


def run_phase_c(verifier: VerificationAgent, records: Dict[str, AppResearchRecord]) -> Dict[str, AppVerificationRecord]:
    """Phase C: Run Hardened Verification on the 10 Pilot Applications."""
    print("\n" + "=" * 75)
    print(" PHASE C: HARDENED INDEPENDENT VERIFICATION (10 PILOT APPLICATIONS)")
    print("=" * 75)

    v_records: Dict[str, AppVerificationRecord] = {}

    for item in PILOT_APPS:
        app_id = item["id"]
        app_name = item["app"]
        rec = records[app_name]

        print(f"\n[{app_id:02d}/10] Verifying claims for: {app_name}")
        try:
            v_rec = verifier.verify_app(app_name=app_name, app_id=app_id, record=rec)
            v_records[app_name] = v_rec
            print(f"       Audit Result: {v_rec.overall_verification_status.value} | Claims Verified: {v_rec.claims_verified}/{v_rec.claims_checked} | Corrections: {v_rec.corrections_made}")
        except Exception as e:
            logger.error(f"Verification failed for {app_name}: {e}", exc_info=True)

        time.sleep(1.0)

    return v_records


def run_phase_d_e_f(
    records: Dict[str, AppResearchRecord],
    v_records: Dict[str, AppVerificationRecord],
    first_pass_report: Dict[str, Any],
):
    """Phase D, E, F: Compute Pilot Metrics, Correction Analysis, and Failure Diagnosis."""
    print("\n" + "=" * 75)
    print(" PHASE D & E: METRICS & CORRECTION ANALYSIS")
    print("=" * 75)

    total_claims = 0
    verified_claims = 0
    contradicted_claims = 0
    insufficient_claims = 0
    corrections_made = 0
    first_pass_correct = 0

    field_stats: Dict[str, Dict[str, Any]] = {}
    corrections_list: List[Dict[str, Any]] = []

    for v_rec in v_records.values():
        corrections_made += v_rec.corrections_made
        for fname, fres in v_rec.field_results.items():
            total_claims += 1
            if fname not in field_stats:
                field_stats[fname] = {"checked": 0, "first_pass_correct": 0, "post_verified": 0, "corrections": 0}
            field_stats[fname]["checked"] += 1

            if fres.verification_status == ClaimVerificationStatus.VERIFIED:
                verified_claims += 1
                field_stats[fname]["post_verified"] += 1
                if not fres.was_corrected:
                    first_pass_correct += 1
                    field_stats[fname]["first_pass_correct"] += 1
            elif fres.verification_status == ClaimVerificationStatus.CONTRADICTED:
                contradicted_claims += 1
            elif fres.verification_status == ClaimVerificationStatus.INSUFFICIENT_EVIDENCE:
                insufficient_claims += 1

            if fres.was_corrected:
                field_stats[fname]["corrections"] += 1
                corrections_list.append({
                    "app": v_rec.app,
                    "field": fname,
                    "original_value": fres.original_value,
                    "corrected_value": fres.corrected_value.value if hasattr(fres.corrected_value, "value") else (
                        [v.value if hasattr(v, "value") else str(v) for v in fres.corrected_value] if isinstance(fres.corrected_value, list) else fres.corrected_value
                    ),
                    "reason": fres.verification_notes,
                    "original_evidence": [e.claim for e in v_rec.original_record.evidence],
                    "new_evidence": [e.claim for e in fres.evidence],
                    "verification_status": fres.verification_status.value,
                    "verifier_confidence": fres.verifier_confidence,
                })

    # Accuracy calculations
    first_pass_acc = round((first_pass_correct / total_claims) * 100, 1) if total_claims else 0.0
    post_verif_acc = round((verified_claims / total_claims) * 100, 1) if total_claims else 0.0
    correction_rate = round((corrections_made / total_claims) * 100, 1) if total_claims else 0.0

    total_first_pass_unknowns = sum(first_pass_report["unknown_count_per_major_field"].values())
    unknown_rate = round((total_first_pass_unknowns / total_claims) * 100, 1) if total_claims else 0.0

    fp_confs = [r.overall_confidence for r in records.values() if r.overall_confidence is not None]
    avg_fp_conf = round(sum(fp_confs) / len(fp_confs), 2) if fp_confs else 0.0

    verif_confs = [r.verified_record.overall_confidence for r in v_records.values() if r.verified_record.overall_confidence is not None]
    avg_verif_conf = round(sum(verif_confs) / len(verif_confs), 2) if verif_confs else 0.0

    total_original_evidence = sum(len(r.evidence) for r in records.values())
    total_verified_evidence = sum(len(v.verified_record.evidence) for v in v_records.values())
    new_evidence_count = total_verified_evidence - total_original_evidence

    field_accuracy_summary = {}
    for fname, stats in field_stats.items():
        cnt = stats["checked"]
        field_accuracy_summary[fname] = {
            "claims_checked": cnt,
            "first_pass_accuracy": round((stats["first_pass_correct"] / cnt) * 100, 1) if cnt else 0.0,
            "post_verification_accuracy": round((stats["post_verified"] / cnt) * 100, 1) if cnt else 0.0,
            "corrections_made": stats["corrections"],
        }

    verification_report = {
        "pilot_label": "10-application pilot",
        "sample_size_note": "10-application pilot. Not presented as statistically representative of all 100 apps.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_applications": len(v_records),
        "total_claims_checked": total_claims,
        "verified_claims": verified_claims,
        "contradicted_claims": contradicted_claims,
        "insufficient_evidence_claims": insufficient_claims,
        "corrections_made": corrections_made,
        "first_pass_accuracy": first_pass_acc,
        "post_verification_accuracy": post_verif_acc,
        "accuracy_by_field": field_accuracy_summary,
        "correction_rate": correction_rate,
        "unknown_rate": unknown_rate,
        "average_first_pass_confidence": avg_fp_conf,
        "average_verified_confidence": avg_verif_conf,
        "new_evidence_items_discovered": new_evidence_count,
    }

    verif_report_path = DATA_DIR / "pilot_verification_report.json"
    with open(verif_report_path, "w", encoding="utf-8") as f:
        json.dump(verification_report, f, indent=2)
    print(f"Saved pilot verification report to {verif_report_path}")

    # Phase E: Classification
    correction_types_summary: Dict[str, int] = {}
    for c in corrections_list:
        field = c["field"]
        reason = c["reason"].lower()
        if "pruned" in reason or "unverified methods" in reason or "partially verified" in reason and field == "authentication":
            cat = "unsupported authentication method"
        elif "unverified types" in reason or "partially verified" in reason and field == "api_surface":
            cat = "unsupported API type"
        elif field == "access_model" or "credential" in reason or "gating" in reason:
            cat = "unresolved credential gating"
        elif field == "mcp_status" or "mcp" in reason:
            cat = "incorrect MCP classification"
        elif field == "buildability" or "rate limits" in reason or "restrictions" in reason:
            cat = "incorrect buildability"
        elif "insufficient evidence" in reason:
            cat = "insufficient evidence"
        else:
            cat = "other"

        correction_types_summary[cat] = correction_types_summary.get(cat, 0) + 1

    corrections_doc = {
        "pilot_label": "10-application pilot",
        "total_corrections": len(corrections_list),
        "most_common_correction_types": dict(sorted(correction_types_summary.items(), key=lambda x: x[1], reverse=True)),
        "corrections": corrections_list,
    }

    corrections_path = DATA_DIR / "pilot_corrections.json"
    with open(corrections_path, "w", encoding="utf-8") as f:
        json.dump(corrections_doc, f, indent=2)
    print(f"Saved pilot corrections analysis to {corrections_path}")


def main():
    agent = ResearchAgent()
    verifier = VerificationAgent()

    # Phase A: Research
    records = run_phase_a(agent)

    # Phase B: Quality Report
    fp_report = run_phase_b(records)

    # Phase C: Verification
    v_records = run_phase_c(verifier, records)

    # Phase D, E, F: Metrics, Corrections, Diagnostics
    run_phase_d_e_f(records, v_records, fp_report)

    print("\n" + "=" * 75)
    print(" 10-APPLICATION PILOT COMPLETED SUCCESSFULLY")
    print("=" * 75)


if __name__ == "__main__":
    main()
