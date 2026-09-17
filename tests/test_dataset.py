"""
Unit tests for AI Product Ops dataset integrity.
"""

from pathlib import Path
from main import load_apps, validate_apps

BASE_DIR = Path(__file__).resolve().parent.parent
APPS_CSV = BASE_DIR / "data" / "apps.csv"

EXPECTED_CATEGORIES = [
    "CRM and Sales",
    "Support and Helpdesk",
    "Communications and Messaging",
    "Marketing, Ads, Email and Social",
    "Ecommerce",
    "Data, SEO and Scraping",
    "Developer, Infra and Data platforms",
    "Productivity and Project Management",
    "Finance and Fintech",
    "AI, Research and Media-native",
]


def test_apps_csv_exists():
    assert APPS_CSV.exists(), f"apps.csv not found at {APPS_CSV}"


def test_apps_count():
    apps = load_apps(APPS_CSV)
    assert len(apps) == 100, f"Expected 100 apps, got {len(apps)}"


def test_apps_validation():
    apps = load_apps(APPS_CSV)
    assert validate_apps(apps) is True


def test_categories_breakdown():
    apps = load_apps(APPS_CSV)
    categories = {}
    for app in apps:
        cat = app["category"]
        categories[cat] = categories.get(cat, 0) + 1

    assert set(categories.keys()) == set(EXPECTED_CATEGORIES)
    for cat, count in categories.items():
        assert count == 10, f"Category '{cat}' has {count} apps, expected 10"


if __name__ == "__main__":
    test_apps_csv_exists()
    test_apps_count()
    test_apps_validation()
    test_categories_breakdown()
    print("All unit tests passed successfully!")