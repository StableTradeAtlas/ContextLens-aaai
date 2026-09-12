"""Record annotated UI states from the actual stateless preview, then assemble GIFs."""
from __future__ import annotations

from contextlib import contextmanager
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


def record(page, stem, number, caption, selector=None):
    page.evaluate("""(args) => {
      document.querySelector('#capture-caption')?.remove();
      document.querySelectorAll('[data-capture-highlight]').forEach(el => {
        el.style.removeProperty('outline'); delete el.dataset.captureHighlight;
      });
      // Keep the selected state above the annotation and reset action-induced scroll.
      if(args.selector !== '#modal'){
        const target=document.querySelector(args.selector || 'body');
        const top=args.selector === '#candidateBox' && target
          ? Math.max(0, window.scrollY + target.getBoundingClientRect().top - 180) : 0;
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


def gif(stem, frames):
    images = []
    for path in frames:
        with Image.open(path) as im:
            images.append(im.convert("RGB").quantize(colors=192))
    images[0].save(OUT / f"{stem}.gif", save_all=True, append_images=images[1:],
                   duration=1900, loop=0, optimize=True, disposal=2)
    # Keep only one static fallback per GIF.
    with Image.open(frames[-1]) as im:
        im.save(OUT / f"{stem}.png")
    for path in frames:
        path.unlink()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with preview(), sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-gl=angle", "--use-angle=swiftshader"])
        page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
        page.goto(BASE, wait_until="domcontentloaded")
        page.locator("#langBtn").click()
        page.locator("#addressInput").fill("436 Avenue Joffre")
        page.locator("#eraInput").fill("1934")
        frames=[record(page,"01-address",1,"1. Enter an old address and year. The English example maps to the curated road identity.","#searchForm")]
        page.locator("#searchForm").evaluate("(form) => form.requestSubmit()")
        page.wait_for_function("document.querySelector('#dossier').hidden === false")
        frames.append(record(page,"01-address",2,"2. Inspect dated road names and the resolver's heuristic confidence.","#viewPanel"))
        page.locator('[data-view="timeline"]').click()
        frames.append(record(page,"01-address",3,"3. Read the dated records; historical context is not restricted to the query year.","#viewPanel"))
        page.locator('[data-view="atlas"]').click()
        # Capture either the loaded map or the application's explicit unavailable state.
        try:
            page.wait_for_function("""() => {
              const scan=document.querySelector('.archive-map img');
              const canvas=document.querySelector('#modernMap canvas');
              const failed=document.querySelector('#mapFail');
              return scan?.complete && (canvas || (failed && getComputedStyle(failed).display !== 'none'));
            }""", timeout=8000)
        except Exception:
            pass
        frames.append(record(page,"01-address",4,"4. Compare archival and modern maps; the scan does not establish an exact house number.","#viewPanel"))
        gif("01-address",frames)

        page.locator('[data-view="sources"]').click()
        frames=[record(page,"02-evidence",1,"5. Compare this dossier's evidence cards with the collection total.","#viewPanel")]
        page.locator('.source-table [data-evidence]').first.click()
        page.locator("#modal.open").wait_for()
        frames.append(record(page,"02-evidence",2,"6. Open a Source Passport to inspect its identifier, URI, and provenance.","#modal"))
        page.locator("#modalClose").click()
        with page.expect_download() as download:
            page.locator("#downloadBtn").click()
        data = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
        assert data["claims"] and data["evidence"]
        frames.append(record(page,"02-evidence",3,"7. Download the actual dossier JSON with the same claim-to-evidence links.","#downloadBtn"))
        gif("02-evidence",frames)

        page.locator("#backBtn").click()
        page.locator("#addressInput").fill("南京路百货公司")
        page.locator("#searchForm").evaluate("(form) => form.requestSubmit()")
        page.locator("#candidateList .candidate").first.wait_for()
        frames=[record(page,"03-boundaries",1,"8. Nanjing Road remains ambiguous: the user chooses a candidate.","#candidateBox")]
        page.locator("#addressInput").fill("9999 Mars Road")
        page.locator("#searchForm").evaluate("(form) => form.requestSubmit()")
        page.wait_for_function("document.querySelector('#candidateList').children.length === 0")
        frames.append(record(page,"03-boundaries",2,"9. An unsupported address returns unresolved; no dossier is invented.","#candidateBox"))
        gif("03-boundaries",frames)
        browser.close()
    print("Saved three GIFs and static fallbacks from actual browser states in docs/media/")


if __name__ == "__main__":
    main()
