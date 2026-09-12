"""Render both README teasers and check SVG assets, text fit, and local links."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "docs" / "media"
TEASERS = (
    MEDIA / "contextlens-teaser.svg",
    MEDIA / "contextlens-teaser.zh-CN.svg",
)


def validate_svg(path: Path) -> None:
    root = ET.parse(path).getroot()
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError(f"{path.name}: expected an SVG document")
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in {"script", "foreignObject", "image", "iframe", "animate", "set"}:
            raise ValueError(f"{path.name}: unsupported SVG element {tag}")
        for key, value in element.attrib.items():
            key = key.rsplit("}", 1)[-1].lower()
            if key.startswith("on"):
                raise ValueError(f"{path.name}: event handler is not allowed")
            if key in {"href", "src"} and not value.startswith("#"):
                raise ValueError(f"{path.name}: external reference is not allowed")
            if re.search(r"url\(\s*['\"]?(?!#)", value, re.I):
                raise ValueError(f"{path.name}: external CSS reference is not allowed")


def heading_ids(text: str) -> set[str]:
    result = set(re.findall(r'\bid="([^"]+)"', text))
    for heading in re.findall(r"^#{1,6}\s+(.+)$", text, re.M):
        heading = re.sub(r"[^\w\- ]", "", heading.lower())
        result.add(heading.replace(" ", "-"))
    return result


def validate_links(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    urls = re.findall(r'\b(?:href|src)="([^"]+)"', text)
    urls += re.findall(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", text)
    checked = 0
    for url in urls:
        parsed = urlsplit(unquote(url))
        if parsed.scheme or parsed.netloc:
            continue
        target = (path.parent / parsed.path).resolve() if parsed.path else path
        if not target.is_relative_to(ROOT) or not target.exists():
            raise ValueError(f"{path.relative_to(ROOT)}: missing local target {url}")
        if parsed.fragment and target.suffix == ".md":
            anchors = heading_ids(target.read_text(encoding="utf-8"))
            if parsed.fragment not in anchors:
                raise ValueError(f"{path.relative_to(ROOT)}: missing anchor {url}")
        checked += 1
    return checked


def main() -> None:
    assets = [*TEASERS, *sorted((MEDIA / "badges").glob("*.svg"))]
    for path in assets:
        validate_svg(path)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1600, "height": 940}, device_scale_factor=2
        )
        for path in assets:
            page.goto(path.as_uri(), wait_until="load")
            page.evaluate("document.fonts.ready")
            overflow = page.evaluate("""() => {
              const view = document.documentElement.viewBox.baseVal;
              return Array.from(document.querySelectorAll("text")).flatMap(el => {
                const box = el.getBBox();
                const max = Number(el.dataset.maxWidth || view.width);
                const fits = box.width <= max + 1 &&
                  box.x >= -1 && box.y >= -1 &&
                  box.x + box.width <= view.width + 1 &&
                  box.y + box.height <= view.height + 1;
                return fits ? [] : [{
                  text: el.textContent, width: box.width, maximum: max,
                  x: box.x, y: box.y
                }];
              });
            }""")
            if overflow:
                raise ValueError(f"{path.name}: text overflow {overflow}")
            if path in TEASERS:
                page.locator("svg").screenshot(path=str(path.with_suffix(".png")))
        browser.close()
    links = sum(validate_links(path) for path in [
        ROOT / "README.md", ROOT / "README.zh-CN.md", MEDIA / "README.md"
    ])
    print(json.dumps({
        "svg_assets": len(assets),
        "local_links": links,
        "text_fit": "passed",
        "self_contained_svg": "passed",
        "png": [str(path.with_suffix(".png").relative_to(ROOT)) for path in TEASERS],
        "png_dimensions": [3200, 1880],
    }, indent=2))


if __name__ == "__main__":
    main()
