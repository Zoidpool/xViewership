"""Project thumbnail (1600x900): logo and title on the left, a live screenshot of the app on the right.

    python tools/make_thumbnail.py [url]     # default http://127.0.0.1:5066/  -> video/xv-thumbnail.png
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5066/"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "video"

CARD = """<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Serif+Text&family=IBM+Plex+Mono:wght@700&family=IBM+Plex+Sans+Condensed:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  body { margin: 0; width: 1600px; height: 900px; overflow: hidden; background: #F2EEE5;
    background-image: radial-gradient(rgba(120,105,80,.07) 1px, transparent 1px); background-size: 3px 3px;
    font-family: 'IBM Plex Sans Condensed', sans-serif; color: #151412; position: relative; }
  .left { position: absolute; left: 70px; top: 120px; width: 560px; }
  .left img { width: 190px; height: 190px; margin-left: -12px; }
  h1 { font: 128px/1 'DM Serif Display', Georgia, serif; margin: 6px 0 0; letter-spacing: -1px; }
  h1 b { color: #C0392B; font-weight: 400; }
  h2 { font: 44px/1.1 'DM Serif Display', Georgia, serif; margin: 6px 0 22px; }
  p { font: 25px/1.4 'DM Serif Text', Georgia, serif; margin: 0 0 28px; color: #3d3a34; }
  .chips { display: flex; flex-wrap: wrap; gap: 10px; }
  .chip { border: 2px solid #151412; padding: 6px 14px; font: 700 17px 'IBM Plex Sans Condensed'; letter-spacing: .06em; text-transform: uppercase; }
  .chip.r { border-color: #C0392B; color: #C0392B; } .chip.b { border-color: #1F4E9C; color: #1F4E9C; }
  .shot { position: absolute; right: 60px; top: 70px; width: 880px; border: 3px solid #151412; box-shadow: 14px 14px 0 rgba(21,20,18,.14); background: #fff; }
  .shot img { display: block; width: 100%; }
  .tag { position: absolute; right: 60px; bottom: 50px; font: 600 16px 'IBM Plex Sans Condensed'; letter-spacing: .12em; text-transform: uppercase; color: #555048; }
  .bar { position: absolute; left: 0; top: 0; bottom: 0; width: 14px; background: #C0392B; }
</style></head><body>
<div class="bar"></div>
<div class="left">
  <img src="LOGO">
  <h1>x<b>V</b></h1>
  <h2>expected Viewership</h2>
  <p>Live, explainable match intelligence: every moment narrated for the viewer and fact-checked against the evidence.</p>
  <div class="chips"><span class="chip b">Microsoft Agent Framework</span><span class="chip b">Foundry Local</span><span class="chip r">Synthetic data</span></div>
</div>
<div class="shot"><img src="SHOT"></div>
<div class="tag">Inside the Game · Developer Hackathon</div>
</body></html>"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    shot = OUT / "_screen.png"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.goto(URL + "#live")
        page.wait_for_function("typeof S !== 'undefined' && S.live && document.getElementById('persona').options.length > 0", timeout=60000)
        page.evaluate("""() => { const f = document.getElementById('followp');
          const o = [...f.options].find(o => o.text.includes('Bramoni')); if (o) { f.value = o.value; f.onchange(); }
          document.getElementById('speed').value = '300'; }""")
        page.click("#go")
        time.sleep(8.6)  # ~ minute 41: the 1-2 goal pops up
        page.evaluate("() => { T.playing = false; const o = document.getElementById('overlay'); o.value = 'thirds'; o.onchange(); }")
        time.sleep(0.8)
        page.locator("#screen").screenshot(path=str(shot))
        card = CARD.replace("LOGO", (ROOT / "docs" / "assets" / "xv-mark.png").as_uri()).replace("SHOT", shot.as_uri())
        html = OUT / "_thumb.html"
        html.write_text(card, encoding="utf-8")
        page2 = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
        page2.goto(html.as_uri())
        page2.wait_for_timeout(1500)
        page2.screenshot(path=str(OUT / "xv-thumbnail.png"))
        browser.close()
    html.unlink()
    shot.unlink()
    print("saved", OUT / "xv-thumbnail.png")


if __name__ == "__main__":
    main()
