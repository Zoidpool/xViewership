"""xV: local server for the app and the live stream.

    python -m xv.server      ->  http://127.0.0.1:5065

Serves docs/ (the same files GitHub Pages serves: the app and its data
bundle) plus two live routes. /api/meta tells the page a live server is
there; /stream replays the featured synthetic fixture in accelerated real
time through the workflow and narrates insights for each viewer's persona,
language and favourite team.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from flask import Flask, Response, abort, request, send_from_directory

from .agents.narrator import LANGUAGES, PERSONAS, Narrator, build_client, relevant
from .live import BUNDLE, DATA, ROOT, dramatic_seed, featured_fixture, live_events, tracking_for
from .workflow import MatchPipeline

DOCS = ROOT / "docs"
app = Flask(__name__, static_folder=None)
_fixture = featured_fixture(BUNDLE)
_seed = int(os.getenv("XV_SEED") or dramatic_seed(_fixture))
_teams = json.loads((BUNDLE / "teams.json").read_text(encoding="utf-8"))["teams"]
NARRATOR = Narrator(build_client(), {c: t["name"] for c, t in _teams.items()})


@app.get("/")
def index():
    return send_from_directory(DOCS, "index.html")


@app.get("/<path:path>")
def static_files(path: str):
    if path.startswith("api/") or ".." in path:
        abort(404)
    return send_from_directory(DOCS, path)


@app.get("/api/meta")
def meta():
    return {"live": True, "fixture": _fixture, "seed": _seed,
            "personas": [[k, p.label] for k, p in PERSONAS.items()],
            "persona_min": {k: p.min_importance for k, p in PERSONAS.items()},
            "languages": list(LANGUAGES.items()), "narration": NARRATOR.mode}


def _sse(kind: str, payload: dict) -> str:
    return f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/stream")
def stream():
    persona = PERSONAS.get(request.args.get("persona", "fan"), PERSONAS["fan"])
    lang = request.args.get("lang", "en")
    fav = request.args.get("team") or None
    speed = max(1.0, min(600.0, float(request.args.get("speed", 45))))

    def gen():
        loop = asyncio.new_event_loop()
        try:
            pipe = MatchPipeline(DATA, _fixture, BUNDLE)
            events = live_events(_fixture, _seed)
            track, acts = tracking_for(_fixture, events)
            frames, fi, ai = track["frames"], 0, 0
            yield _sse("hello", {"fixture": _fixture, "narration": NARRATOR.mode,
                                 "track": {k: v for k, v in track.items() if k != "frames"}})
            start, offset, last = time.monotonic(), 0.0, 0.0
            for ev in events:
                if ev["type"] == "period_start" and ev["period"] == 2:
                    offset = last + 5
                at = ev["t"] + offset
                last = at
                wait = at / speed - (time.monotonic() - start)
                if wait > 0:
                    time.sleep(min(wait, 2.0))
                # positions and on-ball actions up to this moment
                batch = []
                while fi < len(frames) and (frames[fi][0], frames[fi][1]) <= (ev["period"], ev["t"]):
                    batch.append(frames[fi] + [frames[fi][1] + (offset if frames[fi][0] == 2 else 0)])
                    fi += 1
                new_acts = []
                while ai < len(acts) and (acts[ai][0], acts[ai][1]) <= (ev["period"], ev["t"]):
                    new_acts.append(acts[ai])
                    ai += 1
                if batch or new_acts:
                    yield _sse("frames", {"frames": batch, "actions": new_acts})
                out = loop.run_until_complete(pipe.push(ev))
                if not out:
                    continue
                if out.snapshot:
                    yield _sse("stats", out.snapshot)
                for ins in out.insights:
                    if not relevant(ins, persona, fav):
                        continue
                    line = loop.run_until_complete(NARRATOR.narrate(ins, persona, lang, fav))
                    yield _sse("insight", {**ins.to_dict(), "line": line})
            yield _sse("done", {"score": pipe.state.score(), "rejected_llm_lines": NARRATOR.rejections})
        finally:
            loop.close()

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def main() -> None:
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", 5065)), threaded=True)


if __name__ == "__main__":
    main()
