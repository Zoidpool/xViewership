"""Smoke test for Foundry narration.

Runs the next fixture through the pipeline, picks a spread of insights and
asks the Foundry agent for every persona x language. Prints each line, its
latency, and every grounding rejection (with the rejected text) so the prompt
can be tuned.

    python -m xv.check_foundry                 # en, ro, es
    python -m xv.check_foundry --langs en --max 3
"""
from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from .agents.narrator import PERSONAS, Narrator, build_client
from .live import BUNDLE, DATA, dramatic_seed, featured_fixture, live_events
from .workflow import MatchPipeline


async def run(args) -> int:
    client = build_client()
    if client is None:
        print("Not configured: set FOUNDRY_LOCAL_MODEL, or FOUNDRY_PROJECT_ENDPOINT + FOUNDRY_MODEL (env or .env).")
        return 2
    fx = featured_fixture(BUNDLE)
    pipe = MatchPipeline(DATA, fx, BUNDLE)
    found = []
    for ev in live_events(fx, dramatic_seed(fx)):
        out = await pipe.push(ev)
        found.extend(out.insights)
    # one of each kind first, most important first, then fill up
    by_kind: dict[str, list] = {}
    for ins in sorted(found, key=lambda i: -i.importance):
        by_kind.setdefault(ins.kind, []).append(ins)
    picked = [v[0] for v in by_kind.values()][: args.max]

    narrator = Narrator(client, {c: v["name"] for c, v in pipe.ctx.clubs.items()})
    print(f"backend: {narrator.mode}")
    calls = ok = 0
    latencies = []
    for ins in picked:
        print(f"\n== {ins.clock} {ins.kind}: {ins.title}")
        for pkey in PERSONAS:
            for lang in args.langs:
                t0 = time.perf_counter()
                line = await narrator.narrate(ins, PERSONAS[pkey], lang)
                dt = time.perf_counter() - t0
                calls += 1
                latencies.append(dt)
                ok += line["source"] != "template"
                tag = "OK " if line["source"] != "template" else "REJ" if not line["grounded"] \
                    else "ERR"
                print(f"  [{tag}] {pkey:<7} {lang} {dt:4.1f}s  {line['text']}")
                if not line["grounded"]:
                    print(f"        rejected ({'; '.join(line['rejected_reasons'])}): "
                          f"{line['rejected_text']}")
                if line.get("error"):
                    print(f"        error: {line['error']}: {line.get('error_detail', '')}")
    latencies.sort()
    print(f"\n{ok}/{calls} Foundry lines accepted, {narrator.rejections} rejected by the "
          f"grounding check. Median latency {latencies[len(latencies) // 2]:.1f}s.")
    return 0 if ok == calls else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--langs", nargs="+", default=["en", "ro", "es"])
    ap.add_argument("--max", type=int, default=6, help="insights to test")
    ap.add_argument("--seed", type=int, default=99)
    raise SystemExit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
