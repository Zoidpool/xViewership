"""Build the analysis bundle the app reads (locally and on GitHub Pages).

    python -m xv.build            # data/ -> docs/data/*.json

Files:
  meta.json      leagues, stat catalogues, roles, archetypes, checks
  players.json   every player: per-90 values, percentiles, archetype, rating factors
  teams.json     every club: season values, ranks, table position, match list
  insights.json  league observations, market gaps, model-vs-market evaluation
  fixtures.json  the next round in every league with model and market probabilities
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from .analytics.model import fit_ratings, market_probs, outcome_probs, walk_forward
from .analytics.profiles import ARCHETYPES, ROLE_NAMES, ROLE_ORDER, ROLE_STATS, build_profiles
from .analytics.stats import CATALOG, aggregate
from .analytics.teams import TEAM_STATS, league_observations, team_tables
from .analytics.zones import ASSIST_ZONES

ROOT = Path(__file__).resolve().parent.parent


def build(data_dir: Path, out_dir: Path) -> dict:
    agg = aggregate(data_dir)
    prof = build_profiles(agg)
    tt = team_tables(agg)
    world, index = agg["world"], agg["index"]
    clubs_by_league = {lg["id"]: [c["code"] for c in lg["clubs"]] for lg in world["leagues"]}
    team_xg = {m.match_id: {m.home: m.team[m.home].get("xg", 0), m.away: m.team[m.away].get("xg", 0)}
               for m in agg["matches"]}
    wf = walk_forward(index, team_xg, clubs_by_league)
    obs = league_observations(agg, wf)

    # current ratings and the next round's probabilities
    ratings, fixtures = {}, []
    for lg in world["leagues"]:
        rows = [{"home": m.home, "away": m.away, "hg": m.hg, "ag": m.ag,
                 "hxg": m.team[m.home].get("xg", 0), "axg": m.team[m.away].get("xg", 0)}
                for m in agg["matches"] if m.league == lg["id"]]
        rt = fit_ratings(lg["id"], rows, clubs_by_league[lg["id"]])
        ratings[lg["id"]] = rt.to_dict()
        for m in index:
            if m["league"] == lg["id"] and "home_goals" not in m:
                lh, la = rt.rates(m["home"], m["away"])
                fixtures.append({**{k: m[k] for k in ("match_id", "league", "round", "home", "away")},
                                 "rates": {"home": round(lh, 3), "away": round(la, 3)},
                                 "model": outcome_probs(lh, la), "market": market_probs(m["market"]),
                                 "odds": m["market"]})

    # model vs market, all leagues together and per league
    def summary(rows):
        if not rows:
            return None
        return {"n": len(rows),
                "market_log_loss": round(mean(-math.log(r["market"][r["result"]]) for r in rows), 4),
                "model_log_loss": round(mean(-math.log(r["model"][r["result"]]) for r in rows), 4),
                "model_top_pick_right": round(100 * mean(max(("home", "draw", "away"), key=lambda o: r["model"][o]) == r["result"] for r in rows), 1),
                "market_top_pick_right": round(100 * mean(max(("home", "draw", "away"), key=lambda o: r["market"][o]) == r["result"] for r in rows), 1)}
    evaluation = {"all": summary(wf), **{lid: summary([r for r in wf if r["league"] == lid])
                                         for lid in clubs_by_league}}

    players = []
    for r in prof["players"]:
        players.append({k: v for k, v in r.items() if k != "ratings"} |
                       {"ratings": [{"round": m["round"], "rating": m["rating"], "minutes": m["minutes"]}
                                    for m in sorted(r["ratings"], key=lambda m: m["round"])]})
    meta = {
        "app": "xV", "synthetic": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "leagues": [{k: v for k, v in lg.items() if k not in ("clubs", "fixtures", "home_adv", "tempo", "open",
                                                               "fouls", "cards", "strength")}
                    | {"rounds_played": prof["rounds_played"].get(lg["id"], 0),
                       "clubs": clubs_by_league[lg["id"]]}
                    for lg in world["leagues"]],
        "catalog": {k: {"label": v[0], "category": v[1], "kind": v[2], "higher_better": v[3]}
                    for k, v in CATALOG.items()},
        "team_stats": {k: {"label": v[0], "higher_better": v[1]} for k, v in TEAM_STATS.items()},
        "roles": [{"id": r, "name": ROLE_NAMES[r], "stats": ROLE_STATS[r],
                   "archetypes": [{"id": a, "name": n, "desc": d, "weights": w} for a, n, d, w in ARCHETYPES[r]]}
                  for r in ROLE_ORDER],
        "averages": prof["averages"], "pool_sizes": prof["pool_sizes"],
        "archetype_check": prof["archetype_check"], "rating_shift": prof["rating_shift"],
        "minutes_rule": "60% of the minutes the player's team could have played",
        "assist_zones": [{"name": n, "x0": a, "x1": b, "y0": c, "y1": d} for n, a, b, c, d in ASSIST_ZONES],
        "ratings_model": ratings,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    dump = lambda name, obj: (out_dir / name).write_text(
        json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    dump("meta.json", meta)
    dump("players.json", players)
    dump("teams.json", {"teams": tt["teams"], "tables": tt["tables"], "league_zones": tt["league_zones"]})
    dump("insights.json", {**obs, "evaluation": evaluation})
    dump("fixtures.json", fixtures)
    return {"players": len(players), "teams": len(tt["teams"]), "fixtures": len(fixtures),
            "evaluation": evaluation["all"], "archetypes": prof["archetype_check"]["pct"],
            "sizes_kb": {p.name: round(p.stat().st_size / 1024) for p in out_dir.glob("*.json")}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="docs/data")
    args = ap.parse_args()
    info = build(Path(args.data), Path(args.out))
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
