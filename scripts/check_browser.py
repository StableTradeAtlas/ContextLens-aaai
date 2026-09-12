"""Check the local or deployed bilingual address flow and API error messages."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from capture_walkthrough import BASE, preview


def check_dossier(page, language):
    if page.locator("#langBtn").inner_text() == ("EN" if language == "en" else "ZH"):
        page.locator("#langBtn").click()
    page.locator("#examples button[data-address='外滩20号']").click()
    expect(page.locator("#dossier")).to_be_visible(timeout=45000)
    expect(page.locator("#statusDot")).to_have_class("ok")
    for view in ("identity", "timeline", "atlas", "sources"):
        page.locator(f"#dossierTabs button[data-view='{view}']").click()
        expect(page.locator("#viewPanel")).not_to_be_empty()
    with page.expect_download() as event:
        page.locator("#downloadBtn").click()
    download = event.value
    payload = json.loads(Path(download.path()).read_text(encoding="utf-8"))
    assert payload["evidence"] and payload["claims"]
    assert payload["quality"]["live_feature_count"] == 0
    print(f"PASS: {language} Bund dossier, four views, evidence JSON", flush=True)
    page.locator("#backBtn").click()


def main(base_url=None):
    base = (base_url or BASE).rstrip("/")
    parsed = urlsplit(base)
    assert parsed.scheme in ("http", "https") and parsed.netloc
    with (nullcontext() if base_url else preview()), sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        if not base_url:
            page.route("**/api/**", lambda route: route.fulfill(
                status=500, content_type="text/plain",
                body="A server error has occurred\nFUNCTION_INVOCATION_FAILED",
            ))
            page.goto(base, wait_until="domcontentloaded")
            expect(page.locator("#serviceText")).to_have_text("证据服务离线")
            page.locator("#resolveBtn").click()
            expect(page.locator("#toast")).to_have_text("证据服务暂时不可用，请稍后重试。")
            page.locator("#langBtn").click()
            expect(page.locator("#serviceText")).to_have_text("Evidence service offline")
            page.locator("#resolveBtn").click()
            expect(page.locator("#toast")).to_have_text(
                "Evidence service is temporarily unavailable. Please try again shortly."
            )
            print("PASS: plain-text server errors and offline status in both languages", flush=True)
            page.unroute("**/api/**")
        page.goto(base, wait_until="domcontentloaded")
        expect(page.locator("#statusDot")).to_have_class("ok", timeout=45000)
        check_dossier(page, "zh")
        check_dossier(page, "en")
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="Public demo URL; omit for the local stateless preview.")
    main(parser.parse_args().base_url)
