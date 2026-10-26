"""Run the featured synthetic match through the pipeline in the terminal.

    python -m xv.demo --why                  # featured fixture, template narration
    python -m xv.demo --persona fan --lang ro --seed auto
(set FOUNDRY_LOCAL_MODEL, or a Foundry project, for model narration)
"""
from __future__ import annotations

import argparse
import asyncio

from .agents.narrator import PERSONAS, Narrator, build_client, relevant
from .live import BUNDLE, DATA, dramatic_seed, featured_fixture, live_events
from .workflow import MatchPipeline


async def run(args) -> None:
    fx = featured_fixture(BUNDLE, args.league, args.match)
    seed = dramatic_seed(fx) if args.seed == "auto" else int(args.seed)
    pipe = MatchPipeline(DATA, fx, BUNDLE)
    narrator = Narrator(build_client(), {c: v["name"] for c, v in pipe.ctx.clubs.items()})
    persona = PERSONAS[args.persona]
    print(f"[{fx['match_id']} seed {seed} | {narrator.mode} narration | {persona.key} | {args.lang}]")
    shown = 0
    for ev in live_events(fx, seed):
        out = await pipe.push(ev)
        if not out:
            continue
        for ins in out.insights:
            if not relevant(ins, persona, args.favourite):
                continue
            line = await narrator.narrate(ins, persona, args.lang, args.favourite)
            shown += 1
            print(f"{ins.clock:>7} [{ins.kind:<11} {ins.importance:.2f}] {line['text']}")
            if args.why:
                for w in ins.why:
                    print(f"{'':>9}- because {w['text']}")
    snap = pipe.state.snapshot()
    probs = pipe.forecast.model.history
    print(f"\n{shown} cards. Final {snap['score']}. {len(probs)} probability updates. "
          f"Ingest dropped {pipe.ingest.dropped}. LLM lines rejected: {narrator.rejections}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="meridian")
    ap.add_argument("--match", default=None)
    ap.add_argument("--persona", default="analyst", choices=list(PERSONAS))
    ap.add_argument("--lang", default="en")
    ap.add_argument("--favourite", default=None, help="club code")
    ap.add_argument("--seed", default="99", help="number or 'auto' (a dramatic match)")
    ap.add_argument("--why", action="store_true")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
