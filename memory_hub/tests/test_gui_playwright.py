"""Playwright smoke test for the Streamlit dashboard.

Run with: python -m pytest tests/test_gui_playwright.py -v
Requires: streamlit running at localhost:8501 (hub gui)
"""
import io
import sys
import time

# Force UTF-8 stdout on Windows
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright, expect


BASE_URL = "http://localhost:8501"

# Streamlit sidebar radio labels for each page
PAGES = [
    "Dashboard",
    "Setup Wizard",
    "Ingest Data",
    "Reconcile & Facts",
    "Generate Projections",
    "Deploy to Platforms",
    "Search History",
    "Sync & Reports",
]


def _wait_for_streamlit(page):
    """Wait for Streamlit app to finish loading."""
    # Wait for the main app container to appear
    page.wait_for_selector('[data-testid="stAppViewContainer"]', timeout=15000)
    # Give Streamlit a moment to render
    time.sleep(1)


def _navigate_to_page(page, page_name):
    """Click a sidebar radio option to navigate to a page."""
    # Find the radio button with the page name text
    radio = page.locator(f'label:has-text("{page_name}")')
    if radio.count() > 0:
        radio.first.click()
        time.sleep(2)  # Wait for page to render
        return True
    return False


def test_all_pages_load():
    """Smoke test: verify each page loads without errors."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Load the app
        page.goto(BASE_URL, wait_until="networkidle")
        _wait_for_streamlit(page)

        results = {}

        for page_name in PAGES:
            navigated = _navigate_to_page(page, page_name)
            if not navigated:
                results[page_name] = "SKIP - radio button not found"
                continue

            # Check for Python tracebacks / Streamlit error blocks
            error_elements = page.locator('[data-testid="stException"]')
            error_count = error_elements.count()

            if error_count > 0:
                error_text = error_elements.first.inner_text()[:200]
                results[page_name] = f"ERROR - {error_text}"
            else:
                results[page_name] = "OK"

        browser.close()

        # Print results
        print("\n=== GUI Smoke Test Results ===")
        all_ok = True
        for name, status in results.items():
            icon = "OK" if status == "OK" else "!!"
            print(f"  [{icon}] {name}: {status}")
            if status != "OK" and not status.startswith("SKIP"):
                all_ok = False

        assert all_ok, f"Some pages had errors: {results}"


def test_dashboard_has_metrics():
    """Verify the dashboard shows the expected metric cards."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        _wait_for_streamlit(page)

        # Dashboard should show metrics (events, facts, conflicts)
        metrics = page.locator('[data-testid="stMetric"]')
        metric_count = metrics.count()

        print(f"\n=== Dashboard Metrics: {metric_count} found ===")
        for i in range(metric_count):
            label = metrics.nth(i).locator('[data-testid="stMetricLabel"]').inner_text()
            value = metrics.nth(i).locator('[data-testid="stMetricValue"]').inner_text()
            print(f"  {label}: {value}")

        browser.close()

        assert metric_count >= 3, f"Expected at least 3 metrics, got {metric_count}"


def test_search_page():
    """Verify the search page accepts input and shows results."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        _wait_for_streamlit(page)

        # Navigate to Search page
        _navigate_to_page(page, "Search History")

        # Find the search input and type a query
        search_input = page.locator('input[type="text"]').first
        search_input.fill("[ROLE]")
        search_input.press("Enter")
        time.sleep(3)  # Wait for search results

        # Check that some content appeared (results or "No results" info)
        body_text = page.locator('[data-testid="stAppViewContainer"]').inner_text()
        has_results = "results" in body_text.lower() or "[role]" in body_text.lower()

        print(f"\n=== Search Test ===")
        print(f"  Query: [ROLE]")
        print(f"  Has results: {has_results}")

        browser.close()

        assert has_results, "Search page did not show results for '[ROLE]'"


if __name__ == "__main__":
    print("Running GUI smoke tests against http://localhost:8501")
    print("Make sure 'hub gui' is running first.\n")
    test_all_pages_load()
    test_dashboard_has_metrics()
    test_search_page()
    print("\n=== All tests passed ===")
