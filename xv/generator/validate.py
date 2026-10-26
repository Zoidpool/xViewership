"""Check that the synthetic matches look like real football.

Simulates matches in every league and compares per-match averages (both
teams combined) with broad ranges typical of European top flights. The
ranges are deliberately wide public ballparks, not a claim about any
specific league. A per-league table shows the leagues' different characters.

    python -m xv.generator.validate --matches 150     # per league
"""
from __future__ import annotations

import argparse
import random
from collections import Counter
from statistics import mean

from .engine import simulate_match
from .league import build_world

TARGETS = {
    "goals": (2.4, 3.2),
    "shots": (21, 28),
    "shots_on_target": (7, 10.5),
    "xg": (2.3, 3.1),
    "xg_per_shot": (0.09, 0.13),
    "passes": (800, 1050),
    "pass_accuracy_pct": (76, 85),
    "corners": (8.5, 11.5),
    "fouls": (19, 26),
    "yellow_cards": (3.0, 5.0),
    "red_cards": (0.05, 0.25),
    "offsides": (2.5, 5.0),
    "penalties": (0.15, 0.4),
    "substitutions": (7, 10),
    "crosses": (25, 50),
    "dribbles": (25, 50),
    "aerials": (50, 110),
    "home_win_pct": (40, 50),
    "draw_pct": (20, 30),
}


def match_metrics(events: list[dict]) -> dict:
    c = Counter()
    xg = 0.0
    for e in events:
        t = e["type"]
        if t == "shot":
            c["shots"] += 1
            xg += e["xg"]
            c["shots_on_target"] += e["outcome"] in ("goal", "saved")
            c["penalties"] += e.get("situation") == "penalty"
        elif t == "pass":
            c["passes"] += 1
            c["passes_ok"] += e["outcome"] == "complete"
            c["crosses"] += bool(e.get("cross"))
        elif t == "goal":
            c["goals"] += 1
        elif t == "card":
            c["yellow_cards" if e["card"] == "yellow" else "red_cards"] += 1
        elif t in ("corner", "foul", "offside", "substitution", "dribble", "aerial"):
            c[{"corner": "corners", "foul": "fouls", "offside": "offsides",
               "substitution": "substitutions", "dribble": "dribbles",
               "aerial": "aerials"}[t]] += 1
    score = events[-1]["score"]
    out = {k: c[k] for k in TARGETS if k in c or k in (
        "red_cards", "penalties", "goals", "offsides")}
    out.update({k: c[k] for k in ("goals", "shots", "shots_on_target", "passes", "corners", "fouls",
                                  "yellow_cards", "red_cards", "offsides", "penalties",
                                  "substitutions", "crosses", "dribbles", "aerials")})
    out.update({
        "xg": xg, "xg_per_shot": xg / c["shots"] if c["shots"] else 0,
        "pass_accuracy_pct": 100 * c["passes_ok"] / c["passes"] if c["passes"] else 0,
        "home_win_pct": 100.0 * (score["home"] > score["away"]),
        "draw_pct": 100.0 * (score["home"] == score["away"]),
        "over25_pct": 100.0 * (score["home"] + score["away"] > 2),
    })
    return out


def run(n_per_league: int, seed: int = 7) -> dict[str, dict[str, float]]:
    world = build_world()
    rng = random.Random(seed)
    per = {}
    for lid, lw in world.items():
        codes = list(lw["clubs"])
        rows = []
        for i in range(n_per_league):
            h, a = rng.sample(codes, 2)
            rows.append(match_metrics(simulate_match(lw["clubs"][h], lw["clubs"][a], f"V{i}",
                                                     seed * 10_000 + i, league=lw["league"])))
        per[lid] = {k: mean(r[k] for r in rows) for k in rows[0]}
    per["all"] = {k: mean(per[l][k] for l in world) for k in per[next(iter(world))]}
    return per


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=150, help="per league")
    args = ap.parse_args()
    per = run(args.matches)
    avg = per["all"]
    bad = 0
    print(f"{'metric':<20}{'all':>9}  target    " + "".join(f"{l[:10]:>11}" for l in per if l != "all"))
    for k in list(TARGETS) + ["over25_pct"]:
        lo, hi = TARGETS.get(k, (None, None))
        ok = lo is None or lo <= avg[k] <= hi
        bad += not ok
        rng_txt = f"{lo:g}-{hi:g}" if lo is not None else ""
        print(f"{k:<20}{avg[k]:>9.2f}  {rng_txt:<9} {'ok ' if ok else 'OUT'}"
              + "".join(f"{per[l][k]:>11.2f}" for l in per if l != "all"))
    print(f"\n{len(TARGETS) - bad}/{len(TARGETS)} metrics in range "
          f"({args.matches} matches per league, {args.matches * (len(per) - 1)} total)")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
