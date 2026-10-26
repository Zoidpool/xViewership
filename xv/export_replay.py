"""Pre-render the featured live match for static hosting (GitHub Pages).

Runs the featured fixture through the same workflow as the live server,
narrates every insight for every persona x language x supporter view with the
configured backend (Foundry Local by default), and writes docs/replay.json:
a timeline of stats snapshots (with live probabilities and player lines) and
narrated insights.

    python -m xv.export_replay                      # all six languages
    python -m xv.export_replay --langs en ro --templates

Narrations are cached in docs/.narration_cache.json (keyed on the insight's
facts, so a changed insight is narrated again).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .agents.narrator import LANGUAGES, PERSONAS, Narrator, build_client, relevant
from .live import BUNDLE, DATA, ROOT, dramatic_seed, featured_fixture, live_events, tracking_for
from .workflow import MatchPipeline


def _fp(ins) -> str:
    return hashlib.sha1(json.dumps([ins.title, ins.facts, ins.why, ins.depth], sort_keys=True).encode()).hexdigest()[:12]


async def run(args) -> None:
    out = Path(args.out)
    cache_path = out / ".narration_cache.json"
    disk = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    fx = featured_fixture(BUNDLE)
    seed = dramatic_seed(fx) if args.seed == "auto" else int(args.seed)
    pipe = MatchPipeline(DATA, fx, BUNDLE)
    clubs = {c: v["name"] for c, v in pipe.ctx.clubs.items()}
    narrator = Narrator(None if args.templates else build_client(), clubs)
    print(f"{fx['match_id']} seed {seed}, narration backend: {narrator.mode}")

    events = live_events(fx, seed)
    track, acts = tracking_for(fx, events)
    timeline, offset, last = [], 0.0, 0.0
    for ev in events:
        if ev["type"] == "period_start" and ev["period"] == 2:
            offset = last + 5
        at = round(ev["t"] + offset, 1)
        last = at
        res = await pipe.push(ev)
        if not res:
            continue
        if res.snapshot:
            timeline.append({"at": at, "type": "stats", "data": res.snapshot})
        for ins in res.insights:
            timeline.append({"at": at, "type": "insight", "data": ins.to_dict(), "lines": {}, "_ins": ins})

    jobs = []
    for item in timeline:
        if item["type"] != "insight":
            continue
        ins = item["_ins"]
        favs = [""] + ([fx["home"], fx["away"]] if ins.team else [])
        for persona in PERSONAS.values():
            for lang in args.langs:
                for fav in favs:
                    if relevant(ins, persona, fav or None):
                        jobs.append((item, ins, persona, lang, fav))
    print(f"{len(timeline)} timeline items, {len(jobs)} narrations")

    t0, done = time.perf_counter(), 0
    for item, ins, persona, lang, fav in jobs:
        key = f"{persona.key}|{lang}|{fav}"
        ck = f"{narrator.mode}|{_fp(ins)}|{key}"
        line = disk.get(ck)
        if line is None:
            line = await narrator.narrate(ins, persona, lang, fav or None)
            if not line.get("error"):
                disk[ck] = line
            done += 1
            if done % 20 == 0:
                cache_path.write_text(json.dumps(disk, ensure_ascii=False), encoding="utf-8")
                print(f"  {done} new lines, {(time.perf_counter() - t0) / done:.1f}s each")
        item["lines"][key] = line
    cache_path.write_text(json.dumps(disk, ensure_ascii=False), encoding="utf-8")

    lines = [l for it in timeline if it["type"] == "insight" for l in it["lines"].values()]
    accepted = sum(l["source"] != "template" for l in lines)
    rejected = sum(not l["grounded"] for l in lines)
    for it in timeline:
        it.pop("_ins", None)
    meta = {
        "live": False, "fixture": fx, "seed": seed,
        "personas": [[k, p.label] for k, p in PERSONAS.items()],
        "persona_min": {k: p.min_importance for k, p in PERSONAS.items()},
        "languages": [[k, LANGUAGES[k]] for k in args.langs], "narration": narrator.mode,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stats": {"lines": len(lines), "llm_accepted": accepted, "grounding_rejected": rejected},
    }
    meta["half_time_offset"] = offset  # replay seconds where the second half starts
    (out / "replay.json").write_text(json.dumps({"meta": meta, "timeline": timeline, "track": track,
                                                 "actions": acts},
                                                ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"wrote {out}/replay.json: {len(lines)} lines, {accepted} from the model, "
          f"{rejected} rejected by the fact-checker (template shown instead)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs"))
    ap.add_argument("--langs", nargs="+", default=list(LANGUAGES))
    ap.add_argument("--seed", default="auto")
    ap.add_argument("--templates", action="store_true", help="skip the model (quick test)")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
