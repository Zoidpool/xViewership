"""Build the synthetic world's season and write it to disk.

Output (under --out, default data/):
  world.json             leagues, clubs, squads (with hidden design styles), fixtures
  matches/<id>.jsonl     one event per line, in order
  season_index.json      every fixture: result (if played) and synthetic market prices

Every league plays all but its last round; the last round is left for live
streaming. Market prices come from a "sharp" synthetic bookmaker that knows
the clubs' true strengths (fitted on the simulated goals), adds noise, then a
margin (power method for 1X2, proportional for two-way markets).

    python -m xv.generator.season
"""
from __future__ import annotations

import argparse
import json
import math
import random
import zlib
from pathlib import Path

from .engine import simulate_match
from .league import build_world, round_robin

MARGIN_1X2 = 0.055
MARGIN_2WAY = 0.05


def match_id(league: str, round_no: int, home: str, away: str) -> str:
    return f"{league[:3].upper()}-R{round_no:02d}-{home}-{away}"


def write_events(path: Path, events: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, separators=(",", ":")) + "\n")


# ---------- the synthetic bookmaker ----------
def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def score_grid(lh: float, la: float, n: int = 11) -> list[list[float]]:
    ph = [poisson_pmf(i, lh) for i in range(n)]
    pa = [poisson_pmf(j, la) for j in range(n)]
    return [[ph[i] * pa[j] for j in range(n)] for i in range(n)]


def markets_from_grid(g: list[list[float]]) -> dict[str, float]:
    n = len(g)
    home = sum(g[i][j] for i in range(n) for j in range(n) if i > j)
    draw = sum(g[i][i] for i in range(n))
    away = sum(g[i][j] for i in range(n) for j in range(n) if i < j)
    over = sum(g[i][j] for i in range(n) for j in range(n) if i + j > 2)
    btts = sum(g[i][j] for i in range(1, n) for j in range(1, n))
    tot = home + draw + away
    return {"home": home / tot, "draw": draw / tot, "away": away / tot,
            "over25": over / tot, "btts": btts / tot}


def _power_margin(p: list[float], margin: float) -> list[float]:
    """Implied probabilities q_i = p_i^c with sum q = 1 + margin (c < 1)."""
    lo, hi = 0.5, 1.0
    for _ in range(60):
        c = (lo + hi) / 2
        if sum(x ** c for x in p) > 1 + margin:
            lo = c
        else:
            hi = c
    return [x ** c for x in p]


def price(p: dict[str, float]) -> dict[str, list[float]]:
    q = _power_margin([p["home"], p["draw"], p["away"]], MARGIN_1X2)
    two = lambda a: [round(1 / (a * (1 + MARGIN_2WAY)), 2), round(1 / ((1 - a) * (1 + MARGIN_2WAY)), 2)]
    return {"1x2": [round(1 / x, 2) for x in q], "ou25": two(p["over25"]), "btts": two(p["btts"])}


def fit_strength_model(rows: list[tuple[float, int]]) -> tuple[float, float]:
    """Poisson regression log(goals) = a + b*d by Newton's method."""
    a, b = math.log(max(0.5, sum(g for _, g in rows) / len(rows))), 0.0
    for _ in range(30):
        ga = gb = haa = hab = hbb = 0.0
        for d, g in rows:
            lam = math.exp(a + b * d)
            ga += g - lam
            gb += (g - lam) * d
            haa += lam
            hab += lam * d
            hbb += lam * d * d
        det = haa * hbb - hab * hab
        a += (hbb * ga - hab * gb) / det
        b += (haa * gb - hab * ga) / det
    return a, b


def build_season(out: Path, seed: int = 2026) -> dict:
    world = build_world(seed)
    out.mkdir(parents=True, exist_ok=True)
    (out / "matches").mkdir(exist_ok=True)
    rng = random.Random(seed + 1)
    index, fixtures_out, played = [], {}, 0
    for lid, lw in world.items():
        lg, clubs = lw["league"], lw["clubs"]
        rounds = round_robin(list(clubs), seed)
        fixtures_out[lid] = [[{"round": r, "home": h, "away": a, "match_id": match_id(lid, r, h, a)}
                              for h, a in pairs] for r, pairs in enumerate(rounds, start=1)]
        rows_played = []
        goal_rows: list[tuple[float, int]] = []
        for r, pairs in enumerate(rounds, start=1):
            for i, (h, a) in enumerate(pairs):
                row = {"match_id": match_id(lid, r, h, a), "league": lid, "round": r,
                       "home": h, "away": a}
                if r < len(rounds):
                    ev = simulate_match(clubs[h], clubs[a], row["match_id"],
                                        seed * 1000 + zlib.crc32(f"{lid}-{r}-{i}".encode()) % 100_000, r, lg)
                    write_events(out / "matches" / f"{row['match_id']}.jsonl", ev)
                    sc = ev[-1]["score"]
                    row.update(home_goals=sc["home"], away_goals=sc["away"])
                    d = (clubs[h].strength + lg["home_adv"] - clubs[a].strength) / 10
                    goal_rows += [(d, sc["home"]), (-d, sc["away"])]
                    played += 1
                rows_played.append(row)
        a_, b_ = fit_strength_model(goal_rows)
        for row in rows_played:
            d = (clubs[row["home"]].strength + lg["home_adv"] - clubs[row["away"]].strength) / 10
            lh = math.exp(a_ + b_ * d) * math.exp(rng.gauss(0, 0.06))
            la = math.exp(a_ - b_ * d) * math.exp(rng.gauss(0, 0.06))
            row["market"] = price(markets_from_grid(score_grid(lh, la)))
        index += rows_played

    doc = {
        "synthetic": True, "seed": seed,
        "leagues": [{**lw["league"], "clubs": [c.to_dict() for c in lw["clubs"].values()],
                     "fixtures": fixtures_out[lid]} for lid, lw in world.items()],
    }
    (out / "world.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    (out / "season_index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    return {"leagues": len(world), "played": played, "fixtures": len(index)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="data")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    info = build_season(Path(args.out), args.seed)
    print(f"World built: {info['leagues']} leagues, {info['played']} matches played, "
          f"{info['fixtures'] - info['played']} left for live -> {args.out}/")


if __name__ == "__main__":
    main()
