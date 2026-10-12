"""Exercise a running local workspace in a real browser; no mocked API or screenshots.

Install Playwright and its Chromium browser in a separate tooling environment.
The application must already be running, with optional ML disabled. A token may be supplied through FLAKY_SMOKE_TOKEN.
This is a functional smoke test, not an accessibility/performance certification.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--source-view",
        action="store_true",
        help="Require a configured redacted source view and source:read credential",
    )
    parser.add_argument(
        "--runtime-repo",
        help="Repository already present in the configured event store",
    )
    args = parser.parse_args()
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Use a local test instance; this smoke submits sample source code.")
    args.output.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {"status": "blocked", "url": args.url, "checks": []}
    checks: list[str] = []
    report["checks"] = checks
    browser_errors: list[str] = []
    report["browser_errors"] = browser_errors
    exit_code = 2
    try:
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as manager:
            browser = manager.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.on("pageerror", lambda error: browser_errors.append(str(error)))
                report["status"] = "failed"
                page.goto(args.url, wait_until="networkidle")
                if os.environ.get("FLAKY_SMOKE_TOKEN"):
                    page.get_by_label("API access token").fill(os.environ["FLAKY_SMOKE_TOKEN"])
                if args.source_view:
                    page.get_by_role(
                        "checkbox", name="Request a temporary redacted source view"
                    ).check()
                source = page.get_by_role("textbox", name="Python test source")
                source.fill("import time\ndef test_wait():\n    time.sleep(1)\n")
                page.get_by_role("button", name="Run analysis", exact=True).click()
                expect(page.get_by_role("heading", name="Evidence, not a guess")).to_be_visible()
                expect(page.get_by_text("Risk detected", exact=True)).to_be_visible()
                checks.append("real-api-analysis")
                page.get_by_text("Open captured source", exact=False).first.click()
                if args.source_view:
                    expect(page.locator(".source-line.highlighted").first).to_be_visible()
                    checks.append("authorized-redacted-source-navigation")
                else:
                    expect(
                        page.get_by_text(
                            "Source access is disabled, denied or expired.", exact=False
                        ).first,
                    ).to_be_visible()
                    expect(page.locator(".source-line.highlighted")).to_have_count(0)
                    checks.append("source-hidden-by-default")
                source.fill("def test_fixed():\n    assert True\n")
                expect(page.get_by_test_id("stale-analysis")).to_be_visible()
                page.get_by_role("button", name="Run analysis", exact=True).click()
                expect(page.get_by_test_id("stale-analysis")).to_have_count(0)
                expect(page.get_by_role("heading", name="test_fixed", exact=True)).to_be_visible()
                checks.append("edit-stale-rerun")
                page.get_by_role("checkbox", name="Request evaluated ML model").check()
                expect(page.get_by_test_id("stale-analysis")).to_be_visible()
                page.get_by_role("checkbox", name="Request evaluated ML model").uncheck()
                checks.append("settings-mark-stale")
                page.get_by_role("button", name="File / ZIP", exact=True).click()
                page.get_by_label("Source file or ZIP").set_input_files(
                    {
                        "name": "test_upload.py",
                        "mimeType": "text/x-python",
                        "buffer": b"def test_uploaded():\n    assert True\n",
                    },
                )
                page.get_by_role("button", name="Run analysis", exact=True).click()
                expect(
                    page.get_by_role("heading", name="test_uploaded", exact=True)
                ).to_be_visible()
                page.get_by_role("button", name="Clear file and return to code").click()
                expect(source).to_have_value("def test_fixed():\n    assert True\n")
                checks.append("upload-clear-preserves-draft")
                source.fill("def broken(:\n")
                page.get_by_role("button", name="Run analysis", exact=True).click()
                expect(page.locator(".status-error")).to_be_visible()
                expect(
                    page.get_by_role("heading", name="Analysis coverage and limitations")
                ).to_be_visible()
                checks.append("syntax-422-is-rendered")
                if args.runtime_repo:
                    page.get_by_label("Runtime repository").fill(args.runtime_repo)
                    page.get_by_role("button", name="Load history", exact=True).click()
                    expect(
                        page.get_by_role("heading", name="Reliability measurements")
                    ).to_be_visible()
                    checks.append("runtime-ledger-and-metrics")
                if browser_errors:
                    raise AssertionError("Uncaught browser errors")
                page.screenshot(path=str(args.output / "desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(args.output / "mobile.png"), full_page=True)
                report["status"] = "passed"
                exit_code = 0
            finally:
                browser.close()
    except Exception as exc:
        report["reason"] = f"{type(exc).__name__}: {exc}"
        exit_code = 2 if report["status"] == "blocked" else 1
    (args.output / "browser.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
