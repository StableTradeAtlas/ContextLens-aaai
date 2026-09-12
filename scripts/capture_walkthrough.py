"""Record annotated UI states from the actual stateless preview, then assemble GIFs."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import partial
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "media"
BASE = "http://127.0.0.1:8766"
ZH_CAPTIONS = {
    "1. Enter an old address and year. The English example maps to the curated road identity.": "1. 输入老地址和年代，进入已整理的道路身份记录。",
    "2. Inspect dated road names and the resolver's heuristic confidence.": "2. 查看各时期的路名，以及解析器的启发式匹配置信度。",
    "3. Read the dated records; historical context is not restricted to the query year.": "3. 查看带日期的历史记录；背景信息不限于输入的年份。",
    "4. Compare archival and modern maps; the scan does not establish an exact house number.": "4. 比较历史扫描件与现代地图；扫描件不能确定精确门牌位置。",
    "5. Compare this dossier's evidence cards with the collection total.": "5. 区分本次调查返回的证据卡片与整个数据集合的总量。",
    "6. Open a Source Passport to inspect its identifier, URI, and provenance.": "6. 打开来源档案，检查证据标识符、原始 URI 和来源信息。",
    "7. Download the actual dossier JSON with the same claim-to-evidence links.": "7. 下载实际档案 JSON，保留相同的主张与证据关联。",
    "8. Nanjing Road remains ambiguous: the user chooses a candidate.": "8. 南京路仍存在歧义，需要用户确认候选地址。",
    "9. An unsupported address returns unresolved; no dossier is invented.": "9. 不受支持的地址返回无法解析，不生成无依据的档案。"
}


@contextmanager
def preview():
    process = subprocess.Popen([sys.executable, str(ROOT / "scripts/preview_vercel.py")], cwd=ROOT)
    try:
        for _ in range(100):
            try:
                with urlopen(BASE + "/api/health", timeout=0.5) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Preview did not start")
        yield
    finally:
        process.terminate()
        process.wait(timeout=10)


def record(page, stem, number, caption, selector=None, *, language="en"):
    if language == "zh":
        stem += ".zh-CN"
        caption = ZH_CAPTIONS[caption]
    page.evaluate("""(args) => {
      document.querySelector('#capture-caption')?.remove();
      document.querySelectorAll('[data-capture-highlight]').forEach(el => {
        el.style.removeProperty('outline'); delete el.dataset.captureHighlight;
      });
      // Keep the selected state above the annotation and reset action-induced scroll.
      document.body.style.paddingBottom='110px';
      if(args.selector !== '#modal'){
        const target=document.querySelector(args.selector || 'body');
        const top=args.selector === '#candidateBox' && target
          ? Math.max(0, window.scrollY + target.getBoundingClientRect().top - 180)
          : args.selector === '#viewPanel' && target
            ? Math.max(0, window.scrollY + target.getBoundingClientRect().top - 95) : 0;
        window.scrollTo({top,behavior:'instant'});
      }
      const label=document.createElement('div');
      label.id='capture-caption'; label.textContent=args.caption;
      Object.assign(label.style,{position:'fixed',bottom:'16px',left:'28px',right:'28px',
        padding:'15px 20px',background:'#10283b',color:'#fff',font:'600 18px Arial',
        borderRadius:'12px',zIndex:'99999',boxShadow:'0 3px 18px #0003',pointerEvents:'none'});
      document.body.appendChild(label);
      if(args.selector){const target=document.querySelector(args.selector);
        if(target){target.style.outline='3px solid #b64b38';target.dataset.captureHighlight='true';}}
    }""", {"caption": caption, "selector": selector})
    path = OUT / f"{stem}-{number}.png"
    page.screenshot(path=str(path), animations="disabled")
    return path


def gif(stem, frames, *, language="en"):
    if language == "zh":
        stem += ".zh-CN"
    images = []
    for path in frames:
        with Image.open(path) as im:
            images.append(im.convert("RGB").quantize(colors=192))
    images[0].save(OUT / f"{stem}.gif", save_all=True, append_images=images[1:],
                   duration=1900, loop=0, optimize=True, disposal=2)
    # Keep only one static fallback per GIF.
    images[-1].save(OUT / f"{stem}.png", optimize=True)
    for path in frames:
        path.unlink()


def main(language="en"):
    record_state = partial(record, language=language)
    save_gif = partial(gif, language=language)
    OUT.mkdir(parents=True, exist_ok=True)
    with preview(), sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-gl=angle", "--use-angle=swiftshader"])
        page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
        page.goto(BASE, wait_until="domcontentloaded")
        page.locator("#searchForm").wait_for()
        if language == "en":
            page.locator("#langBtn").click()
        expected_language = "zh-CN" if language == "zh" else "en"
        assert page.locator("html").get_attribute("lang") == expected_language
        page.locator("#addressInput").fill("霞飞路436号" if language == "zh" else "436 Avenue Joffre")
        page.locator("#eraInput").fill("1934")
        frames=[record_state(page,"01-address",1,"1. Enter an old address and year. The English example maps to the curated road identity.","#searchForm")]
        page.locator("#searchForm").evaluate("(form) => form.requestSubmit()")
        page.wait_for_function("document.querySelector('#dossier').hidden === false")
        frames.append(record_state(page,"01-address",2,"2. Inspect dated road names and the resolver's heuristic confidence.","#viewPanel"))
        page.locator('[data-view="timeline"]').click()
        frames.append(record_state(page,"01-address",3,"3. Read the dated records; historical context is not restricted to the query year.","#viewPanel"))
        page.locator('[data-view="atlas"]').click()
        # Capture either the loaded map or the application's explicit unavailable state.
        try:
            page.wait_for_function("""() => {
              const scan=document.querySelector('.archive-map img');
              const canvas=document.querySelector('#modernMap canvas');
              const failed=document.querySelector('#mapFail');
              return scan?.complete && (canvas || (failed && getComputedStyle(failed).display !== 'none'));
            }""", timeout=8000)
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        frames.append(record_state(page,"01-address",4,"4. Compare archival and modern maps; the scan does not establish an exact house number.","#viewPanel"))
        save_gif("01-address",frames)

        page.locator('[data-view="sources"]').click()
        frames=[record_state(page,"02-evidence",1,"5. Compare this dossier's evidence cards with the collection total.","#viewPanel")]
        page.locator('.source-table [data-evidence]').first.click()
        page.locator("#modal.open").wait_for()
        frames.append(record_state(page,"02-evidence",2,"6. Open a Source Passport to inspect its identifier, URI, and provenance.","#modal"))
        page.locator("#modalClose").click()
        with page.expect_download() as download:
            page.locator("#downloadBtn").click()
        data = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
        assert data["claims"] and data["evidence"]
        frames.append(record_state(page,"02-evidence",3,"7. Download the actual dossier JSON with the same claim-to-evidence links.","#downloadBtn"))
        save_gif("02-evidence",frames)

        page.locator("#backBtn").click()
        page.locator("#addressInput").fill("南京路百货公司")
        page.locator("#searchForm").evaluate("(form) => form.requestSubmit()")
        page.locator("#candidateList .candidate").first.wait_for()
        frames=[record_state(page,"03-boundaries",1,"8. Nanjing Road remains ambiguous: the user chooses a candidate.","#candidateBox")]
        page.locator("#addressInput").fill("9999 Mars Road")
        page.locator("#searchForm").evaluate("(form) => form.requestSubmit()")
        page.wait_for_function("document.querySelector('#candidateList').children.length === 0")
        frames.append(record_state(page,"03-boundaries",2,"9. An unsupported address returns unresolved; no dossier is invented.","#candidateBox"))
        save_gif("03-boundaries",frames)
        browser.close()
    print(f"Saved three {language} GIFs and static fallbacks from actual browser states in docs/media/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("en", "zh"), default="en",
                        help="Interface and annotation language; defaults to English.")
    main(parser.parse_args().language)
