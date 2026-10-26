"""Record the xV demo video: a scripted tour of every tab with on-screen captions.

    python tools/record_demo.py [url]      # default http://127.0.0.1:5066/  -> video/xv-demo.webm (+ .mp4)

Needs Playwright (pip install playwright; playwright install chromium). Runs in real time (~1:50).
"""
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5066/"
OUT = Path(__file__).resolve().parent.parent / "video"
W, H = 1440, 900

CAPTION_JS = """
(() => {
  if (document.getElementById('demo-cap')) return;
  const s = document.createElement('style');
  s.textContent = `#demo-cap{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:1100px;z-index:9999;
    background:#151412;color:#F2EEE5;padding:12px 22px;border-left:8px solid #C0392B;font:20px/1.35 'IBM Plex Sans Condensed',sans-serif;
    box-shadow:0 6px 24px rgba(0,0,0,.25);transition:opacity .4s}
    #demo-cap b{color:#E8C55A} #demo-cap.hide{opacity:0}
    #demo-card{position:fixed;inset:0;z-index:10000;background:#F2EEE5;display:flex;flex-direction:column;align-items:center;justify-content:center;
    gap:14px;transition:opacity .6s;font-family:'IBM Plex Sans Condensed',sans-serif;color:#151412;text-align:center}
    #demo-card img{width:230px;height:230px} #demo-card h1{font:64px 'DM Serif Display',Georgia,serif;margin:0}
    #demo-card h1 b{color:#C0392B} #demo-card p{font:22px/1.4 'DM Serif Text',Georgia,serif;margin:0;max-width:900px}
    #demo-card .s{font:600 15px 'IBM Plex Sans Condensed';letter-spacing:.12em;text-transform:uppercase;color:#555048}`;
  document.head.appendChild(s);
  const d = document.createElement('div'); d.id = 'demo-cap'; d.className = 'hide'; document.body.appendChild(d);
})();
"""


def cap(page, html):
    page.evaluate("h => { const d = document.getElementById('demo-cap'); d.innerHTML = h; d.classList.toggle('hide', !h); }", html)


def card(page, html):
    page.evaluate("""h => { let c = document.getElementById('demo-card');
      if (!c) { c = document.createElement('div'); c.id = 'demo-card'; document.body.appendChild(c); }
      c.innerHTML = h; c.style.opacity = 1; c.style.display = 'flex'; }""", html)


def uncard(page):
    page.evaluate("() => { const c = document.getElementById('demo-card'); if (c) { c.style.opacity = 0; setTimeout(() => c.style.display = 'none', 650); } }")


def scroll_to(page, selector, offset=-70):
    page.evaluate("""([s, o]) => { const el = document.querySelector(s); if (el)
      window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY + o, behavior: 'smooth' }); }""", [selector, offset])


def tab(page, view):
    page.evaluate("v => { location.hash = v; }", view)
    time.sleep(0.6)
    page.evaluate("() => window.scrollTo({ top: 0 })")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                                  record_video_dir=str(OUT / "raw"), record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        page.goto(URL + "#live")
        page.wait_for_function("typeof S !== 'undefined' && S.live && document.getElementById('persona').options.length > 0",
                               timeout=60000)
        page.evaluate(CAPTION_JS)
        time.sleep(1.0)

        # 1. title card
        card(page, """<img src="assets/xv-mark.png" alt=""><h1>x<b>V</b> · expected Viewership</h1>
          <p>Explainable match intelligence from a stream of synthetic football events: live, narrated, personalised, and every claim backed by evidence.</p>
          <div class="s">Microsoft Agent Framework · Foundry Local · all data synthetic</div>""")
        time.sleep(5)
        uncard(page)

        # 2. live match
        page.evaluate("""() => { const f = document.getElementById('followp');
          const o = [...f.options].find(o => o.text.includes('Bramoni')); if (o) { f.value = o.value; f.onchange(); }
          document.getElementById('speed').value = '180'; document.getElementById('overlay').value = 'none'; }""")
        cap(page, "<b>Live match.</b> Synthetic events flow through an Agent Framework workflow: ingest → interpret → forecast → explain. 22 players tracked every second.")
        page.click("#go")
        scroll_to(page, "#screen", -150)
        time.sleep(6)
        for mode, text, secs in (
            ("thirds", "<b>Thirds &amp; attacking lanes</b>, each team's left / centre / right from its own direction of attack.", 4.5),
            ("heatteam", "<b>Heatmaps</b> for either team or both, filtered to the whole match, one half or the last 15 minutes.", 4),
            ("passes", "<b>Pass map</b>: completed passes solid, lost passes dashed.", 3.5),
            ("avg", "<b>Average positions</b>, so you can see the shape each side really played.", 3.5),
        ):
            page.evaluate("m => { const o = document.getElementById('overlay'); o.value = m; o.onchange(); }", mode)
            cap(page, text)
            time.sleep(secs)
        page.evaluate("() => { const o = document.getElementById('overlay'); o.value = 'none'; o.onchange(); }")
        cap(page, "<b>Insights pop up as they happen</b>, then fade: narrated for a casual fan or an analyst, in six languages, for a neutral or a supporter.")
        time.sleep(4)
        scroll_to(page, "#ltabs", -330)
        cap(page, "<b>Win probability</b> re-priced after every event (score, clock, red cards, the flow of chances), against the market's pre-match line.")
        time.sleep(5)
        page.click("#ltabs [data-tab=zones]")
        cap(page, "<b>Zones</b>: where passes are played, entries through the lanes and half-spaces, territory by square.")
        time.sleep(4.5)
        page.click("#ltabs [data-tab=log]")
        scroll_to(page, "#ltabs", -10)
        cap(page, "<b>Insights log</b>: every card shows <b>why</b> and <b>in depth</b> season context. Written on-device by a Foundry Local agent; a fact-checker rejects any number not in the evidence.")
        time.sleep(6)

        # 3. players
        pid = page.evaluate("""() => { const p = S.players.filter(p => p.eligible && p.role === 'ST')
          .sort((a, b) => Object.values(b.pct).filter(v => v >= 99).length - Object.values(a.pct).filter(v => v >= 99).length)[0];
          openPlayer(p.id); return p.name; }""")
        page.evaluate("() => window.scrollTo({ top: 0 })")
        cap(page, f"<b>Players.</b> 960 fictional players, 55+ stats per 90, percentiles within their role, archetypes, and the factors behind every rating ({pid}).")
        time.sleep(4.5)
        scroll_to(page, "#radarP", -120)
        cap(page, "<b>Radar</b> with any stats you pick, plus <b>season heatmaps</b> from synthetic tracking.")
        time.sleep(4)
        scroll_to(page, "#ph-heat", -110)
        time.sleep(2)
        scroll_to(page, ".pct.head", -20)
        cap(page, "<b>Every stat</b> against the role group: value, percentile, group average. <b>Gold ★ = top 1%.</b>")
        time.sleep(4.5)

        # 4. compare + scatter
        tab(page, "compare")
        cap(page, "<b>Compare</b> any two players or teams, across leagues, each measured against their own role.")
        time.sleep(4.5)
        tab(page, "scatter")
        page.evaluate("""() => { const r = document.getElementById('s-role'); r.value = 'all';
          document.getElementById('s-x').value = 'npxg'; document.getElementById('s-y').value = 'xa'; renderScatter(); }""")
        scroll_to(page, "#scatterChart", -150)
        cap(page, "<b>Scatter</b> any stat against any stat, for one role or all players, with outliers labelled.")
        time.sleep(4.5)

        # 5. rankings
        tab(page, "rankings")
        page.evaluate("() => { RK.filters.push({ k: 'goals', min: '0.3', max: '' }); renderRankFilters(); renderRankings(); }")
        cap(page, "<b>Rankings</b> by role with grouped columns, filters on any stat range, and percentile heat.")
        time.sleep(3)
        scroll_to(page, "#r-body", -40)
        time.sleep(4)

        # 6. teams
        tab(page, "teams")
        cap(page, "<b>Teams.</b> Tables with expected points, team profiles with league ranks.")
        time.sleep(3.5)
        scroll_to(page, "#t-zones", -20)
        cap(page, "<b>Team zones</b>: pass bands against the league, lanes and half-spaces, territory, and assist areas for and against.")
        time.sleep(4.5)
        scroll_to(page, "#t-all", -110)
        cap(page, "<b>All 40 clubs side by side</b>, across four leagues with different personalities.")
        time.sleep(3.5)
        scroll_to(page, "#t-take", -70)
        cap(page, "<b>Takeaways</b> found in the data: who presses hardest, who rides their luck, who lives in the half-spaces.")
        time.sleep(4)

        # 7. leagues
        tab(page, "leagues")
        cap(page, "<b>Leagues &amp; probabilities.</b> Which league is most likely to see what, with honest 90% ranges.")
        time.sleep(4)
        scroll_to(page, "#sec-gaps", -10)
        cap(page, "Where results ran away from the market's prices, and how xV's model compares with the market.")
        time.sleep(4)
        scroll_to(page, "#sec-eval", -10)
        cap(page, "<b>The market still beats our model, and we say so.</b> Probability explains the game; it is not betting advice.")
        time.sleep(4.5)

        # 8. end card
        cap(page, "")
        card(page, """<img src="assets/xv-mark.png" alt=""><h1>x<b>V</b></h1>
          <p>Try it: <b>zoidpool.github.io/xViewership</b><br>Code: github.com/Zoidpool/xViewership</p>
          <div class="s">Four fictional leagues · 960 players · every number synthetic · built on Microsoft Agent Framework and Foundry Local</div>""")
        time.sleep(4.5)
        video = page.video.path()
        ctx.close()
        browser.close()
    final = OUT / "xv-demo.webm"
    shutil.move(video, final)
    shutil.rmtree(OUT / "raw", ignore_errors=True)
    print("saved", final)


if __name__ == "__main__":
    main()
