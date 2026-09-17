"""
AI Product Ops Research System
CLI Entrypoint and Project Runner
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
APPS_CSV = DATA_DIR / "apps.csv"


def load_apps(csv_path: Path = APPS_CSV) -> list[dict]:
    """Load and return the list of apps from apps.csv."""
    if not csv_path.exists():
        print(f"[ERROR] Apps file not found at: {csv_path}", file=sys.stderr)
        sys.exit(1)

    apps = []
    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            apps.append({
                "id": int(row["id"].strip()),
                "app": row["app"].strip(),
                "category": row["category"].strip()
            })
    return apps


def validate_apps(apps: list[dict]) -> bool:
    """Validate dataset schema, row count, and uniqueness."""
    print("=" * 60)
    print("DATASET INTEGRITY VALIDATION")
    print("=" * 60)

    is_valid = True

    # 1. Row count validation
    total_apps = len(apps)
    print(f"- Total Applications: {total_apps}")
    if total_apps != 100:
        print(f"  [FAIL] Expected exactly 100 applications, found {total_apps}")
        is_valid = False
    else:
        print("  [PASS] Exactly 100 applications found.")

    # 2. Unique IDs
    ids = [a["id"] for a in apps]
    if len(ids) != len(set(ids)):
        print("  [FAIL] Duplicate IDs detected!")
        is_valid = False
    else:
        print("  [PASS] All 100 IDs are unique and sequential.")

    # 3. Non-empty names & categories
    empty_fields = [a for a in apps if not a["app"] or not a["category"]]
    if empty_fields:
        print(f"  [FAIL] Found {len(empty_fields)} records with missing app or category")
        is_valid = False
    else:
        print("  [PASS] All entries have valid app names and categories.")

    # 4. Category breakdown
    counts = Counter(a["category"] for a in apps)
    print(f"- Total Categories: {len(counts)}")
    if len(counts) != 10:
        print(f"  [FAIL] Expected 10 categories, found {len(counts)}")
        is_valid = False
    else:
        print("  [PASS] Exactly 10 categories present.")

    all_ten = all(count == 10 for count in counts.values())
    if not all_ten:
        print("  [WARNING] Some categories do not have exactly 10 applications.")
    else:
        print("  [PASS] Each category has exactly 10 applications.")

    print("-" * 60)
    if is_valid:
        print("Status: ALL VALIDATION CHECKS PASSED")
    else:
        print("Status: VALIDATION CHECKS FAILED")
    print("=" * 60)
    return is_valid


def display_summary(apps: list[dict]):
    """Display clean summary statistics of the dataset."""
    counts = Counter(a["category"] for a in apps)

    print("\n" + "=" * 65)
    print(" AI PRODUCT OPS RESEARCH - DATASET SUMMARY")
    print("=" * 65)
    print(f" Total Applications : {len(apps)}")
    print(f" Total Categories   : {len(counts)}")
    print("-" * 65)
    print(f" {'#':<3} | {'Category':<38} | {'Apps':>5}")
    print("-" * 65)

    for idx, (cat, count) in enumerate(counts.items(), 1):
        print(f" {idx:<3} | {cat:<38} | {count:>5}")

    print("=" * 65 + "\n")


def list_apps(apps: list[dict], category_filter: str | None = None):
    """List applications, optionally filtered by category."""
    filtered = apps
    if category_filter:
        filtered = [
            a for a in apps
            if category_filter.lower() in a["category"].lower()
        ]
        if not filtered:
            print(f"[INFO] No applications found matching category filter: '{category_filter}'")
            return

    print("\n" + "=" * 70)
    title = f"APPLICATIONS LIST ({len(filtered)})"
    if category_filter:
        title += f" [Filter: {category_filter}]"
    print(title)
    print("=" * 70)
    print(f" {'ID':<4} | {'Application Name':<28} | {'Category'}")
    print("-" * 70)
    for a in filtered:
        print(f" {a['id']:<4} | {a['app']:<28} | {a['category']}")
    print("=" * 70 + "\n")


def parse_args():
    parser = argparse.ArgumentParser(
        description="AI Product Ops Research System - CLI Runner"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Display dataset summary statistics and category distribution"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run integrity validation checks on data/apps.csv"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all applications in the dataset"
    )
    parser.add_argument(
        "--category",
        type=str,
        help="Filter applications by category name"
    )
    parser.add_argument(
        "--research",
        type=str,
        help="Run autonomous research for an application by name (e.g., 'Slack')"
    )
    parser.add_argument(
        "--research-id",
        type=int,
        help="Run autonomous research for an application by ID (e.g., 21)"
    )
    parser.add_argument(
        "--verify",
        type=str,
        help="Run independent verification loop for an application by name (e.g., 'Slack')"
    )
    parser.add_argument(
        "--verify-id",
        type=int,
        help="Run independent verification loop for an application by ID (e.g., 21)"
    )
    return parser.parse_args()


def run_verification(app_name: str | None = None, app_id: int | None = None):
    """Execute independent verification agent for a given application."""
    from verification.verifier import VerificationAgent

    verifier = VerificationAgent()
    print("\n" + "=" * 70)
    print(f" LAUNCHING AUTOMATED VERIFICATION LOOP")
    target = f"ID: {app_id}" if app_id else f"App: '{app_name}'"
    print(f" Target: {target}")
    print("=" * 70)

    try:
        res = verifier.verify_app(app_name=app_name, app_id=app_id)
    except Exception as e:
        print(f"\n[ERROR] Verification failed: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 70)
    print(f" VERIFICATION AUDIT: {res.app.upper()} (ID: {res.app_id})")
    print("=" * 70)
    print(f" Category             : {res.category}")
    print(f" Overall Status       : {res.overall_verification_status.value}")
    print(f" Claims Checked       : {res.claims_checked}")
    print(f" Claims Verified      : {res.claims_verified}")
    print(f" Claims Contradicted  : {res.claims_contradicted}")
    print(f" Insufficient Evidence: {res.claims_insufficient_evidence}")
    print(f" Corrections Made     : {res.corrections_made}")
    print("-" * 70)
    print(f" {'Field':<15} | {'Original Value':<20} | {'Status':<12} | {'Corrected Value'}")
    print("-" * 70)
    for fld, f_res in res.field_results.items():
        orig_str = str(f_res.original_value)
        if len(orig_str) > 18:
            orig_str = orig_str[:15] + "..."
        corr_str = str(f_res.corrected_value.value if hasattr(f_res.corrected_value, 'value') else f_res.corrected_value) if f_res.was_corrected else "-"
        print(f" {fld:<15} | {orig_str:<20} | {f_res.verification_status.value:<12} | {corr_str}")

    print("-" * 70)
    print(f" Original Confidence : {res.original_record.overall_confidence}")
    print(f" Verified Confidence : {res.verified_record.overall_confidence}")
    print("-" * 70)
    print(f" Summary Notes        : {res.summary_notes}")

    if res.corrections_made > 0:
        print("\n[CORRECTIONS APPLIED]")
        for fld, f_res in res.field_results.items():
            if f_res.was_corrected:
                print(f" * [{fld}] Original: '{f_res.original_value}' -> Corrected: '{f_res.corrected_value.value if hasattr(f_res.corrected_value, 'value') else f_res.corrected_value}'")
                print(f"   Reason: {f_res.verification_notes}")

    from agent.researcher import get_slug
    slug = get_slug(res.app)
    print("\n[ARTIFACTS PRESERVED & SAVED]")
    print(f" - Original Research  : data/research/{slug}.json (UNTOUCHED)")
    print(f" - Verification Audit : data/verification/{slug}.json")
    print(f" - Accuracy Metrics   : data/verification_metrics.json")
    print("=" * 70 + "\n")


def run_research(app_name: str | None = None, app_id: int | None = None):
    """Execute research agent for a given application and format output."""
    from agent.researcher import ResearchAgent

    agent = ResearchAgent()
    print("\n" + "=" * 70)
    print(f" LAUNCHING RESEARCH AGENT")
    target = f"ID: {app_id}" if app_id else f"App: '{app_name}'"
    print(f" Target: {target}")
    print("=" * 70)

    try:
        record = agent.research_app(app_name=app_name, app_id=app_id)
    except Exception as e:
        print(f"\n[ERROR] Research failed: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 70)
    print(f" RESEARCH RESULT: {record.app.upper()} (ID: {record.id})")
    print("=" * 70)
    print(f" Category        : {record.category}")
    print(f" Official Website: {record.website or 'Unknown'}")
    print(f" Description     : {record.one_line_description}")
    print("-" * 70)
    print(f" Auth Methods    : {[m.value for m in record.auth_methods]}")
    print(f" Auth Confidence : {record.auth_confidence}")
    print(f" Access Model    : {record.access_model.value}")
    print(f" Access Notes    : {record.credential_access_notes}")
    print(f" Access Conf.    : {record.access_confidence}")
    print("-" * 70)
    print(f" API Types       : {[t.value for t in record.api_types]}")
    print(f" API Breadth     : {record.api_breadth.value}")
    print(f" API Scope Notes : {record.api_scope_notes}")
    print(f" API Confidence  : {record.api_confidence}")
    print("-" * 70)
    print(f" MCP Status      : {record.mcp_status.value}")
    print(f" MCP Notes       : {record.mcp_notes}")
    print(f" MCP Confidence  : {record.mcp_confidence}")
    print("-" * 70)
    print(f" Buildability    : {record.buildability.value}")
    print(f" Main Blocker    : {record.main_blocker or 'None'}")
    print(f" Build Conf.     : {record.buildability_confidence}")
    print("-" * 70)
    print(f" OVERALL CONF.   : {record.overall_confidence}")
    print(f" RESEARCH STATUS : {record.research_status.value}")
    print(f" EVIDENCE ITEMS  : {len(record.evidence)}")
    print("=" * 70)

    print("\n[EVIDENCE COLLECTED]")
    for idx, ev in enumerate(record.evidence, 1):
        print(f" {idx}. [{ev.source_type.value}] {ev.claim}")
        print(f"    Title : {ev.source_title}")
        print(f"    URL   : {ev.source_url}")
        print(f"    Quote : {ev.evidence_summary[:160]}...")

    from agent.researcher import get_slug
    slug = get_slug(record.app)
    print("\n[ARTIFACTS SAVED]")
    print(f" - Raw Findings    : data/research_raw/{slug}.json")
    print(f" - Validated Record: data/research/{slug}.json")
    print(f" - Research Log    : data/research_log.jsonl")
    print("=" * 70 + "\n")


def main():
    args = parse_args()
    apps = load_apps()

    # Route CLI actions
    if args.verify or args.verify_id is not None:
        run_verification(app_name=args.verify, app_id=args.verify_id)
    elif args.research or args.research_id is not None:
        run_research(app_name=args.research, app_id=args.research_id)
    elif args.validate:
        validate_apps(apps)
    elif args.list:
        list_apps(apps, category_filter=args.category)
    elif args.category:
        list_apps(apps, category_filter=args.category)
    elif args.summary:
        display_summary(apps)
    else:
        # Default behavior: show summary and prompt next steps
        display_summary(apps)
        print("Project foundation is ready.")
        print("Run 'python main.py --validate' to verify dataset integrity.")
        print("Run 'python main.py --list' to list all 100 apps.")
        print("Run 'python main.py --research \"Slack\"' to research an application.")
        print("Run 'python main.py --verify \"Slack\"' to run the verification loop.")



if __name__ == "__main__":
    main()